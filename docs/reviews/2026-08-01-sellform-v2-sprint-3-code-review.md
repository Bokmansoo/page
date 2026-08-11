# Sellform V2 Sprint 3 코드리뷰 — 사실·증거·충돌 보드

검토일: 2026-08-03  
대상 기획: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-3-evidence-board.md`

## 최종 결론

초기 코드리뷰의 완료 판정은 테스트와 생성 통합 검증이 부족해 정확하지 않았다. 재검토에서 확인한 누락을 보완했으며, 현재는 Sprint 3 기획 범위와 완료 기준을 충족한다.

Sprint 4로 넘어가기 전에는 각 프로젝트의 사실·증거 보드에서 `확인/제외 필요`가 0인지 확인해야 한다. 이는 미구현이 아니라 Sprint 3가 의도한 판매자 승인 게이트다.

## 재검토에서 발견하고 수정한 항목

| 초기 누락 | 수정 결과 |
| --- | --- |
| `1kg`와 `1000g` 같은 동치 단위 검증 부족 | g/mAh/cm 기준 정규화 및 같은 사실·복수 근거 병합 |
| 모델별·상품/개별 포장/외박스 범위 혼합 위험 | 모델과 scope를 conflict group에 포함하고 교차 병합 금지 |
| 판매자 확정 사실도 충돌에서 빠질 수 있음 | 동일 그룹의 값이 다르면 출처 우선순위와 무관하게 모두 `conflicted` |
| 후보 병합 API 없음 | 같은 항목·범위·모델 후보의 근거 병합 API와 이력 추가 |
| 위험 표현 승인 재확인 없음 | 단건·일괄 확인 시 risk acknowledgement 필수 |
| 생성 시작 시 미확정 사실을 차단하지 않음 | mock/real 생성 모두 409 `fact_evidence_not_ready` 및 사실 보드 URL 반환 |
| 승인 스냅샷 ID·해시만 저장 | 승인 사실과 전체 근거 payload도 AgentRun 입력에 고정 |
| 사실 변경 영향이 현재 섹션만 표시 | 스토리보드 카드, 섹션, 일반 페이지 버전, 상세페이지 버전 영향 표시 |
| OCR 확대 화면에 좌표 강조 없음 | 원본 이미지 위에 OCR bbox를 빨간 상자로 표시 |
| 화면에서 수정과 승인이 한 동작으로 섞임 | 값 수정 후 재검토 상태 유지, 별도 판매자 확인/충돌 해결/명시적 제외 |
| 일괄 승인·생성 가능 요약 없음 | 현재 검토 카드 일괄 확인, 위험 표현 확인, 생성 사용 가능 사실 요약 추가 |
| 페이지 버전의 구조화 사실 재현 정보 부족 | 구조화 값·단위·범위·모델·추출기·evidence ID와 stale 상태 저장 |
| 기존 프로젝트의 예전 자동 확정 위험값 유지 | 카드 갱신 시 위험 규칙 재평가, 명시적 `risk_acknowledged` 이력만 확정 유지 |
| 외박스 규격이 제품 크기로 남는 기존 데이터 | 포장 문맥 후보를 우선하고 근거 없는 product-scope 중복 후보를 이력과 함께 제외 |
| 확정 후 페이지 표에 공급처 중국어 OCR·원단위가 다시 노출됨 | 페이지 그래픽은 `normalized_value + normalized_unit`만 사용하고 원문·번역은 사실 보드에만 보존 |
| 사실이 추출 순서대로 섹션에 배정됨 | `field_key`·`scope` 기반으로 HERO/FEATURES를 배정하고 외박스 값은 최종 사양에만 유지 |
| FEATURES에 임시 문구가 노출됨 | `확인된 핵심 기능을 한눈에`와 확정 기능 사실 목록으로 교체 |
| 주의사항·CTA에 전압·온도 칩이 임의 표시됨 | 사실을 의도적으로 비운 텍스트 섹션을 표시하고 다른 수치를 자동 상속하지 않도록 계약 추가 |
| 기존 결과 페이지의 텍스트 섹션에 레이아웃 계약 누락 | `PROBLEM`·`TARGET_CUSTOMER`·`CAUTION`을 사실을 발명하지 않는 `image_text` HTML 계약으로 보정 |
| 자동 판매자 체크리스트가 최종 사양 뒤에 추가됨 | 체크리스트를 최종 사양 앞으로 이동하고 `specifications`를 항상 마지막 가시 섹션으로 정규화 |

## 기획 항목별 확인

| 기획 요구 | 상태 | 구현 근거 |
| --- | --- | --- |
| 원문·번역·정규화 값/단위 | 완료 | `ProductFact`, `FactEvidence`, `fact_evidence_service.py` |
| 모델·옵션·본체·개별 포장·외박스 분리 | 완료 | `model_option`, `scope`, 범위별 conflict group |
| URL·이미지·OCR 좌표·신뢰도·추출기 | 완료 | `FactEvidence`와 사실 보드 응답/화면 |
| 추출·확정·검토·충돌·거부 상태 | 완료 | V2 상태 모델과 필터 탭 |
| 수정·승인·병합·충돌 해결 이력 | 완료 | `FactHistory.event_type`, 이전 payload, note |
| 사용 섹션·스토리보드·페이지 버전 영향 | 완료 | `fact_impact_summary()`, `facts_stale` |
| 같은 의미 단위 병합 | 완료 | kg→g, Ah→mAh, mm→cm |
| 값 충돌 자동 선택 금지 | 완료 | `apply_conflicts()`와 명시적 후보 선택 API |
| 위험 표현 재확인 | 완료 | 위험 flag + acknowledgement 없는 승인 409 |
| 후보 병합·충돌 해결·판매자 확인 API | 완료 | `/merge`, `/conflicts/resolve`, `/confirm` |
| 사용자·워크스페이스 권한 검사 | 완료 | 프로젝트 scope 검사와 editor role 검사 |
| 생성 시 승인 사실 스냅샷 | 완료 | `FactSnapshot`, hash, full evidence payload, AgentRun input |
| 미확정/근거 없음 생성 차단 | 완료 | `fact_board_blockers()`, mock/real 생성 게이트 |
| 페이지 조립 시 정규화 사실만 노출 | 완료 | `page_composer_service.py`, `planning_draft_service.py`, `visual_contract_backfill.py` |

## YL-T02 사례 확인

- `4개`와 `6개 이상` 마사지 헤드: 같은 모델·항목 그룹의 충돌로 유지하고 판매자가 하나를 선택한다.
- `10분`, `3.5시간`, `2시간`: 1회 작동, 충전, 총 사용 시간으로 분리한다.
- 외박스 `6kg`: `master_carton / 6000g`로 저장해 본체 무게와 섞지 않는다.
- YL-T01 `950g`, YL-T02 `1000g`: 모델별 별도 후보로 유지한다.
- `약 42°C`와 효능·인증·친환경·저소음·수면/경추 표현: 판매자 재확인 전 생성 입력에서 제외한다.

## 검증 결과

```powershell
Set-Location C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_v2_sprint3_evidence_board.py -q
# 14 passed

.\.venv\Scripts\python.exe -m pytest tests/test_v2_sprint0_baseline_policy.py tests/test_v2_sprint1_product_input_bundle.py tests/test_v2_sprint2_asset_understanding.py tests/test_v2_sprint3_evidence_board.py tests/test_agent_run_api.py -q
# 59 passed

.\.venv\Scripts\python.exe -m pytest tests/test_v2_sprint0_baseline_policy.py tests/test_v2_sprint1_product_input_bundle.py tests/test_v2_sprint2_asset_understanding.py tests/test_v2_sprint3_evidence_board.py tests/test_agent_run_api.py tests/test_planning_draft_service.py tests/test_visual_contract_backfill.py -q
# 80 passed

.\.venv\Scripts\python.exe -m pytest tests/test_planning_draft_api.py tests/test_planning_draft_approve_api.py -q
# 3 passed

Set-Location C:\page\frontend
npm.cmd run build
# compiled successfully, type check passed

Set-Location C:\page\backend
uv run pytest tests/test_visual_contract_backfill.py tests/test_page_readiness_service.py tests/test_planning_draft_approve_api.py -q
# 32 passed

# 실프로젝트 93917981-ec1e-4b72-983a-a6f8646160e5 재검증
# ready: false
# blockers: hero_visual_required, ai_redesign_required, seller_action_required
# 기능 카드: 4개 / 최종 사양: 마지막 섹션
```

Sprint 3 테스트는 다음을 검증한다.

- 숫자·단위 정규화, 원문 보존, 동치 단위 병합
- 모델·상품·외박스 scope 분리
- 단일 YL-T02 프로젝트의 일반 상품 속성을 선택 모델에 귀속해 4개/6개 이상 충돌 생성
- 시간 의미 분리와 온도 위험 검토
- 4개/6개 이상 충돌, 선택 이력
- 위험 표현 승인 acknowledgement
- 기존 자동 확정 위험값 재검사와 명시적 위험 승인 보존
- 기존 외박스 규격의 scope 재분류와 표시명 보정
- 수동 후보 병합과 모든 근거 보존
- 거부·검토 사실의 스냅샷 제외
- 섹션·스토리보드·페이지 버전 stale/impact
- 승인 스냅샷 hash 재현과 전체 근거 보존
- 타 워크스페이스 조회·승인 거부
- AgentRun 생성 차단 코드와 사실 보드 이동 URL
- 공급처 OCR 원문과 정규화된 페이지 표시값 분리
- HERO/FEATURES의 의미 기반 사실 배정과 외박스 scope 제외
- 사실 없는 텍스트 섹션의 임의 수치 상속 방지
- 사실 없는 텍스트 섹션의 유효한 미리보기·내보내기 레이아웃 계약
- 판매자 체크리스트 생성 후에도 최종 사양을 마지막에 유지
- 검수 완료 상품 이미지가 없는 HERO의 잘못된 완료 판정 차단
- 숨긴 AI 리디자인 대기 섹션과 판매자 조치 체크리스트의 완료 우회 차단
- 구매자 결과물에서 판매자 전용 체크리스트 제외
- 본문과 HTML 그래픽의 중복 문구 제거, 기능 카드·사양 표의 이중 렌더링 방지

## 서버 수동 확인

1. 결과 화면에서 **사실·증거 확인**을 연다.
2. **사실 카드 갱신**을 누른다.
3. 원문·번역·값·단위·모델·scope·근거 이미지의 빨간 OCR 위치를 확인한다.
4. 충돌은 올바른 후보 하나를 선택하고, 나머지는 명시적으로 제외하거나 판매자 확인한다.
5. 위험 표현이 포함된 일괄 확인에서는 재확인 창이 나오는지 확인한다.
6. 상단의 `확인/제외 필요`가 0이 되면 새 생성을 실행한다.
7. 미완료 상태에서 생성하면 `fact_evidence_not_ready` 409와 `/facts` 검토 URL이 반환되어야 한다.

## 최종 판정 보정

기존 수동 검증의 `ready: true`는 이미지 없는 HERO와 숨긴 CTA를 완료로 간주한 잘못된 판정이었다. 현재는 이 상태를 성공으로 보고하지 않는다. 공급처 참고 이미지는 최종 출력에 직접 사용할 수 없으므로, API 키 없이 AI 리디자인 이미지가 만들어지지 않은 현재 프로젝트는 정상적으로 `ready: false`이다. 이미지 생성·검수와 판매자 확인이 끝나야 다운로드가 열린다.

## 남은 경고

테스트 출력의 `google.generativeai` 종료 예고, Pydantic class config, `datetime.utcnow()` 경고는 기존 기술 부채이며 Sprint 3 기능 실패는 아니다. 기능 범위 내 미완료 항목은 없다.

확장 회귀 묶음에 포함해 실행한 `test_pages.py::test_get_page_backfills_incomplete_html_visual_payloads`는 사실이 전혀 없는 완료 상태의 레거시 페이지에도 가상의 카드·표 행을 채우라는 기존 기대값 때문에 실패한다. 현재 안전 정책은 근거 없는 판매 카드 대신 섹션을 숨기고 판매자 확인 항목을 제공하므로 Sprint 3 사실·증거 계약과는 별개의 기존 테스트 기대값 불일치다. Sprint 3 및 기획/승인/조립 경로 테스트는 모두 통과했다.
