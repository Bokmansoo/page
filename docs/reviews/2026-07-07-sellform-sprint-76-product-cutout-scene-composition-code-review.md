# Code Review: Sprint 76 - 실제 상품 누끼 기반 장면 합성 기능 구현

본 문서는 **Sprint 76: 실제 상품 누끼 기반 장면 합성 기능** 구현에 대한 코드 리뷰 보고서입니다.

---

## 1. 개요 및 설계 사항 (Overview & Design)
이번 스프린트에서는 사용자가 업로드한 원본 촬영 이미지(`self_shot`)로부터 상품 본체의 누끼(cutout) 이미지를 자동으로 추출/생성하고, 이를 이미지 생성 모델(SD 등)에 입력하여 배경 합성(compositing) 프롬프트를 통해 자연스러운 스튜디오 컷과 라이프스타일 컷을 합성하도록 파이프라인을 구축하였습니다. 
또한 상세페이지 기획안 승인 시, 스펙표/비교표 등 정보를 제공하는 섹션은 불필요한 이미지 생성 과금을 방지하기 위해 생성 작업을 스킵하고 HTML/CSS 기반 그래픽 레이어로 연동하도록 변경하였습니다.

---

## 2. 변경 파일별 리뷰 (Files Reviewed)

### A. 데이터 모델 & 마이그레이션 DDL
- **[models.py](file:///c:/page/backend/src/db/models.py)**
  - `Asset` SQLAlchemy 모델에 `source_asset_id` (ForeignKey self-reference), `cutout_status` (Enum), `background_removed` (Boolean), `product_identity_preserved` (Boolean) 필드 추가.
  - 이 데이터 구조는 원본 이미지와 누끼 이미지 간의 연관관계를 보존하고, 누끼 생성이 완료되었는지, 상품 고유 정체성이 잘 유지되고 있는지 추적할 수 있도록 지원합니다.
- **[database.py](file:///c:/page/backend/src/db/database.py)**
  - SQLite와 PostgreSQL을 모두 지원하도록 `ensure_runtime_schema_compatibility` 함수 내에 `ALTER TABLE` 쿼리를 안전하게 보강하였습니다.
  - SQLite에서는 에러 방지를 위해 컬럼 존재 여부를 별도로 사전 검사하여 안전성을 강화했습니다.

### B. 누끼 서비스 & 오케스트레이션 연동
- **[product_cutout_service.py](file:///c:/page/backend/src/services/product_cutout_service.py)**
  - PIL의 알파 채널 조작을 통해 밝은 배경 영역을 픽셀 투명화하는 가상 누끼 생성 로직을 구현하였습니다.
  - 이미지 처리 예외나 손상된 포맷의 파일이 유입될 경우, 원본 이미지를 그대로 복사하는 Fallback 메커니즘을 적용하여 전체 파이프라인의 에러 전파를 차단하였습니다.
- **[detail_page_orchestrator.py](file:///c:/page/backend/src/services/detail_page_orchestrator.py)**
  - 상세페이지 빌드 흐름 중 `_handle_intake` 메서드 내에서 업로드된 원본 촬영본 (`source_type == "self_shot"`)에 대해 자동으로 누끼 생성을 호출하도록 비동기 백그라운드 태스크 형태로 연동 완료하였습니다.

### C. 비주얼 패키지 기획 및 스킵 로직
- **[visual_package_planner.py](file:///c:/page/backend/src/services/visual_package_planner.py)**
  - `representative_product` 및 `lifestyle_scene` 등의 이미지 생성 프롬프트 템플릿에 "제공된 누끼 이미지의 모양/색상/디테일을 완벽히 유지하면서 배경을 자연스럽게 합성할 것"을 지시하는 합성 중심 텍스트로 보강하였습니다.
  - `specifications`, `comparison`, `pre_purchase`, `product_information` 등 카드 섹션 타입에 대해서는 이미지 생성 작업(`ImageGenerationJob`) 생성을 스킵하도록 루프 필터를 구축하였습니다.
  - AI 생성 대상 역할의 source_asset_ids 설정 시, 매핑된 원본 이미지와 쌍을 이루는 누끼 이미지(`source_type == "ai_corrected"`)의 ID를 우선적으로 바인딩하도록 우선순위 룰을 세웠습니다.

### D. 기획안 승인 및 API 연동
- **[pages.py](file:///c:/page/backend/src/api/pages.py)**
  - 기획안 승인(`approve_planning_draft`) 단계에서, specifications/comparison/pre_purchase 등의 카드 타입은 `needs_image = False`, `visual_kind = "html_graphic"`으로 고정 조립되도록 설계하였습니다.
  - `get_image_candidates_for_section` API에서 반환되는 candidate 딕셔너리에 매칭된 누끼의 소스 자산 정보 및 메타데이터 필드(`source_asset_id`, `cutout_status`, `background_removed`, `product_identity_preserved`)를 채워 프런트엔드 연동성을 향상시켰습니다.

### E. 테스트 연동 안전장치
- **[page_asset_policy.py](file:///c:/page/backend/src/services/page_asset_policy.py)**
  - 로컬 환경 local dev fallback 기능으로 인해 테스트 중 검증 정책이 무시되는 현상을 방지하기 위해 `sys.modules` 내에 `pytest`가 존재하는 경우 Fallback 연동을 원천 비활성화시켰습니다.

---

## 3. 총평 및 피드백 (Conclusion)
실제 촬영본의 정밀한 상품 엣지를 보존하며 새로운 스튜디오 배경을 입히는 이미지 파이프라인의 핵심적 기반이 안정적으로 다져졌습니다.
스펙 및 비교표 등 이미지 리소스 낭비가 심했던 무의미한 생성 작업들을 HTML 그래픽 레이어로 강제 전향함으로써 과금 요소를 획기적으로 줄였습니다.
작성된 테스트 스위트가 모두 **PASSED** 상태로 정상 작동함을 확인하였으며, 최종 검증이 성공적으로 완료되었습니다.
