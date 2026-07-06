# Sellform CMD 기준 로컬 서버 실행 가이드

이 문서는 Windows **CMD 기준**으로 Sellform 로컬 개발 서버를 켜는 방법을 정리한다.

PowerShell 명령이 헷갈릴 때는 이 문서만 보면 된다.

## 1. 실행해야 하는 서버

Sellform을 로컬에서 쓰려면 보통 서버를 2개 켠다.

| 구분 | 역할 | 주소 | 실행 위치 |
| --- | --- | --- | --- |
| 백엔드 | FastAPI API 서버 | `http://localhost:8000` | `C:\page` |
| 프론트엔드 | Next.js 홈페이지 | `http://localhost:3000` | `C:\page\frontend` |

브라우저로 접속하는 곳은 프론트엔드 주소다.

```text
http://localhost:3000/workspace
```

## 2. 백엔드 실행하기

CMD 창을 하나 열고 아래 순서대로 입력한다.

```cmd
cd /d C:\page
run_backend.cmd
```

정상 실행되면 대략 이런 의미의 로그가 나온다.

```text
Starting Sellform backend
URL:      http://127.0.0.1:8000
Database: sqlite:///./sellform_run.db
```

이 CMD 창은 백엔드 서버용 창이므로 닫지 말고 그대로 둔다.

## 3. 프론트엔드 실행하기

CMD 창을 하나 더 열고 아래 순서대로 입력한다.

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

정상 실행되면 브라우저에서 아래 주소로 접속한다.

```text
http://localhost:3000/workspace
```

## 4. 실행 확인하기

### 백엔드 확인

브라우저에서 아래 주소를 열어본다.

```text
http://localhost:8000/docs
```

FastAPI 문서 화면이 뜨면 백엔드는 켜진 것이다.

CMD에서 확인하고 싶으면 아래 명령을 쓴다.

```cmd
curl http://localhost:8000/api/v1/projects
```

응답이 JSON 형태로 오면 정상이다.

### 프론트엔드 확인

브라우저에서 아래 주소를 연다.

```text
http://localhost:3000/workspace
```

Sellform 대시보드가 뜨면 프론트엔드는 켜진 것이다.

## 5. 자주 나는 문제

### 화면에 `Failed to fetch`가 뜰 때

대부분 백엔드가 꺼져 있거나 `8000` 포트가 정상 연결되지 않은 상태다.

먼저 백엔드 CMD 창이 살아 있는지 확인한다.

그다음 아래 주소가 열리는지 확인한다.

```text
http://localhost:8000/docs
```

안 열리면 백엔드를 다시 실행한다.

```cmd
cd /d C:\page
run_backend.cmd
```

만약 백엔드는 켜져 있는데 특정 프로젝트 화면만 `데이터 로딩 에러 / Failed to fetch`가 뜬다면, 로컬 SQLite DB 스키마가 최신 코드보다 오래된 상태일 수 있다.

이 경우 백엔드 CMD 창에서 `Ctrl + C`로 서버를 끈 뒤 다시 실행한다.

```cmd
cd /d C:\page
run_backend.cmd
```

Sellform 백엔드는 시작할 때 로컬 SQLite에 필요한 누락 컬럼을 자동 보정한다.

### `Port 8000 is already in use`가 뜰 때

이미 8000번 포트를 쓰는 프로세스가 있다는 뜻이다.

CMD에서 확인한다.

```cmd
netstat -ano | findstr :8000
```

예시:

```text
TCP    127.0.0.1:8000    0.0.0.0:0    LISTENING    12345
```

맨 오른쪽 숫자 `12345`가 PID다.

종료해도 되는 Sellform/uvicorn/python 프로세스가 맞다면 아래처럼 종료한다.

```cmd
taskkill /PID 12345 /F
```

그 후 다시 백엔드를 실행한다.

```cmd
run_backend.cmd
```

주의: PID가 매번 달라지므로 문서의 숫자를 그대로 쓰면 안 된다. `netstat`로 나온 숫자를 사용해야 한다.

### `taskkill` 했는데 프로세스를 찾을 수 없다고 나올 때

그 PID는 이미 종료된 상태일 가능성이 높다.

다시 확인한다.

```cmd
netstat -ano | findstr :8000
```

아무것도 안 나오면 8000번 포트는 비어 있는 상태다.

그냥 다시 실행하면 된다.

```cmd
run_backend.cmd
```

## 6. 서버 끄는 방법

각 CMD 창에서 `Ctrl + C`를 누른다.

질문이 나오면 `Y`를 입력하고 Enter를 누른다.

```text
Terminate batch job (Y/N)? Y
```

## 7. 개발 서버 말고 빌드된 프론트엔드로 실행하고 싶을 때

일반 개발 중에는 `npm.cmd run dev`를 쓰면 된다.

빌드된 상태로 확인하고 싶을 때만 아래를 쓴다.

```cmd
cd /d C:\page\frontend
npm.cmd run start:fresh
```

이 경우에도 브라우저 접속 주소는 보통 같다.

```text
http://localhost:3000/workspace
```

## 8. 가장 짧은 실행 요약

CMD 1번 창:

```cmd
cd /d C:\page
run_backend.cmd
```

CMD 2번 창:

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

브라우저:

```text
http://localhost:3000/workspace
```
# Sellform CMD 기준 로컬 서버 실행 가이드 - PostgreSQL 기준

현재 Sellform의 기본 로컬 실행 DB는 **PostgreSQL**이다. SQLite는 임시 fallback 용도로만 사용한다.

아래 순서대로 실행한다.

## 빠른 실행 요약

CMD 1번 창:

```cmd
cd /d C:\page
docker compose up -d db
run_backend.cmd
```

CMD 2번 창:

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

브라우저:

```text
http://localhost:3000/workspace
```

정상 백엔드 로그는 PostgreSQL 주소를 보여야 한다.

```text
Database: postgresql://sellform:sellformpassword@localhost:5434/sellform_dev
```

만약 아래처럼 SQLite가 보이면 예전 실행 방식이거나 임시 fallback으로 실행된 것이다.

```text
Database: sqlite:///./sellform_run.db
```

## PostgreSQL이 안 켜졌을 때

백엔드 실행 중 아래 메시지가 나오면 PostgreSQL 컨테이너가 꺼져 있는 상태다.

```text
PostgreSQL is not reachable on localhost:5434.
```

이때는 먼저 DB를 켠다.

```cmd
cd /d C:\page
docker compose up -d db
```

그 다음 백엔드를 다시 켠다.

```cmd
run_backend.cmd
```

## 임시로 SQLite를 써야 할 때

기본은 PostgreSQL이다. Docker/PostgreSQL이 안 될 때만 임시로 SQLite fallback을 쓴다.

```cmd
cd /d C:\page
run_backend.cmd -UseSqlite
```

주의: Sprint 구현 검증과 실제 사용 흐름은 PostgreSQL 기준으로 확인한다.

---
