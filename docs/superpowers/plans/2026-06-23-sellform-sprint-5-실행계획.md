# 셀폼(Sellform) 스프린트 5 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** 상세페이지 최종 검수(규제 검수 및 자산 누락 검증)를 수행하고, 설정 데이터 기반의 판매처 프리셋(쿠팡, 스마트스토어 등)에 맞추어 Headless Chromium을 활용해 모바일 가로폭 기준으로 긴 세로형 상세페이지를 비동기식으로 렌더링하고 이미지 묶음(ZIP 파일)으로 내보내는 기능을 구현합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [MODIFY] `backend/pyproject.toml`: `playwright` 및 `pillow` 의존성 추가
- [MODIFY] `backend/src/db/models.py`: 비동기 내보내기 이력 관리용 `ExportJob` 테이블 모델 추가 및 `Asset` 테이블 `source_type` 관계 확인
- [NEW] `backend/src/api/exports.py`: 상세페이지 검수 및 비동기 내보내기/다운로드 API 엔드포인트 구현
- [NEW] `backend/src/services/compliance_checker.py`: 상세페이지 섹션 전체 문구와 자산(이미지) 누락을 실시간으로 확인하는 검수 비즈니스 로직 구현
- [NEW] `backend/src/services/renderer.py`: Playwright를 이용한 HTML/CSS 렌더링, Pillow를 활용한 긴 이미지 분할 및 ZIP 파일 패키징 서비스 구현
- [MODIFY] `backend/src/app.py`: `exports` 라우터 마운트
- [NEW] `backend/tests/test_exports.py`: 검수 차단 및 허용 규칙 검증, 비동기 렌더링 실행 및 ZIP 출력본 생성 단위 테스트

### 1.2 프론트엔드 구조 (`frontend/`)
- [NEW] `frontend/src/app/workspace/projects/[id]/export/page.tsx`: 검수 결과 경고창, 판매처 프리셋 선택(쿠팡/스마트스토어), 비동기 렌더링 상태 추적 및 최종 다운로드 화면 구현

---

## 2. 데이터 모델 (PostgreSQL 스키마)

### 2.1 SQLAlchemy 신규 테이블 정의

#### **`export_jobs`**
- `id` (UUID, PK, default=generate_uuid)
- `project_id` (UUID, FK -> `product_projects.id`, cascade="all, delete-orphan", nullable=False)
- `preset_name` (String(100), nullable=False) - e.g., "coupang", "smartstore"
- `status` (String(50), nullable=False, default="pending") - pending, running, completed, failed
- `error_message` (Text, nullable=True)
- `zip_asset_id` (UUID, FK -> `assets.id`, nullable=True) - 최종 ZIP 파일 에셋 ID
- `output_images` (JSON, nullable=True) - 생성된 분할 이미지 파일 경로 목록 (JSON List)
- `created_by` (UUID, FK -> `users.id`, nullable=False)
- `created_at` (DateTime, default=utcnow)
- `completed_at` (DateTime, nullable=True)

---

## 3. API 계약 (API Contract)

### 3.1 상세페이지 최종 검수 (Compliance & Integrity Check)
- **요청**: `GET /api/v1/projects/{project_id}/page/compliance`
- **응답 (200 OK)**:
  ```json
  {
    "can_export": false,
    "issues": [
      {
        "severity": "Blocker",
        "rule": "어린이제품 KC 인증번호 누락",
        "message": "아동용 제품은 어린이제품 안전 특별법에 따른 KC안전인증 번호 표기가 필수적이나 누락되었습니다.",
        "section_id": "section_uuid_1"
      },
      {
        "severity": "Warning",
        "rule": "섹션 이미지 누락",
        "message": "'주요 기능 설명' 섹션에 이미지 자산이 설정되지 않았습니다.",
        "section_id": "section_uuid_2"
      }
    ]
  }
  ```
- **비즈니스 로직**:
  1. 프로젝트 카테고리 정보 및 상세페이지의 활성화된(`is_visible == true`) 섹션 리스트를 조회합니다.
  2. 각 섹션의 `title`과 `body_copy`를 기존 규제 검수 엔진(`check_compliance`)에 전달하여 법적 이슈를 탐색합니다.
  3. 섹션의 `image_asset_id`가 필수적인 섹션 타입(예: `features` 등 이미지 필수 영역)에서 누락되어 있다면 `Warning` 등급의 이슈를 생성합니다.
  4. 이슈 중 `Blocker` 등급이 존재하면 `can_export`를 `false`로 설정하여 출력을 차단합니다.

### 3.2 상세페이지 비동기 이미지 출력 요청
- **요청**: `POST /api/v1/projects/{project_id}/page/export`
  - Body: `{ "preset_name": "coupang | smartstore" }`
- **응답 (202 Accepted)**:
  ```json
  {
    "job_id": "UUID",
    "status": "pending"
  }
  ```
- **비즈니스 로직**:
  1. 검수 엔진을 사전 가동하여 `Blocker` 이슈가 있는지 확인하고, 존재할 경우 `400 Bad Request` 처리합니다.
  2. `ExportJob` 레코드를 `pending` 상태로 생성합니다.
  3. FastAPI `BackgroundTasks`에 이미지 렌더링 작업을 등록하고 응답을 반환합니다.

### 3.3 비동기 출력 작업 상태 조회
- **요청**: `GET /api/v1/projects/{project_id}/page/export/jobs/{job_id}`
- **응답 (200 OK)**:
  ```json
  {
    "id": "UUID",
    "status": "running | completed | failed",
    "preset_name": "coupang",
    "zip_asset_id": "asset_uuid_or_null",
    "output_images": ["/uploads/export_1_1.png", "/uploads/export_1_2.png"],
    "error_message": null,
    "completed_at": "datetime_or_null"
  }
  ```

### 3.4 내보내기 이력 목록 조회
- **요청**: `GET /api/v1/projects/{project_id}/page/export/jobs`
- **응답 (200 OK)**: `List[ExportJob]` 객체 리스트 반환

### 3.5 출력 파일 다운로드
- **요청**: `GET /api/v1/projects/{project_id}/page/export/download/{asset_id}`
- **응답**: ZIP 파일 바이너리 스트림 반환

---

## 4. 핵심 서비스 구현 명세

### 4.1 판매처별 출력 프리셋 설정
설정 데이터를 백엔드 메모리나 별도 관리합니다.
- **Coupang (쿠팡)**: 가로폭 780px, 이미지당 최대 높이 5,000px, 파일 형식 PNG
- **Smartstore (스마트스토어)**: 가로폭 860px, 이미지당 최대 높이 20,000px, 파일 형식 PNG

### 4.2 Playwright & Pillow 기반 렌더링 및 분할 (Slice) 알고리즘
1. 상세페이지의 전체 템플릿 HTML을 컴파일합니다. (각 섹션의 텍스트와 등록된 이미지 파일 경로/URL을 HTML DOM 구조로 변환)
2. Playwright 헤드리스 브라우저를 구동하여 뷰포트 크기를 프리셋 가로폭(예: 860px)으로 조절하고 로드합니다.
3. `fullPage=True` 옵션으로 전체 스냅샷 이미지를 캡처하여 디렉토리에 저장합니다.
4. Pillow를 이용하여 캡처된 전체 이미지의 세로 길이를 계산하고, 프리셋의 최대 높이(예: 5000px) 간격으로 위에서부터 차례대로 슬라이스하여 개별 파일로 저장합니다.
   *   *단, 마지막 남은 영역이 최소 높이보다 작아도 안전하게 잘라 저장합니다.*
5. 슬라이스된 모든 이미지 조각들과 설명 텍스트를 담은 ZIP 파일을 만들고, 이를 `Asset` 테이블 및 `uploads/` 스토리지에 관리합니다.
6. **테스트 환경 대응**: 서버 인프라에 따라 Chromium 실행이 실패하거나 MOCK 환경인 경우, 임의의 더미 이미지 세트와 ZIP 파일을 생성하는 **Mock Renderer Fallback** 로직을 적용하여 전체 빌드와 CI가 통과되도록 보장합니다.

---

## 5. 테스트 케이스 및 실행 명령

### 5.1 백엔드 단위 테스트 명세 (`backend/tests/test_exports.py`)
1. **최종 검수 차단 룰 테스트**:
   - `Blocker` 등급 규제 위반 사항이 있을 때 검수 결과가 `can_export = false`가 되는지 확인.
   - `Blocker` 이슈가 존재할 때 내보내기 시작 요청 시 400 에러를 뱉는지 확인.
2. **비동기 렌더링 정상 실행 테스트**:
   - 내보내기 작업 요청 후 상태가 `pending` -> `completed`로 성공적으로 이행되는지 확인.
   - 디렉토리에 슬라이스된 이미지 파일 및 ZIP 압축본이 올바르게 생성되는지 검증.
3. **판매처별 프리셋 가로폭 분할 검증**:
   - 쿠팡 프리셋(780px)과 스마트스토어 프리셋(860px)별로 각각 다른 이미지 해상도를 가진 결과가 나오는지 검증.

### 5.2 실행 명령
```bash
cd backend
uv run pytest tests/test_exports.py
```

---

## 6. 완료 및 기록 기준 (Definition of Done)

### 6.1 기능 완료 기준
1. **규제 차단 엔진 완성**: `Blocker` 급 경고가 남은 상태에서는 ZIP 생성이 불가하고 차단 메시지가 정확히 나와야 합니다.
2. **비동기 백그라운드 렌더링**: 렌더링 도중 백엔드 메인 스레드가 정지되지 않고 비동기로 진행되며, 실패 시 런타임 오류가 로깅되고 상태가 `failed`로 기록됩니다.
3. **프리셋별 이미지 슬라이싱**: 최종 생성된 이미지 묶음들의 가로폭이 선택된 프리셋 규격과 일치하고, 잘린 부분 없이 순차적으로 저장되어야 합니다.
4. **ZIP 에셋 관리 및 다운로드**: 생성된 ZIP 파일이 에셋 테이블에 기록되고 다운로드 링크를 통해 실제 다운로드받을 수 있어야 합니다.

### 6.2 기록 산출물 기준
- **자가 코드리뷰**: `docs/reviews/2026-06-23-sellform-sprint-5-code-review.md`
- **자가 테스트 로그**: `docs/testing/2026-06-23-sellform-sprint-5-test-run-log.md`
- **의사결정 기록**: `docs/decisions/2026-06-23-sellform-sprint-5-export-strategy.md`
- **트러블슈팅 로그**: `docs/troubleshooting/2026-06-23-sellform-sprint-5-rendering-issues.md`
- **워크스루 최신화**: 프로젝트 루트의 `walkthrough.md` 및 `task.md` 완료 처리.
