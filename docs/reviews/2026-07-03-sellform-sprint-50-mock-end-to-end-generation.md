# 코드 리뷰: Sellform Sprint 50 Mock End-To-End Generation

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-07-03 |
| 리뷰 범위 | mock_outputs, AgentGraph, AgentRunService, /run-mock API, GenerationProgressShell, Playwright E2E Spec |
| 관련 기획·작업 | [2026-07-03-sellform-sprint-50-mock-end-to-end-generation.md](file:///c:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-50-mock-end-to-end-generation.md) |
| 리뷰어 | Antigravity AI |
| 상태 | 승인 |

## 1. 변경 요약

- 외부 LLM/Image API 호출 없이 모의 생성을 보장하기 위해 한국어 문구 및 플레이스홀더 이미지 ID(`mock-hero-visual`) 등이 적용된 8개 생성 단계의 **Mock Output Fixtures**를 구현했습니다.
- `AgentGraph`에 **`run_all(state)`** 연산 루프를 신설하여 오프라인에서 `INTAKE` 단계부터 `REVIEW_EDITOR` 단계까지 상태 전이를 모사하도록 개발했습니다.
- DB 레코드를 복원하여 그래프 연산을 수행한 후 생성 상태와 완료 내역을 DB에 영속화하는 **`AgentRunService.run_mock`** 비즈니스 로직과 이를 중개하는 **`POST /api/agent-runs/{id}/run-mock`** API 엔드포인트를 탑재했습니다.
- 프론트엔드의 **`<GenerationProgressShell />`** 로딩 컴포넌트 마운트 시점과 백엔드 `run-mock` API를 통신 연동하였으며, 연산 완료 시점에 우측 하단에 **`생성된 상세페이지 보기`** CTA 버튼을 렌더링하고 클릭 시 해당 상세페이지의 에디터 경로(`/workspace/projects/{projectId}/page-editor`)로 전환되도록 보완했습니다.
- 전체 모의 생성 파이프라인의 오프라인 연산 흐름을 최종 검증하기 위한 **Playwright E2E 스펙**을 구축했습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- **기획 문서**: [2026-07-03-sellform-sprint-50-mock-end-to-end-generation.md](file:///c:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-50-mock-end-to-end-generation.md)
- **추가/수정 코드**:
  - [mock_outputs.py](file:///C:/page/backend/src/agents/mock_outputs.py)
  - [graph.py](file:///C:/page/backend/src/agents/graph.py)
  - [agent_run_service.py](file:///C:/page/backend/src/services/agent_run_service.py)
  - [agent_runs.py](file:///C:/page/backend/src/api/agent_runs.py)
  - [GenerationProgressShell.tsx](file:///C:/page/frontend/src/components/GenerationProgressShell.tsx)
- **테스트 및 검증 증적**:
  - [test_mock_agent_generation.py](file:///C:/page/backend/tests/test_mock_agent_generation.py)
  - [test_agent_run_api.py](file:///C:/page/backend/tests/test_agent_run_api.py)
  - [mock-generation.spec.ts](file:///C:/page/frontend/e2e/mock-generation.spec.ts)

### 핵심 흐름

```text
  [Intake 완료 및 runId 수신]
             ↓
[GenerationProgressShell 마운트] ── (API 요청) ──> [POST /api/agent-runs/{runId}/run-mock]
             ↓ (8단계 모의 진행 안내)                       ↓ (DB 복구 및 AgentGraph.run_all)
    [진행 단계 순차 활성화]                                 ↓ (mock output 생성 및 DB 반영)
             ↓ (애니메이션 완료)                            ↓ (200 OK 응답 및 projectId 수신)
 [생성된 상세페이지 보기 CTA 노출] <───────────────────────────┘
             ↓ (클릭)
[이동: /workspace/projects/{projectId}/page-editor]
```

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### ⚪ N1. 다중 프로젝트 import 경로 지정에 따른 SQLAlchemy 중복 등록 경고
- **위치**: 백엔드 서비스 및 API 라우터 모듈 전반
- **내용**: `PYTHONPATH="c:\page"` 환경 하에서 모듈을 `backend.src` prefix와 `src` prefix로 혼용하여 임포트하면 SQLAlchemy가 동일 클래스를 이중 정의한 것으로 인지하여 `InvalidRequestError`를 발생시킵니다.
- **영향**: 로컬 유닛 테스트 또는 API 라우팅 검증 중 404/500 에러 및 서버 기동 중단으로 이어질 수 있습니다.
- **제안**: 프로젝트 소스 내의 모든 내부 임포트 구문을 기존 관례와 부합하는 `src.` prefix 형태로 단일화하여 통일되도록 조치해야 합니다.
> **[조치 상태 - 2026-07-03]** 신규 작성된 `agent_run_service.py` 및 `graph.py` 등의 임포트 경로를 모두 `src.` 형식으로 즉시 수정하여 해결 완료 상태입니다.

## 4. 우선순위 권고

1. **⚪ N1 (수입 경로 단일화 준수)** — 프로젝트 표준 import 규칙을 준수하도록 개발 가이드라인을 유지합니다.

## 5. 긍정적인 부분

- **오프라인 검증 최적화**: API 키 장벽이나 유료 크레딧 소모 없이, 1인 셀러의 생성 폼 진입부터 상세페이지 에디터 완성판까지의 흐름을 초고속으로 검증할 수 있게 되어 프론트 및 백엔드 개발 생산성이 극대화되었습니다.
- **유기적인 UI 컴포넌트 연동**: API 응답이 백그라운드에서 실행되는 동안 8개 로딩 단계가 자연스럽게 전환되도록 애니메이션을 부여했고, 포크된 UUID(`projectId`)를 인지해 즉각 에디터로 리다이렉트하는 유려한 UX 흐름이 돋보입니다.

## 6. AI·사실 신뢰성 검토

- 모의 생성된 8단계 fixtures에 기획에서 약속된 규정 및 금지 사항(예: "최고의 자전거", "절대 안전" 등 과장/허위 광고 차단 필터)에 대한 모의 QA 체크 결과(`qa_report`)를 내포시킴으로써 규제 필터의 프로토타이핑을 현실적으로 검증해 줍니다.

## 7. 검증 증적

### 백엔드 테스트 통과 증적
```text
backend/tests/test_mock_agent_generation.py::test_mock_product_understanding_uses_input_name PASSED
backend/tests/test_mock_agent_generation.py::test_mock_page_assembly_has_copy_and_visual_slots PASSED
backend/tests/test_mock_agent_generation.py::test_mock_graph_runs_to_review_editor PASSED
backend/tests/test_agent_run_api.py::test_create_agent_run_from_product_name PASSED
backend/tests/test_agent_run_api.py::test_run_mock_generation_returns_page_assembly PASSED

======================= 5 passed, 20 warnings in 0.82s ========================
```

### Playwright E2E 통합 테스트 통과 증적
```text
Running 1 test using 1 worker

  ok 1 [chromium] › e2e\mock-generation.spec.ts:3:5 › mock mode creates a complete detail page draft (5.2s)

  1 passed (12.9s)
```
