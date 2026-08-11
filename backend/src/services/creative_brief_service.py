"""LG-7 review/reference boundaries and immutable creative brief compiler."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from typing import Any
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun, Asset, BrandKitVersion, CompiledPromptArtifact, FactSnapshot, ProductCreativeBriefVersion,
    ProductFact, ProductProject, ReferenceInputVersion, ReferenceInsightVersion,
    PromptPackVersion, ReviewInputVersion, ReviewInsightVersion, SellerCreativeDirectionVersion,
    WorkflowGateEvent,
)
from src.services.creative_brief_llm_service import (
    CreativeBriefLLMError,
    generate_structured_creative_brief,
)
from src.services.provider_adapters import TextProviderProtocol

COMPILER_VERSION = "lg7-creative-brief-v1"


class CreativeBriefInputError(ValueError):
    def __init__(self, code: str, message: str, remedy: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy

    def as_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "remedy": self.remedy}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalize_interaction_mode(value: str | None) -> str:
    # Runs created before LG-7 have no explicit mode. Preserve their manual
    # approval behavior; new runs explicitly persist the new `quick` default.
    normalized = (value or "expert").strip().lower()
    if normalized == "quality":
        return "expert"
    if normalized not in {"quick", "expert"}:
        raise ValueError("interaction_mode must be quick or expert")
    return normalized


def _parse_review_bytes_legacy_1(filename: str, content: bytes) -> tuple[str, str]:
    if not content:
        raise CreativeBriefInputError("REVIEW_FILE_EMPTY", "리뷰 파일이 비어 있습니다.", "내용이 있는 CSV, XLSX 또는 TXT 파일을 선택해 주세요.")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "csv", "xlsx"}:
        raise CreativeBriefInputError("REVIEW_FILE_FORMAT_UNSUPPORTED", "지원하지 않는 리뷰 파일 형식입니다.", "CSV, XLSX 또는 TXT 파일로 다시 업로드해 주세요.")
    if suffix in {"txt", "csv"}:
        text = ""
        for encoding in ("utf-8-sig", "cp949"):
            try:
                text = content.decode(encoding, errors="strict")
                break
            except UnicodeDecodeError:
                continue
        if not text or "\x00" in text or "\ufffd" in text:
            raise CreativeBriefInputError("REVIEW_FILE_CORRUPT", "리뷰 파일을 정상적인 텍스트로 읽을 수 없습니다.", "UTF-8 또는 CP949로 저장한 파일인지 확인해 주세요.")
        if suffix == "csv":
            try:
                rows = csv.reader(io.StringIO(text), strict=True)
                text = "\n".join(" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)
            except csv.Error as exc:
                raise CreativeBriefInputError("REVIEW_FILE_CORRUPT", "CSV 구조가 손상되었습니다.", "따옴표와 열 구분자를 확인한 뒤 다시 저장해 주세요.") from exc
        if not text.strip():
            raise CreativeBriefInputError("REVIEW_FILE_EMPTY", "리뷰 파일에 분석할 문장이 없습니다.", "리뷰 문장이 포함된 파일을 선택해 주세요.")
        return suffix, text.strip()
    if suffix == "xlsx":
        # Read the OpenXML package without adding a heavyweight spreadsheet dependency.
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                names = package.namelist()
                if "[Content_Types].xml" not in names or not any(name.startswith("xl/worksheets/sheet") for name in names):
                    raise CreativeBriefInputError("REVIEW_FILE_CORRUPT", "XLSX 구조가 올바르지 않습니다.", "스프레드시트에서 XLSX 형식으로 다시 저장해 주세요.")
                shared: list[str] = []
                if "xl/sharedStrings.xml" in names:
                    root = ElementTree.fromstring(package.read("xl/sharedStrings.xml"))
                    shared = ["".join(node.itertext()) for node in root.iter() if node.tag.endswith("}si")]
                lines: list[str] = []
                for name in sorted(item for item in names if item.startswith("xl/worksheets/sheet") and item.endswith(".xml")):
                    root = ElementTree.fromstring(package.read(name))
                    cells: list[str] = []
                    for cell in root.iter():
                        if not cell.tag.endswith("}c"):
                            continue
                        value = next((node.text or "" for node in cell if node.tag.endswith("}v")), "")
                        if cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                            value = shared[int(value)]
                        elif cell.attrib.get("t") == "inlineStr":
                            value = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                        if value.strip():
                            cells.append(value.strip())
                    if cells:
                        lines.append(" | ".join(cells))
        except CreativeBriefInputError:
            raise
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, OSError) as exc:
            raise CreativeBriefInputError("REVIEW_FILE_CORRUPT", "XLSX 파일이 손상되어 읽을 수 없습니다.", "파일을 다시 내려받거나 XLSX로 다시 저장해 주세요.") from exc
        body = "\n".join(lines).strip()
        if not body:
            raise CreativeBriefInputError("REVIEW_FILE_EMPTY", "스프레드시트에 분석할 리뷰가 없습니다.", "텍스트가 들어 있는 셀을 추가해 주세요.")
        return suffix, body
    raise AssertionError("validated suffix")


def _strict_review_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            decoded = content.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        if decoded and "\x00" not in decoded and "\ufffd" not in decoded:
            return decoded
    raise CreativeBriefInputError(
        "REVIEW_FILE_CORRUPT", "리뷰 파일을 정상적인 텍스트로 읽을 수 없습니다.",
        "UTF-8 또는 CP949로 저장한 파일인지 확인해 주세요.",
    )


def _parse_review_bytes_legacy_2(filename: str, content: bytes) -> tuple[str, str]:
    """Strict LG-7R parser; this replaces the compatibility definition above."""
    if not content:
        raise CreativeBriefInputError(
            "REVIEW_FILE_EMPTY", "리뷰 파일이 비어 있습니다.",
            "내용이 있는 CSV, XLSX 또는 TXT 파일을 선택해 주세요.",
        )
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "csv", "xlsx"}:
        raise CreativeBriefInputError(
            "REVIEW_FILE_FORMAT_UNSUPPORTED", "지원하지 않는 리뷰 파일 형식입니다.",
            "CSV, XLSX 또는 TXT 파일로 다시 업로드해 주세요.",
        )
    if suffix in {"txt", "csv"}:
        text = _strict_review_text(content)
        if suffix == "csv":
            try:
                rows = csv.reader(io.StringIO(text), strict=True)
                text = "\n".join(" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)
            except csv.Error as exc:
                raise CreativeBriefInputError(
                    "REVIEW_FILE_CORRUPT", "CSV 구조가 손상되었습니다.",
                    "따옴표와 열 구분자를 확인한 뒤 다시 저장해 주세요.",
                ) from exc
        if not text.strip():
            raise CreativeBriefInputError(
                "REVIEW_FILE_EMPTY", "리뷰 파일에 분석할 문장이 없습니다.",
                "리뷰 문장이 포함된 파일을 선택해 주세요.",
            )
        return suffix, text.strip()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            names = package.namelist()
            if "[Content_Types].xml" not in names or not any(
                name.startswith("xl/worksheets/sheet") and name.endswith(".xml") for name in names
            ):
                raise CreativeBriefInputError(
                    "REVIEW_FILE_CORRUPT", "XLSX 구조가 올바르지 않습니다.",
                    "스프레드시트에서 XLSX 형식으로 다시 저장해 주세요.",
                )
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(package.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root.iter() if node.tag.endswith("}si")]
            lines: list[str] = []
            for name in sorted(item for item in names if item.startswith("xl/worksheets/sheet") and item.endswith(".xml")):
                root = ElementTree.fromstring(package.read(name))
                cells: list[str] = []
                for cell in root.iter():
                    if not cell.tag.endswith("}c"):
                        continue
                    value = next((node.text or "" for node in cell if node.tag.endswith("}v")), "")
                    if cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                    if value.strip():
                        cells.append(value.strip())
                if cells:
                    lines.append(" | ".join(cells))
    except CreativeBriefInputError:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, OSError) as exc:
        raise CreativeBriefInputError(
            "REVIEW_FILE_CORRUPT", "XLSX 파일이 손상되어 읽을 수 없습니다.",
            "파일을 다시 내려받거나 XLSX로 다시 저장해 주세요.",
        ) from exc
    body = "\n".join(lines).strip()
    if not body:
        raise CreativeBriefInputError(
            "REVIEW_FILE_EMPTY", "스프레드시트에 분석할 리뷰가 없습니다.",
            "텍스트가 들어 있는 셀을 추가해 주세요.",
        )
    return suffix, body


def _parse_review_bytes_legacy_3(filename: str, content: bytes) -> tuple[str, str]:
    """Parse an uploaded review file with strict, typed validation."""
    if not content:
        raise CreativeBriefInputError(
            "REVIEW_FILE_EMPTY", "리뷰 파일이 비어 있습니다.",
            "내용이 있는 CSV, XLSX 또는 TXT 파일을 선택해 주세요.",
        )
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "csv", "xlsx"}:
        raise CreativeBriefInputError(
            "REVIEW_FILE_FORMAT_UNSUPPORTED", "지원하지 않는 리뷰 파일 형식입니다.",
            "CSV, XLSX 또는 TXT 파일로 다시 업로드해 주세요.",
        )
    if suffix in {"txt", "csv"}:
        text = ""
        for encoding in ("utf-8-sig", "cp949"):
            try:
                text = content.decode(encoding, errors="strict")
                break
            except UnicodeDecodeError:
                continue
        if not text or "\x00" in text or "\ufffd" in text:
            raise CreativeBriefInputError(
                "REVIEW_FILE_CORRUPT", "리뷰 파일을 정상적인 텍스트로 읽을 수 없습니다.",
                "UTF-8 또는 CP949로 저장한 파일인지 확인해 주세요.",
            )
        if suffix == "csv":
            try:
                rows = csv.reader(io.StringIO(text), strict=True)
                text = "\n".join(" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)
            except csv.Error as exc:
                raise CreativeBriefInputError(
                    "REVIEW_FILE_CORRUPT", "CSV 구조가 손상되었습니다.",
                    "따옴표와 열 구분자를 확인한 뒤 다시 저장해 주세요.",
                ) from exc
        if not text.strip():
            raise CreativeBriefInputError(
                "REVIEW_FILE_EMPTY", "리뷰 파일에 분석할 문장이 없습니다.",
                "리뷰 문장이 포함된 파일을 선택해 주세요.",
            )
        return suffix, text.strip()

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            names = package.namelist()
            if "[Content_Types].xml" not in names or not any(
                name.startswith("xl/worksheets/sheet") and name.endswith(".xml") for name in names
            ):
                raise CreativeBriefInputError(
                    "REVIEW_FILE_CORRUPT", "XLSX 구조가 올바르지 않습니다.",
                    "스프레드시트에서 XLSX 형식으로 다시 저장해 주세요.",
                )
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ElementTree.fromstring(package.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root.iter() if node.tag.endswith("}si")]
            lines: list[str] = []
            sheets = sorted(
                item for item in names
                if item.startswith("xl/worksheets/sheet") and item.endswith(".xml")
            )
            for name in sheets:
                root = ElementTree.fromstring(package.read(name))
                cells: list[str] = []
                for cell in root.iter():
                    if not cell.tag.endswith("}c"):
                        continue
                    value = next((node.text or "" for node in cell if node.tag.endswith("}v")), "")
                    if cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                    if value.strip():
                        cells.append(value.strip())
                if cells:
                    lines.append(" | ".join(cells))
    except CreativeBriefInputError:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, OSError) as exc:
        raise CreativeBriefInputError(
            "REVIEW_FILE_CORRUPT", "XLSX 파일이 손상되어 읽을 수 없습니다.",
            "파일을 다시 내려받거나 XLSX로 다시 저장해 주세요.",
        ) from exc
    body = "\n".join(lines).strip()
    if not body:
        raise CreativeBriefInputError(
            "REVIEW_FILE_EMPTY", "스프레드시트에 분석할 리뷰가 없습니다.",
            "텍스트가 들어 있는 셀을 추가해 주세요.",
        )
    return suffix, body


def parse_review_bytes(filename: str, content: bytes) -> tuple[str, str]:
    """Return normalized review text or a stable, actionable LG-7R error."""
    if not content:
        raise CreativeBriefInputError(
            "REVIEW_FILE_EMPTY",
            "리뷰 파일이 비어 있습니다.",
            "내용이 있는 CSV, XLSX 또는 TXT 파일을 선택해 주세요.",
        )

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "csv", "xlsx"}:
        raise CreativeBriefInputError(
            "REVIEW_FILE_UNSUPPORTED",
            "지원하지 않는 리뷰 파일 형식입니다.",
            "CSV, XLSX 또는 TXT 파일로 다시 업로드해 주세요.",
        )

    if suffix in {"txt", "csv"}:
        text: str | None = None
        for encoding in ("utf-8-sig", "cp949"):
            try:
                candidate = content.decode(encoding, errors="strict")
            except UnicodeDecodeError:
                continue
            if "\x00" not in candidate and "\ufffd" not in candidate:
                text = candidate
                break
        if text is None:
            raise CreativeBriefInputError(
                "REVIEW_FILE_ENCODING_INVALID",
                "리뷰 파일의 문자 인코딩을 확인할 수 없습니다.",
                "UTF-8 또는 CP949로 저장한 뒤 다시 업로드해 주세요.",
            )
        if suffix == "csv":
            try:
                rows = csv.reader(io.StringIO(text), strict=True)
                text = "\n".join(
                    " | ".join(cell.strip() for cell in row if cell.strip())
                    for row in rows
                )
            except csv.Error as exc:
                raise CreativeBriefInputError(
                    "REVIEW_CSV_CORRUPT",
                    "CSV 구조가 손상되었습니다.",
                    "따옴표와 열 구분자를 확인한 뒤 다시 저장해 주세요.",
                ) from exc
        if not text.strip():
            raise CreativeBriefInputError(
                "REVIEW_FILE_EMPTY",
                "리뷰 파일에 분석할 문장이 없습니다.",
                "리뷰 문장이 포함된 파일을 선택해 주세요.",
            )
        return suffix, text.strip()

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            names = package.namelist()
            sheets = sorted(
                name for name in names
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            if not sheets:
                raise CreativeBriefInputError(
                    "REVIEW_XLSX_CORRUPT",
                    "XLSX 구조가 올바르지 않습니다.",
                    "스프레드시트에서 XLSX 형식으로 다시 저장해 주세요.",
                )

            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ElementTree.fromstring(package.read("xl/sharedStrings.xml"))
                shared = [
                    "".join(node.itertext())
                    for node in shared_root.iter()
                    if node.tag.endswith("}si")
                ]

            lines: list[str] = []
            for name in sheets:
                root = ElementTree.fromstring(package.read(name))
                cells: list[str] = []
                for cell in root.iter():
                    if not cell.tag.endswith("}c"):
                        continue
                    value = next(
                        (node.text or "" for node in cell if node.tag.endswith("}v")),
                        "",
                    )
                    if cell.attrib.get("t") == "s" and value.isdigit():
                        index = int(value)
                        value = shared[index] if index < len(shared) else ""
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(
                            node.text or "" for node in cell.iter() if node.tag.endswith("}t")
                        )
                    if value.strip():
                        cells.append(value.strip())
                if cells:
                    lines.append(" | ".join(cells))
    except CreativeBriefInputError:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, OSError) as exc:
        raise CreativeBriefInputError(
            "REVIEW_XLSX_CORRUPT",
            "XLSX 파일이 손상되어 읽을 수 없습니다.",
            "파일을 다시 내려받거나 XLSX로 다시 저장해 주세요.",
        ) from exc

    body = "\n".join(lines).strip()
    if not body:
        raise CreativeBriefInputError(
            "REVIEW_FILE_EMPTY",
            "스프레드시트에 분석할 리뷰가 없습니다.",
            "텍스트가 들어 있는 셀을 추가해 주세요.",
        )
    return suffix, body


def allowed_review_assets(db: Session, project_id: str) -> list[Asset]:
    return db.query(Asset).filter(
        Asset.project_id == project_id,
        Asset.usage_status.notin_(["blocked", "ai_generated"]),
    ).order_by(Asset.created_at.desc()).all()


def _review_text_from_asset_legacy(asset: Asset) -> str:
    if (asset.ocr_text or "").strip():
        return str(asset.ocr_text).strip()
    path = Path(asset.file_path)
    if path.suffix.lower() not in {".txt", ".csv", ".xlsx"} or not path.is_file():
        raise CreativeBriefInputError("REVIEW_ASSET_TEXT_UNAVAILABLE", "선택한 수집 자료에 분석 가능한 텍스트가 없습니다.", "OCR 텍스트가 있는 자료를 선택하거나 CSV, XLSX, TXT 파일을 직접 올려 주세요.")
    _, text = parse_review_bytes(asset.filename, path.read_bytes())
    return text


def review_text_from_asset(asset: Asset) -> str:
    """Load review text from an allowed collected asset."""
    if (asset.ocr_text or "").strip():
        return str(asset.ocr_text).strip()
    path = Path(asset.file_path)
    if path.suffix.lower() not in {".txt", ".csv", ".xlsx"} or not path.is_file():
        raise CreativeBriefInputError(
            "REVIEW_ASSET_TEXT_UNAVAILABLE",
            "선택한 수집 자료에 분석 가능한 텍스트가 없습니다.",
            "OCR 텍스트가 있는 자료를 선택하거나 CSV, XLSX, TXT 파일을 직접 올려 주세요.",
        )
    _, text = parse_review_bytes(asset.filename, path.read_bytes())
    return text


def _next_version(db: Session, model: type, project_id: str) -> int:
    return int(db.query(func.max(model.version)).filter(model.project_id == project_id).scalar() or 0) + 1


def _phrases(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n.!?]+", text) if len(item.strip()) >= 4]


def analyze_reviews(text: str) -> dict[str, Any]:
    lines = _phrases(text)
    negative_tokens = ("아쉽", "불편", "약하", "무겁", "소음", "고장", "느리", "작다", "불량")
    positive_tokens = ("좋", "편하", "추천", "만족", "강하", "가볍", "조용", "예쁘")
    improvement_tokens = ("개선", "바라", "했으면", "필요", "아쉽", "불편")
    target_tokens = ("직장인", "학생", "육아", "캠핑", "여행", "출퇴근", "가정", "사무실")
    complaints = [line for line in lines if any(token in line for token in negative_tokens)][:12]
    purchase_reasons = [line for line in lines if any(token in line for token in positive_tokens)][:12]
    improvement_requests = [line for line in lines if any(token in line for token in improvement_tokens)][:12]
    inferred_targets = sorted({token for line in lines for token in target_tokens if token in line})
    claim_candidates = [
        line for line in lines
        if re.search(r"\d|효능|인증|구성|포함|용량|시간|출력|전력", line)
    ][:12]
    words = re.findall(r"[가-힣A-Za-z]{2,}", text.casefold())
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    repeated_language = [word for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])) if count >= 2][:12]
    return {
        "repeated_complaints": complaints,
        "purchase_reasons": purchase_reasons,
        "positive_signals": purchase_reasons,
        "improvement_requests": improvement_requests,
        "claim_candidates": claim_candidates,
        "repeated_language": repeated_language,
        "inferred_targets": inferred_targets,
        "claim_policy": "creative_direction_only_never_approved_fact",
    }


def analyze_reviews(text: str) -> dict[str, Any]:
    """Extract creative signals while blocking fact promotion from reviews."""
    lines = _phrases(text)
    negative_tokens = ("아쉬", "불편", "약하", "무거", "소음", "고장", "느리", "작다", "불량")
    positive_tokens = ("좋", "편하", "추천", "만족", "강하", "가볍", "조용", "예쁘")
    improvement_tokens = ("개선", "바라", "했으면", "필요", "아쉬", "불편")
    target_tokens = ("직장인", "학생", "육아", "캠핑", "여행", "출퇴근", "가정", "사무실")
    complaints = [line for line in lines if any(token in line for token in negative_tokens)][:12]
    purchase_reasons = [line for line in lines if any(token in line for token in positive_tokens)][:12]
    improvement_requests = [line for line in lines if any(token in line for token in improvement_tokens)][:12]
    inferred_targets = sorted({token for line in lines for token in target_tokens if token in line})
    claim_candidates = [line for line in lines if re.search(r"\d|성능|인증|구성|포함|용량|시간|출력|압력", line)][:12]
    words = re.findall(r"[가-힣A-Za-z]{2,}", text.casefold())
    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    repeated_language = [
        word for word, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= 2
    ][:12]
    return {
        "repeated_complaints": complaints,
        "purchase_reasons": purchase_reasons,
        "positive_signals": purchase_reasons,
        "improvement_requests": improvement_requests,
        "claim_candidates": claim_candidates,
        "repeated_language": repeated_language,
        "inferred_targets": inferred_targets,
        "claim_policy": "creative_direction_only_never_approved_fact",
    }


def analyze_reference(text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    allowed_signals = {"palette", "layout", "section_flow", "shoot_mood", "copy_tone"}
    selected_signals = set(metadata.get("selected_signals") or allowed_signals) & allowed_signals
    clean = re.sub(r"https?://\S+", "", text or "")
    clean = re.sub(r"(?:logo|로고|상표|브랜드)\s*[:：]?\s*\S+", "", clean, flags=re.IGNORECASE)
    lowered = clean.casefold()
    palettes = [token for token in ("neutral", "pastel", "dark", "bright", "monochrome") if token in lowered]
    layouts = [token for token in ("mobile_first", "grid", "editorial", "minimal", "hero_led") if token in lowered]
    return {
        "palette_signals": (palettes or ["neutral"]) if "palette" in selected_signals else [],
        "layout_signals": (layouts or ["mobile_first"]) if "layout" in selected_signals else [],
        "section_flow_signals": ["problem", "benefit", "proof", "details", "cta"] if "section_flow" in selected_signals else [],
        "shoot_mood_signals": ["clean_product_led"] if "shoot_mood" in selected_signals else [],
        "copy_tone_signals": ["clear", "trustworthy"] if "copy_tone" in selected_signals else [],
        "excluded_replication": ["source_copy", "source_logo", "source_product_image", "unique_design_expression"],
        "source_metadata": {**metadata, "selected_signals": sorted(selected_signals)},
    }


def create_review_input(db: Session, *, project: ProductProject, user_id: str, input_format: str,
                        text: str, source_label: str = "", consent_status: str = "unconfirmed",
                        rights_status: str = "unverified", source_metadata: dict[str, Any] | None = None,
                        source_asset_id: str | None = None) -> ReviewInputVersion:
    body = text.strip()
    if not body:
        raise CreativeBriefInputError("REVIEW_CONTENT_EMPTY", "리뷰 내용이 비어 있습니다.", "리뷰를 입력하거나 기존 수집 자료를 선택해 주세요.")
    content_hash = canonical_hash(body)
    duplicate = db.query(ReviewInputVersion).filter_by(project_id=project.id, content_hash=content_hash).first()
    if duplicate:
        setattr(duplicate, "_deduplicated", True)
        return duplicate
    row = ReviewInputVersion(
        workspace_id=project.workspace_id, project_id=project.id,
        version=_next_version(db, ReviewInputVersion, project.id), input_format=input_format,
        source_label=source_label or None, source_asset_id=source_asset_id,
        source_metadata=source_metadata or {}, consent_status=consent_status,
        rights_status=rights_status, content_text=body, content_hash=content_hash, created_by=user_id,
    )
    db.add(row); db.flush()
    insights = analyze_reviews(body)
    db.add(ReviewInsightVersion(
        project_id=project.id, review_input_version_id=row.id, insights_json=insights,
        content_hash=canonical_hash(insights), fact_promotion_status="blocked", usage_status="available",
    ))
    db.commit(); db.refresh(row)
    return row


def create_reference_input(db: Session, *, project: ProductProject, user_id: str, input_kind: str,
                           text: str = "", source_url: str = "", asset_id: str | None = None,
                           rights_status: str = "unverified", source_metadata: dict[str, Any] | None = None) -> ReferenceInputVersion:
    if input_kind not in {"url", "image", "pdf", "text"}:
        raise ValueError("Reference kind must be url, image, pdf, or text.")
    if asset_id:
        asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project.id).first()
        if asset is None:
            raise ValueError("Reference asset does not belong to this project.")
    payload = {"kind": input_kind, "text": text.strip(), "url": source_url.strip(), "asset_id": asset_id}
    if not any((payload["text"], payload["url"], payload["asset_id"])):
        raise ValueError("Reference content is empty.")
    usage_scope = (
        "final_output_eligible"
        if rights_status in {"verified", "seller_owned", "licensed"}
        else "analysis_only"
    )
    row = ReferenceInputVersion(
        workspace_id=project.workspace_id, project_id=project.id,
        version=_next_version(db, ReferenceInputVersion, project.id), input_kind=input_kind,
        source_url=source_url.strip() or None, asset_id=asset_id, content_text=text.strip() or None,
        source_metadata=source_metadata or {}, rights_status=rights_status, usage_scope=usage_scope,
        content_hash=canonical_hash(payload), created_by=user_id,
    )
    db.add(row); db.flush()
    signals = analyze_reference(text or source_url, source_metadata)
    db.add(ReferenceInsightVersion(
        project_id=project.id, reference_input_version_id=row.id,
        abstract_signals_json=signals, content_hash=canonical_hash(signals), usage_status="available",
    ))
    db.commit(); db.refresh(row)
    return row


def create_creative_direction(db: Session, *, project: ProductProject, user_id: str,
                              desired_mood: list[str], target_audience: str,
                              emphasis: list[str], forbidden_scenes: list[str]) -> SellerCreativeDirectionVersion:
    payload = {"desired_mood": desired_mood, "target_audience": target_audience.strip(),
               "emphasis": emphasis, "forbidden_scenes": forbidden_scenes}
    row = SellerCreativeDirectionVersion(
        project_id=project.id, version=_next_version(db, SellerCreativeDirectionVersion, project.id),
        desired_mood=desired_mood, target_audience=target_audience.strip() or None,
        emphasis=emphasis, forbidden_scenes=forbidden_scenes, content_hash=canonical_hash(payload), created_by=user_id,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def _default_section_strategy(approved_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {"section": "problem", "target": "고객 문제 공감", "objective": "구매 맥락을 과장 없이 설명합니다.",
         "fact_ids": [], "copy_classification": "creative", "source": "creative_insight",
         "claim_policy": "narrative_non_claim"},
        {"section": "benefit", "target": "핵심 이익", "objective": "승인된 사실로 제품 이점을 설명합니다.",
         "fact_ids": approved_ids, "copy_classification": "fact", "source": "approved_facts",
         "claim_policy": "approved_fact_required"},
        {"section": "proof", "target": "신뢰 근거", "objective": "승인된 사양과 근거를 보여줍니다.",
         "fact_ids": approved_ids, "copy_classification": "fact", "source": "approved_facts",
         "claim_policy": "approved_fact_required"},
        {"section": "details", "target": "구매 정보", "objective": "제품 사양과 구성을 안내합니다.",
         "fact_ids": approved_ids, "copy_classification": "fact", "source": "approved_facts",
         "claim_policy": "approved_fact_required"},
        {"section": "cta", "target": "다음 행동", "objective": "판매 채널에 맞춰 안전하게 행동을 유도합니다.",
         "fact_ids": [], "copy_classification": "creative", "source": "seller_direction",
         "claim_policy": "narrative_non_claim"},
    ]


def compile_creative_brief(db: Session, run: AgentRun, *, llm_provider: TextProviderProtocol | None = None) -> ProductCreativeBriefVersion:
    snapshot_data = run.input_snapshot or {}
    fact_snapshot = db.query(FactSnapshot).filter_by(
        id=snapshot_data.get("approved_fact_snapshot_id"), project_id=run.project_id,
    ).one()
    artifact = db.query(CompiledPromptArtifact).filter_by(run_id=run.id).one()
    direction = db.query(SellerCreativeDirectionVersion).filter_by(project_id=run.project_id).order_by(
        SellerCreativeDirectionVersion.version.desc()).first()
    review_insights = db.query(ReviewInsightVersion).filter_by(project_id=run.project_id, usage_status="available").all()
    reference_insights = db.query(ReferenceInsightVersion).filter_by(project_id=run.project_id, usage_status="available").all()
    previous = db.query(ProductCreativeBriefVersion).filter_by(project_id=run.project_id).order_by(
        ProductCreativeBriefVersion.version.desc()).first()
    approved_ids = [str(item["id"]) for item in (fact_snapshot.facts_json or []) if item.get("id")]
    direction_payload = {
        "desired_mood": list(direction.desired_mood or []) if direction else list(snapshot_data.get("desired_mood") or []),
        "target_audience": direction.target_audience if direction else "",
        "emphasis": list(direction.emphasis or []) if direction else [],
        "forbidden_scenes": list(direction.forbidden_scenes or []) if direction else [],
    }
    review_payloads = [dict(item.insights_json or {}) for item in review_insights]
    customer_problem = [
        value
        for insight in review_payloads
        for value in list(insight.get("repeated_complaints") or []) + list(insight.get("improvement_requests") or [])
    ]
    purchase_motivation = [
        value for insight in review_payloads for value in list(insight.get("purchase_reasons") or [])
    ]
    inferred_targets = sorted({
        str(value) for insight in review_payloads for value in list(insight.get("inferred_targets") or [])
    })
    target_audience = direction_payload["target_audience"] or ", ".join(inferred_targets)
    forbidden_claims = ["unapproved_numeric_claim", "review_derived_claim", "unsupported_effect", "unsupported_certification"]
    section_strategy = [
        {"section": "problem", "target": "고객 문제 공감", "objective": "구매 맥락을 과장 없이 설명합니다.", "fact_ids": [], "copy_classification": "creative", "source": "creative_insight", "claim_policy": "narrative_non_claim"},
        {"section": "benefit", "target": "핵심 효익", "objective": "승인된 사실로 제품 이점을 설명합니다.", "fact_ids": approved_ids, "copy_classification": "fact", "source": "approved_facts", "claim_policy": "approved_fact_required"},
        {"section": "proof", "target": "신뢰 근거", "objective": "승인된 사양과 근거를 보여줍니다.", "fact_ids": approved_ids, "copy_classification": "fact", "source": "approved_facts", "claim_policy": "approved_fact_required"},
        {"section": "details", "target": "구매 정보", "objective": "제품 사양과 구성을 안내합니다.", "fact_ids": approved_ids, "copy_classification": "fact", "source": "approved_facts", "claim_policy": "approved_fact_required"},
        {"section": "cta", "target": "다음 행동", "objective": "판매자 톤에 맞춰 안전하게 행동을 유도합니다.", "fact_ids": [], "copy_classification": "creative", "source": "seller_direction", "claim_policy": "narrative_non_claim"},
    ]
    section_strategy = _default_section_strategy(approved_ids)
    llm_metadata = {"mode": "deterministic", "attempts": 0, "repairs": 0}
    if run.mode == "real" or llm_provider is not None:
        if llm_provider is None:
            from src.services.llm_router import get_text_provider_by_settings
            llm_provider = get_text_provider_by_settings()
        structured, llm_metadata = generate_structured_creative_brief(
            llm_provider,
            product_name=str(snapshot_data.get("product_name") or ""),
            compiler_input={
                "approved_fact_ids": approved_ids,
                "review_insights": review_payloads,
                "reference_signals": [dict(item.abstract_signals_json or {}) for item in reference_insights],
                "seller_direction": direction_payload,
                "required_sections": ["problem", "benefit", "proof", "details", "cta"],
            },
        )
        target_audience = structured["target_audience"] or target_audience
        customer_problem = structured["customer_problem"] or customer_problem
        purchase_motivation = structured["purchase_motivation"] or purchase_motivation
        direction_payload["desired_mood"] = structured["desired_mood"] or direction_payload["desired_mood"]
        direction_payload["emphasis"] = structured["emphasis"] or direction_payload["emphasis"]
        direction_payload["forbidden_scenes"] = sorted(set(direction_payload["forbidden_scenes"] + structured["forbidden_scenes"]))
        forbidden_claims = sorted(set(forbidden_claims + structured["forbidden_claims"]))
        section_strategy = structured["section_strategy"]
        for item in section_strategy:
            if item["claim_policy"] == "approved_fact_required":
                item["fact_ids"] = [fact_id for fact_id in item.get("fact_ids", []) if fact_id in approved_ids] or approved_ids
            else:
                item["fact_ids"] = []
    brief = {
        "schema_version": "lg7-v1", "product_name": snapshot_data.get("product_name") or "",
        "target_audience": target_audience,
        "customer_problem": customer_problem,
        "purchase_motivation": purchase_motivation,
        "desired_mood": direction_payload["desired_mood"],
        "emphasis": direction_payload["emphasis"],
        "forbidden_claims": forbidden_claims,
        "forbidden_scenes": direction_payload["forbidden_scenes"],
        "section_strategy": section_strategy,
        "approved_fact_ids": approved_ids,
        "creative_directions": direction_payload,
        "creative_direction": direction_payload,
        "review_insights": [{"id": item.id, "usage": "creative_direction", **dict(item.insights_json or {})} for item in review_insights],
        "reference_signals": [{"id": item.id, **dict(item.abstract_signals_json or {})} for item in reference_insights],
        "constraints": {
            "review_claims_are_not_facts": True, "reference_replication_forbidden": True,
            "forbidden_output": ["unapproved_numeric_claim", "source_copy", "source_logo", "qr", "watermark", "price_clone"],
        },
        "llm_generation": llm_metadata,
        "provenance": {
            "fact_snapshot_id": fact_snapshot.id, "fact_snapshot_hash": fact_snapshot.snapshot_hash,
            "compiled_prompt_artifact_id": artifact.id,
            "category_pack_version_id": artifact.category_pack_version_id,
            "channel_pack_version_id": artifact.channel_pack_version_id,
            "brand_kit_version_id": artifact.brand_kit_version_id, "brand_kit_hash": artifact.brand_kit_hash,
        },
    }
    manifest = {"brief": brief, "direction_hash": direction.content_hash if direction else None,
                "review_hashes": sorted(item.content_hash for item in review_insights),
                "reference_hashes": sorted(item.content_hash for item in reference_insights)}
    input_hash = canonical_hash(manifest)
    existing = db.query(ProductCreativeBriefVersion).filter_by(run_id=run.id, input_hash=input_hash).first()
    if existing:
        return existing
    previous_snapshot = dict((run.input_snapshot or {}).get("creative_brief_snapshot") or {})
    row = ProductCreativeBriefVersion(
        workspace_id=run.workspace_id, project_id=run.project_id, run_id=run.id,
        version=_next_version(db, ProductCreativeBriefVersion, run.project_id),
        previous_version_id=previous.id if previous else None,
        fact_snapshot_id=fact_snapshot.id, fact_snapshot_hash=fact_snapshot.snapshot_hash,
        compiled_prompt_artifact_id=artifact.id, category_pack_version_id=artifact.category_pack_version_id,
        channel_pack_version_id=artifact.channel_pack_version_id, brand_kit_version_id=artifact.brand_kit_version_id,
        brand_kit_hash=artifact.brand_kit_hash, creative_direction_version_id=direction.id if direction else None,
        review_insight_version_ids=[item.id for item in review_insights],
        reference_insight_version_ids=[item.id for item in reference_insights], approved_fact_ids=approved_ids,
        input_hash=input_hash, output_hash=canonical_hash(brief), brief_json=brief, created_by=run.created_by,
    )
    db.add(row); db.flush()
    inputs = dict(run.input_snapshot or {})
    inputs["creative_brief_snapshot"] = {"id": row.id, "version": row.version, "input_hash": row.input_hash,
                                         "output_hash": row.output_hash, "brand_kit_version_id": row.brand_kit_version_id,
                                         "brand_kit_hash": row.brand_kit_hash}
    run.input_snapshot = inputs
    outputs = dict(run.outputs_json or {})
    if previous_snapshot and previous_snapshot.get("output_hash") != row.output_hash:
        # The immutable brief sits immediately before Sales Strategy. A changed
        # brief invalidates only its derived planning projection; source
        # collection, approved facts, prompt packs and Brand Kit stay pinned.
        invalidated_stages = sorted(
            str(stage) for stage in dict(outputs.get("langgraph_commerce_planning_artifacts") or {})
        )
        outputs.pop("langgraph_commerce_planning_artifacts", None)
        outputs.pop("langgraph_commerce", None)
        invalidations = list(outputs.get("creative_brief_invalidations") or [])
        invalidations.append({
            "previous_brief_hash": previous_snapshot.get("output_hash"),
            "current_brief_hash": row.output_hash,
            "invalidated_stages": invalidated_stages,
            "reason": "creative_brief_changed",
        })
        outputs["creative_brief_invalidations"] = invalidations[-20:]
        if isinstance(run.project.planning_draft, dict):
            draft = dict(run.project.planning_draft)
            draft["status"] = "stale"
            history = list(draft.get("revision_history") or [])
            history.append({
                "revision": draft.get("revision", 1),
                "action": "creative_brief_invalidated",
                "reason": "creative_brief_changed",
            })
            draft["revision_history"] = history[-20:]
            run.project.planning_draft = draft
            db.add(run.project)
    outputs["creative_brief"] = inputs["creative_brief_snapshot"]
    run.outputs_json = outputs
    db.commit(); db.refresh(row)
    return row


def record_gate_event(db: Session, run: AgentRun, *, stage: str, decision: str, source: str,
                      rationale: str, impact: dict[str, Any] | None = None) -> WorkflowGateEvent:
    row = WorkflowGateEvent(
        workspace_id=run.workspace_id, project_id=run.project_id, run_id=run.id, gate_stage=stage,
        interaction_mode=normalize_interaction_mode((run.input_snapshot or {}).get("interaction_mode") or run.project.planning_mode),
        decision=decision, decision_source=source, rationale=rationale, impact_json=impact or {},
        checkpoint_id=run.graph_checkpoint_id, created_by=run.created_by,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def project_intelligence(db: Session, project_id: str, run_id: str | None = None) -> dict[str, Any]:
    direction = db.query(SellerCreativeDirectionVersion).filter_by(project_id=project_id).order_by(
        SellerCreativeDirectionVersion.version.desc()).first()
    reviews = db.query(ReviewInputVersion).filter_by(project_id=project_id).order_by(ReviewInputVersion.version.desc()).all()
    references = db.query(ReferenceInputVersion).filter_by(project_id=project_id).order_by(ReferenceInputVersion.version.desc()).all()
    briefs = db.query(ProductCreativeBriefVersion).filter_by(project_id=project_id).order_by(ProductCreativeBriefVersion.version.desc()).all()
    review_insights = {
        row.review_input_version_id: row
        for row in db.query(ReviewInsightVersion).filter_by(project_id=project_id).all()
    }
    run = None
    if run_id:
        run = db.query(AgentRun).filter_by(id=run_id, project_id=project_id).first()
    if run is None:
        run = db.query(AgentRun).filter_by(project_id=project_id).order_by(AgentRun.created_at.desc()).first()
    artifact = None if run is None else db.query(CompiledPromptArtifact).filter_by(run_id=run.id).first()
    category_pack = None if artifact is None else db.query(PromptPackVersion).filter_by(id=artifact.category_pack_version_id).first()
    channel_pack = None if artifact is None else db.query(PromptPackVersion).filter_by(id=artifact.channel_pack_version_id).first()
    brand_kit = None if artifact is None or not artifact.brand_kit_version_id else db.query(BrandKitVersion).filter_by(id=artifact.brand_kit_version_id).first()
    latest_brief = briefs[0] if briefs else None
    snapshot = None if latest_brief is None else db.query(FactSnapshot).filter_by(id=latest_brief.fact_snapshot_id).first()
    approved_facts = list(snapshot.facts_json or []) if snapshot else []
    approved_ids = {str(item.get("id")) for item in approved_facts if item.get("id")}
    candidates = db.query(ProductFact).filter_by(project_id=project_id).order_by(ProductFact.created_at.desc()).all()
    gate_events = [] if run is None else db.query(WorkflowGateEvent).filter_by(run_id=run.id).order_by(WorkflowGateEvent.created_at.asc()).all()
    project = db.query(ProductProject).filter_by(id=project_id).first()
    planning_draft = dict(project.planning_draft or {}) if project else {}
    invalidations = list((run.outputs_json or {}).get("creative_brief_invalidations") or []) if run else []
    stale = []
    if planning_draft.get("status") == "stale":
        stale.append({"artifact": "planning_draft", "impact": "storyboard_and_downstream", "reason": "creative_brief_changed"})
    stale.extend({"artifact": "commerce_planning", "impact": item.get("invalidated_stages", []), "reason": item.get("reason")} for item in invalidations)
    brief_sections = list((latest_brief.brief_json or {}).get("section_strategy") or []) if latest_brief else []
    card_by_id = {str(card.get("id")): card for card in list(planning_draft.get("cards") or [])}
    section_trace = []
    for section in brief_sections:
        card = card_by_id.get(str(section.get("section")), {})
        section_trace.append({
            "section": section.get("section"),
            "target": section.get("target") or card.get("target") or "",
            "objective": section.get("objective") or card.get("scene_request") or "",
            "fact_ids": section.get("fact_ids") or card.get("source_fact_ids") or [],
            "copy_classification": section.get("copy_classification") or "creative",
        })
    trace = {
        "run_id": run.id if run else None,
        "generation_mode": run.mode if run else None,
        "interaction_mode": (
            (run.input_snapshot or {}).get("interaction_mode") if run
            else (project.planning_mode if project else None)
        ),
        "prompt_packs": [
            {"kind": "category", "id": category_pack.id, "version": category_pack.version, "hash": artifact.category_pack_hash} if category_pack else None,
            {"kind": "channel", "id": channel_pack.id, "version": channel_pack.version, "hash": artifact.channel_pack_hash} if channel_pack else None,
        ],
        "brand_kit": None if brand_kit is None else {"id": brand_kit.id, "version": brand_kit.version, "hash": brand_kit.content_hash},
        "creative_brief": None if latest_brief is None else {"id": latest_brief.id, "version": latest_brief.version, "hash": latest_brief.output_hash},
        "approved_facts": approved_facts,
        "fact_candidates": [{"id": row.id, "text": row.fact_text, "status": row.verification_status} for row in candidates if row.id not in approved_ids],
        "creative_direction": None if direction is None else {"id": direction.id, "version": direction.version, "hash": direction.content_hash},
        "review_usage": {"used": bool(latest_brief and latest_brief.review_insight_version_ids), "ids": list(latest_brief.review_insight_version_ids or []) if latest_brief else []},
        "reference_usage": {"used": bool(latest_brief and latest_brief.reference_insight_version_ids), "ids": list(latest_brief.reference_insight_version_ids or []) if latest_brief else []},
        "sections": section_trace,
        "auto_approval_history": [{"stage": row.gate_stage, "decision": row.decision, "source": row.decision_source, "rationale": row.rationale, "checkpoint_id": row.checkpoint_id} for row in gate_events if row.decision_source == "quick_auto"],
        "stale_artifacts": stale,
    }
    return {
        "creative_direction": None if direction is None else {"id": direction.id, "version": direction.version,
            "desired_mood": direction.desired_mood, "target_audience": direction.target_audience,
            "emphasis": direction.emphasis, "forbidden_scenes": direction.forbidden_scenes, "content_hash": direction.content_hash},
        "reviews": [{"id": row.id, "version": row.version, "format": row.input_format, "source_label": row.source_label,
                     "source_asset_id": row.source_asset_id,
                     "consent_status": row.consent_status, "rights_status": row.rights_status,
                     "fact_promotion_status": (
                         review_insights[row.id].fact_promotion_status if row.id in review_insights else "blocked"
                     ), "content_hash": row.content_hash} for row in reviews],
        "references": [{"id": row.id, "version": row.version, "kind": row.input_kind, "source_url": row.source_url,
                         "asset_id": row.asset_id, "rights_status": row.rights_status,
                         "usage_scope": row.usage_scope, "content_hash": row.content_hash} for row in references],
        "briefs": [{"id": row.id, "version": row.version, "input_hash": row.input_hash, "output_hash": row.output_hash,
                    "brief": row.brief_json} for row in briefs],
        "review_asset_options": [{"id": row.id, "filename": row.filename, "mime_type": row.mime_type,
                                  "has_text": bool((row.ocr_text or "").strip() or Path(row.file_path).suffix.lower() in {".txt", ".csv", ".xlsx"})}
                                 for row in allowed_review_assets(db, project_id)],
        "trace": trace,
    }
