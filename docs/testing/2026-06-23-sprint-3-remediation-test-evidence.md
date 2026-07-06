# 테스트 로그: Sprint 3 보완 구현

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | AI 분석 API 계약, 워크스페이스 격리, 카테고리 확정 API, AI 어댑터, compliance 테스트, 프론트 빌드 |
| 결론 | Sprint 3 보완 범위 통과 |

---

## 1. RED 확인

```bash
cd backend
uv run --project . pytest tests/test_ai_api.py -q
```

초기 결과:

```text
4 failed
```

실패 원인:

- analyze API가 `processing` 대신 `pending` 반환
- 다른 워크스페이스의 프로젝트도 analyze 호출 가능
- 카테고리 확정 API 없음

---

## 2. GREEN 확인

```bash
cd backend
uv run --project . pytest tests/test_ai_api.py -q
```

결과:

```text
4 passed
```

---

## 3. Sprint 3 관련 테스트

```bash
cd backend
uv run --project . pytest tests/test_ai_api.py tests/test_ai_adapter.py tests/test_compliance.py -q
```

결과:

```text
21 passed, 18 warnings
```

---

## 4. 전체 백엔드 회귀 테스트

```bash
cd backend
uv run --project . pytest -q
```

결과:

```text
33 passed, 69 warnings
```

---

## 5. 프론트 빌드

```bash
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
Linting and checking validity of types ...
✓ Generating static pages (7/7)
```

---

## 6. 남은 메모

- 경고는 기존 `StarletteDeprecationWarning`, `google.generativeai` deprecation, `datetime.utcnow()` deprecation 계열이다.
- 이미지 기반 AI 실분석은 후속 스프린트에서 공개 URL/서명 URL/base64 변환 정책과 함께 구현한다.
