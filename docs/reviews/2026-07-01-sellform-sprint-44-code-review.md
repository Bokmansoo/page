# Sprint 44 - 비주얼 패키지 및 이미지 생성 계약 코드 리뷰 (보완본)

본 문서는 Sprint 44 구현 및 보완 작업(비주얼 패키지 기획 및 이미지 생성 계약 시스템)에 대한 핵심 소스 코드 리뷰입니다.

---

## 1. 코드 리뷰 개요

- **목적**: 상세페이지 이미지 기획, 원본 사진 매핑 우선순위 규칙, AI 생성 계약서 명세화 및 컴포넌트 통합의 품질 검증.
- **대상**:
  - `image_generation_contract.py` (이미지 생성 작업 Pydantic 스키마 및 검증)
  - `visual_package_planner.py` (비주얼 패키지 기획 및 프롬프트 생성 서비스)
  - `commerce_visual_cut_builder.py` (비주얼 역할 매핑 확장)
  - `pages.py (API)` (비주얼 패키지 계획, 업데이트, 재생성 API endpoints)
  - `VisualPackagePanel.tsx` (프론트엔드 비주얼 패키지 리뷰 패널)
  - `page.tsx (page-editor)` (프론트엔드 비주얼 패키지 탭 및 레이아웃 연동)
  - `conftest.py` (테스트 DB 환경의 속도 및 세션 격리 최적화)

---

## 2. 세부 코드 리뷰 의견

### 1) 이미지 생성 계약 스키마 (`image_generation_contract.py`)
- **강점**:
  - `job_id`와 `section_id` 필드를 신설하여 다중 이미지 또는 동일 역할(`detail_closeup` 등)의 컷들이 겹치더라도 명확하게 고유 식별되도록 설계했습니다.
  - Pydantic v2의 `@model_validator(mode="after")`를 통해 `job_id` 및 `section_id`가 필수 불가결한 값임을 확실히 체크하고, `needs_generation` 시 프롬프트 유효성과 아이덴티티 수집 조건을 강제합니다.

### 2) 비주얼 패키지 기획서 서비스 (`visual_package_planner.py`)
- **강점**:
  - 계획 단계에서 각 작업마다 UUID 기반 고유 `job_id`를 발행하고 해당 섹션 ID를 연동해 데이터 일관성을 확보했습니다.
  - **판매 전략(Sales Strategy) 반영**: 상품의 메인 소구점, 핵심 고객 타겟, 고민 해결 문안, 톤앤매너를 프롬프트 템플릿에 동적으로 융합해 생성 가이드 품질을 높였습니다.
  - **인증마크 및 문구 자동 제외**: `badge_set`, `comparison_graphic`, `faq_graphic` 등 텍스트나 심볼이 인쇄되는 역할군의 지시문에 텍스트/로고를 배제하라는 강한 영문 클로즈를 덧붙였으며, 네거티브 프롬프트에 `text`, `logo`, `badge`, `certificate` 등을 보편 주입해 Paid API의 텍스트 깨짐 현상을 근원적으로 차단하고 편집 레이어 합성으로 우회하도록 유도했습니다.

### 3) 비주얼 패키지 API 엔드포인트 (`pages.py`)
- **강점**:
  - `GET /projects/{project_id}/visual-package`: 최초 기획 시 판매 전략을 바인딩해 프롬프트를 자동 제안합니다.
  - `POST /projects/{project_id}/visual-package/jobs/{job_id}/update`: 
    - 역할(role) 대신 `job_id`로 대상을 선별하게 하여 다중 세부컷 대응이 용이해졌습니다.
    - **자산 보안 및 타입 검증**: 업데이트 시 지정한 이미지 파일이 실재하는지, 타 프로젝트의 자산 침범은 없는지, MIME 타입이 `image/*`로 부합하는지 꼼꼼히 확인해 API 불일치를 사전에 방어합니다.
    - **AI 이미지 전환 시 프롬프트 자동 재생성**: planned 상태에서 needs_generation으로 스위치할 때 지시문이 유실되었거나 빈 값일 경우, 판매 전략 기반의 추천 지시문을 실시간 재생성 및 바인딩해 줍니다.
  - `POST /projects/{project_id}/visual-package/regenerate`: 캐시를 완벽하게 무효화(Invalidate)하고 최신 상세페이지 구조에 맞춰 전체 비주얼 계획을 처음부터 새로 짜는 기능을 제공합니다.

### 4) 프론트엔드 비주얼 패키지 패널 및 연동 (`VisualPackagePanel.tsx`, `page.tsx`)
- **강점**:
  - 기존의 역할 기준 이벤트 처리를 고유 `job_id` 기준으로 리팩토링하여 중복 컷이 존재해도 정확한 상태 전이가 이루어지도록 UI 액션을 개선했습니다.
  - 상단에 **기획서 재생성(Regenerate Plan)** 연동 단추를 설계하여 캐시 갱신 기능을 명시적으로 유저에게 노출합니다.
  - page-editor의 `activeTab` 상태에 `'visual'`을 정규 타입으로 편입하여 JSX 컴파일 경고를 일소했습니다.

### 5) 테스트 DB 및 프레임워크 최적화 (`conftest.py`)
- **강점**:
  - 매 테스트 함수마다 SQLite DB를 삭제하고 테이블을 재생성(`create_all` / `drop_all`)하던 구조에서, **PRAGMA foreign_keys = OFF를 활용한 TRUNCATE(데이터 삭제) 방식으로 변경**했습니다.
  - 이를 통해 전체 210개 단위 테스트 실행 속도가 **6분 39초에서 33초로 대폭 단축(약 12배 속도 개선)**되었으며, 백그라운드 스레드와의 DB 세션 정리 충돌로 발생하던 flaky 오류(`no such table: brands/users`)를 완벽히 종식시켰습니다.
