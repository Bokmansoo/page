from src.db.models import Asset, GenerationJobRecord, ProductFact, User, WorkspaceMember
from src.services.api_ready_generation_service import generation_rendering_contract


def _headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _project(client):
    response = client.post("/api/agent-runs", headers=_headers(), json={
        "product_name": "온열 마사지기", "description": "판매자 직접 입력", "sales_channel": "쿠팡",
        "model_options": "YL-T02", "ux_auto_generate": True,
    })
    assert response.status_code == 201
    return response.json()["project_id"]


def test_ux2e1_ocr_candidates_remain_review_only_and_keep_evidence(client, db_session):
    project_id = _project(client)
    asset = Asset(
        project_id=project_id, source_type="sourced", usage_status="reference_only",
        filename="supplier-spec.jpg", file_path="https://supplier.example/spec.jpg", mime_type="image/jpeg", file_size=1,
        ocr_text="型号 YL-T02\n额定功率 8W\n电池容量 2000mAh\n尺寸 40 x 17 x 15cm\n价格 199元",
    )
    db_session.add(asset); db_session.commit()

    response = client.post(f"/api/v1/projects/{project_id}/facts/ocr-candidates", headers=_headers(), json={"asset_ids": [asset.id]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"][0]["status"] == "completed"
    facts = db_session.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    assert {fact.field_key for fact in facts} >= {"model_name", "rated_power", "battery_capacity", "product_size"}
    assert all(fact.verification_status == "needs_review" for fact in facts)
    assert all(fact.evidences[0].source_asset_id == asset.id for fact in facts)
    assert all(fact.evidences[0].bbox for fact in facts)
    assert all(fact.evidences[0].inspection_id for fact in facts)
    assert db_session.query(GenerationJobRecord).filter(GenerationJobRecord.project_id == project_id, GenerationJobRecord.task_type == "ocr_candidate").count() == 1
    assert "file_path" not in response.text


def test_ux2e1_copy_drafts_only_use_confirmed_evidence_and_are_review_only(client, db_session):
    project_id = _project(client)
    fact = ProductFact(
        project_id=project_id, fact_text="정격 소비전력: 8W", verification_status="seller_confirmed",
        needs_review=False, field_key="rated_power", normalized_value="8", normalized_unit="W",
    )
    db_session.add(fact); db_session.flush()
    from src.db.models import FactEvidence
    db_session.add(FactEvidence(fact_id=fact.id, source_type="seller_input", original_text="정격 소비전력 8W", confidence=1))
    db_session.commit()
    plan_response = client.post(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers())
    assert plan_response.status_code == 200
    plan = plan_response.json()
    hero = plan["scenes"][0]
    update = client.patch(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers(), json={"scenes": [{"id": hero["id"], "source_fact_ids": [fact.id]}]})
    assert update.status_code == 200

    rejected = client.post(f"/api/v1/projects/{project_id}/generation-plan/copy-drafts", headers=_headers(), json={})
    assert rejected.status_code == 409
    created = client.post(f"/api/v1/projects/{project_id}/generation-plan/copy-drafts", headers=_headers(), json={"seller_cost_approved": True, "scene_ids": [hero["id"]]})
    assert created.status_code == 200, created.text
    draft = created.json()["results"][0]
    assert draft["status"] == "needs_seller_review"
    assert draft["source_fact_ids"] == [fact.id]
    assert draft["forbidden_check"]["passed"] is True
    assert "8W" in draft["body"]
    approved = client.patch(f"/api/v1/projects/{project_id}/generation-plan/copy-drafts/{hero['id']}", headers=_headers(), json={"seller_approved": True})
    assert approved.status_code == 200
    assert approved.json()["copy_draft"]["status"] == "seller_approved"
    assert db_session.query(GenerationJobRecord).filter(GenerationJobRecord.project_id == project_id, GenerationJobRecord.task_type == "grounded_copy").count() == 1

    unconfirmed = ProductFact(project_id=project_id, fact_text="치료 보장", verification_status="needs_review", needs_review=True, field_key="claim:therapy")
    db_session.add(unconfirmed); db_session.commit()
    blocked = client.patch(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers(), json={"scenes": [{"id": hero["id"], "source_fact_ids": [unconfirmed.id]}]})
    assert blocked.status_code == 422


def test_ux2e1_preserves_seller_fact_marks_copy_stale_and_exposes_only_approved_handoff(client, db_session):
    project_id = _project(client)
    confirmed = ProductFact(project_id=project_id, fact_text="정격 소비전력: 8W", verification_status="seller_confirmed", needs_review=False, field_key="rated_power", normalized_value="8", normalized_unit="W")
    db_session.add(confirmed); db_session.flush()
    from src.db.models import FactEvidence
    db_session.add(FactEvidence(fact_id=confirmed.id, source_type="seller_input", original_text="정격 소비전력 8W", confidence=1))
    ocr_asset = Asset(project_id=project_id, source_type="sourced", usage_status="reference_only", filename="conflict.jpg", file_path="https://supplier.example/conflict.jpg", mime_type="image/jpeg", file_size=1, ocr_text="额定功率 10W")
    db_session.add(ocr_asset); db_session.commit()
    ocr = client.post(f"/api/v1/projects/{project_id}/facts/ocr-candidates", headers=_headers(), json={"asset_ids": [ocr_asset.id]})
    assert ocr.status_code == 200
    db_session.refresh(confirmed)
    assert confirmed.verification_status == "seller_confirmed"

    plan = client.post(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers()).json()
    hero = plan["scenes"][0]
    assert client.patch(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers(), json={"scenes": [{"id": hero["id"], "source_fact_ids": [confirmed.id]}]}).status_code == 200
    created = client.post(f"/api/v1/projects/{project_id}/generation-plan/copy-drafts", headers=_headers(), json={"seller_cost_approved": True, "scene_ids": [hero["id"]]})
    assert created.status_code == 200
    assert client.patch(f"/api/v1/projects/{project_id}/generation-plan/copy-drafts/{hero['id']}", headers=_headers(), json={"seller_approved": True}).status_code == 200
    changed = client.patch(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers(), json={"scenes": [{"id": hero["id"], "objective": "전원 정보 재확인"}]})
    assert changed.status_code == 200
    current_scene = next(scene for scene in changed.json()["scenes"] if scene["id"] == hero["id"])
    assert current_scene["copy_draft"]["status"] == "stale"
    assert generation_rendering_contract(changed.json())["approved_copy_drafts"] == []


def test_ux2e1_viewer_cannot_generate_or_approve_copy(client, db_session):
    project_id = _project(client)
    viewer_id = "00000000-0000-0000-0000-000000000099"
    db_session.add(User(id=viewer_id, email="viewer@sellform.test", name="Viewer"))
    db_session.add(WorkspaceMember(workspace_id="00000000-0000-0000-0000-000000000002", user_id=viewer_id, role="viewer"))
    db_session.commit()
    plan = client.post(f"/api/v1/projects/{project_id}/generation-plan", headers=_headers()).json()
    viewer_headers = {"X-Mock-User-Id": viewer_id, "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002"}
    response = client.post(f"/api/v1/projects/{project_id}/generation-plan/copy-drafts", headers=viewer_headers, json={"seller_cost_approved": True, "scene_ids": [plan["scenes"][0]["id"]]})
    assert response.status_code == 403
