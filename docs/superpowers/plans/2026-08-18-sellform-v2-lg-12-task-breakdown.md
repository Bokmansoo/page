# LG-12 작업 분해: Visual Quality Bar·Golden Dataset 품질 게이트

## 범위와 공통 원칙

LG-12의 목표는 API와 renderer가 성공했다는 사실만으로 상세페이지를 완료하지 않고, LG-11까지 만들어진 immutable `DetailPageVersion`과 동일 frozen output을 대상으로 사실성·제품 정체성·한국어·레이아웃·브랜드·채널·출력 일치 품질을 검증해 판매 가능한 결과만 최종 승격하는 것이다.

현재 기준선은 `TASK-12.1` Contract Golden Dataset v1 완료·PASS, `TASK-12.2` 미착수다. TASK-12.1의 trusted hash와 기존 5 category×3 product case는 LG-10/LG-11 frozen contract 회귀 기준으로 변경하지 않는다. LG-12I와 `TASK-12.1R` Product Intake Golden Dataset v2가 완료되기 전에는 TASK-12.2 이후 evaluator·threshold·quality gate 구현을 시작하지 않는다.

- 원본 요구사항은 `ARC-08`, `QA-01`~`QA-06`, `FACT-01`~`FACT-05`, `VQB-01`~`VQB-08`이다.
- production LangGraph와 LG-9 approved asset manifest, LG-10 canonical assembly/renderer/frozen version/export, LG-11 Canvas/channel safety/version restore 계약을 그대로 사용한다.
- visual quality 판정은 제품 사실의 진위를 만들어내지 않는다. 사실·권리·정책 판정은 승인된 fact/evidence/provenance로, 이미지·레이아웃 판정은 frozen asset과 renderer geometry로 각각 수행한다.
- 기본 품질 gate는 fake provider와 고정 fixture만으로 외부 비용 없이 결정론적으로 재현돼야 한다. real provider 검증은 명시적 opt-in smoke로 분리한다.
- 점수는 하나의 불투명 값으로 만들지 않는다. 제품 정체성 20, 사실·정책 안전성 20, 레이아웃·시각적 완성도 20, 한국어 카피·가독성 15, Brand Kit 일치 10, 장면 다양성·섹션 흐름 10, 채널 출력 품질 5의 영역과 하위 지표를 보존한다.
- 치명 오류는 점수와 별도로 기록하며 1건이라도 있으면 완료·최종 승격·export를 차단한다. 자동 PASS는 총점 85 이상이고 모든 영역 점수가 70 이상일 때만 가능하다.
- 모든 report는 frozen source/version ID, snapshot hash, asset manifest hash, dataset/evaluator/threshold version과 section/scene/element/asset/copy/fact/evidence identity를 구조화해 기록한다.
- 모든 report는 input mode, source/truth/confirmation/master version ID, source fidelity, prohibited inference count, unknown fact count와 clarification count를 frozen metadata로 추가 기록한다.
- unsupported claim, prohibited inference, missing seller confirmation, unconfirmed rights와 product identity drift는 점수로 상쇄할 수 없는 critical failure다.
- 기존 channel safety의 경고·차단은 LG-12가 재사용하는 입력이다. LG-12가 별도의 경쟁하는 safe-area validator를 만들지 않는다.
- LG-13의 SLO, telemetry, 운영 dashboard, recovery sweep과 LG-14 Detail Page Beta·채널 최종화는 포함하지 않는다.
- legacy/mock execution path에 새 기능을 추가하지 않는다. fake provider는 production LangGraph 경로에 주입되는 결정론적 provider일 뿐 별도 실행 경로가 아니다.

---

## TASK-12.1 — Versioned Golden Dataset 계약과 기준 fixture

### 목표

생활용품·뷰티·식품·패션·전자제품 5개 기존 category pack마다 최소 3개 제품을 가진, 해시로 식별되는 재현 가능한 Golden Dataset v1 계약을 확정한다.

### 요구사항

- dataset, case, reference asset, expected output, human rubric 각각에 stable ID와 schema version을 둔다.
- 각 case에 입력 asset ID/SHA-256, 승인 fact/evidence ID, 권리 상태, 기대 category, 필수 section/scene, 금지 claim, identity-critical 특징, 기대 manifest/section/copy identity, 대상 channel, 사람 평가 기준을 포함한다.
- fake 결과에는 exact fixture/hash 기대값을 둘 수 있지만 real 결과에는 생성 bytes의 exact hash를 요구하지 않고 구조·threshold·rubric 기대값을 둔다.
- dataset content hash는 canonical serialization로 계산하고, 수정은 기존 version 덮어쓰기가 아니라 새 dataset version으로만 허용한다.
- 중복 case ID, 잘못된 SHA-256, 누락 category, category당 3개 미만, rights 미확정 final asset을 schema validation에서 차단한다.
- 원본·fixture asset은 권리와 provenance를 명시하며 외부 URL이나 mutable DB 현재값에 의존하지 않는다.

### Acceptance Criteria

- Golden Dataset v1이 5개 category와 category당 최소 3개 case를 포함한다.
- 동일 dataset 파일은 환경과 실행 순서에 무관하게 동일 content hash를 만든다.
- case마다 reference/golden asset 및 expected output identity와 사람 rubric이 완전하게 연결된다.
- invalid hash, 누락 rights, 중복 identity, 최소 case 수 미달 dataset은 명시적으로 거부된다.
- 기존 version을 변경해도 과거 report가 참조한 dataset version/hash가 바뀌지 않는다.

### 예상 변경 파일

- `backend/src/schemas/`의 기존 versioned artifact schema 또는 최소 LG-12 dataset schema
- `backend/src/services/`의 기존 canonical hash/validation helper
- `backend/tests/fixtures/lg12_golden_dataset/v1/`
- `backend/tests/test_lg12_golden_dataset_contract.py`

### 관련 테스트

- 5 category × 3 case 최소 구성 검증
- canonical hash 결정성 및 dataset version 불변성
- asset/fact/evidence/expected output identity 완전성
- invalid SHA-256, rights, duplicate, minimum-count rejection

### 다른 Task와의 의존성

- 선행: LG-6 category pack, LG-9 asset manifest, LG-10 frozen version 계약
- 후행: TASK-12.2~12.12 전체가 dataset version/case identity를 사용한다.

### fake-provider 검증 범위

- 모든 fixture와 expected identity를 로컬에서 로드하고 schema/hash를 반복 검증한다.
- 외부 provider와 네트워크 호출은 0회다.

### opt-in real-provider 검증 범위

- dataset schema 자체에는 real 호출이 없다.
- real smoke가 선택됐을 때도 동일 case/rubric/version을 사용하되 exact generated image hash는 비교하지 않는다.

---

## TASK-12.1R — Product Intake Golden Dataset v2 계약

### 목표

완료된 Contract Golden Dataset v1을 수정하지 않고, LG-12I의 세 first-class 입력 모드와 immutable source/truth/confirmation/master 계약을 검증하는 별도 Product Intake Golden Dataset v2를 정의한다.

### 요구사항

- 생활용품·뷰티·식품·패션·전자제품 5개 category와 `owned_product_url`·`photo_only`·`manual` 3개 input mode 조합의 정확히 15개 stable case를 둔다.
- 각 case는 input mode, raw input fixture identity, `ProductSourceSnapshotVersion`, `ProductTruthVersion`, `SellerConfirmationVersion`, `ProductCreativeBriefVersion`, `CommerceCreativeMasterVersion`의 ID/hash와 기대 lineage를 포함한다.
- source fidelity, 허용 evidence, unknown fact, conflict, prohibited inference, rights/provenance, seller confirmation과 최대 3개 clarification 기대값을 구조화한다.
- expected downstream identity는 기존 Product Creative Brief, approved fact/asset, DetailPage canonical input과 source master reference를 연결하되 대용량 내용을 복사하지 않는다.
- v2는 별도 schema/dataset version/trusted registry hash를 사용하며 v1 case와 trusted hash를 덮어쓰거나 재해석하지 않는다.
- fixture는 외부 URL의 mutable 현재 응답이나 real provider에 의존하지 않고 deterministic capture/photo/manual 자료를 사용한다.

### Acceptance Criteria

- 정확히 5 category×3 input mode의 15개 case와 고유 stable ID가 존재한다.
- 세 mode가 동일 normalized product와 master contract를 만들며 mode별 source provenance 차이는 보존된다.
- unsupported inference, 미확인 rights, 누락 seller confirmation, 3개 초과 clarification 기대값은 invalid case로 거부된다.
- source/truth/confirmation/master 중 하나의 hash·lineage를 변조하면 trusted validation이 실패한다.
- 같은 v2 fixture를 반복 load하면 동일 canonical dataset/case/master identity를 만든다.
- v1 load/validate 결과와 trusted hash는 v2 추가 전후에 동일하다.

### 예상 변경 파일

- LG-12I에서 확정한 source/truth/confirmation/master schema와 canonical hash helper
- `backend/tests/fixtures/lg12_golden_dataset/v2/`
- `backend/tests/test_lg12_product_intake_golden_dataset.py`
- 기존 trusted Golden Dataset registry

### 관련 테스트

- 5 category×3 input mode collection/count/stable ID
- deterministic source/truth/confirmation/master lineage와 canonical hash
- prohibited inference/unknown/rights/confirmation/clarification validation
- v1 immutability·trusted hash regression
- provider/outbox/cost approval 0회

### 다른 Task와의 의존성

- 선행: LG-12I 전체 production contract, 완료된 TASK-12.1 v1
- 후행: TASK-12.2~12.12가 v1 contract regression과 v2 intake lineage를 함께 사용한다.

### fake-provider 검증 범위

- capture/photo/manual 고정 fixture로 세 mode의 production intake normalization과 lineage를 외부 비용 없이 반복 검증한다.
- VLM/OCR은 production provider interface에 연결된 deterministic fake 결과를 사용한다.

### opt-in real-provider 검증 범위

- dataset 작성·기본 검증에서는 real provider를 호출하지 않는다.
- TASK-12.12 opt-in smoke가 v2 대표 case를 사용할 수 있지만 exact OCR/VLM bytes나 생성 이미지 hash를 baseline으로 요구하지 않는다.

---

## TASK-12.2 — Versioned QA report·threshold profile 계약

### 목표

모든 evaluator가 공유하는 투명한 영역별 결과, 치명 오류, 영향 identity, routing code와 threshold를 하나의 immutable versioned QA report로 정의한다.

### 요구사항

- report는 frozen `DetailPageVersion` ID/snapshot hash, approved manifest hash, channel, dataset version/case, evaluator versions, threshold profile version을 고정한다.
- report metadata는 input mode, source/truth/confirmation/master version ID, source fidelity, prohibited inference count, unknown fact count와 clarification count를 고정한다.
- 각 dimension은 0~100 점수, weight, 하위 metric, evidence, status를 별도로 보존한다.
- finding은 severity, reason code, message, section/scene/element/asset/copy/fact/evidence ID와 재작업 대상 identity를 구조화한다.
- critical finding, total score, per-dimension score, gate result, routing code를 분리한다.
- routing code는 `COPY_REWORK`, `PLAN_REWORK`, `VISUAL_REWORK`, `IMAGE_REWORK`, `SELLER_REVIEW`, `BLOCKED_POLICY`, `PASS`만 허용한다.
- threshold profile v1은 critical 0, total 85 이상, 모든 영역 70 이상을 고정하며 canonical report hash를 만든다.
- report 저장과 AgentRun durable projection은 같은 serialization/projection helper를 사용하고 mutable page state를 다시 읽지 않는다.
- unsupported claim, prohibited inference, missing seller confirmation, unconfirmed rights와 product identity drift reason code를 critical finding으로 허용하고 일반 점수와 분리한다.

### Acceptance Criteria

- 동일 frozen input/evaluator/profile은 동일 report payload와 report hash를 만든다.
- 단일 총점만 있는 report, target identity가 없는 failure, 허용되지 않은 routing code는 거부된다.
- report에서 자동 metric과 human rubric 결과를 구분하면서 같은 case/version에 함께 연결할 수 있다.
- checkpoint/history rebuild 이후 동일 report identity와 gate 결과가 복원 가능한 저장 계약을 가진다.
- 필수 intake/source/master metadata가 없거나 source lineage가 일치하지 않는 report는 incomplete로 거부된다.

### 예상 변경 파일

- `backend/src/db/models.py` 및 필요한 migration
- `backend/src/schemas/`의 graph/quality schema
- `backend/src/services/langgraph_run_service.py`
- 기존 canonical hash/projection helper가 있는 service
- `backend/tests/test_lg12_quality_report_contract.py`

### 관련 테스트

- report canonical hash/immutability
- dimension/finding/identity/routing schema validation
- threshold profile version 고정
- durable projection/rebuild round trip

### 다른 Task와의 의존성

- 선행: LG-12I, TASK-12.1, TASK-12.1R
- 후행: TASK-12.3~12.10 evaluator·graph·UI가 이 report를 사용한다.

### fake-provider 검증 범위

- 고정 report fixture로 serialization, projection, threshold metadata를 반복 검증한다.
- provider 호출은 없다.

### opt-in real-provider 검증 범위

- real 결과도 동일 report schema를 사용한다는 contract만 검증한다.
- report 저장 자체는 provider를 호출하지 않는다.

---

## TASK-12.3 — Fact·rights·policy critical evaluator

### 목표

frozen copy와 asset이 승인 사실·evidence·rights/provenance 범위를 벗어나지 않는지 판정하고, visual score와 독립된 사실·정책 안전성 결과를 만든다.

### 요구사항

- 모든 수치·효능·인증·구성·가격 claim을 frozen copy provenance의 approved fact/evidence ID와 대조한다.
- `narrative_non_claim`과 fact-backed copy를 구분하고 충돌 fact는 자동 선택하지 않는다.
- 중국어, 금지 표현, QR, 워터마크, 타사 로고·가격 복제 신호를 구조화된 critical finding으로 기록한다.
- 최종 asset의 rights/provenance/content hash를 LG-9/LG-10 frozen manifest와 대조한다.
- 이미지나 LLM의 시각 추정으로 business fact를 새로 승인하지 않는다.
- 사실/권리 치명 오류는 점수와 무관하게 `BLOCKED_POLICY` 또는 evidence/seller review 대상으로 판정한다.
- Product Truth와 Seller Confirmation 범위를 벗어난 unsupported claim, prohibited inference, missing seller confirmation과 unconfirmed rights를 source/truth/confirmation identity에 연결된 critical finding으로 기록한다.

### Acceptance Criteria

- 승인 fact ID가 없는 fact claim과 rights 미확정 final asset이 critical failure로 탐지된다.
- narrative copy는 사실 claim으로 잘못 승격되지 않고 fact claim은 단순 visual warning으로 약화되지 않는다.
- finding이 copy/fact/evidence/asset ID와 frozen source hash를 직접 포함한다.
- valid frozen provenance/rights case는 결정론적으로 통과한다.
- source/truth/confirmation lineage가 없거나 불일치한 claim은 점수와 관계없이 통과하지 않는다.
- evaluator 실행은 provider, outbox, cost approval, page mutation을 발생시키지 않는다.

### 예상 변경 파일

- `backend/src/services/fact_evidence_service.py`
- `backend/src/services/copy_quality_guard.py`
- `backend/src/services/page_finalization_service.py`의 기존 frozen provenance helper
- LG-12 quality evaluator를 조정하는 기존 validation/service 위치
- `backend/tests/test_lg12_fact_rights_quality.py`

### 관련 테스트

- approved/unapproved numeric and nonnumeric claim
- conflicting fact와 narrative classification
- forbidden Chinese/QR/watermark/third-party mark
- seller-owned/approved vs reference-only/supplier/blocked asset
- content hash/provenance mismatch

### 다른 Task와의 의존성

- 선행: TASK-12.1, TASK-12.2, LG-7/LG-11 provenance 계약
- 후행: TASK-12.8 aggregate gate, TASK-12.9 routing, TASK-12.10 export 승격

### fake-provider 검증 범위

- 고정 Korean copy/fact/rights fixture로 critical 판정을 검증하며 외부 호출은 0회다.

### opt-in real-provider 검증 범위

- real provider로 이미 생성된 frozen 결과를 읽기 전용으로 평가할 수 있다.
- evaluator 자체가 text/image provider를 호출하거나 fact를 승인하지 않는다.

---

## TASK-12.4 — Image quality·product identity evaluator

### 목표

LG-9가 보존한 scene별 identity/OCR/crop/resolution/safety/rights 증거와 frozen asset bytes를 재사용해 이미지 품질과 제품 정체성을 독립 dimension으로 평가한다.

### 요구사항

- approved manifest의 scene/section/asset ID와 SHA-256을 실제 저장 bytes 및 LG-9 검사 report와 대조한다.
- 형태, 색상, 버튼/컨트롤, 포트/커넥터, 구성품, 로고 정책, OCR 오염, crop, 해상도를 개별 metric/finding으로 보존한다.
- identity evidence가 부족하거나 판정 불가한 상태를 `passed`로 간주하지 않는다.
- seller가 LG-9에서 명시적으로 승인한 review 결과는 approval identity와 함께 기록하되 fact/rights critical error를 override하지 못한다.
- 중복 scene 이미지, 비정상 저해상도, 잘림은 scene/asset identity를 가진 failure로 반환한다.
- source snapshot·master identity와 최종 제품의 형태·구성·브랜드 identity가 달라진 product identity drift를 critical finding으로 반환한다.
- 새 CV pipeline을 만들지 않고 `product_identity_validator`와 LG-9 structured report를 확장·재사용한다.

### Acceptance Criteria

- 정상 fixture는 identity와 image submetric을 가진 결정론적 결과를 만든다.
- shape/color/button/port/component/logo 불일치와 OCR/crop/resolution failure가 해당 scene/asset에 연결된다.
- evidence 부족은 `needs_review`이며 자동 PASS가 아니다.
- frozen hash와 실제 bytes 불일치는 critical failure다.
- source/master identity와 결과 asset 사이의 product identity drift는 seller review 가능한 단순 경고로 약화되지 않는다.
- image quality evaluator만 실행해 provider 재생성이나 비용이 발생하지 않는다.

### 예상 변경 파일

- `backend/src/services/product_identity_validator.py`
- `backend/src/services/langgraph_image_generation_service.py`의 기존 structured report reader
- 기존 image validation schema/helper
- `backend/tests/test_lg12_image_identity_quality.py`
- `backend/tests/fixtures/lg12_golden_dataset/v1/assets/`

### 관련 테스트

- identity feature별 pass/fail/insufficient evidence
- OCR/crop/resolution/duplicate scene
- manifest SHA-256와 actual bytes 일치/불일치
- seller review identity 보존 및 critical non-override

### 다른 Task와의 의존성

- 선행: TASK-12.1, TASK-12.2, LG-9 identity report/manifest
- 후행: TASK-12.8, TASK-12.9의 `IMAGE_REWORK`

### fake-provider 검증 범위

- 서로 다른 고정 이미지 bytes와 LG-9 report fixture로 모든 metric을 재현하며 비용은 0이다.

### opt-in real-provider 검증 범위

- 명시적으로 생성한 최소 1개 scene 결과를 같은 evaluator로 평가한다.
- real 호출 횟수·case는 smoke 설정에서 제한하며 기본 suite에서는 반드시 skip한다.

---

## TASK-12.5 — Korean copy·readability evaluator

### 목표

이미지 내부 텍스트가 아니라 frozen editable text layer를 기준으로 한국어 카피 품질, 반복, 과장, CTA와 가독성을 평가한다.

### 요구사항

- title/body/spec/notice/CTA를 stable copy field와 section ID 단위로 평가한다.
- 깨진 한글, 불필요한 중국어, 반복 문장, 과장·금지 표현, 비문, 지나치게 긴 제목/문단, CTA 누락을 별도 metric으로 둔다.
- 사실성은 TASK-12.3 결과를 참조하고 copy evaluator가 fact/evidence를 임의로 승인하거나 변경하지 않는다.
- typography의 font size/line height/contrast/overflow는 TASK-12.6이 담당하며 copy 내용 평가와 분리한다.
- 결정론적 규칙을 우선 사용하고 선택적 linguistic evaluator가 필요하면 기존 centralized LLM router와 evaluator version을 사용한다.
- 자동 결과와 human Korean rubric을 동일 report case에 별도 필드로 저장한다.

### Acceptance Criteria

- 정상 Korean fixture와 broken/duplicate/exaggerated/overlong fixture가 field별 structured 결과를 낸다.
- finding이 section ID, copy artifact ref/version/hash, field name을 포함한다.
- fact-changing copy는 copy rework만으로 승인되지 않고 TASK-12.3/evidence route를 유지한다.
- 같은 frozen copy와 evaluator version은 같은 결과를 만든다.

### 예상 변경 파일

- `backend/src/services/copy_quality_guard.py`
- `backend/src/services/commerce_content_quality_service.py`
- 기존 centralized LLM evaluator/router schema(실제로 필요한 경우만)
- `backend/tests/test_lg12_korean_copy_quality.py`

### 관련 테스트

- Korean corruption/Chinese leakage/duplicate/exaggeration/CTA/readability
- stable copy identity와 evaluator version
- fact evaluator와 책임 분리
- optional LLM disabled deterministic result

### 다른 Task와의 의존성

- 선행: TASK-12.1~12.3, LG-10 text-layer/frozen copy 계약
- 후행: TASK-12.8, TASK-12.9의 `COPY_REWORK`

### fake-provider 검증 범위

- rule-based fixture만으로 핵심 copy regression을 전부 검증하며 LLM/provider 호출은 0회다.

### opt-in real-provider 검증 범위

- 선택적 text evaluator를 켠 경우에만 소수 Golden copy를 기존 router로 평가한다.
- 기본 gate와 fake matrix는 이 결과에 의존하지 않는다.

---

## TASK-12.6 — Layout·typography·Brand Kit·scene flow evaluator

### 목표

frozen canonical renderer의 section/element geometry와 Brand Kit identity를 기준으로 시각적 완성도, 위계, 가독성, 브랜드 일치와 장면 흐름을 평가한다.

### 요구사항

- LG-11 effective geometry/safe-area/overlap helper를 재사용해 clipping, unsafe overlap, spacing, section height, typography contrast와 위계를 평가한다.
- hidden element는 실제 render contract대로 제외하고 grouped/locked/background/logo/watermark는 frozen effective geometry로 평가한다.
- Brand Kit color/font/logo/watermark ID+hash가 frozen canonical input/renderer와 일치하는지 검사한다.
- scene role 다양성, 중복 이미지, required section 순서, final spec의 visible/final-position 계약을 평가한다.
- layout, typography, Brand Kit, scene-flow submetric을 하나로 뭉개지 않고 target identity와 함께 보존한다.
- channel별 hard limit은 TASK-12.7에서 담당하고 여기서는 renderer 자체의 composition 품질을 평가한다.

### Acceptance Criteria

- 잘림·겹침·저대비·비정상 여백/위계가 section/element identity를 가진 finding으로 반환된다.
- Brand Kit ID/hash 불일치와 rights-approved brand asset 적용 누락을 탐지한다.
- 중복 scene/잘못된 section 흐름/final spec 위반을 구조화해 탐지한다.
- hidden/intentional decorative overlap은 기존 LG-11 contract에 맞게 오탐 없이 처리된다.
- valid frozen renderer fixture는 동일한 submetric과 점수를 반복 생성한다.

### 예상 변경 파일

- `backend/src/services/page_visual_contract.py`
- `backend/src/services/page_finalization_service.py`의 frozen renderer reader
- `backend/src/services/commerce_renderer_service.py` 또는 기존 renderer contract
- `backend/tests/test_lg12_layout_brand_flow_quality.py`

### 관련 테스트

- clipping/overlap/contrast/spacing/hierarchy
- hidden/grouped/locked/decorative geometry
- Brand Kit color/font/logo/watermark identity
- scene diversity/section flow/final spec order

### 다른 Task와의 의존성

- 선행: TASK-12.1, TASK-12.2, LG-10 renderer, LG-11 Canvas safety
- 후행: TASK-12.8, TASK-12.9의 `VISUAL_REWORK`/`PLAN_REWORK`

### fake-provider 검증 범위

- frozen HTML/CSS/geometry와 deterministic fake assets로 시각 구조를 평가하며 provider 비용은 0이다.

### opt-in real-provider 검증 범위

- real-generated assets가 들어간 frozen renderer를 같은 geometry/Brand Kit evaluator로 읽기 전용 평가한다.
- 별도 이미지 생성 호출은 이 Task가 수행하지 않는다.

---

## TASK-12.7 — Channel constraint·preview/export parity evaluator

### 목표

LG-11 channel safety와 LG-10 frozen export 계약을 재사용해 channel별 출력 제약과 preview/PNG/JPG/copyable HTML/standalone HTML/ZIP/export-history parity를 검증한다.

### 요구사항

- 평가 channel은 frozen version/export artifact의 명시적 channel identity만 사용하고 silent fallback을 허용하지 않는다.
- LG-11 safe-area, width, height, overflow, overlap, Brand Kit geometry 결과를 공통 validation source로 사용한다.
- 동일 version의 section order/visibility/height, copy refs/hash, asset manifest/hash, Brand Kit refs/hash가 모든 output에서 일치하는지 검사한다.
- 파일 형식, 크기, channel width/height, 분할 경계, 필수 고지와 artifact token parsing을 검증한다.
- renderer 결과를 다시 생성해 mutable current page와 비교하지 않고 frozen snapshot과 artifact metadata/hash를 비교한다.
- parity mismatch와 unsafe channel output은 critical failure로 기록한다.

### Acceptance Criteria

- smartstore와 coupang fixture에서 preview 및 모든 export가 동일 version/channel/manifest를 사용한다.
- channel 불일치, malformed artifact token, missing channel, section/copy/asset parity mismatch가 구조화된 critical finding이 된다.
- 기존 LG-11 unsafe 409 contract와 LG-12 report의 reason/identity가 일치한다.
- 정상 standalone/copyable/export-history redownload는 parity PASS를 만든다.

### 예상 변경 파일

- `backend/src/services/page_visual_contract.py`
- `backend/src/services/export_service.py`
- `backend/src/api/pages.py`, `backend/src/api/exports.py`의 기존 frozen artifact reader
- `backend/tests/test_lg12_channel_parity_quality.py`

### 관련 테스트

- smartstore/coupang width/height/format/split constraints
- preview/PNG/JPG/copyable/HTML/ZIP/history manifest parity
- channel/token mismatch와 safe/unsafe contract
- hidden section/height/Brand Kit output parity

### 다른 Task와의 의존성

- 선행: TASK-12.1, TASK-12.2, LG-10 export, LG-11 safety
- 후행: TASK-12.8 aggregate와 TASK-12.10 export 승격

### fake-provider 검증 범위

- 기존 frozen fake output을 사용해 모든 format/channel을 로컬에서 비교하며 provider 호출은 0회다.

### opt-in real-provider 검증 범위

- real asset이 포함된 동일 frozen version에 대해 export parity만 확인한다.
- export 검증 중 provider를 재호출하지 않는다.

---

## TASK-12.8 — Dimension aggregation·Visual Quality Bar 판정

### 목표

TASK-12.3~12.7의 투명한 evaluator 결과를 versioned threshold profile로 합산하고 치명 오류·총점·영역별 기준에 따라 단일 gate/routing 결정을 만든다.

### 요구사항

- 7개 원본 score 영역과 고정 weight를 사용하고 각 영역의 구성 submetric을 report에 남긴다.
- critical finding이 1개라도 있으면 점수와 무관하게 실패한다.
- critical 0, total 85 이상, 모든 영역 70 이상일 때만 자동 `PASS`를 반환한다.
- missing evaluator/dimension을 0점 또는 명시적 incomplete로 처리하고 PASS로 간주하지 않는다.
- failure reason과 section/scene/element/asset/copy/fact/evidence identity로 최소 재작업 범위를 계산한다.
- routing 우선순위는 policy/fact critical, image identity, copy, planning/visual, seller review 순으로 명시하고 결과를 결정론적으로 만든다.
- seller 승인 가능 항목과 절대 override 불가한 fact/rights/parity critical을 구분한다.

### Acceptance Criteria

- boundary fixture에서 total 84.99, 영역 69.99, critical 1건이 각각 실패한다.
- total 85 이상·모든 영역 70 이상·critical 0인 report만 PASS한다.
- 같은 evaluator result set은 순서와 무관하게 같은 score/gate/route/report hash를 만든다.
- failure마다 관련 identity와 최소 재작업 대상이 누락 없이 보존된다.
- 단일 opaque score나 visual 판정으로 fact failure를 덮어쓸 수 없다.

### 예상 변경 파일

- LG-12 quality aggregation을 담당할 기존 validation/service 위치
- `backend/src/schemas/`의 threshold/report schema
- `backend/tests/test_lg12_visual_quality_bar.py`

### 관련 테스트

- weight/rounding/boundary/critical precedence
- incomplete evaluator fail-closed
- deterministic routing/minimal target selection
- seller-reviewable vs non-overridable critical

### 다른 Task와의 의존성

- 선행: TASK-12.2~12.7
- 후행: TASK-12.9~12.12

### fake-provider 검증 범위

- synthetic dimension fixtures와 Golden fake report로 모든 threshold branch를 비용 없이 검증한다.

### opt-in real-provider 검증 범위

- real smoke report에도 동일 profile/version/aggregation을 적용한다.
- real 결과라고 threshold를 완화하거나 별도 score 공식을 사용하지 않는다.

---

## TASK-12.9 — Production LangGraph QA node·선택적 재작업 routing

### 목표

LG-10/11 frozen candidate 뒤에 production QA node를 연결하고, 실패 이유에 맞는 기존 node/path만 최대 2회 선택적으로 재실행한 뒤 seller review로 전환한다.

### 요구사항

- 빠른 생성과 단계별 검토 모두 동일 QA node와 Quality Bar를 반드시 통과한다.
- `COPY_REWORK`, `PLAN_REWORK`, `VISUAL_REWORK`, `IMAGE_REWORK`, `SELLER_REVIEW`, `BLOCKED_POLICY`, `PASS`를 기존 production node/path에 명시적으로 매핑한다.
- `IMAGE_REWORK`는 LG-9/LG-11 scene regeneration과 새 cost approval/outbox/worker/review 계약을 우회하지 않는다.
- fact/evidence 변경은 LG-11 evidence review, copy는 copy provenance, visual/layout은 page assembly/renderer selective reassembly를 재사용한다.
- section/scene/copy별 retry counter를 durable state에 기록하고 동일 node/target 자동 재작업은 최대 2회로 제한한다.
- 2회 후에도 실패하면 비교 후보, 문제 설명, 영향 identity와 허용 사용자 행동을 seller review interrupt로 제공한다.
- checkpoint/history rebuild와 중복 resume에서 QA run, retry, provider 호출, candidate version이 중복되지 않게 한다.

### Acceptance Criteria

- QA failure reason과 일치하는 node/target만 재실행되고 unrelated frozen identity는 유지된다.
- 자동 재작업은 target/node별 최대 2회이며 세 번째에는 seller review로 간다.
- image rework는 비용 승인 전 provider 0회이고 승인 후 대상 scene만 기존 outbox를 사용한다.
- 빠른 생성 모드도 QA를 거치며 직접 finalize/export로 우회하지 못한다.
- restart/resume/rebuild와 중복 호출 후 retry count, pending review, report/version lineage가 동일하다.

### 예상 변경 파일

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- 기존 `langgraph_review_service.py`, `langgraph_image_generation_service.py`
- `backend/src/api/graph_runs.py`
- `backend/tests/test_lg12_quality_graph_routing.py`

### 관련 테스트

- routing code별 production graph target
- quick/expert QA non-bypass
- max-two retry와 seller escalation
- image cost/outbox reuse 및 unrelated identity preservation
- checkpoint/rebuild/idempotency

### 다른 Task와의 의존성

- 선행: TASK-12.8, LG-9~LG-11 production flows
- 후행: TASK-12.10~12.12

### fake-provider 검증 범위

- production compiled graph에 deterministic evaluator/provider를 주입해 모든 route와 재작업 횟수를 검증한다.
- fake provider의 actual external cost는 0이다.

### opt-in real-provider 검증 범위

- `IMAGE_REWORK` 한 scene만 명시적 비용 승인 아래 실행한다.
- 기본 graph test에서는 real provider 환경변수가 있어도 실행하지 않는다.

---

## TASK-12.10 — Final promotion·export gate와 seller quality report UI

### 목표

QA를 통과한 frozen candidate만 final version으로 승격하고, 실패 결과는 모든 preview/export 진입점에서 차단하며 판매자에게 구조화된 문제와 비교 후보를 제공한다.

### 요구사항

- frozen candidate 생성과 `is_final`/active 승격을 분리하고 PASS report ID/hash가 일치할 때만 최종 승격한다.
- critical/threshold/incomplete report와 stale report는 preview finalization 및 PNG/JPG/copyable HTML/standalone HTML/ZIP/history download에서 동일하게 차단한다.
- report의 source version/snapshot/manifest/channel이 요청 output과 정확히 일치해야 하며 mutable current page를 다시 읽지 않는다.
- UI는 영역별 점수, critical finding, 이유, 영향 section/scene/element/asset/copy identity, route, attempt, 비교 후보와 다음 행동을 보여준다.
- seller override는 QA-03에서 허용한 명시적 image review 범위만 provenance와 함께 기록하고 fact/rights/parity critical은 우회하지 못한다.
- 기존 LG-10/11 frozen version restore는 과거 report와 version identity를 유지하며, restore가 새 QA 통과를 위조하지 않는다.

### Acceptance Criteria

- 미달 candidate는 final/active로 승격되지 않고 모든 export가 동일 structured 409 quality contract로 차단된다.
- PASS report와 frozen hash가 일치하는 candidate만 final/export 가능하다.
- report가 다른 version/channel/manifest를 가리키면 fail-closed한다.
- seller UI가 failure identity와 최대 2회 비교 후보/문제 설명/허용 행동을 실제 production API에서 표시한다.
- report 조회·차단만으로 provider/outbox/cost approval이 발생하지 않는다.

### 예상 변경 파일

- `backend/src/services/page_finalization_service.py`
- `backend/src/services/export_service.py`
- `backend/src/api/pages.py`, `backend/src/api/exports.py`, `backend/src/api/graph_runs.py`
- `frontend/src/components/planning/GraphReviewPanel.tsx`
- `frontend/src/app/workspace/projects/[id]/render/DetailPageRenderClient.tsx`
- `backend/tests/test_lg12_final_promotion_gate.py`
- `frontend/e2e/lg12-quality-report-gate.spec.ts`

### 관련 테스트

- candidate vs final promotion
- stale/mismatched/missing report fail-closed
- all output endpoints identical quality 409
- seller report/compare/allowed action UI payload
- LG-10/LG-11 restore/export regression

### 다른 Task와의 의존성

- 선행: TASK-12.8, TASK-12.9
- 후행: TASK-12.11, TASK-12.12

### fake-provider 검증 범위

- pass/fail fake reports로 promotion, UI, 모든 export gate를 반복 검증하며 외부 비용은 0이다.

### opt-in real-provider 검증 범위

- real smoke가 만든 frozen version/report도 동일 promotion/export gate를 사용한다.
- UI나 export 요청이 provider를 호출하지 않는다.

---

## TASK-12.11 — Baseline regression comparator·fake-provider Golden suite

### 목표

Prompt Pack·model adapter·renderer·evaluator 변경 전후의 versioned report를 비교하고, Contract v1과 Product Intake v2의 각 15개 Golden case를 production LangGraph로 반복 실행하는 기본 LG-12 release gate를 만든다.

### 요구사항

- baseline과 candidate의 dataset version, frozen version, prompt/pack/model/renderer/evaluator/profile version을 명시한다.
- critical finding 증가, total/per-dimension threshold 미달, score 하락, expected identity/parity 변경을 구조화된 regression으로 비교한다.
- baseline update는 명시적 command/review 없이 자동으로 덮어쓰지 않는다.
- `lg12_fake_quality_gate` marker/suite는 Contract Golden Dataset v1의 15 case와 Product Intake Golden Dataset v2의 5 category×3 input mode, 3 design direction, smartstore/coupang, pass/fail route fixture를 포함한다.
- suite는 production LangGraph → frozen candidate → evaluator → rework/escalation → promotion/export gate를 직접 사용한다.
- actual provider cost/call이 0임을 호출 spy와 outbox/provider mode로 검증한다.

### Acceptance Criteria

- 같은 revision의 fake suite는 반복 실행해 동일 report hash/score/route를 만든다.
- baseline 대비 critical/threshold/identity/parity regression이 release failure로 반환된다.
- evaluator 또는 threshold version 변경이 비교 metadata에 명확히 드러난다.
- baseline 파일이 test run 중 변경되지 않는다.
- legacy/mock orchestration을 경유하지 않고 production LangGraph path를 검증한다.

### 예상 변경 파일

- `backend/tests/test_lg12_fake_quality_gate.py`
- `backend/tests/fixtures/lg12_golden_dataset/v1/expected_reports/`
- `backend/pytest.ini` 또는 기존 marker 설정 파일
- 기존 test helper/quality comparison helper
- 필요 시 `frontend/e2e/lg12-golden-matrix.spec.ts`

### 관련 테스트

- v1 15-case contract와 v2 15-case input-mode collection/count/repeatability
- baseline/candidate comparison dimensions
- critical/threshold/identity/parity regression
- fake cost/provider call 0
- production path marker collection

### 다른 Task와의 의존성

- 선행: LG-12I, TASK-12.1, TASK-12.1R, TASK-12.2~12.10
- 후행: TASK-12.12와 LG-12 최종 quality gate

### fake-provider 검증 범위

- 이 Task의 주 검증 범위다. 모든 필수 case와 routing/promotion/export regression을 외부 비용 없이 실행한다.

### opt-in real-provider 검증 범위

- baseline comparator는 real report도 읽을 수 있지만 기본 fake marker는 real artifact를 요구하지 않는다.
- real baseline은 fake deterministic baseline과 별도 namespace/version으로 저장한다.

---

## TASK-12.12 — Opt-in real-provider smoke와 최종 LG-12 golden matrix

### 목표

기본 fake release gate와 비용이 드는 real-provider smoke를 실행 조건과 판정 방식까지 분리하고, LG-12 원본 완료 조건 전체를 최종 matrix로 검증한다.

### 요구사항

- real smoke는 명시적 opt-in 환경변수와 사용 가능한 provider credentials가 모두 있을 때만 수집/실행한다.
- 기본 pytest, `lg12_fake_quality_gate`, frontend build, Playwright 실행에는 real 호출이 절대 포함되지 않는다.
- real smoke는 대표 Golden case와 최소 scene 수로 제한하고 기존 LG-9 cost approval/outbox/worker를 사용한다.
- real-generated bytes는 exact hash가 아니라 frozen identity/provenance, critical 0, dimension threshold, human rubric 대상으로 평가한다.
- 최종 matrix는 dataset schema, 모든 evaluator, threshold, routing/max-two, seller escalation, promotion/export gate, restart/rebuild, fake repeatability를 요구사항 ID별로 연결한다.
- 실제 provider timeout/safety/unknown outcome에서 LG-9 dead-letter/retry·중복 과금 방지 정책을 유지한다.
- LG-13 telemetry/SLO와 LG-14 Detail Page Beta/channel finalization은 추가하지 않는다.

### Acceptance Criteria

- opt-in이 없으면 real smoke는 명확한 skip이고 provider 호출은 0회다.
- opt-in 시 제한된 case/scene만 비용 승인 후 호출되며 동일 request가 중복 dispatch되지 않는다.
- real 결과가 fake와 동일 report/profile/promotion contract를 사용한다.
- final fake matrix가 v1 5×3 Contract cases, v2 5 category×3 input mode와 LG-12 critical/85/70/rework/export 조건을 모두 직접 검증한다.
- LG-9~LG-11 핵심 regression과 production path 연결이 최종 gate에서 유지된다.

### 예상 변경 파일

- `backend/tests/test_lg12_real_provider_smoke.py`
- `backend/tests/test_lg12_final_golden_matrix.py`
- `frontend/e2e/lg12-quality-report-gate.spec.ts`
- 기존 pytest/Playwright marker 설정

### 관련 테스트

- default real smoke skip와 opt-in guard
- one-case/limited-scene/cost-approval/idempotency
- real report schema/threshold/promotion
- final requirement matrix와 LG-9~LG-11 regression selection
- frontend production build 및 seller report Playwright

### 다른 Task와의 의존성

- 선행: LG-12I, TASK-12.1, TASK-12.1R, TASK-12.2~12.11
- 후행: 없음. 이 Task가 LG-12 완료 gate다.

### fake-provider 검증 범위

- 최종 기본 gate는 `lg12_fake_quality_gate`와 final matrix를 전부 실행한다.
- 외부 provider 비용과 네트워크 의존성은 0이다.

### opt-in real-provider 검증 범위

- 명시적 opt-in에서만 대표 case/최소 scene smoke를 실행한다.
- 결과 변동성은 exact pixel/hash가 아니라 동일 frozen/report/threshold/human-rubric 계약으로 판정한다.

---

## 권장 구현 순서

```text
TASK-12.1 Contract Golden Dataset v1 (완료·PASS)
  → LG-12I Unified Product Intake & Commerce Creative Master
      → TASK-12.1R Product Intake Golden Dataset v2
          → TASK-12.2 QA report/profile
      → TASK-12.3 Fact/Rights
      → TASK-12.4 Image/Identity
      → TASK-12.5 Korean Copy
      → TASK-12.6 Layout/Brand/Flow
      → TASK-12.7 Channel/Parity
          → TASK-12.8 Quality Bar aggregation
              → TASK-12.9 LangGraph routing/rework
                  → TASK-12.10 promotion/export/UI gate
                      → TASK-12.11 fake regression suite
                          → TASK-12.12 real smoke/final matrix
```

TASK-12.1 Contract Golden Dataset v1은 완료·PASS 상태로 보존한다. LG-12I와 TASK-12.1R이 모두 완료된 뒤 TASK-12.2를 시작하며, TASK-12.3~TASK-12.7은 TASK-12.2가 확정된 뒤 서로 독립적으로 구현·테스트할 수 있다.

## 범위 밖

- LG-13 event telemetry, SLO/ETA dashboard, 운영 recovery command, 비용 집계 UI
- LG-14 Detail Page Beta의 legacy 전환 제거, 세 입력 모드 E2E와 채널 규격 최종화
- LG-15 Social Creative Kit, LG-16 Short-form Video Studio, LG-17 Campaign Content Pack
- 새로운 이미지 생성/CV pipeline 또는 기존 provider/router를 우회하는 evaluator 호출
- Golden 결과를 맞추기 위한 legacy 전용/fixture 전용 production 분기
