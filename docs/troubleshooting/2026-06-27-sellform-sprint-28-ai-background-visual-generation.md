# Sprint 28 - AI 배경 비주얼 생성 트러블슈팅

## 1. 로컬 데이터베이스 컬럼 추가 누락 이슈
- **문제 현상**: `ProductProject` DB 모델에 `selected_background` 컬럼을 신규 정의했으나, 기존 로컬 PostgreSQL DB 컨테이너에서 해당 컬럼이 없어 API 호출 시 `ProgrammingError`가 발생할 소지가 있음.
- **원인 분석**: SQLAlchemy의 `create_all()`은 신규 테이블은 생성하지만 기존 테이블에 대한 `ALTER TABLE` 마이그레이션을 자동으로 처리하지 못함.
- **해결 방안**: `backend/src/db/database.py`의 `ensure_runtime_schema_compatibility()` 함수 내부에 `selected_background` 컬럼 존재 여부를 수동 감지하고, 없을 시 DDL(`ALTER TABLE product_projects ADD COLUMN selected_background VARCHAR(100)`)을 동적 실행하도록 추가 작성함. 이를 통해 기존 로컬 DB 초기화 없이 즉각 반영에 성공함.

## 2. 프론트엔드 page-editor HTML 중복 및 꼬임 이슈
- **문제 현상**: page-editor 컴포넌트에 디자인 설정을 추가하는 과정에서 조건식 괄호와 `div` 닫는 태그가 일부 꼬여 글로벌 설정 패널이 잘못 중첩 렌더링되거나 타입 오류로 빌드가 되지 않는 컴파일 이슈 발생.
- **원인 분석**: 복잡한 React JSX 3단 패널 조건부 렌더링 로직(`activeTab === 'edit'`) 사이에 코드가 부적절하게 병합됨.
- **해결 방안**: 파일의 원본 구조를 Git 히스토리 및 이전 로그와 대조하고, 중복 주입된 `글로벌 디자인 톤` 찌꺼기 요소를 완전히 절제 및 삭제함. JSX 닫기 태그들과 분기 구조를 원래 상태에 맞춰 정밀 재설계하여 문법 완성도를 완벽히 함.

## 3. Pillow 렌더링 한글 가독성 및 그라데이션 성능 최적화
- **문제 현상**: 긴 세로 이미지를 병합하는 과정에서 배경색 대비로 인해 일부 연한 한글 텍스트의 가독성이 급감할 우려가 있었음.
- **원인 분석**: 그라데이션의 하단 톤이 너무 어둡거나 텍스트 액센트 색과 충돌하는 경우 가독성이 무너짐.
- **해결 방안**:
  - 첫 번째 섹션에 들어가는 수직 선형 그라데이션 색상을 연한 톤(예: `#EAF4FF` -> `#DDEBFF`)으로 좁게 유지함.
  - 액센트 텍스트 컬러를 배경 카테고리에 맞춰 가시성이 보장된 Sleek Navy Blue(`#1D4ED8`)와 Warm Amber(`#C2410C`)로 지정하여 가독성과 심미성을 동시에 보장함.
