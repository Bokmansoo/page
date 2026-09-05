# Sellform API-Free Visual Sprint 3 코드리뷰

## 재검토 결론

최초 리뷰의 완료 판정에는 두 가지 누락이 있었다. 심한 품질 경고 자산을 export readiness에서 다시 차단하지 않았고, 모바일·고정 export 폭의 실제 브라우저 검증이 없었다. 재검토 과정에서 두 항목을 구현하고 회귀 검증을 추가했다.

현재는 Sprint 3 기획의 필수 범위를 구현했다. 외부 이미지 생성 API 없이, Sprint 2에서 확정한 실제 상품 사진을 `composed_product` HERO로 구성한다. 상품 원본은 변형하지 않고 `object-fit: contain`으로 보존하며, 제목·본문·배지는 HTML 텍스트 레이어로 분리된다.

기존 `image`/`hero_overlay` HERO는 호환된다. 안전한 기존 기본 HERO는 페이지를 불러올 때 새 구성으로 한 번 업그레이드하고, 사용자가 별도로 만든 레이아웃은 변경하지 않는다.

## 기획 대비 구현 확인

| 기획 항목 | 구현 | 확인 위치 |
| --- | --- | --- |
| `composed_product` 시각 계약 | 완료 | `page_visual_contract.py`에 새 visual kind와 필수 payload 검증을 추가했다. |
| 대표 사진 기반 결정론적 payload | 완료 | `hero_composition.py`가 `product_main` 대표 확정 상태, 품질·안전 크롭 상태·스타일을 바탕으로 layout, 배경, 장식을 결정한다. |
| 위험 사진 HERO 차단 | 완료 | 저해상도·극단 비율·중복·무결성 경고 사진은 payload 생성과 export readiness 양쪽에서 차단한다. |
| 기존 `image` HERO 호환 | 완료 | 기존 기본 `hero_overlay`만 안전하게 업그레이드하며, 나머지 이미지 렌더러는 유지한다. |
| 좌측 문구·우측 상품 구성 | 완료 | `ComposedProductVisual.tsx`의 `hero_product_right` 변형으로 구현했다. |
| 중앙 상품·하단 문구 구성 | 완료 | 안전 크롭 검수가 필요한 사진에는 `hero_product_center` 변형을 사용한다. |
| 비율 보존 | 완료 | 상품 이미지는 항상 `object-contain`으로 렌더링한다. |
| 텍스트 안전 영역 | 완료 | split HERO는 좌측, center HERO는 하단에 텍스트 DOM을 분리한다. |
| 배경·그림자·SVG 장식 | 완료 | mint/ink/sand 배경 토큰, 제품 그림자, 원·곡선 SVG 장식을 적용했다. |
| 미리보기와 export 공통 렌더링 | 완료 | 결과 페이지와 export route가 모두 `DetailPageDocument`와 `ComposedProductVisual`을 사용한다. |
| export 스냅샷 보존 | 완료 | 최종 버전에도 `visual_kind`, `visual_payload`를 저장한다. |
| 편집 표식 export 제외 | 완료 | 출처 배지는 `exportMode`에서 렌더링하지 않는다. |
| 모바일·고정 폭·JPG 검증 | 완료 | Playwright가 390px 모바일 적층, 760px export 문서, 겹침 여부, `contain`, export 준비 신호와 JPEG 캡처를 확인한다. |

## 주요 변경

### 백엔드

- `composed_product` 계약은 다음 필드를 요구한다: `layout_variant`, `product_fit: contain`, `text_safe_area`, `background_token`, `decoration_tokens`.
- 실제 사진이 없거나 거절 상태이거나 주요 품질 경고가 있으면 기존 이미지 상태를 유지하고, export 준비 완료로 판정하지 않는다.
- `composed_product`는 `product_main` 역할이면서 대표로 확정된 자산만 사용한다.
- Page Assembly, 자동 이미지 매핑, 기존 페이지 backfill 세 경로가 같은 HERO payload 생성기를 사용한다.
- 기존 페이지는 HERO 변환 전에 Sprint 2 자산 분류를 먼저 실행해 페이지·자산 동시 요청의 첫 로딩 race를 제거했다.
- 최종 확정 시 스냅샷에 새 시각 계약을 저장해 미리보기와 JPG/PNG export의 구성 차이를 막았다.

### 프론트엔드

- 새 `ComposedProductVisual`은 사진을 CSS/SVG 배경 위에 배치한다. 이미지 자체에는 텍스트를 합성하지 않는다.
- 데스크톱에서는 문구 좌측·상품 우측, 모바일에서는 문구와 상품이 세로로 흐른다.
- 안전 크롭 검수가 필요한 사진은 중앙 상품·하단 문구로 바꿔 피사체와 문구가 겹칠 가능성을 낮춘다.

## 검증 결과

```powershell
Set-Location C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests\test_sprint3_hero_composition.py tests\test_page_readiness_service.py tests\test_page_visual_contract.py tests\test_visual_contract_backfill.py tests\test_page_finalization_service.py tests\test_wysiwyg_export_contract.py tests\test_export_service.py tests\test_image_candidate_selection_contract.py tests\test_sprint1_real_product_images.py -q
```

결과: **61 passed**

추가 확인:

- `composed_product` 계약의 정상/오류 검증
- 대표 미확정·상품 대표 역할이 아닌 사진의 composed HERO 차단
- 품질 경고 사진의 HERO 조합 차단
- 품질 경고 및 대표 미확정 자산의 export readiness 차단
- 기존 기본 HERO의 idempotent 업그레이드와 기존 커스텀 이미지 레이아웃 보존
- 기존 미분류 자산도 첫 페이지 로딩에서 분류 후 즉시 HERO로 업그레이드
- 최종 export 버전에 visual payload 보존
- Sprint 1 실상품 사진 선택 및 기존 export 회귀

```powershell
Set-Location C:\page\frontend
npm.cmd run lint
```

결과: 성공. 기존 및 이미지 태그 관련 경고만 있으며 오류는 없다.

브라우저 검증:

```powershell
Set-Location C:\page\frontend
npx.cmd playwright test sprint3-composed-hero.spec.ts --project=chromium --workers=1
```

시나리오 결과: **2 passed**

- 결과 페이지와 export route에서 같은 `composed_product` 컴포넌트 사용
- 760px 고정 export 폭에서 좌측 문구·우측 상품 비겹침
- 390px 모바일에서 문구·상품 세로 적층 및 비겹침
- 상품 이미지 `object-fit: contain`, 이미지 로딩 후 export 준비 신호 확인
- 실제 JPEG 버퍼 캡처 성공

참고: 현재 Windows 실행 환경에서는 두 worker가 모두 `ok`를 반환한 뒤 테스트용 Next 서버 정리가 지연되어 상위 명령 래퍼가 제한시간에 종료됐다. 테스트 시나리오 실패는 없었다.

TypeScript 전체 검사에서는 이번 Sprint와 무관한 기존 `e2e/upload-ready-golden-path.spec.ts`의 타입 오류 2건이 남아 있다. Sprint 3 신규 파일에서는 타입 오류가 발생하지 않았고 `next lint`는 통과했다.

## 남은 한계와 Sprint 4 인계

- 안전 크롭 판단은 원본 이미지의 비율과 품질 메타데이터 기반이다. 상품 피사체의 실제 위치를 읽는 비전 모델 판정은 포함하지 않는다.
- Sprint 3은 HERO만 구성한다. HERO 아래의 장점·비교·스펙 섹션이 사진을 반복하지 않도록 HTML/CSS 그래픽으로 풍부하게 만드는 일은 Sprint 4 범위다.

## 판정

Sprint 3 완료 기준을 충족했다. Sprint 4 HTML/CSS 그래픽 섹션 구현으로 진행할 수 있다.
