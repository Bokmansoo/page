# Sellform Sprint 24 Browser Assisted URL Collection Code Review

## 1. Overview
본 코드 리뷰는 **Sprint 24: Browser Assisted URL Collection** 구현 결과의 타당성 및 코드 품질을 평가합니다. 이번 스프린트에서는 쇼핑몰 크롤링 보안 제한으로 인해 자동 텍스트 수집이 막힌 경우, 사용자가 본 화면의 스펙 테이블이나 설명글을 드래그 복사해 오면 이를 실시간으로 여러 사실 카드 후보로 파싱하여 안전하게 DB에 적재하는 브라우저 보조 수집 협업 체계를 완성했습니다.

## 2. Key Changes

### A. 백엔드 벌크 파서 모듈 개발
- **[bulk_fact_parser.py](file:///c:/page/backend/src/services/bulk_fact_parser.py)**:
  - 사용자가 붙여넣은 지저분한 원문 텍스트 내에서 개별 상품 사실(Spec)을 발라내는 유틸리티 함수 `parse_bulk_fact_text`를 추가했습니다.
  - 줄바꿈 문자열 노멀라이즈 및 라인별 좌우 공백 정리를 수행합니다.
  - 문장 시작점에 섞여 있을 수 있는 특수 불릿 기호(`-`, `*`, `•`), 숫자, 마침표, 괄호 및 연속된 공백 문자들을 정규식(`r"^[\\-\\*\\•\\d\\.\\)\\s]+"` 패턴)로 깨끗하게 트리밍하여 실질적인 문장만 걸러냅니다.
  - 지나치게 짧은 줄(3자 미만)을 배제하고, 소문자 기준 공백 제거 키를 이용해 고유성(Deduplication)을 체크해 최대 N개(기본 50개)까지 유일한 스펙 행만 반환하도록 구현했습니다.

### B. 프론트엔드 브라우저 보조 수집 UI 콤보 추가
- **[BrowserAssistedSourcePanel.tsx](file:///c:/page/frontend/src/components/BrowserAssistedSourcePanel.tsx)**:
  - 브라우저 클립보드 복사본 붙여넣기 전용 컴포넌트를 설계했습니다.
  - 사용자가 붙여넣은 텍스트를 줄 단위 및 3자 이상 기준으로 분할 필터링해 임시 후보 리스트로 관리합니다.
  - 미리보기 테이블에서 개별 후보를 제거할 수 있는 제어 장치를 내장했습니다.
  - 저장 시 `/api/v1/projects/[id]/facts/bulk` 벌크 API를 호출하여 중복은 건너뛰고 새로운 팩트 후보들을 일괄 적재하며, 기본 상태는 사용자 검수를 유도하기 위해 `unknown`으로 등록합니다.
- **[page.tsx (facts)](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/facts/page.tsx)**:
  - `failed_sources` 결과에 `url` 수집 실패 사유가 포함되어 있을 때만 `BrowserAssistedSourcePanel`이 나타나도록 조건부 렌더링하고 콜백을 바인딩했습니다.
- **[page.tsx (new project)](file:///c:/page/frontend/src/app/workspace/projects/new/page.tsx)**:
  - URL 검증 차단 시나리오(`SOURCE_EXTRACTION_UNAVAILABLE`)가 유도되었을 때, 수동 상세 텍스트 수집 가이드 팁을 명확하게 리스트로 명시해 사용자 이탈을 방어했습니다.

## 3. Standard and Quality Review
- **타입 안정성**: 모든 React 컴포넌트 프롭 및 API 요청 본문의 타이핑이 명확히 선언되었습니다.
- **아키텍처적 일관성**: 브라우저 보안 규제를 불법적인 세션 우회 등으로 크래킹하지 않고, 클립보드와 브라우저 협업 흐름으로 처리해 법적/기술적 리스크를 최소화했습니다.

## 4. Conclusion
구현 사항은 완벽한 정합성을 갖추고 있으며, 빌드 및 단위/통합 테스트 검증이 모두 성공적으로 끝났습니다.
