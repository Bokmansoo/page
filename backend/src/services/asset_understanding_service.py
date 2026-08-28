"""Versioned, evidence-first asset understanding for V2 Sprint 2.

This service deliberately analyses supplier assets as references.  It does not
alter their pixels, remove watermarks, or make them final-output eligible.
OCR is evidence: numbers and model identifiers are copied verbatim, while
translations are clearly marked for seller review when incomplete.
"""

from __future__ import annotations

import datetime
import copy
import base64
import json
import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session
from PIL import Image

from src.db.models import Asset, AssetInspectionRecord
from src.config import settings
from src.services.commerce_policy import resolved_asset_usage_status
from src.services.image_asset_inspector import apply_asset_inspection, recommend_asset_role


ANALYZER_VERSION = "asset-understanding-v2"

# These are transparent terminology substitutions, not generated product
# claims. Any remaining Chinese characters keep the translation in review.
TERM_TRANSLATIONS: tuple[tuple[str, str], ...] = (
    ("智能3键设计", "스마트 3버튼 설계"),
    ("便捷操作", "간편한 조작"),
    ("可灵活调节头枕", "유연하게 조절 가능한 헤드레스트"),
    ("多种角度自在选择", "다양한 각도 조절"),
    ("一体式头枕", "일체형 헤드레스트"),
    ("随时随地享受按摩", "언제 어디서나 편리하게 마사지"),
    ("科学支撑保护颈椎", "목을 편안하게 받쳐주는 구조"),
    ("让睡眠更轻松", "편안한 휴식 지원"),
    ("阳离子空气层面料", "에어레이어 원단"),
    ("触感柔软", "부드러운 촉감"),
    ("红色气泡加热", "레드라이트 온열"),
    ("恒温加热", "일정 온도 온열"),
    ("提升按摩体验", "마사지 사용감 향상"),
    ("按摩枕", "마사지 베개"),
    ("颈椎", "목·어깨"),
    ("智能3按键", "스마트 3버튼"),
    ("一键启动", "원터치 시작"),
    ("长按3秒开机", "3초 길게 눌러 전원 켜기"),
    ("档位调节", "단계 조절"),
    ("加热开关", "온열 켜기/끄기"),
    ("隐藏式", "숨김형"),
    ("充电口", "충전 포트"),
    ("额定电压", "정격 입력 전압"),
    ("额定功率", "정격 소비전력"),
    ("额定频率", "정격 주파수"),
    ("电池容量", "배터리 용량"),
    ("工作时间", "작동 시간"),
    ("产品参数", "제품 사양"),
    ("产品名称", "제품명"),
    ("产品型号", "제품 모델"),
    ("产品颜色", "제품 색상"),
    ("适用人群", "권장 대상"),
    ("红色氛围温感热敷", "레드 무드 온열"),
    ("恒温加热", "정온 가열"),
    ("可灵活调节头枕", "각도 조절 헤드레스트"),
    ("多种角度", "다양한 각도"),
    ("功能描述", "기능 설명"),
    ("产品材质", "제품 소재"),
    ("阳离子空气层面料", "양이온 에어레이어 원단"),
    ("触感柔软", "부드러운 촉감"),
    ("舒适环保", "편안하고 친환경적인 소재"),
    ("锦纶双面布料", "나일론 양면 원단"),
    ("随时随地享受按摩", "언제 어디서나 편안한 마사지"),
    ("科学支撑", "인체공학적 지지"),
    ("保护颈椎", "목 주변을 편안하게 지지"),
    ("慢回弹头部靠枕", "천천히 복원되는 헤드 쿠션"),
    ("让睡眠更轻松", "더 편안한 휴식을 돕는 설계"),
    ("温感热敷", "따뜻한 온열 기능"),
    ("提升按摩体验", "마사지 사용감을 높이는 설계"),
    ("使用时间", "사용 시간"),
    ("充电时间", "충전 시간"),
    ("按摩头", "마사지 헤드"),
    ("自动正转反转", "자동 양방향 회전"),
    ("力度", "강도"),
    ("产品清单", "제품 구성"),
    ("灰色", "그레이"),
    ("成人", "성인"),
    ("分钟", "분"),
    ("小时", "시간"),
    ("Type-C", "Type-C"),
)

_NUMERIC_EVIDENCE_PATTERN = re.compile(
    r"(?:DC|AC)?\s*\d+(?:\.\d+)?\s*(?:V|A|W|Hz|mAh|Ah|°C|℃|cm|mm|kg|g|%)"
    r"|\d+(?:\.\d+)?\s*[×x*]\s*\d+(?:\.\d+)?(?:\s*[×x*]\s*\d+(?:\.\d+)?)?\s*(?:cm|mm)",
    re.IGNORECASE,
)

# Prefer complete electrical inputs and preserve commonly seen Korean/Chinese
# duration units as a single evidence value.  This later definition keeps
# compatibility with older source encodings in the initial pattern above.
_NUMERIC_EVIDENCE_PATTERN = re.compile(
    r"(?:DC|AC)\s*\d+(?:\.\d+)?\s*V\s*\d+(?:\.\d+)?\s*A"
    r"|\d+(?:\.\d+)?\s*(?:mAh|Ah|Hz|W|V|A|\u00B0C|\u2103|cm|mm|kg|g|%|分钟|分|분|min(?:ute)?s?)"
    r"|\d+(?:\.\d+)?\s*[×x*]\s*\d+(?:\.\d+)?(?:\s*[×x*]\s*\d+(?:\.\d+)?)?\s*(?:cm|mm)",
    re.IGNORECASE,
)


def _split_ocr_blocks(raw_text: str | None) -> list[str]:
    if not raw_text:
        return []
    blocks = [line.strip() for line in re.split(r"[\r\n]+", raw_text) if line.strip()]
    # A URL collector may return one large HTML-derived snippet. Keep its
    # evidence bounded but do not silently discard it.
    return blocks[:30]


def _asset_scope_bbox(asset: Asset) -> dict[str, Any]:
    return {
        "x": 0,
        "y": 0,
        "width": int(asset.width or 0),
        "height": int(asset.height or 0),
        "coordinate_space": "asset_pixels",
        "precision": "asset_scope",
    }


def _configure_local_tesseract(pytesseract: Any) -> str | None:
    """Resolve the Windows executable and project-local language data.

    UB Mannheim's installer places the executable under Program Files, but a
    newly opened terminal does not always have that directory on PATH. Extra
    language packs can also live in ``backend/.runtime`` so local development
    does not require writing to the protected Program Files directory.
    """
    configured_cmd = os.environ.get("SELLFORM_TESSERACT_CMD")
    executable_candidates = [
        configured_cmd,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe" if os.name == "nt" else None,
    ]
    for candidate in executable_candidates:
        if candidate and os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            break

    configured_tessdata = os.environ.get("SELLFORM_TESSDATA_DIR") or os.environ.get("TESSDATA_PREFIX")
    project_tessdata = Path(__file__).resolve().parents[2] / ".runtime" / "tesseract" / "tessdata"
    tessdata_dir = Path(configured_tessdata) if configured_tessdata else project_tessdata
    if tessdata_dir.is_dir():
        return str(tessdata_dir)
    return None


def _tesseract_blocks(
    asset: Asset,
    image: Image.Image,
    pytesseract: Any,
    languages: str,
    tessdata_dir: str | None = None,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "lang": languages,
        "output_type": pytesseract.Output.DICT,
    }
    if tessdata_dir:
        # pytesseract/shlex on Windows can preserve the quote characters and
        # make Tesseract look for a literal `"C:\\..."` directory. The local
        # runtime path is deliberately space-free, so pass it unquoted.
        kwargs["config"] = f"--tessdata-dir {tessdata_dir}"
    data = pytesseract.image_to_data(image, **kwargs)
    grouped: dict[tuple[int, int, int], list[int]] = {}
    for index, raw_text in enumerate(data.get("text", [])):
        if not str(raw_text or "").strip():
            continue
        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        grouped.setdefault(key, []).append(index)

    blocks: list[dict[str, Any]] = []
    for indexes in grouped.values():
        text_value = " ".join(str(data["text"][i]).strip() for i in indexes).strip()
        left = min(int(data["left"][i]) for i in indexes)
        top = min(int(data["top"][i]) for i in indexes)
        right = max(int(data["left"][i]) + int(data["width"][i]) for i in indexes)
        bottom = max(int(data["top"][i]) + int(data["height"][i]) for i in indexes)
        confidences = [
            float(data["conf"][i])
            for i in indexes
            if str(data["conf"][i]).replace(".", "", 1).lstrip("-").isdigit()
            and float(data["conf"][i]) >= 0
        ]
        blocks.append(
            {
                "text": text_value,
                "language": _language_of(text_value),
                "source": "local_tesseract",
                "bbox": {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                    "coordinate_space": "asset_pixels",
                    "precision": "word_line",
                },
                "confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
            }
        )
    return blocks[:50]


def extract_ocr_blocks(asset: Asset) -> tuple[list[dict[str, Any]], str]:
    """Use seller/source OCR first, then optional local Tesseract OCR.

    Tesseract is intentionally optional because its multi-language language
    packs are installed at the operating-system level.  A missing engine is a
    visible, retryable inspection warning; it never becomes invented OCR text.
    """
    supplied = _split_ocr_blocks(asset.ocr_text)
    if supplied:
        return [
            {
                "text": block,
                "language": _language_of(block),
                "source": "source_ocr",
                "bbox": _asset_scope_bbox(asset),
                "confidence": None,
            }
            for block in supplied
        ], "source_ocr"
    if not asset.file_path or asset.file_path.startswith(("http://", "https://")):
        return [], "ocr_image_not_local"
    if not os.path.isfile(asset.file_path):
        return [], "ocr_image_not_available"
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError:
        return [], "ocr_engine_not_configured"
    try:
        languages = os.environ.get("SELLFORM_OCR_LANGUAGES", "chi_sim+kor+eng")
        tessdata_dir = _configure_local_tesseract(pytesseract)
        with Image.open(asset.file_path) as image:
            blocks = _tesseract_blocks(asset, image, pytesseract, languages, tessdata_dir)
    except Exception:
        return [], "ocr_engine_failed"
    return blocks, "local_tesseract" if blocks else "ocr_no_text_detected"


def _language_of(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "unknown"


def _configured_ai_translator(text: str) -> str | None:
    if not settings.SELLFORM_OCR_AI_TRANSLATION_ENABLED:
        return None
    try:
        if settings.OPENAI_API_KEY:
            import openai

            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=settings.effective_openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "상품 이미지 OCR 원문을 자연스러운 한국어로만 번역하세요. "
                            "숫자, 단위, 모델명, 구성품명과 주의 문구는 절대 생략하거나 변경하지 마세요."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0,
                timeout=settings.AI_FACT_EXTRACTION_TIMEOUT_SECONDS,
            )
            return (response.choices[0].message.content or "").strip() or None
        if settings.GEMINI_API_KEY:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.SELLFORM_TEXT_LLM_FALLBACK1_MODEL)
            response = model.generate_content(
                "숫자·단위·모델명을 보존하여 다음 상품 OCR을 한국어로 번역하세요:\n" + text
            )
            return str(response.text or "").strip() or None
    except Exception:
        return None
    return None


def _configured_vision_analyzer(asset: Asset) -> dict[str, Any] | None:
    """Analyze actual pixels with the configured vision model when enabled.

    The deterministic OCR/quality path remains available without an API key.
    Enabling this switch is explicit because an upload-time vision call can
    incur provider cost.
    """
    if not settings.SELLFORM_ASSET_AI_VISION_ENABLED or not settings.OPENAI_API_KEY:
        return None
    if not asset.file_path or not os.path.isfile(asset.file_path):
        return None
    try:
        import openai

        with open(asset.file_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.effective_openai_model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "상품 이미지 자산을 분류하세요. JSON으로 role, confidence, "
                        "product_identifiable, logo_or_watermark, text_heavy, "
                        "ai_scene_reference_suitability, reasoning을 반환하세요. "
                        "role은 product_main, product_detail, feature, usage_scene, components, "
                        "material_detail, package, shipping_info, spec_reference, supplier_banner, "
                        "decorative, unidentifiable_reference 중 하나입니다."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"파일명: {asset.filename}"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{asset.mime_type};base64,{encoded}",
                                "detail": "low",
                            },
                        },
                    ],
                },
            ],
            temperature=0,
            timeout=settings.AI_FACT_EXTRACTION_TIMEOUT_SECONDS,
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception:
        return None


def _translate_ocr_block(
    block: dict[str, Any],
    translator: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    source_text = str(block.get("text") or "")
    # OCR engines commonly split Chinese words into individual characters.
    # Removing only whitespace *between* CJK characters lets the deterministic
    # glossary match while the original source text remains unchanged below.
    translated = re.sub(r"\s+", "", source_text) if _language_of(source_text) == "zh" else source_text
    for source, target in TERM_TRANSLATIONS:
        translated = translated.replace(source, target)
    language = _language_of(source_text)
    unresolved = bool(re.search(r"[\u4e00-\u9fff]", translated))
    provider = "local_glossary"
    if unresolved and translator:
        ai_translation = translator(source_text)
        if ai_translation and not re.search(r"[\u4e00-\u9fff]", ai_translation):
            translated = ai_translation
            unresolved = False
            provider = "configured_ai"
    numeric_values = list(
        dict.fromkeys(
            match.group(0).strip().replace("℃", "°C")
            for match in _NUMERIC_EVIDENCE_PATTERN.finditer(source_text)
        )
    )
    numeric_values = [
        re.sub(r"\s+", " ", value.strip()).replace("\u2103", "\u00B0C")
        for value in numeric_values
    ]
    missing_numeric_values = [value for value in numeric_values if value.lower() not in translated.lower()]
    if missing_numeric_values:
        translated = f"{translated} ({', '.join(missing_numeric_values)})"
    return {
        "source_text": source_text,
        "translated_text": translated,
        "language": language,
        "translation_status": "needs_review" if unresolved else "translated",
        "translation_provider": provider,
        "bbox": block.get("bbox"),
        "preserved_numeric_values": numeric_values,
    }


def _rights_state(asset: Asset, warnings: list[str]) -> tuple[str, bool]:
    usage_status = resolved_asset_usage_status(asset)
    if usage_status == "reference_only":
        return "reference_only", False
    if usage_status == "blocked" or asset.quality_status == "rejected":
        return "blocked", False
    blocking_review_signals = {
        "LOW_RESOLUTION",
        "IMAGE_FILE_CORRUPT",
        "IMAGE_FILE_NOT_AVAILABLE",
        "SUPPLIER_LOGO_OR_WATERMARK",
        "OCR_TRANSLATION_REVIEW_REQUIRED",
    }
    needs_review = bool(blocking_review_signals.intersection(warnings))
    if asset.asset_role in {"unknown", "unidentifiable_reference", "supplier_banner"}:
        needs_review = True
    if asset.asset_role == "product_main" and asset.identity_status != "confirmed":
        needs_review = True
    final_eligible = (
        usage_status in {"seller_owned", "ai_generated", "derived_graphic"}
        and not needs_review
    )
    return ("final_candidate" if final_eligible else "needs_review"), final_eligible


def _dhash(file_path: str) -> int | None:
    try:
        with Image.open(file_path) as image:
            pixels = list(image.convert("L").resize((9, 8)).getdata())
    except Exception:
        return None
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return value


def _duplicate_asset_ids(asset: Asset, db: Session) -> list[str]:
    duplicates: list[str] = []
    source_dhash = _dhash(asset.file_path) if os.path.isfile(asset.file_path or "") else None
    rows = db.query(Asset).filter(Asset.project_id == asset.project_id, Asset.id != asset.id).all()
    for row in rows:
        if asset.content_hash and row.content_hash == asset.content_hash:
            duplicates.append(row.id)
            continue
        if source_dhash is None or not os.path.isfile(row.file_path or ""):
            continue
        other_dhash = _dhash(row.file_path)
        if other_dhash is not None and (source_dhash ^ other_dhash).bit_count() <= 5:
            duplicates.append(row.id)
    return list(dict.fromkeys(duplicates))


def _visual_analysis_metadata(
    asset: Asset,
    ocr_blocks: list[dict[str, Any]],
    vision_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    image_area = max(1, int(asset.width or 0) * int(asset.height or 0))
    text_area = 0
    for block in ocr_blocks:
        bbox = block.get("bbox") or {}
        if bbox.get("precision") == "word_line":
            text_area += int(bbox.get("width") or 0) * int(bbox.get("height") or 0)
    text_density = min(1.0, text_area / image_area)
    if asset.asset_role == "product_main" and asset.identity_status == "confirmed":
        ai_scene_suitability = "suitable"
    elif asset.asset_role in {"product_main", "product_detail", "feature", "usage_scene", "components", "material_detail"}:
        ai_scene_suitability = "needs_review"
    else:
        ai_scene_suitability = "not_suitable"
    metadata = {
        "text_density": round(text_density, 4),
        "text_density_status": "high" if text_density >= 0.35 else "normal",
        "identity_status": asset.identity_status,
        "safe_crop_status": asset.safe_crop_status,
        "ai_scene_reference_suitability": ai_scene_suitability,
        "role_source": asset.role_source,
    }
    if vision_result:
        metadata["vision_analysis"] = vision_result
        metadata["ai_scene_reference_suitability"] = vision_result.get(
            "ai_scene_reference_suitability",
            metadata["ai_scene_reference_suitability"],
        )
    return metadata


def run_asset_inspection(
    asset: Asset,
    db: Session,
    *,
    translator: Callable[[str], str | None] | None = None,
    vision_analyzer: Callable[[Asset], dict[str, Any] | None] | None = None,
) -> AssetInspectionRecord:
    """Create a new inspection result; failures are recorded, never raised.

    The current implementation consumes pre-collected OCR text.  If a local
    OCR engine is not configured, the record says so instead of fabricating
    recognized text. A later provider can populate ``asset.ocr_text`` and use
    the same versioned contract.
    """
    next_version = (
        (db.query(AssetInspectionRecord.analysis_version)
         .filter(AssetInspectionRecord.asset_id == asset.id)
         .order_by(AssetInspectionRecord.analysis_version.desc())
         .first() or (0,))[0]
        + 1
    )
    record = AssetInspectionRecord(
        project_id=asset.project_id,
        asset_id=asset.id,
        analysis_version=next_version,
        status="pending",
        analyzer_version=ANALYZER_VERSION,
    )
    db.add(record)
    db.flush()

    try:
        # First pass records dimensions/quality so even source-provided OCR can
        # be linked to the asset coordinate space. A second pass may refine the
        # semantic role with newly recognized text.
        apply_asset_inspection(asset, db)
        preliminary_blocks, ocr_source = extract_ocr_blocks(asset)
        recognized_text = "\n".join(str(block.get("text") or "") for block in preliminary_blocks)
        if recognized_text and asset.role_source != "manual":
            role, confidence = recommend_asset_role(
                asset.filename,
                asset.source_type,
                asset.file_path,
                recognized_text,
            )
            asset.asset_role = role
            asset.role_confidence = confidence
            asset.role_source = "auto"
        vision_result = (vision_analyzer or _configured_vision_analyzer)(asset)
        allowed_vision_roles = {
            "product_main", "product_detail", "feature", "usage_scene", "components",
            "material_detail", "package", "shipping_info", "spec_reference",
            "supplier_banner", "decorative", "unidentifiable_reference",
        }
        if (
            vision_result
            and asset.role_source != "manual"
            and vision_result.get("role") in allowed_vision_roles
        ):
            asset.asset_role = vision_result["role"]
            asset.role_confidence = max(0.0, min(1.0, float(vision_result.get("confidence") or 0.0)))
            asset.role_source = "vision"
        db.flush()
        ocr_blocks = preliminary_blocks
        active_translator = translator or _configured_ai_translator
        translations = [_translate_ocr_block(block, active_translator) for block in ocr_blocks]
        warnings = list(asset.quality_warnings or [])
        if not ocr_blocks:
            warnings.append(ocr_source.upper())
        if any(item["translation_status"] == "needs_review" for item in translations):
            warnings.append("OCR_TRANSLATION_REVIEW_REQUIRED")
        combined_text = " ".join(str(block.get("text") or "") for block in ocr_blocks).lower()
        if any(signal in combined_text for signal in ("watermark", "logo", "店铺", "供应商", "品牌")):
            warnings.append("SUPPLIER_LOGO_OR_WATERMARK")
        if vision_result and vision_result.get("logo_or_watermark"):
            warnings.append("SUPPLIER_LOGO_OR_WATERMARK")

        rights_status, final_eligible = _rights_state(asset, warnings)
        record.status = "completed"
        record.asset_role = asset.asset_role
        record.rights_status = rights_status
        record.final_output_eligible = final_eligible
        record.duplicate_asset_ids = _duplicate_asset_ids(asset, db)
        record.warnings = list(dict.fromkeys(warnings))
        record.ocr_blocks = ocr_blocks
        record.translation_blocks = translations
        record.numeric_evidence = list(
            dict.fromkeys(
                value
                for item in translations
                for value in item["preserved_numeric_values"]
            )
        )
        record.analysis_metadata = _visual_analysis_metadata(asset, ocr_blocks, vision_result)
        record.completed_at = datetime.datetime.utcnow()
    except Exception as exc:  # Record one asset's failure without failing the project.
        record.status = "failed"
        record.error_code = "ASSET_INSPECTION_FAILED"
        record.error_message = str(exc)[:500]
        record.warnings = ["ASSET_INSPECTION_FAILED"]
        record.completed_at = datetime.datetime.utcnow()
    return record


def run_project_asset_inspections(
    project_id: str, db: Session, asset_ids: Iterable[str] | None = None
) -> list[AssetInspectionRecord]:
    query = db.query(Asset).filter(Asset.project_id == project_id)
    if asset_ids is not None:
        selected_ids = list(dict.fromkeys(asset_ids))
        if not selected_ids:
            return []
        query = query.filter(Asset.id.in_(selected_ids))
    assets = [asset for asset in query.all() if (asset.mime_type or "").startswith("image/")]
    return [run_asset_inspection(asset, db) for asset in assets]


def latest_asset_inspections(project_id: str, db: Session) -> list[AssetInspectionRecord]:
    """Return one latest analysis record per asset for the asset board."""
    records = (
        db.query(AssetInspectionRecord)
        .filter(AssetInspectionRecord.project_id == project_id)
        .order_by(AssetInspectionRecord.asset_id, AssetInspectionRecord.analysis_version.desc())
        .all()
    )
    latest: dict[str, AssetInspectionRecord] = {}
    for record in records:
        latest.setdefault(record.asset_id, record)
    return list(latest.values())


def review_asset_inspection(
    asset: Asset,
    current: AssetInspectionRecord,
    db: Session,
    *,
    translated_text_by_index: dict[int, str] | None = None,
    confirm_identity: bool = False,
) -> AssetInspectionRecord:
    """Create a seller-reviewed version without mutating prior evidence."""
    translations = copy.deepcopy(current.translation_blocks or [])
    for index, translated_text in (translated_text_by_index or {}).items():
        if index < 0 or index >= len(translations):
            raise ValueError(f"Translation block index out of range: {index}")
        cleaned = translated_text.strip()
        if not cleaned:
            raise ValueError("Confirmed translation cannot be empty")
        translations[index]["translated_text"] = cleaned
        translations[index]["translation_status"] = "seller_confirmed"
        translations[index]["translation_provider"] = "seller_review"

    if confirm_identity:
        asset.identity_status = "confirmed"

    warnings = [
        warning
        for warning in (current.warnings or [])
        if warning != "OCR_TRANSLATION_REVIEW_REQUIRED"
    ]
    if any(item.get("translation_status") == "needs_review" for item in translations):
        warnings.append("OCR_TRANSLATION_REVIEW_REQUIRED")
    rights_status, final_eligible = _rights_state(asset, warnings)
    record = AssetInspectionRecord(
        project_id=asset.project_id,
        asset_id=asset.id,
        analysis_version=current.analysis_version + 1,
        status="completed",
        analyzer_version="seller-review-v1",
        asset_role=asset.asset_role,
        rights_status=rights_status,
        final_output_eligible=final_eligible,
        duplicate_asset_ids=copy.deepcopy(current.duplicate_asset_ids or []),
        warnings=list(dict.fromkeys(warnings)),
        ocr_blocks=copy.deepcopy(current.ocr_blocks or []),
        translation_blocks=translations,
        numeric_evidence=copy.deepcopy(current.numeric_evidence or []),
        analysis_metadata={
            **copy.deepcopy(current.analysis_metadata or {}),
            "identity_status": asset.identity_status,
            "seller_reviewed": True,
        },
        completed_at=datetime.datetime.utcnow(),
    )
    db.add(record)
    db.flush()
    return record


TEXT_EVIDENCE_ROLES = {
    "feature",
    "product_detail",
    "material_detail",
    "spec_reference",
    "supplier_banner",
    "shipping_info",
}


def project_asset_understanding_blockers(
    project_id: str,
    db: Session,
    *,
    asset_ids: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """Return Sprint 3 gate blockers for the seller-selected asset bundle."""
    query = db.query(Asset).filter(Asset.project_id == project_id, Asset.mime_type.like("image/%"))
    selected_ids = list(dict.fromkeys(asset_ids or []))
    if selected_ids:
        query = query.filter(Asset.id.in_(selected_ids))
    assets = query.all()
    latest = {record.asset_id: record for record in latest_asset_inspections(project_id, db)}
    blockers: list[dict[str, str]] = []

    for asset in assets:
        record = latest.get(asset.id)
        label = asset.filename or asset.id
        if record is None:
            blockers.append({"asset_id": asset.id, "code": "INSPECTION_MISSING", "message": f"{label}: 이미지 분석이 필요합니다."})
            continue
        if record.status != "completed":
            blockers.append({"asset_id": asset.id, "code": "INSPECTION_INCOMPLETE", "message": f"{label}: 이미지 분석을 다시 실행해 주세요."})
            continue
        if not record.asset_role or record.asset_role in {"unknown", "unidentifiable_reference"}:
            blockers.append({"asset_id": asset.id, "code": "ROLE_UNCONFIRMED", "message": f"{label}: 이미지 역할을 선택해 주세요."})
        if not record.rights_status:
            blockers.append({"asset_id": asset.id, "code": "RIGHTS_UNCONFIRMED", "message": f"{label}: 이미지 권리 상태를 확인해 주세요."})
        if any(item.get("translation_status") == "needs_review" for item in (record.translation_blocks or [])):
            blockers.append({"asset_id": asset.id, "code": "TRANSLATION_UNCONFIRMED", "message": f"{label}: OCR 번역을 확인해 주세요."})
        if record.asset_role in TEXT_EVIDENCE_ROLES and not record.ocr_blocks:
            blockers.append({"asset_id": asset.id, "code": "OCR_EVIDENCE_MISSING", "message": f"{label}: 텍스트 근거 OCR이 필요합니다."})
        if any((block.get("bbox") or {}).get("width") is None for block in (record.ocr_blocks or [])):
            blockers.append({"asset_id": asset.id, "code": "OCR_COORDINATES_MISSING", "message": f"{label}: OCR 위치 정보가 필요합니다."})

    if assets and not any(asset.asset_role == "product_main" and asset.identity_status == "confirmed" for asset in assets):
        blockers.append({"asset_id": "", "code": "PRODUCT_IDENTITY_UNCONFIRMED", "message": "대표 상품 이미지를 선택해 상품 정체성을 확인해 주세요."})
    return blockers
