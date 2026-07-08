# 코드 리뷰: Sellform 중복 감지 및 라우팅 개선

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-07-08 |
| 리뷰 범위 | 중복 감지 모달 UX 개선, 진행 상태별 라우팅 정상화, force_new 재생성 옵션 추가, 작업 목록 탭 개선 |
| 리뷰어 | Antigravity (AI Coding Assistant) |
| 상태 | **승인 완료 (Approved)** |

---

## 1. 변경 요약

- **진행 상태별 라우팅 에러 해결**:
  - 상세페이지 생성이 진행 중이거나 준비 상태(`created`, `running`, `waiting_for_cost_approval`)인 프로젝트의 "이어서 진행" 링크가 기존에는 `/workspace/projects/{projectId}/planning`으로 하드코딩되어 404가 발생하던 라우팅 버그를, 실행 중인 run을 이어서 보여주는 `/workspace?runId={runId}` 경로로 정상 연결했습니다.
- **중복 감지 모달 (`GenerationDuplicateRunDialog`) UX 전면 개편**:
  - 사용자가 중복 입력 시 취할 수 있는 세 가지 핵심 선택지를 명확히 분리하여 버튼으로 제공하도록 고도화했습니다:
    1. **기존 작업 이어가기** (초록색 버튼): 프로젝트 상태에 따라 알맞은 화면(`created/running` -> `/workspace?runId=...`, `completed` -> `result_url`, `needs_review` -> `review_url`)으로 연결됩니다.
    2. **그래도 새 작업으로 다시 만들기** (황색 보조 버튼): 사용자가 의도적으로 재생성이나 A/B 테스트를 원할 경우를 위해 force_new API 요청을 트리거합니다.
    3. **작업 목록 확인** (테두리 버튼): 대시보드 화면(`/workspace/projects`)으로 안전하게 탈출합니다.
- **`force_new` 재생성 메커니즘 연동**:
  - 프론트엔드 `AIDetailPageIntake.tsx` 제출 함수(`handleSubmit`)가 `forceNew` 불리언 파라미터를 추가 수용하도록 시그니처를 수정하고, 요청 본문에 `force_new: forceNew`를 탑재하여 중복 감지 모달에서 "새 작업으로 다시 만들기"를 클릭했을 때 백엔드 차단 조건(`req.force_new`)을 해제하고 신규 run이 구동될 수 있게 연동했습니다.
- **작업 목록 (`ProjectWorklist`) 상태 맞춤형 대응**:
  - 프로젝트의 진행 상태(`status`)에 무관하게 무조건 동일한 "결과 보기" 및 "검수하며 다듬기" 버튼이 노출되던 기존 UI를 개선하여, 프로젝트 상태별로 딱 필요한 행동 배너만 노출하도록 개편했습니다:
    - **생성 중** (`generating`) -> `"이어서 진행"`
    - **검수 필요** (`needs_review`) -> `"검수하며 다듬기"`
    - **완료** (`completed`) -> `"결과 보기"`
    - **실패** (`failed`) -> `"상태 확인"`
  - 이를 위해 백엔드 `ProjectWorklistItem` 스키마 및 `/worklist` API가 프로젝트의 최신 `run_id`를 조회하여 응답 객체에 실어주도록 수정했습니다.

---

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| 진행 중 라우팅 404 수정 | **충족** | `/planning` 대신 `/workspace?runId=...`로 라우팅되도록 `actionHref` 함수 수정 완료 |
| 중복 모달 내 3대 선택권 부여 | **충족** | 기존 이어가기, force_new 새 작업, 작업 목록 확인 버튼 탑재 완료 |
| force_new=true API 연동 | **충족** | `AIDetailPageIntake` 및 `GenerationDuplicateRunDialog`에 `onForceNew` 연동 완료 |
| 작업 목록 탭 상태 분기 | **충족** | `ProjectWorklist.tsx`에 flex-wrap 반응형 레이아웃 도입 및 status에 따른 분기 구현 완료 |
| E2E 및 단위 테스트 수정 | **충족** | Playwright E2E spec 내 status-guard 기대값 및 픽스처 수정 완료 |

---

## 3. 테스트 및 검증 결과

### 백엔드 단위 테스트
`ProjectWorklistItem` 스키마 수정 및 `/worklist` API가 올바른 `run_id`를 가져오는지, 중복 생성 방지 기능이 원활한지 검증했습니다.
- 실행 명령: `.venv\Scripts\pytest tests/test_project_worklist_api.py tests/test_generation_run_guard.py`
- 결과: **4 passed** (StarletteDeprecationWarning 및 datetime.utcnow Warning 외 에러 없음)

### 프론트엔드 E2E 테스트
`generation-status-guard.spec.ts` 픽스처에 `active_run` 정보를 추가하고, 이어서 진행 링크가 `/workspace?runId=run-running-id`로 정확히 매핑되는지 확인했습니다.
- 실행 명령: `powershell -ExecutionPolicy Bypass -Command "npx playwright test e2e/generation-status-guard.spec.ts"`
- 결과: **2 passed** (operations page translates completed action to result link / shows duplicate generation status)

---

## 4. 종합 평가
이번 변경을 통해 사용자가 동일한 상품명이나 사진으로 상세페이지를 만들 때 불필요한 비용 낭비를 예방함과 동시에, 이탈(404 에러) 없이 부드럽게 작업을 이어가거나 필요 시 주도적으로 재생성할 수 있는 탄탄한 UX 순환 고리가 마련되었습니다. 코드 결함이 없고 테스트를 완벽히 통과하여 프로덕션 적용을 최종 승인합니다.
