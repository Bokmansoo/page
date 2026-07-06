# 테스트 로그: Sellform Sprint 5

## 1. Sprint 5 export 단위 테스트

명령:

```bash
cd backend
uv run --project . pytest tests/test_exports.py -q
```

결과:

```text
2 passed, 18 warnings
```

검증 범위:

- compliance API가 Blocker 이슈를 감지하는지 확인
- Blocker가 있을 때 export 요청이 `400 Bad Request`로 차단되는지 확인
- Warning만 있을 때 export 요청이 `202 Accepted`로 시작되는지 확인
- background export 작업이 `completed` 상태가 되는지 확인
- ZIP asset과 output image 목록이 생성되는지 확인
- ZIP 다운로드 API가 `application/zip`으로 응답하는지 확인

## 2. 전체 백엔드 회귀 테스트

명령:

```bash
cd backend
uv run --project . pytest -q
```

결과:

```text
42 passed, 139 warnings
```

## 3. 프론트엔드 빌드

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

## 4. 주의 사항

- pytest를 여러 프로세스로 병렬 실행하면 현재 SQLite 파일 기반 fixture가 `test_temp.db`를 동시에 생성/삭제해 `no such table` 오류를 만들 수 있다.
- Sprint 5 검증은 순차 실행 기준으로 통과했다.
