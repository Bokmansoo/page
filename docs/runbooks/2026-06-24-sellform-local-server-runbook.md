# Sellform 로컬 서버 실행 Runbook

이 문서는 노트북 재부팅 후 Sellform을 다시 실행할 때 사용하는 로컬 개발 서버 실행 절차다. 특히 `localhost:3000` 화면에서 `Failed to fetch`, `FastAPI 백엔드가 구동 중인지 확인해 주세요`, `22220` 같은 포트/PID 문제가 반복될 때 이 문서를 기준으로 확인한다.

## 한 줄 결론

백엔드는 `uv run ...` 대신 프로젝트 루트의 `run_backend.ps1`로 실행한다.

```powershell
cd C:\page
.\run_backend.ps1
```

프론트엔드는 별도 터미널에서 실행한다.

```cmd
cd C:\page\frontend
npm.cmd run dev
```

`next dev`가 `spawn EPERM`으로 실패하면 빌드 후 실행한다.

```cmd
cd C:\page\frontend
npm.cmd run start:fresh
```

## 왜 `run_backend.ps1`을 쓰는가

이 프로젝트에서는 기존 `backend/sellform_dev.db`가 오래된 스키마와 SQLite journal 문제를 가지고 있었다. 그래서 백엔드를 아무 생각 없이 실행하면 예전 DB를 물고 다음 문제가 발생할 수 있다.

- 백엔드 프로세스는 떠 있는데 API가 500을 반환한다.
- 브라우저에는 `Failed to fetch`가 표시된다.
- `localhost:8000/docs`는 열리지만 `/api/v1/projects` 또는 `/api/v1/operations/stats`가 실패한다.
- `22220` 같은 PID가 8000 포트를 계속 잡는 것처럼 보인다.

`run_backend.ps1`은 검증된 기본값을 사용한다.

- 실행 파일: `backend\.venv\Scripts\uvicorn.exe`
- 기본 DB: `sqlite:///./sellform_run.db`
- 기본 주소: `http://127.0.0.1:8000`
- 8000 포트가 이미 사용 중이면 실행하지 않고 어떤 PID가 잡고 있는지 알려준다.

## 정상 실행 절차

### 1. 백엔드 포트 확인

CMD에서 확인한다.

```cmd
netstat -ano | findstr :8000
```

아무것도 출력되지 않으면 8000 포트가 비어 있는 상태다.

출력이 있다면 예를 들어 이런 형태다.

```text
TCP    127.0.0.1:8000    0.0.0.0:0    LISTENING    22220
```

맨 오른쪽 숫자가 PID다. 위 예시에서는 `22220`이다.

### 2. 8000 포트를 잡은 프로세스 종료

CMD에서 실행한다.

```cmd
taskkill /PID 22220 /F
```

PID가 다르면 숫자만 바꾼다.

```cmd
taskkill /PID 나온PID /F
```

만약 이렇게 나온다면:

```text
오류: 프로세스 "22220"을(를) 찾을 수 없습니다.
```

그 PID는 이미 종료된 것이다. 다시 포트를 확인한다.

```cmd
netstat -ano | findstr :8000
```

계속 `Access denied`가 나오면 일반 CMD가 아니라 관리자 권한 CMD 또는 관리자 PowerShell에서 같은 명령을 실행한다.

### 3. 백엔드 실행

PowerShell에서 실행한다.

```powershell
cd C:\page
.\run_backend.ps1
```

CMD에서 PowerShell 스크립트를 실행하려면 이렇게 실행한다.

```cmd
cd C:\page
powershell -ExecutionPolicy Bypass -File .\run_backend.ps1
```

정상적으로 실행되면 다음과 비슷하게 나온다.

```text
Starting Sellform backend
  URL:      http://127.0.0.1:8000
  Database: sqlite:///./sellform_run.db
```

이 터미널은 닫지 않는다. 백엔드 서버가 실행 중인 터미널이다.

### 4. 백엔드 정상 확인

브라우저에서 확인한다.

```text
http://127.0.0.1:8000/docs
```

또는 CMD/PowerShell에서 포트를 확인한다.

```cmd
netstat -ano | findstr :8000
```

`LISTENING`이 보이면 백엔드가 떠 있는 것이다.

### 5. 프론트엔드 실행

새 터미널을 열고 실행한다.

```cmd
cd C:\page\frontend
npm.cmd run dev
```

브라우저에서 접속한다.

```text
http://localhost:3000/workspace
```

프론트가 `spawn EPERM`으로 실패하면 다음 방식으로 실행한다.

```cmd
cd C:\page\frontend
npm.cmd run start:fresh
```

## 자주 보는 문제와 해결

### `taskkill /PID 33276 /F` 했는데 프로세스를 찾을 수 없다고 나온다

문제가 아니다. 해당 PID는 이미 종료된 것이다.

다시 현재 포트 상태를 확인한다.

```cmd
netstat -ano | findstr :8000
```

아무것도 나오지 않으면 백엔드를 실행하면 된다.

```cmd
cd C:\page
powershell -ExecutionPolicy Bypass -File .\run_backend.ps1
```

### 계속 `22220`이 보인다

`22220`은 고정된 버그 번호가 아니라 Windows 프로세스 ID다. 매번 달라질 수 있다.

중요한 것은 오른쪽 PID가 무엇이든 8000 포트를 잡고 있으면 백엔드 새 실행이 막힌다는 점이다.

```cmd
netstat -ano | findstr :8000
taskkill /PID 나온PID /F
```

### `Access denied`가 나온다

해당 프로세스가 관리자 권한 또는 다른 권한으로 실행된 상태일 수 있다.

1. 관리자 권한으로 CMD 또는 PowerShell을 연다.
2. 다시 종료한다.

```cmd
taskkill /PID 나온PID /F
```

### 화면에 `Failed to fetch`가 뜬다

먼저 백엔드 API가 실제로 살아있는지 확인한다.

```text
http://127.0.0.1:8000/docs
```

`/docs`는 열리는데 화면이 실패하면 다음 API가 200인지 확인한다.

```text
http://127.0.0.1:8000/api/v1/projects
http://127.0.0.1:8000/api/v1/operations/stats
```

둘 중 하나가 500이면 백엔드가 잘못된 DB나 오래된 프로세스로 떠 있을 가능성이 높다. 포트를 종료한 뒤 `run_backend.ps1`로 다시 실행한다.

### `uv run uvicorn ...`으로 실행해도 되나?

현재 로컬에서는 권장하지 않는다.

이유:

- `uv`가 다른 Python 버전으로 실행될 수 있다.
- 기존 `sellform_dev.db`를 물고 실행될 수 있다.
- SQLite journal 문제가 다시 나타날 수 있다.

백엔드는 아래 방식으로 통일한다.

```powershell
cd C:\page
.\run_backend.ps1
```

### 프로젝트 목록이 비어 있다

`sellform_run.db`는 깨끗한 로컬 실행 DB라 데이터가 비어 있을 수 있다. 화면에서 새 상품 프로젝트를 만들거나, 운영 리포트 화면의 Mock 시딩 기능을 사용한다.

## 빠른 재시작 체크리스트

1. 8000 포트 확인

   ```cmd
   netstat -ano | findstr :8000
   ```

2. 포트를 잡은 PID 종료

   ```cmd
   taskkill /PID 나온PID /F
   ```

3. 백엔드 실행

   ```cmd
   cd C:\page
   powershell -ExecutionPolicy Bypass -File .\run_backend.ps1
   ```

4. 프론트 실행

   ```cmd
   cd C:\page\frontend
   npm.cmd run dev
   ```

5. 브라우저 접속

   ```text
   http://localhost:3000/workspace
   ```

## PostgreSQL 운영/구독형 환경 설정 (Sprint 18)

운영 및 구독형 서비스를 대비하여 PostgreSQL 런타임을 구성하는 절차입니다. 

1. **Docker 데이터베이스 구동**
   프로젝트 루트에서 Docker Compose를 사용하여 PostgreSQL 컨테이너를 실행합니다.
   ```powershell
   docker compose up -d db
   ```
   *참고: 포트 충돌이 나는 경우 `docker-compose.yml`에서 포트 바인딩 설정을 점검하십시오.*

2. **환경 변수 (.env) 설정**
   `C:\page\.env` 파일 내에 `DATABASE_URL`을 SQLite 대신 PostgreSQL 주소(충돌 방지를 위해 5434 포트 권장)로 설정합니다.
   ```env
   DATABASE_URL=postgresql://sellform:sellformpassword@localhost:5434/sellform_dev
   ```

3. **테이블 스키마 생성 및 연동 검증**
   백엔드가 실행되면 SQLAlchemy 모델을 기반으로 PostgreSQL에 테이블이 자동 생성됩니다. 무결성을 검증하기 위해 아래 테스트 명령어로 검증해볼 수 있습니다.
   ```powershell
   $env:DATABASE_URL="postgresql://sellform:sellformpassword@localhost:5434/sellform_dev"
   uv run --project backend pytest backend/tests/test_facts.py -q
   ```

## 로컬 AI Key 환경 변수 설정 (Sprint 16)

로컬 개발 환경에서 실제 AI 기능(OpenAI API)을 사용하여 사실 카드를 생성하려면 API 키 설정이 필요합니다.

1. `C:\page\.env` 파일을 생성합니다.
2. 아래와 같이 API 키 값을 설정합니다.
   ```env
   OPENAI_API_KEY=sk-...
   OPENAI_FACT_MODEL=gpt-4o-mini
   AI_FACT_EXTRACTION_TIMEOUT_SECONDS=30
   AI_FACT_EXTRACTION_MAX_FACTS=20
   ```
3. API 키를 설정한 뒤 백엔드를 재시작해야 합니다.
4. **주의:** API 키가 포함된 `.env` 파일은 절대 Git에 커밋하지 않아야 합니다. `.gitignore`에 이미 등록되어 있는지 재차 확인하십시오.

## 관련 파일

- `run_backend.ps1`
- `backend/src/config.py`
- `backend/src/db/database.py`
- `backend/sellform_run.db`
- `backend/sellform_dev.db` — 과거 개발 DB. 현재 로컬 실행 기본값으로 사용하지 않는다.
# CMD 실행 바로가기 (2026-06-24)

CMD를 선호하면 프로젝트 루트에서 아래 명령만 실행한다.

```cmd
cd /d C:\page
run_backend.cmd
```

`run_backend.cmd`는 `run_backend.ps1`을 호출하는 래퍼다. 따라서 포트 충돌 확인, 프로젝트 전용 가상환경 사용, `sellform_run.db` 지정 같은 기존 안전장치를 그대로 적용한다.
