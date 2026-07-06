# 트러블슈팅: Sprint 3 보완 구현

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | AI 분석 API 계약, 워크스페이스 격리, 카테고리 확정 흐름 |
| 상태 | 해결 |

---

## Issue 1. Analyze API 응답 계약 불일치

### 증상

Sprint 3 계획서의 API 계약은 `status="processing"`을 반환해야 하지만 실제 API는 `pending`을 반환했다.

### 원인

`AnalyzeResponse` 생성부와 `JobStatus` 생성부에서 초기 상태를 기존 작업 큐 기본값인 `pending`으로 유지하고 있었다.

### 조치

분석 요청이 접수되어 작업이 진행 상태임을 사용자에게 명확히 보여주기 위해 API 응답과 `JobStatus` 초기값을 `processing`으로 맞췄다.

---

## Issue 2. Analyze API 워크스페이스 권한 격리 누락

### 증상

`POST /api/v1/projects/{project_id}/analyze`가 `project_id`만으로 프로젝트를 조회했다.

### 원인

Sprint 1/2 프로젝트 API에서 쓰던 `workspace_id` 필터가 AI 분석 라우터에 적용되지 않았다.

### 조치

`get_current_user_and_workspace` 의존성을 추가하고, 프로젝트 조회 조건에 `ProductProject.workspace_id == workspace.id`를 포함했다.

---

## Issue 3. 카테고리 최종 확정 흐름 누락

### 증상

AI가 추천한 카테고리를 사용자가 변경·확정할 API/UI가 없었다.

### 원인

Sprint 3 구현이 AI 어댑터와 compliance 엔진 중심으로 끝나면서 사용자 승인 지점이 빠졌다.

### 조치

- `ProductProject`에 `category_confirmed`, `category_confirmed_by`, `category_confirmed_at` 필드를 추가했다.
- `PATCH /api/v1/projects/{project_id}/category` API를 추가했다.
- 사실 확인 보드에 AI 분석 실행, 카테고리 선택, 카테고리 확정 UI를 추가했다.

---

## 남은 메모

이미지 기반 AI 분석은 아직 텍스트 분석과 같은 수준으로 완성하지 않았다. 로컬 업로드 파일을 외부 AI 모델에 전달하려면 공개 URL/서명 URL 또는 base64 변환 정책이 필요하므로 후속 스프린트에서 별도 작업으로 다룬다.
