from __future__ import annotations

from base64 import b64decode
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from html import escape
from io import BytesIO
import json
from pathlib import Path
import re
import zipfile
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image, ImageDraw

from src.db.models import (
    AgentRun,
    Asset,
    BrandKit,
    BrandKitVersion,
    DetailPageVersion,
    FactEvidence,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductFact,
    ProductProject,
)


# Small valid JPEGs are sufficient private identity references for the domain
# contract. The provider itself is replaced in these graph tests.
JPEG = b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQL/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/Aaf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/Aaf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Aqf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/If/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//Z"
)


def _build_identity_reference() -> bytes:
    image = Image.new("RGB", (512, 512), color=(232, 236, 240))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((96, 176, 416, 336), radius=48, fill=(132, 142, 152))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


# The durable fake provider produces this product silhouette in a fresh PNG
# composition. A realistic 512px seller-owned reference lets the real quality
# and identity validators run instead of bypassing them in the E2E.
JPEG = _build_identity_reference()


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


@pytest.fixture
def lg5_runtime(monkeypatch):
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _create_run(client, headers, db_session, tmp_path, *, mode: str = "mock") -> AgentRun:
    response = client.post("/api/agent-runs", headers=headers, json={
        "product_name": "LG-5 image workflow pillow",
        "description": "Rated input: DC 5V 2A. Size: 40 x 17 x 15cm.",
    })
    assert response.status_code == 201, response.text
    run = db_session.query(AgentRun).filter(AgentRun.id == response.json()["id"]).one()
    run.mode = mode
    fact = ProductFact(
        project_id=run.project_id,
        fact_text="Rated input: DC 5V 2A",
        source_text="DC 5V 2A",
        verification_status="seller_confirmed",
        needs_review=False,
        field_key="rated_input",
        fact_category="electrical",
        normalized_value="DC 5V 2A",
        scope="product",
    )
    assets: list[Asset] = []
    for index, role in enumerate(("product_main", "product_detail"), start=1):
        file_path = tmp_path / f"lg5-{role}.jpg"
        file_path.write_bytes(JPEG)
        assets.append(Asset(
            project_id=run.project_id,
            source_type="uploaded",
            usage_status="seller_owned",
            filename=file_path.name,
            file_path=str(file_path),
            mime_type="image/jpeg",
            file_size=len(JPEG),
            asset_role=role,
            quality_status="usable",
            identity_status="confirmed",
            is_representative=index == 1,
            intake_order=index,
        ))
    db_session.add_all([fact, *assets])
    db_session.flush()
    db_session.add(FactEvidence(fact_id=fact.id, source_type="seller_input", original_text="DC 5V 2A"))
    run.input_snapshot = {**run.input_snapshot, "asset_ids": [asset.id for asset in assets]}
    db_session.commit()
    return run


def _resume(client, headers, state, decision: str, **extra):
    pending = state["values"]["review"]["pending"]
    return client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=headers,
        json={
            "thread_id": state["thread_id"],
            "response": {
                "schema_version": pending["schema_version"],
                "review_stage": pending["review_stage"],
                "decision": decision,
                **extra,
            },
        },
    )


def _cost_hash(state) -> str:
    pending = state["values"]["review"]["pending"]
    return pending["context"]["generation"]["cost_plan"]["cost_plan_hash"]


def _to_generation_pending(client, headers, run_id: str, db_session=None, *, minimum_generation_scenes: int = 1):
    state = client.post(f"/api/v1/graph-runs/{run_id}/start", headers=headers).json()
    state = _resume(client, headers, state, "approve").json()
    state = _resume(client, headers, state, "approve").json()
    if db_session is not None and minimum_generation_scenes > 1:
        run = db_session.query(AgentRun).filter(AgentRun.id == run_id).one()
        project = db_session.query(ProductProject).filter(ProductProject.id == run.project_id).one()
        draft = dict(project.planning_draft or {})
        cards = [dict(card) for card in draft.get("cards") or []]
        for card in cards[:minimum_generation_scenes]:
            card["image_requirement"] = "ai_redesign_required"
        draft["cards"] = cards
        project.planning_draft = draft
        db_session.commit()
    state = _resume(client, headers, state, "approve").json()
    assert state["current_stage"] == "generation_pending"
    return state


def test_lg10_page_assembly_route_is_lg10_compiled_graph_only():
    """Existing compiled graphs must retain their original terminal route."""

    from src.agents.langgraph_runtime import (
        _lg5_image_review_route,
        _lg10_image_review_route,
        build_lg5_compiled_graph,
        build_lg6_compiled_graph,
        build_lg7_compiled_graph,
        build_lg8_compiled_graph,
        build_lg10_compiled_graph,
    )

    approved_state = {
        "generation": {
            "next_action": "finalize",
            "canonical_page_assembly_input": {"input_hash": "a" * 64},
        },
    }
    assert _lg5_image_review_route(approved_state) == "finalize_run"
    for builder in (
        build_lg5_compiled_graph,
        build_lg6_compiled_graph,
        build_lg7_compiled_graph,
        build_lg8_compiled_graph,
    ):
        assert "page_assembly" not in builder(checkpointer=InMemorySaver()).get_graph().nodes
    lg10_graph = build_lg10_compiled_graph(checkpointer=InMemorySaver())
    assert "page_assembly" in lg10_graph.get_graph().nodes
    assert _lg10_image_review_route(approved_state) == "page_assembly"
    assert _lg10_image_review_route({"generation": {"next_action": "finalize"}}) == "image_review"


def test_lg10_page_assembly_rejects_invalid_canonical_input_in_production_graph():
    """A malformed frozen input cannot become an assembly state or final run."""

    from src.agents.langgraph_runtime import build_lg10_compiled_graph
    from src.services.page_finalization_service import PageAssemblyInputError, build_page_assembly_structure

    invalid_input = {"schema_version": "invalid"}
    with pytest.raises(PageAssemblyInputError):
        build_page_assembly_structure(canonical_page_assembly_input=invalid_input)

    graph = build_lg10_compiled_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "lg10-invalid-canonical-test"}}
    graph.update_state(
        config,
        {
            "run_id": "invalid-run",
            "project_id": "invalid-project",
            "workspace_id": "invalid-workspace",
            "mode": "mock",
            "generation": {
                "next_action": "finalize",
                "canonical_page_assembly_input": invalid_input,
            },
        },
        as_node="image_review",
    )
    with pytest.raises(PageAssemblyInputError):
        graph.invoke(None, config)
    assert not graph.get_state(config).values.get("page_assembly")


def test_lg10_canonical_renderer_keeps_korean_text_and_assets_separate():
    """Renderer output is deterministic and leaves image identities out of the text layer."""

    from src.services.renderer import render_lg10_canonical_page_html

    canonical_input = {
        "design_direction": "balanced_sale",
        "sections": [
            {
                "section_id": "hero",
                "sort_order": 0,
                "copy_ref": {"fields": ["hero_title", "hero_body"]},
                "approved_assets": [{"asset_id": "asset-hero", "asset_content_hash": "a" * 64}],
            },
            {
                "section_id": "product_information",
                "sort_order": 1,
                "copy_ref": {"fields": ["specification", "caution"]},
                "approved_assets": [],
            },
        ],
    }
    assembly = {
        "sections": [
            {"section_id": "hero", "sort_order": 0, "component_id": "media_with_copy", "layout_token": "image_text", "design_direction": "balanced_sale", "renderer_token": "balanced_sale_v1"},
            {"section_id": "product_information", "sort_order": 1, "component_id": "information_only", "layout_token": "spec_table", "design_direction": "balanced_sale", "renderer_token": "balanced_sale_v1"},
        ],
    }
    copy_set = {
        "hero_title": "강력한 바람을 빠르게 전달합니다",
        "hero_body": "집과 사무실에서 간편하게 사용하세요.",
        "specification": "정격 입력: DC 5V 2A",
        "caution": "주의: 충전 중에는 물에 닿지 않게 하세요.",
    }
    brand_tokens = {
        "brand_kit_version_id": None,
        "color_tokens": {"accent": "#0f766e", "text": "#172033", "surface": "#ffffff", "muted_surface": "#eef2f7"},
        "typography": {"body_font": "system-ui, sans-serif"},
        "asset_layer": {"logo": None, "watermark": None, "font_assets": []},
        "fallback": True,
    }

    rendered = render_lg10_canonical_page_html(
        canonical_page_assembly_input=canonical_input,
        page_assembly=assembly,
        copy_set=copy_set,
        brand_tokens=brand_tokens,
    )
    assert rendered == render_lg10_canonical_page_html(
        canonical_page_assembly_input=canonical_input,
        page_assembly=assembly,
        copy_set=copy_set,
        brand_tokens=brand_tokens,
    )
    assert [section["section_id"] for section in rendered["sections"]] == ["hero", "product_information"]
    assert rendered["sections"][0]["asset_layer"] == [{"asset_id": "asset-hero", "asset_content_hash": "a" * 64}]
    assert rendered["sections"][0]["text_layer"] == [
        {"field": "hero_title", "text": copy_set["hero_title"]},
        {"field": "hero_body", "text": copy_set["hero_body"]},
    ]
    assert rendered["sections"][1]["asset_layer"] == []
    for text in copy_set.values():
        assert escape(text) in rendered["html"]
    information_start = rendered["html"].index('data-section-id="product_information"')
    information_end = rendered["html"].index("</section>", information_start)
    assert "sf-asset-layer" not in rendered["html"][information_start:information_end]
    assert "<img" not in rendered["html"]
    assert re.search(r'<figure class="sf-asset-layer"[^>]*></figure>', rendered["html"])


def test_lg10_renderer_accepts_only_three_fixed_design_directions():
    """Each allowed direction has a deterministic token; arbitrary layouts cannot enter rendering."""

    from src.services.page_visual_contract import (
        lg10_renderer_direction_tokens,
        select_lg10_page_assembly_component,
    )
    from src.services.renderer import render_lg10_canonical_page_html

    brand_tokens = {
        "brand_kit_version_id": None,
        "color_tokens": {"accent": "#0f766e", "text": "#172033", "surface": "#ffffff", "muted_surface": "#eef2f7"},
        "typography": {"body_font": "system-ui, sans-serif"},
        "asset_layer": {"logo": None, "watermark": None, "font_assets": []},
        "fallback": True,
    }
    for direction in ("safe_information", "image_centric", "balanced_sale"):
        selected = select_lg10_page_assembly_component(
            rendering_mode="approved_asset",
            design_direction=direction,
        )
        canonical_input = {
            "design_direction": direction,
            "sections": [{
                "section_id": "hero", "sort_order": 0,
                "copy_ref": {"fields": ["hero_title"]},
                "approved_assets": [{"asset_id": "asset-hero", "asset_content_hash": "a" * 64}],
            }],
        }
        rendered = render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical_input,
            page_assembly={"sections": [{"section_id": "hero", "sort_order": 0, **selected}]},
            copy_set={"hero_title": "검증된 한국어 제목"},
            brand_tokens=brand_tokens,
        )
        assert rendered["design_direction"] == direction
        assert rendered["renderer_tokens"] == lg10_renderer_direction_tokens(design_direction=direction)
        assert f'data-design-direction="{direction}"' in rendered["html"]

        if direction in {"safe_information", "image_centric"}:
            information_selected = select_lg10_page_assembly_component(
                rendering_mode="information_only",
                design_direction=direction,
            )
            information_rendered = render_lg10_canonical_page_html(
                canonical_page_assembly_input={
                    "design_direction": direction,
                    "sections": [{
                        "section_id": "product_information", "sort_order": 0,
                        "copy_ref": {"fields": ["specification"]}, "approved_assets": [],
                    }],
                },
                page_assembly={"sections": [{
                    "section_id": "product_information", "sort_order": 0, **information_selected,
                }]},
                copy_set={"specification": "정격 입력: DC 5V 2A"},
                brand_tokens=brand_tokens,
            )
            assert information_rendered["sections"][0]["component_id"] == "information_only"
            assert information_rendered["sections"][0]["layout_token"] == "spec_table"
            assert "sf-asset-layer" not in information_rendered["html"]

    with pytest.raises(ValueError):
        select_lg10_page_assembly_component(
            rendering_mode="approved_asset",
            design_direction="freeform_canvas",
        )
    with pytest.raises(ValueError, match="invalid component selection"):
        render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical_input,
            page_assembly={"sections": [{
                "section_id": "hero", "sort_order": 0, **selected, "layout_token": "freeform_canvas",
            }]},
            copy_set={"hero_title": "검증된 한국어 제목"},
            brand_tokens=brand_tokens,
        )


def test_lg10_brand_tokens_use_only_rights_confirmed_assets_and_safe_fallback(
    client, auth_headers, db_session, tmp_path
):
    """Logo/watermark identities cannot include reference-only assets."""

    from src.services.page_finalization_service import resolve_lg10_brand_renderer_tokens

    run = _create_run(client, auth_headers, db_session, tmp_path)
    logo_file = tmp_path / "brand-logo.jpg"
    logo_file.write_bytes(JPEG)
    trusted_logo = Asset(
        project_id=run.project_id, source_type="uploaded", usage_status="seller_owned",
        filename=logo_file.name, file_path=str(logo_file), mime_type="image/jpeg", file_size=len(JPEG),
        content_hash=hashlib.sha256(JPEG).hexdigest(), quality_status="usable",
    )
    reference_logo = Asset(
        project_id=run.project_id, source_type="sourced", usage_status="reference_only",
        filename="supplier-logo.jpg", file_path=str(tmp_path / "supplier-logo.jpg"), mime_type="image/jpeg",
        file_size=len(JPEG), content_hash="b" * 64, quality_status="usable",
    )
    blocked_logo = Asset(
        project_id=run.project_id, source_type="uploaded", usage_status="blocked",
        filename="blocked-logo.jpg", file_path=str(tmp_path / "blocked-logo.jpg"), mime_type="image/jpeg",
        file_size=len(JPEG), content_hash="f" * 64, quality_status="usable",
    )
    kit = BrandKit(workspace_id=run.workspace_id, name="LG10 renderer kit", created_by=run.created_by)
    db_session.add_all([trusted_logo, reference_logo, blocked_logo, kit])
    db_session.flush()
    trusted_version = BrandKitVersion(
        brand_kit_id=kit.id, workspace_id=run.workspace_id, version=1, status="active",
        scope="workspace", logo_asset_ids=[trusted_logo.id, reference_logo.id],
        color_tokens={"primary": "#2563EB", "secondary": "#EFF6FF"},
        typography={"font_family": "Arial"}, watermark_policy={"mode": "logo_subtle"},
        content_hash="c" * 64, created_by=run.created_by,
    )
    blocked_version = BrandKitVersion(
        brand_kit_id=kit.id, workspace_id=run.workspace_id, version=2, status="draft",
        scope="workspace", logo_asset_ids=[blocked_logo.id], content_hash="d" * 64,
        created_by=run.created_by,
    )
    db_session.add_all([trusted_version, blocked_version])
    db_session.commit()

    trusted = resolve_lg10_brand_renderer_tokens(
        run=run,
        brand_kit_ref={"brand_kit_version_id": trusted_version.id, "brand_kit_hash": trusted_version.content_hash},
        db=db_session,
    )
    assert trusted["fallback"] is False
    assert trusted["color_tokens"]["accent"] == "#2563eb"
    assert trusted["asset_layer"]["logo"] == {
        "asset_id": trusted_logo.id, "asset_content_hash": trusted_logo.content_hash,
    }
    assert trusted["asset_layer"]["watermark"] == trusted["asset_layer"]["logo"]
    assert reference_logo.id not in repr(trusted["asset_layer"])

    blocked = resolve_lg10_brand_renderer_tokens(
        run=run,
        brand_kit_ref={"brand_kit_version_id": blocked_version.id, "brand_kit_hash": blocked_version.content_hash},
        db=db_session,
    )
    assert blocked["fallback"] is True
    assert blocked["asset_layer"] == {"logo": None, "watermark": None, "font_assets": []}
    assert blocked_logo.id not in repr(blocked["asset_layer"])

    reference_logo.usage_status = "seller_owned"
    supplier_with_claimed_rights = resolve_lg10_brand_renderer_tokens(
        run=run,
        brand_kit_ref={"brand_kit_version_id": trusted_version.id, "brand_kit_hash": trusted_version.content_hash},
        db=db_session,
    )
    assert supplier_with_claimed_rights["asset_layer"]["logo"]["asset_id"] == trusted_logo.id
    assert reference_logo.id not in repr(supplier_with_claimed_rights["asset_layer"])


@pytest.mark.lg9_fake_e2e
@pytest.mark.lg10_fake_e2e
def test_lg5r_cost_outbox_worker_checkpoint_resume_and_per_scene_review(
    client, auth_headers, db_session, lg5_runtime, testing_session_local, tmp_path
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    project = db_session.query(ProductProject).filter(ProductProject.id == run.project_id).one()
    brand_logo = db_session.query(Asset).filter(
        Asset.project_id == run.project_id, Asset.asset_role == "product_main"
    ).one()
    brand_logo.content_hash = hashlib.sha256(JPEG).hexdigest()
    kit = BrandKit(workspace_id=run.workspace_id, name="LG10 production renderer kit", created_by=run.created_by)
    db_session.add(kit)
    db_session.flush()
    brand_version = BrandKitVersion(
        brand_kit_id=kit.id, workspace_id=run.workspace_id, version=1, status="active",
        scope="workspace", logo_asset_ids=[brand_logo.id],
        color_tokens={"primary": "#2563EB", "secondary": "#EFF6FF"},
        typography={"font_family": "Arial"}, watermark_policy={"mode": "logo_subtle"},
        content_hash="e" * 64, created_by=run.created_by,
    )
    db_session.add(brand_version)
    db_session.flush()
    project.brand_kit_version_id = brand_version.id
    run.input_snapshot = {**run.input_snapshot, "design_direction": "image_centric"}
    db_session.commit()
    generation_wait = _to_generation_pending(
        client, auth_headers, run.id, db_session, minimum_generation_scenes=3
    )
    db_session.refresh(project)
    assert project.planning_draft["status"] == "approved"
    assert db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == run.project_id).count() == 0

    assert db_session.query(ImageGenerationOutboxRecord).filter(ImageGenerationOutboxRecord.run_id == run.id).count() == 0

    stale = _resume(client, auth_headers, generation_wait, "approve", cost_plan_hash="0" * 64)
    assert stale.status_code == 409
    assert db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == run.project_id).count() == 0

    provider_wait_response = _resume(
        client, auth_headers, generation_wait, "approve", cost_plan_hash=_cost_hash(generation_wait)
    )
    assert provider_wait_response.status_code == 200, provider_wait_response.text
    provider_wait = provider_wait_response.json()
    assert provider_wait["current_stage"] == "provider_wait"
    jobs = db_session.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == run.project_id).all()
    deliveries = db_session.query(ImageGenerationOutboxRecord).filter(ImageGenerationOutboxRecord.run_id == run.id).all()
    assert len(jobs) > 1
    assert len(deliveries) == len(jobs)
    assert all(item.provider_mode == "mock" for item in deliveries)
    assert all(item.provider_dispatch_count == 0 for item in deliveries)
    assert len({item.idempotency_key for item in jobs}) == len(jobs)

    # A duplicate browser poll is a pure checkpoint refresh. It cannot call the provider.
    polled = _resume(client, auth_headers, provider_wait, "refresh")
    assert polled.status_code == 200, polled.text
    provider_wait = polled.json()
    db_session.expire_all()
    assert all(item.provider_dispatch_count == 0 for item in db_session.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.run_id == run.id
    ).all())

    # Use the actual lease/outbox worker. Its completion callback resumes the
    # exact LangGraph provider_wait interrupt; no graph/provider function is patched.
    from src.db.database import SessionLocal
    from src.services.image_generation_worker import run_image_worker_batch

    worker_db = SessionLocal()
    try:
        worker_results = run_image_worker_batch(worker_db, owner="lg5r-e2e-worker", batch_size=100)
    finally:
        worker_db.close()
    assert len(worker_results) == len(jobs)
    assert all(item["provider_dispatch_count"] == 1 for item in worker_results)
    db_session.expire_all()
    assert all(job.actual_cost == 0 for job in db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == run.project_id
    ).all())

    restored = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert restored.status_code == 200, restored.text
    image_review = restored.json()
    assert image_review["current_stage"] == "image_review"
    assert image_review["status"] == "awaiting_review"
    generation = image_review["values"]["generation"]
    stale_image_review_pending = image_review["values"]["review"]["pending"]
    assert generation["review_generated_asset_ids"]
    assert generation["approved_generated_asset_ids"] == []
    from src.services.commerce_policy import is_asset_final_output_eligible

    candidate_assets = db_session.query(Asset).filter(
        Asset.id.in_(generation["review_generated_asset_ids"])
    ).all()
    assert candidate_assets
    assert all(not is_asset_final_output_eligible(asset) for asset in candidate_assets)

    # Approving one scene must keep the same graph in image_review. Completion
    # happens only after every required scene has an explicit seller decision.
    required_count = generation["required_scene_count"]
    while image_review["status"] != "completed":
        pending = image_review["values"]["review"]["pending"]
        review_jobs = pending["context"]["generation"]["jobs"]
        target = next(item for item in review_jobs if item["status"] == "needs_review")
        response = _resume(client, auth_headers, image_review, "approve", job_id=target["job_id"])
        assert response.status_code == 200, response.text
        db_session.expire_all()
        approved_asset = db_session.query(Asset).filter(Asset.id == target["output_asset_id"]).one()
        assert is_asset_final_output_eligible(approved_asset)
        image_review = response.json()
        if image_review["status"] != "completed":
            assert image_review["current_stage"] == "image_review"

    assert required_count == len(jobs)
    assert image_review["values"]["review"]["pending"] is None
    assert image_review["values"]["generation"]["all_required_scenes_approved"] is True
    assert all(item["status"] == "approved" for item in image_review["values"]["generation"]["jobs"])
    manifest = image_review["values"]["generation"]["approved_asset_manifest"]
    assert manifest["schema_version"] == "lg9-approved-asset-manifest-v1"
    assert manifest["run_id"] == run.id
    assert manifest["project_id"] == run.project_id
    assert {item["asset_id"] for item in manifest["assets"]} == set(
        image_review["values"]["generation"]["approved_asset_ids"]
    )
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["asset_content_hash"]) for item in manifest["assets"])
    assert manifest["manifest_hash"]
    canonical_input = image_review["values"]["generation"]["canonical_page_assembly_input"]
    assert canonical_input["schema_version"] == "lg10-canonical-page-assembly-input-v1"
    assert canonical_input["approved_asset_manifest"] == manifest
    assert canonical_input["design_direction"] == "image_centric"
    assert canonical_input["brand_kit_ref"] == {
        "brand_kit_version_id": brand_version.id,
        "brand_kit_hash": brand_version.content_hash,
    }
    assert re.fullmatch(r"[0-9a-f]{64}", canonical_input["input_hash"])
    assert "brand_kit_version_id" in canonical_input["brand_kit_ref"]
    assert canonical_input["channel_override_ref"]["channel_pack_version_id"]
    assert [section["sort_order"] for section in canonical_input["sections"]] == list(
        range(len(canonical_input["sections"]))
    )
    assert all(section["section_id"] and section["copy_ref"]["artifact_hash"] for section in canonical_input["sections"])
    assert {
        asset["asset_id"]
        for section in canonical_input["sections"]
        for asset in section["approved_assets"]
    } == {asset["asset_id"] for asset in manifest["assets"]}
    assembly = image_review["values"]["page_assembly"]
    assert assembly["schema_version"] == "lg10-page-assembly-v1"
    assert assembly["canonical_input_ref"] == {
        "schema_version": canonical_input["schema_version"],
        "input_hash": canonical_input["input_hash"],
    }
    assert assembly["design_direction"] == "image_centric"
    assert assembly["brand_kit_ref"] == canonical_input["brand_kit_ref"]
    assert assembly["approved_asset_manifest_ref"] == {"manifest_hash": manifest["manifest_hash"]}
    assert all(
        section["component_id"] in {"media_with_copy", "information_only"}
        and section["layout_token"] in {"image_text", "spec_table"}
        and section["design_direction"] == "image_centric"
        and section["renderer_token"] == "image_centric_v1"
        and section["selection_basis"] in {"approved_asset", "information_only"}
        for section in assembly["sections"]
    )
    assert "html" not in repr(assembly).lower()
    rendering = image_review["values"]["rendering"]
    assert rendering["schema_version"] == "lg10-canonical-render-v1"
    assert rendering["design_direction"] == "image_centric"
    assert rendering["renderer_tokens"]["renderer_token"] == "image_centric_v1"
    assert rendering["brand_tokens"]["brand_kit_version_id"] == brand_version.id
    assert rendering["brand_tokens"]["brand_kit_hash"] == brand_version.content_hash
    assert rendering["brand_tokens"]["asset_layer"]["logo"] == {
        "asset_id": brand_logo.id, "asset_content_hash": brand_logo.content_hash,
    }
    assert rendering["brand_tokens"]["asset_layer"]["watermark"] == rendering["brand_tokens"]["asset_layer"]["logo"]
    assert f'data-asset-id="{brand_logo.id}"' in rendering["html"]
    assert 'data-brand-placement="header"' in rendering["html"]
    assert 'data-brand-placement="watermark"' in rendering["html"]
    assert rendering["canonical_input_ref"]["input_hash"] == canonical_input["input_hash"]
    assert rendering["page_assembly_ref"]["assembly_hash"] == assembly["assembly_hash"]
    assert re.fullmatch(r"[0-9a-f]{64}", rendering["render_hash"])
    assert [section["section_id"] for section in rendering["sections"]] == [
        section["section_id"] for section in assembly["sections"]
    ]
    assert {
        asset["asset_id"]
        for section in rendering["sections"]
        for asset in section["asset_layer"]
    } == {asset["asset_id"] for asset in manifest["assets"]}
    copy_output = (
        db_session.query(AgentRun).filter(AgentRun.id == run.id).one().outputs_json[
            "langgraph_commerce_planning_artifacts"
        ]["copywriting"]["output"]
    )
    for section in rendering["sections"]:
        canonical_section = next(
            item for item in canonical_input["sections"] if item["section_id"] == section["section_id"]
        )
        assert section["text_layer"] == [
            {"field": field, "text": str(copy_output[field] or "")}
            for field in canonical_section["copy_ref"]["fields"]
        ]
    assert all(escape(item["text"]) in rendering["html"] for section in rendering["sections"] for item in section["text_layer"])
    version_ref = rendering["detail_page_version"]
    assert version_ref["schema_version"] == "lg10-detail-page-version-v1"
    version = db_session.query(DetailPageVersion).filter(
        DetailPageVersion.id == version_ref["id"],
        DetailPageVersion.project_id == run.project_id,
    ).one()
    assert version.is_final is True
    assert version.style_key == "image_centric"
    version_snapshot = deepcopy(version.sections_json)
    assert version_snapshot["schema_version"] == "lg10-detail-page-version-v1"
    assert version_snapshot["snapshot_hash"] == version_ref["snapshot_hash"]
    assert version_snapshot["lg10"]["canonical_page_assembly_input"] == canonical_input
    assert version_snapshot["lg10"]["page_assembly"] == assembly
    assert version_snapshot["lg10"]["canonical_rendering"] == {
        key: value for key, value in rendering.items() if key != "detail_page_version"
    }
    assert [section["section_type"] for section in version_snapshot["commerce_renderer"]["sections"]] == [
        section["section_id"] for section in rendering["sections"]
    ]
    assert version_snapshot["commerce_renderer"]["brand_assets"] == {
        "logo": {"asset_id": brand_logo.id, "asset_content_hash": brand_logo.content_hash},
        "watermark": {"asset_id": brand_logo.id, "asset_content_hash": brand_logo.content_hash},
    }
    brand_logo_path = Path(brand_logo.file_path)
    original_brand_logo_bytes = brand_logo_path.read_bytes()
    try:
        preview_brand_asset = client.get(
            f"/api/v1/files/assets/{brand_logo.id}?expected_content_hash={brand_logo.content_hash}",
            headers=auth_headers,
        )
        assert preview_brand_asset.status_code == 200
        brand_logo_path.write_bytes(b"tampered-frozen-brand-logo")
        rejected_preview_brand_asset = client.get(
            f"/api/v1/files/assets/{brand_logo.id}?expected_content_hash={brand_logo.content_hash}",
            headers=auth_headers,
        )
        assert rejected_preview_brand_asset.status_code == 409
    finally:
        brand_logo_path.write_bytes(original_brand_logo_bytes)
    assert {
        section["image_asset_id"]
        for section in version_snapshot["commerce_renderer"]["sections"]
        if section["image_asset_id"]
    } == {asset["asset_id"] for asset in manifest["assets"]}
    assert {
        section["image_asset_id"]: section["image_asset_content_hash"]
        for section in version_snapshot["commerce_renderer"]["sections"]
        if section["image_asset_id"]
    } == {
        asset["asset_id"]: asset["asset_content_hash"]
        for asset in manifest["assets"]
    }
    version_response = client.get(
        f"/api/v1/projects/{run.project_id}/page/final?version_id={version.id}",
        headers=auth_headers,
    )
    assert version_response.status_code == 200, version_response.text
    assert version_response.json()["id"] == version.id
    assert version_response.json()["sections_json"] == version_snapshot
    captured_exports: dict[str, dict[str, object]] = {}

    def fake_capture(**kwargs):
        output_format = str(kwargs["output_format"])
        extension = "jpg" if output_format in {"jpg", "jpeg"} else "png"
        image_path = tmp_path / f"lg10-preview.{extension}"
        Image.new("RGB", (16, 16), color=(255, 255, 255)).save(
            image_path, format="JPEG" if extension == "jpg" else "PNG"
        )
        zip_path = tmp_path / f"lg10-preview-{extension}-sections.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr(f"01-section.{extension}", image_path.read_bytes())
        captured_exports[output_format] = dict(kwargs)
        return {
            "long_vertical_image": str(image_path),
            "section_images_zip": str(zip_path),
            "section_heights": [16],
        }

    with patch("src.api.exports.SessionLocal", testing_session_local), patch(
        "src.services.export_service.capture_next_render_export", side_effect=fake_capture
    ):
        for output_format in ("png", "jpg"):
            export_response = client.post(
                f"/api/v1/projects/{run.project_id}/page/export",
                headers=auth_headers,
                json={
                    "preset_name": "coupang",
                    "output_format": output_format,
                    "export_target": "local_download",
                    "final_version_id": version.id,
                },
            )
            assert export_response.status_code == 202, export_response.text
            export_job = export_response.json()
            assert export_job["status"] == "pending"
            completed_export = client.get(
                f"/api/v1/projects/{run.project_id}/page/export/jobs/{export_job['id']}", headers=auth_headers,
            )
            assert completed_export.status_code == 200, completed_export.text
            assert completed_export.json()["status"] == "completed"
    assert set(captured_exports) == {"png", "jpg"}
    assert all(captured_exports[output_format]["version_id"] == version.id for output_format in captured_exports)
    assert all(captured_exports[output_format]["project_id"] == run.project_id for output_format in captured_exports)
    assert db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == run.project_id,
        ImageGenerationJobRecord.status == "approved",
    ).count() == required_count

    # Regression: historical runs may contain the pre-fix interrupt payload
    # even though their graph checkpoint already completed. Browser refresh
    # must prefer the final checkpoint instead of resurrecting that stale job.
    db_session.expire_all()
    completed_run = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
    mutable_outputs = dict(completed_run.outputs_json or {})
    mutable_commerce = deepcopy(mutable_outputs["langgraph_commerce_planning_artifacts"])
    mutable_commerce["copywriting"]["output"]["hero_title"] = "later mutable copy"
    mutable_outputs["langgraph_commerce_planning_artifacts"] = mutable_commerce
    completed_run.outputs_json = mutable_outputs
    db_session.commit()
    db_session.expire(version)
    assert version.sections_json == version_snapshot
    outputs = dict(completed_run.outputs_json or {})
    review_output = dict(outputs.get("langgraph_review") or {})
    review_output["pending"] = stale_image_review_pending
    outputs["langgraph_review"] = review_output
    completed_run.outputs_json = outputs
    db_session.add(completed_run)
    db_session.commit()

    db_session.refresh(completed_run)
    assert completed_run.outputs_json["langgraph_generation"]["approved_asset_manifest"] == manifest
    assert completed_run.outputs_json["langgraph_generation"]["canonical_page_assembly_input"] == canonical_input
    assert completed_run.outputs_json["langgraph_page_assembly"] == assembly
    assert completed_run.outputs_json["langgraph_page_rendering"] == rendering

    from src.services.page_finalization_service import build_canonical_page_assembly_input
    invalid_manifest = deepcopy(manifest)
    invalid_manifest["assets"][0]["asset_content_hash"] = "not-a-sha256"
    invalid_payload = {key: value for key, value in invalid_manifest.items() if key != "manifest_hash"}
    invalid_manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(invalid_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    from src.services.page_finalization_service import PageAssemblyInputError

    with pytest.raises(PageAssemblyInputError):
        build_canonical_page_assembly_input(
            run=completed_run,
            approved_asset_manifest=invalid_manifest,
            db=db_session,
        )
    with pytest.raises(PageAssemblyInputError):
        build_canonical_page_assembly_input(
            run=completed_run,
            approved_asset_manifest=None,
            db=db_session,
        )

    # An image API is optional for LG-10 only when this run has no required
    # image jobs. The fallback input then uses seller-owned originals and does
    # not silently treat a required image scene as information-only.
    for job in db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == run.project_id,
    ).all():
        job.required_for_completion = False
    supplier = Asset(
        project_id=run.project_id,
        source_type="sourced",
        usage_status="reference_only",
        filename="supplier-reference.jpg",
        file_path=str(tmp_path / "supplier-reference.jpg"),
        mime_type="image/jpeg",
        file_size=len(JPEG),
        quality_status="usable",
        identity_status="confirmed",
    )
    (tmp_path / supplier.filename).write_bytes(JPEG)
    rights_unconfirmed = Asset(
        project_id=run.project_id,
        source_type="uploaded",
        usage_status="blocked",
        filename="rights-unconfirmed.jpg",
        file_path=str(tmp_path / "rights-unconfirmed.jpg"),
        mime_type="image/jpeg",
        file_size=len(JPEG),
        quality_status="usable",
        identity_status="confirmed",
    )
    (tmp_path / rights_unconfirmed.filename).write_bytes(JPEG)
    db_session.add_all([supplier, rights_unconfirmed])
    db_session.commit()

    fallback_input = build_canonical_page_assembly_input(
        run=completed_run,
        approved_asset_manifest=None,
        db=db_session,
    )
    assert build_canonical_page_assembly_input(
        run=completed_run,
        approved_asset_manifest=None,
        db=db_session,
    ) == fallback_input
    fallback_assets = {
        asset["asset_id"]
        for section in fallback_input["sections"]
        for asset in section["seller_owned_fallback_assets"]
    }
    assert fallback_assets
    assert supplier.id not in fallback_assets
    assert rights_unconfirmed.id not in fallback_assets
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", asset["asset_content_hash"])
        for section in fallback_input["sections"]
        for asset in section["seller_owned_fallback_assets"]
    )

    for asset in db_session.query(Asset).filter(
        Asset.project_id == run.project_id,
        Asset.id.notin_([supplier.id, rights_unconfirmed.id]),
    ).all():
        if asset.source_type in {"uploaded", "self_shot", "local_upscaled"}:
            asset.usage_status = "reference_only"
    db_session.commit()
    information_only_input = build_canonical_page_assembly_input(
        run=completed_run,
        approved_asset_manifest=None,
        db=db_session,
    )
    assert any(section["rendering_mode"] == "information_only" for section in information_only_input["sections"])
    assert all(
        section["rendering_mode"] != "information_only"
        for section in information_only_input["sections"]
        if section["image_required"]
    )

    refreshed = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert refreshed.status_code == 200, refreshed.text
    refreshed_state = refreshed.json()
    assert refreshed_state["status"] == "completed"
    assert refreshed_state["values"]["review"]["pending"] is None
    assert refreshed_state["values"]["generation"]["all_required_scenes_approved"] is True
    assert all(item["status"] == "approved" for item in refreshed_state["values"]["generation"]["jobs"])
    assert refreshed_state["values"]["generation"]["approved_asset_manifest"] == manifest
    assert refreshed_state["values"]["generation"]["canonical_page_assembly_input"] == canonical_input
    assert refreshed_state["values"]["page_assembly"] == assembly
    assert refreshed_state["values"]["rendering"] == rendering

    # Simulate a process stopping after the LangGraph checkpoint commit but
    # before the AgentRun SQL projection was written. History replay must use
    # the same projector and restore the exact durable generation contract.
    from src.services.langgraph_run_service import LangGraphRunService

    db_session.refresh(completed_run)
    outputs = dict(completed_run.outputs_json or {})
    outputs.pop("langgraph_generation", None)
    outputs.pop("langgraph_page_assembly", None)
    outputs.pop("langgraph_page_rendering", None)
    completed_run.outputs_json = outputs
    db_session.add(completed_run)
    db_session.commit()
    graph = LangGraphRunService._compiled_graph(lg5_runtime)
    rebuilt = LangGraphRunService._rebuild_projection_from_history(
        completed_run,
        db_session,
        graph,
        LangGraphRunService._config(run.id),
    )
    assert rebuilt.outputs_json["langgraph_generation"]["approved_asset_manifest"] == manifest
    assert rebuilt.outputs_json["langgraph_generation"]["canonical_page_assembly_input"] == canonical_input
    assert rebuilt.outputs_json["langgraph_page_assembly"] == assembly
    assert rebuilt.outputs_json["langgraph_page_rendering"] == rendering
    rebuilt_version = db_session.query(DetailPageVersion).filter(DetailPageVersion.id == version.id).one()
    assert rebuilt_version.sections_json == version_snapshot

    # A final version's expected SHA-256 is checked against the bytes served to
    # both preview and image export. An asset ID alone cannot silently accept
    # replacement bytes.
    manifest_asset = manifest["assets"][0]
    final_asset = db_session.query(Asset).filter(Asset.id == manifest_asset["asset_id"]).one()
    final_asset_path = Path(final_asset.file_path)
    original_bytes = final_asset_path.read_bytes()
    verified_asset = client.get(
        f"/api/v1/files/assets/{final_asset.id}?expected_content_hash={manifest_asset['asset_content_hash']}",
        headers=auth_headers,
    )
    assert verified_asset.status_code == 200
    try:
        final_asset_path.write_bytes(b"tampered-lg10-final-asset")
        mismatch = client.get(
            f"/api/v1/files/assets/{final_asset.id}?expected_content_hash={manifest_asset['asset_content_hash']}",
            headers=auth_headers,
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "asset_snapshot_hash_mismatch"
    finally:
        final_asset_path.write_bytes(original_bytes)

    # Duplicate worker/webhook/poll effects are absorbed by the durable outbox.
    worker_db = SessionLocal()
    try:
        assert run_image_worker_batch(worker_db, owner="duplicate-worker", batch_size=100) == []
    finally:
        worker_db.close()
    db_session.expire_all()
    assert all(item.provider_dispatch_count == 1 for item in db_session.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.run_id == run.id
    ).all())


@pytest.mark.lg9_fake_e2e
@pytest.mark.lg10_fake_e2e
def test_lg5r_reject_regenerates_only_target_and_manual_upload_uses_owned_asset(
    client, auth_headers, db_session, lg5_runtime, tmp_path
):
    """Exercise the real review interrupt through scene-only retry and upload.

    No provider node is patched: the durable fake-provider worker completes the
    first batch, resumes provider_wait, then completes only the new attempt.
    """

    from src.db.database import SessionLocal
    from src.services.image_generation_worker import run_image_worker_batch

    run = _create_run(client, auth_headers, db_session, tmp_path)
    generation_wait = _to_generation_pending(
        client, auth_headers, run.id, db_session, minimum_generation_scenes=2
    )
    provider_wait = _resume(
        client,
        auth_headers,
        generation_wait,
        "approve",
        cost_plan_hash=_cost_hash(generation_wait),
    ).json()
    assert provider_wait["current_stage"] == "provider_wait"

    worker_db = SessionLocal()
    try:
        first_results = run_image_worker_batch(worker_db, owner="lg5r-review-worker-1", batch_size=100)
    finally:
        worker_db.close()
    assert len(first_results) >= 2

    image_review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers).json()
    assert image_review["current_stage"] == "image_review"
    first_jobs = image_review["values"]["generation"]["jobs"]
    rejected_job = first_jobs[0]
    preserved_job = first_jobs[1]
    preserved_snapshot = (preserved_job["job_id"], preserved_job["output_asset_id"], preserved_job["generation_attempt"])

    rejected = _resume(
        client, auth_headers, image_review, "reject", job_id=rejected_job["job_id"]
    )
    assert rejected.status_code == 200, rejected.text
    rejected_state = rejected.json()
    assert rejected_state["current_stage"] == "image_review"
    assert next(
        item for item in rejected_state["values"]["generation"]["jobs"]
        if item["job_id"] == rejected_job["job_id"]
    )["status"] == "rejected"

    retry_cost_response = _resume(
        client, auth_headers, rejected_state, "regenerate", job_id=rejected_job["job_id"]
    )
    assert retry_cost_response.status_code == 200, retry_cost_response.text
    retry_cost = retry_cost_response.json()
    assert retry_cost["current_stage"] == "generation_pending"
    retry_plan = retry_cost["values"]["generation"]["cost_plan"]
    assert retry_plan["scene_count"] == 1
    assert retry_plan["scenes"][0]["scene_id"] == rejected_job["scene_id"]

    second_wait_response = _resume(
        client,
        auth_headers,
        retry_cost,
        "approve",
        cost_plan_hash=_cost_hash(retry_cost),
    )
    assert second_wait_response.status_code == 200, second_wait_response.text
    assert second_wait_response.json()["current_stage"] == "provider_wait"

    worker_db = SessionLocal()
    try:
        second_results = run_image_worker_batch(worker_db, owner="lg5r-review-worker-2", batch_size=100)
    finally:
        worker_db.close()
    assert len(second_results) == 1
    assert second_results[0]["provider_dispatch_count"] == 1

    retried_review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers).json()
    assert retried_review["current_stage"] == "image_review"
    retried_jobs = retried_review["values"]["generation"]["jobs"]
    retried_target = next(item for item in retried_jobs if item["scene_id"] == rejected_job["scene_id"])
    preserved_after = next(item for item in retried_jobs if item["scene_id"] == preserved_job["scene_id"])
    assert retried_target["generation_attempt"] == 2
    assert retried_target["job_id"] != rejected_job["job_id"]
    assert (preserved_after["job_id"], preserved_after["output_asset_id"], preserved_after["generation_attempt"]) == preserved_snapshot

    seller_asset = db_session.query(Asset).filter(
        Asset.project_id == run.project_id,
        Asset.source_type == "uploaded",
        Asset.usage_status == "seller_owned",
    ).first()
    assert seller_asset is not None
    uploaded = _resume(
        client,
        auth_headers,
        retried_review,
        "upload",
        job_id=preserved_after["job_id"],
        asset_id=seller_asset.id,
        seller_attested=True,
    )
    assert uploaded.status_code == 200, uploaded.text
    uploaded_state = uploaded.json()
    assert uploaded_state["current_stage"] == "image_review"
    uploaded_job = next(
        item for item in uploaded_state["values"]["generation"]["jobs"]
        if item["job_id"] == preserved_after["job_id"]
    )
    assert uploaded_job["status"] == "needs_review"
    assert uploaded_job["output_asset_id"] == seller_asset.id

    approved_upload = _resume(
        client, auth_headers, uploaded_state, "approve", job_id=uploaded_job["job_id"]
    )
    assert approved_upload.status_code == 200, approved_upload.text
    if approved_upload.json()["status"] != "completed":
        assert approved_upload.json()["current_stage"] == "image_review"


def test_lg5r_worker_reconciles_completed_output_left_pending_before_provider_wait_resume(
    monkeypatch, client, auth_headers, db_session, lg5_runtime, tmp_path
):
    """A completed outbox result must not leave its LangGraph run polling forever."""

    from src.db.database import SessionLocal
    from src.services import image_generation_worker

    run = _create_run(client, auth_headers, db_session, tmp_path)
    generation_wait = _to_generation_pending(client, auth_headers, run.id, db_session, minimum_generation_scenes=2)
    provider_wait = _resume(
        client, auth_headers, generation_wait, "approve", cost_plan_hash=_cost_hash(generation_wait)
    ).json()
    assert provider_wait["current_stage"] == "provider_wait"

    original_resume = image_generation_worker._resume_completed_run
    monkeypatch.setattr(image_generation_worker, "_resume_completed_run", lambda _run_id: None)
    worker_db = SessionLocal()
    try:
        results = image_generation_worker.run_image_worker_batch(worker_db, owner="completion-recovery-worker", batch_size=100)
    finally:
        worker_db.close()
    assert len(results) >= 2

    db_session.expire_all()
    stale_job = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == run.project_id,
        ImageGenerationJobRecord.output_asset_id.isnot(None),
    ).order_by(ImageGenerationJobRecord.created_at).first()
    assert stale_job is not None
    stale_job.status = "queued"
    db_session.commit()

    monkeypatch.setattr(image_generation_worker, "_resume_completed_run", original_resume)
    worker_db = SessionLocal()
    try:
        assert image_generation_worker.run_image_worker_batch(
            worker_db, owner="completion-recovery-reconciler", batch_size=100
        ) == []
    finally:
        worker_db.close()

    db_session.expire_all()
    assert db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.id == stale_job.id
    ).one().status == "needs_review"
    recovered = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["current_stage"] == "image_review"


@pytest.mark.lg9_fake_e2e
@pytest.mark.lg10_fake_e2e
def test_lg5r_provider_failure_keeps_other_scene_output_for_review(
    monkeypatch, client, auth_headers, db_session, lg5_runtime, tmp_path
):
    """A failed scene dead-letters without discarding a completed sibling."""

    from src.db.database import SessionLocal
    from src.services import image_generation_worker

    run = _create_run(client, auth_headers, db_session, tmp_path)
    generation_wait = _to_generation_pending(
        client, auth_headers, run.id, db_session, minimum_generation_scenes=2
    )
    provider_wait = _resume(
        client,
        auth_headers,
        generation_wait,
        "approve",
        cost_plan_hash=_cost_hash(generation_wait),
    ).json()
    assert provider_wait["current_stage"] == "provider_wait"

    jobs = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == run.project_id
    ).order_by(ImageGenerationJobRecord.created_at).all()
    assert len(jobs) >= 2
    failed_job_id = jobs[0].job_id
    original_generate = image_generation_worker.DurableFakeImageProvider.generate

    def fail_one_scene(self, request):
        if request.job_id == failed_job_id:
            raise RuntimeError("MODERATION_REJECTED")
        return original_generate(self, request)

    monkeypatch.setattr(
        image_generation_worker.DurableFakeImageProvider,
        "generate",
        fail_one_scene,
    )
    worker_db = SessionLocal()
    try:
        results = image_generation_worker.run_image_worker_batch(
            worker_db,
            owner="lg5r-partial-failure-worker",
            batch_size=100,
        )
    finally:
        worker_db.close()
    assert len(results) == len(jobs)
    assert next(item for item in results if item["job_id"] == failed_job_id)["status"] == "dead_letter"

    image_review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers).json()
    assert image_review["current_stage"] == "image_review"
    review_jobs = image_review["values"]["generation"]["jobs"]
    failed_job = next(item for item in review_jobs if item["job_id"] == failed_job_id)
    completed_job = next(item for item in review_jobs if item["job_id"] != failed_job_id)
    assert failed_job["status"] == "failed"
    assert failed_job["output_asset_id"] is None
    assert completed_job["status"] == "needs_review"
    assert completed_job["output_asset_id"] is not None
    assert "approved_asset_manifest" not in image_review["values"]["generation"]
    assert "canonical_page_assembly_input" not in image_review["values"]["generation"]
    assert not image_review["values"].get("page_assembly")
    assert not image_review["values"].get("rendering")
    assert "langgraph_page_assembly" not in (
        db_session.query(AgentRun).filter(AgentRun.id == run.id).one().outputs_json or {}
    )
    assert "langgraph_page_rendering" not in (
        db_session.query(AgentRun).filter(AgentRun.id == run.id).one().outputs_json or {}
    )
    from src.services.page_finalization_service import PageAssemblyInputError, build_canonical_page_assembly_input

    run_record = db_session.query(AgentRun).filter(AgentRun.id == run.id).one()
    with pytest.raises(PageAssemblyInputError):
        build_canonical_page_assembly_input(
            run=run_record,
            approved_asset_manifest=None,
            db=db_session,
        )

    failed_record = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.job_id == failed_job_id,
    ).one()
    completed_record = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.job_id == completed_job["job_id"],
    ).one()
    failed_record.status = "rejected"
    completed_record.status = "approved"
    db_session.commit()
    with pytest.raises(PageAssemblyInputError):
        build_canonical_page_assembly_input(
            run=run_record,
            approved_asset_manifest=None,
            db=db_session,
        )
    failed_record.status = "failed"
    completed_record.status = "needs_review"
    db_session.commit()

    approved = _resume(client, auth_headers, image_review, "approve", job_id=completed_job["job_id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["current_stage"] == "image_review"
    preserved = next(
        item for item in approved.json()["values"]["generation"]["jobs"]
        if item["job_id"] == completed_job["job_id"]
    )
    still_failed = next(
        item for item in approved.json()["values"]["generation"]["jobs"]
        if item["job_id"] == failed_job_id
    )
    assert preserved["status"] == "approved"
    assert preserved["output_asset_id"] == completed_job["output_asset_id"]
    assert still_failed["status"] == "failed"
    assert "approved_asset_manifest" not in approved.json()["values"]["generation"]
    assert "canonical_page_assembly_input" not in approved.json()["values"]["generation"]
    from src.services import langgraph_image_generation_service as image_graph

    retry_plan = image_graph.apply_image_review(
        run_id=run.id,
        project_id=run.project_id,
        decision="regenerate",
        job_id=failed_job_id,
        db=db_session,
    )
    assert retry_plan["regenerate_scene_ids"] == [failed_job["scene_id"]]
    assert retry_plan["next_action"] == "cost_approval"

    source_assets = db_session.query(Asset).filter(
        Asset.project_id == run.project_id,
        Asset.source_type == "uploaded",
    ).order_by(Asset.intake_order).all()
    disallowed_asset = source_assets[0]
    disallowed_asset.usage_status = "reference_only"
    seller_path = tmp_path / "seller-owned-final.jpg"
    seller_image = Image.new("RGB", (512, 512), color=(238, 226, 214))
    seller_image.save(seller_path, format="JPEG")
    seller_asset = Asset(
        project_id=run.project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename=seller_path.name,
        file_path=str(seller_path),
        mime_type="image/jpeg",
        file_size=seller_path.stat().st_size,
        asset_role="product_detail",
        quality_status="usable",
        identity_status="confirmed",
        content_hash=None,
        intake_order=99,
    )
    db_session.add(seller_asset)
    db_session.commit()
    with pytest.raises(image_graph.ImageGenerationGateError):
        image_graph.apply_image_review(
            run_id=run.id,
            project_id=run.project_id,
            decision="upload",
            job_id=failed_job_id,
            asset_id=disallowed_asset.id,
            seller_attested=True,
            db=db_session,
        )

    uploaded = _resume(
        client,
        auth_headers,
        approved.json(),
        "upload",
        job_id=failed_job_id,
        asset_id=seller_asset.id,
        seller_attested=True,
    )
    assert uploaded.status_code == 200, uploaded.text
    uploaded_jobs = uploaded.json()["values"]["generation"]["jobs"]
    uploaded_target = next(item for item in uploaded_jobs if item["job_id"] == failed_job_id)
    untouched_sibling = next(item for item in uploaded_jobs if item["job_id"] == completed_job["job_id"])
    assert uploaded_target["status"] == "needs_review"
    assert uploaded_target["output_asset_id"] == seller_asset.id
    assert untouched_sibling["status"] == "approved"
    assert untouched_sibling["output_asset_id"] == completed_job["output_asset_id"]
    db_session.refresh(seller_asset)
    assert re.fullmatch(r"[0-9a-f]{64}", seller_asset.content_hash or "")

    recovered = _resume(client, auth_headers, uploaded.json(), "approve", job_id=failed_job_id)
    assert recovered.status_code == 200, recovered.text
    recovered_target = next(
        item for item in recovered.json()["values"]["generation"]["jobs"]
        if item["job_id"] == failed_job_id
    )
    assert recovered_target["status"] == "approved"
    db_session.refresh(seller_asset)
    assert re.fullmatch(r"[0-9a-f]{64}", seller_asset.content_hash or "")


@pytest.mark.parametrize("invalid_hash", [None, "truthy-but-not-sha256", "A" * 64])
def test_lg9_manifest_rejects_approved_asset_without_valid_sha256_content_hash(
    client, auth_headers, db_session, lg5_runtime, tmp_path, invalid_hash
):
    from src.services import langgraph_image_generation_service as image_graph

    run = _create_run(client, auth_headers, db_session, tmp_path)
    asset = db_session.query(Asset).filter(Asset.project_id == run.project_id).first()
    assert asset is not None
    asset.content_hash = invalid_hash
    db_session.add(ImageGenerationJobRecord(
        project_id=run.project_id,
        job_id=f"{run.id}-missing-content-hash",
        section_id="hash-required-scene",
        scene_id="hash-required-scene",
        role="detail_closeup",
        prompt="test",
        status="approved",
        output_asset_id=asset.id,
        required_for_completion=True,
        usage_metadata={"langgraph_run_id": run.id},
    ))
    db_session.commit()

    with pytest.raises(image_graph.ImageGenerationGateError) as error:
        image_graph.build_approved_asset_manifest(
            run_id=run.id,
            project_id=run.project_id,
            db=db_session,
        )
    assert error.value.code == "APPROVED_ASSET_MANIFEST_INELIGIBLE"


def test_lg5r_real_provider_failure_dead_letters_one_scene_and_enters_review(
    monkeypatch, client, auth_headers, db_session, lg5_runtime, tmp_path
):
    """Exercise the production real-mode outbox/worker path without a paid call."""

    from src.db.database import SessionLocal
    from src.services import (
        image_generation_service,
        image_generation_worker,
        langgraph_image_generation_service as image_graph,
        storyboard_image_generation_service,
    )

    run = _create_run(client, auth_headers, db_session, tmp_path, mode="real")
    monkeypatch.setattr(
        image_generation_service.settings,
        "SELLFORM_IMAGE_GENERATION_MODE",
        "real",
    )
    monkeypatch.setattr(image_graph, "storyboard_image_generation_is_available", lambda: True)
    monkeypatch.setattr(
        storyboard_image_generation_service,
        "storyboard_image_generation_is_available",
        lambda: True,
    )

    generation_wait = _to_generation_pending(
        client, auth_headers, run.id, db_session, minimum_generation_scenes=2
    )
    provider_wait = _resume(
        client,
        auth_headers,
        generation_wait,
        "approve",
        cost_plan_hash=_cost_hash(generation_wait),
    ).json()
    assert provider_wait["current_stage"] == "provider_wait"
    jobs = db_session.query(ImageGenerationJobRecord).filter(
        ImageGenerationJobRecord.project_id == run.project_id
    ).order_by(ImageGenerationJobRecord.created_at).all()
    assert len(jobs) >= 2
    failed_job_id = jobs[0].job_id
    fake_provider = image_generation_worker.DurableFakeImageProvider()

    class RealProviderDouble:
        def generate(self, request):
            if request.job_id == failed_job_id:
                raise RuntimeError("TIMEOUT")
            return fake_provider.generate(request)

    monkeypatch.setattr(
        image_generation_service,
        "get_image_generation_adapter",
        lambda provider_name, model=None: RealProviderDouble(),
    )
    worker_db = SessionLocal()
    try:
        results = image_generation_worker.run_image_worker_batch(
            worker_db,
            owner="lg5r-real-provider-worker",
            batch_size=100,
        )
    finally:
        worker_db.close()
    failed_result = next(item for item in results if item["job_id"] == failed_job_id)
    assert failed_result["status"] == "dead_letter"
    assert failed_result["error_code"] == "PROVIDER_TIMEOUT"
    assert failed_result["provider_dispatch_count"] == 1

    failed_delivery = db_session.query(ImageGenerationOutboxRecord).filter(
        ImageGenerationOutboxRecord.job_id == failed_job_id
    ).one()
    assert failed_delivery.provider_mode == "real"
    assert failed_delivery.status == "dead_letter"
    assert client.post(
        f"/api/v1/image-worker/outbox/{failed_delivery.id}/retry", headers=auth_headers
    ).status_code == 409

    image_review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers).json()
    assert image_review["current_stage"] == "image_review"
    review_jobs = image_review["values"]["generation"]["jobs"]
    failed_job = next(item for item in review_jobs if item["job_id"] == failed_job_id)
    successful_job = next(item for item in review_jobs if item["job_id"] != failed_job_id)
    assert failed_job["status"] == "failed"
    assert failed_job["output_asset_id"] is None
    assert successful_job["status"] == "needs_review"
    assert successful_job["output_asset_id"] is not None


def test_lg5r_planning_reference_and_attempt_change_idempotency(client, auth_headers, db_session, lg5_runtime, tmp_path):
    from src.services import langgraph_image_generation_service as image_graph

    run = _create_run(client, auth_headers, db_session, tmp_path)
    generation_wait = _to_generation_pending(client, auth_headers, run.id)
    first_plan = generation_wait["values"]["review"]["pending"]["context"]["generation"]["cost_plan"]

    project = db_session.query(ProductProject).filter(ProductProject.id == run.project_id).one()
    draft = dict(project.planning_draft)
    cards = [dict(card) for card in draft["cards"]]
    cards[0]["title"] = cards[0]["title"] + " revised"
    draft["cards"] = cards
    draft["revision"] = int(draft.get("revision") or 1) + 1
    project.planning_draft = draft
    db_session.commit()
    changed_plan = image_graph.ensure_generation_cost_plan(run_id=run.id, project_id=run.project_id, db=db_session)
    assert changed_plan["cost_plan_hash"] != first_plan["cost_plan_hash"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter(
        ImageGenerationCostApprovalRecord.cost_plan_hash == first_plan["cost_plan_hash"]
    ).one().status == "stale"

    reference = db_session.query(Asset).filter(Asset.project_id == run.project_id).first()
    reference.content_hash = "changed-reference-content"
    db_session.commit()
    changed_reference = image_graph.ensure_generation_cost_plan(run_id=run.id, project_id=run.project_id, db=db_session)
    assert changed_reference["cost_plan_hash"] != changed_plan["cost_plan_hash"]

    contract = {
        "scene_id": "hero",
        "prompt_version": "prompt-v1",
        "reference_hash": "reference-v1",
    }
    base = image_graph._idempotency_key(run.project_id, contract, 1)
    assert image_graph._idempotency_key(run.project_id, {**contract, "prompt_version": "prompt-v2"}, 1) != base
    assert image_graph._idempotency_key(run.project_id, {**contract, "reference_hash": "reference-v2"}, 1) != base
    assert image_graph._idempotency_key(run.project_id, contract, 2) != base


def test_lg5r_worker_restart_recovery_and_operator_tools(
    client, auth_headers, db_session
):
    import datetime

    run = AgentRun(
        workspace_id="00000000-0000-0000-0000-000000000002",
        project_id="project-recovery",
        mode="mock",
        status="running",
        current_stage="provider_wait",
        input_snapshot={},
        created_by="00000000-0000-0000-0000-000000000001",
    )
    project = ProductProject(
        id="project-recovery",
        workspace_id=run.workspace_id,
        brand_id="brand-recovery",
        name="recovery",
    )
    db_session.add_all([project, run])
    db_session.flush()
    jobs = []
    for index, provider_mode in enumerate(("mock", "real"), start=1):
        job = ImageGenerationJobRecord(
            project_id=project.id,
            job_id=f"recovery-{index}",
            section_id=f"scene-{index}",
            scene_id=f"scene-{index}",
            role="generated_image",
            prompt="durable recovery test",
            negative_prompt="text, logo",
            status="running",
            idempotency_key=f"recovery-key-{index}",
            generation_attempt=1,
            required_for_completion=True,
            usage_metadata={"langgraph_run_id": run.id},
        )
        db_session.add(job)
        db_session.flush()
        delivery = ImageGenerationOutboxRecord(
            workspace_id=run.workspace_id,
            project_id=project.id,
            run_id=run.id,
            thread_id=run.id,
            image_job_id=job.id,
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            provider_mode=provider_mode,
            status="leased",
            lease_owner="dead-process",
            lease_expires_at=datetime.datetime.utcnow() - datetime.timedelta(seconds=1),
            provider_dispatch_count=0 if provider_mode == "mock" else 1,
        )
        db_session.add(delivery)
        jobs.append(job)
    db_session.commit()

    recovery = client.post("/api/v1/image-worker/recovery-sweep", headers=auth_headers)
    assert recovery.status_code == 200, recovery.text
    result = recovery.json()
    assert result == {"recovered": 1, "dead_lettered": 1}
    deliveries = db_session.query(ImageGenerationOutboxRecord).order_by(ImageGenerationOutboxRecord.job_id).all()
    assert deliveries[0].status == "queued"
    assert deliveries[1].status == "dead_letter"
    assert deliveries[1].last_error_code == "PROVIDER_OUTCOME_UNKNOWN"

    listing = client.get("/api/v1/image-worker/outbox", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    assert {item["id"] for item in listing.json()["items"]} == {item.id for item in deliveries}

    unknown_retry = client.post(
        f"/api/v1/image-worker/outbox/{deliveries[1].id}/retry", headers=auth_headers
    )
    assert unknown_retry.status_code == 409

    deliveries[1].last_error_code = "PROVIDER_TIMEOUT"
    db_session.commit()
    timeout_retry = client.post(
        f"/api/v1/image-worker/outbox/{deliveries[1].id}/retry", headers=auth_headers
    )
    assert timeout_retry.status_code == 409

    deliveries[0].status = "dead_letter"
    deliveries[0].last_error_code = "PROVIDER_SAFETY"
    deliveries[0].image_job.status = "failed"
    db_session.commit()
    safe_retry = client.post(
        f"/api/v1/image-worker/outbox/{deliveries[0].id}/retry", headers=auth_headers
    )
    assert safe_retry.status_code == 200, safe_retry.text
    assert safe_retry.json()["status"] == "queued"


def test_lg5_real_dispatch_is_blocked_before_any_provider_call(monkeypatch):
    from src.services import langgraph_image_generation_service as image_graph

    monkeypatch.setattr(image_graph, "storyboard_image_generation_is_available", lambda: False)
    with pytest.raises(image_graph.ImageGenerationGateError) as error:
        image_graph._provider_gate("real")
    assert error.value.code == "API_KEY_MISSING"


@pytest.mark.parametrize(("message", "expected"), [
    ("invalid_api_key", "API_KEY_MISSING"),
    ("insufficient_quota", "BALANCE_OR_LIMIT"),
    ("request timeout", "PROVIDER_TIMEOUT"),
    ("moderation safety rejected", "PROVIDER_SAFETY"),
    ("product identity silhouette mismatch", "IDENTITY_MISMATCH"),
    ("OCR watermark contamination", "OCR_CONTAMINATION"),
    ("seller_owned rights required", "RIGHTS_BLOCKED"),
])
def test_lg5r_error_taxonomy(message, expected):
    from src.services.image_generation_worker import normalize_image_error

    assert normalize_image_error(message)[0] == expected
