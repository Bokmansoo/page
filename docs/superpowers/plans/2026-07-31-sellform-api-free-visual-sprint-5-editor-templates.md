# Sellform Sprint 5 템플릿 및 판매자 편집 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 판매자가 코드 없이 자동 생성된 상품 사진 배치와 정보 그래픽을 조정하고 저장한다.  
**기간:** 1주  
**의존성:** Sprint 4 완료

## 범위

- 3개 템플릿 선택
- 섹션 이미지 교체와 위치·크기 조정
- 배경·팔레트·아이콘 변경
- 카드와 섹션 순서 편집
- 편집 저장, 되돌리기와 재진입

## 예상 수정 파일

- `frontend/src/components/ReviewEditorLayout.tsx`
- `frontend/src/components/VisualPackagePanel.tsx`
- `frontend/src/components/detail-page/DetailPageDocument.tsx`
- 신규 이미지 위치·템플릿 편집 컴포넌트
- `backend/src/api/pages.py`
- page version 및 snapshot 관련 서비스
- 관련 E2E 테스트

## 작업

### Task 1: 템플릿 선택

- [ ] `clean_product`, `benefit_cards`, `editorial_story`의 구조 차이를 정의한다.
- [ ] 템플릿 변경 전 미리보기를 제공한다.
- [ ] 템플릿 변경이 사실·문구·원본 이미지 데이터를 삭제하지 않게 한다.
- [ ] 기존 섹션을 새 템플릿에 안전하게 매핑한다.

### Task 2: 이미지 편집

- [ ] 섹션별 실제 이미지 교체 기능을 제공한다.
- [ ] 확대, 축소와 위치를 제한된 transform 값으로 저장한다.
- [ ] 상품이 프레임 밖으로 완전히 벗어나지 않도록 제한한다.
- [ ] 원본 이미지 파일은 변경하지 않는다.

### Task 3: 그래픽 편집

- [ ] 배경과 브랜드 팔레트를 변경한다.
- [ ] 장점 카드와 아이콘 순서를 변경한다.
- [ ] 섹션 표시 여부와 순서를 변경한다.
- [ ] 자동 조합 결과로 되돌리는 기능을 제공한다.

### Task 4: 저장과 버전

- [ ] 변경 사항을 canonical payload에 저장한다.
- [ ] 새로고침과 재진입 후 결과가 유지되는지 테스트한다.
- [ ] 저장 실패 시 화면 결과를 성공으로 표시하지 않는다.
- [ ] 직전 저장 버전으로 되돌릴 수 있게 한다.

## 완료 기준

- [ ] 판매자가 상품 이미지와 템플릿을 직접 교체할 수 있다.
- [ ] 이미지 위치, 배경과 카드 순서가 저장된다.
- [ ] 편집이 원본 상품 사진을 변경하지 않는다.
- [ ] 저장 후 재진입해도 동일한 결과가 보인다.

## 다음 스프린트 인계

Sprint 6은 편집 화면과 최종 PNG/JPG가 동일한 canonical renderer를 사용하도록 통합한다.
