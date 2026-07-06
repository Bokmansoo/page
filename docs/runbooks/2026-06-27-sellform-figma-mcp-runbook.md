# Sellform 공식 Figma Remote MCP 실행 가이드

## 목적

Sellform 상세페이지를 편집 가능한 Figma 프레임으로 내보내는 Sprint 33 운영 절차다.
연동은 FastAPI → 로컬 Figma Bridge → 공식 Figma Remote MCP 순서로 동작한다.

- Remote MCP 주소: `https://mcp.figma.com/mcp`
- 전송 방식: Streamable HTTP
- 필수 도구: `use_figma`
- 이미지가 있는 경우: `upload_assets`
- 브리지 바인딩: `127.0.0.1:3417`

PNG 내보내기는 Figma 장애와 무관하게 계속 사용할 수 있다.

## 사전 조건

1. Figma 계정에 대상 Design 파일의 편집 권한이 있어야 한다.
2. Figma Dev Mode의 쓰기 기능을 사용할 수 있는 Full seat가 필요하다.
3. 이미지가 포함된 상세페이지는 브리지가 접근 가능한 공개 HTTPS 이미지 URL을 사용해야 한다.
4. Node.js 의존성을 설치한다.

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd install
```

## 환경 변수

루트 `C:\page\.env`에 다음 값을 설정한다. 토큰은 충분히 긴 임의 문자열로 만들고
백엔드와 브리지가 동일한 값을 읽게 한다.

```dotenv
SELLFORM_FIGMA_MCP_ENABLED=true
SELLFORM_FIGMA_BRIDGE_HOST=127.0.0.1
SELLFORM_FIGMA_BRIDGE_PORT=3417
SELLFORM_FIGMA_BRIDGE_URL=http://127.0.0.1:3417
SELLFORM_FIGMA_BRIDGE_TOKEN=replace-with-a-long-random-token
SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS=120
SELLFORM_FIGMA_MCP_URL=https://mcp.figma.com/mcp
SELLFORM_FIGMA_OAUTH_REDIRECT_URI=http://127.0.0.1:3417/oauth/callback
SELLFORM_FIGMA_OAUTH_STORE_PATH=.sellform/figma-oauth.json
SELLFORM_PUBLIC_ASSET_BASE_URL=https://your-public-asset-host.example
```

`.sellform/figma-oauth.json`에는 OAuth 상태와 토큰이 저장되므로 Git에 올리지 않는다.
현재 `.gitignore`에 해당 경로가 등록되어 있다.

## 실행 순서

터미널 1:

```cmd
cd C:\page
docker compose up -d db
run_backend.cmd
```

터미널 2:

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd start
```

터미널 3:

```cmd
cd C:\page\frontend
npm.cmd run dev
```

브리지 상태 확인:

```cmd
curl http://127.0.0.1:3417/health
```

## 사용 절차

1. `http://localhost:3000/workspace`에서 프로젝트를 연다.
2. 상세페이지 편집 단계에서 `Figma로 내보내기`를 누른다.
3. 편집 가능한 `https://www.figma.com/design/...` URL을 입력한다.
4. 처음 연결이면 API가 반환한 `Figma 인증하기` 링크를 연다.
5. Figma에서 권한을 승인하고 Sellform으로 돌아온다.
6. `인증 후 재시도`를 누른다.
7. 완료 후 `Figma에서 확인하기` 링크로 실제 생성 노드를 확인한다.

OAuth 주소는 브리지가 공식 MCP SDK를 통해 받은 값만 사용한다. Sellform은 임의의
클라이언트 ID나 가짜 토큰을 만들지 않는다.

## 수동 검수 체크리스트

- [ ] 대상 파일에 860px 루트 프레임이 실제로 생성됨
- [ ] 텍스트가 편집 가능한 Figma TextNode임
- [ ] 섹션 순서가 Sellform 상세페이지 순서와 일치함
- [ ] 이미지가 있는 컷은 실제 이미지가 채워짐
- [ ] 완료 링크의 `node-id`가 실제 생성 노드를 가리킴
- [ ] 같은 요청을 반복해 완료 작업이 중복 생성되지 않음
- [ ] Figma 실패 후에도 PNG 내보내기 링크가 동작함

자동화 테스트는 MCP 응답 계약을 모의 검증한다. 실제 Figma 계정과 파일에 노드가
생성되는지 확인하는 위 수동 검수는 릴리스 승인 전에 별도로 수행해야 한다.
