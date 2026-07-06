# Sellform LangGraph 도입 판단 기록

| 항목 | 내용 |
| --- | --- |
| 결정 일자 | 2026-06-24 |
| 주제 | Sellform 상세페이지 생성 구조에 LangGraph/LangChain을 도입할지 여부 |
| 현재 결정 | 지금은 도입하지 않고, FastAPI 서비스 파이프라인 + LLM Router 구조를 유지한다. |

## 1. 현재 구조

현재 Sellform은 LangGraph/LangChain 기반 에이전트 구조가 아니라 다음에 가까운 서비스 파이프라인 구조다.

```text
상품 링크/이미지/텍스트 입력
→ source collection
→ AI fact extraction
→ fact verification
→ category/style/template selection
→ page generation
→ review
→ version/export
```

이 구조는 아직 각 단계의 입출력이 비교적 명확하고, 사용자가 중간중간 검수하는 흐름이 중요하다.

## 2. 지금 LangGraph를 바로 쓰지 않는 이유

지금 단계에서는 LangGraph를 도입하면 다음 비용이 생긴다.

- 상태 그래프, 노드, 엣지, checkpoint 설계가 필요해진다.
- 단순 API 호출보다 디버깅 난도가 올라간다.
- 현재 필요한 것은 “복잡한 자율 에이전트”보다 “검수 가능한 상세페이지 제작 파이프라인”에 가깝다.
- Sprint 18의 LLM Router만으로도 OpenAI → Google → deterministic fallback 흐름은 충분히 구현 가능하다.

따라서 지금은 굳이 LangGraph가 없어도 된다.

## 3. 나중에 LangGraph가 좋아지는 조건

다음 조건이 2개 이상 충족되면 LangGraph 도입을 검토한다.

1. URL 수집, 이미지 OCR, 사실 추출, 규정 검수, 카피 생성, 디자인 생성이 서로 재시도/분기/중단/재개를 자주 요구한다.
2. 사용자가 “이 단계만 다시 실행”하거나 “실패한 노드부터 재개”하기를 원한다.
3. 상품 10~100개를 배치로 처리하면서 단계별 상태 추적이 필요해진다.
4. LLM provider, OCR provider, browser collector, Figma MCP, Google Drive MCP 같은 도구가 여러 개 연결된다.
5. 한 프로젝트 안에서 여러 agent 역할이 명확해진다.

예:

```text
Research Agent
→ Fact Extraction Agent
→ Compliance Review Agent
→ Copywriting Agent
→ Design Strategy Agent
→ Export QA Agent
```

이 정도로 역할이 나뉘면 LangGraph가 의미 있어진다.

## 4. 추천 로드맵

현재:

```text
FastAPI service pipeline
```

Sprint 18:

```text
FastAPI service pipeline
+ LLM Router
+ PostgreSQL runtime option
```

Sprint 19~21:

```text
Style strategy selection
+ grounded generation validation
+ version/export
```

추후 고도화:

```text
Workflow state machine
→ LangGraph proof of concept
→ agent workflow migration
```

## 5. 결론

지금은 LangGraph를 쓰지 않는 것이 좋다.

다만 Sellform이 외부 셀러용 구독형 서비스로 확장되고, 여러 도구와 agent가 복잡하게 협업하는 단계가 오면 LangGraph 도입 가치가 커진다.

즉, 현재 판단은 다음과 같다.

```text
지금은 LLM Router.
나중에 복잡한 워크플로우가 실제로 생기면 LangGraph.
```
