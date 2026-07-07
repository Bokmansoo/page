# Code Review: Sprint 77 - AI 대본 버전 수정 및 비교 적용 기능 구현

본 문서는 **Sprint 77: AI 대본 버전 수정 및 비교 적용** 구현에 대한 코드 리뷰 보고서입니다.

---

## 1. 개요 및 설계 사항 (Overview & Design)
이번 스프린트에서는 사용자가 직접 수기(수동) 수정한 대본을 기준으로 목적별 AI 수정 제안을 받을 수 있는 preview API 파이프라인을 보강하고, 제안 수락 전에 즉시 덮어씌워지지 않도록 "수정 전/후 비교 모달" UI를 신규 구축하였습니다. 
수동 수정 중인 문구가 유실되거나 덮어씌워지는 부작용을 원천 차단하기 위해 입력값 보존 정책 및 적용 전 PATCH 금지 규칙을 설계 및 검증하였습니다.

---

## 2. 변경 파일별 리뷰 (Files Reviewed)

### A. AI Copy Rewrite 프리셋 및 스키마 확장
- **[copy_rewrite_service.py](file:///c:/page/backend/src/services/copy_rewrite_service.py)**
  - `CopyRewriteCommand` Enum에 기획서에 명시된 8가지 목적별 프리셋을 정의하였습니다.
    - 강한 구매 설득 버전: `stronger_persuasion`
    - 짧고 임팩트 있는 버전: `shorter_impact`
    - 초보 셀러 자연스러운 버전: `beginner_seller_tone`
    - 프리미엄 브랜드 톤: `premium_brand_tone`
    - 쿠팡/스마트스토어 최적화 버전: `marketplace_optimized`
    - 과장 줄인 신뢰형 버전: `trust_oriented`
    - 감성 라이프스타일 버전: `emotional_lifestyle`
    - 구매 불안 감소 버전: `reduce_purchase_anxiety`
  - `CopyRewriteResult` response 스키마 구조에 `before`, `after`, `rationale`, `safety_notes` 필드를 추가하여 수정본의 차이점을 명확히 객체 형태로 분리 반환하도록 확장하였습니다.
  - `_MOCK_RESULTS` 및 `_build_user_prompt`에 프리셋 문구들과 매칭되는 구체적인 프롬프트 작성 지침을 구축했습니다.

### B. Preview API 보강 및 수동 수정 보존
- **[pages.py](file:///c:/page/backend/src/api/pages.py)**
  - `/copy-rewrite/preview` Request Payload(`CopyRewritePreviewRequest`)에 `title` 및 `body_copy` 필드를 선택사항으로 추가하였습니다.
  - API 컨트롤러 단에서 사용자가 입력창에 수정 중인 문구(현재 편집본)를 전달하는 경우, DB의 기존 저장값보다 우선적으로 사용하여 AI의 Rewrite Source로 매핑하였습니다. 이를 통해 사용자가 편집한 노력이 온전히 보존됩니다.

### C. 비교 모달 및 UI 흐름 구현
- **[AiCopyRewriteCompareModal.tsx](file:///c:/page/frontend/src/components/AiCopyRewriteCompareModal.tsx)** [NEW]
  - 수정 전(입력값)/수정 후(제안값) 카드 및 주의 사항(Warning) 영역을 시각적으로 정밀 구분한 side-by-side 레이아웃 컴포넌트를 설계하였습니다.
  - `이 수정안 적용`, `다시 생성` (재시도), `취소` 버튼들을 명시적으로 배치해 UX 계약 사항을 충실히 준수하였습니다.
- **[AiEditCommandPanel.tsx](file:///c:/page/frontend/src/components/AiEditCommandPanel.tsx)**
  - Preset 버튼 및 직접 요청 버튼 클릭 시 DOM으로부터 현재 입력된 `#section-title-edit` 및 `#section-body-edit` 값을 긁어와 API Body로 전달하도록 연동했습니다.
  - 모달의 "다시 생성(onRetry)" 핸들러를 바인딩하여, 사용자가 프리뷰 화면에서 즉시 재생성을 요청할 수 있는 흐름을 구현하였습니다.
- **[DetailPagePackageEditor.tsx](file:///c:/page/frontend/src/components/DetailPagePackageEditor.tsx)**
  - 보완 리뷰에서 발견된 구형 `ai-edit` 직접 실행 경로를 제거하고, 비교 모달의 `이 수정안 적용` 버튼이 눌렸을 때만 `/page` PATCH로 섹션 제목/본문을 저장하도록 연결했습니다.
  - 이로써 신형 검수 페이지뿐 아니라 패키지 에디터 재사용 경로에서도 Sprint 77의 “미리보기는 읽기 전용, 적용 버튼에서만 저장” 계약을 동일하게 지킵니다.

---

## 3. 검증 결과 및 자동화 테스트 (Verification & E2E)
- **백엔드 유닛 테스트**:
  - `uv run pytest tests/test_copy_rewrite_preview.py -q`
  - 결과: `2 passed, 18 warnings`
  - 8종의 프리셋 응답 유효성, `[AI 수정됨]` 마커 정제 여부 및 수동 수정 전달 기능을 검증했습니다.
- **Playwright E2E 검증**:
  - `npx.cmd playwright test e2e/review-editor-reframe.spec.ts --project=chromium --reporter=line --output=.pw-results-sprint77`
  - 결과: `1 passed`
  - React state와 비동기 PATCH 간의 경쟁 상태를 `blur()` 및 `waitForResponse()`로 제어하고, "이 수정안 적용" 버튼 클릭 시에만 서버에 최종 PATCH가 가해지는 전체 라이프사이클을 검증했습니다.
- **프런트엔드 정적 검증**:
  - `npm.cmd run lint`
  - 결과: 통과. 기존 `<img>` 사용 및 hook dependency 관련 warning만 남아 있으며 Sprint 77 차단 에러는 없습니다.
- **빌드 검증 상태**:
  - 이번 보완 리뷰에서는 `npm run build`를 완료 검증으로 사용하지 않았습니다. 이전 세션에서 Next build가 장시간 멈춘 이력이 있어 별도 빌드 안정화 이슈로 분리합니다.

---

## 4. 종합 평가 (Conclusion)
사용자가 직접 수정한 입력본을 Rewrite Source로 인지하고, 비교 모달에서 확인한 뒤에만 저장하는 Sprint 77 핵심 계약은 보완 후 충족되었습니다. 다만 실제 프로덕션 빌드 안정성은 이번 스프린트의 승인 조건에서 제외하고 별도 이슈로 관리하는 것이 안전합니다.
