# Sprint 32 Figma MCP 테스트 로그

## TDD RED

초기 전용 테스트 결과:

```text
4 failed, 2 passed
```

실패 원인:

- 공개 asset base URL을 주입할 수 없음
- 활성화 상태에서 실제 sender 없이 전송 성공을 반환함
- sender 주입 인터페이스 없음
- API가 MCP 비활성 상태를 payload 미준비로 표시함

## 백엔드 전용 테스트

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_figma_design_payload_builder.py backend\tests\test_figma_mcp_adapter.py backend\tests\test_figma_export_api.py -q --basetemp=.pytest-tmp-sprint32-green1
```

결과:

```text
8 passed
```

2026-06-28 보완에서 다른 workspace의 프로젝트를 Figma payload로 내보낼 수 없는 권한 회귀 테스트를 추가했다.

## 백엔드 전체 회귀

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q --basetemp=.pytest-tmp-sprint32-full-green
```

결과:

```text
138 passed
```

## 프론트 빌드

```cmd
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
Generating static pages (9/9)
```

`<img>` 사용에 관한 Next.js 성능 경고 1건은 남아 있으나 빌드 실패는 아니다.

## 브라우저 회귀 테스트

추가 파일:

`frontend/e2e/sprint32-figma-export.spec.ts`

기존 개발 서버가 사용하는 3000번 포트와 충돌하지 않도록 Playwright 기본 포트를 3100번으로 분리했다. 필요하면 `SELLFORM_E2E_PORT` 환경변수로 변경할 수 있다.

```cmd
cd C:\page\frontend
npm.cmd run test:e2e -- sprint32-figma-export.spec.ts --output=test-results-sprint32-remediation
```

결과:

```text
1 passed
```

## 2026-06-28 보완 검증

- workspace 권한 회귀: `3 passed`
- 백엔드 전체 회귀: `138 passed`
- 프론트 프로덕션 빌드: 성공
- Sprint 32 Playwright: `1 passed`
- 남은 비차단 경고: `<img>` 사용에 관한 Next.js 성능 경고 1건
