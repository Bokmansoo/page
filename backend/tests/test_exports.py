import os
import shutil
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.db.models import User, Workspace, Brand, ProductProject, ProductPage, PageSection, ExportJob, Asset, ProductFact
from src.db.database import Base
from src.api.exports import should_block_export

# RENDERER_MOCK을 활성화하여 테스트 중 Playwright가 없거나 환경 설정 오류로 인한 테스트 실패 방지
os.environ["RENDERER_MOCK"] = "true"

@pytest.fixture(scope="function")
def test_setup(db_session):
    # 테스트용 기본 엔티티 생성
    user = User(id="test-user-id", email="test@example.com", name="Test User")
    db_session.add(user)
    db_session.flush()

    workspace = Workspace(id="test-ws-id", name="Test Workspace", owner_id=user.id)
    db_session.add(workspace)
    db_session.flush()

    brand = Brand(id="test-brand-id", workspace_id=workspace.id, name="Test Brand")
    db_session.add(brand)
    db_session.flush()

    # Food 카테고리 프로젝트 생성
    project = ProductProject(
        id="test-proj-id",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Test Apple Juice",
        category="Food"
    )
    db_session.add(project)
    db_session.flush()

    # 페이지 및 섹션 생성
    page = ProductPage(id="test-page-id", project_id=project.id, theme_color="#FF0000")
    db_session.add(page)
    db_session.flush()

    db_session.commit()
    return {
        "user": user,
        "workspace": workspace,
        "brand": brand,
        "project": project,
        "page": page
    }

# Mock Authentication context
def mock_auth():
    from src.db.models import User, Workspace
    user = User(id="test-user-id", email="test@example.com", name="Test User")
    workspace = Workspace(id="test-ws-id", name="Test Workspace", owner_id=user.id)
    return {"user": user, "workspace": workspace}


def test_local_download_is_not_blocked_by_qa_compliance():
    assert should_block_export(
        {"can_export": False, "issues": [{"severity": "Blocker"}]},
        "local_download",
    ) is False
    assert should_block_export(
        {"can_export": False, "issues": [{"severity": "Blocker"}]},
        "marketplace",
    ) is True


@patch("src.api.exports.get_current_user_and_workspace", Depends=mock_auth)
def test_compliance_and_export_blocker(mock_dep, client, db_session, test_setup):
    page = test_setup["page"]
    project = test_setup["project"]

    # 1. Blocker 규제 이슈를 위반하는 섹션 생성
    # Food 카테고리에서 "암 예방" 과 같은 의약품 오인 광고 표현
    sec1 = PageSection(
        page_id=page.id,
        section_type="features",
        title="항암 효과가 있는 사과즙",
        body_copy="이 사과즙은 암 예방과 만병통치약 효능을 가집니다.",
        sort_order=1,
        is_visible=True
    )
    db_session.add(sec1)
    db_session.commit()

    # 2. Compliance API 호출 및 차단 여부 검증
    # mock auth dependency override
    from src.api.auth import get_current_user_and_workspace
    client.app.dependency_overrides[get_current_user_and_workspace] = mock_auth

    res = client.get(f"/api/v1/projects/{project.id}/page/compliance")
    assert res.status_code == 200
    data = res.json()
    assert data["can_export"] is False
    assert len(data["issues"]) > 0
    # Blocker 이슈가 최소 1개 검출되었는지 확인
    blocker_issues = [i for i in data["issues"] if i["severity"] == "Blocker"]
    assert len(blocker_issues) > 0
    assert any("식품 의약품 오인 광고 금지" in i["rule"] for i in blocker_issues)

    # 3. Blocker 이슈 상태에서 Export 시도 시 400 에러 발생 확인
    res_export = client.post(
        f"/api/v1/projects/{project.id}/page/export",
        json={"preset_name": "coupang"}
    )
    assert res_export.status_code == 400
    assert "Blocker compliance issues" in res_export.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("output_format", "expected_mime", "expected_extension"),
    [
        ("png", "image/png", ".png"),
        ("jpg", "image/jpeg", ".jpg"),
    ],
)
@patch("src.api.exports.get_current_user_and_workspace", Depends=mock_auth)
def test_compliance_warning_and_successful_export(
    mock_dep,
    client,
    db_session,
    test_setup,
    testing_session_local,
    tmp_path,
    output_format,
    expected_mime,
    expected_extension,
):
    page = test_setup["page"]
    project = test_setup["project"]

    # 1. Blocker는 없고 Warning(이미지 누락)만 있는 섹션 생성
    # Food 카테고리 정상 문구이나 features 타입에 이미지 미설정
    sec1 = PageSection(
        page_id=page.id,
        section_type="features",
        title="국내산 유기농 사과 사용",
        body_copy="매일 아침 엄선된 사과만을 착즙합니다. 원재료: 사과 99.9%. 알레르기 정보: 본 제품은 메밀을 사용한 제품과 같은 시설에서 제조되었습니다. 보관방법: 실온 보관.",
        sort_order=1,
        is_visible=True
    )
    db_session.add(sec1)
    db_session.commit()

    # DetailPageVersion 추가
    from src.db.models import DetailPageVersion
    version = DetailPageVersion(
        project_id=project.id,
        name="최종본",
        style_key="modern",
        sections_json=[
            {"key": "features", "title": sec1.title, "body": sec1.body_copy}
        ],
        is_final=True
    )
    db_session.add(version)
    db_session.commit()

    # 2. Compliance API 호출 검증
    from src.api.auth import get_current_user_and_workspace
    client.app.dependency_overrides[get_current_user_and_workspace] = mock_auth

    res = client.get(f"/api/v1/projects/{project.id}/page/compliance")
    assert res.status_code == 200
    data = res.json()
    # Blocker가 없으므로 내보내기 가능
    assert data["can_export"] is True
    # features 이미지 미지정으로 인한 Warning 검출
    warning_issues = [i for i in data["issues"] if i["severity"] == "Warning"]
    assert len(warning_issues) == 1
    assert warning_issues[0]["rule"] == "섹션 이미지 누락"

    def fake_capture(**kwargs):
        extension = "jpg" if output_format in {"jpg", "jpeg"} else "png"
        image_path = tmp_path / f"captured.{extension}"
        zip_path = tmp_path / "sections.zip"
        image_path.write_bytes(b"\xff\xd8\xff" if extension == "jpg" else b"\x89PNG\r\n\x1a\n")
        zip_path.write_bytes(b"PK\x05\x06" + (b"\x00" * 18))
        return {
            "long_vertical_image": os.fspath(image_path),
            "section_images_zip": os.fspath(zip_path),
        }

    # Background tasks must use the same database as the request fixture.
    with patch("src.api.exports.SessionLocal", testing_session_local), patch(
        "src.services.export_service.capture_next_render_export",
        side_effect=fake_capture,
    ):
        # 3. Export 요청
        res_export = client.post(
            f"/api/v1/projects/{project.id}/page/export",
            json={"preset_name": "coupang", "output_format": output_format}
        )
        assert res_export.status_code == 202
        job_data = res_export.json()
        assert job_data["status"] == "pending"
        job_id = job_data["id"]

        # 4. Job 상태 조회 (FastAPI TestClient는 백그라운드 태스크를 동기적으로 즉시 수행함)
        res_job = client.get(f"/api/v1/projects/{project.id}/page/export/jobs/{job_id}")
        assert res_job.status_code == 200
        job_status_data = res_job.json()
        assert job_status_data["status"] == "completed"
        assert job_status_data["zip_asset_id"] is not None
        assert len(job_status_data["output_images"]) > 0
        image_download_url = job_status_data["output_images"][0]
        assert image_download_url.startswith(
            f"/api/v1/projects/{project.id}/page/export/download/"
        )
        res_image_download = client.get(image_download_url)
        assert res_image_download.status_code == 200
        assert res_image_download.headers["content-type"] == expected_mime
        assert expected_extension in res_image_download.headers["content-disposition"]

        # 5. Asset 및 로컬 파일 실제 생성 여부 검증
        asset_id = job_status_data["zip_asset_id"]
        asset = db_session.query(Asset).filter(Asset.id == asset_id).first()
        assert asset is not None
        assert os.path.exists(asset.file_path)

        # 6. 다운로드 API 검증
        res_download = client.get(f"/api/v1/projects/{project.id}/page/export/download/{asset_id}")
        assert res_download.status_code == 200
        assert res_download.headers["content-type"] == "application/zip"

        # 테스트 클린업 (생성된 exports 폴더 삭제)
        exports_folder = os.path.join("uploads", "exports")
        if os.path.exists(exports_folder):
            shutil.rmtree(exports_folder, ignore_errors=True)
