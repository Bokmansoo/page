# Sellform Sprint 22 Living Golden Path UX Code Review

## 1. Overview
본 코드 리뷰는 **Sprint 22: Living Golden Path UX** 기획 및 실행 계획에 따라 진행된 프론트엔드 및 백엔드 주요 변경 사항을 검토합니다. 이번 스프린트에서는 사용자가 상품 링크 입력부터 상세페이지 저장 및 내보내기 단계에 이르기까지 진행 과정을 한눈에 파악하고, 각 단계의 요구 조건을 명확히 인지할 수 있도록 하는 UX 개선에 집중하였습니다.

## 2. Key Changes

### A. 공통 컴포넌트 개발 및 연동
- **[WorkflowStepHeader.tsx](file:///c:/page/frontend/src/components/WorkflowStepHeader.tsx)**: 전체 5단계 워크플로우를 가시화하고 현재 단계 및 이전 단계의 상태(완료, 진행 중, 대기)를 상태별 색상 및 애니메이션(펄스 효과)을 통해 명확히 전달하도록 구현했습니다.
- **[NextActionPanel.tsx](file:///c:/page/frontend/src/components/NextActionPanel.tsx)**: 현재 화면에서 수행해야 하는 액션 가이드라인을 동적으로 제시합니다. 백엔드 통신 오류 시 `serverError` 프롭을 통해 친숙한 사용자 안내 문구를 노출하며, 팩트 수 부족(3개 미만) 또는 카테고리 미확정 시 추가적인 경고(Warning) 체크리스트를 표시합니다.

### B. 각 페이지별 UX 연동 고도화
1. **사실 확인 페이지 ([page.tsx](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/facts/page.tsx))**:
   - `WorkflowStepHeader` 및 `NextActionPanel` 연동.
   - 확정 팩트 개수가 3개 이상이고 카테고리가 최종 확정된 경우에만 `검증 완료 및 다음 단계` 버튼이 활성화되도록 제어했습니다.
2. **스타일 선택 컴포넌트 ([StyleCandidateSelector.tsx](file:///c:/page/frontend/src/components/StyleCandidateSelector.tsx))**:
   - 팩트 3개 이상 확정 및 카테고리 확정 상태여야만 상세페이지 생성이 가능하도록 생성 버튼을 비활성화하고 가이드 캡션을 노출했습니다.
3. **상세페이지 에디터 페이지 ([page.tsx](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/page-editor/page.tsx))**:
   - 에디터 내 각 섹션의 본문 텍스트 길이를 공백 제외 20자 미만인 경우 감지하여, "이 섹션은 문구가 짧습니다. 핵심 사실과 사용 장면을 한 문장 더 추가해 보세요." 라는 실시간 품질 주의 배너를 렌더링합니다.
   - 우측 사이드바에 실시간 자동 저장 여부, 최종본 지정 여부, export 준비 전 단계에 대한 상태 요약 카드를 직관적으로 연동했습니다.
   - TypeScript 빌드 안정성을 확보하기 위해 명시적인 `any` 타입을 제거하고 `ProductProject` 및 `Fact` 인터페이스 타입을 추가 정의 및 적용하였습니다.
4. **내보내기(Export) 페이지 ([page.tsx](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/export/page.tsx))**:
   - `WorkflowStepHeader` 및 `NextActionPanel` 연동.
   - 최종본 지정 여부(`finalVersion !== null`)와 상세페이지 버전 수(`versionCount > 0`), 그리고 필수 체크리스트 항목 충족 여부를 결합하여 `판매처 이미지 패키지 생성` 버튼의 비활성화 조건을 세분화했습니다.
   - 활성화 조건 미충족 시 버튼 하단에 각 불충족 원인(버전 미생성, 최종본 미지정 등)을 사용자 친화적 문구로 정확히 표시하도록 캡션을 세분화했습니다.

## 3. Code Quality & Typesafe Review
- **ESLint 및 TypeScript 컴파일 검증**: `any` 타입을 걷어내고 상세한 도메인 인터페이스를 프론트엔드 코드에 정의함으로써 컴파일 타임 에러와 ESLint 컴파일 실패 문제를 사전에 방지했습니다.
- **백엔드 정합성**: 백엔드 API 연동 흐름은 유지하되, 프론트엔드에서 수신한 버전 데이터 및 규제 검수 결과를 바탕으로 안전한 조건 처리를 수행합니다.

## 4. Conclusion
본 변경 사항은 골든 패스 상에서 사용자가 마주할 수 있는 모호함을 해소하고, 다음 단계로 나아갈 수 있는 명확한 기준(사실 3개 이상, 카테고리 확정, 버전 존재, 최종본 지정)을 강제함으로써 고품질의 UX 플로우를 완성했습니다. 빌드 및 백엔드 테스트를 성공적으로 통과하여 즉시 머지 가능한 상태로 판단됩니다.
---

## 5. 후속 보완 리뷰 - Playwright E2E 골든패스 안정화 (2026-06-26)

### 변경 요약

- `@playwright/test`를 프론트엔드 개발 의존성으로 추가했습니다.
- [playwright.config.ts](../../frontend/playwright.config.ts)를 추가하여 Next.js 개발 서버를 자동 기동하고 Chromium 기준 E2E를 실행할 수 있게 했습니다.
- [sprint22-living-golden-path.spec.ts](../../frontend/e2e/sprint22-living-golden-path.spec.ts)를 추가하여 Sprint 22의 핵심 UX 가드레일을 자동 검증합니다.
  - 사실 확인 단계: 확정 사실 부족/카테고리 미확정 시 다음 단계 진행 제한
  - 상세페이지 에디터: 짧은 카피 경고 및 export 준비 상태 표시
  - export 단계: 최종본 지정 전 이미지 패키지 생성 제한
- E2E 중 발견된 안정성 이슈를 보완했습니다.
  - `facts/page.tsx`가 백엔드 응답에 `assets` 필드가 없을 때 `project.assets.length` 접근으로 런타임 크래시가 발생했습니다.
  - `ProductProject.assets`를 optional로 완화하고, 렌더링에서는 `const projectAssets = project.assets ?? []`를 사용하도록 수정했습니다.

### 리뷰 판단

Sprint 22는 기존 수동 QA 중심에서 벗어나 최소 핵심 골든패스 E2E가 추가되어 회귀 안정성이 높아졌습니다. 특히 이번 E2E가 실제 `assets` 누락 크래시를 발견했기 때문에, 단순 문서 보완이 아니라 제품 안정성에 직접 기여한 보완으로 판단합니다.

### 검증 결과

- `npm.cmd run test:e2e` — PASS, 3 passed
- `npm.cmd run build` — PASS

### 남은 리스크

- 현재 E2E는 API를 mock 처리하므로 실제 FastAPI + DB + 업로드 파일까지 포함한 통합 시나리오는 별도 Sprint에서 보강하는 것이 좋습니다.
- `npm install` 과정에서 npm audit 취약점 5건이 보고되었지만, 의존성 강제 수정은 breaking risk가 있어 이번 Sprint 22 안정화 범위에서는 조치하지 않았습니다.
