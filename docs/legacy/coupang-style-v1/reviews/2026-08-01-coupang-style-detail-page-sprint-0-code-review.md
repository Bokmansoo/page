# 쿠팡형 상세페이지 Sprint 0 코드리뷰

작성일: 2026-08-01  
결론: **기획상 필요한 기준선 등록·검사 기능까지 구현 완료. 실제 회귀용 상품 자료는 판매자 자료를 등록하면 된다.**

## 기획 대비 확인

| 기획 항목 | 구현 | 검토 결과 |
| --- | --- | --- |
| 소형 가전·뷰티·생활용품 기준 상품 3종 | `BASELINE_PRODUCTS` | 완료 |
| 대표컷 1장 + 기능/상세 이미지 3장 기준 | `inspect_coupang_style_baseline` | 완료 |
| HERO/기능/사용 장면/구성품/스펙/CTA 평가표 | `EVALUATION_ITEMS`와 등록 API의 확인값 저장 | 완료 |
| 이미지 반복·근거 없는 주장·빈 섹션·출력 확인 | 기준선 API의 반복/빈 섹션/기존 readiness 경고/JPG 보관 체크 | 완료 |
| 기준선 JPG 보관 | `exported_image` JPG만 기준선으로 등록 가능 | 완료 |
| 실제 상품 원본/참고 캡처 등록 | 기준 상품 ↔ 프로젝트 ↔ 참고 캡처 ↔ JPG 연결 레코드 | 완료 (실제 판매자 자료 입력은 운영 데이터) |

## 변경 파일

- `backend/src/db/models.py`: 워크스페이스별 기준 상품 증거 등록 레코드.
- `backend/src/services/coupang_style_baseline.py`: 3종 회귀 팩, 고정 평가표, 프로젝트별 기준선 검사.
- `backend/src/api/pages.py`: 기준 상품 목록·증거 등록·프로젝트별 기준선 API.
- `backend/tests/test_coupang_style_baseline.py`: 회귀 팩, 자료 부족 경고, 증거 등록, 반복 이미지, JPG 보관 검증.
- `../testing/2026-08-01-coupang-style-detail-page-sprint-0-baseline.md`: 판매자 자료 등록 및 수동 비교 절차.

## 검증 명령

```powershell
Set-Location C:\page\backend
uv run pytest tests/test_coupang_style_baseline.py tests/test_page_readiness_service.py -q
```

실행 결과:

```text
uv run pytest tests/test_coupang_style_baseline.py tests/test_page_readiness_service.py -q
15 passed
```

추가로 `tests/test_pages.py`까지 함께 실행했을 때에는 기존
`test_get_page_backfills_incomplete_html_visual_payloads` 1건이 실패했다. 이 테스트는
기존 HTML 카드 보정 정책(`visual_contract_backfill`)을 기대하며, Sprint 0에서 변경한
파일은 기준선 서비스·API·테스트뿐이다. 다음 시각 보정 작업에서 별도로 원인을 확인한다.

## 코드리뷰 재확인 결과

초기 코드리뷰에서 미완료로 남아 있던 “참고 캡처·기준선 JPG·평가표 등록”은 이번 보완으로
해결됐다. 다만 실제 사진과 캡처 자체는 외부 쇼핑몰에서 무단 수집하지 않으며, 판매자가
권한 있는 자료를 올려야 채워진다. 이는 코드 미구현이 아니라 운영 입력의 선행 조건이다.

## 다음 단계

Sprint 1에서 이 기준선의 각 상품에 여러 장의 판매자 사진을 한 번에 올리고, 부족한 이미지 유형을 안내하는 입력 흐름을 만든다.
