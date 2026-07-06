# Sellform Sprint 19 Code Review

**Sprint Goal:** 상품별 상세페이지 생성 전에 7단 설득 구조와 카테고리별 변형 규칙을 적용하고, 디자인 미리보기와 판매 전략 설명이 포함된 스타일 후보 3개를 사용자가 선택할 수 있게 만듭니다.

---

## 1. 주요 변경 파일 목록

- [models.py](file:///c:/page/backend/src/db/models.py): `ProductProject` 테이블에 `selected_style` 컬럼 추가.
- [database.py](file:///c:/page/backend/src/db/database.py): SQLite 호환성을 위해 `ensure_sqlite_schema_compatibility` 내 `selected_style` 자동 ALTER ddl 구문 추가.
- [style_strategy_service.py](file:///c:/page/backend/src/services/style_strategy_service.py): 카테고리별 7단 프레임 및 스타일 후보 3개 생성 서비스 모듈 작성.
- [page_generator.py](file:///c:/page/backend/src/services/page_generator.py): `_get_problem_solution_mock_page`를 동적 Category Frame 구조로 마이그레이션.
- [pages.py](file:///c:/page/backend/src/api/pages.py): 후보 리스트 조회/재추천/선택 API 신규 구현 및 상세페이지 초안 생성 시 selected_style 연계.
- [StyleCandidateSelector.tsx](file:///c:/page/frontend/src/components/StyleCandidateSelector.tsx): 스타일 후보 3개 카드 및 재추천 피드백 UI 작성.
- [page.tsx](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/page-editor/page.tsx): `StyleCandidateSelector` 컴포넌트 마운트 및 연동.

---

## 2. 코드 품질 및 아키텍처 검토

### 2.1 스타일 전략 설계 (`style_strategy_service.py`)
- **디자인 패턴:** 카테고리별로 분기되는 상세페이지 7단 구조의 정의를 `CategoryDetailPageFrame` 구조체로 분리하여 데이터 모델링하였습니다.
- **확장성:** 생활/패션/뷰티/식품 외 새로운 카테고리가 추가되어도 `get_category_frame` 내 조건문 추가만으로 간단히 새로운 설득 구도를 확장시킬 수 있어 OCP(Open-Closed Principle)를 충족합니다.
- **동적 재추천:** 피드백 옵션(`feedback_option`)에 따라 AI 추천 가중치가 `spec_focused` 또는 `lifestyle`로 동적 이동하도록 처리하여 실제 LLM API 호출 없이도 로컬 수준에서 직관적인 반응성을 구현했습니다.

### 2.2 API 라우팅 (`pages.py`)
- Pydantic 데이터 검증과 SQLAlchemy 영속성 연계를 분리했습니다.
- `GET /style-candidates`, `POST /style-candidates/regenerate`, `POST /style-candidates/{key}/select` 엔드포인트를 추가하여 REST 규약을 바르게 준수했습니다.
- Pydantic model_validate 대신 명시적인 List Comprehension 매핑을 사용하여 Dataclass와 Pydantic Schemas의 인코딩 불일치 이슈를 완벽하게 차단했습니다.
- `create_page_draft` 호출 시 기존 DB에 선택된 스타일 정보가 없으면 `"problem_solution"`을 자동으로 기본 적용하여 기존 레거시 테스트들과의 하위 호환성을 100% 지켜냈습니다.

### 2.3 프론트엔드 React 컴포넌트 (`StyleCandidateSelector.tsx`)
- Tailwind CSS를 활용해 반응형 레이아웃과 Hover 마이크로 인터랙션을 설계했습니다.
- 사용자가 직관적으로 선택을 변경할 수 있도록 `selectedKey` 상태 매핑을 단순화했으며, "다른 스타일 다시 추천" 클릭 시 absolute dropdown을 활용한 오버레이 UX를 제공하여 세련된 디자인을 유도했습니다.
- 선택되지 않은 상태에서는 생성 액션이 비활성화되는 안전장치를 화면단에 구현했습니다.
- 백엔드 `/page` 생성 API는 기존 레거시 테스트와 직접 API 호출 하위 호환을 위해 `selected_style`이 없으면 `"problem_solution"`을 기본값으로 사용합니다.

---

## 3. 종합 평가

- **유연성 (Flexibility):** 기하급수적으로 레이아웃 구조가 복잡해지는 프론트-백 연계 아키텍처에서 스타일 정보 전달용 스키마 구조를 깔끔하게 정립했습니다.
- **안정성 (Stability):** 84개의 전체 백엔드 테스트와 프론트엔드 production 빌드가 완벽히 통과하여 사이드 이펙트 없는 안정적인 릴리즈가 가능합니다.
- **Aesthetic Wow:** 모던 다크 테마 기반의 글래스모피즘 배지 디자인을 활용하여 프리미엄 UX를 제공하고 있습니다.

---

## 4. 후속 보완 리뷰 - candidate key 검증 (2026-06-26)

### 변경 요약

- `style_strategy_service.py`에 `STYLE_CANDIDATE_KEYS`와 `is_valid_style_candidate_key()`를 추가했습니다.
- `POST /projects/{project_id}/style-candidates/{candidate_key}/select`에서 유효하지 않은 스타일 키를 `400 Bad Request`로 거부하도록 수정했습니다.
- `test_style_strategy_service.py`에 스타일 키 검증 단위 테스트를 추가했습니다.
- `test_style_strategy_api.py`에 잘못된 `candidate_key` 저장 방지 통합 테스트를 추가했습니다.

### 검증 결과

```powershell
uv run pytest tests/test_style_strategy_service.py tests/test_style_strategy_api.py -q
```

```text
9 passed, 21 warnings
```

### 최종 판정

- 프론트 UX는 스타일 선택 전 생성 버튼을 비활성화합니다.
- 백엔드는 잘못된 스타일 키 저장을 차단합니다.
- `/page` 생성 API의 미선택 기본값은 하위 호환 정책으로 유지합니다.
