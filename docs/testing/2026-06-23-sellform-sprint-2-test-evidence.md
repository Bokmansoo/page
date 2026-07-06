# 테스트 로그: Sellform Sprint 2

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | Sprint 2 사실 검증 보드, 사실 CRUD API, 변경 이력, 필터링, 프론트 빌드 |
| 목적 | Sprint 2 기획서의 완료 기준이 실제 코드와 테스트로 충족되는지 확인 |

---

## 1. RED 단계

```bash
cd backend
uv run --project . pytest tests/test_facts.py -q
```

결과:

```text
2 failed, 4 passed
```

확인한 실패:

- 잘못된 상태값 `approved`가 거부되지 않고 200으로 처리됨.
- 다른 프로젝트에 속한 `source_asset_id`가 사실 카드 근거로 연결됨.

---

## 2. GREEN 단계

```bash
cd backend
uv run --project . pytest tests/test_facts.py -q
```

결과:

```text
6 passed, 41 warnings
```

---

## 3. Sprint 2 관련 회귀 테스트

```bash
cd backend
uv run --project . pytest tests/test_projects.py tests/test_facts.py -q
```

결과:

```text
9 passed, 53 warnings
```

비고:

- 경고는 기존 `StarletteDeprecationWarning`, `google.generativeai` package deprecation, `datetime.utcnow()` deprecation 계열이다.
- Sprint 2 기능 실패 또는 테스트 실패는 없음.

---

## 4. 전체 백엔드 테스트 참고 결과

```bash
cd backend
uv run --project . pytest -q
```

결과:

```text
5 failed, 24 passed, 46 warnings
```

분리 판단:

- `test_compliance.py` 3건은 Sprint 2 사실 검증 보드 범위 밖의 규칙 엔진 기대값 불일치다.
- 전체 suite 순서에서 `test_facts.py` DB 격리 실패 2건이 관찰되었지만, `test_facts.py` 단독 및 `test_projects.py + test_facts.py` 묶음은 통과한다.

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

비고:

- 최종 빌드에서는 Sprint 2 사실 검증 보드 관련 lint/type 경고 없이 통과했다.
