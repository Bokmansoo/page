# Sprint 33 Figma Live 내보내기 트러블슈팅

## `BRIDGE_NOT_CONFIGURED`

`SELLFORM_FIGMA_BRIDGE_TOKEN`이 비어 있다. 루트 `.env`에 긴 임의 토큰을 설정하고
백엔드와 브리지를 모두 재시작한다. 토큰이 없으면 브리지는 의도적으로 503을 반환한다.

## `BRIDGE_UNAUTHORIZED`

백엔드가 보내는 `X-Sellform-Bridge-Token`과 브리지 설정값이 다르다. 동일한 루트
`.env`를 읽는지 확인하고 두 프로세스를 재시작한다.

## `AUTH_REQUIRED`

Figma OAuth 승인이 아직 없거나 만료됐다.

1. 화면의 `Figma 인증하기` 링크를 연다.
2. Figma 권한을 승인한다.
3. 원래 화면에서 `인증 후 재시도`를 누른다.

주소창에 임의 OAuth URL을 만들지 않는다. `auth_url`은 상태 API가 반환한 값만 사용한다.
콜백에서 `state`가 없거나 일치하지 않으면 브리지가 요청을 거부한다.

## `MCP_TOOL_UNSUPPORTED`

공식 Remote MCP가 필수 `use_figma` 도구를 제공하지 않았다. Remote MCP 주소가
`https://mcp.figma.com/mcp`인지 확인하고 브리지를 최신 의존성으로 다시 빌드한다.

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd install
npm.cmd run build
```

## `IMAGE_UPLOAD_UNSUPPORTED`

상세페이지에 이미지 컷이 있지만 MCP 세션에 `upload_assets`가 없다. 이미지 없는
payload로 재시도하거나 Figma 권한·도구 제공 상태를 확인한다. 성공으로 위장하지 않고
PNG 내보내기를 대안으로 사용한다.

## `ASSET_URL_NOT_PUBLIC`

이미지 URL이 localhost, 로컬 파일, 비공개 주소이거나 10MB를 초과했다.

- `SELLFORM_PUBLIC_ASSET_BASE_URL`을 공개 HTTPS 호스트로 설정한다.
- URL을 시크릿 브라우저에서 인증 없이 열 수 있는지 확인한다.
- 이미지 한 장을 10MB 이하로 줄인다.

## `INVALID_MCP_RESPONSE`

Figma가 실제 생성 노드 ID 또는 이미지 슬롯 ID를 반환하지 않았다. 이 경우 Sellform은
`0-1` 같은 가짜 노드로 완료 처리하지 않는다. 브리지 로그를 확인하고 재시도한다.

## `INVALID_FIGMA_URL`

입력값이 `https://www.figma.com/design/FILE_KEY/...` 형식인지 확인한다. FigJam,
프로토타입 공유 단축 URL, HTTP URL은 허용하지 않는다.

## 2분 후 타임아웃

화면 폴링은 2분 후 중단된다. 상태가 계속 진행 중이면 브리지 로그와 네트워크를 확인한
뒤 재시도한다. 편집 작업과 PNG 내보내기는 계속 사용할 수 있다.

## 기본 진단 명령

```cmd
curl http://127.0.0.1:3417/health
netstat -ano | findstr :3417
docker compose ps
```

브리지 단위·통합 검증:

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd test -- --runInBand
npm.cmd run build
```
