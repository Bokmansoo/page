# Sellform PostgreSQL Only CMD 실행 가이드

Sellform 로컬 실행 DB는 **PostgreSQL만 사용**한다.

SQLite fallback은 사용하지 않는다.

## 실행 순서

CMD 1번 창:

```cmd
cd /d C:\page
docker compose up -d db
run_backend.cmd
```

정상 백엔드 로그:

```text
Starting Sellform backend
URL:      http://127.0.0.1:8000
Database: postgresql://sellform:sellformpassword@localhost:5434/sellform_dev
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

## PostgreSQL이 안 켜졌을 때

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

## 8000 포트 충돌

확인:

```cmd
netstat -ano | findstr :8000
```

종료:

```cmd
taskkill /PID <PID> /F
```

다시 실행:

```cmd
run_backend.cmd
```

## 서버 끄기

백엔드/프론트 CMD 창에서 각각 `Ctrl + C`를 누른다.

PostgreSQL 컨테이너까지 끄려면:

```cmd
cd /d C:\page
docker compose down
```

DB 데이터까지 완전히 삭제하려면:

```cmd
docker compose down -v
```

주의: `-v`는 PostgreSQL 데이터도 삭제한다.

