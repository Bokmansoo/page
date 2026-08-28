# Sellform V2.1 LG-7 구현 계획

## 1. 목표

LG-7은 판매자가 제공한 사실, 리뷰에서 얻은 정성 인사이트, 레퍼런스에서 얻은 추상적 디자인 신호, 판매자의 창작 방향을 서로 다른 경계로 저장한 뒤 `ProductCreativeBriefVersion`으로 컴파일한다. 이 브리프는 승인된 사실을 참조만 하며 변경하지 않고, LG-3 판매 전략 앞에서 LangGraph의 입력으로 고정된다. 또한 신규 실행은 `quick` 또는 `expert` 모드를 체크포인트에 저장하고, 안전한 승인만 빠른 모드에서 자동 처리한다.

## 2. 구현 경계

- DB: 원본 입력, 분석 결과, 판매자 방향, 불변 브리프 버전, 게이트 이력을 각각 별도 테이블로 저장한다.
- API: 리뷰와 레퍼런스 입력을 별도 엔드포인트와 스키마로 제공한다. 지원 형식은 리뷰 `CSV/XLSX/TXT/붙여넣기`, 레퍼런스 `URL/이미지/PDF/텍스트`다.
- LangGraph: `prompt_pack_resolver -> creative_brief_compiler -> sales_strategy` 순서를 사용한다.
- 기획 에이전트: pack/Brand Kit/creative brief/fact snapshot의 버전과 해시를 입력 및 산출물 메타데이터에 남긴다.
- UI: 시작 화면에서 빠른 생성(권장)/전문가 모드를 선택하고, 기획 화면에서 리뷰·레퍼런스·창작 방향·브리프 근거를 확인/편집한다.
- 안전: 리뷰 주장은 승인 사실로 승격하지 않고, 권리 미확인 레퍼런스는 `analysis_only`이며 최종 출력 자산으로 사용할 수 없다.

## 3. 요구사항 추적표

| 요구사항 | 구현 | 테스트 |
|---|---|---|
| ARC-03 | LangGraph `creative_brief_compiler` 노드와 immutable version | graph 순서·resume 통합 테스트 |
| PRM-06 | `fact_candidate`와 `creative_direction` 분리 저장 | 경계 단위 테스트 |
| PRM-07 | brief `approved_fact_ids` 검증 | 존재하지 않는 fact ID 거부 테스트 |
| PRM-08 | mood/target/emphasis/forbidden scenes 보존 | API round-trip 및 graph 테스트 |
| PRM-09 | canonical input hash와 mock output hash | 동일 입력 결정성 테스트 |
| FACT-01 | 페이지/카피 section fact ID 검증 | 숫자 주장·사실 링크 테스트 |
| FACT-02 | `narrative_non_claim` 분류 유지 | copy provenance 테스트 |
| FACT-03 | 충돌 리뷰 인사이트는 manual review 상태 | promotion 차단 테스트 |
| FACT-04 | 금지 문구·OCR 오염 신호를 brief constraint로 전달 | forbidden signal 테스트 |
| FACT-05 | rights/provenance를 reference 및 brief에 보존 | analysis_only 테스트 |
| REV-01 | 리뷰 CSV/XLSX/TXT/paste 입력 | 각 형식 API 테스트 |
| REV-02 | 반복 불만/구매 이유/표현/타깃 추출 | deterministic analyzer 테스트 |
| REV-03 | 리뷰 insight가 ProductFact를 생성하지 않음 | DB 불변 테스트 |
| REV-04 | source/collected_at/consent/hash 저장 | provenance 테스트 |
| REV-05 | 레퍼런스 URL/image/PDF/text 입력 | 형식별 API 테스트 |
| REV-06 | palette/layout/flow/mood/tone 추상 신호 | analyzer 테스트 |
| REV-07 | 로고·카피·고유 디자인 복제 금지 | sanitized output 테스트 |
| REV-08 | 권리 미확인 `analysis_only` | final-use eligibility 테스트 |
| REV-09 | insight-to-brief 링크와 usage 상태 | UI/API 조회 테스트 |
| BRAND-05 | 동일 Brand Kit version/hash 고정 | downstream metadata 테스트 |
| FAST-01 | quick/expert 선택 | intake UI/API 테스트 |
| FAST-02 | 실행 input snapshot/checkpoint 저장 | refresh/resume 테스트 |
| FAST-03 | 안전 gate quick 자동 처리 | graph auto-approval 테스트 |
| FAST-04 | 위험 gate 항상 interrupt | cost/rights/fact/identity 테스트 |
| FAST-05 | expert는 모든 gate rationale/cost/impact 노출 | interrupt payload 테스트 |
| FAST-06 | quick→expert 전환 시 artifact/approval 보존 | mode switch API 테스트 |
| FAST-07 | 자동 승인 이력·근거 저장 | gate history 테스트 |

## 4. 데이터 모델

1. `review_input_versions`: 프로젝트별 불변 원본, 형식, 출처, 동의/권리, 해시.
2. `review_insight_versions`: 반복 불만/구매 이유/표현/추정 타깃, `fact_promotion_status=blocked`.
3. `reference_input_versions`: 입력 종류, URL/asset/text 메타데이터, 권리 상태, `usage_scope`.
4. `reference_insight_versions`: 추상 palette/layout/flow/mood/tone만 저장.
5. `seller_creative_direction_versions`: mood/target/emphasis/forbidden scenes.
6. `product_creative_brief_versions`: 위 버전 ID, fact snapshot ID, pack/Brand Kit 버전, canonical hash, compiled JSON.
7. `workflow_gate_events`: manual/auto 결정, 근거, 영향, 모드, checkpoint ID.

모든 버전 테이블은 update 대신 새 row를 만들며 `(project_id, version)`을 유일하게 한다.

## 5. 실행 순서

1. 신규 실행 생성 시 `interaction_mode=quick|expert`를 project와 run input snapshot에 고정한다. 과거 `quality`는 읽을 때만 `expert`로 정규화한다.
2. 입력 승인 뒤 리뷰/레퍼런스/판매자 방향의 최신 버전을 읽는다.
3. `creative_brief_compiler`가 승인 fact snapshot, prompt pack, Brand Kit 버전과 함께 불변 brief를 만든다.
4. 판매 전략, 페이지 기획, 카피, 비주얼 기획은 같은 brief ID/hash와 Brand Kit ID/hash를 소비한다.
5. 브리프 변경 시 판매 전략 이후 산출물만 stale 처리하고 승인 사실과 수집 산출물은 유지한다.
6. quick 모드는 안전한 input/planning 확인을 근거와 함께 자동 승인할 수 있다. fact conflict, 미승인 주장, 비용, 권리, 정체성, 정책 gate는 항상 interrupt한다.

## 6. 테스트 계획

- 단위: 파서, 해시, 추상화, 사실 승격 차단, 모드 정규화.
- API: 모든 입력 형식, 권한/프로젝트 경계, version immutability, mode switch.
- 그래프: 실제 interrupt/`Command(resume=...)`, quick auto/manual 분기, 동일 thread resume, downstream metadata.
- 통합: brief 변경 시 downstream-only stale, 새로고침 상태 복구.
- 프런트/Playwright: 모드 선택→실행 생성→입력 패널→브리프 근거→새로고침→모드 전환.

실제 유료 provider는 호출하지 않고 mock/fake provider만 사용한다.

## 7. 자체 누락 검토

- 리뷰와 레퍼런스를 하나의 자유 입력 필드에 합치지 않는다.
- 리뷰/레퍼런스 인사이트가 `product_facts`를 생성하거나 승인하지 않는다.
- 브리프는 pack, Brand Kit, fact snapshot을 ID와 hash 양쪽으로 고정한다.
- quick 모드도 위험 gate를 생략하지 않는다.
- UI 표시만이 아니라 API 상태 전이, DB version, checkpoint/resume을 테스트한다.
- 기존 LG-5R 이미지 비용/검수 및 LG-6 활성 pack/Brand Kit 흐름은 보존한다.

