# 결정: Sellform LangGraph 실행기와 체크포인트 책임 경계

상태: **채택**  
결정일: 2026-08-06  
대체 문서: [2026-06-24 Sellform LangGraph 도입 판단 기록](./2026-06-24-sellform-langgraph-adoption-criteria.md)

## 배경

Sellform은 상품 수집, 사실 확인, 판매 기획, 이미지 생성, 판매자 승인, 페이지 조립, QA를 거친다. 이 흐름은 API 키·비용 부족 상태에서 멈췄다가 나중에 재개하고, 실패한 단계만 다시 실행하며, 여러 승인 지점을 가져야 한다.

기존 `AgentGraph`는 11개 에이전트를 `for`문으로 실행하고 일부 별도 FastAPI 엔드포인트가 이미지 생성·페이지 조립을 직접 처리한다. 이는 현재 동작에는 유효하지만, 장기 실행과 사람 승인 상태를 일관되게 보존할 실행기가 필요하다.

## 선택지

1. 기존 순차 `AgentGraph`와 API별 상태 변경을 계속 확장한다.
2. 자체 상태 머신을 새로 구현한다.
3. LangGraph `StateGraph`와 PostgreSQL checkpointer로 실행을 관리하고, 기존 도메인 서비스를 노드에서 호출한다.

## 결정

신규 상세페이지 생성은 단계적으로 **LangGraph `StateGraph`**로 전환한다. 실행 상태는 PostgreSQL checkpointer에 저장하고, 도메인 데이터는 기존 Sellform 테이블에 유지한다.

LG-0에서는 실제 LangGraph 의존성·안전 입력 경계·`legacy` 기본 feature flag만 추가한다. 실제 `AgentRun` 라우팅과 PostgreSQL checkpointer 연결은 LG-1에서 시작한다.

## 책임 경계

| 저장소 또는 모델 | 기준 책임 | LangGraph와의 관계 |
| --- | --- | --- |
| LangGraph checkpoint | 현재 노드, 상태 delta, interrupt, resume 위치 | 실행 상태의 기준 |
| `AgentRun` | 작업 목록·권한·현재 상태 요약 | checkpoint 이벤트를 투영한 운영 projection |
| `AgentRunStep` | 노드별 진행·오류·비용 요약 | checkpoint/stream event를 투영 |
| 사실·자산·장면 계획 | 상품 근거와 승인된 입력 | graph state에는 ID·hash만 저장 |
| `ImageGenerationJobRecord` | 외부 제공자 작업·attempt·비용·결과 자산 | 이미지 노드가 생성·조회, graph가 재개 |
| `DetailPageVersion` | 최종 페이지의 불변 스냅샷 | Page Assembly 완료 후 생성 |

API 키, access token, 세션, 원본 이미지 바이트, SQLAlchemy 세션, HTTP client는 checkpoint에 저장하지 않는다.

## 현재 생성 진입점과 직접 조립 경로

| 구분 | 현재 API 또는 호출 경로 | 현재 책임 | LangGraph 전환 시 처리 |
| --- | --- | --- | --- |
| 신규 run 생성 | `POST /api/agent-runs` | `AgentRun` 생성 | LG-1 graph-run 생성 adapter로 연결 |
| mock 실행 | `POST /api/agent-runs/{id}/run-mock` → `AgentRunService.run_mock()` | `AgentGraph.mock()` 순차 실행 | LG-1~LG-6 전환 전까지 legacy 유지 |
| real text 실행 | `POST /api/agent-runs/{id}/run` → `AgentRunService.run_real_text()` | `AgentGraph.real_text()` 순차 실행 | LG-1~LG-6 전환 전까지 legacy 유지 |
| 기획 승인·페이지 조립 | `POST /api/v1/projects/{project_id}/planning-draft/approve` | PageSection·버전 생성, 조건부 이미지 실행 | LG-4 이후 planning resume node로 대체 |
| 시각 작업 직접 생성 | `POST /api/v1/projects/{project_id}/visual-jobs/{job_id}/generate` | image provider 호출 | LG-5 image subgraph의 dispatch worker로 편입 |
| 스토리보드 이미지 시작 | `POST /api/v1/projects/{project_id}/storyboard/image-jobs/{job_id}/start` | background worker 시작 | LG-5가 같은 graph thread 재개로 연결 |
| 스토리보드 이미지 승인 | `POST /api/v1/projects/{project_id}/storyboard/image-jobs/{job_id}/approve` | 결과 자산 승인 | LG-5 `image_review` resume payload로 편입 |
| 이미지 비용 승인 | `POST /api/v1/projects/{project_id}/images/approve-cost` | 별도 orchestrator 실행 | LG-4 `generation_pending` resume으로 대체 |
| 페이지 직접 생성·수정 | `/api/v1/projects/{project_id}/page*`, `page/sections/*/ai-edit` | 페이지 생성·변경·최종화 | LG-6까지 읽기·편집 호환 유지, 신규 생성은 graph 결과 사용 |

이 표의 모든 쓰기 경로는 LG-8 전환 검증 목록에 포함한다. 신규 생성이 LangGraph를 우회하는 경로가 발견되면 LG-8 완료로 인정하지 않는다.

## 이유와 트레이드오프

- LangGraph는 checkpoint, interrupt/resume, 조건부 분기, 실패 재개를 제공하므로 승인·비용·이미지 생성 흐름에 적합하다.
- 도메인 서비스와 테이블을 유지하므로 전면 재작성이나 기존 프로젝트 데이터 변환이 필요하지 않다.
- 체크포인트와 업무 projection이 이중 저장이 되므로 projection rebuild와 멱등 키가 필요하다.
- 운영에서 checkpoint 크기와 보존 기간을 관리해야 한다.
- 노드가 interrupt 이전에 외부 작업을 만들 경우 재개 때 중복 실행될 수 있으므로 provider 작업은 멱등 키를 필수로 사용한다.

## 영향 범위

- LG-0: 실제 의존성, 안전 상태 입력, 경로 목록과 기준선 테스트
- LG-1: checkpointer, thread, `AgentRun` projection
- LG-2~LG-6: 11개 에이전트와 승인·재작업 전환
- LG-7: 진행 이벤트와 복구
- LG-8: legacy 신규 쓰기 경로 제거

## 재검토 조건

- PostgreSQL checkpointer가 현재 운영 DB의 보존·성능 요구를 충족하지 못하는 경우
- LangGraph 상태 직렬화가 Sellform의 도메인 스냅샷과 충돌하는 경우
- 단일 서비스 내 graph worker가 제공자 작업의 복구를 보장하지 못하는 경우

위 경우에도 checkpoint·업무 데이터 책임 분리는 유지하고, 저장소 또는 worker 구현만 재선택한다.
