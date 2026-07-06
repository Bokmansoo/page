# Sellform Figma MCP CMD 실행 가이드

## 1. 준비 상태

루트 `C:\page\.env`에 다음 항목이 설정되어 있어야 한다.

```dotenv
SELLFORM_FIGMA_MCP_ENABLED=true
SELLFORM_FIGMA_BRIDGE_HOST=127.0.0.1
SELLFORM_FIGMA_BRIDGE_PORT=3417
SELLFORM_FIGMA_BRIDGE_TOKEN=<긴 임의 문자열>
SELLFORM_FIGMA_BRIDGE_URL=http://127.0.0.1:3417
SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS=120
SELLFORM_FIGMA_MCP_URL=https://mcp.figma.com/mcp
SELLFORM_FIGMA_OAUTH_REDIRECT_URI=http://127.0.0.1:3417/oauth/callback
SELLFORM_FIGMA_OAUTH_STORE_PATH=.sellform/figma-oauth.json
```

실제 토큰 값은 문서나 Git에 복사하지 않는다. 현재 `.env`와 `.sellform/`은
`.gitignore`로 제외되어 있다.

## 2. 최초 한 번만 설치

CMD를 열고 실행한다.

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd install
```

## 3. 매번 실행할 서버

총 네 개의 CMD 창을 사용한다.

### CMD 1 — PostgreSQL

```cmd
cd C:\page
docker compose up -d db
docker compose ps
```

`sellform-postgres`가 `Running` 또는 `Up`이면 정상이다.

### CMD 2 — FastAPI 백엔드

```cmd
cd C:\page
run_backend.cmd
```

확인 주소:

```text
http://127.0.0.1:8000/health
```

### CMD 3 — Figma MCP Bridge

```cmd
cd C:\page\integrations\figma-bridge
npm.cmd start
```

확인 주소:

```text
http://127.0.0.1:3417/health
```

정상이면 다음과 비슷한 JSON이 표시된다.

```json
{"status":"healthy","service":"Figma Bridge Express"}
```

### CMD 4 — Next.js 프론트엔드

```cmd
cd C:\page\frontend
npm.cmd run dev
```

접속 주소:

```text
http://localhost:3000/workspace
```

## 4. 실제 Figma 내보내기

1. Figma에서 새 Design 파일을 만들거나 편집 가능한 기존 파일을 연다.
2. `https://www.figma.com/design/...` 형태의 주소를 복사한다.
3. Sellform 프로젝트의 상세페이지 편집 화면을 연다.
4. `Figma로 내보내기`를 누른다.
5. 복사한 Design URL을 입력하고 `Figma 내보내기 시작`을 누른다.
6. 처음 연결이면 `Figma 인증하기`를 누른다.
7. Figma에서 권한을 승인한다.
8. Sellform으로 돌아와 `인증 후 재시도`를 누른다.
9. 완료되면 `Figma에서 확인하기`로 실제 생성 프레임을 연다.

Figma MCP는 새 Figma 파일을 자동 생성하지 않는다. 사용자가 지정한 편집 가능한
Design 파일 안에 Sellform 상세페이지 프레임과 텍스트 노드를 만든다.

## 5. 이미지가 안 들어갈 때

Figma Remote MCP는 `localhost`의 이미지를 읽을 수 없다. 이미지 URL은 인증 없이
열리는 공개 HTTPS 주소여야 하며 파일당 10MB 이하여야 한다.

공개 이미지 호스트가 준비되면 `.env`에 다음 값을 추가한다.

```dotenv
SELLFORM_PUBLIC_ASSET_BASE_URL=https://your-public-image-host.example
```

이미지 호스트가 아직 없다면 프레임과 텍스트 생성부터 검증하고, 이미지 검증은 이후에
진행한다. Figma 내보내기가 실패해도 Sellform의 PNG 내보내기는 계속 사용할 수 있다.

## 6. 종료 방법

백엔드, 브리지, 프론트 CMD 창에서 각각 `Ctrl+C`를 누른다.

PostgreSQL까지 종료하려면 별도 CMD에서 실행한다.

```cmd
cd C:\page
docker compose stop db
```

## 7. 자주 발생하는 오류

### 포트 3417 사용 중

```cmd
netstat -ano | findstr :3417
```

LISTENING 행의 PID를 확인한 뒤, 본인이 실행한 이전 Figma Bridge 프로세스가 맞을 때만
종료한다.

```cmd
taskkill /PID 확인한_PID /F
```

### `BRIDGE_NOT_CONFIGURED`

`.env`에 `SELLFORM_FIGMA_BRIDGE_TOKEN`이 설정되어 있는지 확인하고 백엔드와 브리지를
모두 다시 시작한다.

### `AUTH_REQUIRED`

화면에 표시된 `Figma 인증하기` 링크로 승인한 뒤 `인증 후 재시도`를 누른다.

### `ASSET_URL_NOT_PUBLIC`

이미지가 공개 HTTPS 주소가 아니거나 10MB를 초과했다. 공개 이미지 호스트 설정을
확인한다.
