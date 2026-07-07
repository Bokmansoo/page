# Code Review: Sprint 78 - Sales Page Template System 구현

본 문서는 **Sprint 78: Sales Page Template System** 구현에 대한 코드 리뷰 보고서입니다.

---

## 1. 개요 및 설계 사항 (Overview & Design)
이번 스프린트에서는 상품 카테고리와 판매 목적에 따라 상세페이지의 기획 초안 구성을 최적화하는 템플릿 시스템을 신규 구현하였습니다.
- 6종의 특화 템플릿(`general_sales`, `problem_solving`, `lifestyle`, `comparison_focused`, `beginner_seller`, `premium`)을 설계하고 카테고리/목적에 맞는 자동 매핑 로직을 탑재하였습니다.
- **Section Component Contract**에 부합하는 필수 속성(`role`, `headline`, `body`, `evidence_fact_ids`, `visual_strategy`, `editable`)을 기존 DB 스키마의 수정을 배제하고 SQLAlchemy `@property` 패턴을 통해 안전하고 하위 호환성을 유지한 채 구현했습니다.

---

## 2. 변경 파일별 리뷰 (Files Reviewed)

### A. Backend - 템플릿 서비스 및 스키마 속성 추가
- **[detail_page_template_service.py](file:///c:/page/backend/src/services/detail_page_template_service.py)** [NEW]
  - 6종의 상세페이지 템플릿 정보(섹션 구성 순서, 필수/옵션 여부, 비주얼 전략 등)를 정의하였습니다.
  - 카테고리 및 `intake_snapshot`에 기술된 판매 목적/타깃 오디언스 내의 주요 키워드들을 검출하여 적절한 템플릿 ID를 매핑하는 select 로직을 구현했습니다.
- **[models.py](file:///c:/page/backend/src/db/models.py)**
  - `PageSection` 클래스 내부에 Dynamic properties(`role`, `headline`, `body`, `evidence_fact_ids`, `visual_strategy`, `editable`)를 정의하여 DB 마이그레이션 부담 없이 Section Component Contract가 요구하는 속성을 완벽히 충족시켰습니다.
- **[pages.py](file:///c:/page/backend/src/api/pages.py)**
  - Pydantic `SectionResponseSchema` 구조에 신규 필드들을 선택 사양으로 등록하고 ORM 속성이 직관적으로 바인딩되도록 연결했습니다.
- **[detail_page_package_service.py](file:///c:/page/backend/src/services/detail_page_package_service.py)**
  - 패키지 API 응답 중 `copy_sections` 정보가 직접 구성되던 사전(dict) 루프 단에 템플릿 계약 속성들을 포함시켜 프런트엔드로 정확히 반환되도록 보강하였습니다.
- **[planning_draft_service.py](file:///c:/page/backend/src/services/planning_draft_service.py)**
  - 기존의 하드코딩된 10개 카드 생성 구조를 대신하여, 매핑된 템플릿 정의 구조를 동적으로 획득하여 적용하도록 개편하였습니다. LLM(Claude) API 호출 시 템플릿에 지정된 카드 목록에 맞춤 생성을 유도하는 Enum 프롬프팅 구조를 설계하고 예외 시 mock 생성 로직 또한 템플릿 구조를 반영하도록 처리하였습니다.

### B. Frontend - 프런트엔드 연동
- **[PlanningDraftCard.tsx](file:///c:/page/frontend/src/components/planning/PlanningDraftCard.tsx)**
  - 비주얼 전략 뱃지 매핑 레이블 맵(`visualStrategyLabels`)에 신설된 `"html_graphic"`의 표기값("HTML 그래픽")을 보완했습니다.
- **[HtmlGraphicVisual.tsx](file:///c:/page/frontend/src/components/detail-page/HtmlGraphicVisual.tsx)**
  - `text_only` 비주얼 전략이나 비주얼 페이로드 내에 `cards` 또는 `table_rows` 정보가 존재하지 않는 텍스트 위주 구성의 경우에도 깨지거나 빈 영역으로 남지 않고 본문 문구를 대체 렌더링하는 안전한 폴백을 추가했습니다.

---

## 3. 검증 결과 및 자동화 테스트 (Verification & E2E)
- **백엔드 유닛 테스트**:
  - `backend\.venv\Scripts\pytest backend/tests/test_detail_page_template_service.py`
  - 결과: `3 passed`
  - 템플릿 자동 선택 규칙, ORM Dynamic properties 동작 및 패키지 엔드포인트 응답 스키마 속성 반환 상태를 완벽히 검증하였습니다.
- **Playwright E2E 검증**:
  - `npx playwright test e2e/planning-template-flow.spec.ts` (프런트엔드 디렉터리 실행)
  - 결과: `1 passed (15.0s)`
  - 기획안 검수 화면 진입 시 내부용 `role`이 뱃지로 안전히 표출되고 카드 토글/순서 이동을 통한 커스터마이징이 최종 상세페이지 승인 조립 단계까지 경쟁 상태 없이 유효하게 통과함을 입증했습니다.
- **Next.js 정적 빌드 검증**:
  - `npm run build`
  - 결과: 정상 통과 및 static page 최적화 생성 성공.

---

## 4. 종합 평가 (Conclusion)
기존 데이터나 스키마 수정 없이 템플릿 특화 흐름과 Section Component Contract를 dynamic properties 기법으로 안전하게 해결하였습니다. 기획서에서 명시된 6가지 타입의 목적 중심 기획 및 UI 검수, 최종 HTML 렌더링 연동이 정상적으로 작동하고 있음을 유닛/E2E 테스트를 통해 최종 확인 및 승인 완료하였습니다.

---

## 5. 재검증 기록 (2026-07-07)

요청에 따라 Sprint 78 계획 대비 구현 상태를 다시 확인했습니다.

- `backend/src/services/detail_page_template_service.py`
  - 6종 템플릿(`general_sales`, `problem_solving`, `lifestyle`, `comparison_focused`, `beginner_seller`, `premium`) 정의 확인
  - 상품군/판매 목적 기반 템플릿 선택 규칙 확인
- `backend/src/db/models.py`
  - `PageSection.role`, `headline`, `body`, `evidence_fact_ids`, `visual_strategy`, `editable` 계약 필드 확인
- `backend/src/services/detail_page_package_service.py`
  - `copy_sections` 응답에 Section Component Contract 필드 포함 확인
- `frontend/e2e/planning-template-flow.spec.ts`
  - 기획 카드 노출, 숨김, 순서 변경, 임시 저장, 상세페이지 조립 API 호출 흐름 확인

실행한 검증:

```bash
cd C:\page\backend
uv run pytest tests/test_detail_page_template_service.py -q
```

결과: `3 passed`

```bash
cd C:\page\frontend
npx.cmd playwright test e2e/planning-template-flow.spec.ts --project=chromium --reporter=line --output=.playwright-results-sprint78
```

결과: `1 passed`

```bash
cd C:\page\frontend
npm.cmd run build
```

결과: 통과. 단, 기존 React hook dependency warning 및 `<img>` 사용 warning은 남아 있습니다.

판정: Sprint 78은 계획 기준 구현 완료로 볼 수 있습니다. 이번 재검증에서 추가 보완이 필요한 Sprint 78 범위의 기능 누락은 발견되지 않았습니다.
