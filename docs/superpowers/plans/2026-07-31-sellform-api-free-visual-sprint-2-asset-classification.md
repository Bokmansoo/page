# Sellform Sprint 2 이미지 자산 분류 및 품질 검사 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 실제 상품 이미지를 역할과 품질에 따라 분류하고 판매자가 사용 위치를 확인·수정하게 한다.  
**기간:** 1주  
**의존성:** Sprint 1 완료

## 범위

- 이미지 역할과 품질 상태 데이터 계약
- 해상도, 비율, 중복과 안전 크롭 가능성 검사
- 대표 이미지 선택 및 역할 변경 UI
- 저품질 이미지 경고

## 예상 수정 파일

- `backend/src/db/models.py`
- `backend/src/api/files.py`
- `backend/src/services/image_asset_mapper.py`
- 신규 `backend/src/services/image_asset_inspector.py`
- `frontend/src/components/VisualPackagePanel.tsx`
- 이미지 후보 관련 프론트엔드 컴포넌트
- 관련 migration 또는 호환 backfill

## 데이터 계약

```json
{
  "role": "product_main | product_detail | usage_scene | components | package | spec_reference",
  "quality_status": "usable | warning | rejected",
  "identity_status": "confirmed | needs_review",
  "width": 1600,
  "height": 1600,
  "quality_warnings": []
}
```

## 작업

### Task 1: 메타데이터와 호환성

- [ ] 기존 `Asset` 모델과 응답 스키마를 조사해 중복 필드를 피한다.
- [ ] 필요한 필드와 기본값을 추가한다.
- [ ] 기존 자산은 안전한 기본 역할과 `needs_review` 상태로 backfill한다.
- [ ] 원본 파일 경로와 메타데이터 갱신을 분리한다.

### Task 2: 결정론적 품질 검사

- [ ] Pillow로 폭, 높이, 비율과 파일 형식을 읽는다.
- [ ] 기준 이하 해상도와 극단적 비율에 경고를 부여한다.
- [ ] 파일 해시로 완전 중복을 감지한다.
- [ ] 자동 거절은 손상 파일에만 적용하고 애매한 이미지는 판매자 검토로 보낸다.

### Task 3: 역할 추천

- [ ] 가장 크고 상품이 분명한 이미지를 `product_main` 후보로 추천한다.
- [ ] URL 위치, 파일명과 기존 OCR 정보를 보조 신호로 사용한다.
- [ ] 자동 분류 신뢰도를 저장한다.
- [ ] 사용자가 역할을 바꾸면 자동 추천보다 우선한다.

### Task 4: 판매자 UI

- [ ] 이미지 썸네일에 역할, 해상도와 경고를 표시한다.
- [ ] 대표 이미지 선택과 역할 변경을 제공한다.
- [ ] 각 이미지가 사용 중인 섹션을 표시한다.
- [ ] 저품질 이미지를 HERO로 선택할 때 확인을 요구한다.

## 완료 기준

- [ ] 모든 실제 이미지에 역할과 품질 상태가 있다.
- [ ] 저해상도 이미지를 HERO에 자동 배치하지 않는다.
- [ ] 판매자가 대표 이미지와 역할을 변경할 수 있다.
- [ ] 기존 프로젝트가 migration 이후에도 열린다.

## 다음 스프린트 인계

Sprint 3은 `product_main`으로 확정된 이미지를 사용해 HERO 자동 조합 레이아웃을 만든다.
