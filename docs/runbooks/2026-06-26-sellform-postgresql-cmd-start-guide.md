# Sellform PostgreSQL CMD 실행 가이드

이 문서는 Windows CMD에서 Sellform을 **PostgreSQL 기준**으로 실행하는 방법이다.

SQLite는 임시 fallback 용도이고, 실제 개발/검증은 PostgreSQL 기준으로 진행한다.

## 1. PostgreSQL 실행

CMD 1번 창:

```cmd
cd /d C:\page
docker compose up -d db
```

정상 실행 확인:

```cmd
docker ps
```

`sellform-postgres`가 보이고 `5434->5432` 포트 매핑이 보이면 정상이다.

## 2. 백엔드 실행

같은 CMD 창 또는 새 CMD 창에서:

```cmd
cd /d C:\page
run_backend.cmd
```

정상 로그:

```text
Starting Sellform backend
URL:      http://127.0.0.1:8000
Database: postgresql://sellform:sellformpassword@localhost:5434/sellform_dev
```

중요: 여기서 `sqlite:///./sellform_run.db`가 보이면 PostgreSQL 기준 실행이 아니다.

## 3. 프론트엔드 실행

CMD 2번 창:

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

브라우저 접속:

```text
http://localhost:3000/workspace
```

## 4. 자주 나는 문제

### PostgreSQL 연결 실패

아래 메시지가 나오면 DB 컨테이너가 꺼져 있는 것이다.

```text
PostgreSQL is not reachable on localhost:5434.
```

해결:

```cmd
cd /d C:\page
docker compose up -d db
run_backend.cmd
```

### 8000 포트 충돌

확인:

```cmd
netstat -ano | findstr :8000
```

종료:

```cmd
taskkill /PID <PID> /F
```

그 후:

```cmd
run_backend.cmd
```

## 5. 임시 SQLite fallback

PostgreSQL/Docker가 당장 안 될 때만 임시로 쓴다.

```cmd
cd /d C:\page
run_backend.cmd -UseSqlite
```

주의: Sprint 구현 검증과 실제 사용 흐름은 PostgreSQL 기준으로 확인한다.

