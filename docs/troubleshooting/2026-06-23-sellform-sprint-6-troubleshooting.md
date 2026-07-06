# 트러블슈팅: Sellform Sprint 6

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | 공개 페이지 발행, 테스트 DB 충돌, 이미지 갤러리, 문구 깨짐 |

## 1. 병렬 pytest 실행 시 SQLite 테이블 없음 오류

### 증상

`tests/test_publications.py`와 전체 pytest를 동시에 실행했을 때 다음 오류가 발생했다.

```text
sqlite3.OperationalError: no such table: product_projects
sqlite3.OperationalError: no such table: users
```

### 원인

두 pytest 프로세스가 같은 `backend/test_temp.db` 파일을 동시에 생성/삭제하면서 충돌했다.

### 조치

검증은 순차 실행 기준으로 확정했다.

```bash
uv run --project . pytest tests/test_publications.py -q
uv run --project . pytest -q
```

두 명령 모두 순차 실행에서는 통과한다.

## 2. 이미지 갤러리 자산 누락

### 증상

Sprint 6 계획에는 공개 페이지 이미지 갤러리가 포함되어 있었지만, 공개 조회 API는 섹션과 Before/After에 쓰인 자산만 반환했다.

### 조치

`PublishedPage.project_id` 기준으로 프로젝트 전체 `Asset` 목록을 조회해 `assets` 맵에 포함하도록 보완했다.

## 3. 공개 페이지 사용자 문구 깨짐

### 증상

`/p/[id]`와 발행 관리 화면의 한국어 문구가 깨져 실제 고객용 페이지로 쓰기 어려웠다.

### 조치

두 프론트 화면의 사용자 문구를 정상 한국어로 정리하고, 갤러리 fallback, 구매 링크 없음 안내, 비공개 페이지 안내 문구를 추가했다.

## 4. 남은 예방 작업

- 병렬 테스트를 공식 지원하려면 worker별 SQLite DB 경로를 분리한다.
- 운영 배포 전 `/uploads` 정적 파일 서빙 또는 S3/CDN 공개 URL 정책을 확정한다.
