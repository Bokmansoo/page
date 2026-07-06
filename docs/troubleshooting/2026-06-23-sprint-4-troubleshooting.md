# 트러블슈팅 로그: Sprint 4 (상세페이지 계획·생성·가이드형 편집)

- **작성일:** 2026-06-23
- **작성자:** AI (Antigravity)

---

## Issue 1. Pytest DB 독립 세션 격리로 인한 `AttributeError: 'NoneType' object` 에러

### 1. 현상 (Symptom)
*   `test_pages.py` 모듈 구동 시, 프로젝트 및 페이지를 데이터베이스에서 쿼리해오는 첫 단계인 `project = db_session.query(ProductProject).first()` 구문에서 `project` 객체가 `None`으로 반환되어 하위 필드 접근 시 에러가 발생함.

### 2. 원본 원인 (Root Cause)
*   pytest 환경에서는 매 테스트 함수 구동 시 독립 세션(Isolated Transaction) 단위로 데이터베이스가 롤백 및 초기화되므로, 이전 테스트 함수(예: `test_projects.py`)에서 성공적으로 생성되었던 데이터가 보존되지 않고 전부 사라짐.

### 3. 해결책 (Resolution)
*   각 테스트 함수 시작점에 Mock 헤더와 함께 **상위 API(`/api/v1/projects`)를 직접 호출하여 테스트용 격리 프로젝트를 생성**해 낸 뒤 그 반환된 ID(`p_id`)를 활용하도록 테스트 코드를 구조적으로 자급자족형(Self-bootstrapping)으로 개선함.

---

## Issue 2. Page 스냅샷 직렬화(Serialization) 실패 오류

### 1. 현상 (Symptom)
*   오토세이브 실행 시 백업본을 만드는 `create_page_snapshot` 과정에서, `json.dumps()` 연산 수행 도중 `TypeError: Object of type datetime is not JSON serializable` 오류가 발생함.

### 2. 원본 원인 (Root Cause)
*   SQLAlchemy 테이블 객체의 `created_at` 또는 `updated_at` 같은 `datetime` 속성이 데이터 직렬화 스냅샷 대상에 포함되었으나, 파이썬 표준 `json` 라이브러리는 `datetime` 객체를 자동으로 직렬화해주지 못함.

### 3. 해결책 (Resolution)
*   `create_page_snapshot` 헬퍼 함수에서 백업할 대상을 상세페이지 테마(`theme_color`, `font_family`) 및 섹션 구성정보의 필수 기초 타입(String, Integer, Boolean, JSON List)들로만 명확히 한정하고, 날짜 객체 등의 비호환 속성들은 백업 대상에서 배제하여 데이터 직렬화 정합성을 확보함.
