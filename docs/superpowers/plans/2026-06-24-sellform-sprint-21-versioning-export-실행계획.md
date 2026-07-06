# Sellform Sprint 21 Versioning & Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상세페이지 생성/재생성/큰 수정 시 버전 스냅샷을 저장하고, 최종본을 긴 세로 이미지와 섹션별 이미지 ZIP으로 내보낼 수 있게 만든다.

**Architecture:** 상품 프로젝트 아래에 `fact set`, `detail page version`, `export artifact`를 분리한다. 사용자는 이전 버전을 복원하고, 최종본을 지정한 뒤 export를 실행한다.

**Tech Stack:** FastAPI, SQLAlchemy, file storage, Playwright or browser screenshot/export utility, Next.js, TypeScript, React, Tailwind CSS, pytest.

---

## 1. 제품 결정

Sprint 21에서는 기본 버전 관리와 export 1차 완성을 구현한다.

### 버전 관리

- AI 초안 생성 시 버전 저장
- 스타일 재추천/재생성 시 버전 저장
- 큰 수정 시 버전 저장
- 이전 버전 복원 가능
- 최종본 표시 가능

나중에 고도화할 C 범위:

- 버전 비교
- 변경 이력
- 누가 수정했는지
- 코멘트/리뷰
- 팀 협업 승인 플로우

### Export

초기 export 기본값:

- 긴 세로 이미지 1장
- 섹션별 이미지 ZIP

추후 고도화:

- PDF 검수본
- HTML
- 쿠팡/스마트스토어별 권장 사이즈 자동 분할
- 이미지 최적화
- 이미지 호스팅/CDN 업로드
- 마켓 자동 업로드

---

## 2. 파일 구조

### Backend

- Modify: `backend/src/models.py`
  - `DetailPageVersion`, `ExportArtifact` 모델을 추가하거나 기존 모델을 확장한다.
- Create: `backend/src/services/page_version_service.py`
  - 버전 생성, 목록 조회, 복원, 최종본 지정 로직을 담당한다.
- Create: `backend/src/services/export_service.py`
  - 긴 세로 이미지와 섹션별 ZIP export를 담당한다.
- Modify: page-editor API router
  - 버전/복원/export API를 연결한다.
- Test: `backend/tests/test_page_version_service.py`
- Test: `backend/tests/test_export_service.py`

### Frontend

- Modify: page-editor UI
  - 자동 저장 버전 목록, 복원 버튼, 최종본 표시를 제공한다.
- Create or Modify: `frontend/src/.../ExportPanel.tsx`
  - 긴 이미지/섹션별 ZIP export 버튼과 진행 상태를 표시한다.

### Docs

- Create: `docs/testing/2026-06-24-sellform-sprint-21-versioning-export-test-log.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-21-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-21-versioning-export.md`

---

## 3. Task 1: 상세페이지 버전 서비스

**Files:**

- Create: `backend/src/services/page_version_service.py`
- Test: `backend/tests/test_page_version_service.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.page_version_service import create_page_version, restore_page_version


def test_create_and_restore_page_version():
    version = create_page_version(
        project_id="project-1",
        name="v1 문제 해결형 초안",
        sections=[
            {"key": "problem_statement", "title": "작은 불편", "body": "더운 날 외출이 번거롭습니다."},
        ],
        style_key="problem_solution",
    )

    restored = restore_page_version(version.id)

    assert restored.project_id == "project-1"
    assert restored.name == "v1 문제 해결형 초안"
    assert restored.sections[0]["key"] == "problem_statement"
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_version_service.py -q
```

Expected:

```text
FAILED ... ModuleNotFoundError 또는 ImportError
```

- [ ] **Step 3: 최소 구현**

프로젝트의 기존 DB 패턴을 확인한 뒤 SQLAlchemy 모델 기반으로 구현한다. 테스트 격리를 위해 in-memory repository 또는 test DB fixture를 사용한다.

필수 필드:

```text
id
project_id
name
style_key
sections_json
is_final
created_at
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_version_service.py -q
```

Expected:

```text
passed
```

---

## 4. Task 2: 최종본 지정

**Files:**

- Modify: `backend/src/services/page_version_service.py`
- Test: `backend/tests/test_page_version_service.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.page_version_service import create_page_version, mark_final_version, list_page_versions


def test_only_one_final_version_per_project():
    v1 = create_page_version("project-1", "v1", [], "problem_solution")
    v2 = create_page_version("project-1", "v2", [], "spec_focused")

    mark_final_version(v2.id)

    versions = list_page_versions("project-1")
    final_versions = [version for version in versions if version.is_final]

    assert len(final_versions) == 1
    assert final_versions[0].id == v2.id
```

- [ ] **Step 2: 구현**

`mark_final_version(version_id)`는 같은 project의 기존 final flag를 모두 false로 바꾼 뒤 선택한 버전만 true로 만든다.

- [ ] **Step 3: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_version_service.py -q
```

Expected:

```text
passed
```

---

## 5. Task 3: Export 서비스

**Files:**

- Create: `backend/src/services/export_service.py`
- Test: `backend/tests/test_export_service.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from backend.src.services.export_service import build_export_manifest


def test_build_export_manifest_for_long_image_and_section_zip():
    manifest = build_export_manifest(
        project_id="project-1",
        version_id="version-1",
        sections=[
            {"key": "problem_statement", "title": "고객의 고민", "body": "더운 날 외출이 번거롭습니다."},
            {"key": "product_information", "title": "상품 정보", "body": "4,800mAh 배터리입니다."},
        ],
    )

    assert manifest["project_id"] == "project-1"
    assert manifest["version_id"] == "version-1"
    assert manifest["outputs"] == ["long_vertical_image", "section_images_zip"]
    assert len(manifest["sections"]) == 2
```

- [ ] **Step 2: 최소 구현**

```python
def build_export_manifest(project_id: str, version_id: str, sections: list[dict]) -> dict:
    return {
        "project_id": project_id,
        "version_id": version_id,
        "outputs": ["long_vertical_image", "section_images_zip"],
        "sections": [
            {
                "index": index + 1,
                "key": section.get("key"),
                "title": section.get("title"),
                "filename": f"{index + 1:02d}-{section.get('key', 'section')}.png",
            }
            for index, section in enumerate(sections)
        ],
    }
```

- [ ] **Step 3: 테스트 통과 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_export_service.py -q
```

Expected:

```text
passed
```

---

## 6. Task 4: 실제 이미지/ZIP 생성 연결

**Files:**

- Modify: `backend/src/services/export_service.py`
- Modify: export API router

- [ ] **Step 1: 긴 세로 이미지 생성 방식 결정**

현재 프론트 렌더링 결과를 이미지로 저장해야 하므로 다음 중 하나를 선택한다.

1. Playwright로 page-editor preview URL을 열고 전체 페이지 screenshot 저장
2. 서버에서 HTML template을 렌더링하고 이미지 변환

초기 구현은 1번이 적합하다. 현재 사용자가 보는 상세페이지와 export 결과가 가장 잘 맞기 때문이다.

- [ ] **Step 2: 섹션별 이미지 ZIP 생성**

각 섹션 DOM에 `data-section-key`를 부여하고, Playwright가 섹션별 screenshot을 저장한 뒤 ZIP으로 묶는다.

- [ ] **Step 3: export artifact 저장**

저장 필드:

```text
id
project_id
version_id
artifact_type
file_path
created_at
```

- [ ] **Step 4: 실패 처리**

브라우저 렌더링 실패, 파일 저장 실패, 섹션 DOM 누락 시 API는 500 대신 사용자가 이해 가능한 메시지를 반환한다.

---

## 7. Task 5: 프론트 버전/Export UI

**Files:**

- Modify: page-editor UI
- Create or Modify: `frontend/src/.../ExportPanel.tsx`

- [ ] **Step 1: 버전 목록 표시**

다음 정보를 표시한다.

```text
버전명
생성 시간
스타일명
최종본 여부
복원 버튼
최종본 지정 버튼
```

- [ ] **Step 2: Export 패널 표시**

다음 버튼을 제공한다.

```text
긴 세로 이미지 다운로드
섹션별 이미지 ZIP 다운로드
```

- [ ] **Step 3: Export 전 체크리스트 표시**

```text
주의 문구 확인
최종 버전 선택
모바일 미리보기 확인
이미지 누락 확인
```

- [ ] **Step 4: 프론트 빌드 검증**

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

## 8. 완료 기준

- AI 생성/재생성/큰 수정 시 버전 스냅샷을 남길 수 있다.
- 이전 버전을 복원할 수 있다.
- 하나의 프로젝트에는 최종본이 하나만 존재한다.
- 최종본을 긴 세로 이미지로 export할 수 있다.
- 최종본을 섹션별 이미지 ZIP으로 export할 수 있다.
- export 실패 시 원인을 사용자가 이해할 수 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.
- 테스트로그, 코드리뷰, 트러블슈팅 문서가 작성된다.

---

## 9. 검증 명령

```powershell
uv run --project backend pytest backend/tests/test_page_version_service.py backend/tests/test_export_service.py -q
cd frontend
npm.cmd run build
```
