# 셀폼(Sellform) 스프린트 4 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** 확정된 상품 사실(Fact) 카드와 에셋 사진들을 기반으로 카테고리별 매력적인 상세페이지 초안(테마, 섹션별 문구, 이미지 매핑)을 AI를 통해 생성하고, 3단 편집기를 통해 사용자가 레이아웃, 문구, 이미지, 버전을 가이드 형태로 조작 및 복원할 수 있는 상세페이지 계획·편집 기능을 구현합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [MODIFY] `backend/src/db/models.py`: 상세페이지(`ProductPage`), 페이지 섹션(`PageSection`), 페이지 버전 이력(`PageVersion`) 테이블 모델 정의
- [NEW] `backend/src/api/pages.py`: 상세페이지 생성, 조회, 업데이트, AI 부분 수정, 버전 백업 및 복원 API 엔드포인트 구현
- [NEW] `backend/src/services/page_generator.py`: `Claude 3.5 Sonnet` 연동을 통한 테마, 섹션 레이아웃 계획 및 판매 카피 생성 로직 구현
- [MODIFY] `backend/src/app.py`: `pages` 라우터 마운트
- [NEW] `backend/tests/test_pages.py`: 상세페이지 라이프사이클 API 단위 테스트 (생성, 편집, 버전 복원, 미확정 사실 경고 검증)

### 1.2 프론트엔드 구조 (`frontend/`)
- [NEW] `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`: 가이드형 3단 편집기 구현
  *   **왼쪽 패널**: 섹션 목록 관리 (순서 변경, 숨기기/보이기, 신규 추가)
  *   **중앙 패널**: 모바일 웹 뷰 스타일의 실시간 미리보기 (HTML/CSS 반응형)
  *   **오른쪽 패널**: 선택 섹션 텍스트 편집, 이미지 에셋 매핑 교체, 섹션 단위 AI 부분 수정(재생성) 인터페이스

---

## 2. 데이터 모델 (PostgreSQL 스키마)

### 2.1 SQLAlchemy 테이블 정의

#### **`product_pages`**
- `id` (UUID, PK)
- `project_id` (UUID, FK -> `product_projects.id`, cascade="all, delete-orphan", nullable=False): 연동된 프로젝트 ID
- `theme_color` (String(50), default="#3B82F6"): 대표 테마 색상 (Hex 코드)
- `font_family` (String(50), default="sans-serif"): 대표 폰트 스타일
- `created_at` (DateTime, default=utcnow)
- `updated_at` (DateTime, default=utcnow, onupdate=utcnow)

#### **`page_sections`**
- `id` (UUID, PK)
- `page_id` (UUID, FK -> `product_pages.id`, cascade="all, delete-orphan", nullable=False): 상세페이지 ID
- `section_type` (String(100), nullable=False): 섹션 유형 (예: `header`, `features`, `specifications`, `faq`)
- `title` (String(255), nullable=True): 섹션 제목
- `body_copy` (Text, nullable=True): AI가 생성한 판매 카피 문구
- `associated_fact_ids` (JSON, nullable=True): 연결된 상품 사실(`ProductFact.id`)의 JSON List (예: `["uuid1", "uuid2"]`)
- `image_asset_id` (UUID, FK -> `assets.id`, nullable=True): 섹션 대표 이미지 에셋 ID
- `sort_order` (Integer, nullable=False, default=0): 섹션 배치 순서
- `is_visible` (Boolean, default=True): 섹션 노출 여부

#### **`page_versions`**
- `id` (UUID, PK)
- `page_id` (UUID, FK -> `product_pages.id`, cascade="all, delete-orphan", nullable=False): 대상 상세페이지 ID
- `version_number` (Integer, nullable=False): 버전 일련번호
- `page_data` (JSON, nullable=False): 당시의 테마 및 섹션 데이터 전체 스냅샷
- `created_by` (UUID, FK -> `users.id`, nullable=False): 작성자 ID
- `created_at` (DateTime, default=utcnow)

---

## 3. API 계약 (API Contract)

### 3.1 상세페이지 초안 AI 생성
- **요청**: `POST /api/v1/projects/{project_id}/page`
  - Body: `{ "style_preset": "modern | emotional | formal", "primary_color": "string?" }`
- **응답 (201 Created)**: 상세 생성된 `ProductPage` 객체 및 포함된 `page_sections` 리스트 반환
- **비즈니스 로직**:
  1. `project.facts` 목록 중 **확정된 사실(`verification_status == 'confirmed'`)**만 수집합니다.
  2. 미확정 사실이 존재한다면, 섹션 데이터의 경고 리스트(`warnings`)에 담되 판매 카피 본문에는 포함시키지 않습니다.
  3. `Claude 3.5 Sonnet` API를 호출하여 테마, 섹션별 제목, 판매 카피 문구를 구조화된 JSON으로 생성합니다.
  4. 생성 데이터를 데이터베이스에 영구 적재하고 페이지 객체를 반환합니다.

### 3.2 페이지 및 섹션 정보 조회
- **요청**: `GET /api/v1/projects/{project_id}/page`
- **응답 (200 OK)**:
  ```json
  {
    "id": "UUID",
    "theme_color": "#3B82F6",
    "font_family": "sans-serif",
    "sections": [
      {
        "id": "UUID",
        "section_type": "features",
        "title": "100% 면 소재의 편안함",
        "body_copy": "피부에 닿는 부드러움...",
        "associated_fact_ids": ["fact_uuid_1"],
        "image_asset_id": "asset_uuid_1",
        "sort_order": 0,
        "is_visible": true,
        "warnings": []
      }
    ]
  }
  ```

### 3.3 상세페이지 레이아웃/스타일 업데이트 (오토세이브 대응)
- **요청**: `PATCH /api/v1/projects/{project_id}/page`
  - Body: `{ "theme_color": "string?", "font_family": "string?", "sections": [...] }`
- **응답 (200 OK)**: 업데이트된 `ProductPage` 데이터
- **비즈니스 로직**: 사용자의 레이아웃 변경, 문구 수정, 이미지 교체, 섹션 숨김 여부를 일괄 반영합니다. 업데이트 직전, 현재 상태를 스냅샷으로 `page_versions` 테이블에 백업합니다.

### 3.4 섹션 단위 부분 AI 수정 (재생성)
- **요청**: `POST /api/v1/projects/{project_id}/page/sections/{section_id}/regenerate`
  - Body: `{ "user_instruction": "좀 더 따뜻한 톤으로 문구를 길게 고쳐줘" }`
- **응답 (200 OK)**: 재생성 완료된 `PageSection` 단일 객체 데이터

### 3.5 이전 페이지 버전 복원
- **요청**: `POST /api/v1/projects/{project_id}/page/versions/{version_id}/restore`
- **응답 (200 OK)**: 복원 완료된 전체 `ProductPage` 스키마 데이터

---

## 4. 테스트 케이스 및 실행 명령

### 4.1 백엔드 단위 테스트 명세 (`backend/tests/test_pages.py`)
1. **페이지 생성 시 미확정 사실 필터링 검증**:
   *   `verification_status != 'confirmed'` 상태인 사실 카드가 AI 본문 카피 생성 시 배제되고, 경고 항목(`warnings`)으로만 기록되는지 검증.
2. **페이지 오토세이브 및 버저닝 검증**:
   *   페이지 정보가 변경될 때마다 버전 이력이 순차적(1, 2, 3...)으로 안전하게 적재되는지 검증.
3. **버전 복원(Restore) 테스트**:
   *   특정 버전 복원을 호출했을 때, 현재 페이지 테마와 섹션 리스트 상태가 과거 스냅샷 데이터와 동일하게 원상복구되는지 확인.

### 4.2 실행 명령
```bash
cd backend
uv run pytest tests/test_pages.py
```

---

## 5. 완료 및 기록 기준 (Definition of Done)

### 5.1 기능 완료 기준
1. **페이지 조합 모델 수립**: 테마 색상, 폰트 종류, 섹션 배열이 DB 스키마와 완벽하게 싱크되어 있어야 합니다.
2. **사실 기반 카피 라이팅**: 생성된 모든 판매 카피 문구가 연동된 확정 사실 ID(`associated_fact_ids`)와 명확하게 관계가 맺어집니다.
3. **3단 가이드형 조작 완결**: UI 컴포넌트 수준에서 섹션 보이기/숨기기, 순서 변경(sort_order), 문구 변경이 즉시 화면 미리보기에 동기화됩니다.
4. **롤백 버저닝 완비**: 복원 호출 시 이전 상태로 안전하게 전환되며, 과거 정보가 유실되지 않아야 합니다.

### 5.2 기록 산출물 기준
*   **자가 코드리뷰**: `docs/reviews/2026-06-23-sprint-4-code-review.md`
*   **자가 테스트 로그**: `docs/testing/2026-06-23-sprint-4-test-run-log.md`
*   **의사결정 기록**: `docs/decisions/2026-06-23-sprint-4-editor-ux-design.md`
*   **트러블슈팅 로그**: `docs/troubleshooting/2026-06-23-sprint-4-troubleshooting.md`
*   **워크스루 최신화**: 프로젝트 루트의 `walkthrough.md` 및 `task.md` 완료 처리.
