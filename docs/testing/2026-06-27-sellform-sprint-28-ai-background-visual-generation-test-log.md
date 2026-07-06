# Sprint 28 - AI 배경 비주얼 생성 테스트 로그

## 1. 테스트 목적
AI 이미지 생성 API에 앞서, 상품 속성에 부합하는 안전한 배경 후보 시스템(Fallback)의 동작 및 page-editor 미리보기 반영, 이미지 Export 레이아웃 반영 여부를 테스트한다.

## 2. 백엔드 API & DB 검증
- **데이터베이스 마이그레이션**:
  - `ProductProject` 테이블에 `selected_background` 컬럼 추가를 `ensure_runtime_schema_compatibility`를 통해 런타임 호환되도록 처리함.
  - 마이그레이션 DDL이 로컬 PostgreSQL 상에서 예외 없이 동작함을 검증함 (`pytest` 107개 전원 통과).
- **배경 후보 생성 API (`POST /api/v1/projects/{project_id}/visual-backgrounds/generate`)**:
  - 호출 결과 기본 리빙 카테고리 테마인 3종 후보군(`cooling-blue`, `minimal-white`, `lifestyle-summer`)의 JSON 응답이 올바르게 생성되는 것을 검증함.
- **배경 선택 API (`POST /api/v1/projects/{project_id}/visual-backgrounds/{candidate_id}/select`)**:
  - `candidate_id` 유효성 체크 및 DB 내 `selected_background` 변경 완료를 검증함.
  - Audit Log 작성으로 감사 이력이 정상 로깅되는지 확인함.

## 3. Export 서비스 레이아웃 렌더링 테스트
- 첫 번째(히어로) 섹션에 배경 그라데이션(`linear-gradient`)이 수직으로 정상 렌더링됨.
- 본문 섹션(index > 0)에 옅은 파스텔 배경색이 채워지고, 텍스트 가독성을 위해 흰색 라운디드 카드형 레이아웃(`draw.rounded_rectangle`)이 씌워지는 것을 검증함.
- `cooling-blue` 및 `lifestyle-summer` 별로 프리미엄 액센트 텍스트 컬러(`Sleek Navy Blue`, `Warm Amber`)가 알맞게 변경되는 것을 확인하여 상세페이지의 완성도가 비약적으로 향상됨을 검증함.

## 4. 프론트엔드 UI/UX 테스트
- `page-editor` 우측 패널의 "글로벌 디자인 톤" 탭 하단에 **AI 배경 비주얼** 목록 카드가 정상 노출됨.
- 각 카드에서 추천 팔레트와 🛡️ 안전 유의사항(safety_note)이 명시적으로 노출되며 "선택" 클릭 시 프로젝트에 바로 기록됨.
- 중앙의 모바일 미리보기 패널에 실시간으로 수직 그라데이션 및 카드형 레이아웃 미리보기가 반영됨.
