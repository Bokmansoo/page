# Sellform 현재 서버 실행 가이드

이 문서는 현재 `C:\page` 기준으로 Sellform 로컬 개발 서버를 실행하는 최소 명령어를 정리한다.

## 한 번에 보는 실행 순서

CMD 창을 각각 따로 열어서 아래 순서대로 실행한다.

### 1. PostgreSQL 실행

```cmd
cd /d C:\page
docker compose up -d db
docker compose ps
```

`sellform-postgres`가 `Running` 또는 `Up`이면 정상이다.

### 2. 백엔드 실행

```cmd
cd /d C:\page
run_backend.cmd
```

정상 실행되면 아래 주소에서 FastAPI 문서를 확인할 수 있다.

```text
http://127.0.0.1:8000/docs
```

현재 백엔드 실행 스크립트는 내부적으로 다음 앱을 실행한다.

```cmd
C:\page\backend\.venv\Scripts\uvicorn.exe src.app:app --host 127.0.0.1 --port 8000
```

### 3. 프론트엔드 실행

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

브라우저에서 아래 주소로 접속한다.

```text
http://localhost:3000/workspace
```

## 선택 실행: Figma Plugin

Figma 플러그인을 함께 테스트할 때만 실행한다.

### 최초 1회 또는 manifest가 없을 때

```cmd
cd /d C:\page\integrations\figma-plugin
npm.cmd run configure -- <실제_figma_plugin_id>
```

`<실제_figma_plugin_id>`에는 Figma 개발 플러그인의 숫자 ID를 넣는다. 예시처럼 `<...>`를 그대로 입력하면 CMD에서 구문 오류가 날 수 있다.

### 플러그인 빌드

```cmd
cd /d C:\page\integrations\figma-plugin
npm.cmd run build
```

Figma Desktop에서는 `manifest.json`을 다시 import하거나, 이미 등록되어 있으면 플러그인을 다시 실행한다.

## 선택 실행: Figma MCP Bridge

Figma MCP 내보내기 흐름까지 확인할 때만 실행한다.

```cmd
cd /d C:\page\integrations\figma-bridge
npm.cmd start
```

확인 주소:

```text
http://127.0.0.1:3417/health
```

이 기능을 쓰려면 `C:\page\.env`에 아래 값들이 맞게 들어 있어야 한다.

```dotenv
SELLFORM_FIGMA_MCP_ENABLED=true
SELLFORM_FIGMA_BRIDGE_URL=http://127.0.0.1:3417
SELLFORM_FIGMA_BRIDGE_TOKEN=<32자 이상 임의 문자열>
SELLFORM_FIGMA_OAUTH_REDIRECT_URI=http://127.0.0.1:3417/oauth/callback
```

## 포트 충돌 확인

### 백엔드 8000 포트

```cmd
netstat -ano | findstr :8000
```

종료해도 되는 Sellform 백엔드 프로세스가 맞으면 PID를 확인한 뒤 종료한다.

```cmd
taskkill /PID <PID> /F
```

### 프론트엔드 3000 포트

```cmd
netstat -ano | findstr :3000
```

종료해도 되는 Next.js 프로세스가 맞으면 종료한다.

```cmd
taskkill /PID <PID> /F
```

### Figma Bridge 3417 포트

```cmd
netstat -ano | findstr :3417
```

필요하면 같은 방식으로 PID를 종료한다.

## 자주 보는 문제

### `PostgreSQL is not reachable on localhost:5434`

DB가 꺼져 있는 상태다.

```cmd
cd /d C:\page
docker compose up -d db
```

그 다음 백엔드를 다시 실행한다.

```cmd
run_backend.cmd
```

### 프론트에서 `Failed to fetch`

대부분 백엔드가 꺼져 있거나 `8000` 포트가 다른 프로세스에 잡힌 상태다.

1. `http://127.0.0.1:8000/docs`가 열리는지 확인한다.
2. 안 열리면 `C:\page`에서 `run_backend.cmd`를 다시 실행한다.
3. 포트 충돌 메시지가 나오면 `netstat -ano | findstr :8000`으로 PID를 확인한다.

### Figma Plugin에서 실행 에러

1. `C:\page\integrations\figma-plugin\manifest.json`이 있는지 확인한다.
2. 없으면 `npm.cmd run configure -- <실제_figma_plugin_id>`를 다시 실행한다.
3. `npm.cmd run build`를 실행한다.
4. Figma Desktop에서 플러그인을 다시 import하거나 다시 실행한다.
5. 백엔드 `http://127.0.0.1:8000/docs`가 열리는지 확인한다.

## API 크레딧 주의

서버를 켜는 것만으로는 OpenAI/Gemini/Anthropic API 크레딧이 사용되지 않는다.

다만 `.env`에 실제 API 키가 들어 있고, 화면에서 AI 분석, LLM 문구 생성, 이미지 생성 같은 기능을 직접 실행하면 해당 provider의 크레딧이 사용될 수 있다.

테스트나 UI 확인만 할 때 비용 사용을 피하려면 실제 API 키를 비워두거나 deterministic/mock 경로를 사용한다.

## 종료 방법

백엔드, 프론트엔드, Figma Bridge CMD 창에서 각각 `Ctrl + C`를 누른다.

PostgreSQL까지 끄려면 아래 명령을 실행한다.

```cmd
cd /d C:\page
docker compose stop db
```

## 프로덕션 빌드로 프론트엔드 확인

일반 개발은 위의 `npm.cmd run dev`를 사용한다. 프로덕션 빌드를 확인할 때는 실행 중인
3000번 포트의 기존 Next.js 프로세스를 먼저 종료한 뒤 다음 명령 하나만 사용한다.

```cmd
cd /d C:\page\frontend
npm.cmd run start:fresh
```

`start:fresh`는 새 빌드를 만든 다음 빌드에
`/workspace/projects/[id]/result` 라우트가 포함됐는지, 프론트엔드 소스가 빌드보다
새롭지 않은지 검사하고 `next start`를 실행한다. 기존 빌드를 그대로 실행하는
`npm.cmd run start`도 같은 검사를 통과해야만 서버를 시작한다.

결과 라우트 확인:

```cmd
curl.exe -I http://127.0.0.1:3000/workspace/projects/route-probe/result
```

HTTP `200`이면 실행 중인 프로덕션 빌드에 결과 라우트가 포함된 상태다.
