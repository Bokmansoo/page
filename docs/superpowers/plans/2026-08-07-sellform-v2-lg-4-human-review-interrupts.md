# LG-4 — Human-in-the-loop 승인·재개 구현 계획

작성일: 2026-08-07  
상태: 구현 완료 · 회귀 검증 완료

## 목표

LG-3의 Discovery·Commerce Planning 결과를 판매자의 명시적 승인 전에는 다음 단계로 넘기지 않는다. 승인 요청은 단순한 프런트엔드 상태가 아니라 LangGraph의 durable `interrupt()` checkpoint이며, 같은 `AgentRun.id` thread에서만 `Command(resume=...)`로 재개한다.

## 고정 계약

| 대기 단계 | 이전에 완료되어야 하는 작업 | 판매자 승인 뒤 진행 | 승인 전 금지 작업 |
| --- | --- | --- | --- |
| `input_review` | `bootstrap_run` | 자료 수집·상품 이해 | Discovery 전체 |
| `evidence_review` | LG-2 Discovery | 판매 전략·페이지·카피·비주얼 계획 | LG-3 전체 |
| `planning_review` | LG-3 Commerce Planning | 이미지 생성 준비 대기 | 이미지 제공자 호출 |
| `generation_pending` | 스토리보드 승인 | LG-5가 같은 thread에서 인계 | 이미지 제공자 호출·가짜 이미지 생성 |

모든 resume body는 아래 버전 계약을 사용한다.

```json
{
  "thread_id": "AgentRun.id와 같은 값",
  "response": {
    "schema_version": "lg4-v1",
    "review_stage": "planning_review",
    "decision": "approve",
    "comment": "선택 사항"
  }
}
```

`thread_id`가 다른 경우 409으로 거부한다. `generation_pending`은 LG-5 전까지 `defer`만 받고 다시 같은 interrupt를 기록한다. 따라서 API 키·잔액·이미지 제공자가 준비되지 않았을 때 외부 호출은 0회다.

## 구현 범위

1. `SellformGraphState`에 checkpoint-safe review 상태를 추가하고, LG-4 compiled graph를 기본 LangGraph rollout graph로 설정한다.
2. `input_review`, `evidence_review`, `planning_review`, `generation_pending`에서 실제 LangGraph `interrupt()`를 사용한다.
3. interrupt payload와 resume payload를 `lg4-v1` Pydantic 스키마로 검증한다.
4. interrupt를 `AgentRun.status=awaiting_review`, `AgentRunStep.status=awaiting_review`, `outputs_json.langgraph_review.pending`으로 투영한다.
5. `GET /api/v1/graph-runs/projects/{project_id}/review`로 새로고침 후에도 최신 대기 요청을 복원한다.
6. `POST /api/v1/graph-runs/{run_id}/resume`가 versioned body와 동일 thread를 확인한 뒤에만 `Command(resume=...)`를 실행하게 한다.
7. LangGraph runtime으로 새 프로젝트를 만든 경우, 입력 사진 확정 뒤 그래프를 시작하고 planning 화면의 `?runId=`로 이동한다.
8. planning 화면의 스토리보드 승인 버튼은 `planning_review` interrupt의 graph resume을 호출한다. 기존 legacy 프로젝트는 기존 승인 API를 계속 쓴다.
9. LangGraph run이 붙은 planning 화면에서는 기존 직접 이미지 생성 패널을 숨긴다. LG-4의 `generation_pending`을 우회해 provider를 호출하지 않기 위해서다.

## 완료 기준과 테스트

- 승인 전 downstream node가 실행되지 않는다.
- 반려는 동일 interrupt로 다시 대기하고 `AgentRunStep`을 중복 생성하지 않는다.
- 입력·증거·기획 승인 뒤 각각 다음 interrupt가 durable checkpoint로 남는다.
- 브라우저 새로고침 후 project review API가 동일 run·thread·payload를 반환한다.
- 다른 thread ID, 응답 body 누락, 잘못된 stage는 resume할 수 없다.
- `generation_pending`을 반복 재개해도 ImageGenerationJobRecord와 provider dispatch가 생성되지 않는다.
- 기존 LG-2/LG-3 characterization suite는 해당 sprint graph를 명시적으로 선택해 그대로 통과한다.
