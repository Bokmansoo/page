import pytest
from src.db.models import User, Workspace, Brand, ProductProject, ProductPage, PageSection
from src.services.copy_rewrite_service import CopyRewriteCommand

HEADERS = {
    "X-Mock-User-Id": "rewrite-user",
    "X-Mock-Workspace-Id": "rewrite-workspace",
}

@pytest.fixture
def setup_rewrite_project(db_session):
    user = User(
        id=HEADERS["X-Mock-User-Id"],
        email="rewrite@example.com",
        name="Rewrite User",
    )
    workspace = Workspace(
        id=HEADERS["X-Mock-Workspace-Id"],
        name="Rewrite Workspace",
        owner_id=user.id,
    )
    brand = Brand(id="rewrite-brand", workspace_id=workspace.id, name="Rewrite Brand")
    project = ProductProject(
        id="rewrite-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="테스트 냉각선풍기",
        category="가전제품",
        status="ready",
    )
    page = ProductPage(
        id="rewrite-page",
        project_id=project.id,
        theme_color="#5B7CFA",
        font_family="Sans-Serif",
    )
    section = PageSection(
        id="rewrite-section",
        page_id=page.id,
        section_type="hero",
        title="기존 원본 제목",
        body_copy="기존 원본 본문 내용입니다. 아주 좋습니다.",
        sort_order=0,
        is_visible=True,
    )
    db_session.add_all([user, workspace, brand, project, page, section])
    db_session.commit()
    return project.id, section.id

def test_copy_rewrite_preview_presets(client, setup_rewrite_project):
    project_id, section_id = setup_rewrite_project

    presets = [
        CopyRewriteCommand.STRONGER_PERSUASION,
        CopyRewriteCommand.SHORTER_IMPACT,
        CopyRewriteCommand.BEGINNER_SELLER_TONE,
        CopyRewriteCommand.PREMIUM_BRAND_TONE,
        CopyRewriteCommand.MARKETPLACE_OPTIMIZED,
        CopyRewriteCommand.TRUST_ORIENTED,
        CopyRewriteCommand.EMOTIONAL_LIFESTYLE,
        CopyRewriteCommand.REDUCE_PURCHASE_ANXIETY,
        CopyRewriteCommand.CUSTOM_EDIT,
    ]

    for preset in presets:
        response = client.post(
            f"/api/v1/projects/{project_id}/page/sections/{section_id}/copy-rewrite/preview",
            json={
                "command": preset.value,
                "instruction": "특별 혜택 강조" if preset == CopyRewriteCommand.CUSTOM_EDIT else "",
                "scope": "section"
            },
            headers=HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify structure
        assert "before" in data
        assert "after" in data
        assert "rationale" in data
        assert "safety_notes" in data
        
        # Verify text fields
        assert data["before"]["title"] == "기존 원본 제목"
        assert data["before"]["body_copy"] == "기존 원본 본문 내용입니다. 아주 좋습니다."
        assert data["after"]["title"] != ""
        assert data["after"]["body_copy"] != ""
        assert data["rationale"] != ""
        
        # Verify no internal markers
        assert "[AI 수정됨]" not in data["after"]["title"]
        assert "[AI 수정됨]" not in data["after"]["body_copy"]

def test_copy_rewrite_preview_manual_edit_preservation(client, setup_rewrite_project):
    project_id, section_id = setup_rewrite_project

    # Provide custom current title/body to simulate manual unsaved changes
    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section_id}/copy-rewrite/preview",
        json={
            "command": CopyRewriteCommand.SHORTER_IMPACT.value,
            "title": "사용자 수동 수정 제목",
            "body_copy": "사용자 수동 수정 본문 내용",
            "scope": "section"
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    data = response.json()

    # The manual edits must be recorded as 'before' source
    assert data["before"]["title"] == "사용자 수동 수정 제목"
    assert data["before"]["body_copy"] == "사용자 수동 수정 본문 내용"
