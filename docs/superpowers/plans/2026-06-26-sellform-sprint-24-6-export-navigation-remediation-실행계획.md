# Sprint 24.6 - Export 가독성 및 단계 이동 UX 보완 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint 24 이후 실사용 테스트에서 발견된 상세페이지 export 가독성 문제와 단계 이동 UX 문제를 안정화한다.

**Architecture:** 기존 상세페이지 생성·편집·export 흐름은 유지하고, export 렌더링 계층과 화면 상단 이동 버튼만 작게 보완한다. AI 배경 비주얼 생성처럼 범위가 커지는 디자인 고도화는 Sprint 28로 분리한다.

**Tech Stack:** FastAPI, Python, Pillow, Next.js, TypeScript, React, PostgreSQL-only 로컬 개발 환경.

---

## 배경

Sprint 24까지 구현된 흐름에서 사용자는 상품 URL 기반 사실 카드 생성, 사실 확인, 상세페이지 편집, export까지 도달할 수 있었다. 다만 실제 export 결과에서 다음 문제가 확인되었다.

- 긴 세로 PNG의 한글 문구가 너무 작거나 깨져 보여 상세페이지 결과물로 쓰기 어렵다.
- page-editor 상단의 뒤로가기 버튼이 직전 단계가 아니라 대시보드로 이동한다.
- publish 화면의 뒤로가기 버튼이 직전 단계인 export가 아니라 page-editor로 이동한다.
- 상품에 맞는 AI 배경/히어로 비주얼은 필요하지만, export 안정화와는 별도 스프린트로 다루는 것이 안전하다.

## 범위

- [x] export 결과물에서 한글이 깨지지 않도록 한국어 지원 폰트 로더를 추가한다.
- [x] export 이미지 폭과 제목/본문 폰트 크기를 키워 모바일 상세페이지 가독성을 개선한다.
- [x] 긴 문장과 모델명/KC 인증 문구가 화면 밖으로 밀리지 않도록 줄바꿈을 적용한다.
- [x] page-editor 상단 이동 버튼을 “사실 확인으로 돌아가기”로 변경한다.
- [x] publish 상단 이동 버튼을 “저장/내보내기로 돌아가기”로 변경한다.
- [x] AI 배경 비주얼 생성은 Sprint 28 실행계획으로 분리한다.
- [x] 테스트 로그, 코드리뷰 문서, 트러블슈팅 문서를 남긴다.

## 제외 범위

- AI 이미지 생성 Provider 연동.
- 상품별 배경/히어로 이미지 후보 생성.
- 쿠팡/스마트스토어 자동 업로드.
- 상세페이지 디자인 시스템 전면 개편.

## 변경 파일

- Modify: `backend/src/services/export_service.py`
  - 한글 폰트 로더, 줄바꿈, export 폭/폰트 크기 개선.
- Modify: `backend/tests/test_export_service.py`
  - 한글 폰트 로딩과 export 이미지 폭 검증 테스트.
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - page-editor 상단 뒤로가기 경로 변경.
- Modify: `frontend/src/app/workspace/projects/[id]/publish/page.tsx`
  - publish 상단 뒤로가기 경로 변경.
- Create: `docs/testing/2026-06-26-sellform-export-navigation-remediation-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-export-navigation-remediation-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-export-navigation-remediation.md`
- Create: `docs/superpowers/plans/2026-06-26-sellform-sprint-28-ai-background-visual-generation-실행계획.md`

## Task 1: Export 한글 렌더링 테스트 추가

- [x] **Step 1: 실패 테스트 작성**

`backend/tests/test_export_service.py`

```python
def test_load_export_font_supports_korean_text():
    font = load_export_font(24)
    bbox = font.getbbox("루메나 휴대용 무선 냉각선풍기")
    assert bbox[2] > bbox[0]
    assert bbox[3] > bbox[1]
```

- [x] **Step 2: 실패 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q
```

Expected:

```text
ImportError: cannot import name 'load_export_font'
```

- [x] **Step 3: 최소 구현**

`backend/src/services/export_service.py`

- `load_export_font(size, bold=False)` 추가.
- Windows `NotoSansKR`, `Malgun Gothic`, Linux `NotoSansCJK`, `NanumGothic` 후보를 순서대로 로드.
- 실패 시 Pillow default font로 fallback.

- [x] **Step 4: 통과 확인**

Run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q
```

Expected:

```text
5 passed
```

## Task 2: Export 이미지 가독성 개선

- [x] **Step 1: 실패 테스트 작성**

`backend/tests/test_export_service.py`

```python
def test_run_export_creates_readable_mobile_width_image_for_korean_content():
    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "sections": [
            {
                "key": "problem_statement",
                "title": "작은 불편이 쌓이면 일상이 번거로워집니다",
                "body": "루메나 휴대용 무선 냉각선풍기는 외출과 실내 사용 환경에서 확인된 상품 정보를 바탕으로 시원한 사용 경험을 제안합니다.",
            },
            {
                "key": "product_information",
                "title": "상품 정보",
                "body": "KC 인증정보와 모델명 FAN JET ULTRA를 확인했습니다.",
            },
        ],
    }

    result = run_export("project-ko", "version-ko", snapshot)

    from PIL import Image
    with Image.open(result["long_vertical_image"]) as image:
        assert image.width >= 720
        assert image.height > 500
```

- [x] **Step 2: 실패 확인**

Expected:

```text
image.width is 480
```

- [x] **Step 3: 최소 구현**

`backend/src/services/export_service.py`

- export width를 `860`으로 확대.
- label/title/body font를 분리.
- `_wrap_text`로 긴 한글 문장과 모델명 줄바꿈 처리.
- section height를 실제 줄 수 기반으로 계산.

- [x] **Step 4: 통과 확인**

Expected:

```text
5 passed
```

## Task 3: 단계별 뒤로가기 UX 수정

- [x] **Step 1: page-editor 뒤로가기 변경**

`frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

```tsx
onClick={() => router.push(`/workspace/projects/${projectId}/facts`)}
```

버튼 문구:

```text
← 사실 확인으로 돌아가기
```

- [x] **Step 2: publish 뒤로가기 변경**

`frontend/src/app/workspace/projects/[id]/publish/page.tsx`

```tsx
onClick={() => router.push(`/workspace/projects/${projectId}/export`)}
```

버튼 문구:

```text
← 저장/내보내기로 돌아가기
```

- [x] **Step 3: 프론트 빌드 확인**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

## Task 4: AI 배경 비주얼 생성 분리

- [x] **Step 1: Sprint 28 실행계획 작성**

Create:

```text
docs/superpowers/plans/2026-06-26-sellform-sprint-28-ai-background-visual-generation-실행계획.md
```

- [x] **Step 2: Sprint 28 범위 정의**

Sprint 28은 다음을 담당한다.

- 상품명·카테고리·확인된 사실 기반 배경 후보 생성.
- fallback 배경 후보 제공.
- 선택된 배경의 미리보기/export 반영.
- 타사 로고·인증마크·실물 제품 이미지 임의 생성 방지.

## 검증 결과

| 검증 | 명령 | 결과 |
| --- | --- | --- |
| Backend export test | `backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q` | `5 passed` |
| Frontend build | `cd frontend && npm.cmd run build` | 성공 |

## 산출물

- `docs/testing/2026-06-26-sellform-export-navigation-remediation-test-log.md`
- `docs/reviews/2026-06-26-sellform-export-navigation-remediation-code-review.md`
- `docs/troubleshooting/2026-06-26-sellform-export-navigation-remediation.md`
- `docs/superpowers/plans/2026-06-26-sellform-sprint-28-ai-background-visual-generation-실행계획.md`

## 완료 기준

- [x] 새 export PNG는 한글 지원 폰트로 렌더링된다.
- [x] export 이미지 폭이 720px 이상이다.
- [x] 긴 한국어 문장과 모델명이 줄바꿈된다.
- [x] page-editor에서 사실 확인 단계로 돌아갈 수 있다.
- [x] publish에서 저장/내보내기 단계로 돌아갈 수 있다.
- [x] AI 배경 비주얼은 Sprint 28로 분리되어 계획 문서가 존재한다.
- [x] 테스트 로그, 코드리뷰, 트러블슈팅 문서가 존재한다.

## 다음 작업

1. 백엔드 서버를 재시작한다.
2. 기존 루메나 프로젝트에서 새 export를 다시 생성한다.
3. 새 PNG의 한글 가독성, 줄바꿈, 섹션 간격을 육안 QA한다.
4. 결과물이 안정적이면 Sprint 28 구현으로 넘어간다.

