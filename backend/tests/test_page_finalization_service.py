import pytest

from src.db.models import (
    Asset,
    Brand,
    DetailPageVersion,
    ProductPage,
    ProductProject,
    PageSection,
    User,
    Workspace,
)
from src.services.page_finalization_service import (
    FinalPageNotFoundError,
    PageDraftNotFoundError,
    finalize_page,
    get_final_page_version,
)


def _create_page(db_session):
    user = User(id="final-user-id", email="final@example.com", name="Final User")
    workspace = Workspace(id="final-ws-id", name="Final Workspace", owner_id=user.id)
    brand = Brand(id="final-brand-id", workspace_id=workspace.id, name="Final Brand")
    project = ProductProject(
        id="final-project-id",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Final Product",
        category="Living",
        selected_style="minimal",
    )
    page = ProductPage(
        id="final-page-id",
        project_id=project.id,
        theme_color="#123456",
        font_family="Pretendard",
    )
    db_session.add_all([user, workspace, brand, project, page])
    db_session.flush()
    db_session.add_all(
        [
            Asset(
                id="asset-hero",
                project_id=project.id,
                source_type="uploaded",
                filename="hero.png",
                file_path="/tmp/hero.png",
                mime_type="image/png",
                file_size=123,
            ),
            PageSection(
                page_id=page.id,
                section_type="hero",
                title="첫 화면 제목",
                body_copy="대표 설명",
                image_asset_id="asset-hero",
                associated_fact_ids=["fact-1"],
                sort_order=1,
                is_visible=True,
            ),
            PageSection(
                page_id=page.id,
                section_type="features",
                title="특징",
                body_copy="기능 설명",
                sort_order=2,
                is_visible=False,
            ),
        ]
    )
    db_session.commit()
    return project


def test_finalize_page_creates_single_final_snapshot(db_session):
    project = _create_page(db_session)
    stale_final = DetailPageVersion(
        project_id=project.id,
        name="Old final",
        style_key="old",
        sections_json={"sections": []},
        is_final=True,
    )
    db_session.add(stale_final)
    db_session.commit()

    final_version = finalize_page(db_session, project.id, name="Ready to export")

    assert final_version.is_final is True
    assert final_version.name == "Ready to export"
    assert final_version.style_key == "minimal"
    assert final_version.sections_json["theme_color"] == "#123456"
    assert final_version.sections_json["font_family"] == "Pretendard"
    assert [section["section_type"] for section in final_version.sections_json["sections"]] == [
        "hero",
        "features",
    ]
    assert final_version.sections_json["sections"][0]["image_asset_id"] == "asset-hero"

    finals = (
        db_session.query(DetailPageVersion)
        .filter(
            DetailPageVersion.project_id == project.id,
            DetailPageVersion.is_final == True,  # noqa: E712
        )
        .all()
    )
    assert [version.id for version in finals] == [final_version.id]


def test_get_final_page_version_never_falls_back_to_latest_draft(db_session):
    project = _create_page(db_session)
    db_session.add(
        DetailPageVersion(
            project_id=project.id,
            name="Latest draft",
            style_key="minimal",
            sections_json={"sections": [{"title": "draft"}]},
            is_final=False,
        )
    )
    db_session.commit()

    with pytest.raises(FinalPageNotFoundError):
        get_final_page_version(db_session, project.id)


def test_finalize_page_requires_existing_draft(db_session):
    with pytest.raises(PageDraftNotFoundError):
        finalize_page(db_session, "missing-project-id")
