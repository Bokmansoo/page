# 쿠팡형 상세페이지 Sprint 0 기준선 검증 팩

작성일: 2026-08-01  
상태: 구현 완료 — 각 기준 상품의 실제 판매자 자료 등록 대기

## 고정 회귀 상품

| 키 | 분류 | 기준 상품 | 필요한 판매자 자료 |
| --- | --- | --- | --- |
| `small-appliance` | 소형 가전 | 바디프랜드 미니 마사지건 | 대표컷 1장 + 기능/상세컷 3장 이상 |
| `beauty` | 뷰티 | 라운드랩 자작나무 수분 크림 | 대표컷 1장 + 제형/성분/상세컷 3장 이상 |
| `living-set` | 생활용품 | 락앤락 비스프리 밀폐용기 세트 | 대표컷 1장 + 구성품/상세컷 3장 이상 |

상품 사진과 참고 상세페이지 캡처는 권한이 확인된 판매자 업로드 자료만 사용한다. 외부 쇼핑몰의 제한된 이미지를 자동 복사하거나 우회 수집하지 않는다.

## 자동 기준

`GET /api/v1/projects/{project_id}/commerce-story-baseline`은 다음을 반환한다.

- 사용 가능한 판매자 원본 이미지 수와 대표 이미지 선택 여부
- 본문 동일 이미지 반복 횟수
- 빈 표시 섹션과 근거/검수 경고
- 기준선 JPG 저장 여부

기준 상품의 실제 증거는 아래 API로 등록한다. 등록할 때 연결한 프로젝트 안에 원본 상품 사진,
참고 상세페이지 캡처, 그리고 Sellform이 내보낸 JPG가 있어야 한다.

```text
GET /api/v1/commerce-story-baselines
PUT /api/v1/commerce-story-baselines/{baseline_key}/registration
GET /api/v1/projects/{project_id}/commerce-story-baseline?baseline_key={baseline_key}
```

등록 데이터에는 `project_id`, `reference_capture_asset_id`, `baseline_export_asset_id`,
그리고 아래 평가표의 확인 결과를 넣는다. 기준선 JPG에는 일반 상품 사진이 아닌
`exported_image` 형식의 JPG만 연결할 수 있다.

| 평가 키 | 확인 내용 |
| --- | --- |
| `hero` | 제품과 핵심 소구점이 HERO에서 보이는가 |
| `features` | 기능이 근거 이미지 또는 사실과 연결되는가 |
| `usage_scene` | 사용 장면/사용 방법이 이해되는가 |
| `components_detail` | 구성품 또는 디테일이 확인되는가 |
| `specifications` | 수치와 스펙이 확인된 사실에 근거하는가 |
| `cta` | 구매 전 확인 또는 CTA가 있는가 |
| `image_repetition` | 본문에서 같은 이미지가 반복되지 않는가 |
| `grounding` | 근거 없는 주장이 없는가 |
| `empty_sections` | 빈 섹션이 없는가 |
| `preview_export_parity` | 미리보기와 JPG가 같은가 |

대표컷 1장과 기능/상세 이미지 3장 미만이면 `source_image_pack_incomplete`으로 표시된다. 이는 사실이 부족한 상태에서 길고 그럴듯한 상세페이지를 꾸며내지 않기 위한 기준이다.

## 수동 확인 항목

각 기준 상품에서 참고 캡처와 결과 페이지를 비교하여 아래를 기록한다.

- HERO → 기능 → 사용 장면 → 구성품/디테일 → 스펙 → CTA 흐름
- 이미지 반복, 근거 없는 주장, 빈 섹션
- 미리보기와 저장 JPG의 섹션 순서·문구·이미지 일치

미리보기/출력의 픽셀 수준 일치 검사는 Sprint 7에서 자동화한다. Sprint 0에서는 기준 JPG를 보관하고 사람이 같은 흐름을 확인한다.
