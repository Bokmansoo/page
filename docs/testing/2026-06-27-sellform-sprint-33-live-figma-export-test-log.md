# Sprint 33 공식 Figma MCP 보완 테스트 로그

| 항목 | 내용 |
| --- | --- |
| 실행 일자 | 2026-06-28 |
| 범위 | canonical payload, FastAPI job/API, 공식 MCP bridge, OAuth, 이미지 업로드, 프론트 빌드 |
| 실제 Figma 계정 검수 | 미실행 |

## 1. 백엔드 전체 회귀

```cmd
cd C:\page\backend
uv run pytest tests -q --basetemp=.pytest-tmp-sprint33-remediation
```

결과:

```text
152 passed, 663 warnings in 10.05s
```

경고는 기존 Starlette/httpx, Pydantic V2, `datetime.utcnow()`,
`google.generativeai` 사용 중단 예고다. Sprint 33 실패는 없다.

## 2. Figma 백엔드 집중 검증

```cmd
cd C:\page\backend
uv run pytest tests/test_figma_design_payload_builder.py tests/test_figma_bridge_client.py tests/test_figma_export_job_service.py tests/test_figma_live_export_api.py tests/test_figma_mcp_adapter.py -q
```

결과:

```text
19 passed, 68 warnings in 1.39s
```

검증 항목:

- canonical payload `schema_version=1.0`
- `authenticating → rendering → completed` 상태 전이
- API가 받은 실제 `auth_url` 보존
- 완료 작업 재시도 409
- 실패 작업만 재시도
- 완료 응답에 실제 결과 URL이 없으면 실패
- payload-only 어댑터의 `not_configured` fallback

## 3. 공식 MCP Bridge 단위·통합 테스트

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd test -- --runInBand
```

결과:

```text
Test Suites: 3 passed, 3 total
Tests:       16 passed, 16 total
```

검증 항목:

- Streamable HTTP 및 `use_figma`/`upload_assets` 도구 계약
- canonical payload 변환
- 실제 root/image-slot node ID 파싱
- 가짜 node ID 성공 처리 차단
- 이미지 다운로드 → upload URL 전송
- OAuth state 누락 거부 및 `finishAuth`
- 빈 bridge token fail-closed
- localhost/file 이미지 차단

## 4. Bridge TypeScript 빌드

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd run build
```

결과: 성공 (`tsc`, 오류 0건).

## 5. 프론트엔드 프로덕션 빌드

```cmd
cd C:\page\frontend
npm.cmd run build
```

결과: 성공. 타입·린트·정적 페이지 생성 완료.

알려진 비차단 경고:

```text
page-editor/page.tsx:972 @next/next/no-img-element
```

## 6. Playwright와 실제 Figma 검수 상태

Sprint 32/33 Playwright 재실행은 이번 세션의 브라우저 프로세스 실행 승인이 사용량
제한으로 거부되어 수행하지 못했다. 테스트 파일에는 다음 회귀 항목을 추가·유지했다.

- 잘못된 Design URL은 API를 호출하지 않음
- 성공 폴링 및 실제 result node URL 표시
- API가 반환한 OAuth URL만 표시
- 인증 후 재시도
- Sprint 32 payload-only 요청 유지

따라서 현재 결론은 자동 단위·통합·빌드 검증 완료, 브라우저 E2E 재실행과 실제 Figma
계정/파일 검수 대기다. 실제 승인 전에 아래를 실행한다.

```cmd
cd C:\page\frontend
npx.cmd playwright test e2e/sprint32-figma-export.spec.ts e2e/sprint33-live-figma-export.spec.ts --reporter=list
```
