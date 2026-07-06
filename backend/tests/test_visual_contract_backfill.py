import pytest
from src.db.models import Brand, PageSection, ProductFact, ProductPage, ProductProject, User, Workspace
from src.services.visual_contract_backfill import backfill_page_visuals


@pytest.fixture
def db_session_with_project(db_session):
    user = User(id="backfill-user", email="backfill@test.com", name="Backfill User")
    workspace = Workspace(id="backfill-ws", name="Backfill WS", owner_id=user.id)
    brand = Brand(id="backfill-brand", workspace_id=workspace.id, name="Backfill Brand")
    project = ProductProject(
        id="legacy-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Legacy page",
    )
    page = ProductPage(id="legacy-page", project_id=project.id)
    sections = [
        PageSection(page_id=page.id, section_type="hero", image_asset_id="hero-asset", sort_order=0),
        PageSection(page_id=page.id, section_type="comparison", image_asset_id=None, sort_order=1),
        PageSection(page_id=page.id, section_type="detail_1", image_asset_id=None, sort_order=2),
        PageSection(page_id=page.id, section_type="detail_2", image_asset_id="detail-asset", sort_order=3),
        PageSection(page_id=page.id, section_type="guarantee", image_asset_id=None, sort_order=4),
    ]
    db_session.add_all([user, workspace, brand, project, page, *sections])
    db_session.commit()
    return db_session, project, page


def test_backfill_maps_images_and_html_graphics(db_session_with_project):
    db_session, project, page = db_session_with_project
    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 5

    kinds = [section.visual_kind for section in page.sections]
    assert kinds == ["image", "html_graphic", "html_graphic", "image", "html_graphic"]

    # Idempotent: second call does nothing
    second = backfill_page_visuals(db_session, project.id)
    assert second.updated == 0


def test_backfill_skips_already_backfilled(db_session_with_project):
    db_session, project, page = db_session_with_project
    # First pass
    backfill_page_visuals(db_session, project.id)
    # Mark one section as already having a visual_kind
    page.sections[0].visual_kind = "image"
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    # All sections already have visual_kind, so 0 updates
    assert report.updated == 0


def test_backfill_uses_confirmed_facts_for_html(db_session_with_project):
    db_session, project, page = db_session_with_project
    db_session.add(
        ProductFact(
            project_id=project.id,
            fact_text="무선으로 사용 가능",
            source_text="제품 설명서",
            verification_status="confirmed",
        )
    )
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 5

    comparison = next(s for s in page.sections if s.section_type == "comparison")
    assert comparison.visual_kind == "html_graphic"
    assert comparison.visual_payload["layout_variant"] == "comparison_cards"
    assert comparison.visual_payload["cards"][0]["title"] == "무선으로 사용 가능"


def test_backfill_fills_incomplete_comparison_cards(db_session_with_project):
    db_session, project, page = db_session_with_project
    # First fully backfill all sections
    backfill_page_visuals(db_session, project.id)
    # Then break one section's payload
    comparison = next(s for s in page.sections if s.section_type == "comparison")
    comparison.visual_payload = {"layout_variant": "comparison_cards"}  # no cards
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 1
    db_session.refresh(comparison)
    assert comparison.visual_payload.get("cards") is not None
    assert len(comparison.visual_payload["cards"]) > 0


def test_backfill_fills_incomplete_benefit_cards(db_session_with_project):
    db_session, project, page = db_session_with_project
    backfill_page_visuals(db_session, project.id)
    detail = next(s for s in page.sections if s.section_type == "detail_1")
    detail.visual_payload = {"layout_variant": "benefit_cards"}  # no cards
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 1
    db_session.refresh(detail)
    assert detail.visual_payload.get("cards") is not None
    assert len(detail.visual_payload["cards"]) > 0


def test_backfill_fills_incomplete_spec_table(db_session_with_project):
    db_session, project, page = db_session_with_project
    backfill_page_visuals(db_session, project.id)
    guarantee = next(s for s in page.sections if s.section_type == "guarantee")
    guarantee.visual_payload = {"layout_variant": "spec_table"}  # no table_rows
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 1
    db_session.refresh(guarantee)
    assert guarantee.visual_payload.get("table_rows") is not None
    assert len(guarantee.visual_payload["table_rows"]) > 0


def test_backfill_does_not_overwrite_complete_payload(db_session_with_project):
    db_session, project, page = db_session_with_project
    backfill_page_visuals(db_session, project.id)
    comparison = next(s for s in page.sections if s.section_type == "comparison")
    original_cards = list(comparison.visual_payload.get("cards", []))
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 0, "Should not overwrite complete payload"
    assert comparison.visual_payload["cards"] == original_cards


def test_backfill_returns_zero_for_missing_page(db_session_with_project):
    db_session, project, page = db_session_with_project
    report = backfill_page_visuals(db_session, "nonexistent")
    assert report.updated == 0
