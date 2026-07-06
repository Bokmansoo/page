# Sellform Sprint 20 Grounded Page Generation Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상세페이지 생성 시 확인된 사실 카드를 중심으로 문구를 만들고, 근거가 필요한 표현은 경고/수정 제안으로 검수할 수 있게 만든다.

**Architecture:** 상세페이지 생성 엔진에 `grounding validator`를 추가한다. 확인된 사실 카드는 강한 주장 생성의 근거로 쓰고, 일반적인 사용 장면/감성 표현은 허용하되 성능·수치·효능·안전·건강·인증·비교 우위 표현은 근거가 없으면 위험 문구로 분류한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Python services, Next.js, TypeScript, React, Tailwind CSS, pytest.

---

## 1. 제품 결정

생성 원칙은 다음으로 확정한다.

```text
확인된 사실 카드를 중심으로 상세페이지를 만들되,
일반적인 사용 장면과 감성 표현은 허용한다.
하지만 성능, 효능, 수치, 안전, 건강, 인증, 비교 우위 표현은
근거 없으면 금지하거나 위험 문구로 경고한다.
```

검수 UX는 `간단 요약 + 상세 패널` 구조를 사용한다.

- 기본 화면: 상세페이지 미리보기 중심
- 상단 요약: `주의 필요 N건`, `근거 연결 완료 N개 섹션`, `확인된 사실 N개 사용`
- 상세 패널: 섹션별 근거 카드, 위험 문구, 수정 제안

---

## 2. 파일 구조

### Backend

- Create: `backend/src/services/grounding_validator.py`
  - 생성 문구와 확인된 사실 카드의 연결 상태를 검증한다.
- Modify: existing page generation service
  - 섹션별 source fact mapping과 warning list를 반환한다.
- Test: `backend/tests/test_grounding_validator.py`

### Frontend

- Create or Modify: `frontend/src/.../GroundingReviewPanel.tsx`
  - 검수 요약과 상세 패널을 표시한다.
- Modify: page-editor UI
  - 위험 문구 요약과 섹션별 근거 확인을 연결한다.

### Docs

- Create: `docs/testing/2026-06-24-sellform-sprint-20-grounded-generation-test-log.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-20-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-20-grounded-generation.md`

---

## 3. Task 1: 위험 표현 분류기 테스트와 구현

**Files:**

- Create: `backend/src/services/grounding_validator.py`
- Test: `backend/tests/test_grounding_validator.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.grounding_validator import detect_claim_risks


def test_detects_numeric_and_performance_claim_without_evidence():
    warnings = detect_claim_risks(
        text="1초 만에 체감 온도 -10도, 업계 최고 냉각 성능을 제공합니다.",
        confirmed_facts=["4,800mAh 배터리", "최대 18시간 무선 사용"],
    )

    assert len(warnings) >= 2
    assert any(warning.risk_type == "numeric_claim_without_evidence" for warning in warnings)
    assert any(warning.risk_type == "performance_claim_without_evidence" for warning in warnings)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_grounding_validator.py -q
```

Expected:

```text
FAILED ... ModuleNotFoundError 또는 ImportError
```

- [ ] **Step 3: 최소 구현**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class GroundingWarning:
    risk_type: str
    phrase: str
    reason: str
    suggestion: str


NUMERIC_PATTERNS = ["-10도", "1초", "100%", "1위", "최고"]
PERFORMANCE_PATTERNS = ["업계 최고", "초강력", "최강", "압도적"]
SAFETY_PATTERNS = ["안전한", "무독성", "어린이 안전", "알레르기 걱정 없음"]
HEALTH_PATTERNS = ["의학", "치료", "예방", "개선", "효능"]
CERTIFICATION_PATTERNS = ["KC 인증", "인증 완료", "공식 인증"]


def _has_evidence(phrase: str, confirmed_facts: list[str]) -> bool:
    compact_phrase = phrase.replace(" ", "").lower()
    for fact in confirmed_facts:
        if compact_phrase in fact.replace(" ", "").lower():
            return True
    return False


def detect_claim_risks(text: str, confirmed_facts: list[str]) -> list[GroundingWarning]:
    warnings: list[GroundingWarning] = []

    for phrase in NUMERIC_PATTERNS:
        if phrase in text and not _has_evidence(phrase, confirmed_facts):
            warnings.append(
                GroundingWarning(
                    "numeric_claim_without_evidence",
                    phrase,
                    "수치 표현은 확인된 사실 카드에 근거가 있어야 합니다.",
                    "확인된 수치만 사용하거나 표현을 완화하세요.",
                )
            )

    for phrase in PERFORMANCE_PATTERNS:
        if phrase in text and not _has_evidence(phrase, confirmed_facts):
            warnings.append(
                GroundingWarning(
                    "performance_claim_without_evidence",
                    phrase,
                    "성능 우위 표현은 비교 근거가 필요합니다.",
                    "시원한 바람을 보조하는 제품처럼 완화된 표현을 사용하세요.",
                )
            )

    for phrase in SAFETY_PATTERNS + HEALTH_PATTERNS + CERTIFICATION_PATTERNS:
        if phrase in text and not _has_evidence(phrase, confirmed_facts):
            warnings.append(
                GroundingWarning(
                    "regulated_claim_without_evidence",
                    phrase,
                    "안전, 건강, 인증 표현은 명확한 근거가 필요합니다.",
                    "근거를 추가하거나 해당 표현을 삭제하세요.",
                )
            )

    return warnings
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_grounding_validator.py -q
```

Expected:

```text
1 passed
```

---

## 4. Task 2: 섹션별 근거 카드 매핑

**Files:**

- Modify: `backend/src/services/grounding_validator.py`
- Test: `backend/tests/test_grounding_validator.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.grounding_validator import map_section_to_facts


def test_maps_section_to_relevant_confirmed_facts():
    matched = map_section_to_facts(
        section_text="4,800mAh 대용량 배터리로 최대 18시간 무선 사용이 가능합니다.",
        confirmed_facts=[
            "4,800mAh 배터리",
            "최대 18시간 무선 사용",
            "휴대용 무선 냉각 선풍기",
        ],
    )

    assert matched == ["4,800mAh 배터리", "최대 18시간 무선 사용"]
```

- [ ] **Step 2: 최소 구현**

```python
def map_section_to_facts(section_text: str, confirmed_facts: list[str]) -> list[str]:
    normalized_text = section_text.replace(",", "").replace(" ", "").lower()
    matched: list[str] = []

    for fact in confirmed_facts:
        keywords = [token for token in fact.replace(",", "").split() if len(token) >= 2]
        if any(keyword.replace(" ", "").lower() in normalized_text for keyword in keywords):
            matched.append(fact)

    return matched
```

- [ ] **Step 3: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_grounding_validator.py -q
```

Expected:

```text
2 passed
```

---

## 5. Task 3: 검수 요약 생성

**Files:**

- Modify: `backend/src/services/grounding_validator.py`
- Test: `backend/tests/test_grounding_validator.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.grounding_validator import build_grounding_review


def test_builds_grounding_review_summary():
    review = build_grounding_review(
        sections=[
            {"key": "main_claim", "title": "오래 지속되는 시원함", "body": "4,800mAh 배터리로 최대 18시간 무선 사용이 가능합니다."},
            {"key": "benefit_list", "title": "강력한 냉각", "body": "업계 최고 냉각 성능을 제공합니다."},
        ],
        confirmed_facts=["4,800mAh 배터리", "최대 18시간 무선 사용"],
    )

    assert review["summary"]["warning_count"] >= 1
    assert review["summary"]["grounded_section_count"] == 1
    assert review["summary"]["used_fact_count"] == 2
```

- [ ] **Step 2: 구현**

```python
def build_grounding_review(sections: list[dict], confirmed_facts: list[str]) -> dict:
    section_reviews = []
    used_facts = set()
    warning_count = 0
    grounded_section_count = 0

    for section in sections:
        text = f"{section.get('title', '')} {section.get('body', '')}"
        matched_facts = map_section_to_facts(text, confirmed_facts)
        warnings = detect_claim_risks(text, confirmed_facts)

        for fact in matched_facts:
            used_facts.add(fact)
        if matched_facts:
            grounded_section_count += 1
        warning_count += len(warnings)

        section_reviews.append(
            {
                "section_key": section.get("key"),
                "matched_facts": matched_facts,
                "warnings": [warning.__dict__ for warning in warnings],
            }
        )

    return {
        "summary": {
            "warning_count": warning_count,
            "grounded_section_count": grounded_section_count,
            "used_fact_count": len(used_facts),
        },
        "sections": section_reviews,
    }
```

- [ ] **Step 3: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_grounding_validator.py -q
```

Expected:

```text
3 passed
```

---

## 6. Task 4: 프론트 검수 패널

**Files:**

- Create or Modify: `frontend/src/.../GroundingReviewPanel.tsx`
- Modify: page-editor UI

- [ ] **Step 1: 검수 요약 표시**

상단에 다음 정보를 표시한다.

```text
주의 필요 N건
근거 연결 완료 N개 섹션
확인된 사실 N개 사용
```

- [ ] **Step 2: 상세 패널 표시**

클릭 시 섹션별로 다음 정보를 보여준다.

```text
섹션 이름
연결된 사실 카드
위험 문구
위험 사유
수정 제안
```

- [ ] **Step 3: 프론트 빌드 검증**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
✓ built
```

---

## 7. 완료 기준

- 확인된 사실 기반 문구와 일반 감성 표현이 공존할 수 있다.
- 성능, 수치, 효능, 안전, 건강, 인증, 비교 우위 표현은 근거 없으면 경고된다.
- 상세페이지 생성 후 검수 요약이 표시된다.
- 상세 패널에서 섹션별 근거 카드와 위험 문구를 확인할 수 있다.
- 위험 문구에는 수정 제안이 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

---

## 8. 검증 명령

```powershell
uv run --project backend pytest backend/tests/test_grounding_validator.py -q
cd frontend
npm.cmd run build
```
