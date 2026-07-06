# Sellform Sprint 25 Social Video Source Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인스타그램 릴스, 쇼츠, 틱톡, 쿠팡 숏클립처럼 영상 중심 상품 소스를 Sellform 프로젝트의 근거 자료로 안전하게 접수한다.

**Architecture:** Sprint 23~24가 상품 URL 텍스트 수집을 다뤘다면, Sprint 25는 영상/소셜 URL을 “직접 크롤링 대상”이 아니라 “근거 수집 프로젝트 소스”로 등록하는 단계다. 플랫폼 정책을 우회하지 않고, 사용자가 직접 볼 수 있는 캡션/설명/댓글 요약/스크린샷/수동 메모를 한곳에 모으는 UX를 만든다.

**Tech Stack:** Next.js, TypeScript, FastAPI, SQLAlchemy, PostgreSQL, pytest, Next.js build.

---

## 1. 제품 결정

이번 스프린트의 핵심은 “영상 URL을 넣으면 Sellform이 바로 다운로드한다”가 아니다. 플랫폼 정책, 로그인, 저작권, 캡차 이슈를 피하기 위해 먼저 안전한 입력 구조를 만든다.

### 이번 스프린트에 하는 것

- 상품 프로젝트 생성/수정 화면에서 `상품 링크` 외에 `영상/소셜 링크`를 추가 입력할 수 있게 한다.
- 지원 소스 유형을 `instagram`, `youtube_shorts`, `tiktok`, `coupang_shortclip`, `smartstore_clip`, `other`로 분류한다.
- 소셜 URL을 저장하고, 사용자가 캡션/영상 설명/댓글에서 확인한 상품 정보를 붙여넣을 수 있게 한다.
- 영상 근거 자료는 “자동 수집됨”이 아니라 “사용자 제공 근거”로 표시한다.
- 링크 직접 수집이 어려운 경우 스크린샷/텍스트/수동 메모를 다음 단계로 넘긴다.

### 이번 스프린트에 하지 않는 것

- 인스타그램/틱톡 영상 무단 다운로드
- 로그인 세션 우회
- 캡차 우회
- 댓글 대량 크롤링
- 영상 프레임 OCR/자막 추출 자동화

---

## 2. 파일 구조

### Backend

- Modify: `backend/src/db/models.py`
  - `ProductProject`에 `social_source_url`, `social_source_type`, `social_source_note` 필드 추가.
- Modify: `backend/src/api/projects.py`
  - 프로젝트 생성/조회/수정 스키마에 소셜 소스 필드 추가.
- Create: `backend/src/services/social_source_classifier.py`
  - URL host/path 기반으로 소셜 소스 유형을 판별.
- Test: `backend/tests/test_social_source_classifier.py`
  - Instagram, YouTube Shorts, TikTok, Coupang, unknown URL 분류 검증.
- Test: `backend/tests/test_projects_social_source.py`
  - 프로젝트 생성/조회 시 소셜 소스 필드가 보존되는지 검증.

### Frontend

- Modify: `frontend/src/app/workspace/projects/new/page.tsx`
  - 영상/소셜 링크 입력 필드 추가.
  - 소셜 URL 입력 시 “영상은 직접 다운로드하지 않고, 사용자가 제공한 근거만 사용합니다” 안내 표시.
- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
  - 소셜 소스가 있는 경우 “영상 근거 입력 패널” 진입 안내 표시.
- Create: `frontend/src/components/SocialVideoSourcePanel.tsx`
  - 소셜 링크 열기, 캡션/설명 붙여넣기, 영상에서 확인한 상품 정보 메모 입력 UI 제공.

### Docs

- Create: `docs/guides/2026-06-26-sellform-social-video-source-guide.md`
- Create: `docs/testing/2026-06-26-sellform-sprint-25-social-video-source-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-sprint-25-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-sprint-25-social-video-source.md`

---

## 3. Task 1: 소셜 소스 분류기 추가

**Files:**
- Create: `backend/src/services/social_source_classifier.py`
- Test: `backend/tests/test_social_source_classifier.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.services.social_source_classifier import classify_social_source


def test_classify_social_source_supported_hosts():
    assert classify_social_source("https://www.instagram.com/p/DZFKa3pgP6R/") == "instagram"
    assert classify_social_source("https://www.youtube.com/shorts/abc123") == "youtube_shorts"
    assert classify_social_source("https://www.tiktok.com/@seller/video/123") == "tiktok"
    assert classify_social_source("https://www.coupang.com/vp/products/123") == "coupang_shortclip"
    assert classify_social_source("https://example.com/product-video") == "other"
```

- [ ] **Step 2: 실패 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_social_source_classifier.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 3: 최소 구현**

```python
from typing import Literal
from urllib.parse import urlparse

SocialSourceType = Literal[
    "instagram",
    "youtube_shorts",
    "tiktok",
    "coupang_shortclip",
    "smartstore_clip",
    "other",
]


def classify_social_source(url: str) -> SocialSourceType:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if "instagram.com" in host:
        return "instagram"
    if "youtube.com" in host and "/shorts/" in path:
        return "youtube_shorts"
    if "youtu.be" in host:
        return "youtube_shorts"
    if "tiktok.com" in host:
        return "tiktok"
    if "coupang.com" in host:
        return "coupang_shortclip"
    if "smartstore.naver.com" in host or "shopping.naver.com" in host:
        return "smartstore_clip"
    return "other"
```

- [ ] **Step 4: 테스트 통과 확인**

Expected:

```text
1 passed
```

---

## 4. Task 2: 프로젝트 모델/API에 소셜 소스 필드 추가

**Files:**
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/api/projects.py`
- Test: `backend/tests/test_projects_social_source.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_create_project_preserves_social_video_source(client):
    headers = {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }

    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": "릴스에서 본 휴대용 선풍기",
            "raw_input_url": "https://www.coupang.com/vp/products/8717208468",
            "raw_input_text": "대용량 배터리 휴대용 선풍기",
            "social_source_url": "https://www.instagram.com/p/DZFKa3pgP6R/",
            "social_source_note": "영상에서 손에 들고 쓰는 장면과 냉각판 강조가 보임",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["social_source_url"] == "https://www.instagram.com/p/DZFKa3pgP6R/"
    assert body["social_source_type"] == "instagram"
    assert "냉각판" in body["social_source_note"]
```

- [ ] **Step 2: 모델 필드 추가**

`ProductProject`에 다음 컬럼을 추가한다.

```python
social_source_url = Column(String, nullable=True)
social_source_type = Column(String, nullable=True)
social_source_note = Column(Text, nullable=True)
```

- [ ] **Step 3: API 스키마와 생성 로직 연결**

프로젝트 생성 요청에서 `social_source_url`이 들어오면 `classify_social_source`를 호출해 `social_source_type`을 저장한다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -m pytest backend\tests\test_projects_social_source.py -q
```

Expected:

```text
1 passed
```

---

## 5. Task 3: 프론트 소셜 링크 입력 UX 추가

**Files:**
- Modify: `frontend/src/app/workspace/projects/new/page.tsx`
- Create: `frontend/src/components/SocialVideoSourcePanel.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: 새 프로젝트 화면에 소셜 링크 입력 필드 추가**

필드 라벨:

```text
영상/소셜 참고 링크 선택
```

안내 문구:

```text
인스타그램 릴스, 쇼츠, 틱톡 등에서 발견한 상품 영상 링크를 넣을 수 있습니다. Sellform은 로그인/캡차를 우회하지 않고, 사용자가 직접 확인한 캡션·설명·스크린샷·메모만 근거로 사용합니다.
```

- [ ] **Step 2: facts 화면에 소셜 근거 입력 패널 표시**

프로젝트에 `social_source_url`이 있으면 다음 기능을 제공한다.

```text
1. 영상 링크 새 탭에서 열기
2. 캡션/설명 붙여넣기
3. 영상에서 확인한 상품 장면 메모 입력
4. 여러 사실 후보로 넘기기
```

- [ ] **Step 3: 프론트 빌드 확인**

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

- 소셜/영상 URL을 프로젝트에 저장할 수 있다.
- URL 유형이 자동 분류된다.
- 사용자는 영상 링크를 새 탭으로 열고, 캡션/설명/메모를 Sellform에 남길 수 있다.
- 소셜 소스는 자동 크롤링 결과가 아니라 사용자 제공 근거로 표시된다.
- 백엔드 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 가이드/테스트로그/코드리뷰/트러블슈팅 문서가 남는다.
