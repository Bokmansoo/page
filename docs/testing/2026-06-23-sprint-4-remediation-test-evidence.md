# 테스트 증적: Sellform Sprint 4 Remediation

## 1. RED 확인

명령:

```bash
cd backend
uv run --project . pytest tests/test_pages_sprint4_remediation.py -q
```

결과:

```text
4 failed
```

실패 사유:

- `regenerate` API: `NameError: name 'settings' is not defined`
- workspace 격리: 다른 workspace 요청이 `200 OK`로 통과
- 버전 목록 API: `404 Not Found`
- 섹션 추가 API: `404 Not Found`

## 2. GREEN 확인

명령:

```bash
cd backend
uv run --project . pytest tests/test_pages_sprint4_remediation.py -q
```

결과:

```text
4 passed, 35 warnings
```

## 3. Page API 회귀 테스트

명령:

```bash
cd backend
uv run --project . pytest tests/test_pages.py tests/test_pages_sprint4_remediation.py -q
```

결과:

```text
7 passed, 59 warnings
```

## 4. 전체 백엔드 테스트

명령:

```bash
cd backend
uv run --project . pytest -q
```

결과:

```text
40 passed, 126 warnings
```

## 5. 프론트엔드 빌드

명령:

```bash
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
Linting and checking validity of types passed
```
