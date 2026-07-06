# Sprint 66 AI 문구 수정 품질 강화 기획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** AI 문구 수정 버튼을 눌렀을 때 `[AI 수정됨]` 같은 내부 문구가 나오지 않고, 제목과 본문이 버튼 의도에 맞게 자연스럽게 바뀌게 만든다.

**아키텍처:** `CopyRewriteService`에서 명령별 rewrite contract를 강화하고, sanitizer/post-processor로 부자연스러운 기호와 내부 마커를 제거한다. 프론트엔드는 비교 모달에서 실제 수정 전/후 차이를 보여주고, 적용 시 page PATCH만 수행한다.

**기술 스택:** FastAPI, Pydantic, LLM router, Next.js, pytest, Playwright E2E

---

## 1. 현재 문제

- `더위엔 ‘바람+냉각’—콘센트 없이 휴대해서 시원하게` 같은 제목이 부자연스럽다.
- 수정안이 거의 바뀌지 않는다.
- `[AI 수정됨]` 같은 내부 문구가 본문에 들어갈 수 있다.
- mock/fallback 문구 일부가 깨진 문자열로 남아 있다.

---

## 2. 구현 범위

백엔드:

- `backend/src/services/copy_rewrite_service.py`
- `backend/src/services/llm_router.py`
- `backend/src/api/pages.py`
- `backend/tests/test_copy_rewrite_service.py`
- `backend/tests/test_ai_edit_command_api.py`

프론트엔드:

- `frontend/src/components/AiEditCommandPanel.tsx`
- `frontend/src/components/CopyRewriteComparison.tsx`
- `frontend/e2e/review-editor-reframe.spec.ts`

---

## 3. 문구 규칙

공통 금지:

- `[AI 수정됨]`
- `제목을 더 강하게 바꿔줘:`
- `AI가 수정했습니다`
- 실제 제품명/브랜드가 아닌 `+`
- 한국어 제목 안의 `—`
- 근거 없는 `최고`, `완벽`, `100%`, `즉시`, `무조건`

권장 표현:

```text
바람+냉각—콘센트 없이
```

대신:

```text
바람과 냉각감을 더해, 콘센트 없이도 시원하게
```

---

## 4. 버튼별 rewrite contract

| 버튼 | title 변경 | body 변경 | 기준 |
| --- | --- | --- | --- |
| 제목 강화 | 필수 | 선택 | 제목이 더 구체적이고 구매 이유가 보여야 함 |
| 짧고 자연스럽게 | 필수 | 필수 | 중복 단어와 군더더기 제거 |
| 과장 표현 축소 | 선택 | 필수 | 근거 없는 강한 표현 제거 |
| 사용 장면 보강 | 선택 | 필수 | 방, 침대 옆, 차량, 캠핑 등 맥락 추가 |
| 초보 셀러 톤 | 필수 | 필수 | 쉬운 단어, 짧은 문장 |
| 구매 불안 감소 | 선택 | 필수 | 구매 전 확인사항 추가 |
| 직접 요청 | 요청에 따름 | 요청에 따름 | 사용자 지시를 grounding 안에서 반영 |

---

## 5. 작업 계획

### Task 1 — 깨진 mock/fallback 문구 교체

- [ ] `copy_rewrite_service.py`의 `_MOCK_RESULTS`를 정상 한글로 교체한다.
- [ ] 모든 command의 `change_summary`를 정상 한글로 교체한다.

예시:

```python
CopyRewriteCommand.STRONGER_HEADLINE: {
    "title": "콘센트 없이도, 더운 순간 바로 시원하게",
    "body_copy": "방, 책상, 차량, 캠핑처럼 전원 연결이 번거로운 곳에서도 가볍게 사용할 수 있습니다.",
    "change_summary": "제목을 더 구체적이고 구매 상황이 보이도록 강화했습니다.",
}
```

### Task 2 — copy sanitizer 추가

- [ ] `sanitize_rewrite_output()` 함수를 만든다.
- [ ] 내부 마커를 제거한다.
- [ ] `+`, `—`를 자연스러운 표현으로 바꾼다.
- [ ] 금지된 과장 표현을 제거하거나 완화한다.

테스트:

```python
def test_sanitizer_removes_internal_markers_and_symbols():
    result = sanitize_rewrite_output("[AI 수정됨] 바람+냉각—콘센트 없이")
    assert "[AI 수정됨]" not in result
    assert "+" not in result
    assert "—" not in result
```

### Task 3 — 명령별 변화량 테스트 추가

- [ ] `stronger_headline`은 제목이 반드시 바뀌는지 확인한다.
- [ ] `shorter_natural`은 제목과 본문이 모두 바뀌는지 확인한다.
- [ ] `usage_context`는 본문에 사용 장면이 추가되는지 확인한다.
- [ ] 모든 결과에 `[AI 수정됨]`, `+`, `—`가 없는지 확인한다.

실행:

```bash
uv run --project backend pytest backend/tests/test_copy_rewrite_service.py -q
```

### Task 4 — real mode prompt 강화

- [ ] system prompt에 금지 기호와 내부 마커 금지 규칙을 추가한다.
- [ ] user prompt에 command별 목표를 더 구체적으로 넣는다.
- [ ] LLM 결과에도 sanitizer를 통과시킨다.

### Task 5 — 비교 모달 E2E 강화

- [ ] 비교 모달이 뜨는지 확인한다.
- [ ] 수정 후 title/body가 실제로 달라지는지 확인한다.
- [ ] 적용 후 PATCH payload에 새 title/body가 들어가는지 확인한다.
- [ ] 화면에 `[AI 수정됨]`이 0개인지 확인한다.

실행:

```bash
npx.cmd playwright test e2e/review-editor-reframe.spec.ts --project=chromium --reporter=line
```

---

## 6. 완료 기준

- `[AI 수정됨]`이 어디에도 출력되지 않는다.
- 제목에 부자연스러운 `+`, `—`가 나오지 않는다.
- 버튼별 수정 의도가 결과에 보인다.
- 비교 모달에서 수정 전/후 차이가 명확하다.
- backend copy rewrite 테스트 통과.
- review editor E2E 통과.

