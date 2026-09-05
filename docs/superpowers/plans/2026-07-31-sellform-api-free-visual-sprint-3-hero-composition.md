# Sellform Sprint 3 HERO 비주얼 자동 조합 MVP 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 확정된 대표 상품 사진 한 장과 HTML/CSS/SVG만으로 완성도 있는 HERO를 만든다.  
**기간:** 1주  
**의존성:** Sprint 2 완료

## 범위

- `composed_product` 시각 계약
- `clean_product` HERO 레이아웃
- 상품 `contain` 배치와 텍스트 안전 영역
- 배경·그림자·장식 토큰
- 미리보기와 export 공통 렌더링

## 예상 수정 파일

- `backend/src/services/page_visual_contract.py`
- `backend/src/services/visual_package_planner.py`
- `backend/src/services/page_generator.py`
- `frontend/src/components/detail-page/types.ts`
- `frontend/src/components/detail-page/DetailPageDocument.tsx`
- 신규 `frontend/src/components/detail-page/ComposedProductVisual.tsx`
- `frontend/src/app/globals.css`

## 시각 계약

```json
{
  "visual_kind": "composed_product",
  "image_asset_id": "asset-main",
  "visual_payload": {
    "layout_variant": "hero_product_right",
    "product_fit": "contain",
    "text_safe_area": "left",
    "background_token": "surface_mint",
    "decoration_tokens": ["soft_circle", "accent_line"]
  }
}
```

## 작업

### Task 1: 백엔드 계약

- [x] `composed_product`를 정상 완료 시각으로 인정하는 테스트를 작성한다.
- [x] 대표 이미지와 템플릿에 따라 HERO payload를 결정론적으로 생성한다.
- [x] 이미지가 없거나 품질 경고가 심하면 준비 완료로 판정하지 않는다.
- [x] 기존 `image` HERO를 호환 렌더링한다.

### Task 2: HERO 렌더러

- [x] 상품을 왜곡하지 않는 `object-fit: contain`을 기본값으로 사용한다.
- [x] 좌측 텍스트·우측 상품, 중앙 상품·하단 텍스트 변형을 구현한다.
- [x] 제목, 본문과 배지는 실제 DOM 텍스트로 렌더링한다.
- [x] CSS 배경, 그림자와 SVG 장식을 적용한다.
- [x] 상품 사진과 텍스트가 겹치지 않도록 안전 영역을 제한한다.

### Task 3: 반응형 및 export

- [x] 모바일과 고정 export 폭에서 레이아웃을 테스트한다.
- [x] 이미지 로딩 완료 신호를 export 준비 상태에 연결한다.
- [x] 미리보기·결과·export route가 같은 HERO 컴포넌트를 사용하게 한다.
- [x] 편집 배지와 선택 테두리가 export에 포함되지 않게 한다.

## 완료 기준

- [x] 외부 이미지 API 없이 실제 상품 HERO가 완성된다.
- [x] 상품 비율, 색상과 로고가 유지된다.
- [x] 제목과 상품이 겹치지 않는다.
- [x] 모바일 화면과 JPG에서 주요 구성이 유지된다.

## 다음 스프린트 인계

Sprint 4는 HERO 아래의 장점, 단계, 스펙과 구매 전 확인 섹션을 HTML/CSS 그래픽으로 완성한다.
