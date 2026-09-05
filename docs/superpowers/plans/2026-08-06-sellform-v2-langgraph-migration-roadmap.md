# Sellform V2 실제 LangGraph 전환 Sprint 로드맵

> **기준 변경 안내 (2026-08-07):** LG-0~LG-5 구현 이력은 이 문서에 보존합니다. 현재 후속 구현 순서와 완료 기준은 [Sellform V2.1 AI Commerce Studio Sprint 로드맵](./2026-08-07-sellform-v2-ai-commerce-studio-v2.1-roadmap.md)을 따릅니다.

작성일: 2026-08-06  
상태: **구현 대기**  
상위 기획: [실제 LangGraph 멀티에이전트 시스템 최종 기획](../specs/2026-08-06-sellform-v2-langgraph-agent-system-final-design.md)

## 1. 목적

현재 커스텀 순차형 `AgentGraph`와 API별 수동 오케스트레이션을 실제 LangGraph 기반 멀티에이전트 실행 구조로 안전하게 전환한다.

기존 V2·UX-2E 기능을 다시 만들지 않는다. 상품 입력, 사실·증거, 장면 계획, 이미지 생성, 렌더러, 편집기와 출력 기능은 유지하고 중앙 실행·승인·재개·관측 구조를 교체한다.

## 2. Sprint 운영 원칙

- Sprint는 `LG-0`부터 별도 번호를 사용한다.
- 각 Sprint는 독립된 구현 계획과 코드리뷰 문서를 만든다.
- 이전 Sprint 완료 조건과 회귀 테스트를 통과하지 않으면 다음 Sprint로 넘어가지 않는다.
- 실제 provider 비용이 없어도 LG-0~4, LG-6 대부분과 LG-7~8의 mock/fake-provider 검증을 진행할 수 있다.
- 실제 이미지 API 검증은 LG-5의 별도 비용 승인 테스트로 제한한다.
- 전환 중에는 feature flag로 legacy와 LangGraph 경로를 비교한다.

## 3. 전체 Sprint

| Sprint | 목표 | 사용자에게 보이는 결과 | 실제 API 비용 |
| --- | --- | --- | --- |
| LG-0 | 기준선·의존성·전환 계약 | 기존 기능 변화 없음 | 없음 |
| LG-1 | StateGraph·상태·Postgres 체크포인터 | 실행이 재시작 후 복구됨 | 없음 |
| LG-2 | 자료 수집·상품 이해 서브그래프 | 입력 부족·사실 충돌을 정확히 안내 | 텍스트/비전 선택 |
| LG-3 | 전략·스토리보드·카피·비주얼 서브그래프 | 전문 에이전트 결과와 기획 초안 제공 | 텍스트 선택 |
| LG-4 | 승인 interrupt/resume와 프런트 연결 | 새로고침 후에도 승인 대기·재개 | 없음 |
| LG-5 | 이미지 생성 서브그래프 | 비용 준비 후 같은 run에서 이미지 생성 | 이미지 선택 |
| LG-6 | 페이지 조립·QA 재작업 루프 | 검수 통과한 상세페이지 완성 | QA 텍스트 선택 |
| LG-7 | 스트리밍·복구·멱등·운영 관측 | 정확한 진행률과 실패 복구 | 없음 |
| LG-8 | 전체 전환·legacy 제거·출력 E2E | 원클릭부터 JPG·ZIP까지 단일 흐름 | 제한적 |

## 4. LG-0 — 기준선과 전환 안전망

### 목표

현재 동작을 테스트로 고정하고 “실제 LangGraph”의 기술 기준과 전환 경계를 코드에 준비한다.

### 주요 작업

1. 현재 `AgentGraph`, `AgentRunService`, planning 승인, 이미지 작업, page assembly 호출 경로를 문서화한다.
2. 생성 진입점과 직접 페이지 조립 엔드포인트 목록을 만든다.
3. 현재 11개 에이전트 입출력을 characterization test로 고정한다.
4. `langgraph`와 PostgreSQL checkpointer 의존성을 추가하고 버전을 lock한다.
5. `SELLFORM_GRAPH_RUNTIME=legacy|langgraph` 설정을 추가한다.
6. 테스트에서는 외부 API를 호출하지 않는 fake text/image provider를 고정한다.
7. LangGraph checkpoint 저장소와 Sellform 업무 테이블의 책임을 ADR로 남긴다.

### 완료 조건

- 기존 golden-path 결과와 상태 전이가 자동 테스트로 고정된다.
- 실제 LangGraph 패키지 import와 최소 컴파일 smoke test가 통과한다.
- 설정이 `legacy`일 때 기존 동작이 변하지 않는다.
- API 키·secret이 체크포인트에 직렬화되지 않는 테스트가 있다.
- LG-0 코드리뷰 문서에 신규/legacy 진입점 목록이 포함된다.

## 5. LG-1 — LangGraph 런타임·상태·체크포인트

### 목표

실제 `StateGraph` 실행기와 영속 상태 기반을 만든다.

### 주요 작업

1. JSON 직렬화 가능한 `SellformGraphState`를 정의한다.
2. `bootstrap_run`, 임시 test node, finalize node를 가진 최소 그래프를 만든다.
3. 로컬 단위 테스트용 `InMemorySaver`와 PostgreSQL checkpointer factory를 만든다.
4. `thread_id=AgentRun.id` 계약을 적용한다.
5. `AgentRun`과 `AgentRunStep`을 graph event에서 갱신하는 projection adapter를 만든다.
6. `start`, `get state`, `cancel`, 내부 `resume` 서비스 계약을 만든다.
7. 프로세스 재시작·실패 후 동일 thread 복구 테스트를 작성한다.

### 완료 조건

- `StateGraph(...).compile(checkpointer=...)`가 실제 실행된다.
- 노드별 체크포인트와 state history를 조회할 수 있다.
- 서버 재시작을 모사한 새 DB 세션에서 같은 thread를 재개한다.
- `AgentRun.current_stage`는 그래프 이벤트 projection으로만 변경된다.
- 같은 start 요청이 중복 run을 만들지 않는 idempotency 테스트가 통과한다.

## 6. LG-2 — Discovery 서브그래프

### 목표

입력부터 상품 이해와 레퍼런스 분석까지 첫 네 전문 에이전트를 실제 그래프 노드로 전환한다.

### 대상 에이전트

1. Input Router
2. Source Collection
3. Product Understanding
4. Reference Analysis

### 주요 작업

1. 각 에이전트를 `state delta` 반환 방식으로 변경한다.
2. 기존 prompt와 schema를 유지하면서 노드별 입력 필드를 최소화한다.
3. URL 유무에 따른 Reference Analysis skip 조건부 엣지를 만든다.
4. 필수 입력 누락과 수집 실패를 오류가 아닌 명시적 routing decision으로 만든다.
5. OCR·자산 이해·사실 보드 서비스는 도메인 서비스 호출로 연결한다.
6. 사실 스냅샷 ID와 hash만 graph state에 보존한다.
7. mock과 real provider가 동일 상태 계약을 반환하게 한다.

### 완료 조건

- 네 에이전트가 `StateGraph` 노드로 등록된다.
- URL 없는 입력은 Reference Analysis가 `skipped`로 기록된다.
- 링크 수집 실패 후 직접 업로드 자료로 계속 진행할 수 있다.
- 근거 없는 사실이 승인 사실로 승격되지 않는다.
- 기존 ProductBrief·증거 보드 데이터와 결과가 호환된다.

## 7. LG-3 — Commerce Planning 서브그래프

### 목표

상품 이해 결과를 판매 가능한 상세페이지 기획으로 바꾸는 네 전문 에이전트를 실제 그래프 노드로 전환한다.

### 대상 에이전트

5. Sales Strategy
6. Page Planning
7. Copywriting
8. Visual Planning

### 주요 작업

1. 승인된 사실 스냅샷만 판매 전략과 카피 입력으로 허용한다.
2. 전략 후보, 선택 근거, 페이지 섹션, 카피, 장면 계획의 버전 스키마를 고정한다.
3. 검증되지 않은 수치·효능·경쟁 우월 표현을 차단한다.
4. 각 카피에 사실 근거 ID 또는 비사실 표현 분류를 붙인다.
5. Visual Planning 결과를 UX-2E `ScenePlan`과 통합한다.
6. 기존 planning 화면이 신규 graph state projection을 읽게 하는 read adapter를 만든다.
7. 일부 노드 재실행 시 뒤 단계 결과를 무효화하는 규칙을 만든다.

### 완료 조건

- 네 에이전트가 앞 단계의 구조화 결과를 순서대로 사용한다.
- 장면마다 목적, 사실 ID, 기준 자산, 생성 방식이 존재한다.
- 판매 금지 표현과 미확인 사실이 최종 카피에 포함되지 않는다.
- 같은 승인 사실과 prompt version으로 재실행한 mock 결과가 재현 가능하다.
- 기존 기획 화면에서 새 결과를 확인할 수 있다.

## 8. LG-4 — Human-in-the-loop 승인과 재개

### 목표

사용자 승인과 API 대기를 실제 LangGraph `interrupt`와 `Command(resume=...)`로 연결한다.

### 주요 작업

1. `input_review`, `evidence_review`, `planning_review`, `generation_pending` interrupt 노드를 만든다.
2. interrupt/resume payload의 버전 스키마를 만든다.
3. graph run 시작·조회·resume·취소 API를 만든다.
4. 동일한 `thread_id`를 사용하지 않은 resume를 거부한다.
5. 승인 화면 버튼을 graph resume API와 연결한다.
6. 승인 요청 중 로딩·성공·다음 interrupt·실패 상태를 UI에 표시한다.
7. 브라우저 새로고침 후 대기 interrupt를 복구한다.
8. API 키·비용이 없으면 generation 단계 앞에서 안전하게 중단한다.

### 완료 조건

- 판매자 승인 전에는 뒤 노드가 실행되지 않는다.
- resume 후 interrupt 노드가 재실행되어도 DB 중복 쓰기가 없다.
- 승인 버튼을 두 번 눌러도 외부 작업과 버전이 하나만 생성된다.
- API 비용이 없는 프로젝트를 저장하고 나중에 같은 run에서 재개할 수 있다.
- 아무 변화가 없는 버튼 상태가 자동 E2E 테스트에서 검출된다.

## 9. LG-5 — Image Generation 서브그래프

### 목표

승인된 장면별 이미지 생성, 비동기 대기, 정체성·안전 검사와 판매자 검수를 실제 그래프 흐름으로 연결한다.

### 대상 에이전트

9. Image Generation

### 주요 작업

1. 이미지 생성 노드를 prepare, dispatch, wait, collect, validate로 분리한다.
2. `ImageGenerationJobRecord`를 provider 작업의 단일 기준으로 유지한다.
3. 장면·프롬프트·기준 사진 hash 기반 idempotency key를 적용한다.
4. provider worker 완료가 같은 graph thread를 재개하는 연결을 만든다.
5. API 키 미설정, 잔액 부족, timeout, 안전 차단, 정체성 불일치를 구분한다.
6. 정체성·OCR·가격·QR·로고·권리 검사 결과를 state에 asset ID로 연결한다.
7. `image_review` interrupt에서 승인·거절·재생성·직접 업로드를 처리한다.
8. 일부 장면 실패가 기존 승인 결과를 삭제하지 않도록 한다.

### 완료 조건

- 비용 승인 전 provider 호출 수가 0임을 테스트한다.
- 서버 재시작과 worker 응답 유실 후에도 중복 청구하지 않는다.
- 실패 장면만 재시도하고 성공 장면은 재사용한다.
- 승인되지 않은 생성 이미지는 Page Assembly 입력에 포함되지 않는다.
- API가 없어도 generation pending 상태와 기획 결과가 보존된다.

## 10. LG-6 — Page Assembly와 QA 재작업 루프

### 목표

승인된 사실·카피·이미지를 상세페이지로 조립하고 QA 결과에 따라 필요한 전문 에이전트만 다시 실행한다.

### 대상 에이전트

10. Page Assembly
11. QA Review

### 주요 작업

1. Page Assembly를 canonical renderer 입력 스냅샷 생성 노드로 전환한다.
2. 승인된 asset과 copy version만 조립하도록 한다.
3. QA 구조화 라우팅 코드와 대상 노드를 고정한다.
4. `COPY_REWORK`, `PLAN_REWORK`, `VISUAL_REWORK`, `IMAGE_REWORK` 조건부 엣지를 만든다.
5. 노드별 최대 자동 재작업 횟수를 적용한다.
6. 재작업 한도 초과와 정책 차단은 판매자 검수 interrupt로 보낸다.
7. 최종 승인 시 `DetailPageVersion`을 불변 스냅샷으로 고정한다.
8. 미리보기와 JPG·ZIP이 동일 page version을 사용하게 한다.

### 완료 조건

- QA PASS 없이는 최종 완료 상태가 되지 않는다.
- QA 사유에 맞는 노드만 재실행된다.
- 무한 루프가 불가능하고 한도 초과 시 사용자 행동을 제공한다.
- API 생성 이미지가 없어도 안전한 기존 사진·HTML 경로로 완성 가능하다.
- 미리보기와 다운로드 결과의 section·copy·asset version이 일치한다.

## 11. LG-7 — 스트리밍·복구·운영 관측

### 목표

장시간 실행을 사용자와 운영자가 정확하게 이해하고 복구할 수 있게 한다.

### 주요 작업

1. graph stream/update를 제품용 이벤트로 변환하는 event adapter를 만든다.
2. SSE 또는 기존 인프라에 맞는 단방향 진행 이벤트 API를 만든다.
3. 프런트엔드 진행 화면을 실제 노드·서브그래프 상태에 연결한다.
4. 연결이 끊기면 현재 state 조회 후 이벤트를 재연결한다.
5. 중단된 running 작업을 찾는 recovery sweep과 lease를 만든다.
6. checkpoint와 `AgentRunStep` 불일치를 복구하는 projection rebuild를 만든다.
7. 노드별 latency, provider 비용, 재시도, interrupt 대기 시간을 기록한다.
8. 로그·트레이스에서 API 키와 고객 민감 자료를 마스킹한다.

### 완료 조건

- 새로고침 후 현재 노드와 승인 요청이 동일하게 복원된다.
- 프로세스 강제 종료 후 마지막 안전 checkpoint에서 재개된다.
- 동일 이벤트 재전송이 UI 상태를 손상시키지 않는다.
- 운영 로그만으로 실패 노드·원인·비용·재시도 여부를 식별할 수 있다.
- 외부 추적이 꺼져 있어도 전체 기능이 동작한다.

## 12. LG-8 — 전환·legacy 제거·최종 E2E

### 목표

모든 신규 상세페이지 생성 진입점을 LangGraph로 통일하고 기존 직접 오케스트레이션을 안전하게 제거한다.

### 주요 작업

1. 원클릭 생성, planning 승인, 결과 페이지, 고급 편집기 진입을 graph run으로 통일한다.
2. legacy와 LangGraph 결과를 기준 상품으로 비교한다.
3. 기존 프로젝트는 읽기·다운로드 호환을 유지한다.
4. 신규 생성 경로에서 `AgentGraph.run*` 호출과 API 직접 page assembly를 제거한다.
5. legacy feature flag rollback 절차를 검증한 후 기본값을 `langgraph`로 바꾼다.
6. 쿠팡·스마트스토어 JPG와 분할 ZIP까지 전체 E2E를 실행한다.
7. 보안, 비용, 정체성 보존, 사실 근거, 데이터 격리를 최종 점검한다.
8. 최종 코드리뷰와 운영 가이드를 작성한다.

### 완료 조건

- 신규 프로젝트의 모든 생성은 컴파일된 LangGraph를 통과한다.
- legacy `AgentGraph`는 신규 쓰기 경로에서 호출되지 않는다.
- API 없음 → 대기 → API 준비 → resume → 이미지 승인 → 최종 출력 시나리오가 통과한다.
- 서버 재시작·브라우저 새로고침·중복 클릭·provider 실패 E2E가 통과한다.
- 쿠팡·스마트스토어 결과와 다운로드 이력이 동일 최종 버전을 가리킨다.
- 최종 기획의 완료 정의를 코드리뷰 문서에서 항목별 증명한다.

## 13. 의존 관계

```text
LG-0
  → LG-1
      → LG-2
          → LG-3
              → LG-4
                  ├─ LG-5
                  └─ LG-6 준비
                       LG-5 → LG-6
                                → LG-7
                                    → LG-8
```

LG-5 실제 provider 테스트는 예산 준비까지 미룰 수 있다. 다만 fake provider로 interrupt, worker, 재개, 정체성 검사, 재시도 계약을 먼저 완료해야 LG-6로 넘어갈 수 있다.

## 14. 각 Sprint 공통 산출물

각 Sprint는 다음을 남긴다.

1. Sprint별 구현 계획 문서
2. 변경 코드와 DB migration
3. 단위·통합·필요 E2E 테스트
4. 실행 명령과 테스트 결과
5. 기획 항목별 구현 증거가 있는 코드리뷰 문서
6. 미완료·후속 항목과 다음 Sprint 진입 판단

## 15. 착수 순서

첫 구현 단위는 LG-0이다. LG-0에서는 제품 동작을 바꾸지 않고 현재 경로를 테스트로 고정한 후 실제 LangGraph 의존성, feature flag와 최소 컴파일 그래프만 추가한다. 이를 통과한 뒤 LG-1에서 PostgreSQL 체크포인트와 실행 상태를 연결한다.
