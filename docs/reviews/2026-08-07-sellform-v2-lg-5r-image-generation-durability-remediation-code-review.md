# Sellform V2.1 LG-5R 코드리뷰 — 이미지 생성 내구성 보완

작성일: 2026-08-07  
판정: **LG-5R 범위 충족**  
검증 원칙: 기존 LG-5 리뷰의 판정을 재사용하지 않고 모델, migration, API, worker,
LangGraph checkpoint/interrupt/resume, 프런트와 테스트를 실제 코드에서 역검증했다.

## 1. 최종 판정

- 미구현: 0건
- 부분 구현: 0건
- 테스트 우회: 0건
- LG-5R 대상 실패 테스트: 0건
- 유료 이미지 API 호출: 0건
- 발견 후 같은 작업에서 수정한 결함: 7건
  1. 여러 interrupt를 한 node의 반복문에서 처리해 이전 resume 값이 다음 장면에 재사용되던 문제
  2. 장면 단독 재생성 cost plan이 checkpoint의 이전 전체 cost plan으로 표시되던 문제
  3. 승인 전 생성 후보가 final-output eligible 자산으로 노출되던 문제
  4. 업로드 사진의 제품 정체성 역할을 판매자가 지정할 UI가 없어 모든 사진이
     `unknown`으로 남던 문제
  5. `product_component`와 `product_in_use` 수동 역할이 자동 검사 단계에서 다시
     덮이던 문제
  6. API의 구조화된 422 오류가 planning 화면에서 `[object Object]`로 표시되던 문제
  7. 생성 결과 자산은 저장됐지만 image review 카드에 미리보기가 없어 보지 않고도
     승인할 수 있던 문제

## 2. 요구사항별 코드와 테스트 증거

| ID | 실제 구현 | 테스트 증거 | 판정 |
| --- | --- | --- | --- |
| ARC-07 | `langgraph_image_generation_service.py:186,259`, `langgraph_runtime.py:449`의 versioned cost plan·승인 interrupt | `test_lg5_image_generation_subgraph.py:155`, Playwright 비용 패널 | 충족 |
| IMG-01 | 장면 수/provider/model/장면별·총 비용 snapshot, `GraphReviewPanel.tsx:257` | Playwright `:55` | 충족 |
| IMG-02 | `_idempotency_key`가 project/scene/prompt version/reference/attempt를 canonical hash화, DB unique migration | 테스트 `:377` | 충족 |
| IMG-03 | job/outbox unique, 조건부 lease claim, completion marker | 테스트 `:155`, 중복 worker batch·중복 UI 클릭 | 충족 |
| IMG-04 | `image_generation_worker.py:137,175,259,291`; DB outbox/lease와 실제 fake provider worker | 테스트 `:155,257`; dispatch/worker 동기 완료 monkeypatch 없음 | 충족 |
| IMG-05 | 앱 lifespan recovery와 `recover_expired_image_work:96` | 테스트 `:415` | 충족 |
| IMG-06 | `apply_image_review:462`, graph 장면별 self-interrupt, 모든 필수 장면 승인 gate | 테스트 `:155` | 충족 |
| IMG-07 | rejected/failed 장면만 새 attempt와 새 cost approval, sibling 보존 | 테스트 `:257` | 충족 |
| IMG-08 | worker error taxonomy 7종, UI action label `GraphReviewPanel.tsx:243` | 단위 `:520`, Playwright `:112` | 충족 |
| IMG-09 | seller-owned image asset picker `GraphReviewPanel.tsx:273`; planning 입력 사진 역할 picker; raw ID 입력 없음 | backend `test_manual_classification_api_accepts_lg5r_identity_roles`, Playwright `:55` | 충족 |
| IMG-10 | 생성 후보는 `blocked`, 장면 승인 시에만 `ai_generated`로 승격; reference/mock final 차단 | 테스트 `:155`의 승인 전·후 eligibility | 충족 |
| HITL-03 | API key는 generation_pending 유지, 나머지 오류는 장면별 recoverable review/dead-letter | LG-4/5R 17-test suite, 오류 taxonomy | 충족 |
| HITL-04 | defer는 cost record만 보존하고 job/outbox/dispatch 0 | LG-4 defer와 LG-5R 승인 전 assertion | 충족 |
| HITL-05 | 비용 승인, provider 진행, 오류, 장면별 다음 interrupt UI | Playwright 2개 시나리오 | 충족 |
| HITL-06 | stage/schema/thread/cost hash 사전 검증과 409, GET reload | LG-4 wrong-thread/version, LG-5R stale hash, Playwright reload | 충족 |
| OPS-03 | cost/job/outbox unique, conditional lease, real timeout 자동 재전송 금지 | 중복 worker/poll/click 및 dispatch count 1 | 충족 |
| OPS-09 | outbox 조회, recovery sweep, dead-letter retry API와 unknown-paid-work 차단 | 테스트 `:415` | 충족 |

## 3. 계층별 검토

### DB와 migration

- `backend/src/db/models.py:779,834,865`에 job 입력 hash·attempt, 비용 승인, outbox/lease 모델이 있다.
- `backend/migrations/20260807_lg5r_image_generation_durability.sql`에 기존 DB 확장,
  unique/index와 두 테이블 생성이 있다.
- `ensure_runtime_schema_compatibility`는 기존 `image_generation_jobs` 컬럼·index를 보완하고,
  앱 시작의 `create_all`은 신규 outbox/cost 테이블을 생성한다.

### LangGraph와 worker

- cost, provider wait, image review는 node invocation당 interrupt 1개만 처리하고 conditional
  self-edge로 다음 응답을 받는다.
- API resume은 실제 `Command(resume=...)`를 사용한다.
- worker는 결과 commit 후 같은 run/thread의 `resume_provider_wait`만 호출한다.
- 새로고침 view는 interrupt payload의 최신 generation snapshot을 checkpoint state 위에
  안전하게 overlay하므로 장면 단독 재생성 비용을 이전 전체 비용과 혼동하지 않는다.
- 유료 provider 결과가 불명확한 lease는 자동 재전송하지 않고 `PROVIDER_OUTCOME_UNKNOWN`
  dead-letter로 보낸다.

### 프런트

- 비용 상세, provider 대기 자동 polling, 장면별 승인·거절·재생성·사진 선택 업로드,
  필수 장면 진행률과 오류별 복구 안내를 표시한다.
- in-flight guard가 중복 클릭을 막고, GET 재조회가 비용 승인·대기·검수 상태를 복구한다.
- planning 상단에서 각 권리 보유 사진을 `대표 제품 전체`, `조작부·측면 상세`,
  `제품 구성품`, `제품 실사용`, `사용 장면`으로 직접 분류할 수 있다. PATCH 응답으로
  화면 상태를 갱신하고 재조회 뒤에도 수동 역할을 복구한다.
- 수동 분류는 `role_source=manual`로 저장되며 자동 inspection이 판매자 결정을
  덮어쓰지 않는다.
- FastAPI의 문자열·배열·객체 오류 응답을 사용자 메시지로 정규화해 저장 실패 원인을
  `[object Object]` 대신 붉은 오류 안내로 표시한다.
- image review의 모든 `output_asset_id`를 인증된 asset endpoint의 실제 이미지와 연결한다.
  mock은 테스트용 PNG, real은 provider 결과를 동일한 검수 카드에서 표시하며 이미지가
  없는 `needs_review` 작업에는 승인 금지 안내를 표시한다.
- 미리보기는 실제 라우터 경로인 `/api/v1/files/assets/{asset_id}`를 사용한다. 마지막
  필수 장면 승인으로 실행이 `completed`가 되면 persisted terminal state를 다시 읽도록
  화면을 갱신해 이전 `needs_review` 카드를 남기지 않는다. 완료 뒤에도 승인된 결과를
  읽기 전용 갤러리로 복구해 새로고침 후 다시 확인할 수 있다.

## 4. 실행한 테스트

1. LG-4 + LG-5R 최종 대상
   - 명령: `uv run --project backend --group dev pytest backend/tests/test_lg4_human_review_interrupts.py backend/tests/test_lg5_image_generation_subgraph.py -q ...`
   - 결과: **17 passed**
2. LG-1~LG-5R + 이미지·스토리보드 핵심 통합 회귀
   - 포함: LG-1/2/3/4/5R, 기존 이미지 생성, Sprint 5 리디자인, planning 승인 API
   - 결과: **76 passed**
   - 실행 전 발견한 LG-2/3의 구세대 graph-builder fixture를 최신
     `build_lg5_compiled_graph` 선택점에 맞춘 뒤 하나의 최종 명령으로 재검증했다.
3. 프런트 대상 ESLint
   - `GraphReviewPanel.tsx`, `lg5-image-generation-review.spec.ts`: **exit 0**
4. Playwright
   - 결과: **2 passed (20.7s)**
   - 검증: 비용 표시, 중복 클릭 1요청, provider wait polling, reload 복구, 생성 결과
     미리보기 URL·표시, 부분 승인, seller-owned picker upload, 입력 사진 역할
     PATCH·reload 복구, 오류 7종
5. 브라우저 수동 검증 중 발견한 역할 분류 회귀
   - 명령: `pytest backend/tests/test_sprint2_asset_classification.py backend/tests/test_lg5_image_generation_subgraph.py`
   - 결과: **28 passed**
   - 검증: LG-5R 수동 identity 역할 4종이 정확히 저장되고 자동 검사 후에도 유지됨

참고: 전체 `next build`는 webpack compile까지 성공했으나 LG-5R과 무관한 기존
`account/page.tsx` headers 타입 오류와 `operations/page.tsx`의 기존 `mockHeaders` export
불일치 때문에 type-check 단계에서 중단됐다. 사용자 지시대로 해당 기존 변경은 수정하지
않았다. LG-5R 변경 파일의 ESLint와 Playwright는 모두 통과했다.

## 5. 역검증 결론

- provider worker를 동기 완료 함수로 교체한 테스트가 없다.
- fake provider도 outbox lease와 실제 provider_wait checkpoint resume을 통과한다.
- 비용 승인 전 job/outbox/provider dispatch는 0이다.
- 한 장면 승인으로 전체가 완료되지 않으며 필수 장면 전부 승인 시에만 finalize한다.
- 실패/거절 장면의 새 attempt만 생성되고 성공 장면과 이전 attempt audit은 남는다.
- 승인 전 AI 후보와 supplier reference는 Page Assembly 입력으로 승격되지 않는다.
- 업로드 사진이 자동 분류되지 않아도 판매자가 화면에서 identity 역할을 지정할 수 있고,
  저장·inspection·새로고침 뒤에도 `unknown`으로 되돌아가지 않는다.
- 유료 API 호출 없이 모든 LG-5R 테스트를 실행했다.
