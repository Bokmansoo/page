# Sellform API-Free Visual Sprint 4 코드리뷰

## 결론

Sprint 4 기획 범위를 완료했다. 상품 사진이 한 장뿐이거나 본문 사진이 반복되는 경우, HERO를 제외한 본문 섹션은 실제 사진을 억지로 반복하지 않고 확인된 상품 사실 기반의 HTML/CSS 정보 그래픽으로 전환된다. 확인된 정보가 부족한 섹션은 숨기되, 판매자가 보완할 내용을 구매 전 확인 섹션의 체크리스트로 안내한다.

## 기획 대비 구현 확인

| 기획 항목 | 구현 | 확인 위치 |
| --- | --- | --- |
| 장점·비교·스펙·단계·수치 그래픽 계약 | 완료 | `page_visual_contract.py`에 `benefit_cards`, `comparison_cards`, `numeric_highlights`, `spec_table`, `steps`, `checklist` 계약 추가 |
| 사실 근거 연결·강제 검증 | 완료 | 카드·표·수치·단계는 `source_fact_ids`와 `confirmed` 상태가 없으면 계약 검증에서 실패 |
| 확인되지 않은 사실 제외 | 완료 | `build_grounded_html_payload`가 `verification_status=confirmed` 사실만 사용 |
| 빈 payload를 준비 완료로 처리하지 않음 | 완료 | 빈 cards/highlights/rows/steps/items는 visual contract 검증 오류가 되며, 자동 전환 정책에서는 해당 본문 섹션을 숨김 |
| 정보 부족 판매자 안내 | 완료 | 숨긴 섹션별 보완 요청을 `pre_purchase`의 `seller_action` 체크리스트에 자동 추가 |
| `product_info` 스펙 표 연결 | 완료 | 현재 템플릿의 `product_info`와 기존 `product_information` 모두 `spec_table`로 매핑 |
| 직접 입력한 수치 사양 반영 | 완료 | `260g`, `10분`, `800mAh` 같은 판매자 입력을 `confirmed` ProductFact로 저장해 스펙 표·수치 그래픽에 사용 |
| 기존 프로젝트 호환 | 완료 | 이전 실행의 `AgentRun.input_snapshot`에서 판매자 입력을 한 번만 복구해, 기존 결과 페이지도 새로 만들지 않고 수치 사양을 반영 |
| 반복 사진 자동 전환 | 완료 | 별도의 직접 업로드 사용 장면/상세 사진이 없으면 본문 image visual을 HTML graphic으로 교체 |
| 별도 상품 사진 보존 | 완료 | `usage_scene`, `product_detail`, `components` 역할의 직접 업로드 사진은 유지 |
| 장점·수치·단계·스펙·체크리스트 렌더러 | 완료 | `HtmlGraphicVisual.tsx`에 수치 강조, 단계 번호, 스펙 표, 구매 전 체크리스트 추가 |
| 모바일·긴 텍스트 대응 | 완료 | 카드·단계·체크리스트 단일 열, `min-w-0`, `break-words`, 스펙 표 가로 스크롤 적용 |
| 색상 외 상태 표시 | 완료 | 카드·수치·표에 `확인된 상품 정보` 또는 `확인됨` 텍스트를 함께 표시 |
| 미리보기·JPG 동일 렌더 | 완료 | 상세페이지와 브라우저 캡처 export가 동일한 `DetailPageDocument`/`HtmlGraphicVisual`을 사용하며 JPG 다운로드 E2E에 수치 그래픽을 포함 |

## 주요 변경

- `visual_contract_backfill.py`
  - 기존 이미지 반복 섹션을 정보 그래픽으로 바꾸는 idempotent 정책을 추가했다.
  - 확인된 fact만 payload에 넣고, 근거가 없으면 빈 카드 대신 해당 본문 섹션을 비표시 처리하고 판매자 체크리스트에 보완 요청을 추가한다.
  - `product_info`/`product_information` 스펙 표와 확인된 수치 기반 `numeric_highlights`를 지원한다.
- `seller_fact_ingestion_service.py`, `agent_runs.py`
  - 새 실행에서는 판매자가 직접 입력한 숫자+단위 사양을 즉시 확인된 사실로 저장한다.
  - 이미 만들어진 프로젝트는 저장된 실행 입력을 읽어 같은 사실을 idempotent하게 복구한다.
  - 정보가 복구되면 자동으로 만들었던 판매자 보완 체크리스트는 숨기며, 사용자가 직접 작성한 구매 전 안내는 유지한다.
  - HERO에 남은 `260g, 800mAh, 10` 같은 모호한 수치 나열은 확인된 사실을 바탕으로 `무게 260g · 배터리 800mAh · 사용 시간 10분`으로 정리한다.
- `AIDetailPageIntake.tsx`, `StructuredIntakeReview.tsx`
  - 원본 상세정보를 AI 요약보다 우선 전송하고, 검토 단계에서도 직접 수정할 수 있게 했다. 따라서 `10분`처럼 숫자와 단위가 함께 입력된 사양이 요약 과정에서 `10`으로 축약되지 않는다.
- `pages.py`
  - 레거시 이미지 복구가 본문 정보 그래픽 전환 뒤에 같은 상품 사진을 다시 붙이던 순서 문제를 수정했다. 이제 반복 사진을 제거한 HTML 그래픽이 페이지 조회·내보내기에도 유지된다.
- `visual_contract_backfill.py`
  - 무게·배터리·사용 시간처럼 숫자 사양만 있는 경우에는 장점/차별화 섹션을 같은 카드로 반복하지 않고 숨긴다. 수치는 `benefits_summary`와 `product_info`에서만 한 번씩 보여준다.
- `page_visual_contract.py`, `types.ts`
  - 모든 판매용 카드·표·수치·단계 항목의 사실 근거와 확인 상태를 강제한다.
  - 판매자 보완 항목은 사실 주장과 분리된 `seller_action`으로만 허용한다.
- `HtmlGraphicVisual.tsx`
  - 장점/비교 카드, 수치 강조, 스펙 표, 사용 단계, 구매 전 체크리스트를 HTML/CSS로 렌더한다.
  - 단계·체크리스트의 본문 중복 fallback을 제거했다.
- `page_readiness_service.py`
  - 자동으로 숨긴 섹션은 export readiness blocker로 계산하지 않는다.

## 검증

```powershell
Set-Location C:\page\backend
uv run pytest tests/test_page_visual_contract.py tests/test_visual_contract_backfill.py tests/test_page_readiness_service.py -q
```

결과: **32 passed**

```powershell
Set-Location C:\page\backend
uv run pytest tests/test_seller_fact_ingestion_service.py tests/test_agent_run_api.py tests/test_visual_contract_backfill.py tests/test_page_visual_contract.py -q
```

결과: **37 passed**. 새 실행의 직접 입력 저장, 재시도 중복 방지, 기존 실행 입력의 호환 복구, HERO 단위 보존 문구, 레거시 이미지 복구 뒤 HTML 그래픽 유지까지 검증했다.

```powershell
Set-Location C:\page\frontend
npm.cmd run lint
```

결과: 오류 없음. 기존 `img` 최적화 및 Hook dependency 경고만 남아 있다.

```powershell
Set-Location C:\page\frontend
npm.cmd run test:e2e -- sprint4-html-graphics.spec.ts completed-detail-page-export.spec.ts
```

결과: **2 passed**. 모바일 폭에서 장점 카드·수치·스펙 표·판매자 체크리스트의 폭을 확인하고, 수치 그래픽이 포함된 JPG 다운로드 흐름을 검증했다.

## 남은 한계

- 로컬 보정은 해상도 확대와 선명도 보정이며, 원본에 없던 실제 제품 디테일을 복원하지는 않는다.
- 확인된 상품 사실이 전혀 없으면 해당 본문 그래픽은 숨긴다. 이는 근거 없는 판매 문구를 자동 노출하지 않기 위한 정책이며, 이제 판매자 체크리스트가 필요한 보완 내용을 안내한다.

## 판정

Sprint 4 완료 기준을 충족했다. 다음 Sprint 5에서는 이 카드·표·단계 그래픽과 사진 배치를 판매자가 코드 없이 직접 조정하고 저장하는 편집 기능으로 확장할 수 있다.
