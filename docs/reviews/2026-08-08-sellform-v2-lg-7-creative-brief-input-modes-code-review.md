# Sellform V2.1 LG-7 코드리뷰 및 역검증

## 1. 결론

LG-7 범위는 최종 기획과 구현 계획에 맞게 연결되었다. 리뷰·레퍼런스·판매자 창작 방향은 상품 사실과 분리 저장되고, 불변 `ProductCreativeBriefVersion`으로 컴파일된 뒤 `sales_strategy`보다 먼저 LangGraph에 고정된다. 신규 사용자 흐름은 빠른 생성 모드를 기본으로 제공하고, 전문가 검수로 전환해도 기존 산출물과 승인을 보존한다.

이번 판정은 기존 문서의 충족 표기를 재사용하지 않고 실제 모델, 마이그레이션, 서비스, API, LangGraph 체크포인트·resume 경로, 프런트엔드 및 테스트를 다시 대조한 결과다.

- LG-7 대상 미구현: 0건
- LG-7 대상 부분 구현: 0건
- 테스트 우회: 0건
- 실제 유료 LLM·이미지 provider 호출: 0건
- DB 적용: LG-7 테이블 7/7, `previous_version_id` 확인

## 2. 역검증 중 발견하고 같은 작업에서 보완한 항목

1. Product Creative Brief의 필수 내용을 중첩 객체에만 두지 않고 `target_audience`, `customer_problem`, `purchase_motivation`, `desired_mood`, `emphasis`, `forbidden_claims`, `forbidden_scenes`, `section_strategy`, `approved_fact_ids`, `creative_directions`, `review_insights`, `reference_signals`, `provenance` 필드로 명시했다.
2. 이전 브리프와의 불변 계보를 명확히 하기 위해 `previous_version_id` 자기 참조 FK를 모델·마이그레이션·런타임 호환 스키마에 추가했다.
3. XLSX shared string과 inline string을 모두 읽도록 파서를 보완하고 실제 최소 XLSX 바이트로 검증했다.
4. 레퍼런스는 사용자가 선택한 palette/layout/section flow/shoot mood/copy tone 신호만 저장하도록 제한했다.
5. 오래된 체크포인트로 resume할 때도 DB의 최신 quick/expert 모드를 권위값으로 읽도록 보완했다.

## 3. 요구사항별 판정

| ID | 판정 | 구현 및 테스트 증거 |
|---|---|---|
| ARC-03 | 충족 | `creative_brief_compiler`를 `prompt_pack_resolver`와 `sales_strategy` 사이에 배치. `backend/src/agents/langgraph_runtime.py`, 그래프 순서 테스트 |
| PRM-06 | 충족 | `ReviewInsightVersion`의 fact 승격 차단과 `SellerCreativeDirectionVersion` 별도 저장. `backend/src/db/models.py:648`, `backend/src/db/models.py:698` |
| PRM-07 | 충족 | 브리프는 승인 fact snapshot의 ID만 `approved_fact_ids`로 참조. `backend/src/services/creative_brief_service.py:216` |
| PRM-08 | 충족 | 판매자 target/mood/emphasis/forbidden scenes를 별도 버전과 브리프에 보존 |
| PRM-09 | 충족 | canonical hash와 같은 입력의 동일 버전 재사용으로 mock 결정성 및 멱등성 보장 |
| FACT-01 | LG-7 책임 충족 | 기존 LG-3 section/copy fact ID 계약을 브리프의 승인 fact ID와 연결. `backend/tests/test_lg3_commerce_planning_subgraph.py:99` |
| FACT-02 | LG-7 책임 충족 | 문제·CTA 창작 문장을 `narrative_non_claim`으로 명시. `backend/src/services/creative_brief_service.py:250` |
| FACT-03 | 충족 | 리뷰 claim candidate는 항상 `fact_promotion_status=blocked`; 자동 사실 승격 없음 |
| FACT-04 | 충족 | 중국어 원문·상표·QR·워터마크·가격 복제를 forbidden output으로 전달. `backend/src/services/creative_brief_service.py:273` |
| FACT-05 | LG-7 책임 충족 | 모든 review/reference에 source·consent·rights·hash·usage scope 보존; 권리 미확인은 분석 전용 |
| REV-01 | 충족 | CSV/XLSX/TXT/붙여넣기 입력과 실제 XLSX 파서 테스트 |
| REV-02 | 충족 | 불만, 구매 이유, 반복 표현, 추정 타깃, 긍정 신호, 개선 요청, claim candidate 추출 |
| REV-03 | 충족 | 리뷰 분석은 ProductFact를 생성하지 않고 승격을 차단하는 DB 테스트 통과 |
| REV-04 | 충족 | source, collected_at, consent, rights, content hash, creator, project/version 저장 |
| REV-05 | 충족 | URL/이미지/PDF/텍스트 입력을 별도 API로 지원 |
| REV-06 | 충족 | palette/layout/section flow/shoot mood/copy tone 중 선택한 추상 신호만 저장 |
| REV-07 | 충족 | source copy/logo/product image/고유 디자인 복제 금지 정책을 분석 결과와 브리프에 포함 |
| REV-08 | 충족 | 권리 미확인 레퍼런스는 `analysis_only`; 확인된 자산만 `final_output_eligible` |
| REV-09 | 충족 | 브리프에 review/reference insight version ID와 provenance 연결, UI에 사용 상태 표시 |
| BRAND-05 | LG-7 책임 충족 | 브리프에 LG-6 Brand Kit ID/version/hash를 고정하고 page/copy/visual 입력 계약에서 동일 버전을 소비 |
| FAST-01 | 충족 | 시작 화면에 빠른 생성(권장)·전문가 검수 선택 제공 |
| FAST-02 | 충족 | interaction mode와 creative brief snapshot을 run input/checkpoint에 보존 |
| FAST-03 | 충족 | quick 모드의 안전 gate만 자동 응답하고 `WorkflowGateEvent`에 근거 기록 |
| FAST-04 | 충족 | fact/claim/cost/rights/identity/policy gate는 quick에서도 수동 interrupt 유지 |
| FAST-05 | 충족 | expert는 gate별 이유·비용·영향을 interrupt payload/UI에 유지 |
| FAST-06 | 충족 | mode PATCH는 기존 artifact/approval을 삭제하지 않으며 새로고침 후 유지 |
| FAST-07 | 충족 | auto/manual 결정, 모드, 근거, 영향, checkpoint ID를 `workflow_gate_events`에 기록 |

`FACT-*`와 `BRAND-05`는 후속 LG-8·LG-10·LG-12에서도 최종 산출물까지 반복 검증되는 횡단 요구사항이다. 위 판정은 LG-7이 담당하는 입력·브리프·planning 소비 경계가 완성됐다는 뜻이며 후속 스프린트의 최종 QA를 선완료했다는 뜻은 아니다.

## 4. 구현 연결 증거

- DB 모델: `backend/src/db/models.py:626-748`
- 안전 마이그레이션: `backend/migrations/20260808_lg7_creative_brief_input_modes.sql`
- 파서·분석·불변 브리프·선택적 무효화: `backend/src/services/creative_brief_service.py`
- 분리 API: `backend/src/api/creative_briefs.py:59-153`
- compiler 및 LG-7 그래프: `backend/src/agents/langgraph_runtime.py:958`
- page/copy/visual 공통 입력 계약: `backend/src/services/langgraph_commerce_planning_service.py:143-155`
- 기획 화면: `frontend/src/components/planning/CreativeBriefInputPanel.tsx`
- 신규 실행 모드 선택: `frontend/src/components/AIDetailPageIntake.tsx:642-647`

## 5. 테스트 결과

| 검증 | 결과 |
|---|---|
| LG-7 단위·API·DB·그래프 테스트 | 11 passed |
| LG-6 + LG-7 최종 회귀 | 20 passed |
| LG-4 + LG-5R 실제 interrupt·비용·fake worker·checkpoint/resume 회귀 | 17 passed |
| LG-7 Playwright 요청·상태 전이·새로고침 복구 | 1 passed |
| 관련 Python 소스 AST 구문 검증 | 5 files OK |
| 실제 개발 DB 스키마 | 7/7 tables, previous_version_id=True |

Playwright는 UI 요소가 보이는지만 확인하지 않고 리뷰/레퍼런스/방향 저장 요청, 모드 변경, 새로고침 후 상태 복구 및 리뷰 claim의 fact 승격 차단 표시를 검증한다. 그래프 테스트는 compiler 순서, 체크포인트에 원문 corpus가 들어가지 않는 것, stale checkpoint에서 DB 모드 재조회, gate audit를 검증한다.

## 6. 잔여 비차단 사항

저장소 전체 `tsc --noEmit`에는 LG-7과 무관한 기존 파일의 타입 오류가 남아 있다. LG-7 컴포넌트 자체 오류는 없고 LG-7 Playwright는 통과했다. 사용자 소유의 관련 없는 변경을 수정하지 말라는 범위 제약에 따라 해당 기존 오류는 이 작업에서 변경하지 않았다.

## 7. 최종 판정

LG-7은 다음 단계로 진행 가능한 상태다. 다만 브라우저 사용자 검증 가이드의 quick/expert 전환, 리뷰 claim 차단, 권리 미확인 레퍼런스의 분석 전용 표시, 새로고침 복구를 한 번 직접 확인한 뒤 LG-8을 시작하는 것을 완료 게이트로 삼는다.
