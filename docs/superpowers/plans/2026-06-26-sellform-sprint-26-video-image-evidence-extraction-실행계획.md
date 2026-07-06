# Sellform Sprint 26 Video and Image Evidence Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 업로드한 상품 영상 캡처 이미지, 짧은 클립, 상세페이지 이미지에서 OCR/멀티모달 분석을 통해 사실 카드 후보를 생성한다.

**Architecture:** Sprint 25가 영상/소셜 소스를 프로젝트에 연결했다면, Sprint 26은 사용자가 제공한 이미지·클립 자료를 근거로 구조화한다. 외부 플랫폼에서 영상을 무단 다운로드하지 않고, 사용자가 직접 업로드한 파일만 분석 대상으로 삼는다.

**Tech Stack:** FastAPI UploadFile, PostgreSQL, local asset storage, PIL/OpenCV optional frame extraction, OCR/LLM vision adapter abstraction, pytest, Next.js.

---

## 1. 제품 결정

이번 스프린트는 “영상 URL을 직접 긁기”가 아니라 “사용자가 저장한 이미지/짧은 클립을 근거화하기”다. 실제 판매에 쓸 상세페이지는 근거가 중요하므로, AI가 추정한 내용은 자동 확정하지 않고 `unknown` 또는 `needs_revision`으로 둔다.

### 이번 스프린트에 하는 것

- 이미지/영상 파일 업로드 타입을 명확히 구분한다.
- 이미지 OCR 후보와 영상 프레임 후보를 별도 소스로 기록한다.
- AI Vision 또는 mock adapter를 통해 상품명, 수치, 소재, 사용 장면 후보를 추출한다.
- 추출 결과에는 `asset_id`, `source_kind`, `confidence`, `extraction_note`를 남긴다.
- 사용자는 후보를 확인 후 사실 카드로 저장한다.

### 이번 스프린트에 하지 않는 것

- 저작권이 불명확한 외부 영상 자동 다운로드
- 장시간 영상 전체 분석
- 음성 자막 자동 전사
- 확정 사실 자동 승인

---

## 2. 파일 구조

### Backend

- Create: `backend/src/services/media_evidence_extractor.py`
  - 이미지/영상 자산을 받아 사실 후보를 반환한다.
- Modify: `backend/src/services/image_text_extractor.py`
  - 기존 mock OCR 결과를 media extractor에서 재사용 가능하게 정리한다.
- Modify: `backend/src/api/assets.py`
  - 업로드된 자산의 media type을 반환한다.
- Modify: `backend/src/api/facts.py`
  - 자산 기반 후보 생성 endpoint 추가 또는 기존 auto-extract에 통합.
- Test: `backend/tests/test_media_evidence_extractor.py`
- Test: `backend/tests/test_facts_media_evidence.py`

### Frontend

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
  - 이미지/영상 업로드 후 “자산에서 사실 후보 생성” 버튼 표시.
- Create: `frontend/src/components/MediaEvidenceCandidatePanel.tsx`
  - 자산별 추출 후보 미리보기, 선택 저장, 제외 기능 제공.

### Docs

- Create: `docs/guides/2026-06-26-sellform-media-evidence-extraction-guide.md`
- Create: `docs/testing/2026-06-26-sellform-sprint-26-media-evidence-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-sprint-26-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-sprint-26-media-evidence.md`

---

## 3. Task 1: media evidence extractor 추가

**Files:**
- Create: `backend/src/services/media_evidence_extractor.py`
- Test: `backend/tests/test_media_evidence_extractor.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.services.media_evidence_extractor import MediaEvidenceExtractor


def test_media_evidence_extractor_returns_candidates_for_image_asset():
    extractor = MediaEvidenceExtractor()

    result = extractor.extract_from_asset(
        asset_id="asset-1",
        filename="fan-spec.png",
        media_type="image/png",
        file_path="uploads/fan-spec.png",
    )

    assert result.asset_id == "asset-1"
    assert result.source_kind == "image"
    assert len(result.candidates) >= 1
    assert all(candidate.fact_text for candidate in result.candidates)
```

- [ ] **Step 2: 최소 데이터 구조 구현**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MediaFactCandidate:
    fact_text: str
    source_text: str
    confidence: float
    extraction_note: str


@dataclass(frozen=True)
class MediaEvidenceResult:
    asset_id: str
    source_kind: str
    candidates: list[MediaFactCandidate]
```

- [ ] **Step 3: mock extractor 구현**

초기 구현은 실제 OCR/Vision API 없이 filename과 media type을 기반으로 deterministic 후보를 만든다.

```python
class MediaEvidenceExtractor:
    def extract_from_asset(self, asset_id: str, filename: str, media_type: str, file_path: str) -> MediaEvidenceResult:
        source_kind = "video" if media_type.startswith("video/") else "image"
        return MediaEvidenceResult(
            asset_id=asset_id,
            source_kind=source_kind,
            candidates=[
                MediaFactCandidate(
                    fact_text=f"{filename} 자료에서 확인 가능한 상품 정보가 있습니다.",
                    source_text=f"asset:{asset_id}",
                    confidence=0.4,
                    extraction_note="mock_media_evidence",
                )
            ],
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_media_evidence_extractor.py -q
```

Expected:

```text
1 passed
```

---

## 4. Task 2: 자산 기반 사실 후보 API 추가

**Files:**
- Modify: `backend/src/api/facts.py`
- Test: `backend/tests/test_facts_media_evidence.py`

- [ ] **Step 1: API 테스트 작성**

```python
def test_generate_fact_candidates_from_uploaded_assets(client, setup_project, db_session):
    project_id = setup_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }

    response = client.post(
        f"/api/v1/projects/{project_id}/facts/media-extract",
        headers=headers,
    )

    assert response.status_code in {200, 201}
    body = response.json()
    assert "candidates" in body
```

- [ ] **Step 2: endpoint 구현**

Endpoint:

```text
POST /api/v1/projects/{project_id}/facts/media-extract
```

응답 예시:

```json
{
  "candidates": [
    {
      "asset_id": "asset-1",
      "fact_text": "4,800mAh 배터리 탑재",
      "source_text": "asset:asset-1",
      "confidence": 0.72,
      "extraction_note": "vision_ocr"
    }
  ],
  "failed_assets": []
}
```

- [ ] **Step 3: 테스트 통과 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_facts_media_evidence.py -q
```

Expected:

```text
1 passed
```

---

## 5. Task 3: 프론트 후보 검수 패널 추가

**Files:**
- Create: `frontend/src/components/MediaEvidenceCandidatePanel.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: 업로드 자산이 있을 때 버튼 표시**

버튼 문구:

```text
이미지/영상에서 사실 후보 생성
```

- [ ] **Step 2: 후보 미리보기 UI 추가**

각 후보는 다음 정보를 보여준다.

```text
1. 사실 후보 문장
2. 근거 자산 파일명
3. 신뢰도
4. 저장 / 제외 버튼
```

- [ ] **Step 3: 저장 시 기존 `/facts/bulk` 재사용**

선택된 후보는 `default_status: "unknown"`으로 저장한다.

- [ ] **Step 4: 프론트 빌드 확인**

Run:

```cmd
cd /d C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

---

## 6. 완료 기준

- 사용자가 업로드한 이미지/영상 자산에서 후보 생성 버튼을 사용할 수 있다.
- 후보에는 근거 자산과 신뢰도가 표시된다.
- 후보는 자동 확정되지 않는다.
- 선택한 후보만 사실 카드로 저장된다.
- 백엔드 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 가이드/테스트로그/코드리뷰/트러블슈팅 문서가 남는다.
