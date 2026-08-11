# Sellform V2 실제 LangGraph 멀티에이전트 시스템 최종 기획

> **기준 변경 안내 (2026-08-07):** 이 문서는 LG-0~LG-5의 아키텍처 이력으로 보존합니다. 현재 제품·구현 기준은 [Sellform V2.1 AI Commerce Studio 최종 기획](./2026-08-07-sellform-v2-ai-commerce-studio-v2.1-final-design.md)입니다.

작성일: 2026-08-06  
상태: **최종 아키텍처 기준**  
구현 로드맵: [LangGraph 전환 Sprint 로드맵](../plans/2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 1. 문서의 역할

이 문서는 Sellform의 AI 상세페이지 생성 실행 구조를 실제 LangGraph 기반으로 전환하는 단일 아키텍처 기준이다.

기존 [Commerce Studio V2 최종 기획](../plans/2026-08-01-sellform-commerce-studio-v2-final-master-plan.md)의 제품 비전, 사실 우선 정책, 상품 정체성 보존, 판매자 승인, 편집, 렌더링, 채널 출력 정책은 유지한다. 기존 UX-2E-0~3의 상품 브리프, 장면 계획, 이미지 생성, 검수 계약도 유지한다.

이 문서는 기존 `AgentGraph` 순차 실행과 API별 수동 상태 변경을 대체하는 **실제 LangGraph 런타임 계약**을 새로 정의한다.

## 2. 최종 결정

Sellform의 신규 AI 상세페이지 생성은 다음 조건을 모두 만족해야 한다.

1. `langgraph`의 `StateGraph`로 컴파일한 그래프를 실행한다.
2. 11개 전문 에이전트를 실제 그래프 노드 또는 서브그래프 노드로 등록한다.
3. 분기와 재작업은 `add_conditional_edges` 또는 노드가 반환하는 명시적 라우팅으로 처리한다.
4. 판매자 입력·기획·비용·이미지 승인 대기는 LangGraph `interrupt`로 중단한다.
5. 같은 `thread_id`와 `Command(resume=...)`로 중단 지점부터 재개한다.
6. 로컬 테스트를 제외한 실행은 PostgreSQL 체크포인터로 영속화한다.
7. API 키 부족, 잔액 부족, 제공자 장애가 있어도 생성 계획과 체크포인트를 보존한다.
8. 각 노드는 재시작과 재실행에 안전한 멱등성을 가져야 한다.
9. 실제 이미지 API 호출은 비용 승인 전에는 절대 실행하지 않는다.
10. 최종 상세페이지는 Page Assembly와 QA Review를 통과한 단일 버전 스냅샷으로 렌더링·다운로드한다.

파일이나 클래스 이름만 `graph`, `agent`, `node`로 만드는 것은 완료로 인정하지 않는다. 실제 LangGraph 의존성, 컴파일된 그래프, 체크포인터, interrupt/resume, 조건부 라우팅을 통합 테스트로 증명해야 한다.

## 3. 목표 사용자 경험

판매자는 상품 사진·링크·기본 정보를 입력한 후 하나의 생성 흐름을 시작한다. 내부적으로 여러 에이전트가 작업하지만 사용자는 복잡한 에이전트 제어 화면을 보지 않는다.

```text
상품 자료 입력
  → 자료·상품 이해
  → 사실 및 충돌 확인
  → 판매 전략·스토리보드·카피·비주얼 계획
  → 판매자 기획 승인
  → 비용 승인 또는 API 연결 대기
  → 장면별 이미지 생성·검사
  → 판매자 이미지 승인
  → 상세페이지 조립
  → 판매 품질 QA와 필요한 자동 재작업
  → 최종 검수·편집·다운로드
```

API 키나 예산이 없는 경우에도 앞 단계 결과를 잃지 않는다.

```text
planning_approval 완료
  → cost_or_provider_gate
  → generation_pending interrupt
  → 나중에 API 키·비용 준비
  → 같은 thread_id로 resume
  → image_generation부터 계속 실행
```

## 4. 현재 구조 평가

### 4.1 재사용할 자산

- `backend/src/agents/nodes/*`의 11개 역할별 폴더
- 에이전트별 `prompt.md`, Pydantic 스키마와 provider adapter
- `ProductBrief`, 사실·증거 보드, `ScenePlan`, 이미지 자산 분류 결과
- `AgentRun`, `AgentRunStep`, 이미지 생성 작업, 페이지·버전·출력 기록
- OpenAI 등 텍스트·이미지 제공자 어댑터와 비용 기록
- 기획, 결과, 고급 편집기, 다운로드 화면
- 커머스 렌더러, 최종화, 채널별 출력 서비스

### 4.2 교체할 실행 구조

- `AgentGraph.agents`를 `for`문으로 도는 순차 실행
- FastAPI 엔드포인트가 여러 단계의 상태와 페이지를 직접 조립하는 흐름
- `current_stage` 문자열만 변경하는 수동 진행 관리
- 프로세스 메모리 또는 단일 요청 수명에 의존하는 장시간 실행
- 버튼별로 서로 다른 작업 경로가 같은 프로젝트 결과를 덮어쓰는 구조
- 승인 버튼이 DB 값만 바꾸고 실제 실행 흐름과 연결되지 않는 구조

## 5. 기술 경계

LangGraph는 **오케스트레이션 런타임**이다. 모든 로직을 LLM 에이전트로 바꾸지 않는다.

| 계층 | 책임 |
| --- | --- |
| LangGraph | 노드 순서, 조건 분기, 승인 대기, 재시도, 체크포인트, 재개 |
| 전문 에이전트 | 상품 이해, 전략, 카피, 비주얼 계획, QA 판단 |
| 도메인 서비스 | OCR, 사실 저장, 이미지 API 호출, 정체성 검사, 페이지 조립, 렌더링 |
| FastAPI | 시작·조회·승인·재개·취소·이벤트 API |
| PostgreSQL | 업무 데이터와 LangGraph 체크포인트 영속화 |
| 프런트엔드 | 진행 상태, 승인 요청, 결과 검수, 편집, 다운로드 |

파일 저장, DB 조회, 이미지 변환처럼 결과가 결정적인 작업은 도메인 서비스로 유지하고 그래프 노드가 해당 서비스를 호출한다. 에이전트는 허용된 구조화 출력만 반환한다.

## 6. 최종 그래프

### 6.1 루트 그래프

```text
START
  → bootstrap_run
  → input_router
      ├─ missing_inputs → input_review_interrupt ─┐
      └─ ready ────────────────────────────────────┘
  → source_collection
  → product_understanding
  → reference_route
      ├─ reference 있음 → reference_analysis
      └─ reference 없음 → reference_skipped
  → evidence_gate
      ├─ 충돌·필수 누락 → evidence_review_interrupt
      └─ 통과
  → sales_strategy
  → page_planning
  → copywriting
  → visual_planning
  → planning_review_interrupt
      ├─ 수정 요청 → 지정된 planning 노드로 복귀
      └─ 승인
  → generation_gate
      ├─ API/비용 미준비 → generation_pending_interrupt
      ├─ 기존 사진·HTML만 사용 → page_assembly
      └─ 생성 승인 → image_generation_subgraph
  → image_review_interrupt
      ├─ 일부 재생성 → image_generation_subgraph
      ├─ 직접 업로드 → asset_reconciliation
      └─ 승인
  → page_assembly
  → qa_review
      ├─ COPY_REWORK → copywriting
      ├─ PLAN_REWORK → page_planning
      ├─ VISUAL_REWORK → visual_planning
      ├─ IMAGE_REWORK → image_generation_subgraph
      ├─ SELLER_REVIEW → final_review_interrupt
      └─ PASS → finalize_version
  → final_review_interrupt
      ├─ 수정 → 대상 노드 또는 편집기로 이동
      └─ 승인 → finalize_version
  → END
```

### 6.2 서브그래프

루트 그래프는 다음 네 영역을 독립 서브그래프로 구성할 수 있다.

1. `discovery_subgraph`
   - Input Router
   - Source Collection
   - Product Understanding
   - Reference Analysis

2. `commerce_planning_subgraph`
   - Sales Strategy
   - Page Planning
   - Copywriting
   - Visual Planning

3. `image_generation_subgraph`
   - 장면 작업 준비
   - 비용·중복 요청 확인
   - 제공자 작업 등록
   - 결과 수집
   - 정체성·OCR·권리 검사
   - 재시도 또는 검수 대기 판정

4. `assembly_qa_subgraph`
   - Page Assembly
   - QA Review
   - 제한된 재작업 라우팅
   - 최종 버전 고정

초기 전환에서는 노드 인터페이스를 먼저 고정한 뒤 서브그래프로 묶는다. 서브그래프 경계가 구현 복잡성을 키우면 단일 `StateGraph`로 먼저 전환하되 노드 이름과 상태 계약은 동일하게 유지한다.

## 7. 11개 에이전트 계약

| 순서 | 에이전트 | 입력 | 구조화 출력 | 외부 비용 |
| --- | --- | --- | --- | --- |
| 1 | Input Router | 입력 스냅샷, 자산 ID | 입력 유형, 누락, 라우팅 | 없음 |
| 2 | Source Collection | 승인 URL·업로드 | 출처·수집 결과·실패 이유 | 선택적 |
| 3 | Product Understanding | OCR·판매자 입력·자산 | 사실 후보, 상품 정체성, 불확실성 | 텍스트/비전 |
| 4 | Reference Analysis | reference-only 자료 | 참고 포인트, 복제 위험, 금지 요소 | 텍스트/비전 |
| 5 | Sales Strategy | 승인 사실·상품 분석 | 판매 전략 후보와 선택 근거 | 텍스트 |
| 6 | Page Planning | 전략·사실·채널 | 섹션 순서와 장면 목적 | 텍스트 |
| 7 | Copywriting | 계획·허용 사실 | 섹션별 한국어 카피와 근거 ID | 텍스트 |
| 8 | Visual Planning | 계획·카피·자산 | 장면 요구, 기준 사진, 프롬프트 청사진 | 텍스트/비전 |
| 9 | Image Generation | 승인 장면·비용·기준 사진 | 작업 및 생성 자산·검사 결과 | 이미지 |
| 10 | Page Assembly | 승인 카피·자산·템플릿 | 페이지 버전·섹션 스냅샷 | 없음 |
| 11 | QA Review | 조립본·증거·정책 | PASS 또는 재작업 코드와 대상 | 텍스트/규칙 |

각 에이전트는 `run(state, runtime) -> state delta` 계약을 갖는다. 전체 상태를 임의로 덮어쓰지 않고 자신에게 허용된 필드만 반환한다. 출력은 노드별 Pydantic 또는 TypedDict 스키마 검증을 통과해야 한다.

## 8. 그래프 상태 계약

`SellformGraphState`는 체크포인터에 직렬화 가능한 작은 상태만 가진다. 원본 이미지 바이트, SQLAlchemy 세션, API 키, 열린 파일, HTTP 클라이언트 객체는 저장하지 않는다.

```text
workflow_version
run_id / thread_id
workspace_id / project_id / actor_id
mode                       # mock | real
input_snapshot
asset_ids
source_collection_result
product_brief_version_id
evidence_snapshot_id / hash
reference_analysis
sales_strategy
page_plan
copy_set
visual_plan
approval_state
generation_job_ids
approved_generated_asset_ids
page_version_id
qa_report
routing_decision
retry_counts
cost_summary
errors
audit_context
```

큰 도메인 데이터는 기존 테이블에 저장하고 상태에는 버전 ID와 해시를 보존한다. 재개할 때 해시가 바뀌었다면 자동으로 계속하지 않고 변경 확인 게이트로 보낸다.

## 9. 상태와 데이터의 단일 책임

중복 저장으로 인한 불일치를 막기 위해 책임을 구분한다.

- LangGraph 체크포인트: 실행 위치, 노드 입력·출력, interrupt, 재개에 필요한 상태의 기준
- `AgentRun`: 작업 목록과 운영 화면을 위한 실행 요약 projection
- `AgentRunStep`: 노드별 관측·비용·오류 projection
- 사실, 자산, 장면, 페이지 버전: 도메인 데이터의 기준
- `ImageGenerationJobRecord`: 외부 이미지 제공자 작업과 비용·재시도 기준

체크포인트를 저장한 뒤 projection 갱신이 실패해도 복구 작업이 체크포인트에서 `AgentRun`과 `AgentRunStep`을 다시 만들 수 있어야 한다.

## 10. 영속성과 재개

- 단위 테스트: `InMemorySaver`
- 로컬 통합 및 운영: PostgreSQL 기반 checkpointer
- `thread_id`: 기본적으로 `AgentRun.id`
- 새 전체 생성: 새 `AgentRun.id`와 새 thread
- 같은 작업 재개: 기존 thread ID 유지
- 대안 분기 실험: 명시적 새 run 또는 checkpoint fork로 분리

그래프는 프로세스 재시작 후 다음을 지원해야 한다.

1. 마지막 체크포인트 조회
2. 대기 중 interrupt 복원
3. 실패 노드부터 안전하게 재실행
4. 이미 성공한 유료 제공자 작업 중복 호출 방지
5. 취소된 thread가 자동 재개되지 않도록 차단

## 11. Human-in-the-loop 승인 계약

승인 중단점은 최소 다음 다섯 종류다.

| interrupt | 사용자에게 보여 줄 내용 | 재개 입력 |
| --- | --- | --- |
| `input_review` | 누락 자료와 계속 가능한 범위 | 추가 입력 또는 제한 진행 |
| `evidence_review` | 충돌·미확인 사실 | 승인·수정·제외 |
| `planning_review` | 전략·섹션·카피·장면 계획 | 승인 또는 수정 지시 |
| `generation_pending` | API 상태·장면 수·비용 | 비용 승인, 기존 자산 진행, 나중에 재개 |
| `image_review` | 생성본과 기준 사진·검사 결과 | 승인·거절·재생성·업로드 |
| `final_review` | QA 결과와 최종 페이지 | 승인 또는 수정 |

interrupt payload와 resume payload는 JSON 스키마로 버전 관리한다. 버튼은 항상 하나의 resume API를 호출하며 성공·중단·실패 상태를 명시적으로 돌려받는다. 아무 반응이 없는 버튼은 허용하지 않는다.

interrupt 이전의 DB 쓰기와 외부 호출은 멱등해야 한다. 재개 시 해당 노드가 처음부터 다시 실행될 수 있음을 전제로 한다.

## 12. 이미지 생성 실행 방식

이미지 제공자 호출은 장시간 실행이므로 그래프 요청 스레드에서 기다리지 않는다.

```text
prepare_image_jobs
  → 승인·예산·idempotency key 검증
  → ImageGenerationJobRecord 생성
  → provider worker 실행
  → 그래프는 provider_wait 상태로 중단
  → worker/webhook/poller가 결과 저장
  → 같은 graph thread 재개
  → identity_and_safety_validation
  → image_review interrupt
```

작업 키는 최소 `project_id + scene_id + prompt_version + reference_hash + attempt`를 포함한다. 같은 키의 성공 작업이 있으면 제공자를 다시 호출하지 않는다.

API 키 미설정, 잔액 부족, 한도 초과는 실패 결과를 가짜 이미지로 대체하지 않는다. `generation_pending` 또는 명시적인 복구 가능 오류로 중단하고 기존 사진·HTML 정보형 결과를 유지한다.

## 13. QA와 재작업 루프

QA 결과는 자유 텍스트가 아니라 다음 라우팅 코드 중 하나를 반환한다.

- `PASS`
- `COPY_REWORK`
- `PLAN_REWORK`
- `VISUAL_REWORK`
- `IMAGE_REWORK`
- `SELLER_REVIEW`
- `BLOCKED_POLICY`

노드별 자동 재작업 횟수는 기본 2회로 제한한다. 한도를 넘으면 판매자 검수로 보낸다. QA는 이전 승인 사실을 바꾸지 못하고, 승인 사실과 충돌하는 카피·이미지를 제거하거나 재작업 요청할 수만 있다.

## 14. FastAPI 계약

신규 API의 개념적 계약은 다음과 같다.

- `POST /api/v1/projects/{project_id}/graph-runs`
  - 새 그래프 실행 생성
- `GET /api/v1/graph-runs/{run_id}`
  - 현재 노드, 상태, interrupt, 비용, 결과 조회
- `GET /api/v1/graph-runs/{run_id}/events`
  - 노드 진행 이벤트 스트림
- `POST /api/v1/graph-runs/{run_id}/resume`
  - 승인·수정·업로드·비용 결정을 전달하고 같은 thread 재개
- `POST /api/v1/graph-runs/{run_id}/retry`
  - 허용된 실패 노드 재시도
- `POST /api/v1/graph-runs/{run_id}/cancel`
  - 실행과 미시작 provider 작업 취소
- `GET /api/v1/graph-runs/{run_id}/history`
  - 사용자에게 허용된 실행·승인·버전 이력

초기 전환 기간에는 기존 프로젝트 API가 내부적으로 신규 graph-run API를 호출하는 호환 어댑터를 둔다. 신규 프런트엔드가 더 이상 기존 직접 조립 엔드포인트를 호출하지 않는 것이 확인된 뒤 어댑터를 제거한다.

## 15. 실시간 진행 화면

프런트엔드는 수동으로 추정한 단계가 아니라 그래프 이벤트와 projection을 표시한다.

- 현재 실행 중인 에이전트
- 완료·대기·실패·건너뜀 상태
- 사용자에게 필요한 다음 행동
- 이미지 장면별 작업 상태
- 예상·실제 비용
- 재시도 가능 여부
- 마지막 체크포인트와 갱신 시각

새로고침 후에도 동일 run과 interrupt를 복구해야 한다. 로그인·워크스페이스 권한을 다시 확인한 뒤 이벤트 스트림을 재연결한다.

## 16. 비용과 보안

- API 키와 provider secret은 서버 환경에서만 읽고 그래프 상태·로그·응답에 저장하지 않는다.
- 모든 run, checkpoint 조회, resume, asset 접근은 workspace와 actor 권한을 검사한다.
- 실제 API 호출 전 `cost_approval_status`, 승인 범위, 예상 최대 비용을 검증한다.
- 텍스트와 이미지 비용을 노드·장면·attempt별로 기록한다.
- 재시도 시 기존 provider 작업 상태를 먼저 조회해 중복 청구를 방지한다.
- 판매자가 승인하지 않은 공급처 이미지를 최종 출력 자산으로 승격하지 않는다.

## 17. 관측성과 운영

필수 기록:

- graph version, run ID, thread ID, checkpoint ID
- 노드 시작·완료·실패·중단·재개 시각
- 입력·출력 스키마 버전과 도메인 스냅샷 해시
- provider·model·token·이미지 수·비용·latency
- 라우팅 결정과 재작업 횟수
- 사용자 승인·수정·거절 이벤트

고객 원문과 이미지를 운영 통계나 외부 추적 서비스로 보내지 않는다. 외부 트레이싱을 도입할 경우 명시적 환경 설정, 마스킹, 보존 기간과 비활성화 경로를 먼저 만든다.

## 18. 테스트 전략

### 18.1 노드 계약

- 모든 노드가 허용된 state delta만 반환한다.
- 잘못된 LLM JSON은 스키마 오류로 분류하고 무한 재시도하지 않는다.
- mock과 real이 같은 출력 스키마를 사용한다.

### 18.2 그래프 라우팅

- URL 없음은 Reference Analysis를 건너뛴다.
- 필수 입력 누락은 `input_review`에서 중단한다.
- 사실 충돌은 `evidence_review`에서 중단한다.
- 비용 미승인은 provider 호출 없이 `generation_pending`에서 중단한다.
- QA 라우팅 코드별로 올바른 노드에 돌아간다.
- 재작업 한도 초과 시 판매자 검수로 이동한다.

### 18.3 영속·멱등

- 서버 재시작 후 같은 thread를 재개한다.
- resume 요청 중복 전송이 외부 API·페이지 버전을 중복 생성하지 않는다.
- provider 성공 뒤 응답 유실 상황에서 다시 청구하지 않는다.
- 취소·실패·interrupt 상태가 새로고침 후 유지된다.

### 18.4 제품 E2E

최소 다음 시나리오를 고정한다.

1. API 없는 상태에서 기획까지 만든 후 나중에 같은 run으로 이미지 생성 재개
2. 판매자 사진만으로 HTML·기존 사진형 상세페이지 완성
3. 실제 이미지 생성, 일부 거절·재생성, 승인 후 상세페이지 완성
4. QA 카피 반려 후 Copywriting 재실행 및 최종 통과
5. 서버 재시작·브라우저 새로고침 후 승인 대기 복구
6. 쿠팡·스마트스토어 미리보기와 JPG·분할 ZIP의 버전 일치

## 19. 전환 전략

1. 기존 동작을 characterization test로 고정한다.
2. `SELLFORM_GRAPH_RUNTIME=legacy|langgraph` 기능 플래그를 도입한다.
3. 신규 테스트 프로젝트부터 LangGraph를 사용한다.
4. 기존 프로젝트는 기존 결과를 읽을 수 있게 유지하며 임의로 체크포인트를 합성하지 않는다.
5. 기존 프로젝트를 다시 생성할 때 새 graph run을 만든다.
6. LangGraph 결과와 기존 렌더러 출력이 같은 도메인 계약을 사용하는지 확인한다.
7. 모든 생성 진입점이 신규 graph run으로 연결된 뒤 legacy 쓰기 경로를 제거한다.
8. 최소 한 Sprint 동안 읽기 호환을 유지한 후 불필요한 legacy 코드를 삭제한다.

## 20. 완료 정의

다음 항목이 모두 충족되어야 “LangGraph 전환 완료”로 표시한다.

- `langgraph`와 PostgreSQL checkpointer가 프로젝트 의존성에 존재한다.
- `StateGraph`에 11개 전문 에이전트가 등록되고 그래프가 컴파일된다.
- 최소 하나 이상의 조건부 분기, 재작업 루프, 서브그래프가 실제 실행된다.
- 판매자 승인 대기가 `interrupt`로 저장되고 같은 thread에서 resume된다.
- API 키·비용이 없을 때 체크포인트를 보존하고 나중에 이미지 단계부터 재개한다.
- 프로세스 재시작 후 실행 상태를 복구한다.
- 유료 provider 호출과 페이지 버전 생성의 멱등성이 검증된다.
- 프런트엔드의 생성·승인 버튼이 graph-run API와 연결된다.
- 최종 페이지·미리보기·JPG·ZIP이 동일한 승인 버전을 사용한다.
- legacy `AgentGraph`가 신규 생성 경로에서 호출되지 않는다.
- 정해진 단위·통합·E2E 테스트와 코드리뷰 문서가 통과한다.

## 21. 범위 제외

- 에이전트가 임의로 새 도구나 결제 작업을 선택하는 완전 자율 실행
- 고객 콘텐츠를 모델 학습이나 공개 템플릿에 자동 사용
- 승인되지 않은 경쟁 상품 비교·효능·가격 문구 생성
- 기존 모든 프로젝트 체크포인트의 자동 역생성
- LangSmith 또는 별도 Agent Server 도입을 LangGraph 전환의 필수 조건으로 강제

## 22. 공식 기술 근거

설계는 LangGraph 공식 문서의 다음 계약을 기준으로 한다.

- StateGraph와 durable execution: <https://docs.langchain.com/oss/python/langgraph/overview>
- checkpoint와 thread 기반 persistence: <https://docs.langchain.com/oss/python/langgraph/persistence>
- interrupt와 `Command(resume=...)`: <https://docs.langchain.com/oss/python/langgraph/interrupts>
- 멀티에이전트 서브그래프: <https://docs.langchain.com/oss/python/langgraph/use-subgraphs>
- 그래프 실행 이벤트 스트리밍: <https://docs.langchain.com/oss/python/langgraph/streaming>
