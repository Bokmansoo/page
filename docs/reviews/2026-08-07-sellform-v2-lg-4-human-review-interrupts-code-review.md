# LG-4 코드리뷰 — Human-in-the-loop 승인·재개

검토일: 2026-08-07  
결론: **LG-4 승인·복구 범위 완료. 실제 이미지 생성 재개와 외부 작업 멱등성은 LG-5 검증 필요**

## 기획 항목별 확인

| 기획 항목 | 구현 증거 | 검증 |
| --- | --- | --- |
| 네 개 interrupt node | `backend/src/agents/langgraph_runtime.py`의 `input_review`, `evidence_review`, `planning_review`, `generation_pending` | LG-4 테스트의 단계별 pause 확인 |
| versioned payload | `backend/src/services/langgraph_review_service.py`의 `GraphReviewResumePayload` (`lg4-v1`) | 잘못된/누락 resume body 거부 테스트 |
| start·조회·resume·cancel API | `backend/src/api/graph_runs.py` | 기존 LG-1 API 회귀 + LG-4 API 테스트 |
| 동일 thread 강제 | resume envelope의 `thread_id`와 `AgentRun.id` 비교 | 다른 thread 409 테스트 |
| 승인 화면 연결 | `GraphReviewPanel`, `PlanningDraftEditor`, `AIDetailPageIntake` | planning review 버튼이 graph resume body 전송 |
| 로딩·성공·다음 대기·실패 표시 | `GraphReviewPanel` 및 `PlanningDraftEditor`의 busy/message state | 코드 경로 검토 |
| 새로고침·실패 복구 | `outputs_json.langgraph_review.pending` + `values.execution.last_error` + project review GET | 대기/실패 run 복원 테스트 |
| API 미준비 안전 중단 | `generation_pending`은 `defer` 후 재-interrupt, provider dispatch 없음 | ImageGenerationJobRecord 0건 테스트 |
| 중복 클릭/재개 멱등성 | conditional status lease + in-flight UI guard + 기존 stage step upsert | 반복 resume 단일 step + Playwright 이중 클릭 테스트 |
| 안전 자산 승인 전 점검 | `evidence_review` 승인 시 provider-safe seller asset preflight | 차단 후 같은 interrupt 유지·자산 보완 후 동일 run 재개 테스트 |
| 실패 UX | 실패 원인 코드·사용자 메시지·복구 행동을 graph state에 투영하고 동일 run 재시도 제공 | Playwright 실패 표시·본문 없는 retry 요청 테스트 |

## 실행 결과

다음 백엔드 회귀 범위를 실행했다.

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests\test_lg4_human_review_interrupts.py tests\test_lg3_commerce_planning_subgraph.py tests\test_lg2_discovery_subgraph.py tests\test_lg1_durable_graph_runtime.py tests\test_lg0_langgraph_runtime.py tests\test_11_agent_graph_contract.py tests\test_11_agent_node_contracts.py tests\test_agent_graph_contract.py tests\test_agent_run_api.py tests\test_source_collection_agent.py tests\test_reference_analysis_agent.py tests\test_v2_sprint3_evidence_board.py tests\test_ux2e0_api_ready_generation.py tests\test_planning_draft_service.py tests\test_planning_draft_approve_api.py -q
```

결과: **68 passed, 936 warnings**.

현장 수동 검증에서 안전한 기준 자산이 없는 상태로 `evidence_review`를 승인하면
비주얼 기획에서 실패하고 화면은 이전 interrupt를 유지하는 문제가 발견됐다. 보완 후
다음 추가 검증을 실행했다.

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests\test_lg4_human_review_interrupts.py tests\test_lg3_commerce_planning_subgraph.py tests\test_lg2_discovery_subgraph.py tests\test_lg1_durable_graph_runtime.py tests\test_lg0_langgraph_runtime.py -q

cd C:\page\frontend
.\node_modules\.bin\playwright.cmd test e2e/lg4-graph-review-recovery.spec.ts --project=chromium --reporter=line
```

추가 결과: **백엔드 28 passed**, **LG-4 Playwright 2 passed**, 변경 프런트 ESLint 오류 0건.

이번 보완으로 다음 결함을 회귀 테스트로 고정했다.

- 안전 자산이 없으면 downstream 기획을 실행하지 않고 `evidence_review`에서 이유와 함께 다시 대기한다.
- 차단 원인을 해결하면 두 번째 resume 값이 실제 `Command(resume=...)`에 전달된다.
- 실행 실패 시 이전 승인 카드가 남지 않고 구조화된 실패·복구 카드가 표시된다.
- 승인 버튼을 빠르게 두 번 눌러도 브라우저가 resume 요청을 한 번만 보낸다.
- 실패 run 재시도는 새 run을 만들지 않고 동일 run의 body 없는 resume을 호출한다.
- 상단 graph state와 스토리보드 편집기가 동일한 `review_stage`를 사용한다. `generation_pending`에서는 승인 완료·이미지 생성 대기를 표시하고 중복 승인 버튼을 노출하지 않는다.
- 실패 카드가 표시될 때 하단의 모순된 “판매자 승인을 기다리고 있습니다” 안내를 숨긴다.

프런트 production build는 Google Fonts 네트워크 차단으로 별도 실패했다. 또한 저장소 전체 `tsc --noEmit`에는 기존 e2e/account/operations 타입 오류가 있어, 전체 TypeScript type check를 LG-4 통과 증거로 사용하지 않았다. 이 두 환경/기존 오류는 LG-4 백엔드 회귀 결과와 분리해 기록한다.

## 의도적으로 다음 Sprint에 남긴 범위

LG-4는 이미지 제공자를 호출하지 않는다. `generation_pending` 이후의 prepare/dispatch/wait/collect/validate, 비용·잔액·timeout 구분, 장면별 image review는 LG-5 소유다. 이는 API 비용이 없을 때 가짜 생성 이미지를 만들거나 완료 처리하지 않기 위한 경계다.

따라서 로드맵의 “승인 버튼 두 번 클릭 시 외부 작업·버전 하나”와 “API 준비 후 실제 이미지 생성으로 같은 run 재개”의 최종 증명은 LG-5 provider/job 구현 후 수행해야 한다. LG-4에서는 provider 호출 0건, UI 중복 resume 차단, 동일 thread 보존까지 검증한다.
