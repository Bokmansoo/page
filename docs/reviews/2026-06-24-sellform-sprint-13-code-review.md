# 코드 리뷰: Sellform Sprint 13 (Problem-Solution Narrative Template)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | narrative_template API schema, problem_solution mock & fallback, page editor UI select & layout rebuild trigger |
| 리뷰어 | Codex (Antigravity AI Agent) |
| 상태 | 승인 대기 |

## 1. 변경 요약

본 변경 사항은 상세페이지 제작 시 단순 시각적인 테마 프리셋 외에도, 고객을 설득하는 논리적인 내러티브(구성 섹션 순서 및 의미)를 분리 설정하여 생성할 수 있는 구조를 제공합니다. 첫 번째 시도로 문제 제기형 설득 구조(`problem_solution`)를 도입하고 UI와 유기적으로 연동되도록 하였습니다.

- **[api/pages.py](file:///c:/page/backend/src/api/pages.py)**:
  - `CreatePageRequest` pydantic 스키마에 `narrative_template` (기본값 `"category_default"`) 추가.
  - POST `/projects/{project_id}/page` API 내부에서 해당 파라미터를 추출하여 `PageGenerationService`에 바인딩 전달.
- **[services/page_generator.py](file:///c:/page/backend/src/services/page_generator.py)**:
  - `generate_page()` 및 `_get_mock_page()` 파라미터 시그니처에 `narrative_template` 인수 통합.
  - `problem_solution` 요청이 감지되면 7가지 논리 섹션(`problem_statement`, `main_claim`, `secondary_benefit`, `main_claim_support`, `benefit_list`, `summary_claim`, `product_information`)을 확정적 순서로 구성하는 `_get_problem_solution_mock_page()` 헬퍼 메서드 추가.
  - LLM system prompt 조정을 위해 `_get_narrative_template_instruction()` 헬퍼 메서드를 추가하여 7대 구성 규약을 Claude API에 지시하고, input schema descriptions(section_type)도 추가 템플릿용 값을 지원하도록 명세 변경.
- **[test_pages.py](file:///c:/page/backend/tests/test_pages.py)**:
  - `problem_solution` 템플릿 호출 시 올바른 7대 섹션 종류 및 순서로 데이터가 생성되는지 검증하는 단위/통합 테스트 추가.
- **[page-editor/page.tsx](file:///c:/page/frontend/src/app/workspace/projects/[id]/page-editor/page.tsx)**:
  - `narrativeTemplate` 리액트 로컬 상태 정의.
  - 초안 비생성 화면("초안 생성하기" 위) 및 우측 글로벌 설정 사이드바("글로벌 디자인 톤" 아래)에 템플릿 선택 Dropdown UI 배치.
  - 3단 에디팅 사이드바 내에서 템플릿 구조를 변경하고 바로 갱신할 수 있는 "구조 재생성" 버튼 연동 완료.

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| `problem_solution` 템플릿 섹션 순서 보장 | **충족 (PASS)** | `test_pages.py` 통합 테스트가 7개 고정형 순서(`problem_statement` ~ `product_information`)를 엄격히 검증. |
| 확정된 사실(Confirmed Facts)만 카피에 사용 | **충족 (PASS)** | generator 내부 팩트 격리 규칙 및 기존 auto-extract validation을 우회하지 않고, confirmed ID와 associated_fact_ids가 mock/AI API 양쪽에서 모두 매핑 보장됨을 확인. |
| API `narrative_template` 하위 호환성 | **충족 (PASS)** | `category_default` 기본값으로 기존 프로젝트 생성 파이프라인의 무중단 운영 확보. |
| UI 템플릿 선택 및 구조 재생성 | **충족 (PASS)** | 리액트 Dropdown 및 POST request body에 `narrative_template` 정상 주입 및 프론트 컴파일 무결성 확인. |
| 결정 및 문서 관리 | **충족 (PASS)** | ADR, 테스트 로그, 트러블슈팅, 코드 리뷰 작성 완수. |

## 3. 핵심 아키텍처 및 보안 피드백

### 3.1 관심사의 분리 (Separation of Concerns)
- `style_preset`은 UI 테마 및 번역/카피 라이팅의 어조(Tone of Voice)를 전담하고, `narrative_template`은 논리적 섹션 정보 배열(Layout Structure)을 전담하도록 아키텍처적 경계를 분명히 나눈 것은 좋은 결정입니다. 향후 새로운 내러티브 프레임워크(예: 스펙 비교형, 사용 장면형 등)를 추가하더라도 기존 시각 스타일 라이브러리를 그대로 재사용할 수 있습니다.

### 3.2 LLM 안정성 장치 (Fallback Isolation)
- 외부 Anthropic API 키 유실 혹은 RAG 런타임 오류 발생 시, 7개 고정 섹션 구조를 온전하게 보장하는 `_get_problem_solution_mock_page()` Fallback이 완벽히 동작하여 에디터 렌더링 크래시를 원천 차단하고 있습니다.

## 4. 결론

- 본 Sprint 13 구현 변경 건은 상세페이지 생성 비즈니스 로직의 확장성과 안정성을 크게 증대하였으며, 컴파일 및 회귀 테스트를 정상 통과하였으므로 master 브랜치로의 머지(Merge)를 강력히 권장합니다.
# 재검토 결과 (2026-06-24)

## 판정: 보완 필요

기본 API 전달, Mock/Fallback 7개 섹션 생성, 페이지 에디터 선택 UI, 문서 산출물은 구현되어 있다. 다만 아래 항목은 Sprint 13 실행계획의 완료 기준을 완전히 충족하지 못한다.

### 🟠 M1. 카테고리별 소구점 변형 규칙이 문제 제기 제목에만 적용됨

- 위치: `backend/src/services/page_generator.py:_get_problem_solution_mock_page`
- 계획: Fashion, Beauty, Food, Living 카테고리마다 문제 제기와 핵심 소구점의 변형 규칙을 둔다.
- 현재: `problem_title_by_category`로 `problem_statement` 제목만 카테고리별로 바뀐다. `main_claim`, `secondary_benefit`, `main_claim_support`, `benefit_list`, `summary_claim`은 모든 카테고리에 동일한 범용 문구다.
- 영향: 문제 해결형을 선택해도 상품 카테고리에 맞는 설득 흐름이 충분히 달라지지 않는다.
- 권고: 카테고리별 `problem_statement`, `main_claim`, `secondary_benefit` 문구/가이드 맵을 분리하고, 사실 카드가 부족한 경우에는 일반화된 효능 표현을 만들지 않도록 사실 기반 문장만 조합한다.

### 🟠 M2. 실제 Anthropic 생성 경로에서 7개 섹션 순서를 서버가 검증하지 않음

- 위치: `backend/src/services/page_generator.py:generate_page`
- 계획: `problem_solution` 요청은 정해진 7개 섹션 순서로 생성한다.
- 현재: 프롬프트와 도구 설명에는 순서가 적혀 있지만, LLM 응답 뒤에는 일반 `GeneratedPageSchema.model_validate()`만 수행한다. 따라서 실제 LLM이 누락·중복·순서 변경 응답을 주더라도 그대로 저장된다. 현재 테스트도 Mock/Fallback 경로만 검증한다.
- 영향: API 키를 연결한 운영 환경에서 템플릿의 핵심 구조가 깨질 수 있다.
- 권고: `problem_solution` 전용 섹션 타입 상수와 순서 검증을 추가하고, 불일치하면 안전한 Mock/Fallback으로 전환한다. LLM 응답 순서 불일치 테스트도 추가한다.

### 🟡 m1. `narrative_template` 입력값 검증이 없음

- 위치: `backend/src/api/pages.py:CreatePageRequest`
- 현재: 임의 문자열도 허용되며, 오타는 조용히 `category_default` 동작으로 처리된다.
- 권고: `Literal` 또는 Enum으로 `category_default`, `problem_solution`만 받도록 제한하고 422 응답 테스트를 추가한다.

## 재검증 증적

- `uv run --project backend pytest backend/tests/test_pages.py -q` → `4 passed`
- `uv run --project backend pytest -q` → `58 passed`
- `npm.cmd run build` (`frontend`) → 성공

테스트와 빌드는 통과했지만, 위 M1·M2는 테스트가 다루지 않는 구현 누락이므로 Sprint 13은 보완 후 완료 처리하는 것을 권고한다.
# Sprint 13 보완 완료 재리뷰 (2026-06-24)

## 최종 판정: PASS

이전 재검토에서 확인한 M1, M2, m1을 모두 조치했다.

| 항목 | 조치 | 검증 |
| --- | --- | --- |
| M1 카테고리별 소구점 | Fashion/Beauty/Food/Living별 메인 소구점, 설명, 보조 장점 제목을 분리했다. | 카테고리별 `main_claim` 제목·본문 차이 테스트 통과 |
| M2 운영 LLM 구조 보장 | `problem_solution` 응답의 7개 섹션 타입·순서와 fact ID를 서버에서 검증한다. 불일치 시 기존 예외 처리로 Mock/Fallback 페이지를 반환한다. | 잘못된 LLM 섹션 순서가 fallback으로 전환되는 테스트 통과 |
| m1 템플릿 입력 검증 | API 요청을 `category_default`, `problem_solution` Literal 값으로 제한했다. | 알 수 없는 템플릿 요청이 422를 반환하는 테스트 통과 |

### 최신 검증 증적

- `uv run --project backend pytest backend/tests/test_pages.py -q` → `7 passed`
- `uv run --project backend pytest -q` → `61 passed`
- `npm.cmd run build` (`frontend`) → 성공

기존 경고는 FastAPI TestClient, Pydantic V2 Config, `datetime.utcnow()`, `google.generativeai` 사용 중단 예고에 관한 기존 경고이며 이번 보완의 실패 항목은 아니다.
