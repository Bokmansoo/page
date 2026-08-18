"""Immutable LG-12 Golden Dataset v1 contract.

The dataset deliberately contains only frozen fixture data.  It is not a
projection of a project's current page, assets, or jobs: later LG-12 quality
evaluators must receive a stable input even when production records change.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.services.prompt_intelligence_service import canonical_hash


GOLDEN_DATASET_ID = "lg12-visual-quality-golden-dataset"
GOLDEN_DATASET_SCHEMA_VERSION = "lg12-golden-dataset-v1"
GOLDEN_CASE_SCHEMA_VERSION = "lg12-golden-case-v1"
GOLDEN_ASSET_SCHEMA_VERSION = "lg12-golden-asset-v1"
GOLDEN_OUTPUT_SCHEMA_VERSION = "lg12-golden-output-v1"
GOLDEN_RUBRIC_SCHEMA_VERSION = "lg12-human-rubric-v1"
GOLDEN_DATASET_VERSION = "v1"
GOLDEN_CATEGORIES = ("생활용품", "뷰티", "식품", "패션", "전자제품")
GOLDEN_CHANNELS = ("smartstore", "coupang")


class GoldenDatasetContractError(ValueError):
    """Raised when a Golden Dataset is not a trustworthy frozen fixture."""


_CATEGORY_PRODUCTS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "생활용품": (
        ("storage-box", "접이식 수납 정리함", ("손잡이", "접이식 구조")),
        ("pillow", "온열 마사지 베개", ("조절 버튼", "전원 포트")),
        ("cleaning-brush", "욕실 청소 브러시", ("브러시 헤드", "교체 구성품")),
    ),
    "뷰티": (
        ("serum", "수분 진정 세럼", ("펌프", "브랜드 로고")),
        ("lip-tint", "벨벳 립 틴트", ("팁", "색상 라벨")),
        ("hair-dryer", "이온 헤어 드라이어", ("노즐", "온도 컨트롤")),
    ),
    "식품": (
        ("cold-brew", "콜드브루 커피 선물세트", ("병 라벨", "구성품")),
        ("rice", "유기농 현미", ("포장 라벨", "인증 마크")),
        ("snack", "견과 간식 세트", ("개별 포장", "알레르기 표기")),
    ),
    "패션": (
        ("dress", "린넨 여름 원피스", ("소매", "허리선")),
        ("sneakers", "러닝 스니커즈", ("밑창", "로고")),
        ("bag", "가죽 크로스백", ("잠금장치", "스트랩")),
    ),
    "전자제품": (
        ("fan", "휴대용 무선 선풍기", ("조절 버튼", "USB-C 포트")),
        ("monitor", "스마트 모니터", ("입력 포트", "스탠드")),
        ("earbuds", "무선 이어버드", ("충전 케이스", "터치 컨트롤")),
    ),
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixture_asset(*, case_id: str, role: str) -> dict[str, str]:
    payload = f"sellform/lg12/{GOLDEN_DATASET_VERSION}/{case_id}/{role}".encode("utf-8")
    return {
        "schema_version": GOLDEN_ASSET_SCHEMA_VERSION,
        "asset_id": f"golden-asset:{case_id}:{role}",
        "asset_content_hash": _sha256_bytes(payload),
        "fixture_bytes_b64": base64.b64encode(payload).decode("ascii"),
        "usage_status": "seller_owned",
        "rights_status": "confirmed",
        "provenance_id": f"golden-provenance:{case_id}:{role}",
        "source_kind": "frozen_fixture",
    }


def _frozen_identity(
    case_id: str, role: str, *, approved_asset_manifest_hash: str | None = None
) -> dict[str, str]:
    detail_page_version_id = f"golden-detail-page:{case_id}:{role}"
    return {
        "detail_page_version_id": detail_page_version_id,
        "snapshot_hash": canonical_hash({"case_id": case_id, "role": role, "snapshot": "v1"}),
        "canonical_input_hash": canonical_hash({"case_id": case_id, "role": role, "input": "v1"}),
        "approved_asset_manifest_hash": approved_asset_manifest_hash
        or canonical_hash({"case_id": case_id, "role": role, "manifest": "v1"}),
    }


def _human_rubric() -> dict[str, Any]:
    body = {
        "schema_version": GOLDEN_RUBRIC_SCHEMA_VERSION,
        "rubric_id": "lg12-human-rubric-commerce-v1",
        "dimensions": (
            "product_identity",
            "layout_quality",
            "korean_copy_quality",
            "channel_readiness",
        ),
        "instructions": "승인된 사실과 frozen asset만 기준으로 사람 검수를 기록한다.",
    }
    return {**body, "rubric_hash": canonical_hash(body)}


def _case(
    *, category: str, product_key: str, product_name: str, features: tuple[str, ...], index: int
) -> dict[str, Any]:
    case_id = f"lg12-v1:{category}:{product_key}"
    channel = GOLDEN_CHANNELS[index % len(GOLDEN_CHANNELS)]
    reference_asset = _fixture_asset(case_id=case_id, role="reference")
    golden_asset = _fixture_asset(case_id=case_id, role="golden-output")
    fact_id = f"golden-fact:{case_id}:product-spec"
    evidence_id = f"golden-evidence:{case_id}:seller-confirmed"
    copy_id = f"golden-copy:{case_id}:hero"
    section_id = f"golden-section:{case_id}:hero"
    scene_id = f"golden-scene:{case_id}:hero"
    expected_manifest = {
        "manifest_id": f"golden-manifest:{case_id}",
        "assets": (
            {
                "asset_id": golden_asset["asset_id"],
                "asset_content_hash": golden_asset["asset_content_hash"],
                "scene_id": scene_id,
                "section_id": section_id,
            },
        ),
    }
    expected_manifest["manifest_hash"] = canonical_hash(expected_manifest)
    frozen_version = _frozen_identity(
        case_id,
        "expected-output",
        approved_asset_manifest_hash=expected_manifest["manifest_hash"],
    )
    return {
        "schema_version": GOLDEN_CASE_SCHEMA_VERSION,
        "case_id": case_id,
        "category": category,
        "channel": channel,
        "input": {
            "input_id": f"golden-input:{case_id}",
            "input_hash": canonical_hash({"case_id": case_id, "product_name": product_name, "features": features}),
            "product_name": product_name,
            "reference_assets": (reference_asset,),
            "approved_fact_ids": (fact_id,),
            "evidence_ids": (evidence_id,),
            "required_section_ids": (section_id, f"golden-section:{case_id}:specs"),
            "required_scene_ids": (scene_id,),
            "forbidden_claims": ("근거 없는 효능 보장",),
            "identity_critical_features": features,
        },
        # The contract case is evaluated against this exact frozen version;
        # expected output/manifest fields are not a second mutable source.
        "source_frozen_version": copy.deepcopy(frozen_version),
        "expected_output": {
            "schema_version": GOLDEN_OUTPUT_SCHEMA_VERSION,
            "output_id": f"golden-output:{case_id}",
            "frozen_version": copy.deepcopy(frozen_version),
            "channel": channel,
            "approved_asset_manifest": expected_manifest,
            "section_identities": (
                {"section_id": section_id, "scene_id": scene_id, "asset_id": golden_asset["asset_id"]},
                {"section_id": f"golden-section:{case_id}:specs", "scene_id": None, "asset_id": None},
            ),
            "copy_identity": {
                "copy_artifact_id": copy_id,
                "copy_artifact_hash": canonical_hash({"case_id": case_id, "copy": "hero-v1"}),
                "fact_ids": (fact_id,),
                "evidence_ids": (evidence_id,),
            },
            "golden_assets": (golden_asset,),
        },
        "human_rubric_id": "lg12-human-rubric-commerce-v1",
        "provider_mode": "fake",
    }


def build_golden_dataset_v1() -> dict[str, Any]:
    """Build the checked-in, deterministic LG-12 v1 fixture payload."""
    cases: list[dict[str, Any]] = []
    index = 0
    for category in GOLDEN_CATEGORIES:
        for product_key, product_name, features in _CATEGORY_PRODUCTS[category]:
            cases.append(_case(category=category, product_key=product_key, product_name=product_name, features=features, index=index))
            index += 1
    payload: dict[str, Any] = {
        "schema_version": GOLDEN_DATASET_SCHEMA_VERSION,
        "dataset_id": GOLDEN_DATASET_ID,
        "dataset_version": GOLDEN_DATASET_VERSION,
        "previous_dataset_hash": None,
        "categories": GOLDEN_CATEGORIES,
        "human_rubrics": (_human_rubric(),),
        "cases": tuple(cases),
    }
    return {**payload, "content_hash": canonical_hash(payload)}


# This value is intentionally checked in rather than derived during validation.
# A changed payload must become a new dataset version, not silently redefine v1.
GOLDEN_DATASET_V1_CONTENT_HASH = "846ac09bba6795257d3a527fca76d5dc98c6f2fbd4b634130b0ba0bbe30ab6ae"
TRUSTED_GOLDEN_DATASET_VERSION_HASHES = {
    GOLDEN_DATASET_VERSION: GOLDEN_DATASET_V1_CONTENT_HASH,
}


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GoldenDatasetContractError(f"{label} must be an object.")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise GoldenDatasetContractError(f"{label} must be a lowercase SHA-256 hex digest.")
    return value


def _validate_fixture_asset(asset: Any, label: str) -> None:
    item = _require_mapping(asset, label)
    if item.get("schema_version") != GOLDEN_ASSET_SCHEMA_VERSION:
        raise GoldenDatasetContractError(f"{label} has an unsupported schema version.")
    if not isinstance(item.get("asset_id"), str) or not item["asset_id"]:
        raise GoldenDatasetContractError(f"{label}.asset_id is required.")
    expected_hash = _require_sha256(item.get("asset_content_hash"), f"{label}.asset_content_hash")
    if item.get("usage_status") not in {"seller_owned", "rights_confirmed"} or item.get("rights_status") != "confirmed":
        raise GoldenDatasetContractError(f"{label} must be a rights-confirmed final asset.")
    if item.get("source_kind") != "frozen_fixture" or "external_url" in item:
        raise GoldenDatasetContractError(f"{label} must not depend on external or mutable asset state.")
    if not isinstance(item.get("provenance_id"), str) or not item["provenance_id"]:
        raise GoldenDatasetContractError(f"{label}.provenance_id is required.")
    try:
        payload = base64.b64decode(str(item.get("fixture_bytes_b64") or ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GoldenDatasetContractError(f"{label}.fixture_bytes_b64 is invalid.") from exc
    if _sha256_bytes(payload) != expected_hash:
        raise GoldenDatasetContractError(f"{label} content hash does not match fixture bytes.")


def _validate_frozen_version(identity: Any, label: str) -> None:
    item = _require_mapping(identity, label)
    if not isinstance(item.get("detail_page_version_id"), str) or not item["detail_page_version_id"]:
        raise GoldenDatasetContractError(f"{label}.detail_page_version_id is required.")
    for field in ("snapshot_hash", "canonical_input_hash", "approved_asset_manifest_hash"):
        _require_sha256(item.get(field), f"{label}.{field}")


def _validate_case(case: Any, rubric_ids: set[str]) -> None:
    item = _require_mapping(case, "case")
    case_id = item.get("case_id")
    if item.get("schema_version") != GOLDEN_CASE_SCHEMA_VERSION or not isinstance(case_id, str) or not case_id:
        raise GoldenDatasetContractError("Each case needs a stable ID and supported schema version.")
    if item.get("category") not in GOLDEN_CATEGORIES:
        raise GoldenDatasetContractError(f"{case_id} has an unsupported category.")
    if item.get("channel") not in GOLDEN_CHANNELS:
        raise GoldenDatasetContractError(f"{case_id} has an unsupported frozen channel identity.")
    if item.get("provider_mode") != "fake":
        raise GoldenDatasetContractError(f"{case_id} must be reproducible with the fake provider fixture.")
    if item.get("human_rubric_id") not in rubric_ids:
        raise GoldenDatasetContractError(f"{case_id} does not reference a known human rubric.")

    input_data = _require_mapping(item.get("input"), f"{case_id}.input")
    if not isinstance(input_data.get("input_id"), str) or not input_data["input_id"]:
        raise GoldenDatasetContractError(f"{case_id}.input.input_id is required.")
    _require_sha256(input_data.get("input_hash"), f"{case_id}.input.input_hash")
    for field in ("approved_fact_ids", "evidence_ids", "required_section_ids", "required_scene_ids", "forbidden_claims", "identity_critical_features"):
        values = input_data.get(field)
        if not isinstance(values, (tuple, list)) or not values or not all(isinstance(value, str) and value for value in values):
            raise GoldenDatasetContractError(f"{case_id}.input.{field} must contain stable identities.")
    reference_assets = input_data.get("reference_assets")
    if not isinstance(reference_assets, (tuple, list)) or not reference_assets:
        raise GoldenDatasetContractError(f"{case_id} must include a frozen reference asset.")
    for asset in reference_assets:
        _validate_fixture_asset(asset, f"{case_id}.input.reference_asset")

    _validate_frozen_version(item.get("source_frozen_version"), f"{case_id}.source_frozen_version")
    output = _require_mapping(item.get("expected_output"), f"{case_id}.expected_output")
    if output.get("schema_version") != GOLDEN_OUTPUT_SCHEMA_VERSION or not isinstance(output.get("output_id"), str):
        raise GoldenDatasetContractError(f"{case_id} must have a structured expected output identity.")
    if output.get("channel") != item["channel"]:
        raise GoldenDatasetContractError(f"{case_id} expected output channel must match the frozen case channel.")
    _validate_frozen_version(output.get("frozen_version"), f"{case_id}.expected_output.frozen_version")
    manifest = _require_mapping(output.get("approved_asset_manifest"), f"{case_id}.expected_output.approved_asset_manifest")
    if not isinstance(manifest.get("manifest_id"), str) or not manifest["manifest_id"]:
        raise GoldenDatasetContractError(f"{case_id} expected manifest identity is required.")
    manifest_hash = _require_sha256(manifest.get("manifest_hash"), f"{case_id}.expected_output.approved_asset_manifest.manifest_hash")
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if manifest_hash != canonical_hash(manifest_body):
        raise GoldenDatasetContractError(f"{case_id} manifest hash does not match its canonical content.")
    golden_assets = output.get("golden_assets")
    if not isinstance(golden_assets, (tuple, list)) or not golden_assets:
        raise GoldenDatasetContractError(f"{case_id} needs a golden output asset.")
    for asset in golden_assets:
        _validate_fixture_asset(asset, f"{case_id}.expected_output.golden_asset")
    manifest_assets = manifest.get("assets")
    if not isinstance(manifest_assets, (tuple, list)) or not manifest_assets:
        raise GoldenDatasetContractError(f"{case_id} expected manifest needs asset identities.")
    golden_identity = {(asset["asset_id"], asset["asset_content_hash"]) for asset in golden_assets}
    for identity in manifest_assets:
        manifest_asset = _require_mapping(identity, f"{case_id}.expected_output.manifest_asset")
        pair = (manifest_asset.get("asset_id"), manifest_asset.get("asset_content_hash"))
        if pair not in golden_identity:
            raise GoldenDatasetContractError(f"{case_id} manifest must reference its frozen golden asset and hash.")
        _require_sha256(pair[1], f"{case_id}.expected_output.manifest_asset.asset_content_hash")
    output_frozen_version = _require_mapping(output["frozen_version"], f"{case_id}.expected_output.frozen_version")
    source_frozen_version = _require_mapping(item["source_frozen_version"], f"{case_id}.source_frozen_version")
    if output_frozen_version["approved_asset_manifest_hash"] != manifest_hash:
        raise GoldenDatasetContractError(f"{case_id} expected output frozen version must pin its manifest hash.")
    if source_frozen_version != output_frozen_version:
        raise GoldenDatasetContractError(f"{case_id} source frozen version must match expected output frozen version.")
    sections = output.get("section_identities")
    if not isinstance(sections, (tuple, list)) or not sections:
        raise GoldenDatasetContractError(f"{case_id} expected output needs section identities.")
    if not all(isinstance(section, Mapping) and isinstance(section.get("section_id"), str) for section in sections):
        raise GoldenDatasetContractError(f"{case_id} expected output section identity is invalid.")
    copy_identity = _require_mapping(output.get("copy_identity"), f"{case_id}.expected_output.copy_identity")
    if not isinstance(copy_identity.get("copy_artifact_id"), str) or not copy_identity["copy_artifact_id"]:
        raise GoldenDatasetContractError(f"{case_id} expected copy identity is required.")
    _require_sha256(copy_identity.get("copy_artifact_hash"), f"{case_id}.expected_output.copy_identity.copy_artifact_hash")


def validate_golden_dataset(
    document: Mapping[str, Any], *, expected_content_hash: str | None = None
) -> dict[str, Any]:
    """Validate a complete frozen dataset and return a detached copy.

    ``expected_content_hash`` pins a registered version.  Passing it prevents
    a caller from changing a v1 payload and simply recalculating its own hash.
    """
    data = copy.deepcopy(dict(_require_mapping(document, "dataset")))
    if data.get("schema_version") != GOLDEN_DATASET_SCHEMA_VERSION or data.get("dataset_id") != GOLDEN_DATASET_ID:
        raise GoldenDatasetContractError("Unsupported Golden Dataset identity or schema version.")
    if not isinstance(data.get("dataset_version"), str) or not data["dataset_version"]:
        raise GoldenDatasetContractError("dataset_version is required.")
    stored_hash = _require_sha256(data.get("content_hash"), "dataset.content_hash")
    hashed_payload = {key: value for key, value in data.items() if key != "content_hash"}
    calculated_hash = canonical_hash(hashed_payload)
    if stored_hash != calculated_hash:
        raise GoldenDatasetContractError("Golden Dataset content hash does not match its canonical payload.")
    trusted_hash = TRUSTED_GOLDEN_DATASET_VERSION_HASHES.get(data["dataset_version"])
    if trusted_hash is not None and stored_hash != trusted_hash:
        raise GoldenDatasetContractError("Golden Dataset registered version does not match its trusted canonical hash.")
    if expected_content_hash is not None and stored_hash != expected_content_hash:
        raise GoldenDatasetContractError("Golden Dataset version content hash is immutable and does not match its registered value.")
    if tuple(data.get("categories") or ()) != GOLDEN_CATEGORIES:
        raise GoldenDatasetContractError("Golden Dataset must contain the five fixed category packs in stable order.")

    rubrics = data.get("human_rubrics")
    if not isinstance(rubrics, (tuple, list)) or not rubrics:
        raise GoldenDatasetContractError("Golden Dataset must include versioned human rubrics.")
    rubric_ids: set[str] = set()
    for rubric in rubrics:
        item = _require_mapping(rubric, "human_rubric")
        rubric_id = item.get("rubric_id")
        if item.get("schema_version") != GOLDEN_RUBRIC_SCHEMA_VERSION or not isinstance(rubric_id, str) or not rubric_id:
            raise GoldenDatasetContractError("Human rubric needs a stable ID and schema version.")
        if rubric_id in rubric_ids:
            raise GoldenDatasetContractError("Duplicate human rubric identity is not allowed.")
        rubric_ids.add(rubric_id)
        body = {key: value for key, value in item.items() if key != "rubric_hash"}
        if item.get("rubric_hash") != canonical_hash(body):
            raise GoldenDatasetContractError(f"Human rubric {rubric_id} hash does not match its canonical payload.")

    cases = data.get("cases")
    if not isinstance(cases, (tuple, list)) or len(cases) != 15:
        raise GoldenDatasetContractError("Golden Dataset v1 must contain exactly 15 cases.")
    case_ids = [case.get("case_id") if isinstance(case, Mapping) else None for case in cases]
    if len(set(case_ids)) != len(case_ids) or any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
        raise GoldenDatasetContractError("Golden case IDs must be stable and unique.")
    category_counts = Counter(case.get("category") for case in cases if isinstance(case, Mapping))
    if any(category_counts[category] != 3 for category in GOLDEN_CATEGORIES):
        raise GoldenDatasetContractError("Each Golden Dataset category must contain exactly three cases.")
    for case in cases:
        _validate_case(case, rubric_ids)
    return data


def load_golden_dataset(version: str = GOLDEN_DATASET_VERSION) -> dict[str, Any]:
    """Load a registered immutable Golden Dataset without reading mutable state."""
    if version not in TRUSTED_GOLDEN_DATASET_VERSION_HASHES:
        raise GoldenDatasetContractError(f"Unknown Golden Dataset version: {version}.")
    return validate_golden_dataset(build_golden_dataset_v1())


def validate_dataset_successor(
    document: Mapping[str, Any], *, previous_document: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate a separately versioned successor without changing its predecessor."""
    prior = validate_golden_dataset(previous_document)
    candidate = validate_golden_dataset(document)
    parent_version = candidate.get("parent_version")
    if not isinstance(parent_version, str) or not parent_version:
        raise GoldenDatasetContractError("A Golden Dataset successor must identify its trusted parent version.")
    trusted_parent_hash = TRUSTED_GOLDEN_DATASET_VERSION_HASHES.get(parent_version)
    if trusted_parent_hash is None:
        raise GoldenDatasetContractError("A Golden Dataset successor parent version must be registered and trusted.")
    if candidate["dataset_version"] == parent_version or candidate["dataset_version"] == prior["dataset_version"]:
        raise GoldenDatasetContractError("A changed Golden Dataset must use a new dataset version.")
    if prior["dataset_version"] != parent_version or prior["content_hash"] != trusted_parent_hash:
        raise GoldenDatasetContractError("Golden Dataset successor parent does not match the trusted registered version.")
    if candidate.get("previous_dataset_hash") != trusted_parent_hash:
        raise GoldenDatasetContractError("A Golden Dataset successor must pin the preceding dataset hash.")
    return candidate
