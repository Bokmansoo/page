# Sellform V2.1 LG-8R Provider Resume Stability Code Review

작성일: 2026-08-09  
판정: **LG-8R 대상 미구현 0건 · 부분 구현 0건 · 테스트 우회 0건**

## 1. 검증 범위

기존 LG-8 코드리뷰의 단발성 Playwright 성공 기록을 완료 근거로 사용하지 않았다. 실제 백엔드, DB, fake provider, durable outbox/lease, LangGraph checkpoint와 `Command(resume=...)` 경로를 사용해 실패를 재현하고 원인을 추적한 뒤 수정했다. 실제 유료 LLM·이미지 API는 호출하지 않았다.

LG-8R 안정성 범위는 LG-8의 Visual Prompt Compiler 계약을 변경하지 않고, 이미지 생성 작업 완료 후 `provider_wait`에서 `image_review`로 넘어가는 durable orchestration을 보완하는 것이다.

## 2. 실패 재현과 원인 증거

수정 전 `frontend/e2e/lg8-real-backend-state.spec.ts`는 30초 동안 `image_review`를 기다린 뒤 `provider_wait` 상태로 실패했다.

실패 실행 `15b709fa-77ad-4599-b62e-fc474ec4e73d`의 DB를 확인한 결과:

- 이미지 작업 8건과 outbox 8건은 모두 완료됐다.
- provider dispatch는 각 outbox마다 1회였다.
- 그러나 각 장면 완료가 동일 LangGraph thread를 별도로 재개해 `completion_resume_count`가 8건 모두 1이었다.
- 8회의 직렬 `provider_wait` 재개·checkpoint 저장이 누적되어 최종 `image_review` 전환이 브라우저 제한 시간을 넘겼다.
- 즉 원인은 provider 처리 지연이나 Playwright timeout이 아니라 **장면별 중복 graph resume 경쟁 조건**이었다.

## 3. 수정 내용

| 요구사항 | 판정 | 실제 구현 | 테스트 증거 |
| --- | --- | --- | --- |
| IMG-03 · OPS-03 중복 dispatch/비용 방지 | 충족 | 기존 outbox provider idempotency를 유지하고, 완료 wave에 resume 감사 마커를 정확히 1건만 기록한다. | 모든 outbox `provider_dispatch_count == 1`, resume count 합계 1 |
| IMG-04 · OPS-09 durable outbox/lease | 충족 | DB outbox lease를 사용하며 graph 내부에서 provider 작업을 동기 완료하지 않는다. | 실제 `run_image_worker_batch`와 fake provider 테스트 |
| IMG-05 · OPS-09 서버 재시작 복구 | 충족 | worker batch 시작·종료 시 terminal generation wave를 재조정하며, 빈 queue에서도 마지막 커밋/콜백 사이 crash window를 복구한다. | final commit 후 callback 실패를 모사하고 새 worker session에서 복구 |
| HITL-01 · OPS-04 동일 thread/checkpoint 재개 | 충족 | 기존 conditional `AgentRun.awaiting_review -> running` lease와 실제 `Command(resume=...)` 실행을 사용한다. | 같은 thread가 `provider_wait -> image_review` 전환 |
| HITL-02 새로고침 복구 | 충족 | 상태는 DB와 checkpoint에 남고 새로고침 후 `image_review`를 복원한다. | 실제 백엔드 Playwright의 `page.reload()` 검증 |
| 성공·승인 결과 보존 | 충족 | 최신 장면 attempt를 읽어 readiness만 계산하고 작업이나 asset을 다시 만들지 않는다. | restart/중복 poll 전후 job/outbox 수와 idempotency key 불변 |
| 실패·blocked terminal 처리 | 충족 | queued/running만 대기를 막고 failed/blocked는 검수 단계로 전달한다. | `pending_count == 0` 기반 terminal-wave 테스트 |

## 4. 핵심 코드 근거

- terminal wave 판정: `backend/src/services/image_generation_worker.py:183`
- completion wave 단일 감사 마커: `backend/src/services/image_generation_worker.py:203`
- readiness 기반 graph resume: `backend/src/services/image_generation_worker.py:244`
- crash/restart reconciliation: `backend/src/services/image_generation_worker.py:268`
- worker 완료·dead-letter 이후 조건부 재개: `backend/src/services/image_generation_worker.py:285`
- 빈 queue를 포함한 batch 전후 recovery sweep: `backend/src/services/image_generation_worker.py:367`
- `AgentRun` conditional resume lease: `backend/src/services/langgraph_run_service.py:654`
- 실제 `Command(resume=...)` 실행: `backend/src/services/langgraph_run_service.py:481`

## 5. 자동 테스트 결과

### LG-8 및 LG-5R~LG-7R 회귀

```text
pytest tests/test_lg5_image_generation_subgraph.py
       tests/test_lg6_prompt_intelligence_brand_kit.py
       tests/test_lg7_creative_brief_input_modes.py
       tests/test_lg8_visual_prompt_compiler.py
결과: 51 passed
```

LG-8 테스트에는 다음 실제 경로가 포함된다.

- 8개 fake-provider 작업 완료 후 graph resume 1회
- 동일 thread의 `provider_wait -> image_review`
- duplicate reconciliation/poll의 no-op
- 마지막 job commit 뒤 resume callback process loss와 새 worker 복구
- job/outbox/idempotency key/비용 보존

### 실제 백엔드 Playwright

```text
npx playwright test e2e/lg8-real-backend-state.spec.ts --reporter=line
결과: 1 passed

npx playwright test e2e/lg8-real-backend-state.spec.ts \
  --reporter=line --repeat-each=3 --workers=1
결과: 3 passed
```

이 테스트는 `page.route`로 백엔드를 모킹하지 않는다. 실제 개발 로그인, DB, asset 업로드, LangGraph interrupt/resume, fake provider worker, outbox 조회, 새로고침 복구를 사용한다.

동시에 3개 실행을 한 부하 관찰에서는 단일 in-process fake worker에 24개 이미지가 몰려 2개 브라우저가 기존 30초 제한을 넘겼다. 이는 이번에 수정한 동일 thread 중복 resume 결함과 다른 worker 처리량 문제이며, 이 관찰을 성공으로 숨기거나 timeout을 늘리지 않았다. LG-8R의 반복 안정성 acceptance는 동일 실사용 흐름의 순차 3회 성공으로 판정했다.

### 프런트 정적 검사

관련 파일 ESLint 결과: 오류 0건, 경고 0건.

저장소 전체 `tsc --noEmit`은 LG-8R과 무관한 기존 파일에서 실패한다:

- `e2e/lg5-image-generation-review.spec.ts`
- `e2e/upload-ready-golden-path.spec.ts`
- `e2e/ux2c-uploaded-photo-composition.spec.ts`
- `src/app/account/page.tsx`
- `src/app/workspace/operations/page.tsx`

현재 작업과 무관한 사용자 변경을 보존하기 위해 이 파일들은 수정하지 않았다. LG-8R 관련 변경 파일에는 해당 TypeScript 오류가 없다.

## 6. 테스트 우회 감사

- Playwright timeout 증가: 없음
- blind poll 추가: 없음
- provider worker 동기 함수 전환: 없음
- `page.route` 전체 backend mocking: 없음
- 유료 provider 호출: 없음
- 성공 작업 재생성: 없음
- 중복 비용 또는 중복 outbox 생성: 없음

## 7. 최종 역검증

코드리뷰 문서의 판정을 다시 근거로 삼지 않고 final design의 IMG-03~05, HITL-01~02, OPS-03~05, OPS-09를 실제 코드와 테스트에 역매핑했다. LG-8R 대상에는 미구현·부분 구현·테스트 우회가 남아 있지 않다. 다만 동시 다중 실행 처리량은 별도의 운영 용량 과제로 기록하며 LG-8R의 정확성 수정으로 과장하지 않는다.

