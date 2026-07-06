# Sellform Sprint 12 Image OCR & Multimodal Fact Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 업로드된 상품 이미지 안의 텍스트, 옵션표, 사이즈표, 성분표, 패키지 정보를 읽어 사실 카드 후보를 생성한다.

**Architecture:** Sprint 12는 Sprint 10의 자동 사실 카드 생성 API를 확장한다. 기존 `source_asset_id` 연결 구조는 유지하고, 이미지 분석 서비스를 별도 모듈로 분리해 OCR/mock/멀티모달 adapter를 교체 가능하게 만든다. 초기 구현은 deterministic OCR mock과 OCR provider interface를 먼저 만들고, 실제 외부 멀티모달 호출은 설정 플래그와 비용·보안 게이트 뒤에 둔다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Pillow/optional OCR provider, OpenAI or multimodal adapter later, pytest, Next.js facts page existing UI.

---

## 0. Sprint 12 범위 원칙

### 포함

- 이미지 분석 서비스 인터페이스 설계.
- 업로드 이미지 자산별 OCR/mock 결과 생성.
- 이미지에서 추출한 텍스트를 사실 후보로 변환.
- `source_asset_id`로 이미지 근거 연결.
- 낮은 신뢰도 후보는 `needs_revision`.
- 이미지 분석 실패 시 fallback 안내.
- 비용/지연시간/성공률 테스트 로그 기록.

### 제외

- 쿠팡/스마트스토어 자동 업로드.
- 공급처 URL 직접 크롤링.
- 캡차/로그인 우회.
- 이미지 생성/보정.
- 사람 확인 없이 이미지 기반 사실을 자동 `confirmed` 처리하는 동작.

## 1. 파일 구조

### 수정 대상

- `backend/src/services/source_collector.py`
  - 이미지 source에 OCR 결과 텍스트를 포함할 수 있게 확장.
- `backend/src/services/fact_extractor.py`
  - image source text에서 사이즈/성분/옵션/용량 후보를 만들도록 확장.
- `backend/src/api/facts.py`
  - auto-extract 응답에 이미지 분석 실패 정보를 포함.
- `backend/tests/test_facts.py`
  - 이미지 OCR 후보 생성 테스트 추가 또는 분리.
- `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
  - 이미지 분석 실패/낮은 신뢰도 안내 표시.

### 신규 파일

- `backend/src/services/image_text_extractor.py`
  - 이미지 자산을 받아 텍스트 후보와 신뢰도를 반환하는 provider interface.
- `backend/tests/test_image_text_extractor.py`
  - OCR/mock provider 단위 테스트.
- `docs/testing/2026-06-24-sellform-sprint-12-image-ocr-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-12-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-12-image-ocr.md`
- `docs/decisions/2026-06-24-sellform-image-ocr-provider-strategy.md`

## 2. 데이터 계약

이미지 분석 결과는 다음 구조로 둔다.

```python
class ImageTextExtractionResult(BaseModel):
    asset_id: str
    filename: str
    extracted_text: str
    confidence: float
    provider: str
    warnings: list[str] = []
```

실패 결과는 source collector의 `failed_sources`에 포함한다.

```json
{
  "source": "image",
  "reason": "image_text_unavailable",
  "message": "이미지에서 읽을 수 있는 텍스트를 찾지 못했습니다."
}
```

## 3. Task 1: OCR provider 전략 결정

**Files:**

- Create: `docs/decisions/2026-06-24-sellform-image-ocr-provider-strategy.md`

- [ ] **Step 1: 결정 문서를 작성한다**

Create:

```markdown
# 결정 기록: Sellform 이미지 OCR/멀티모달 Provider 전략

- 날짜: 2026-06-24
- 상태: 제안

## 1. 배경

Sprint 10은 이미지 자산을 사실 후보의 근거로 연결했지만, 이미지 안의 텍스트를 실제로 읽지는 않았다.

## 2. 후보

| 후보 | 장점 | 단점 | 1차 적용 여부 |
| --- | --- | --- | --- |
| deterministic mock OCR | 테스트 안정성, 비용 없음 | 실제 이미지 이해 불가 | 적용 |
| local OCR | 비용 낮음 | 설치/언어 인식 품질 변동 | 검토 |
| multimodal LLM | 한국어/중국어/표 인식 가능성 높음 | 비용/지연/개인정보/키 필요 | 후속 |

## 3. 결정

Sprint 12 1차 구현은 deterministic mock OCR + provider interface로 시작한다. 실제 OCR 또는 멀티모달 LLM은 adapter로 추가 가능한 구조만 만든다.

## 4. 안전 원칙

- 이미지 분석 후보는 자동 확정하지 않는다.
- 낮은 신뢰도 후보는 `needs_revision`으로 저장한다.
- API key가 없으면 mock provider로 동작한다.
- 이미지 원본은 외부 provider로 보내기 전에 사용자가 명시적으로 허용해야 한다.
```

## 4. Task 2: image text extractor 서비스 추가

**Files:**

- Create: `backend/src/services/image_text_extractor.py`
- Create: `backend/tests/test_image_text_extractor.py`

- [ ] **Step 1: failing test를 작성한다**

Create `backend/tests/test_image_text_extractor.py`:

```python
from src.services.image_text_extractor import MockImageTextExtractor


def test_mock_image_text_extractor_returns_text_for_spec_like_filename():
    extractor = MockImageTextExtractor()

    result = extractor.extract(
        asset_id="asset-1",
        filename="portable_fan_4000mah_usb_c_spec.jpg",
        file_path="uploads/portable_fan_4000mah_usb_c_spec.jpg",
    )

    assert result.asset_id == "asset-1"
    assert "USB-C" in result.extracted_text
    assert "4000mAh" in result.extracted_text
    assert result.confidence >= 0.5
    assert result.provider == "mock"


def test_mock_image_text_extractor_reports_no_text_for_generic_image():
    extractor = MockImageTextExtractor()

    result = extractor.extract(
        asset_id="asset-2",
        filename="plain_product_photo.jpg",
        file_path="uploads/plain_product_photo.jpg",
    )

    assert result.extracted_text == ""
    assert result.confidence == 0.0
    assert "no_text_detected" in result.warnings
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_image_text_extractor.py -q
```

Expected:

```text
FAIL: ModuleNotFoundError: No module named 'src.services.image_text_extractor'
```

- [ ] **Step 3: 최소 구현을 작성한다**

Create `backend/src/services/image_text_extractor.py`:

```python
from pydantic import BaseModel


class ImageTextExtractionResult(BaseModel):
    asset_id: str
    filename: str
    extracted_text: str
    confidence: float
    provider: str
    warnings: list[str] = []


class MockImageTextExtractor:
    provider = "mock"

    def extract(self, asset_id: str, filename: str, file_path: str) -> ImageTextExtractionResult:
        lowered = filename.lower()
        facts: list[str] = []

        if "usb" in lowered or "type_c" in lowered or "usb_c" in lowered:
            facts.append("USB-C charging supported")
        if "4000" in lowered or "mah" in lowered:
            facts.append("Battery capacity 4000mAh")
        if "size" in lowered or "spec" in lowered:
            facts.append("Product specification image")
        if "ingredient" in lowered or "composition" in lowered:
            facts.append("Ingredient or composition table")

        if not facts:
            return ImageTextExtractionResult(
                asset_id=asset_id,
                filename=filename,
                extracted_text="",
                confidence=0.0,
                provider=self.provider,
                warnings=["no_text_detected"],
            )

        return ImageTextExtractionResult(
            asset_id=asset_id,
            filename=filename,
            extracted_text=". ".join(facts),
            confidence=0.66,
            provider=self.provider,
            warnings=[],
        )
```

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_image_text_extractor.py -q
```

Expected:

```text
2 passed
```

## 5. Task 3: source collector에 이미지 OCR 결과 연결

**Files:**

- Modify: `backend/src/services/source_collector.py`
- Test: `backend/tests/test_facts.py`

- [ ] **Step 1: failing API test를 작성한다**

Add to `backend/tests/test_facts.py`:

```python
def test_auto_extract_uses_image_ocr_text_for_fact_candidates(client, db_session, setup_project):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    project_id = setup_project
    asset = Asset(
        project_id=project_id,
        source_type="sourced",
        filename="portable_fan_4000mah_usb_c_spec.jpg",
        file_path="uploads/portable_fan_4000mah_usb_c_spec.jpg",
        mime_type="image/jpeg",
        file_size=2048,
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    res = client.post(f"/api/v1/projects/{project_id}/facts/auto-extract", headers=headers)

    assert res.status_code == 201
    body = res.json()
    image_facts = [fact for fact in body["facts"] if fact["source_asset_id"] == asset.id]
    assert any("USB-C" in fact["fact_text"] for fact in image_facts)
    assert any("4000mAh" in fact["fact_text"] for fact in image_facts)
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_facts.py::test_auto_extract_uses_image_ocr_text_for_fact_candidates -q
```

Expected:

```text
FAIL: no image fact contains USB-C / 4000mAh
```

- [ ] **Step 3: source collector를 확장한다**

Modify `backend/src/services/source_collector.py`:

```python
from src.services.image_text_extractor import MockImageTextExtractor

# inside collect_project_sources
image_extractor = MockImageTextExtractor()

for asset in assets:
    extracted = image_extractor.extract(
        asset_id=asset.id,
        filename=asset.filename,
        file_path=asset.file_path,
    )
    if extracted.extracted_text:
        sources.append(
            CollectedSource(
                source="image",
                text=extracted.extracted_text,
                asset_id=asset.id,
            )
        )
    else:
        failed_sources.append(
            FailedSource(
                source="image",
                reason="image_text_unavailable",
                message=f"이미지 '{asset.filename}'에서 읽을 수 있는 텍스트를 찾지 못했습니다.",
            )
        )
```

- [ ] **Step 4: fact extractor가 image text에도 패턴을 적용하게 한다**

Modify `backend/src/services/fact_extractor.py`:

```python
elif source.source == "image":
    image_candidates = _extract_from_manual_text(source)
    if image_candidates:
        for candidate in image_candidates:
            candidates.append(
                ExtractedFactCandidate(
                    fact_text=candidate.fact_text,
                    source_text=source.text,
                    source_asset_id=source.asset_id,
                    confidence=min(candidate.confidence, 0.72),
                    extraction_source="image",
                    needs_review=True,
                    risk_flags=candidate.risk_flags,
                )
            )
    else:
        candidates.append(...)
```

- [ ] **Step 5: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_facts.py::test_auto_extract_uses_image_ocr_text_for_fact_candidates -q
```

Expected:

```text
1 passed
```

## 6. Task 4: 이미지 분석 실패 fallback UI 표시

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: image failed source 메시지를 한국어로 표시한다**

`failed_sources` 렌더링 시 다음 매핑을 추가한다.

```tsx
const FAILED_SOURCE_MESSAGES: Record<string, string> = {
  url_collection_deferred: "링크 직접 수집은 아직 지원하지 않아 입력 텍스트와 업로드 이미지를 우선 분석했습니다.",
  image_text_unavailable: "일부 이미지에서 읽을 수 있는 텍스트를 찾지 못했습니다. 필요한 정보는 수동으로 추가해 주세요.",
};
```

- [ ] **Step 2: 이미지 분석 실패가 있어도 성공 후보는 표시되게 유지한다**

자동 생성 결과 배너에 다음 문구를 포함한다.

```tsx
{autoExtractResult.failed_sources.length > 0 && (
  <p className="text-amber-300">
    일부 자료는 자동 분석하지 못했습니다. 생성된 후보를 검수하고 부족한 정보는 수동으로 추가해 주세요.
  </p>
)}
```

- [ ] **Step 3: 프론트 빌드를 실행한다**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

## 7. Task 5: 전체 테스트와 문서 산출물

**Files:**

- Create: `docs/testing/2026-06-24-sellform-sprint-12-image-ocr-test-log.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-12-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-12-image-ocr.md`

- [ ] **Step 1: 백엔드 테스트 실행**

Run:

```powershell
uv run --project backend pytest backend/tests/test_image_text_extractor.py backend/tests/test_facts.py -q
uv run --project backend pytest -q
```

Expected:

```text
All tests passed
```

- [ ] **Step 2: 프론트 빌드 실행**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

- [ ] **Step 3: 테스트 로그 작성**

Create `docs/testing/2026-06-24-sellform-sprint-12-image-ocr-test-log.md`:

```markdown
# 테스트 실행 로그: Sellform Sprint 12 Image OCR

- 날짜: 2026-06-24
- 목적: 이미지 OCR/mock 분석 결과가 사실 카드 후보로 연결되는지 검증한다.

## 1. OCR provider 단위 테스트

```text
uv run --project backend pytest backend/tests/test_image_text_extractor.py -q
결과:
```

## 2. facts API 회귀 테스트

```text
uv run --project backend pytest backend/tests/test_facts.py -q
결과:
```

## 3. 전체 테스트

```text
uv run --project backend pytest -q
결과:
```

## 4. 프론트 빌드

```text
npm.cmd run build
결과:
```

## 5. 판단
```

- [ ] **Step 4: 코드리뷰 문서 작성**

Create `docs/reviews/2026-06-24-sellform-sprint-12-code-review.md`:

```markdown
# 코드 리뷰: Sellform Sprint 12 (Image OCR & Multimodal Fact Extraction)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | image text extractor, source collector image OCR integration, fact extractor image candidates, UI fallback |
| 리뷰어 | Codex |
| 상태 | 검토 필요 |

## 1. 변경 요약

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| 이미지 OCR/mock provider | 미확인 | `backend/tests/test_image_text_extractor.py` |
| 이미지 텍스트 기반 사실 후보 | 미확인 | `backend/tests/test_facts.py` |
| source_asset_id 연결 | 미확인 | API 응답 |
| 낮은 신뢰도 자동 확정 방지 | 미확인 | verification_status |
| 이미지 분석 실패 fallback | 미확인 | UI/API |
| 테스트/빌드 | 미확인 | testing log |

## 3. 이슈 목록

## 4. 테스트 증적

## 5. 결론
```

- [ ] **Step 5: 트러블슈팅 문서 작성**

Create `docs/troubleshooting/2026-06-24-sellform-sprint-12-image-ocr.md`:

```markdown
# 트러블슈팅: Sellform Sprint 12 Image OCR

## 1. 개요

## 2. 발견 이슈

### M1. 이미지에서 텍스트를 찾지 못함

- 증상:
- 원인:
- 조치:

### M2. OCR 후보 신뢰도 낮음

- 증상:
- 원인:
- 조치:

## 3. 후속 과제

- 실제 OCR provider 검토
- 멀티모달 LLM 비용/정확도 비교
- 사용자 동의 기반 외부 이미지 분석 정책

## 4. 결론
```

## 8. 완료 기준

- 이미지 파일명/mock OCR 결과에서 텍스트 후보가 생성된다.
- 이미지 텍스트에서 1개 이상 사실 카드 후보가 생성된다.
- 생성된 후보는 `source_asset_id`로 이미지 근거와 연결된다.
- 이미지 분석 실패 시 API가 전체 실패하지 않고 `failed_sources`에 실패 사유를 담는다.
- 낮은 신뢰도 또는 위험 후보는 자동 `confirmed` 처리되지 않는다.
- 프론트에서 이미지 분석 실패 안내가 사용자 친화적으로 표시된다.
- 백엔드 전체 테스트와 프론트 빌드가 통과한다.
- 테스트 로그, 코드리뷰, 트러블슈팅, provider 결정 문서가 남는다.

