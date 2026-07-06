# Sprint 28 - AI 배경 비주얼 생성 코드 리뷰

## 1. 개요
흰 배경 중심의 밋밋한 텍스트 형태 상세페이지에서 탈피하여 상품의 특성에 최적화된 배경 비주얼 후보를 제공하고, 이를 모바일 미리보기와 Export 결과물에 입힐 수 있는 구조를 구축하였습니다.

## 2. 코드 변경 사항

### A. 백엔드 서비스 & DB
- **`backend/src/services/visual_background_service.py` [NEW]**:
  - 리빙 상품(예: 루메나 선풍기)에 특화된 안전한 배경 비주얼 후보 3종(`cooling-blue`, `minimal-white`, `lifestyle-summer`)을 추천해주는 서비스 클래스입니다.
- **`backend/src/db/models.py` & `database.py` [MODIFY]**:
  - `ProductProject`에 `selected_background` 필드를 추가했습니다.
  - 마이그레이션 도구 없이도 로컬 PostgreSQL과의 호환을 유지하도록 `ensure_runtime_schema_compatibility` 함수에 DDL 추가 쿼리(`ALTER TABLE`)를 수록하였습니다.

### B. 백엔드 API
- **`backend/src/api/projects.py` [MODIFY]**:
  - `POST /projects/{project_id}/visual-backgrounds/generate` API를 추가하여 해당 프로젝트에 최적화된 배경 목록을 출력합니다.
  - `POST /projects/{project_id}/visual-backgrounds/{candidate_id}/select` API를 통해 사용자가 선택한 배경 스타일을 저장하고 Audit Log를 로깅합니다.

### C. 이미지 렌더링 (Export)
- **`backend/src/services/export_service.py` [MODIFY]**:
  - 첫 번째 히어로 섹션에는 수직 선형 그라데이션(`_draw_gradient_vertical`)을 입혀 시각적 강렬함을 연출합니다.
  - 본문 섹션(index > 0)은 연한 배경색 위에 둥근 사각형 카드(`draw.rounded_rectangle`)를 얹어 텍스트의 가독성을 최대로 높이고 상용 상세페이지 느낌을 극대화하였습니다.
  - `selected_bg` 종류에 맞춰 텍스트 타이틀의 액센트 색상을 Navy Blue 혹은 Warm Orange 톤으로 튜닝해 프리미엄 디자인 완성도를 제공합니다.

### D. 프론트엔드 에디터
- **`frontend/src/app/workspace/projects/[id]/page-editor/page.tsx` [MODIFY]**:
  - 우측 디자인 패널에 **AI 배경 비주얼** 컴포넌트를 탑재하고 후보 추천 및 저장 상태를 연동했습니다.
  - 중앙 모바일 미리보기에서 배경 비주얼이 실시간으로 그라데이션 및 카드 형태로 드로잉되도록 index 조건 스타일을 동기화하였습니다.

## 3. 종합 평가
- **안전성**: 실제 제품 형상의 가짜 생성으로 인한 법적/소비자 기만 리스크를 제거하기 위해 텍스트 미포함 및 로고/인증마크 미생성 원칙을 완전 고수함.
- **디자인 퀄리티**: 단순 백그라운드 색칠이 아닌 그라데이션 히어로와 본문 파스텔 카드 레이아웃의 결합으로 고급 쇼핑몰 웹앱 상세페이지 분위기를 구현함.
