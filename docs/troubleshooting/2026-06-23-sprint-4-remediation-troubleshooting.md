# 트러블슈팅: Sellform Sprint 4 Remediation

## 1. regenerate API 런타임 오류

- 증상: `POST /projects/{project_id}/page/sections/{section_id}/regenerate` 직접 호출 시 `NameError: name 'settings' is not defined` 발생.
- 원인: `backend/src/api/pages.py`에서 `settings`, `anthropic`, `logger`를 사용하지만 import가 누락되어 있었다.
- 조치: 필요한 import를 추가하고 회귀 테스트를 작성했다.
- 검증: `test_regenerate_page_section_applies_user_instruction` 통과.

## 2. workspace 격리 누락

- 증상: 다른 workspace 헤더로 기존 프로젝트의 page API를 호출해도 `200 OK`가 반환되었다.
- 원인: page API가 `ProductProject.workspace_id`를 확인하지 않고 `project_id`만으로 페이지를 조회했다.
- 조치: page API 전체에 `get_current_user_and_workspace` 의존성을 적용하고, project 조회 시 workspace 조건을 함께 검사했다.
- 검증: `test_page_api_rejects_project_from_other_workspace` 통과.

## 3. 프론트 롤백 UI가 mock version에 의존

- 증상: page editor의 버전 목록이 실제 DB의 `PageVersion`이 아니라 `v-1`, `v-2` mock 데이터였다.
- 원인: 버전 목록 조회 API가 없었다.
- 조치: `GET /projects/{project_id}/page/versions` API를 추가하고 프론트에서 실제 API를 호출하도록 변경했다.
- 검증: `test_list_page_versions_returns_real_saved_versions` 통과.

## 4. 섹션 추가 기능 누락

- 증상: Sprint 4 기획서에는 좌측 패널에서 섹션 신규 추가가 필요했지만 API/UI가 없었다.
- 원인: 기존 구현은 섹션 숨김, 순서 변경, 텍스트 편집 중심이었다.
- 조치: `POST /projects/{project_id}/page/sections` API와 프론트 `+ 새 섹션 추가` 버튼을 추가했다.
- 검증: `test_add_page_section_inserts_section_with_next_sort_order` 통과.

## 5. Windows/인코딩 관련 문서 갱신 이슈

- 증상: 기존 Sprint 4 문서 일부가 PowerShell에서 mojibake로 표시되어 상단 삽입 패치 기준점이 안정적으로 잡히지 않았다.
- 조치: 원본 문서를 보존하고 별도 보완 리뷰/테스트/트러블슈팅 문서를 추가했다.
