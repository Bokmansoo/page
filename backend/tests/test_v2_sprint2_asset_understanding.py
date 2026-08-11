from pathlib import Path

import pytest
from PIL import Image

import src.services.asset_understanding_service as asset_understanding_service
from src.db.models import AgentRun, Asset, AssetInspectionRecord, ProductProject
from src.services.agent_run_service import AgentRunService, AssetUnderstandingNotReady
from src.services.asset_understanding_service import (
    _tesseract_blocks,
    _translate_ocr_block,
    project_asset_understanding_blockers,
    run_asset_inspection,
)
from src.services.image_asset_inspector import recommend_asset_role


AUTH_HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}


def test_spaced_chinese_tesseract_text_is_classified_and_glossary_translated():
    role, confidence = recommend_asset_role(
        "6.jpg",
        ocr_text="红 色 气 泡 加 热 42°C 恒 温 加 热 ， 提 升 按 摩 体 验",
    )
    translated = _translate_ocr_block(
        {
            "text": "红 色 气 泡 加 热 42°C 恒 温 加 热 ， 提 升 按 摩 体 验",
            "bbox": {"x": 1, "y": 2, "width": 3, "height": 4},
        }
    )

    assert role == "feature"
    assert confidence >= 0.75
    assert "42°C" in translated["preserved_numeric_values"]
    assert "일정 온도 온열" in translated["translated_text"]


def test_local_ocr_retry_keeps_word_line_coordinates_without_overwriting_source_ocr(
    db_session,
    tmp_path,
    monkeypatch,
):
    project = _project(db_session, "v2-sprint2-local-ocr-retry")
    asset = _asset(db_session, project.id, tmp_path, "local-ocr-retry", "")
    local_blocks = [
        {
            "text": "恒 温 加 热 42°C",
            "language": "zh",
            "source": "local_tesseract",
            "bbox": {
                "x": 10,
                "y": 20,
                "width": 120,
                "height": 30,
                "coordinate_space": "asset_pixels",
                "precision": "word_line",
            },
            "confidence": 91.0,
        }
    ]
    monkeypatch.setattr(
        asset_understanding_service,
        "extract_ocr_blocks",
        lambda target: (local_blocks, "local_tesseract"),
    )

    first = run_asset_inspection(asset, db_session)
    second = run_asset_inspection(asset, db_session)

    assert not asset.ocr_text
    assert first.ocr_blocks[0]["bbox"]["precision"] == "word_line"
    assert second.ocr_blocks[0]["bbox"]["precision"] == "word_line"


def _project(db_session, project_id: str) -> ProductProject:
    project = ProductProject(
        id=project_id,
        workspace_id=AUTH_HEADERS["X-Mock-Workspace-Id"],
        brand_id="00000000-0000-0000-0000-000000000003",
        name="YL-T02 inspection",
    )
    db_session.add(project)
    db_session.commit()
    return project


def _asset(db_session, project_id: str, tmp_path: Path, asset_id: str, text: str, *, usage_status="reference_only") -> Asset:
    image_path = tmp_path / f"{asset_id}.png"
    Image.new("RGB", (900, 1200), color="white").save(image_path)
    asset = Asset(
        id=asset_id,
        project_id=project_id,
        source_type="url-extracted" if usage_status == "reference_only" else "uploaded",
        usage_status=usage_status,
        filename="supplier-feature-banner.png",
        file_path=str(image_path),
        mime_type="image/png",
        file_size=image_path.stat().st_size,
        ocr_text=text,
    )
    db_session.add(asset)
    db_session.flush()
    return asset


def test_versioned_asset_understanding_preserves_ocr_numbers_and_reference_only_policy(db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-reference")
    asset = _asset(
        db_session,
        project.id,
        tmp_path,
        "supplier-image",
        "额定功率 8W\n电池容量 2000mAh\n工作时间 10分钟\n42°C TYPE-C",
    )
    before_bytes = Path(asset.file_path).read_bytes()

    record = run_asset_inspection(asset, db_session)
    db_session.commit()

    assert record.status == "completed"
    assert record.analysis_version == 1
    assert record.rights_status == "reference_only"
    assert record.final_output_eligible is False
    assert {"8W", "2000mAh", "10分钟", "42°C"}.issubset(set(record.numeric_evidence))
    assert any("정격 소비전력" in block["translated_text"] for block in record.translation_blocks)
    assert Path(asset.file_path).read_bytes() == before_bytes


def test_inspection_retry_api_preserves_history_and_manual_role(client, db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-retry")
    asset = _asset(
        db_session,
        project.id,
        tmp_path,
        "manual-role-image",
        "Type-C 2000mAh",
        usage_status="seller_owned",
    )
    asset.asset_role = "usage_scene"
    asset.role_source = "manual"
    db_session.commit()

    first = client.post(
        f"/api/v1/projects/{project.id}/assets/{asset.id}/asset-inspections/retry",
        headers=AUTH_HEADERS,
    )
    second = client.post(
        f"/api/v1/projects/{project.id}/assets/{asset.id}/asset-inspections/retry",
        headers=AUTH_HEADERS,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert (first.json()["analysis_version"], second.json()["analysis_version"]) == (1, 2)
    db_session.refresh(asset)
    assert asset.asset_role == "usage_scene"
    history = client.get(
        f"/api/v1/projects/{project.id}/asset-inspections?include_history=true",
        headers=AUTH_HEADERS,
    )
    assert history.status_code == 200
    assert len(history.json()) == 2
    assert db_session.query(AssetInspectionRecord).filter_by(asset_id=asset.id).count() == 2


def test_supplier_banner_role_is_detected_from_filename(db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-banner")
    asset = _asset(db_session, project.id, tmp_path, "banner", "", usage_status="reference_only")

    record = run_asset_inspection(asset, db_session)
    db_session.commit()

    assert record.asset_role == "supplier_banner"
    assert any(warning.startswith("OCR_") for warning in record.warnings)


def test_yl_t02_six_reference_images_are_classified_by_real_ocr_meaning(db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-yl-t02-six")
    cases = [
        ("1.jpg", "智能3键设计 隐藏式 Type-C充电口", "product_detail"),
        ("2.jpg", "产品参数 额定功率 8W 电池容量 2000mAh 工作时间 10分钟", "spec_reference"),
        ("3.jpg", "可灵活调节头枕 多种角度", "feature"),
        ("4.jpg", "随时随地享受按摩 让睡眠更轻松", "usage_scene"),
        ("5.jpg", "阳离子空气层面料 触感柔软 产品材质", "material_detail"),
        ("6.jpg", "红色气泡加热 温感热敷 42°C恒温加热", "feature"),
    ]
    for index, (filename, ocr_text, expected_role) in enumerate(cases):
        image_path = tmp_path / filename
        Image.new("RGB", (900, 1200), color=(240 - index, 240, 240)).save(image_path)
        asset = Asset(
            id=f"yl-t02-{index + 1}",
            project_id=project.id,
            source_type="url-extracted",
            usage_status="reference_only",
            filename=filename,
            file_path=str(image_path),
            mime_type="image/jpeg",
            file_size=image_path.stat().st_size,
            ocr_text=ocr_text,
        )
        db_session.add(asset)
        db_session.flush()
        record = run_asset_inspection(asset, db_session)
        assert record.asset_role == expected_role
        assert record.ocr_blocks
        assert record.ocr_blocks[0]["bbox"] == {
            "x": 0,
            "y": 0,
            "width": 900,
            "height": 1200,
            "coordinate_space": "asset_pixels",
            "precision": "asset_scope",
        }
        assert record.final_output_eligible is False
    db_session.commit()


def test_general_translation_provider_and_numeric_evidence_are_preserved(db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-general-translation")
    asset = _asset(db_session, project.id, tmp_path, "translation", "全新静音体验 8W 2000mAh")

    record = run_asset_inspection(
        asset,
        db_session,
        translator=lambda text: "새로운 저소음 사용 경험 8W 2000mAh",
    )

    assert record.translation_blocks[0]["translation_status"] == "translated"
    assert record.translation_blocks[0]["translation_provider"] == "configured_ai"
    assert {"8W", "2000mAh"}.issubset(record.numeric_evidence)


def test_tesseract_word_lines_preserve_exact_asset_coordinates():
    class FakeTesseract:
        class Output:
            DICT = "dict"

        @staticmethod
        def image_to_data(image, lang, output_type, config=None):
            assert lang == "chi_sim+kor+eng"
            assert output_type == "dict"
            return {
                "text": ["电池容量", "2000mAh"],
                "block_num": [1, 1],
                "par_num": [1, 1],
                "line_num": [1, 1],
                "left": [12, 104],
                "top": [30, 30],
                "width": [80, 96],
                "height": [24, 24],
                "conf": ["91.5", "96.0"],
            }

    asset = type("AssetLike", (), {})()
    blocks = _tesseract_blocks(
        asset,
        Image.new("RGB", (400, 300), "white"),
        FakeTesseract,
        "chi_sim+kor+eng",
    )
    assert blocks[0]["text"] == "电池容量 2000mAh"
    assert blocks[0]["bbox"] == {
        "x": 12,
        "y": 30,
        "width": 188,
        "height": 24,
        "coordinate_space": "asset_pixels",
        "precision": "word_line",
    }


def test_real_pixel_vision_result_classifies_text_free_usage_scene(db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-vision-role")
    asset = _asset(db_session, project.id, tmp_path, "vision-scene", "")
    asset.filename = "IMG_0001.jpg"

    record = run_asset_inspection(
        asset,
        db_session,
        vision_analyzer=lambda current: {
            "role": "usage_scene",
            "confidence": 0.94,
            "product_identifiable": True,
            "logo_or_watermark": False,
            "text_heavy": False,
            "ai_scene_reference_suitability": "suitable",
            "reasoning": "사람이 제품을 사용하는 실제 장면",
        },
    )

    assert record.asset_role == "usage_scene"
    assert record.analysis_metadata["vision_analysis"]["product_identifiable"] is True
    assert record.analysis_metadata["ai_scene_reference_suitability"] == "suitable"


def test_perceptual_duplicate_detection_finds_near_identical_images(db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-near-duplicate")
    paths = []
    for index in range(2):
        path = tmp_path / f"near-{index}.png"
        image = Image.new("RGB", (900, 900), color="white")
        for x in range(200, 700):
            for y in range(200, 700):
                image.putpixel((x, y), (80 + index, 100, 120))
        image.save(path)
        paths.append(path)
    assets = []
    for index, path in enumerate(paths):
        asset = Asset(
            id=f"near-{index}",
            project_id=project.id,
            source_type="uploaded",
            usage_status="seller_owned",
            filename=f"product-main-{index}.png",
            file_path=str(path),
            mime_type="image/png",
            file_size=path.stat().st_size,
        )
        db_session.add(asset)
        db_session.flush()
        run_asset_inspection(asset, db_session)
        assets.append(asset)
    second_record = run_asset_inspection(assets[1], db_session)
    assert assets[0].id in second_record.duplicate_asset_ids


def test_seller_review_creates_version_and_clears_translation_gate(client, db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-seller-review")
    asset = _asset(db_session, project.id, tmp_path, "seller-review", "未知功能 8W")
    asset.filename = "feature.jpg"
    first = run_asset_inspection(asset, db_session)
    db_session.commit()
    assert first.translation_blocks[0]["translation_status"] == "needs_review"

    response = client.patch(
        f"/api/v1/projects/{project.id}/assets/{asset.id}/asset-inspections/{first.id}/review",
        headers=AUTH_HEADERS,
        json={"translated_text_by_index": {"0": "확인된 기능 8W"}},
    )

    assert response.status_code == 201
    reviewed = response.json()
    assert reviewed["analysis_version"] == 2
    assert reviewed["translation_blocks"][0]["translation_status"] == "seller_confirmed"
    assert "OCR_TRANSLATION_REVIEW_REQUIRED" not in reviewed["warnings"]


def test_sprint3_gate_requires_role_translation_and_confirmed_representative(client, db_session, tmp_path):
    project = _project(db_session, "v2-sprint2-gate")
    main = _asset(db_session, project.id, tmp_path, "main", "", usage_status="seller_owned")
    main.filename = "product-main.png"
    main.asset_role = "product_main"
    main.role_source = "manual"
    run_asset_inspection(main, db_session)
    reference = _asset(db_session, project.id, tmp_path, "feature", "Type-C 8W")
    reference.filename = "feature.jpg"
    reference.asset_role = "feature"
    reference.role_source = "manual"
    run_asset_inspection(reference, db_session)
    project.intake_snapshot = {
        "input_bundle_locked": True,
        "input_bundle": {"asset_ids": [main.id, reference.id]},
    }
    db_session.commit()

    blockers = project_asset_understanding_blockers(project.id, db_session, asset_ids=[main.id, reference.id])
    assert any(blocker["code"] == "PRODUCT_IDENTITY_UNCONFIRMED" for blocker in blockers)
    run = AgentRun(
        id="v2-sprint2-gated-run",
        project_id=project.id,
        workspace_id=AUTH_HEADERS["X-Mock-Workspace-Id"],
        mode="mock",
        status="created",
        current_stage="intake",
        created_by=AUTH_HEADERS["X-Mock-User-Id"],
        input_snapshot={"asset_ids": [main.id, reference.id]},
    )
    db_session.add(run)
    db_session.commit()
    with pytest.raises(AssetUnderstandingNotReady):
        AgentRunService._enforce_asset_understanding_gate(run, db_session, [main.id, reference.id])

    selected = client.patch(
        f"/api/v1/projects/{project.id}/assets/{main.id}/classification",
        headers=AUTH_HEADERS,
        json={"is_representative": True},
    )
    assert selected.status_code == 200
    readiness = client.get(
        f"/api/v1/projects/{project.id}/asset-understanding-readiness",
        headers=AUTH_HEADERS,
    )
    assert readiness.status_code == 200
    assert readiness.json() == {"ready": True, "blockers": []}
    AgentRunService._enforce_asset_understanding_gate(run, db_session, [main.id, reference.id])
