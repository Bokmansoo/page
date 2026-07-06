import pytest
from types import SimpleNamespace
from src.db.models import (
    Asset,
    Brand,
    ImageGenerationJobRecord,
    PageSection,
    ProductPage,
    ProductProject,
    User,
    Workspace,
)
from src.services.page_readiness_service import inspect_page_readiness


def _section(**overrides):
    values = {
        "id": "section-1",
        "section_type": "hero",
        "visual_kind": "image",
        "visual_payload": {"layout_variant": "hero_overlay"},
        "image_asset_id": "asset-1",
        "title": "제목",
        "body_copy": "본문",
        "sort_order": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_readiness_distinguishes_html_visual_from_missing_image():
    page = SimpleNamespace(
        project_id="project-1",
        sections=[
            _section(id="hero", image_asset_id="hero"),
            _section(
                id="comparison",
                section_type="comparison",
                visual_kind="html_graphic",
                visual_payload={
                    "layout_variant": "comparison_cards",
                    "cards": [{"title": "무선", "body": "이동"}],
                },
                image_asset_id=None,
            ),
        ],
        sort_order=lambda: None,
    )
    result = inspect_page_readiness(page)
    assert result.ready is True
    assert len(result.blockers) == 0


def test_readiness_blocks_missing_image_asset():
    page = SimpleNamespace(
        project_id="project-1",
        sections=[
            _section(
                id="hero",
                visual_kind="image",
                visual_payload={"layout_variant": "hero_overlay"},
                image_asset_id=None,
            ),
        ],
        sort_order=lambda: None,
    )
    result = inspect_page_readiness(page)
    assert result.ready is False
    assert any(b.code == "visual_image_asset_required" for b in result.blockers)


def test_readiness_blocks_edit_marker():
    page = SimpleNamespace(
        project_id="project-1",
        sections=[
            _section(
                id="hero",
                body_copy="[AI 수정됨] original text",
            ),
        ],
        sort_order=lambda: None,
    )
    result = inspect_page_readiness(page)
    assert result.ready is False
    assert any(b.code == "internal_edit_marker" for b in result.blockers)


def test_readiness_blocks_invalid_html_layout():
    page = SimpleNamespace(
        project_id="project-1",
        sections=[
            _section(
                id="comparison",
                section_type="comparison",
                visual_kind="html_graphic",
                visual_payload={"layout_variant": "unknown_layout"},
                image_asset_id=None,
            ),
        ],
        sort_order=lambda: None,
    )
    result = inspect_page_readiness(page)
    assert result.ready is False
    assert any(b.code == "visual_invalid_html_layout" for b in result.blockers)


def test_readiness_blocks_generated_image_awaiting_identity_review(db_session):
    user = User(id="readiness-user", email="readiness@test.com", name="Readiness User")
    workspace = Workspace(id="readiness-ws", name="Readiness WS", owner_id=user.id)
    brand = Brand(id="readiness-brand", workspace_id=workspace.id, name="Readiness Brand")
    project = ProductProject(
        id="readiness-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Readiness Project",
    )
    asset = Asset(
        id="generated-asset",
        project_id=project.id,
        source_type="real-generated",
        filename="generated.png",
        file_path="generated.png",
        mime_type="image/png",
        file_size=100,
    )
    page = ProductPage(id="readiness-page", project_id=project.id)
    section = PageSection(
        id="readiness-hero",
        page_id=page.id,
        section_type="hero",
        title="휴대용 선풍기",
        body_copy="필요한 곳에서 사용하세요.",
        image_asset_id=asset.id,
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
        sort_order=0,
    )
    job = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="readiness-job",
        section_id=section.id,
        role="hero",
        prompt="portable fan",
        output_asset_id=asset.id,
        status="needs_review",
    )
    db_session.add_all([user, workspace, brand, project, asset, page, section, job])
    db_session.commit()

    result = inspect_page_readiness(page, db_session)

    assert result.ready is False
    assert any(b.code == "identity_review_required" for b in result.blockers)


def test_readiness_allows_jobless_project_generated_image_in_dev_mode(db_session):
    user = User(id="readiness-user-jobless", email="readiness-jobless@test.com", name="Readiness User")
    workspace = Workspace(id="readiness-ws-jobless", name="Readiness WS", owner_id=user.id)
    brand = Brand(id="readiness-brand-jobless", workspace_id=workspace.id, name="Readiness Brand")
    project = ProductProject(
        id="readiness-project-jobless",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Readiness Project",
    )
    asset = Asset(
        id="generated-asset-jobless",
        project_id=project.id,
        source_type="real-generated",
        filename="generated.png",
        file_path="generated.png",
        mime_type="image/png",
        file_size=100,
    )
    page = ProductPage(id="readiness-page-jobless", project_id=project.id)
    section = PageSection(
        id="readiness-hero-jobless",
        page_id=page.id,
        section_type="hero",
        title="휴대용 냉각선풍기",
        body_copy="콘센트 없이 바로 사용할 수 있어요.",
        image_asset_id=asset.id,
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
        sort_order=0,
    )
    db_session.add_all([user, workspace, brand, project, asset, page, section])
    db_session.commit()

    result = inspect_page_readiness(page, db_session)

    assert result.ready is True
    assert result.blockers == []
