# 셀폼(Sellform) 스프린트 1 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** 사용자, 워크스페이스, 브랜드, 상품 프로젝트, 파일 저장소 및 백그라운드 작업 상태 관리를 아우르는 프로젝트 작업대의 안전한 구현.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- `backend/pyproject.toml`: 백엔드 의존성 및 패키지 정의
- `backend/src/config.py`: 환경변수 관리
- `backend/src/db/database.py`: SQLAlchemy 엔진 및 세션 관리
- `backend/src/db/models.py`: DB 스키마 모델 정의
- `backend/src/services/validation.py`: SSRF 및 안전 업로드 비즈니스 로직
- `backend/src/api/auth.py`: Mock 인증 및 테넌트 컨텍스트 주입 디펜던시
- `backend/src/api/projects.py`: 프로젝트 CRUD 및 자동저장 API
- `backend/src/api/files.py`: 파일 업로드 및 자산 관리 API
- `backend/src/app.py`: FastAPI 엔트리포인트 및 라우터 매핑

### 1.2 프론트엔드 구조 (`frontend/`)
- `frontend/package.json`: 프론트엔드 의존성
- `frontend/src/styles/index.css`: 디자인 시스템 및 CSS 변수 선언
- `frontend/src/app/layout.tsx`: 루트 레이아웃 (Outfit 폰트, 다크모드/글라스모피즘 기본 테마)
- `frontend/src/app/page.tsx`: 엔트리 자동 라우팅
- `frontend/src/app/workspace/layout.tsx`: 브랜드/프로젝트 공통 내비게이션 레이아웃
- `frontend/src/app/workspace/page.tsx`: 상품 프로젝트 관리 대시보드
- `frontend/src/app/workspace/projects/new/page.tsx`: 새 상품 생성 마법사 (수동 전환 포함)

---

## 2. 데이터 모델 (PostgreSQL 스키마)

### 2.1 테이블 정의 (SQLAlchemy 명세)
- **`users`**: `id` (UUID, PK), `email` (String, Unique), `name` (String)
- **`workspaces`**: `id` (UUID, PK), `name` (String), `owner_id` (UUID, FK -> `users.id`)
- **`brands`**: `id` (UUID, PK), `workspace_id` (UUID, FK -> `workspaces.id`), `name` (String), `logo_url` (String, Nullable), `brand_colors` (JSON), `font_tone` (String), `default_disclaimer` (Text, Nullable)
- **`product_projects`**: `id` (UUID, PK), `workspace_id` (UUID, FK -> `workspaces.id`), `brand_id` (UUID, FK -> `brands.id`), `name` (String), `status` (String: draft, processing, checking, ready), `current_step` (String), `raw_input_url` (String, Nullable), `raw_input_text` (Text, Nullable), `created_at` (DateTime), `updated_at` (DateTime)
- **`assets`**: `id` (UUID, PK), `project_id` (UUID, FK -> `product_projects.id`), `source_type` (String: sourced, self_shot, ai_corrected), `filename` (String), `file_path` (String), `mime_type` (String), `file_size` (Integer), `created_at` (DateTime)
- **`audit_logs`**: `id` (UUID, PK), `workspace_id` (UUID, FK -> `workspaces.id`), `user_id` (UUID, FK -> `users.id`), `action` (String), `entity_type` (String), `entity_id` (UUID), `payload` (JSON), `created_at` (DateTime)
- **`job_statuses`**: `id` (UUID, PK), `project_id` (UUID, FK -> `product_projects.id`), `status` (String: pending, running, completed, failed), `error_message` (Text, Nullable), `updated_at` (DateTime)

---

## 3. API 계약 (API Contract)

### 3.1 프로젝트 관리
- **프로젝트 생성**: `POST /api/v1/projects`
  - 요청: `{ "brand_id": "UUID", "name": "string", "raw_input_url": "string?", "raw_input_text": "string?" }`
  - 응답 (201): 생성된 `ProductProject` JSON 객체
- **프로젝트 자동 저장 (Patch)**: `PATCH /api/v1/projects/{project_id}`
  - 요청: `{ "name": "string?", "raw_input_text": "string?", "status": "string?" }`
  - 응답 (200): 업데이트된 `ProductProject` 객체
- **프로젝트 목록 조회**: `GET /api/v1/projects`
  - 응답 (200): `[{ ... }]` (현재 활성 Workspace 하위의 프로젝트 목록)

### 3.2 안전성 및 파일 업로드
- **외부 링크 검증**: `POST /api/v1/links/validate`
  - 요청: `{ "url": "string" }`
  - 응답 (200): `{ "valid": true, "resolved_ip": "string" }`
  - 응답 (400): `{ "valid": false, "reason": "SSRF_ATTEMPT_DETECTED | RESOLVE_FAILED" }`
- **보안 파일 업로드**: `POST /api/v1/files/upload`
  - 요청: Multipart Form 데이터 (`file` 파라미터)
  - 응답 (201): `{ "asset_id": "UUID", "file_path": "string" }`
  - 응답 (400): `{ "reason": "FILE_TOO_LARGE | INVALID_FILE_TYPE" }`

---

## 4. 테스트 케이스 및 실행 명령

### 4.1 백엔드 단위 테스트
1. **SSRF 방지 테스트**: `backend/tests/test_validation.py`
   - Local IP 대역 (`127.0.0.1`, `192.168.1.100`, `10.0.0.1`), Multicast 대역 및 불완전 도메인 입력을 대상으로 400 에러 및 차단 응답이 정상적으로 반환되는지 테스트.
2. **테넌트(워크스페이스) 격리 테스트**: `backend/tests/test_projects.py`
   - 서로 다른 `X-Mock-Workspace-Id` 헤더를 전송하여 생성한 프로젝트가 타 워크스페이스 조회 시 노출되지 않는지 권한 경계 검증.

### 4.2 실행 명령
```bash
# PostgreSQL & Redis 구동
docker-compose up -d

# 백엔드 의존성 및 서버 구동 (SQLite 폴백 모드 시 Compose 생략 가능)
cd backend
uv run uvicorn src.main:app --reload --port 8000

# 프론트엔드 개발서버 구동
cd ../frontend
npm.cmd run dev
```

---

## 5. 완료 기준 (Definition of Done)

1. **테넌트 격리 작동**: 사용자 1명이 활성화된 워크스페이스/브랜드 경계 밖의 프로젝트에 접근할 수 없다.
2. **안전성 확보**: 허용되지 않은 파일 형식이나 사설 대역 URL 입력 시 명확한 이유를 제시하며 안전하게 차단된다.
3. **사용자 복구 흐름**: 외부 주소 검증 오류 또는 크롤링 실패 시 상품 마법사가 멈추지 않고 수동 등록(사진 업로드 및 글 수동 입력) 인터페이스로 상태가 전환된다.
4. **리뷰 증적**: 신규 추가되는 코드 및 API 명세에 대해 `docs/reviews/`에 코드 리뷰 문서를 작성하고 승인받는다.
