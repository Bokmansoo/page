# 셀폼(Sellform) 스프린트 6 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** 동일한 상품 프로젝트를 모바일 웹 랜딩페이지로 발행하고, 비인증 사용자가 전 세계 어디서든 접근하여 볼 수 있게 만듭니다. 또한 구매 링크 연결, FAQ 아코디언, 전후 비교 슬라이더, 동영상 임베드 등 인터랙티브한 client-side 컴포넌트들을 탑재합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [MODIFY] `backend/src/db/models.py`: 웹페이지 공개 발행 내역 및 인터랙티브 설정을 보관하는 `PublishedPage` 테이블 모델 추가
- [NEW] `backend/src/api/publications.py`: 프로젝트 웹 발행, 상태 수정(비공개/공개 전환), 인증이 필요 없는 공개 조회 API 엔드포인트 구현
- [MODIFY] `backend/src/app.py`: `publications` 라우터 마운트
- [NEW] `backend/tests/test_publications.py`: 비활성 페이지 비공개 가드 검증, 비인증 사용자 데이터 조회 허용 검증

### 1.2 프론트엔드 구조 (`frontend/`)
- [NEW] `frontend/src/app/workspace/projects/[id]/publish/page.tsx`: 판매처 외부 링크 설정, 아코디언/전후비교/동영상 등의 인터랙티브 기능 토글, 발행 관리 UI 페이지
- [NEW] `frontend/src/app/p/[id]/page.tsx`: **인증 없는 일반 고객용 모바일 랜딩페이지 뷰**
  - sticky 구매하기 버튼, 이미지 갤러리, FAQ 아코디언, 이미지 전후비교 컴포넌트, 비디오 임베딩 지원

---

## 2. 데이터 모델 (PostgreSQL 스키마)

### 2.1 SQLAlchemy 신규 테이블 정의

#### **`published_pages`**
- `id` (UUID, PK, default=generate_uuid) - 랜딩페이지 공개 고유 식별값 (URL 주소에 매핑)
- `project_id` (UUID, FK -> `product_projects.id`, cascade="all, delete-orphan", nullable=False)
- `page_id` (UUID, FK -> `product_pages.id`, cascade="all, delete-orphan", nullable=False)
- `slug` (String(100), unique=True, nullable=True) - 커스텀 경로 지원용
- `is_active` (Boolean, default=True) - 공개 여부 (False 시 일반 고객 접근 차단)
- `external_store_url` (String(1000), nullable=True) - 구매 버튼 클릭 시 연결될 쿠팡/스마트스토어 등 외부 판매 링크
- `config` (JSON, nullable=True) - 인터랙티브 옵션(예: FAQ 활성화 여부, 전후 비교 이미지 정보, 영상 링크 등)
- `created_at` (DateTime, default=utcnow)
- `updated_at` (DateTime, default=utcnow, onupdate=utcnow)

---

## 3. API 계약 (API Contract)

### 3.1 모바일 랜딩페이지 웹 발행/재발행
- **요청**: `POST /api/v1/projects/{project_id}/publish`
  - Body:
    ```json
    {
      "external_store_url": "https://coupang.com/vp/products/...",
      "slug": "custom-apple-juice",
      "config": {
        "show_faq": true,
        "before_after_slider": {
          "enabled": true,
          "before_image_id": "asset_uuid_1",
          "after_image_id": "asset_uuid_2"
        },
        "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ"
      }
    }
    ```
- **응답 (200 OK)**: 생성 또는 갱신된 `PublishedPage` 객체 정보 반환
- **비즈니스 로직**:
  1. 프로젝트 및 기존 작성된 `ProductPage` 초안 정보를 검증합니다.
  2. 이미 발행된 내역이 있을 경우 기존 레코드를 오버라이트(재발행)하고 `is_active`를 `true`로 설정합니다.

### 3.2 발행 상태 및 링크 설정 수정
- **요청**: `PATCH /api/v1/projects/{project_id}/publication`
  - Body: `{ "is_active": false }`
- **응답 (200 OK)**: 수정 완료된 `PublishedPage` 객체 정보 반환

### 3.3 [비인증] 웹페이지 공개 상세 조회
- **요청**: `GET /api/v1/public/pages/{id_or_slug}` (🚨 *인증 헤더 없음*)
- **응답 (200 OK)**:
  ```json
  {
    "id": "UUID",
    "theme_color": "#FF0000",
    "font_family": "sans-serif",
    "external_store_url": "https://...",
    "config": { ... },
    "sections": [
      {
        "section_type": "features",
        "title": "유기농 사과즙",
        "body_copy": "..."
      }
    ],
    "assets": {
      "asset_uuid_1": "/uploads/..."
    }
  }
  ```
- **에러 응답 (403 Forbidden / 404 Not Found)**:
  - `is_active`가 `false`로 설정된 경우 "해당 페이지는 발행이 중지되었습니다." 메시지와 함께 `403 Forbidden` 또는 `404` 처리합니다.

---

## 4. 인터랙티브 기능 명세 (Client-side)

### 4.0 이미지 갤러리
- 공개 랜딩페이지 상단 또는 주요 섹션에 상품 자산 이미지를 모바일 스와이프 가능한 갤러리 형태로 표시합니다.
- 이미지가 1개일 때는 단일 대표 이미지로 표시하고, 2개 이상일 때는 썸네일 또는 dot indicator를 제공합니다.
- 갤러리에 사용하는 이미지는 해당 상품 프로젝트에 연결된 `Asset` 목록에서 가져오며, 이미지가 없을 경우 텍스트 중심 레이아웃으로 graceful fallback합니다.
- 추후 고도화를 위해 갤러리 이미지는 옵션, 색상, 사용 장면 등의 메타데이터와 연결 가능한 구조로 둡니다.

### 4.1 FAQ 아코디언
- FAQ 섹션 클릭 시 모바일에서 Smooth 슬라이드 형태로 질문 하위에 AI가 수집한 답변 카피가 노출 및 아코디언 토글 애니메이션 지원.

### 4.2 Before / After 이미지 슬라이더
- 슬라이더 조작 바를 조작하여 하나의 캔버스 위에 이전/이후 사진이 오버랩되어 변화되는 모습을 사용자가 마우스 드래그나 모바일 터치 스와이프로 직관적으로 비교할 수 있는 컴포넌트 탑재.

### 4.3 반응형 비디오 임베딩
- YouTube 또는 Vimeo 링크가 활성화된 경우 16:9 비율의 반응형 비디오 임베딩 컴포넌트를 섹션 하단에 표시.

### 4.4 스티키 구매 버튼 (Sticky Purchase Bar)
- 모바일 뷰 최하단에 항상 붙어있는 "구매하기" Sticky Bar 형태로 동작하며, 클릭 시 지정된 `external_store_url` 주소로 새 탭에서 즉시 아웃바운딩 처리.

---

## 5. 테스트 케이스 및 실행 명령

### 5.1 백엔드 단위 테스트 명세 (`backend/tests/test_publications.py`)
1. **공개 발행 및 조회 테스트**:
   - 비인증 API인 `GET /api/v1/public/pages/{id}`를 호출하여 발행한 상세페이지의 마크업 데이터(테마, 섹션 리스트)가 토큰 없이 올바르게 조회되는지 검증.
2. **비공개 차단 정책 검증**:
   - `is_active = False`로 변경한 후 동일한 비인증 API 호출 시 `403 Forbidden` (또는 `404`) 오류로 차단되는지 확인.
3. **구매 링크 및 인터랙티브 설정 검증**:
   - `external_store_url`, FAQ 표시 여부, 전후 비교 이미지 설정, 비디오 링크, 이미지 갤러리용 자산 목록이 공개 조회 응답에 포함되는지 확인.
4. **재발행 검증**:
   - 이미 발행된 프로젝트를 다시 발행하면 신규 중복 레코드가 아니라 기존 `PublishedPage`가 갱신되고 `is_active=true`로 복구되는지 확인.

### 5.2 프론트엔드 빌드 및 수동 QA 명세
1. **프론트 빌드 검증**:
   - `frontend`에서 `npm.cmd run build`를 실행해 TypeScript, lint, Next.js production build가 통과하는지 확인합니다.
2. **모바일 접근성 QA**:
   - 공개 페이지 `/p/[id]`에서 sticky 구매 버튼, FAQ 버튼, 갤러리 조작, 전후 비교 슬라이더가 키보드/터치 기준으로 조작 가능한지 확인합니다.
   - 주요 버튼에는 의미 있는 텍스트가 있고, 이미지에는 대체 텍스트 또는 설명 가능한 fallback이 있어야 합니다.
3. **모바일 성능 QA**:
   - 공개 페이지가 모바일 viewport에서 가로 스크롤 없이 표시되는지 확인합니다.
   - 큰 이미지가 레이아웃을 깨뜨리지 않고 `object-fit`, lazy loading 또는 적절한 크기 제한으로 표시되는지 확인합니다.
4. **링크 오류 QA**:
   - 구매 버튼이 `external_store_url`이 있을 때 새 탭 또는 현재 정책에 맞는 방식으로 이동하는지 확인합니다.
   - 링크가 없을 경우 사용자가 오해하지 않도록 비활성/안내 상태를 표시합니다.

### 5.3 실행 명령
```bash
cd backend
uv run pytest tests/test_publications.py
```

```bash
cd frontend
npm.cmd run build
```

---

## 6. 완료 기준 (Definition of Done)

1. **웹형 공개 페이지 발행**
   - 기존 `ProductPage`와 `PageSection` 데이터를 기반으로 비인증 사용자가 접근 가능한 모바일 랜딩페이지를 발행할 수 있어야 합니다.

2. **공개/비공개 제어**
   - 발행된 페이지는 공개 URL 또는 slug로 조회 가능해야 하며, `is_active=false` 상태에서는 비인증 접근이 차단되어야 합니다.

3. **구매 링크 연결**
   - sticky 구매 버튼은 설정된 쿠팡/스마트스토어 등 외부 판매 링크로 이동해야 하며, 링크가 없는 경우 안전한 안내 상태를 보여야 합니다.

4. **인터랙티브 컴포넌트**
   - 이미지 갤러리, FAQ 아코디언, 전후 비교 슬라이더, 비디오 임베딩이 설정값에 따라 선택적으로 표시되어야 합니다.

5. **모바일 품질**
   - 공개 페이지는 모바일 viewport에서 레이아웃 깨짐 없이 동작해야 하며, 기본 접근성·링크·성능 QA를 통과해야 합니다.

6. **회귀 검증**
   - `backend`의 `test_publications.py`와 전체 백엔드 테스트가 통과해야 합니다.
   - `frontend`의 production build가 통과해야 합니다.

---

## 7. 리뷰·테스트·운영 문서 산출물

Sprint 6 종료 전 다음 문서를 남깁니다.

- **코드 리뷰 문서**: `docs/reviews/2026-06-23-sellform-sprint-6-code-review.md`
  - 발행 API, 공개 조회 보안 경계, 프론트 공개 페이지, 인터랙티브 컴포넌트 구현을 검토합니다.
- **테스트 로그**: `docs/testing/2026-06-23-sellform-sprint-6-test-run-log.md`
  - 백엔드 테스트, 프론트 빌드, 모바일 수동 QA 결과를 기록합니다.
- **트러블슈팅 기록**: `docs/troubleshooting/2026-06-23-sellform-sprint-6-troubleshooting.md`
  - 발행/조회/링크/모바일 UI 문제와 해결 과정을 기록합니다.
- **결정 기록(필요 시)**: `docs/decisions/2026-06-23-sellform-sprint-6-publication-strategy.md`
  - 공개 URL 정책, slug 충돌 처리, 비공개 차단 방식을 별도 결정해야 할 경우 작성합니다.
- **릴리스 노트(사용자 노출 변경 시)**: `docs/releases/2026-06-23-sellform-sprint-6.md`
  - 웹형 랜딩페이지 발행 기능의 사용자 관점 변경점을 정리합니다.
