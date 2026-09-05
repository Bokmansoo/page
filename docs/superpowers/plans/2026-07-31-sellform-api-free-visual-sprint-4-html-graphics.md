# Sellform Sprint 4 핵심 섹션 HTML/CSS 그래픽 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 추가 사진이 부족해도 확인된 상품 정보로 빈칸 없는 상세페이지 본문을 만든다.  
**기간:** 1주  
**의존성:** Sprint 3 완료

## 범위

- 장점 카드, 수치 강조, 단계 안내, 스펙 표, 구성품과 CTA
- 사진 부족 시 HTML 그래픽 전환 규칙
- confirmed facts만 사용하는 payload 생성
- `benefit_cards` 템플릿

## 예상 수정 파일

- `backend/src/services/page_visual_contract.py`
- `backend/src/services/visual_contract_backfill.py`
- `backend/src/services/planning_draft_service.py`
- `backend/src/services/page_readiness_service.py`
- `frontend/src/components/detail-page/HtmlGraphicVisual.tsx`
- `frontend/src/components/detail-page/types.ts`
- 관련 backend 및 frontend 테스트

## 작업

### Task 1: 정보 그래픽 계약 강화

- [ ] `benefit_cards`, `comparison_cards`, `spec_table`, `steps` payload 스키마를 확정한다.
- [ ] 카드와 표의 각 값에 `source_fact_ids`와 확인 상태를 연결한다.
- [ ] 미확인 값은 판매 결과에서 제외한다.
- [ ] 빈 payload를 준비 완료로 판단하지 않는 테스트를 작성한다.

### Task 2: 자동 전환 규칙

- [ ] 사용 장면 사진이 없으면 단계 그래픽으로 전환한다.
- [ ] 상세 사진이 없으면 장점 카드 또는 스펙 표로 전환한다.
- [ ] 정보도 부족하면 섹션을 숨기고 판매자 체크리스트에 추가한다.
- [ ] 하나의 실제 상품 사진을 과도하게 반복하지 않도록 제한한다.

### Task 3: 공통 렌더러

- [ ] 장점 카드와 수치 강조 블록을 구현한다.
- [ ] 사용 단계와 스펙 표를 구현한다.
- [ ] 구성품 및 구매 전 확인 카드를 구현한다.
- [ ] 모든 한글과 수치는 HTML로 렌더링한다.
- [ ] 이미지 없는 HTML 그래픽을 누락 이미지로 계산하지 않는다.

### Task 4: 접근성과 반응형

- [ ] 작은 화면에서도 표와 카드가 읽히도록 재배치한다.
- [ ] 색상만으로 상태를 전달하지 않는다.
- [ ] 긴 제목과 수치에 대한 overflow 테스트를 추가한다.
- [ ] JPG 출력에서 카드가 페이지 밖으로 잘리지 않는지 확인한다.

## 완료 기준

- [ ] 상품 사진 한 장만으로 HERO와 핵심 본문이 완성된다.
- [ ] 빈 빨간 영역과 누락 이미지 오판이 없다.
- [ ] 확인되지 않은 수치와 구성품이 표시되지 않는다.
- [ ] 핵심 그래픽이 모바일과 JPG에서 읽을 수 있다.

## 다음 스프린트 인계

Sprint 5는 자동 조합된 이미지, 카드와 템플릿을 판매자가 직접 조정할 수 있게 한다.

