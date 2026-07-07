# Code Review: Sprint 75 제품 기반 판매 카피 품질 개선

## 1. 개요 (Overview)
- **목적**: 상세페이지 및 기획 초안에 내부 지시문이나 금지 단어가 노출되지 않도록 품질 가드를 적용하고, 상품 사실(Fact) 및 컨텍스트를 정규화하여 품질을 개선합니다.
- **작업 범위**:
  - `CopyQualityGuard` 클래스 구현 및 연동 (Task 4)
  - `PageComposerService` 클래스 구현 (Task 2)
  - `PlanningDraftService` 한글 UTF-8 프롬프트 개선 및 Mock Fallback 교체 (Task 3)
  - `PageGenerationService` 시스템 프롬프트 지침 보강 및 품질 가드 연동
  - 품질 검증 테스트 작성 및 통과 (Task 1)

---

## 2. 주요 변경 사항 및 검토 (Key Changes)

### A. CopyQualityGuard 구현
- **경로**: [copy_quality_guard.py](file:///c:/page/backend/src/services/copy_quality_guard.py)
- **역할**:
  - **금지어 및 마커 필터링**: `정리합니다`, `보여주세요`, `안전한 표현`, `[AI 수정됨]`, `+`, `—` 등의 특수 기호와 기획 메타 텍스트를 제거하거나 위생화(Sanitization)합니다.
  - **과장 표현 검사**: `최고`, `완벽`, `무조건` 등 근거 없는 최상급 소구 표현을 검사하고 차단합니다.
  - **빈약한 제목 검사**: 5글자 미만의 짧거나 불완전한 제목을 차단하고, 각 섹션 유형과 카테고리에 맞는 기본 권장 카피(Default Safe Copy)로 우회(Fallback) 처리합니다.

### B. PageComposerService 구현
- **경로**: [page_composer_service.py](file:///c:/page/backend/src/services/page_composer_service.py)
- **역할**:
  - **사실 정규화 및 분류**: SQLAlchemy DB 모델 객체 및 Dictionary 타입 모두 호환되도록 사실 목록을 입력받아 `confirmed_facts`와 `needs_verification` 구조로 정규화합니다.
  - **우선순위화**: 크롤링 등 상품 링크에서 수집된 정보(`source == "url"`)를 최상단에 배치하여 AI 생성이 정밀한 상품 팩트에 기반하도록 유도합니다.
  - **사용자 입력 통합**: `raw_input_text` 외에도 `intake_snapshot`에 기록된 상품 옵션 및 이미지 설명을 컨텍스트로 병합합니다.

### C. 서비스 연동 및 프롬프트 개선
- **경로**: [planning_draft_service.py](file:///c:/page/backend/src/services/planning_draft_service.py)
  - 시스템 프롬프트를 한글 UTF-8로 선언하여 기획 지시문 배제 및 사실 기반 카피 작성 원칙을 Claude에 명시적으로 인스트럭션합니다.
  - 도구 강제 바인딩(Tool definition) 내 각 인풋 필드 설명을 고객 노출 중심 문구로 보강합니다.
  - Mock 모드에서도 내부 기획 가이드라인 대신 실제 가습기 등 상품 사실에 근거한 예시 판매 카피를 반환하도록 Fallback을 재구성하였습니다.
- **경로**: [page_generator.py](file:///c:/page/backend/src/services/page_generator.py)
  - `PageGenerationService` 내 시스템 프롬프트 가이드라인을 강화하고, 결과 획득 단계(Mock 및 Real 모드 전체)에 `CopyQualityGuard`를 연동하여 안정성을 이중으로 검증합니다.

---

## 3. 테스트 및 검증 결과 (Test & Verification)

### A. 신규 및 보강된 테스트
- **기획 초안 품질 테스트**: [test_planning_draft_service.py](file:///c:/page/backend/tests/test_planning_draft_service.py)
  - 기획 카드 내에 금지된 문자(`+`, `—`, `[AI 수정됨]`) 및 기획 지시문이 완전히 부재함을 확인하는 단언(Assert) 케이스 추가
- **페이지 구성 품질 테스트**: [test_page_composer_copy_quality.py](file:///c:/page/backend/tests/test_page_composer_copy_quality.py)
  - `PageGenerationService` mock 모드 결과에도 지시문 및 어색한 마커가 배제되는지 확인하고, `CopyQualityGuard` 유닛 테스트 수행

### B. pytest 결과
- `tests/test_planning_draft_service.py`와 `tests/test_page_composer_copy_quality.py` 모두 성공적으로 **통과(PASSED)**하였습니다.
- 기존의 레거시 figma 테스트 및 폐기된 `/ai-edit` 테스트 등 환경 의존적/전체 테스트 이외의 본 Sprint 기능 테스트는 전부 성공하였습니다.
