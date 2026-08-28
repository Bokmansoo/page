# Sellform V2.1 LG-5R — 이미지 생성 내구성 보완 구현 계획

작성일: 2026-08-07  
상태: 구현·테스트·역검증 완료  
상위 기획: [Sellform V2.1 AI Commerce Studio 최종 기획](../specs/2026-08-07-sellform-v2-ai-commerce-studio-v2.1-final-design.md)  
로드맵: [Sellform V2.1 Sprint 로드맵](./2026-08-07-sellform-v2-ai-commerce-studio-v2.1-roadmap.md)  
보완 대상: [LG-5 이미지 생성 서브그래프](./2026-08-07-sellform-v2-lg-5-image-generation-subgraph.md)

## 1. 목표와 완료 판정

LG-5의 기존 이미지 job·검수 자산은 보존하되, 동기 provider 우회와 daemon thread에
의존하지 않는 내구성 있는 이미지 생성 서브그래프로 교체한다. 비용 승인, 작업 생성,
provider 실행, 결과 수집, LangGraph 재개, 장면별 승인까지 하나의 DB 기반 상태 머신으로
연결한다.

다음 조건을 모두 만족할 때만 LG-5R을 완료로 판정한다.

1. `ARC-07`, `IMG-01`~`IMG-10`, `HITL-03`~`HITL-06`, `OPS-03`, `OPS-09`에 미구현·부분 구현이 없다.
2. 비용 승인 전 provider dispatch와 실제 비용 기록은 0건이다.
3. fake provider도 DB outbox·lease worker와 실제 `provider_wait` interrupt,
   `Command(resume=...)`를 통과한다.
4. 서버·worker 재시작, 중복 클릭·poll·completion 신호에도 동일 멱등 키의 작업·비용은 하나다.
5. 장면별 승인 상태를 독립적으로 보존하고 모든 필수 장면이 승인되기 전에는 graph를 완료하지 않는다.
6. 백엔드, 그래프, 프런트, Playwright 대상 테스트와 핵심 회귀가 통과한다.
7. 실제 유료 provider는 별도 명시적 승인 없이는 호출하지 않는다.

## 2. 실제 코드 감사 결과

기존 LG-5 코드리뷰의 `충족` 판정을 재사용하지 않고 다음 코드를 직접 확인했다.

| 영역 | 현재 코드 | 결손 |
| --- | --- | --- |
| job 키 | `storyboard_image_generation_service._job_id` | `project + section + variant`만 사용해 prompt/planning/reference/attempt 변경을 구분하지 못한다. |
| 비용 승인 | `_lg5_generation_pending` | 장면·모델·장면별 비용·총 비용 snapshot 없이 provider 설정 유무만 확인한다. |
| 작업 생성 | `prepare_graph_image_jobs` | 승인 후 기존 `s5-*` 작업을 run metadata로 소유할 뿐 입력 hash를 검증하지 않는다. |
| worker | `dispatch_graph_image_jobs` | real은 daemon `threading.Thread`, mock은 동기 `execute_image_generation`이다. |
| 복구 | 앱 lifespan | queued/running lease 회수, outbox sweep, dead-letter가 없다. |
| graph 재개 | `resume_provider_wait` | worker callback 자체는 같은 thread를 사용하지만 durable completion event와 중복 방지가 없다. |
| 장면 승인 | `apply_image_review`, `_lg5_image_review` | job 미지정 approve가 모든 review job을 승인하고 즉시 전체 graph를 완료한다. |
| 재생성 | `apply_image_review` | job 미지정 시 `needs_review`까지 모두 초기화하며 새 attempt/version을 만들지 않는다. |
| 직접 업로드 | `GraphReviewPanel` | 사용자가 raw asset ID를 입력해야 한다. |
| 오류 계약 | provider/service | 일부 오류 코드는 있으나 API 키, 잔액·한도, timeout, safety, identity, OCR, rights 분류와 행동 안내가 일관되지 않다. |
| 새로고침 복원 | graph GET | interrupt는 복원되지만 cost approval/outbox lease/장면별 검수 projection이 별도 DB 계약으로 고정되지 않았다. |
| 테스트 | `test_lg5_image_generation_subgraph.py` | dispatch 함수를 동기 완료 함수로 monkeypatch해 provider wait·worker·resume을 우회한다. |
| Playwright | `lg5-image-generation-review.spec.ts` | mock route로 버튼 요청만 검사하며 worker 상태 전이·새로고침 복구·부분 승인을 검사하지 않는다. |

## 3. 목표 상태 흐름

```text
planning_review 승인
  → cost plan 계산·DB 저장
  → generation_pending(cost_approval interrupt)
      ├─ defer: provider dispatch 0, 같은 interrupt 유지
      └─ approve: 현재 plan hash 검증·승인 기록
          → scene attempt job을 멱등 생성
          → outbox를 멱등 enqueue
          → provider_wait interrupt
              → worker lease claim
              → fake/real provider 실행
              → 결과·오류·비용 저장
              → outbox completed/dead_letter
              → 같은 run/thread/checkpoint Command(resume=refresh)
          → collect/validate
          → image_review interrupt
              ├─ 장면 approve/reject/upload: review 유지
              ├─ failed scene regenerate: 새 attempt job/outbox → provider_wait
              └─ 모든 필수 scene 승인: finalize_run
```

## 4. DB와 migration 계획

### 4.1 `image_generation_jobs` 확장

- `scene_id`: storyboard scene 식별자. 기존 `section_id`와 호환한다.
- `prompt_version`, `prompt_hash`: 실제 provider 입력 prompt의 버전·hash.
- `reference_hash`: 정렬된 reference asset ID/content hash의 hash.
- `planning_hash`: 승인 planning snapshot hash.
- `input_hash`: provider 입력 canonical snapshot hash.
- `generation_attempt`: 판매자 재생성 attempt. provider 내부 retry와 분리한다.
- `idempotency_key`: `project_id + scene_id + prompt_version + reference_hash + generation_attempt`의 canonical hash, unique.
- `required_for_completion`: 필수 장면 완료 gate.
- `supersedes_job_id`: 재생성 계보.
- 승인·거절 시각과 actor audit 필드.

### 4.2 비용 승인

`image_generation_cost_approvals` 테이블을 만든다.

- run/thread/project, planning hash, cost plan hash, provider, model
- scene별 비용 snapshot, scene count, total, currency/unit
- `pending|approved|deferred|stale` 상태와 승인 시각·actor
- run + cost plan hash unique로 중복 승인 레코드를 방지

### 4.3 durable outbox·lease

`image_generation_outbox` 테이블을 만든다.

- idempotency key와 image job FK, run/thread/project
- provider mode, `queued|leased|retry_wait|completed|dead_letter|cancelled`
- lease owner/expiry, delivery attempt, max attempt, next available time
- provider dispatch count, completion resume count
- 마지막 오류 code/message, 완료 시각
- idempotency key unique로 중복 enqueue·dispatch를 방지

기존 local PostgreSQL을 위한 명시적 SQL migration과 현재 프로젝트의
`ensure_runtime_schema_compatibility` adapter를 함께 제공한다. 새 SQLite 테스트 DB는 ORM
metadata로 동일 schema를 만든다.

## 5. 백엔드·LangGraph·worker 계획

1. storyboard와 reference를 canonical JSON으로 직렬화해 planning/prompt/reference/input hash를 계산한다.
2. `generation_pending` 진입 전에 비용 계획을 계산·저장하고 interrupt context에 고정한다.
3. resume approve가 현재 pending interrupt의 plan hash와 일치할 때만 승인되도록 한다.
4. 승인된 cost plan의 장면에 대해서만 attempt 1 job과 outbox를 생성한다.
5. planning/prompt/reference hash가 달라지면 기존 job을 재사용하지 않고 새 멱등 키를 만든다.
6. worker는 DB에서 원자적으로 lease를 claim하고, lease 소유자만 provider boundary를 호출한다.
7. fake provider도 동일 worker 함수를 사용하며 안전한 로컬 이미지 결과를 만든다.
8. 완료 transaction 후 outbox의 동일 run/thread를 읽어 `resume_provider_wait`를 호출한다.
9. 여러 장면 완료 신호가 겹쳐도 graph resume lease와 outbox completion marker로 한 번만 전진한다.
10. startup recovery sweep은 만료된 lease와 고아 `running/generating` job을 queued로 되돌린다.
11. 반복 실패는 dead-letter로 보내고 운영자 list/retry API를 제공한다.
12. provider 오류를 `API_KEY_MISSING`, `BALANCE_OR_LIMIT`, `PROVIDER_TIMEOUT`,
    `PROVIDER_SAFETY`, `IDENTITY_MISMATCH`, `OCR_CONTAMINATION`, `RIGHTS_BLOCKED`,
    `PROVIDER_ERROR`로 정규화한다.
13. 한 장면 approve는 해당 장면만 승인하며 `all_required_scenes_approved`가 참일 때만 finalize한다.
14. 기본 regenerate는 failed/blocked/rejected scene만 대상으로 새 generation attempt를 만든다.
15. 성공·승인 scene과 이전 attempt audit은 변경하지 않는다.

## 6. API 계획

- graph GET/interrupt context에 비용 계획과 장면별 최신 attempt 상태를 제공한다.
- graph resume payload는 `cost_plan_hash`, `job_id`, `asset_id`를 검증한다.
- project asset API를 사용해 seller-owned 이미지 picker를 구성한다.
- outbox 운영 API:
  - 상태·lease·dead-letter 조회
  - recovery sweep
  - dead-letter 개별 재시도
- worker test/운영 진입점은 한 번의 sweep 또는 제한된 batch를 처리하며 유료 provider는 설정·승인·mode gate를 모두 통과해야 한다.
- stale interrupt, 잘못된 job/asset, 이미 처리된 응답은 409와 한국어 복구 행동을 반환한다.

## 7. 프런트엔드 계획

1. 비용 승인 패널에 장면 수, provider/model, 장면별 비용, 총 예상 비용과 단위를 표시한다.
2. 비용 승인/defer 후 성공·진행·실패·다음 interrupt 메시지를 분리한다.
3. provider wait에서 장면별 queued/running/retry/dead-letter와 새로고침 복원 상태를 표시한다.
4. 이미지 검수는 장면 카드마다 승인·거절·실패만 재생성·직접 업로드를 제공한다.
5. 직접 업로드는 프로젝트 seller-owned 이미지의 thumbnail/filename picker로 선택한다.
6. 필수 장면 잔여 수를 표시하고 부분 승인 뒤에도 image_review를 유지한다.
7. 409 stale response는 상태를 다시 불러오고 사용자가 다음 행동을 이해하도록 안내한다.
8. 새로고침 후 같은 runId에서 cost/provider/review 상태와 선택 가능한 asset 목록을 복원한다.

## 8. 요구사항 → 구현 → 테스트 추적표

| ID | 구현 작업 | 필수 테스트 |
| --- | --- | --- |
| ARC-07 | versioned cost plan과 cost approval interrupt, 승인 전 dispatch gate | 비용 승인 전 outbox/dispatch/cost 0 통합·E2E |
| IMG-01 | scene/model/per-scene/total cost snapshot·UI | cost plan API/graph state/Playwright 표시 |
| IMG-02 | prompt/reference/planning/attempt 포함 멱등 키 | hash 변경·attempt 증가 단위/DB unique |
| IMG-03 | job/outbox unique, lease claim, completion marker | 중복 클릭·poll·completion에서 dispatch/cost 1 |
| IMG-04 | DB outbox와 lease worker | fake provider worker 통합, daemon/sync 우회 금지 |
| IMG-05 | startup recovery sweep | expired lease·running job 복구 테스트 |
| IMG-06 | 장면별 review와 전체 완료 gate | 한 장면 승인 후 image_review 유지, 전부 승인 후 완료 |
| IMG-07 | 실패 장면만 새 attempt | 성공·승인 보존 및 실패 장면 job만 증가 |
| IMG-08 | 오류 taxonomy와 action message | 7개 오류 분류 unit/integration/UI |
| IMG-09 | seller-owned asset picker | raw ID input 부재, picker upload 요청 Playwright |
| IMG-10 | approved asset manifest 분리 | unapproved/blocked/reference asset final 차단 |
| HITL-03 | API key/balance 등 recoverable pending/error | 상태·오류 보존과 재개 테스트 |
| HITL-04 | defer는 DB pending만 유지 | provider dispatch/cost 0 테스트 |
| HITL-05 | UI 성공·진행·실패·다음 interrupt | 실제 네트워크·상태 전이 Playwright |
| HITL-06 | stage/schema/hash 불일치 409 | stale resume API와 UI reload 테스트 |
| OPS-03 | job/outbox/cost unique와 원자적 claim | 중복 webhook/poll/worker 테스트 |
| OPS-09 | lease, recovery, dead-letter, retry API | worker crash/restart·dead-letter 운영 API 테스트 |

## 9. 테스트 계획

### 9.1 단위·DB

- canonical hash와 멱등 키 결정성
- planning/prompt/reference/attempt별 키 변화
- cost plan 계산과 stale 판정
- 오류 taxonomy
- unique constraint와 lease claim

### 9.2 통합·그래프

- 실제 LangGraph `interrupt` → API resume → `Command(resume=...)`
- cost approve → job/outbox queued → `provider_wait`
- 별도 worker session의 fake provider 완료 → 같은 checkpoint 자동 resume → `image_review`
- 장면별 approve/reject/upload/regenerate와 전체 완료 gate
- expired lease recovery, dead-letter retry, duplicate completion
- 새로고침에 해당하는 GET에서 비용/대기/검수 projection 복원

테스트는 `dispatch_graph_image_jobs`나 worker를 동기 완료 함수로 monkeypatch하지 않는다.
provider boundary만 deterministic fake adapter로 바꿀 수 있다.

### 9.3 프런트·Playwright

- 타입 검사와 대상 ESLint
- 실서버 fake-provider E2E 또는 HTTP 상태 저장 fixture를 사용하되, 핵심 worker E2E는 백엔드 실제 DB·graph 경로를 이미 통과해야 한다.
- 비용 상세 표시 → 승인 → provider wait → worker 완료 → image review
- 한 장면 승인 후 잔여 장면 유지 → 새로고침 → 나머지 승인 → 완료
- 실패 장면만 재생성
- asset picker 선택·요청, raw ID 필드 부재
- 중복 클릭과 409 stale recovery

### 9.4 회귀

- LG-4 interrupt·resume
- LG-1 durable graph runtime
- storyboard image service와 page asset policy
- 프런트 planning 핵심 E2E

## 10. 구현 순서

1. schema/model/runtime compatibility와 SQL migration
2. hash·cost plan·idempotent preparation service
3. outbox·lease worker·recovery·dead-letter와 운영 API
4. LangGraph cost/provider/review 상태와 resume gate
5. provider 오류 정규화와 asset 승인 manifest
6. 프런트 비용·대기·장면별 검수·asset picker
7. 단위→통합→그래프→프런트→Playwright 테스트
8. 코드리뷰 작성 후 요구사항별 실제 코드 역검증
9. 누락·부분·우회 제거 후 사용자 검증 가이드 작성

## 11. 계획 자체 누락 검토

- [x] 대상 요구사항 17개를 모두 구현·테스트에 매핑했다.
- [x] DB migration, backend, frontend, LangGraph, worker를 포함했다.
- [x] 비용 승인 전 dispatch 0과 실제 비용 기록 0을 포함했다.
- [x] planning/prompt/reference/attempt 변경 시 잘못된 재사용 방지를 포함했다.
- [x] daemon thread와 mock 동기 완료 우회를 제거하는 실제 worker 경로를 포함했다.
- [x] 서버 재시작·lease·dead-letter·운영자 재시도를 포함했다.
- [x] 같은 thread/checkpoint의 실제 `Command(resume=...)` 검증을 포함했다.
- [x] 장면별 승인·거절·재생성·직접 업로드와 전체 완료 gate를 포함했다.
- [x] 실패 장면만 재시도하고 성공·승인 장면을 보존한다.
- [x] raw asset ID 대신 화면 asset picker를 포함했다.
- [x] 요구된 오류 분류와 한국어 복구 행동을 포함했다.
- [x] 새로고침·중복 클릭·중복 completion 복구 테스트를 포함했다.
- [x] 실제 유료 API 무호출과 fake provider 전체 E2E를 포함했다.
