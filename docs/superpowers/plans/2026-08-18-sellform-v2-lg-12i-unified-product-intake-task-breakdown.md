# LG-12I 작업 분해: Unified Product Intake & Commerce Creative Master

작성일: 2026-08-18
상태: 구현 전 source of truth
상위 기획: [Sellform V2.1 AI Commerce Studio 최종 기획](../specs/2026-08-07-sellform-v2-ai-commerce-studio-v2.1-final-design.md)
로드맵: [Sellform V2.1 Sprint 로드맵](./2026-08-07-sellform-v2-ai-commerce-studio-v2.1-roadmap.md)

## 범위와 현재 기준선

LG-12I의 목표는 `owned_product_url`, `photo_only`, `manual`을 production LangGraph의 동등한 입력 모드로 만들고, 모두를 검증 가능한 하나의 상품 기준으로 수렴시키는 것이다.

```text
ProductSourceSnapshotVersion
  → ProductTruthVersion
  → SellerConfirmationVersion
  → ProductCreativeBriefVersion
  → CommerceCreativeMasterVersion
```

`ProductCreativeBriefVersion` compiler는 `ProductTruthVersion`, `SellerConfirmationVersion`, `BrandKitVersion`, 기존 review/reference provenance를 직접 입력으로 사용한다. `CommerceCreativeMasterVersion`은 그 결과를 reference하며 Creative Brief 생성의 입력이 되지 않는다. Category/Channel Pack과 Brand Kit는 이 단방향 compiler 입력에 포함된다.

- LG-5R~LG-11의 production LangGraph, fact/evidence, Creative Brief, rights, asset hash, frozen version과 checkpoint/history rebuild 계약을 재사용한다.
- `CommerceCreativeMasterVersion`은 원문·OCR·이미지·카피를 복사한 대형 JSON이 아니라 artifact ID/version/hash를 가진 immutable index다. 후속 reference는 기존 master 수정이 아니라 successor master version으로 추가한다.
- 관찰하지 못한 상품 정보는 unknown으로 남긴다. VLM/OCR/LLM이 unsupported fact·효능·인증·수치·구성품을 추측해 채우지 않는다.
- seller confirmation은 우선순위가 높은 최대 3개의 clarification만 한 cycle에 제시한다.
- reference-only, supplier, blocked, rights 미확정 asset은 final-use master reference가 될 수 없다.
- 이 문서는 LG-12I만 분해한다. Product Intake Golden Dataset v2의 실제 구현은 후속 `TASK-12.1R`, evaluator/threshold는 `TASK-12.2` 이후다.
- LG-13 SLO/dashboard, LG-14 Detail Page Beta finalization, LG-15~LG-17 Social/Video/Campaign production은 포함하지 않는다.
- legacy/compatibility execution path를 만들지 않고 centralized provider/router와 기존 service/helper를 우선 재사용한다.

---

## TASK-12I.1 — Intake version schema·canonical hash·lineage 계약

### 목표

네 intake/master immutable version의 최소 schema, canonical hash와 lineage를 먼저 고정하고 기존 `ProductCreativeBriefVersion`의 reference contract를 연결한다.

### 요구사항

- `ProductSourceSnapshotVersion`, `ProductTruthVersion`, `SellerConfirmationVersion`, `CommerceCreativeMasterVersion`에 stable ID, schema version, parent/source reference, creator run ID, canonical hash를 둔다.
- source snapshot은 input mode, source asset/document ID+SHA-256, capture/OCR/VLM artifact reference, provenance, rights, source fidelity를 가진다.
- truth는 approved candidate/unknown/conflict/prohibited inference와 evidence edge를 가진다.
- confirmation은 질문·응답·confirmed/rejected/unknown fact와 rights confirmation을 가진다.
- master는 version/hash reference만 보존하고 대용량 raw payload를 중복 저장하지 않는다.

### Acceptance Criteria

- 네 version의 invalid hash, broken lineage, unsupported schema version이 명시적으로 차단된다.
- 같은 canonical input은 순서와 환경에 무관하게 같은 hash를 만든다.
- 과거 version을 수정하지 않고 successor로만 변경할 수 있다.
- master payload에 raw image/document/OCR 전체 bytes가 들어가지 않는다.

### 예상 변경 파일

- `backend/src/db/models.py`와 migration
- `backend/src/schemas/`의 versioned intake/master schema
- 기존 canonical hash/version helper
- `backend/tests/test_lg12i_version_contract.py`

### 관련 테스트

- schema/hash/lineage round trip
- tamper·broken parent·mutable overwrite rejection
- master reference-only payload 검증

### 다른 Task와의 의존성

- 선행: LG-10/LG-11 frozen version/hash 계약
- 후행: TASK-12I.2~12I.10 전체

### fake-provider 검증 범위

- 고정 schema fixture만 사용하며 provider/outbox/cost approval 호출은 0회다.

### opt-in real-provider 검증 범위

- 없음. version contract는 외부 provider와 독립적이다.

---

## TASK-12I.2 — Unified intake envelope·production input router

### 목표

세 입력 모드를 하나의 versioned request envelope와 production LangGraph input router로 연결한다.

### 요구사항

- request에 명시적 `input_mode`와 mode별 typed payload를 사용한다.
- mode별 필수·금지 필드를 backend에서 검증하고 silent mode 추론을 하지 않는다.
- 선택 mode를 run snapshot, checkpoint와 durable projection에 고정한다.
- 기존 project/workspace authorization과 asset picker contract를 재사용한다.
- 이 Task에서는 mode별 OCR/VLM/수집 로직이나 master 생성을 구현하지 않는다.

### Acceptance Criteria

- 세 mode의 valid envelope가 같은 production graph entry로 들어간다.
- missing/mixed/unknown mode payload가 structured 4xx로 차단된다.
- 새로고침·public resume 후 같은 input mode와 source request identity가 복원된다.
- legacy orchestration으로 우회하는 쓰기 경로가 없다.

### 예상 변경 파일

- `backend/src/api/projects.py` 또는 기존 graph run 생성 API
- `backend/src/api/graph_runs.py`
- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- `frontend/src/app/workspace/projects/new/page.tsx`
- `backend/tests/test_lg12i_input_router.py`

### 관련 테스트

- mode envelope validation과 authorization
- production graph entry/routing
- checkpoint/projection round trip

### 다른 Task와의 의존성

- 선행: TASK-12I.1
- 후행: TASK-12I.3~12I.5 mode adapter, TASK-12I.9 durability

### fake-provider 검증 범위

- 세 envelope이 같은 compiled graph로 진입하는 것까지 비용 없이 검증한다.

### opt-in real-provider 검증 범위

- 없음. 입력 routing 자체는 real provider를 호출하지 않는다.

---

## TASK-12I.3 — Manual input source snapshot adapter

### 목표

수동 상품 정보와 판매자 창작 방향을 분리해 immutable source snapshot으로 만든다.

### 요구사항

- 기존 seller fact ingestion과 Creative Brief input helper를 재사용한다.
- 수동 입력을 fact candidate, creative direction, unknown과 source evidence로 분리한다.
- 수치·효능·인증·구성·권리 정보는 seller-provided provenance를 가진다.
- manual adapter가 fact를 자동 승인하거나 Creative Brief를 미리 생성하지 않는다.

### Acceptance Criteria

- manual payload가 source snapshot ID/hash와 구조화 fact candidate를 만든다.
- creative direction이 approved fact로 섞이지 않는다.
- 빈 값·충돌 값·미확인 권리는 unknown/conflict로 남는다.
- 동일 입력은 deterministic snapshot identity를 만든다.

### 예상 변경 파일

- `backend/src/services/product_intake_service.py`
- `backend/src/services/seller_fact_ingestion_service.py`
- `backend/src/services/intake_structuring_service.py`
- `backend/tests/test_lg12i_manual_intake.py`

### 관련 테스트

- fact/creative separation
- numeric/claim/right provenance
- deterministic snapshot/tamper rejection

### 다른 Task와의 의존성

- 선행: TASK-12I.1, TASK-12I.2
- 후행: TASK-12I.6 truth normalization, TASK-12I.10 E2E

### fake-provider 검증 범위

- provider 호출 없이 전체 manual snapshot contract를 검증한다.

### opt-in real-provider 검증 범위

- 없음.

---

## TASK-12I.4 — Owned product URL capture·rights snapshot adapter

### 목표

판매자가 소유·사용 권리를 확인한 상품 URL을 mutable 웹페이지가 아닌 immutable capture identity로 저장한다.

### 요구사항

- 기존 source collector와 URL evidence collector를 재사용한다.
- normalized URL, ownership/usage confirmation, capture time, document/asset ID+hash, parser version과 수집 실패를 기록한다.
- 현재 URL을 downstream에서 다시 읽지 않고 captured artifact만 source로 사용한다.
- 로그인·robots·timeout·partial capture를 source fidelity와 structured status로 구분한다.
- 타사·공급처 URL을 owned URL로 가장하거나 rights-confirmed final asset으로 승격하지 않는다.

### Acceptance Criteria

- 동일 capture fixture는 deterministic source snapshot을 만든다.
- URL 내용이 이후 변경돼도 기존 snapshot/hash는 바뀌지 않는다.
- ownership/rights 미확인 URL은 master final-use source로 진행하지 않는다.
- partial/failed capture는 manual/photo 보완이 가능하되 기존 version을 덮어쓰지 않는다.

### 예상 변경 파일

- `backend/src/services/source_collector.py`
- `backend/src/services/url_evidence_collector.py`
- `backend/src/services/product_intake_service.py`
- `backend/tests/test_lg12i_owned_url_intake.py`

### 관련 테스트

- capture/hash/provenance/rights
- mutable URL response isolation
- partial/failure/fallback successor version

### 다른 Task와의 의존성

- 선행: TASK-12I.1, TASK-12I.2
- 후행: TASK-12I.6, TASK-12I.10

### fake-provider 검증 범위

- 로컬 capture fixture로 network와 provider 호출 없이 검증한다.

### opt-in real-provider 검증 범위

- 명시적 opt-in에서 소유 확인된 단일 URL capture smoke만 허용한다. 기본 gate에는 포함하지 않는다.

---

## TASK-12I.5 — Photo-only OCR/VLM observation adapter

### 목표

권리 확인된 상품 사진만으로 관찰 가능한 정보를 추출하되 관찰과 추론을 분리한다.

### 요구사항

- 기존 asset understanding, image inspection, OCR과 product understanding service를 재사용한다.
- 원본 asset ID/SHA-256, asset role, OCR text/span, VLM observation, confidence, model/parser version과 관찰 불가 영역을 기록한다.
- OCR/VLM 결과는 fact candidate/evidence일 뿐 자동 approved fact가 아니다.
- 효능·인증·구성품·소재·수치를 이미지에서 확인할 수 없으면 unknown/prohibited inference로 남긴다.
- 기존 centralized provider/router를 사용하고 real 호출은 opt-in으로 분리한다.

### Acceptance Criteria

- photo fixture에서 observation과 unsupported inference가 분리된다.
- 실제 asset bytes SHA-256 불일치는 source snapshot 생성을 차단한다.
- 이미지에 없는 claim이 truth candidate로 생성되지 않는다.
- 여러 사진의 중복·충돌 관찰이 asset/evidence identity로 기록된다.

### 예상 변경 파일

- `backend/src/services/asset_understanding_service.py`
- `backend/src/services/image_asset_inspector.py`
- `backend/src/services/product_understanding_service.py`
- `backend/src/services/product_intake_service.py`
- `backend/tests/test_lg12i_photo_only_intake.py`

### 관련 테스트

- OCR/VLM observation provenance
- unknown/prohibited inference
- asset hash/rights/duplicate/conflict

### 다른 Task와의 의존성

- 선행: TASK-12I.1, TASK-12I.2
- 후행: TASK-12I.6, TASK-12I.10

### fake-provider 검증 범위

- deterministic OCR/VLM adapter fixture를 production interface에 주입해 외부 비용 없이 검증한다.

### opt-in real-provider 검증 범위

- 대표 사진 1세트만 명시적 opt-in에서 실행하며 exact wording/hash가 아니라 schema·provenance·금지 추론을 검증한다.

---

## TASK-12I.6 — Product Truth normalization·prohibited inference gate

### 목표

세 mode의 source snapshot을 동일한 Product Truth contract로 정규화하고 unsupported claim을 fail-closed한다.

### 요구사항

- 기존 fact/evidence/conflict helper를 재사용해 fact candidate, evidence edge, unknown, conflict와 prohibited inference를 만든다.
- mode별 source fidelity를 구조화하되 낮은 fidelity를 높은 사실 확신으로 변환하지 않는다.
- 숫자·단위·효능·인증·구성·브랜드 identity는 evidence 연결이 없으면 unknown 또는 review 대상이다.
- deterministic normalization을 우선하고 새 LLM 호출을 추가하지 않는다.
- source/truth canonical hash와 field-level provenance를 유지한다.

### Acceptance Criteria

- 세 mode가 동일 normalized field/identity contract를 만든다.
- evidence 없는 claim, conflicting value와 prohibited inference가 approved truth로 승격되지 않는다.
- source fidelity, unknown/prohibited inference count가 결정론적으로 계산된다.
- unrelated evidence나 creative direction이 truth fact로 섞이지 않는다.

### 예상 변경 파일

- `backend/src/services/fact_evidence_service.py`
- `backend/src/services/product_understanding_service.py`
- `backend/src/services/intake_structuring_service.py`
- `backend/tests/test_lg12i_product_truth.py`

### 관련 테스트

- mode parity normalization
- numeric/nonnumeric unsupported claim
- conflict/unknown/source fidelity/counts
- field provenance/hash

### 다른 Task와의 의존성

- 선행: TASK-12I.3~12I.5 중 대상 mode, TASK-12I.1
- 후행: TASK-12I.7, TASK-12I.8

### fake-provider 검증 범위

- 고정 source snapshot fixture로 모든 truth branch를 검증하며 호출 비용은 0이다.

### opt-in real-provider 검증 범위

- 이미 생성된 opt-in observation을 읽기 전용으로 정규화하며 evaluator가 provider를 재호출하지 않는다.

---

## TASK-12I.7 — Seller confirmation·최대 3개 clarification·rights gate

### 목표

중요 unknown/conflict/rights 항목만 판매자에게 확인하고 응답을 immutable confirmation version으로 고정한다.

### 요구사항

- 질문 우선순위는 downstream 판매 claim, product identity, rights와 필수 channel fact 순으로 결정론적으로 계산한다.
- 한 confirmation cycle에서 질문은 최대 3개이며 각 질문은 fact/evidence/asset identity를 가진다.
- approve/reject/unknown 응답과 actor/time/source truth hash를 저장한다.
- 미확인 필수 fact/rights는 master 생성을 차단하고, 선택 정보는 unknown으로 유지할 수 있다.
- 기존 LangGraph interrupt/resume, schema version, 409 stale response와 history rebuild 계약을 재사용한다.

### Acceptance Criteria

- clarification이 0~3개로 제한되고 동일 truth에서는 같은 우선순위를 가진다.
- 응답 전에는 downstream `ProductCreativeBriefVersion`과 `CommerceCreativeMasterVersion`이 생성되지 않는다.
- reject/unknown/rights 미확정이 approved truth로 승격되지 않는다.
- restart/resume 후 같은 pending 질문과 응답 상태가 복원된다.

### 예상 변경 파일

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_review_service.py`
- `backend/src/services/fact_evidence_service.py`
- `backend/src/services/langgraph_run_service.py`
- `backend/src/api/graph_runs.py`
- `frontend/src/components/planning/GraphReviewPanel.tsx`
- `backend/tests/test_lg12i_seller_confirmation.py`

### 관련 테스트

- clarification priority/max-three
- approve/reject/unknown/rights gate
- stale resume 409와 restart/rebuild
- duplicate resume idempotency

### 다른 Task와의 의존성

- 선행: TASK-12I.6
- 후행: TASK-12I.8~12I.10

### fake-provider 검증 범위

- interrupt/resume 전체를 production graph에서 검증하며 provider/outbox/cost approval은 0회다.

### opt-in real-provider 검증 범위

- 없음. seller confirmation 자체는 provider를 호출하지 않는다.

---

## TASK-12I.8 — Product Creative Brief → Commerce Creative Master 단방향 연결

### 목표

확인된 source/truth/confirmation으로 기존 Product Creative Brief를 먼저 compile한 뒤 그 결과와 후속 production artifact를 가리키는 immutable master reference index를 만든다.

### 요구사항

- 단방향 생성 순서는 `ProductSourceSnapshotVersion → ProductTruthVersion → SellerConfirmationVersion → ProductCreativeBriefVersion → CommerceCreativeMasterVersion`이다.
- Product Creative Brief compiler는 `ProductTruthVersion`, `SellerConfirmationVersion`, `BrandKitVersion`, 기존 review/reference provenance를 직접 입력으로 사용한다. `CommerceCreativeMasterVersion`을 compiler 입력으로 사용하지 않는다.
- 최초 master는 다음 immutable reference identity를 각각 ID/version/hash로 고정한다: `ProductSourceSnapshotVersion`, `ProductTruthVersion`, `SellerConfirmationVersion`, `ProductCreativeBriefVersion`, `BrandKitVersion`, evidence artifact, approved fact snapshot, target channels.
- approved asset manifest는 ID/version/hash로 고정한다. production `copywriting`과 `page_planning` artifact도 각각 stable ID/version/hash reference로 고정하며 내용을 master에 복제하지 않는다. 현재 repository의 실제 artifact contract인 `artifact_key`/`schema_version`/`artifact_hash`를 stable artifact ID/version/hash로 사용하고 존재하지 않는 `CopySetVersion`·`PagePlanVersion` class를 새 계약으로 가정하지 않는다.
- approved asset manifest, `copywriting`, `page_planning` 또는 downstream output reference가 최초 master 이후 생기면 기존 master를 수정하지 않고 successor master version이 이를 인덱싱한다.
- 참조 hash를 실제 canonical artifact와 재검증하고 stale/mismatch/rights 미확정 reference를 차단한다.
- downstream `DetailPageVersion`, 향후 `SocialKitVersion`, `VideoProjectVersion` reference는 기존 master를 수정하지 않고 successor master에서만 추가한다. `DetailPageVersion`은 생성 당시 source master ID/version/hash를 고정하며 생성된 page reference는 별도 successor master에 연결해 순환 참조를 만들지 않는다.
- Social/Video artifact는 구현하지 않고 향후 파생 가능한 reference contract만 둔다.
- master는 source bytes, 원문, OCR, fact/evidence 본문, asset bytes, copy, page plan 내용을 복제하지 않는다.

### Acceptance Criteria

- valid truth/confirmation과 Brand Kit/review provenance에서 deterministic `ProductCreativeBriefVersion`이 먼저 생성되고, 그 결과를 가리키는 하나의 deterministic master index가 생성된다.
- Creative Brief compiler 입력에 master reference가 없고 단방향 dependency chain이 유지된다.
- source/truth/confirmation/brief/Brand Kit/evidence/fact/approved asset manifest/`copywriting`/`page_planning`/target channel reference는 해당 단계에서 ID/version/hash parity를 만족한다.
- approved asset/page reference 추가는 deterministic successor master를 만들며 source master나 page snapshot을 수정하지 않는다.
- 대용량 source bytes/원문/copy가 master에 중복 저장되지 않는다.
- unsupported claim, broken hash/lineage, unconfirmed rights가 있으면 master 생성이 차단된다.
- Creative Brief는 동일 truth/confirmation/fact/Brand Kit identity를 사용하고, master는 해당 Brief를 reference하며 기존 detail-page path는 그 master identity를 사용한다.

### 예상 변경 파일

- `backend/src/services/creative_brief_service.py`
- `backend/src/services/langgraph_commerce_planning_service.py`
- `backend/src/services/langgraph_run_service.py`
- 기존 page finalization/canonical input service
- `backend/tests/test_lg12i_commerce_creative_master.py`

### 관련 테스트

- master reference/hash parity와 payload size contract
- Brief compiler가 truth/confirmation/Brand Kit/review provenance를 직접 사용하고 master를 입력으로 사용하지 않는 단방향 dependency test
- Creative Brief/production `copywriting`·`page_planning`/detail-page source master parity
- invalid rights/lineage/stale reference rejection

### 다른 Task와의 의존성

- 선행: TASK-12I.1, TASK-12I.7, 기존 LG-6~LG-11 artifacts
- 후행: TASK-12I.9, TASK-12I.10, 후속 TASK-12.1R

### fake-provider 검증 범위

- 기존 fake planning/assembly path가 동일 master reference를 소비하는지 검증하며 외부 비용은 0이다.

### opt-in real-provider 검증 범위

- master 생성에는 real provider 호출이 없다. 후속 smoke도 같은 master identity를 읽기만 한다.

---

## TASK-12I.9 — Production graph durability·projection·idempotency

### 목표

intake와 master lifecycle을 checkpoint/history/durable projection에 보존하고 crash·중복 요청에서 정확히 복구한다.

### 요구사항

- production compiled graph에 source→truth→confirmation→Product Creative Brief→master node와 conditional route를 연결한다.
- 정상 projection과 history rebuild가 같은 projection helper를 사용한다.
- checkpoint 저장 후 SQL projection 전 crash에서도 public resume이 최신 state를 복구한다.
- idempotency key에 project/run, input mode, source hash, truth/confirmation/master version identity를 포함한다.
- event metadata에 mode, version IDs, source fidelity, unknown/prohibited inference/clarification count를 남긴다.
- LG-13 dashboard·SLO·alert는 구현하지 않는다.

### Acceptance Criteria

- crash/restart/history rebuild 후 source/truth/confirmation/Brief/master version과 pending confirmation/master lineage가 동일하다.
- 반복 start/resume으로 version, confirmation, master 또는 provider 호출이 중복되지 않는다.
- 이미 projection이 최신이면 rebuild는 no-op이다.
- 기존 LG-4~LG-11 graph의 route/resume behavior가 바뀌지 않는다.

### 예상 변경 파일

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- 기존 graph event/projection helper
- `backend/tests/test_lg12i_checkpoint_rebuild.py`

### 관련 테스트

- checkpoint-before-projection crash/public resume
- duplicate start/resume/idempotency
- projection no-op와 legacy graph regression
- structured event metadata

### 다른 Task와의 의존성

- 선행: TASK-12I.2, TASK-12I.7, TASK-12I.8
- 후행: TASK-12I.10

### fake-provider 검증 범위

- production graph와 durable store를 fake input/provider로 반복 실행하며 외부 비용은 0이다.

### opt-in real-provider 검증 범위

- 기본 durability suite에는 real 호출이 없다.

---

## TASK-12I.10 — 세 입력 모드 production UI·E2E·LG-12I final gate

### 목표

사용자가 세 모드 중 하나를 선택해 source/truth/confirmation/master를 확인하고 기존 상세페이지 흐름까지 이어지는 production 경험을 최종 검증한다.

### 요구사항

- 시작 UI에 owned URL, photo-only, manual mode와 mode별 필수 입력·권리 안내를 제공한다.
- source fidelity, observed/unknown/conflict/prohibited inference, 최대 3개 clarification과 master 근거를 사용자에게 표시한다.
- 세 mode 모두 기존 Creative Brief→planning→LG-9~LG-11 path로 연결한다.
- `lg12i_fake_e2e` marker는 세 golden path, restart/resume, invalid rights/inference와 master lineage를 포함한다.
- real-provider smoke는 명시적 opt-in에서 최소 case만 실행하고 기본 test/build/E2E에서 skip한다.
- Product Intake Golden Dataset v2, LG-12 evaluator, Social/Video/Campaign production은 구현하지 않는다.

### Acceptance Criteria

- 세 mode가 UI와 API에서 같은 production LangGraph contract로 완료된다.
- unsupported inference와 미확인 rights/confirmation이 master·detail flow를 우회하지 못한다.
- source/truth/confirmation/master identity가 UI, checkpoint, AgentRun projection과 DetailPage source reference에서 일치한다.
- frontend production build와 세 mode Playwright 흐름이 통과한다.
- 기본 fake gate에서 provider/outbox/cost approval 호출은 0회이며 real smoke는 명확히 skip된다.

### 예상 변경 파일

- `frontend/src/app/workspace/projects/new/page.tsx`
- `frontend/src/components/planning/GraphReviewPanel.tsx`
- 기존 frontend API client/types
- `backend/tests/test_lg12i_production_flow.py`
- `frontend/e2e/lg12i-unified-product-intake.spec.ts`
- 기존 pytest/Playwright marker 설정

### 관련 테스트

- owned URL/photo-only/manual production flow
- clarification/rights/inference UI와 resume
- Product Creative Brief→Commerce Creative Master→detail source identity parity
- frontend build와 Playwright network payload/state transition

### 다른 Task와의 의존성

- 선행: TASK-12I.1~12I.9
- 후행: TASK-12.1R Product Intake Golden Dataset v2

### fake-provider 검증 범위

- 세 mode 전체를 deterministic fixture로 production graph와 UI에서 반복 검증한다.
- 외부 provider 비용과 네트워크 의존성은 0이다.

### opt-in real-provider 검증 범위

- 별도 환경변수와 credentials가 있을 때 photo-only 대표 1 case의 OCR/VLM schema·provenance smoke만 실행한다.
- default backend tests, frontend build와 Playwright에는 real 호출이 절대 포함되지 않는다.

---

## 권장 구현 순서

```text
TASK-12I.1 Version contracts
  → TASK-12I.2 Unified router
      ├─ TASK-12I.3 Manual adapter
      ├─ TASK-12I.4 Owned URL adapter
      └─ TASK-12I.5 Photo-only adapter
          → TASK-12I.6 Product Truth
              → TASK-12I.7 Seller Confirmation
                  → TASK-12I.8 Product Creative Brief → Commerce Creative Master
                      → TASK-12I.9 Durability
                          → TASK-12I.10 Production E2E
                              → TASK-12.1R Product Intake Golden Dataset v2
                                  → TASK-12.2 QA report/profile
```

TASK-12I.3~12I.5는 TASK-12I.1~12I.2가 확정된 뒤 서로 독립적으로 구현·테스트할 수 있다.

## 범위 밖

- TASK-12.1 Contract Golden Dataset v1의 case·trusted hash 변경
- TASK-12.1R Product Intake Golden Dataset v2 실제 fixture/schema 구현
- TASK-12.2 이후 evaluator, threshold, Quality Bar와 자동 재작업
- LG-13 SLO/dashboard/alert/운영 비용 집계
- LG-14 Detail Page Beta finalization
- LG-15 Social, LG-16 Video, LG-17 Campaign production 기능
- legacy/compatibility execution path와 기존 provider/router 우회
