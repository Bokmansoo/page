# Sellform 서버 실행 및 LLM 모드 가이드

이 문서는 `C:\page`에서 PostgreSQL, FastAPI 백엔드, Next.js 프론트엔드를
실행하고 Sprint 51 텍스트 생성 파이프라인의 Mock/Real 모드를 확인하는 방법을
정리한다.

## 이전 실행 방법과 달라진 점

서버를 켜는 명령과 포트는 이전과 같다.

| 구성 요소 | 실행 위치 | 포트 |
| --- | --- | --- |
| PostgreSQL | Docker Compose | `5544` |
| FastAPI 백엔드 | `C:\page` | `8000` |
| Next.js 프론트엔드 | `C:\page\frontend` | `3000` |

Sprint 51 이후 달라진 부분은 다음과 같다.

- 상세페이지 생성 화면은 `/api/agent-runs/{id}/run`을 호출한다.
- 백엔드의 `SELLFORM_GENERATION_MODE`가 Mock 또는 Real provider를 선택한다.
- 기본값은 `mock`이므로 서버 실행과 일반 UI 확인만으로 API 크레딧이 사용되지 않는다.
- 백엔드 상태 확인 주소는 `/health`가 아니라 `/` 또는 `/docs`다.

## 가장 안전한 Mock 모드 실행

실제 LLM API를 호출하지 않고 UI와 전체 생성 흐름을 확인할 때 사용한다.

### 1. `.env` 확인

`C:\page\.env`에서 다음 값을 사용한다.

```dotenv
SELLFORM_GENERATION_MODE=mock
```

Mock 모드에서는 OpenAI, Gemini, Anthropic API 키가 없어도 된다.

### 2. PostgreSQL 실행

첫 번째 CMD 창에서 실행한다.

```cmd
cd /d C:\page
docker compose up -d db
docker compose ps
```

`sellform-postgres`가 `Up` 또는 `Running`으로 표시되면 정상이다.

### 3. 백엔드 실행

두 번째 CMD 창에서 실행한다.

```cmd
cd /d C:\page
run_backend.cmd
```

`run_backend.cmd`는 내부적으로 다음 명령을 실행한다.

```cmd
C:\page\backend\.venv\Scripts\uvicorn.exe src.app:app --host 127.0.0.1 --port 8001
```

확인 주소:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/docs
```

루트 주소에서는 다음 JSON이 표시된다.

```json
{"status":"running","service":"Sellform Core API"}
```

### 4. 프론트엔드 실행

세 번째 CMD 창에서 실행한다.

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

브라우저에서 다음 주소를 연다.

```text
http://localhost:3000/workspace
```

상품명을 입력하고 `AI 상세페이지 만들기`를 누르면 `/run` 엔드포인트가 호출된다.
Mock 모드에서는 외부 LLM 대신 로컬 Mock provider가 텍스트 결과를 만든다.

## Real LLM 모드 실행

실제 GPT, Gemini 또는 Claude 호출을 확인할 때만 사용한다. 이 모드에서는 provider
정책에 따라 API 크레딧이 사용될 수 있다.

### 1. `.env` 설정

```dotenv
SELLFORM_GENERATION_MODE=real

SELLFORM_TEXT_LLM_PRIMARY_PROVIDER=openai
SELLFORM_TEXT_LLM_PRIMARY_MODEL=gpt-5.4-nano

SELLFORM_TEXT_LLM_FALLBACK1_PROVIDER=gemini
SELLFORM_TEXT_LLM_FALLBACK1_MODEL=gemini-2.5-flash

SELLFORM_TEXT_LLM_FALLBACK2_PROVIDER=claude
SELLFORM_TEXT_LLM_FALLBACK2_MODEL=claude-3-5-sonnet-20241022

SELLFORM_TEXT_LLM_ENABLE_FALLBACKS=true

OPENAI_API_KEY=<실제 OpenAI API 키>
GEMINI_API_KEY=<실제 Gemini API 키>
ANTHROPIC_API_KEY=<실제 Anthropic API 키>
```

실제 키는 문서, 채팅, Git 기록에 남기지 않는다. `.env`를 변경한 뒤에는 백엔드를
반드시 재시작한다.

### 2. 실행 및 확인

PostgreSQL, 백엔드, 프론트엔드 실행 명령은 Mock 모드와 같다. 화면에서 생성을
실행하면 Primary provider를 먼저 호출하고, 실패하면 설정된 순서대로 fallback을
시도한다.

서버를 켜거나 `/workspace`를 여는 것만으로는 크레딧이 사용되지 않는다. Real 모드에서
`AI 상세페이지 만들기`를 눌러 `/run`을 실행할 때 텍스트 API 호출이 발생한다.

## 연결 확인 명령

### 백엔드

```cmd
curl.exe http://127.0.0.1:8000/
```

### FastAPI 문서

```cmd
curl.exe -I http://127.0.0.1:8000/docs
```

### 프론트엔드

```cmd
curl.exe -I http://127.0.0.1:3000/workspace
```

각 요청이 HTTP `200`을 반환하면 연결된 상태다.

## 포트 충돌 확인

```cmd
netstat -ano | findstr :5544
netstat -ano | findstr :8000
netstat -ano | findstr :3000
```

이전에 직접 실행한 Sellform 프로세스가 맞는지 PID를 확인한 뒤에만 종료한다.

```cmd
taskkill /PID <확인한_PID> /F
```

## 문제 해결

### `PostgreSQL is not reachable on localhost:5544`

```cmd
cd /d C:\page
docker compose up -d db
```

DB가 실행된 뒤 `run_backend.cmd`를 다시 실행한다.

### 프론트에서 `Failed to fetch`

1. `http://127.0.0.1:8000/`이 열리는지 확인한다.
2. 백엔드 CMD 창의 오류를 확인한다.
3. `8000` 포트 충돌 여부를 확인한다.
4. `.env` 변경 후 백엔드를 재시작했는지 확인한다.

### Real 모드에서 provider 오류

1. 해당 provider API 키가 `.env`에 있는지 확인한다.
2. provider와 model 이름을 확인한다.
3. fallback을 사용할 경우 `SELLFORM_TEXT_LLM_ENABLE_FALLBACKS=true`인지 확인한다.
4. 비용 사용을 중단하려면 `SELLFORM_GENERATION_MODE=mock`으로 되돌리고 백엔드를
   재시작한다.

## 종료 방법

백엔드와 프론트엔드 CMD 창에서 각각 `Ctrl+C`를 누른다.

PostgreSQL까지 중지하려면 실행한다.

```cmd
cd /d C:\page
docker compose stop db
```

## 프로덕션 빌드 검증 절차

개발 중에는 `npm.cmd run dev`를 사용한다. `next start`로 프로덕션 결과를 확인할 때는
기존 3000번 포트 프로세스를 종료하고 아래 명령으로 빌드와 실행을 한 번에 처리한다.

```cmd
cd /d C:\page\frontend
npm.cmd run start:fresh
```

이 명령은 새 `.next` 빌드를 만든 뒤 결과 라우트 포함 여부와 소스/빌드 시각을 검사한다.
검사에 실패하면 오래된 빌드로 서버를 시작하지 않고 재빌드 명령을 안내한다.

## 2026-07-03 로컬 확인 결과

- PostgreSQL `5544`: 연결됨
- FastAPI `http://127.0.0.1:8000/`: HTTP `200`
- FastAPI 문서 `http://127.0.0.1:8000/docs`: HTTP `200`
- Next.js `http://127.0.0.1:3000/workspace`: HTTP `200`
- 외부 LLM API 호출: 실행하지 않음

## PID가 39324인 프로세스를 강제로 종료합니다. 현재 8001 포트를 점유한 기존 백엔드 서버를 끄는 명령입니다.
taskkill /PID 39324 /F

## 8001 포트를 사용하는 프로세스가 남아 있는지 확인합니다.
netstat -ano | findstr :8001

cd /d C:\page
run_backend.cmd

## 강제로 서버 종료 하는법

for /f "tokens=5" %P in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do taskkill /PID %P /F
