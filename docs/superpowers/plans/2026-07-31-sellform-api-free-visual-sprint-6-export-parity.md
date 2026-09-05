# Sellform Sprint 6 미리보기와 PNG/JPG 출력 일치 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 판매자가 편집 화면에서 본 결과와 다운로드 파일을 실질적으로 동일하게 만든다.  
**기간:** 1주  
**의존성:** Sprint 5 완료

## 범위

- canonical renderer 단일화
- 이미지·폰트·SVG 로딩 완료 신호
- JPG 배경·품질과 PNG 출력
- export blocker 및 실패 처리
- 시각 회귀 테스트

## 예상 수정 파일

- `frontend/src/components/detail-page/DetailPageDocument.tsx`
- `frontend/src/app/export-render/projects/[id]/page.tsx`
- `frontend/src/app/workspace/projects/[id]/export-render/page.tsx`
- `backend/src/services/export_service.py`
- `backend/src/services/page_readiness_service.py`
- `backend/src/api/exports.py`
- export 관련 pytest 및 Playwright E2E

## 작업

### Task 1: 단일 렌더러

- [ ] 결과 화면, 편집기와 export route의 렌더러 사용 경로를 조사한다.
- [ ] 세 화면이 동일한 `DetailPageDocument`와 시각 계약을 사용하게 한다.
- [ ] export 전용 데이터 변환으로 레이아웃이 달라지지 않게 한다.
- [ ] 편집 컨트롤은 DOM에서 명확한 export 제외 속성을 사용한다.

### Task 2: 준비 상태

- [ ] 이미지, 웹폰트와 SVG가 모두 로딩된 후 `data-export-ready=true`를 설정한다.
- [ ] 이미지 오류가 있으면 준비 완료로 전환하지 않는다.
- [ ] 제한 시간 초과 시 실패 자산과 섹션을 응답한다.
- [ ] Playwright 브라우저 미설치 오류를 별도로 구분한다.

### Task 3: 출력 포맷

- [ ] JPG는 불투명 배경과 설정된 품질을 사용한다.
- [ ] PNG는 동일 viewport와 레이아웃을 사용한다.
- [ ] 긴 상세페이지의 전체 높이를 안정적으로 캡처한다.
- [ ] 파일명, MIME type과 다운로드 이력을 정확히 저장한다.

### Task 4: 회귀 검사

- [ ] HERO, 카드, 표, 실제 상품 이미지 기준 E2E fixture를 만든다.
- [ ] 미리보기와 export의 핵심 박스 위치·크기를 비교한다.
- [ ] 내부 배지, 버튼과 후보 패널이 출력되지 않는지 확인한다.
- [ ] 실패 다운로드가 깨진 파일을 반환하지 않는지 확인한다.

## 완료 기준

- [ ] 미리보기와 JPG의 주요 배치가 일치한다.
- [ ] 모든 이미지와 폰트가 로딩된 후 캡처된다.
- [ ] 내부 UI와 개발 표식이 출력되지 않는다.
- [ ] PNG/JPG 실패 원인이 사용자에게 구체적으로 표시된다.

## 다음 스프린트 인계

Sprint 7은 완성된 흐름을 기준 상품 3종으로 반복 검증해 공통 품질 문제를 해결한다.

