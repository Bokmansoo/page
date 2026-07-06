import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.db.models import User, Workspace, Brand, ProductProject, ProductPage, PageSection, PublishedPage, Asset
from src.db.database import Base

@pytest.fixture(scope="function")
def test_setup(db_session):
    # 테스트용 기본 유저 및 리소스 구축
    user = User(id="pub-user-id", email="pub@example.com", name="Pub User")
    db_session.add(user)
    db_session.flush()

    workspace = Workspace(id="pub-ws-id", name="Pub Workspace", owner_id=user.id)
    db_session.add(workspace)
    db_session.flush()

    brand = Brand(id="pub-brand-id", workspace_id=workspace.id, name="Pub Brand")
    db_session.add(brand)
    db_session.flush()

    # Living 카테고리 프로젝트 생성
    project = ProductProject(
        id="pub-proj-id",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Table Project",
        category="Living"
    )
    db_session.add(project)
    db_session.flush()

    # 페이지 정보 생성
    page = ProductPage(
        id="pub-page-id", 
        project_id=project.id, 
        theme_color="#00FF00", 
        font_family="serif"
    )
    db_session.add(page)
    db_session.flush()

    # 이미지 에셋 생성
    asset = Asset(
        id="pub-asset-id",
        project_id=project.id,
        source_type="sourced",
        filename="table_photo.jpg",
        file_path="uploads/table_photo.jpg",
        mime_type="image/jpeg",
        file_size=2048
    )
    db_session.add(asset)
    db_session.flush()

    gallery_asset = Asset(
        id="pub-gallery-asset-id",
        project_id=project.id,
        source_type="self_shot",
        filename="table_gallery.jpg",
        file_path="uploads/table_gallery.jpg",
        mime_type="image/jpeg",
        file_size=4096
    )
    db_session.add(gallery_asset)
    db_session.flush()

    # 보일 섹션과 숨겨진 섹션 생성
    sec1 = PageSection(
        id="pub-sec-1",
        page_id=page.id,
        section_type="features",
        title="편리한 접이식 설계",
        body_copy="언제든 접어서 보관할 수 있습니다.",
        image_asset_id=asset.id,
        sort_order=1,
        is_visible=True
    )
    sec2 = PageSection(
        id="pub-sec-2",
        page_id=page.id,
        section_type="faq",
        title="숨겨진 섹션",
        body_copy="비공개 섹션 테스트 문구입니다.",
        sort_order=2,
        is_visible=False
    )
    db_session.add(sec1)
    db_session.add(sec2)

    db_session.commit()
    return {
        "user": user,
        "workspace": workspace,
        "brand": brand,
        "project": project,
        "page": page,
        "asset": asset,
        "gallery_asset": gallery_asset,
    }

def mock_auth():
    from src.db.models import User, Workspace
    user = User(id="pub-user-id", email="pub@example.com", name="Pub User")
    workspace = Workspace(id="pub-ws-id", name="Pub Workspace", owner_id=user.id)
    return {"user": user, "workspace": workspace}


@patch("src.api.publications.get_current_user_and_workspace", Depends=mock_auth)
def test_page_publishing_lifecycle(mock_dep, client, db_session, test_setup):
    project = test_setup["project"]
    page = test_setup["page"]
    asset = test_setup["asset"]
    gallery_asset = test_setup["gallery_asset"]

    # 1. 발행 API 호출 검증
    # mock auth dependency override
    from src.api.auth import get_current_user_and_workspace
    client.app.dependency_overrides[get_current_user_and_workspace] = mock_auth

    publish_payload = {
        "external_store_url": "https://coupang.com/test-product",
        "slug": "custom-table",
        "config": {
            "show_faq": True,
            "before_after_slider": {
                "enabled": True,
                "before_image_id": asset.id,
                "after_image_id": asset.id
            },
            "video_url": "https://www.youtube.com/embed/demo"
        }
    }

    res_pub = client.post(f"/api/v1/projects/{project.id}/publish", json=publish_payload)
    assert res_pub.status_code == 200
    pub_data = res_pub.json()
    assert pub_data["is_active"] is True
    assert pub_data["external_store_url"] == "https://coupang.com/test-product"
    assert pub_data["slug"] == "custom-table"
    pub_id = pub_data["id"]

    # 2. 비인증 대중 상세 조회 API 호출 검증 (토큰 헤더 없음)
    # Auth 의존성 초기화하여 호출
    client.app.dependency_overrides.pop(get_current_user_and_workspace, None)
    
    res_public = client.get(f"/api/v1/public/pages/{pub_id}")
    assert res_public.status_code == 200
    public_data = res_public.json()
    assert public_data["theme_color"] == "#00FF00"
    assert public_data["font_family"] == "serif"
    assert public_data["external_store_url"] == "https://coupang.com/test-product"
    assert public_data["config"]["show_faq"] is True
    assert public_data["config"]["video_url"] == "https://www.youtube.com/embed/demo"

    # 2-1. 가시적인 섹션(sec1)만 렌더링되고 숨겨진 섹션(sec2)은 배제되었는지 검증
    assert len(public_data["sections"]) == 1
    assert public_data["sections"][0]["title"] == "편리한 접이식 설계"

    # 2-2. 섹션/전후비교 및 갤러리용 프로젝트 이미지 자산 경로 매핑 검증
    assert asset.id in public_data["assets"]
    assert public_data["assets"][asset.id] == "/uploads/table_photo.jpg"
    assert gallery_asset.id in public_data["assets"]
    assert public_data["assets"][gallery_asset.id] == "/uploads/table_gallery.jpg"

    # 3. 커스텀 슬러그 기반 조회 API 호출 검증
    res_slug = client.get(f"/api/v1/public/pages/custom-table")
    assert res_slug.status_code == 200
    assert res_slug.json()["id"] == pub_id

    # 4. 비공개 전환 가드 및 차단 정책 검증
    # 다시 인증 상태로 전환하여 설정 수정
    client.app.dependency_overrides[get_current_user_and_workspace] = mock_auth
    res_update = client.patch(
        f"/api/v1/projects/{project.id}/publication", 
        json={"is_active": False}
    )
    assert res_update.status_code == 200
    assert res_update.json()["is_active"] is False

    # 비인증 상태로 접근 시도
    client.app.dependency_overrides.pop(get_current_user_and_workspace, None)
    res_private = client.get(f"/api/v1/public/pages/{pub_id}")
    assert res_private.status_code == 403
    assert "currently set to private" in res_private.json()["detail"]


@patch("src.api.publications.get_current_user_and_workspace", Depends=mock_auth)
def test_republish_updates_existing_publication_and_reactivates(mock_dep, client, db_session, test_setup):
    project = test_setup["project"]

    from src.api.auth import get_current_user_and_workspace
    client.app.dependency_overrides[get_current_user_and_workspace] = mock_auth

    first_res = client.post(
        f"/api/v1/projects/{project.id}/publish",
        json={
            "external_store_url": "https://coupang.com/old",
            "slug": "old-table",
            "config": {"show_faq": True},
        },
    )
    assert first_res.status_code == 200
    first_data = first_res.json()

    deactivate_res = client.patch(
        f"/api/v1/projects/{project.id}/publication",
        json={"is_active": False},
    )
    assert deactivate_res.status_code == 200
    assert deactivate_res.json()["is_active"] is False

    second_res = client.post(
        f"/api/v1/projects/{project.id}/publish",
        json={
            "external_store_url": "https://smartstore.naver.com/new",
            "slug": "new-table",
            "config": {"show_faq": False, "video_url": "https://www.youtube.com/embed/new"},
        },
    )
    assert second_res.status_code == 200
    second_data = second_res.json()

    assert second_data["id"] == first_data["id"]
    assert second_data["is_active"] is True
    assert second_data["external_store_url"] == "https://smartstore.naver.com/new"
    assert second_data["slug"] == "new-table"
    assert second_data["config"]["show_faq"] is False
    assert second_data["config"]["video_url"] == "https://www.youtube.com/embed/new"
