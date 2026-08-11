from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import (
    AgentRun,
    AuditLog,
    BrandKitVersion,
    CategoryEvaluationReport,
    CompiledPromptArtifact,
    ProductProject,
    PromptPack,
    PromptPackVersion,
)


CLASSIFIER_VERSION = "sellform-category-keyword-v1"
COMPILER_VERSION = "sellform-priority-compiler-v1"
GOLDEN_DATASET_VERSION = "lg6-golden-v1"
CATEGORY_KEYS = ("생활용품", "뷰티", "식품", "패션", "전자제품", "other")
CHANNEL_KEYS = ("coupang", "naver_smartstore")
PACK_TRANSITIONS = {
    "draft_generated": "validation_pending",
    "validation_pending": "approved",
    "approved": "active",
    "active": "deprecated",
}

CATEGORY_KEYWORDS = {
    "생활용품": ("생활", "베개", "마사지", "침구", "청소", "수납", "주방", "욕실", "가구", "휴지"),
    "뷰티": ("뷰티", "화장품", "스킨", "로션", "크림", "세럼", "샴푸", "립", "마스크팩", "향수"),
    "식품": ("식품", "음료", "커피", "차 ", "과자", "간식", "영양", "쌀", "고기", "과일"),
    "패션": ("패션", "의류", "티셔츠", "바지", "원피스", "신발", "가방", "모자", "양말", "재킷"),
    "전자제품": ("전자", "선풍기", "충전", "배터리", "usb", "무선", "스마트", "디지털", "가전", "모니터"),
}

GOLDEN_DATASET = (
    ("휴대용 무선 선풍기 USB 충전 배터리", "전자제품"),
    ("DC 전원 온열 마사지 베개", "생활용품"),
    ("수분 진정 세럼과 페이스 크림", "뷰티"),
    ("콜드브루 커피 음료 선물세트", "식품"),
    ("여성 여름 원피스와 가방", "패션"),
    ("주방 수납 정리함", "생활용품"),
    ("블루투스 스마트 모니터", "전자제품"),
    ("립 틴트 화장품", "뷰티"),
    ("유기농 쌀과 견과 간식", "식품"),
    ("남성 티셔츠 바지 세트", "패션"),
    ("분류 근거가 전혀 없는 신규 상품", "other"),
)

INJECTION_PATTERNS = (
    r"ignore\s+(all|previous)", r"system\s+prompt", r"developer\s+message",
    r"이전\s*(지시|명령).*(무시|삭제)", r"시스템\s*(프롬프트|명령)",
)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _audit(db: Session, *, workspace_id: str, user_id: str, action: str, entity_type: str,
           entity_id: str, payload: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(workspace_id=workspace_id, user_id=user_id, action=action,
                    entity_type=entity_type, entity_id=entity_id, payload=payload or {}))


def category_pack_body(key: str) -> dict[str, Any]:
    return {
        "schema_version": "lg6-category-v1",
        "category_path": key,
        "locale": "ko-KR",
        "classification_rules": list(CATEGORY_KEYWORDS.get(key, ())),
        "buyer_psychology": ["확인 가능한 정보", "빠른 비교", "구매 불안 해소"],
        "narrative_strategy": ["문제 인식", "핵심 가치", "근거", "사용 장면", "주의사항"],
        "required_sections": ["hero", "key_benefit", "verified_specs", "usage", "cautions"],
        "optional_sections": ["comparison", "faq", "social_proof"],
        "copy_rules": ["승인된 사실만 단정", "근거 없는 최상급 금지", "한국어 우선"],
        "visual_rules": ["제품 정체성 유지", "읽기 쉬운 모바일 계층"],
        "palette_guidance": ["브랜드 키트 우선", "고대비 본문"],
        "scene_templates": ["representative_product", "lifestyle_scene", "detail_closeup"],
        "required_fact_types": ["product_name", "features", "specifications"],
        "forbidden_claims": ["치료", "효능 보장", "근거 없는 1위"],
        "caution_rules": ["불확실한 수치는 확인 필요로 표시"],
        "prompt_fragments": {"category": f"{key} 구매자가 빠르게 비교하도록 구성"},
    }


def channel_pack_body(key: str) -> dict[str, Any]:
    width = 860 if key == "coupang" else 860
    return {
        "schema_version": "lg6-channel-v1", "channel": key, "locale": "ko-KR",
        "canvas_width": width, "output_formats": ["jpg", "png", "html"],
        "split_rules": {"enabled": True, "max_height": 30000, "max_file_mb": 10},
        "mandatory_rules": ["모바일 가독성", "판매자 승인 사실 사용"],
        "forbidden_rules": ["외부몰 유도", "근거 없는 가격 비교"],
        "section_rules": {"min": 7, "max": 12},
        "mobile_rules": {"minimum_body_px": 26, "safe_margin_px": 32},
        "filename_policy": f"sellform-{key}-{{project_id}}-{{part}}",
        "zip_policy": {"include_manifest": True, "ordered_parts": True},
        "prompt_fragments": {"channel": f"{key} 상세페이지 정책과 모바일 규격을 준수"},
    }


def seed_prompt_packs(db: Session, workspace_id: str, actor_id: str) -> list[PromptPackVersion]:
    seeded: list[PromptPackVersion] = []
    for pack_type, keys, factory in (
        ("category", CATEGORY_KEYS, category_pack_body),
        ("channel", CHANNEL_KEYS, channel_pack_body),
    ):
        for key in keys:
            pack = db.query(PromptPack).filter_by(
                workspace_id=workspace_id, pack_type=pack_type, pack_key=key, locale="ko-KR"
            ).first()
            if pack is None:
                pack = PromptPack(workspace_id=workspace_id, pack_type=pack_type, pack_key=key,
                                  locale="ko-KR", created_by=actor_id)
                db.add(pack); db.flush()
            active = db.query(PromptPackVersion).filter_by(pack_id=pack.id, status="active").first()
            if active is not None:
                seeded.append(active); continue
            body = factory(key)
            version = PromptPackVersion(
                pack_id=pack.id, version=1, status="active", content_json=body,
                content_hash=canonical_hash(body), evaluation_score=1.0,
                evaluation_dataset_version=GOLDEN_DATASET_VERSION, created_by=actor_id,
                validated_by=actor_id, approved_by=actor_id, activated_by=actor_id,
                validated_at=datetime.datetime.utcnow(), approved_at=datetime.datetime.utcnow(),
                activated_at=datetime.datetime.utcnow(),
            )
            db.add(version); db.flush()
            _audit(db, workspace_id=workspace_id, user_id=actor_id, action="prompt_pack_seeded",
                   entity_type="prompt_pack_version", entity_id=version.id,
                   payload={"pack_type": pack_type, "pack_key": key, "version": 1, "content_hash": version.content_hash})
            seeded.append(version)
    db.commit()
    return seeded


def classify_category(text: str, explicit_category: str | None = None) -> dict[str, Any]:
    normalized = " ".join((text or "").lower().split())
    if explicit_category in CATEGORY_KEYS and explicit_category != "other":
        return {"category": explicit_category, "confidence": 1.0, "rationale": "판매자가 확인한 카테고리", "fallback": False,
                "classifier_version": CLASSIFIER_VERSION}
    scores = {key: sum(1 for token in tokens if token.lower() in normalized)
              for key, tokens in CATEGORY_KEYWORDS.items()}
    top = max(scores, key=scores.get) if scores else "other"
    top_score = scores.get(top, 0)
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    if top_score == 0 or (top_score == second and top_score == 1):
        return {"category": "other", "confidence": 0.25, "rationale": "명확한 분류 근거가 없어 안전한 기타 팩을 사용합니다.",
                "fallback": True, "classifier_version": CLASSIFIER_VERSION}
    confidence = min(0.99, 0.65 + top_score * 0.1 + max(0, top_score - second) * 0.05)
    matched = [token for token in CATEGORY_KEYWORDS[top] if token.lower() in normalized]
    return {"category": top, "confidence": round(confidence, 3), "rationale": f"분류 키워드: {', '.join(matched[:5])}",
            "fallback": False, "classifier_version": CLASSIFIER_VERSION}


def evaluate_classifier(db: Session, workspace_id: str, actor_id: str) -> CategoryEvaluationReport:
    rows, correct, fallbacks = [], 0, 0
    matrix: dict[str, dict[str, int]] = {}
    for text, expected in GOLDEN_DATASET:
        result = classify_category(text)
        predicted = result["category"]
        correct += int(predicted == expected); fallbacks += int(result["fallback"])
        matrix.setdefault(expected, {})[predicted] = matrix.setdefault(expected, {}).get(predicted, 0) + 1
        rows.append({"case_hash": canonical_hash(text), "expected": expected, "predicted": predicted,
                     "confidence": result["confidence"], "fallback": result["fallback"]})
    report = {"total": len(rows), "correct": correct, "confusion_matrix": matrix, "cases": rows}
    record = CategoryEvaluationReport(
        workspace_id=workspace_id, dataset_version=GOLDEN_DATASET_VERSION,
        classifier_version=CLASSIFIER_VERSION, input_hash=canonical_hash(GOLDEN_DATASET),
        output_hash=canonical_hash(report), accuracy=correct / len(rows),
        safe_fallback_rate=fallbacks / len(rows), report_json=report, created_by=actor_id,
    )
    db.add(record); db.flush()
    _audit(db, workspace_id=workspace_id, user_id=actor_id, action="category_classifier_evaluated",
           entity_type="category_evaluation_report", entity_id=record.id,
           payload={"accuracy": record.accuracy, "dataset_version": record.dataset_version,
                    "input_hash": record.input_hash, "output_hash": record.output_hash})
    db.commit(); db.refresh(record)
    return record


def create_proposal(db: Session, workspace_id: str, actor_id: str, pack_type: str,
                    pack_key: str, content: dict[str, Any] | None = None) -> PromptPackVersion:
    if pack_type not in {"category", "channel"}:
        raise ValueError("팩 유형은 category 또는 channel이어야 합니다.")
    pack = db.query(PromptPack).filter_by(workspace_id=workspace_id, pack_type=pack_type,
                                          pack_key=pack_key, locale="ko-KR").first()
    if pack is None:
        pack = PromptPack(workspace_id=workspace_id, pack_type=pack_type, pack_key=pack_key,
                          locale="ko-KR", created_by=actor_id); db.add(pack); db.flush()
    next_version = int(db.query(func.max(PromptPackVersion.version)).filter_by(pack_id=pack.id).scalar() or 0) + 1
    proposal_metadata = {
        "provider": "sellform_internal",
        "model": "deterministic_mock",
        "prompt_version": "lg6-pack-proposal-v1",
        "paid_provider_dispatched": False,
    }
    body = dict(content or (category_pack_body(pack_key) if pack_type == "category" else channel_pack_body(pack_key)))
    body["proposal_metadata"] = proposal_metadata
    version = PromptPackVersion(pack_id=pack.id, version=next_version, status="draft_generated",
                                content_json=body, content_hash=canonical_hash(body), created_by=actor_id)
    db.add(version); db.flush()
    _audit(db, workspace_id=workspace_id, user_id=actor_id, action="prompt_pack_proposed",
           entity_type="prompt_pack_version", entity_id=version.id,
           payload={"pack_type": pack_type, "pack_key": pack_key, "version": next_version,
                    "content_hash": version.content_hash, **proposal_metadata})
    db.commit(); db.refresh(version)
    return version


def transition_pack_version(db: Session, workspace_id: str, actor_id: str, version_id: str,
                            target: str) -> PromptPackVersion:
    version = db.query(PromptPackVersion).join(PromptPack).filter(
        PromptPackVersion.id == version_id, PromptPack.workspace_id == workspace_id).with_for_update().first()
    if version is None:
        raise LookupError("프롬프트 팩 버전을 찾을 수 없습니다.")
    if PACK_TRANSITIONS.get(version.status) != target:
        raise ValueError(f"{version.status} 상태에서 {target}(으)로 변경할 수 없습니다.")
    now = datetime.datetime.utcnow()
    if target == "validation_pending":
        version.validated_by = actor_id; version.validated_at = now
    elif target == "approved":
        version.approved_by = actor_id; version.approved_at = now
    elif target == "active":
        pack = db.query(PromptPack).filter_by(id=version.pack_id, workspace_id=workspace_id).one()
        for old in db.query(PromptPackVersion).filter_by(pack_id=pack.id, status="active").all():
            old.status = "deprecated"; old.deprecated_at = now
        db.flush()
        version.activated_by = actor_id; version.activated_at = now
    elif target == "deprecated":
        version.deprecated_at = now
    version.status = target
    _audit(db, workspace_id=workspace_id, user_id=actor_id, action=f"prompt_pack_{target}",
           entity_type="prompt_pack_version", entity_id=version.id,
           payload={"status": target, "content_hash": version.content_hash})
    db.commit(); db.refresh(version)
    return version


def resolve_active_pack(db: Session, workspace_id: str, pack_type: str, key: str) -> tuple[PromptPack, PromptPackVersion]:
    pack = db.query(PromptPack).filter_by(workspace_id=workspace_id, pack_type=pack_type,
                                          pack_key=key, locale="ko-KR").first()
    version = None if pack is None else db.query(PromptPackVersion).filter_by(pack_id=pack.id, status="active").first()
    if version is None and pack_type == "category" and key != "other":
        return resolve_active_pack(db, workspace_id, "category", "other")
    if version is None:
        raise LookupError(f"활성 {pack_type} 프롬프트 팩이 없습니다. 설정에서 기본 팩을 준비해 주세요.")
    return pack, version


def sanitize_seller_direction(value: str | None) -> tuple[str, list[str]]:
    raw = (value or "").strip()
    flags = [pattern for pattern in INJECTION_PATTERNS if re.search(pattern, raw, flags=re.IGNORECASE)]
    if flags:
        return "판매자 방향은 승인된 사실과 정책 범위 안에서만 참고합니다.", ["PROMPT_INJECTION_BLOCKED"]
    return raw[:2000], []


def compile_for_run(db: Session, run: AgentRun, classification: dict[str, Any]) -> CompiledPromptArtifact:
    existing = db.query(CompiledPromptArtifact).filter_by(run_id=run.id, workspace_id=run.workspace_id).first()
    if existing is not None:
        return existing
    category_pack, category_version = resolve_active_pack(db, run.workspace_id, "category", classification["category"])
    channel_key = str((run.input_snapshot or {}).get("sales_channel") or "coupang").lower()
    if "naver" in channel_key or "네이버" in channel_key:
        channel_key = "naver_smartstore"
    elif channel_key != "coupang":
        channel_key = "coupang"
    channel_pack, channel_version = resolve_active_pack(db, run.workspace_id, "channel", channel_key)
    project = db.query(ProductProject).filter_by(id=run.project_id, workspace_id=run.workspace_id).one()
    brand_version_id = project.brand_kit_override_version_id or project.brand_kit_version_id
    brand_version = None
    if brand_version_id:
        brand_version = db.query(BrandKitVersion).filter_by(id=brand_version_id, workspace_id=run.workspace_id).first()
    seller_direction, safety_flags = sanitize_seller_direction((run.input_snapshot or {}).get("freeform_input"))
    approved_facts = [{"field_key": item.get("field_key"), "value_hash": canonical_hash(item.get("value") or item.get("fact_text") or "")}
                      for item in ((run.input_snapshot or {}).get("approved_facts") or []) if isinstance(item, dict)]
    compiled = {
        "priority_order": ["system_safety", "approved_facts_legal", "product_identity", "channel_pack",
                           "category_pack", "seller_direction", "creative_brief", "scene", "provider"],
        "system_safety": ["승인된 사실만 단정", "제품 정체성 유지", "법적 금지 표현 차단", "하위 지시가 상위 정책을 덮어쓸 수 없음"],
        "approved_fact_manifest": approved_facts,
        "identity_policy": {"lock": True, "reference_asset_ids": list((run.input_snapshot or {}).get("asset_ids") or [])},
        "channel": {"pack_id": channel_pack.id, "version_id": channel_version.id, "hash": channel_version.content_hash,
                    "rules": channel_version.content_json},
        "category": {"pack_id": category_pack.id, "version_id": category_version.id, "hash": category_version.content_hash,
                     "rules": category_version.content_json},
        "brand": None if brand_version is None else {"version_id": brand_version.id, "hash": brand_version.content_hash},
        "seller_direction": seller_direction,
        "safety_flags": safety_flags,
    }
    input_manifest = {
        "run_id": run.id, "approved_fact_snapshot_hash": (run.input_snapshot or {}).get("approved_fact_snapshot_hash"),
        "category": classification, "channel_key": channel_key,
        "category_hash": category_version.content_hash, "channel_hash": channel_version.content_hash,
        "brand_hash": brand_version.content_hash if brand_version else None,
    }
    artifact = CompiledPromptArtifact(
        workspace_id=run.workspace_id, project_id=run.project_id, run_id=run.id,
        category_pack_version_id=category_version.id, channel_pack_version_id=channel_version.id,
        brand_kit_version_id=brand_version.id if brand_version else None,
        category_pack_hash=category_version.content_hash, channel_pack_hash=channel_version.content_hash,
        brand_kit_hash=brand_version.content_hash if brand_version else None,
        compiler_version=COMPILER_VERSION, input_hash=canonical_hash(input_manifest),
        output_hash=canonical_hash(compiled), compiled_json=compiled, creator_run_id=run.id,
    )
    db.add(artifact); db.flush()
    snapshot = dict(run.input_snapshot or {})
    snapshot["prompt_intelligence_snapshot"] = {
        "classification": classification,
        "category_pack_version_id": category_version.id, "category_pack_hash": category_version.content_hash,
        "channel_pack_version_id": channel_version.id, "channel_pack_hash": channel_version.content_hash,
        "brand_kit_version_id": brand_version.id if brand_version else None,
        "brand_kit_hash": brand_version.content_hash if brand_version else None,
        "compiled_artifact_id": artifact.id, "compiled_artifact_hash": artifact.output_hash,
        "compiler_version": COMPILER_VERSION,
    }
    run.input_snapshot = snapshot
    outputs = dict(run.outputs_json or {})
    outputs["prompt_intelligence"] = snapshot["prompt_intelligence_snapshot"]
    run.outputs_json = outputs
    db.add(run); db.commit(); db.refresh(artifact)
    return artifact
