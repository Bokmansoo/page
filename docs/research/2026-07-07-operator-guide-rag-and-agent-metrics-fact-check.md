# operator_guide RAG 및 Agent 수치 사실확인

작성일: 2026-07-07  
확인 대상: `operator_guide`, RAG/pgvector, `process_optimizer`, Quest Agent, Material Generation Agent 관련 수치

## 요약 결론

| 질문 | 확인 결과 | 판정 |
| --- | --- | --- |
| operator_guide에서 실제 사용한 RAG 문서 개수는 몇 개인가? | 현재 저장소와 Git 전체 이력에서 구체적인 문서 개수는 발견되지 않았다. 리뷰 문서에는 "기획·결정 문서"와 RAG 관련 코드 4개 영역을 검토했다고만 적혀 있다. | 확정 불가 |
| pgvector에 저장한 chunk 수는 몇 개인가? | 저장된 chunk 총량을 기록한 문서, 로그, 마이그레이션, 모델, 테스트 증적이 현재 저장소에 없다. 리뷰 문서에는 "pgvector 검색" 및 "청크 정보 반환"만 언급된다. | 확정 불가 |
| process_optimizer의 node 수 30개, operation 5개, test 82개가 최종 수치 맞는가? | 현재 저장소와 Git 전체 이력에서 `process_optimizer`, "30 nodes", "5 operations", "82 tests" 근거를 찾지 못했다. 현재 코드의 에이전트 그래프는 Sellform용 11-node 구조다. | 저장소 근거 없음 |
| `259 tests passed`는 operator_guide 전체 테스트인가, Factory-Space 전체 테스트인가? | 현재 저장소와 Git 전체 이력에서 `259 tests passed` 또는 동등한 테스트 로그를 찾지 못했다. 현재 트리 기준 정적 테스트 함수 수는 backend pytest 417개, frontend e2e 41개, integrations JS 18개다. | 출처 확인 필요 |
| Quest Agent, Material Generation Agent는 본인 구현인가, 팀원 구현인가? | 현재 저장소와 Git 전체 이력에서 Quest Agent, Material Generation Agent 구현 또는 소유자 기록을 찾지 못했다. | 확인 불가 |

## 확인한 근거

### 1. operator_guide RAG 관련 근거

발견된 주요 문서는 다음 1개다.

- `docs/reviews/2026-06-15-operator-guide-rag-sprint-10-code-review.md`

이 문서에서 확인되는 내용:

- 브랜치명: `feature/operator-guide-rag-sprint10`
- RAG 디버그 API: `POST /api/v1/debug/manual-rag/search`
- 보안 플래그: `FACTORY_RAG_DEBUG_ENABLED`
- 테스트 격리 플래그: `FACTORY_RAG_RUNTIME_MOCK`
- pgvector DB 및 Embedding Provider를 `ManualQAService`에 wiring
- 검토 범위로 언급된 코드 영역:
  - `backend/src/api/debug_router.py`
  - `backend/src/app.py`
  - `backend/src/rag/rag_retriever.py`
  - `backend/src/db/engine.py`

하지만 해당 리뷰 문서에는 RAG 입력 문서 개수나 pgvector chunk 총량이 숫자로 적혀 있지 않다.

### 2. 현재 저장소의 RAG 구현 상태

현재 `main` 트리에서는 operator_guide RAG 본체 파일이 남아 있지 않고, Sellform 환경 변수 호환 흔적만 남아 있다.

- `backend/src/config.py`
  - `SELLFORM_RAG_DEBUG_ENABLED`
  - `SELLFORM_RAG_RUNTIME_MOCK`
  - 하위 호환 alias: `FACTORY_RAG_DEBUG_ENABLED`, `FACTORY_RAG_RUNTIME_MOCK`
- `backend/src/api/pages.py`
- `backend/src/services/page_generator.py`
- `backend/src/services/planning_draft_service.py`

현재 트리에서 `pgvector` 전용 모델, chunk 저장 테이블, RAG document ingestion 수량 집계 코드는 확인되지 않았다.

### 3. process_optimizer 수치 확인

검색한 키워드:

- `process_optimizer`
- `ProcessOptimizer`
- `30 nodes`
- `5 operations`
- `82 tests`
- `Quest Agent`
- `Material Generation Agent`

현재 저장소와 Git 전체 이력에서 위 키워드에 대한 구현 근거는 발견되지 않았다.

현재 확인 가능한 에이전트 그래프는 Sellform 상세페이지 생성용 11-node 구조다.

- `backend/src/agents/graph.py`
  - `InputRouterAgent`
  - `SourceCollectionAgent`
  - `ProductUnderstandingAgent`
  - `ReferenceAnalysisAgent`
  - `SalesStrategyAgent`
  - `PagePlanningAgent`
  - `CopywritingAgent`
  - `VisualPlanningAgent`
  - `ImageGenerationAgent`
  - `PageAssemblyAgent`
  - `QAReviewAgent`

따라서 `process_optimizer: node 30개, operation 5개, test 82개`는 현재 저장소만으로 최종 수치라고 말할 수 없다.

## 테스트 수치 확인

현재 트리에서 정적으로 집계한 테스트 수는 다음과 같다.

| 영역 | 정적 집계 방식 | 결과 |
| --- | --- | --- |
| Backend pytest | `backend/tests`의 `def test_`, `async def test_` | 417개 |
| Frontend Playwright e2e | `frontend/e2e`의 `test(` | 41개 |
| Integrations JS tests | `integrations`의 `test(` | 18개 |

이 값은 "현재 저장소에 정의된 테스트 함수/케이스의 정적 개수"이며, 실제 실행 결과의 passed 수와는 다를 수 있다. `259 tests passed`가 어떤 범위의 실행 결과였는지는 현재 저장소 로그만으로 확인되지 않는다.

## 답변에 안전하게 쓸 수 있는 문장

아래 문장은 현재 저장소 근거 기준으로 안전하다.

> operator_guide RAG Sprint 10에서는 RAG 디버그 API, pgvector 기반 검색 wiring, runtime mock 격리, DB URL fallback 문제를 다뤘습니다. 다만 현재 저장소에 남아 있는 증적만으로는 실제 RAG 문서 개수와 pgvector chunk 총량을 확정할 수 없습니다.

> 현재 저장소에서 확인되는 에이전트 그래프는 Sellform 상세페이지 생성용 11-node 구조이며, `process_optimizer`의 30-node/5-operation/82-test 수치는 이 저장소에서는 확인되지 않았습니다.

> `259 tests passed`는 현재 저장소에서 출처가 확인되지 않았으므로 operator_guide 전체 테스트인지 Factory-Space 전체 테스트인지 단정하지 않는 것이 안전합니다. 해당 수치를 쓰려면 당시 pytest 로그 또는 CI 실행 링크가 필요합니다.

> Quest Agent와 Material Generation Agent의 구현 소유권은 현재 저장소 이력에서 확인되지 않아, 본인 구현 또는 팀원 구현으로 단정하기 어렵습니다.

## 추가로 필요하면 확인할 자료

정확한 수치를 확정하려면 아래 자료가 필요하다.

- `feature/operator-guide-rag-sprint10` 브랜치의 원본 코드
- RAG ingestion 실행 로그
- pgvector DB dump 또는 `SELECT count(*) FROM ...` 결과
- 당시 CI/pytest 로그
- Factory-Space 저장소 원본 또는 해당 모듈이 들어 있던 별도 저장소
- Quest Agent / Material Generation Agent 작업 PR, 커밋, 이슈 담당자 기록

## 이번 확인에 사용한 명령

```powershell
rg -n "operator_guide|RAG|pgvector|chunk|process_optimizer|Quest Agent|Material Generation|259 tests|259 passed" backend docs -g "!backend/uv.lock"
rg -n "process_optimizer|ProcessOptimizer|operator guide|operator-guide|operator_guide|pgvector|82 tests|30 nodes|5 operations|259" -S . -g "!backend/uv.lock" -g "!node_modules" -g "!.next"
git grep -n -i "process_optimizer\|operator_guide\|pgvector\|quest agent\|material generation\|259 tests\|259 passed\|82 tests\|30 nodes\|5 operations" $(git rev-list --all) -- . ":!backend/uv.lock"
rg -n "^def test_|^async def test_" backend/tests -g "*.py"
rg -n "\btest\(" frontend/e2e -g "*.ts"
rg -n "\btest\(" integrations -g "*.ts" -g "*.mjs"
```
