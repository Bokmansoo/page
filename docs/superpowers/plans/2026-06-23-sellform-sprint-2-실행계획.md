# 셀폼(Sellform) 스프린트 2 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** 공급처 원본 정보와 업로드 자료를 기반으로 상품 사실 카드를 관리하고, 사용자가 각 사실의 정확성을 직접 비교·수정·확인할 수 있는 "사실 확인 보드"와 변경 이력 관리 체계를 구축합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [MODIFY] `backend/src/db/models.py`: `ProductFact` 및 `FactHistory` 테이블 모델 추가 정의
- [NEW] `backend/src/api/facts.py`: 상품 사실 카드 CRUD, 검증 상태 토글, 변경 이력 조회 API 구현
- [MODIFY] `backend/src/app.py`: `facts` 라우터 등록
- [NEW] `backend/tests/test_facts.py`: 사실 관리 API 및 비즈니스 규칙 테스트

### 1.2 프론트엔드 구조 (`frontend/`)
- [MODIFY] `frontend/src/app/workspace/page.tsx`: 프로젝트 카드 클릭 시 "사실 확인 보드"(`/workspace/projects/[id]/facts`)로 라우팅되도록 수정
- [NEW] `frontend/src/app/workspace/projects/[id]/facts/page.tsx`: "사실 확인 보드" UI 구현 (원본 근거 자료 뷰어 + 한국어 사실 카드 보드, 상태 토글, 수정, 내역 모달, 신규 사실 추가)

---

## 2. 데이터 모델 (PostgreSQL 스키마)

### 2.1 테이블 정의 (SQLAlchemy 명세)

#### **`product_facts`**
- `id` (UUID, PK): 사실 ID
- `project_id` (UUID, FK -> `product_projects.id`, nullable=False): 소속 프로젝트 ID
- `fact_text` (Text, nullable=False): 한글로 정리된 구체적 상품 사실
- `source_text` (Text, nullable=True): 해당 사실의 근거가 된 원본 텍스트/스펙 조각
- `source_asset_id` (UUID, FK -> `assets.id`, nullable=True): 해당 사실의 근거가 된 이미지/자산 ID
- `verification_status` (String(50), default="unknown", nullable=False): 검증 상태 (`confirmed` (확인됨), `needs_revision` (수정 필요), `unknown` (모름))
- `created_at` (DateTime)
- `updated_at` (DateTime)

#### **`fact_histories`**
- `id` (UUID, PK): 이력 ID
- `fact_id` (UUID, FK -> `product_facts.id`, cascade="all, delete-orphan", nullable=False): 대상 사실 ID
- `previous_fact_text` (Text, nullable=False): 변경 전 사실 텍스트
- `previous_source_text` (Text, nullable=True): 변경 전 근거 텍스트
- `previous_source_asset_id` (UUID, FK -> `assets.id`, nullable=True): 변경 전 근거 이미지 ID
- `previous_verification_status` (String(50), nullable=False): 변경 전 상태
- `updated_by` (UUID, FK -> `users.id`, nullable=False): 변경을 가한 사용자 ID
- `updated_at` (DateTime, default=utcnow): 변경 일시

---

## 3. API 계약 (API Contract)

### 3.1 사실 목록 조회
- **요청**: `GET /api/v1/projects/{project_id}/facts?confirmed_only=false`
- **응답 (200)**:
  ```json
  [
    {
      "id": "UUID",
      "project_id": "UUID",
      "fact_text": "본 제품은 100% 면 소재로 제작되었습니다.",
      "source_text": "Material: 100% Cotton",
      "source_asset_id": "UUID | null",
      "verification_status": "unknown | confirmed | needs_revision",
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ]
  ```

### 3.2 사실 카드 신규 추가
- **요청**: `POST /api/v1/projects/{project_id}/facts`
  - Body: `{ "fact_text": "string", "source_text": "string?", "source_asset_id": "string?" }`
- **응답 (201)**: 생성된 `ProductFact` 객체

### 3.3 사실 카드 업데이트 (수정 및 상태 변경)
- **요청**: `PATCH /api/v1/projects/{project_id}/facts/{fact_id}`
  - Body: `{ "fact_text": "string?", "source_text": "string?", "source_asset_id": "string?", "verification_status": "string?" }`
- **응답 (200)**: 업데이트된 `ProductFact` 객체
- **비즈니스 로직**: 업데이트 수행 전, 기존 상태값을 백업하여 `fact_histories` 테이블에 적재함.

### 3.4 사실 카드 삭제
- **요청**: `DELETE /api/v1/projects/{project_id}/facts/{fact_id}`
- **응답 (204)**: No Content

### 3.5 사실 카드 변경 이력 조회
- **요청**: `GET /api/v1/projects/{project_id}/facts/{fact_id}/history`
- **응답 (200)**:
  ```json
  [
    {
      "id": "UUID",
      "fact_id": "UUID",
      "previous_fact_text": "string",
      "previous_source_text": "string",
      "previous_source_asset_id": "string | null",
      "previous_verification_status": "string",
      "updated_by": "UUID",
      "updated_at": "datetime"
    }
  ]
  ```

---

## 4. 테스트 케이스 및 실행 명령

### 4.1 백엔드 단위 테스트 (`backend/tests/test_facts.py`)
1. **사실 생성 및 조회 테스트**: 사실 카드를 추가하고 프로젝트 하위 사실 목록에 올바르게 반영되는지 검증.
2. **사실 업데이트 및 변경 이력(History) 기록 검증**: 사실 텍스트나 검증 상태를 변경했을 때 `fact_histories`에 이전 값이 정확히 기록되는지 검증.
3. **데이터 규칙(Filter) 테스트**: `confirmed_only=true` 옵션 적용 시 `confirmed`가 아닌 사실 카드는 필터링되어 제외되는지 검증.

### 4.2 실행 명령
```bash
# 백엔드 단위 테스트 실행
cd backend
uv run pytest tests/test_facts.py
```

---

## 5. 완료 기준 (Definition of Done)

1. **사실 및 원본 데이터 연동**: 사용자가 직접 작성하거나 AI가 추출한(다음 스프린트 대비) 상품 사실이 근거 자료(텍스트 또는 이미지 Asset)와 연결된다.
2. **수동 복구 및 수동 작성 완결성**: 링크 자동 분석 실패 여부와 무관하게 사용자가 직접 사실을 추가, 수정, 삭제하여 온전한 상품 사실 목록을 구축할 수 있다.
3. **변경 내역 감 감사(Auditing)**: 확정된 사실을 수정할 시, 변경 전 텍스트, 변경 전 근거, 변경 시점의 유저 정보가 감사 이력 테이블에 보존된다.
4. **미확정 사실 제외 규칙**: `confirmed_only=true` 조회 필터가 API 수준에서 완벽하게 기능하여 차후 상세페이지 빌더에서 미확정 사실의 사용을 차단할 수 있도록 한다.
