# Sellform Sprint 27 Social Video to Detail Page Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 소셜 영상/이미지/수동 근거에서 확인된 사실 카드를 바탕으로 생활/리빙 상품의 7단 설득형 상세페이지 초안을 생성하고 저장/export 흐름까지 연결한다.

**Architecture:** Sprint 25는 소셜 소스 접수, Sprint 26은 미디어 근거 추출, Sprint 27은 그 근거를 상세페이지 구조로 변환하는 제품 흐름이다. 기본 7단 구조는 유지하되, 영상 기반 상품은 “사용 장면 → 문제 제기 → 해결 주장 → 구매 판단 정보” 흐름이 자연스럽게 보이도록 섹션 문구를 조정한다.

**Tech Stack:** FastAPI, SQLAlchemy, LLM router, grounded page generator, Next.js page editor, version/export pipeline, pytest, frontend build.

---

## 1. 제품 결정

영상 기반 소싱 상품은 대개 “눈에 보이는 사용 장면”에서 구매 욕구가 생긴다. 따라서 상세페이지는 단순 스펙 나열보다 “영상에서 보인 불편/상황 → 제품이 해결하는 방식 → 확인된 스펙 → 구매 전 체크” 순서가 더 적합하다.

### 이번 스프린트에 하는 것

- 소셜/영상 소스가 있는 프로젝트에 `영상 기반 상세페이지 생성` 모드를 제공한다.
- 확인된 사실 카드만 핵심 주장에 사용한다.
- 영상 장면 메모는 감성/상황 설명으로만 사용하고, 수치·효능 주장은 확인된 사실 카드가 있을 때만 사용한다.
- 기본 7단 구조를 영상형으로 변형한다.
- 생성된 초안은 기존 page-editor, version, export 흐름으로 이어진다.

### 이번 스프린트에 하지 않는 것

- 영상 광고 자동 제작
- 음성 내레이션 생성
- 플랫폼별 업로드 자동화
- 근거 없는 Before/After 효능 주장 생성

---

## 2. 영상형 7단 상세페이지 구조

기본 구조:

```text
1. 문제 제기: 영상에서 보이는 고객의 핵심 불편
2. 메인 소구점 강조: 이 제품으로 해결 가능한 핵심 메시지
3. 소구점 B: 추가 장점
4. 소구점 A 보강: 메인 메시지 재강조
5. 소구점 B~D: 나머지 장점 정리
6. 소구점 요약: 전체 흐름 한 문장 정리
7. 상품 정보: 최종 구매 판단용 정보
```

영상형 변형:

```text
1. 사용 장면 후킹: 영상에서 본 상황을 구매 맥락으로 설명
2. 문제 제기: 사용자가 겪는 불편을 명확히 제시
3. 핵심 해결 메시지: 확인된 사실 기반 메인 소구
4. 체감 장점: 사용 장면에서 기대할 수 있는 장점
5. 스펙 근거: 확인된 수치/구성/소재
6. 구매 전 체크: 주의사항, 구성품, 크기, 호환성
7. 요약 CTA: 누구에게 적합한지 한 문장으로 정리
```

---

## 3. 파일 구조

### Backend

- Create: `backend/src/services/social_video_page_planner.py`
  - 영상형 상세페이지 섹션 구조 생성.
- Modify: `backend/src/services/page_generator.py`
  - 프로젝트에 social source가 있고 사용자가 영상형 모드를 선택하면 social video planner를 사용.
- Modify: `backend/src/api/pages.py`
  - 상세페이지 생성 요청에 `generation_mode: "default" | "social_video"` 추가.
- Test: `backend/tests/test_social_video_page_planner.py`
- Test: `backend/tests/test_pages_social_video_generation.py`

### Frontend

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - 소셜 소스가 있는 프로젝트에 `영상 기반 상세페이지 생성` 옵션 표시.
- Modify: `frontend/src/components/StyleStrategySelector.tsx`
  - 영상형 후보 카드에 디자인 미리보기와 판매 전략 설명 표시.

### Docs

- Create: `docs/guides/2026-06-26-sellform-social-video-detail-page-guide.md`
- Create: `docs/testing/2026-06-26-sellform-sprint-27-social-video-page-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-sprint-27-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-sprint-27-social-video-page.md`

---

## 4. Task 1: 영상형 페이지 플래너 추가

**Files:**
- Create: `backend/src/services/social_video_page_planner.py`
- Test: `backend/tests/test_social_video_page_planner.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.services.social_video_page_planner import build_social_video_sections


def test_build_social_video_sections_uses_seven_part_structure():
    facts = [
        {"fact_text": "4,800mAh 배터리를 탑재했습니다.", "verification_status": "confirmed"},
        {"fact_text": "최대 18시간 무선 사용이 가능합니다.", "verification_status": "confirmed"},
        {"fact_text": "FAN JET ULTRA 모델입니다.", "verification_status": "confirmed"},
    ]

    sections = build_social_video_sections(
        product_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        scene_note="야외에서 손에 들고 사용하는 영상 장면이 확인됨",
        facts=facts,
    )

    assert len(sections) == 7
    assert sections[0]["section_type"] == "VIDEO_HOOK"
    assert sections[-1]["section_type"] == "SUMMARY_CTA"
    assert any("4,800mAh" in section["body"] for section in sections)
```

- [ ] **Step 2: 플래너 구현**

플래너는 확인된 사실만 핵심 주장에 넣고, `scene_note`는 사용 장면 설명에만 사용한다.

- [ ] **Step 3: 테스트 통과 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_social_video_page_planner.py -q
```

Expected:

```text
1 passed
```

---

## 5. Task 2: 페이지 생성 API에 영상형 모드 추가

**Files:**
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/services/page_generator.py`
- Test: `backend/tests/test_pages_social_video_generation.py`

- [ ] **Step 1: API 테스트 작성**

```python
def test_generate_social_video_page_requires_confirmed_facts(client, setup_project):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }

    response = client.post(
        f"/api/v1/projects/{setup_project}/pages/generate",
        headers=headers,
        json={"generation_mode": "social_video"},
    )

    assert response.status_code in {400, 422}
    assert "confirmed facts" in response.text.lower() or "확인된 사실" in response.text
```

- [ ] **Step 2: request schema 확장**

```python
generation_mode: Literal["default", "social_video"] = "default"
```

- [ ] **Step 3: social_video 모드 라우팅**

`generation_mode == "social_video"`일 때 `build_social_video_sections`를 호출한다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_pages_social_video_generation.py -q
```

Expected:

```text
1 passed
```

---

## 6. Task 3: page-editor 영상형 생성 UX 추가

**Files:**
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

- [ ] **Step 1: 소셜 소스가 있는 경우 모드 선택 표시**

옵션:

```text
기본 상세페이지
영상 기반 상세페이지
```

- [ ] **Step 2: 영상형 선택 시 설명 표시**

문구:

```text
영상에서 확인한 사용 장면을 후킹으로 사용하되, 수치·효능·성능 주장은 확인된 사실 카드만 근거로 사용합니다.
```

- [ ] **Step 3: 생성 요청에 generation_mode 전달**

```ts
body: JSON.stringify({ generation_mode: selectedGenerationMode })
```

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

## 7. 완료 기준

- 소셜 소스가 있는 프로젝트에서 영상 기반 상세페이지 생성 모드를 선택할 수 있다.
- 영상형 상세페이지는 7단 구조를 유지한다.
- 사용 장면은 후킹/상황 설명에만 사용된다.
- 수치·성능·효능 주장은 확인된 사실 카드가 있을 때만 사용된다.
- 생성 결과는 page-editor, version, export 흐름으로 이어진다.
- 백엔드 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 가이드/테스트로그/코드리뷰/트러블슈팅 문서가 남는다.
