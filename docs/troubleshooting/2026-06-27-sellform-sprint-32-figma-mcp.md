# Sprint 32 Figma MCP 트러블슈팅

## 버튼은 성공했지만 Figma 파일이 생성되지 않음

Sprint 32 기본 상태는 payload 생성 전용이다. 응답이 `ready`이고 `mcp_status`가 `disabled` 또는 `not_configured`라면 정상적으로 payload만 준비된 상태다.

실제 파일 생성에는 Figma MCP sender 연결이 추가로 필요하다.

## 이미지가 Figma에서 보이지 않음

`SELLFORM_PUBLIC_ASSET_BASE_URL`이 `localhost`이면 외부 Figma 서비스가 접근할 수 없다. 운영 환경에서는 HTTPS로 접근 가능한 CDN 또는 asset origin을 설정한다.

## API 테스트가 404를 반환함

FastAPI 라우터가 등록될 때 `get_db` dependency callable이 캡처되므로 함수 이름을 patch하는 것만으로는 테스트 DB가 교체되지 않는다.

다음 방식으로 오버라이드한다.

```python
app.dependency_overrides[get_db] = lambda: mock_db
```

테스트 종료 후 `app.dependency_overrides.clear()`를 호출한다.

## 프론트 빌드에서 `setLoadingBg`가 없다고 나옴

배경 후보 로딩 상태인 `loadingBg`, `setLoadingBg` 선언이 누락된 상태다. page-editor state에 해당 boolean 상태가 선언되어 있어야 한다.

## Playwright가 `Timed out waiting 120000ms from config.webServer`로 종료됨

### 증상

3000번 포트에 기존 Next.js 개발 서버가 실행 중이면 Playwright가 해당 서버를 재사용하지 못한 상태에서 같은 포트로 새 서버를 시작하려다 타임아웃될 수 있다.

### 근본 원인

개발 서버와 E2E 서버가 모두 3000번 포트를 고정 사용했다.

### 해결

`frontend/playwright.config.ts`의 기본 E2E 포트를 3100번으로 분리했다. 다른 포트가 필요하면 CMD에서 다음과 같이 실행한다.

```cmd
cd C:\page\frontend
set SELLFORM_E2E_PORT=3200
npm.cmd run test:e2e -- sprint32-figma-export.spec.ts
```

기존 3000번 개발 서버를 종료하지 않아도 E2E를 실행할 수 있다.
