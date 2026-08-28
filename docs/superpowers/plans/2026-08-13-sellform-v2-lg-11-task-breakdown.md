# LG-11 작업 분해: Hybrid Canvas, 대화형 부분 편집과 버전 복원

## 범위와 공통 원칙

LG-11의 목표는 LG-10에서 확정한 immutable `DetailPageVersion`을 출발점으로, 판매자가 안전한 범위에서 상세페이지 일부를 직접 또는 자연어로 수정하고, 영향 범위·비용·재승인을 확인한 뒤 새 immutable version으로 저장·복원할 수 있게 하는 것이다.

- 대상 원본 요구사항은 `ARC-05`, `EDT-01`~`EDT-07`, `CANVAS-01`~`CANVAS-09`, `BRAND-07`, `OPS-02`이다.
- 모든 변경은 현재 production LangGraph 경로와 LG-10 canonical input → page assembly → canonical renderer → frozen `DetailPageVersion` 계약을 사용한다.
- 기존 `langgraph_runtime`, `langgraph_run_service`, `page_finalization_service`, renderer, export, asset/rights policy, `DetailPageVersion`을 우선 확장한다. legacy graph/page editor/mock execution path에 새 기능을 추가하거나 compatibility layer를 만들지 않는다.
- 직접 편집은 결정론적 code로 처리한다. 자연어 명령 해석이 필요한 경우에만 기존 centralized LLM/provider/router로 구조화된 `EditIntent`를 만들며, LLM이 HTML/CSS나 이미지를 직접 생성하게 하지 않는다.
- 모든 새 page version은 canonical snapshot·입력 refs·asset content hash를 보존한다. preview, PNG, JPG, copyable HTML, standalone HTML/ZIP은 같은 version만 사용한다.
- `LG-12` 이후의 Visual Quality Bar 점수화, Golden Dataset 확대, 운영 SLO/관측, 릴리스 gate는 이 문서의 범위가 아니다. 단, LG-11이 요구하는 기존 channel safety warning/block은 구현 범위에 포함한다.
- 선택적 edge case나 추가 regression 아이디어는 각 Task의 완료를 막는 조건으로 넣지 않는다. Acceptance Criteria는 원본 요구사항의 핵심 계약만 직접 검증한다.

---

## TASK-11.1 — EditIntent 계약과 변경 영향 미리보기

### 목표

page/section/scene/copy/style/fact 수정 요청을 하나의 versioned `EditIntent`로 정규화하고, 실제 변경 전에 대상·영향 artifact·사라지는 승인·예상 비용·필요한 사용자 확인을 결정론적으로 계산한다.

### 요구사항

- `scope`, `target_ids`, `operation`, `instruction`, `preserve_constraints`, `requires_cost_approval`, `affected_artifacts`를 포함한 구조화 계약을 만든다.
- copy, scene, style, fact, page operation의 허용 조합과 target ID가 현재 frozen version에 속하는지 검증한다.
- preview는 실제 asset/job/page version을 변경하지 않고 영향 범위와 확인 필요 여부만 반환한다.
- 모호한 자연어 명령 또는 사실 변경 가능 명령은 실행하지 않고 명시적 확인이 필요한 preview로 표시한다(EDT-07).

### Acceptance Criteria

- 유효한 copy/scene/style/fact/page 요청이 stable target ID와 version ID를 가진 `EditIntent`로 저장 또는 전달된다.
- preview가 변경 대상, stale될 artifact, 유지되는 승인, 예상 provider 비용, 추가 evidence/cost 확인 필요 여부를 반환한다.
- 존재하지 않는 target, 허용되지 않은 operation, 다른 project/version의 target은 실행 전 차단된다.
- preview만 호출했을 때 `DetailPageVersion`, image job, asset, LangGraph durable projection은 변경되지 않는다.

### 예상 변경 파일

- `backend/src/schemas/`의 기존 graph/page schema 파일
- `backend/src/services/page_finalization_service.py` 또는 기존 version/page service
- `backend/src/api/agent_runs.py`, `backend/src/api/pages.py` 중 production edit API 파일
- `frontend/src/lib/`의 기존 API type/helper 및 후속 UI가 사용하는 최소 type 파일

### 관련 테스트

- EditIntent schema/target validation unit test
- copy·scene·style·fact 영향 미리보기 unit test
- preview side-effect 없음 API test
- 모호/사실 변경 명령 confirmation-required test

### 다른 Task와의 의존성

- 선행: LG-10 frozen `DetailPageVersion`과 asset hash contract
- 후속: TASK-11.2, TASK-11.3, TASK-11.4, TASK-11.5, TASK-11.6, TASK-11.10

---

## TASK-11.2 — LG-11 production edit run, checkpoint 및 version lineage

### 목표

LG-10 final version에서 시작하는 LG-11 전용 production LangGraph edit run을 만들고, edit intent·preview confirmation·fork 기준 version을 checkpoint와 `AgentRun.outputs_json`에 durable하게 보존한다.

### 요구사항

- LG-10 compiled graph를 임의로 재배선하지 않고, LG-11 전용 compiled graph와 명시적 edit entrypoint를 사용한다.
- edit run은 base `DetailPageVersion` ID/snapshot hash와 intent ID만 state에 보관하며 mutable current page를 source of truth로 읽지 않는다.
- checkpoint가 SQL projection보다 먼저 저장되어도 history rebuild가 edit run state와 base-version ref를 같은 projection helper로 복원한다.
- 이후 Task가 만드는 새 version은 base version과 edit run을 lineage로 추적할 수 있어야 한다.

### Acceptance Criteria

- production API에서 LG-10 final version을 선택해 LG-11 edit run을 시작하면 LG-11 graph state가 base version ref와 edit preview를 보존한다.
- checkpoint/restart/history rebuild 뒤 intent, confirmation state, base version ref가 `AgentRun.outputs_json`과 동일하게 복원된다.
- LG-5~LG-10 compiled graph에는 LG-11 edit route나 존재하지 않는 conditional target이 추가되지 않는다.
- 다른 project의 version 또는 final이 아닌 version으로 edit run을 시작할 수 없다.

### 예상 변경 파일

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- `backend/src/api/agent_runs.py`
- `backend/src/db/models.py` 및 필요한 migration
- 기존 graph state/schema 파일

### 관련 테스트

- LG-11 production compiled graph start/resume integration test
- checkpoint → projection-loss → history rebuild test
- base-version/project ownership guard test
- LG-5~LG-10 graph routing regression test

### 다른 Task와의 의존성

- 선행: TASK-11.1
- 후속: TASK-11.3, TASK-11.4, TASK-11.5, TASK-11.6, TASK-11.9, TASK-11.10

---

## TASK-11.3 — 직접 section 카피 편집과 zero-provider version fork

### 목표

선택한 section의 한국어 title/body/spec text를 이미지와 분리된 text layer에서 수정하고, 이미지 provider 호출 없이 새 LG-11 frozen version을 만든다.

### 요구사항

- `EDT-01`, `ASM-06`을 사용한다. copy edit는 해당 text layer와 필요한 renderer/assembly snapshot만 갱신한다.
- 승인 asset manifest, 다른 section asset, LG-9 image job은 유지한다.
- 수정된 text에는 기존 사실 ID/provenance를 유지하거나, 사실 근거가 없는 narrative임을 명시한다.
- direct editor와 후속 natural-language copy edit가 같은 edit intent/version-fork API를 사용하도록 한다.

### Acceptance Criteria

- section copy 수정은 새 immutable `DetailPageVersion`을 만들고 base version의 asset manifest·다른 section·source refs를 변경하지 않는다.
- copy-only edit 중 image outbox, provider dispatch, cost approval은 0건이다.
- 새 version의 preview/PNG/JPG/copyable HTML/standalone export는 변경된 Korean text와 동일 asset identities를 사용한다.
- target section 또는 사실 provenance가 유효하지 않으면 version을 만들지 않는다.

### 예상 변경 파일

- `backend/src/services/page_finalization_service.py`
- `backend/src/services/renderer.py`
- `backend/src/api/pages.py` 또는 LG-11 edit API 파일
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- `frontend/src/components/DetailPageDocument.tsx`

### 관련 테스트

- copy-only edit가 image/provider 호출을 만들지 않는 integration test
- immutable version fork와 asset manifest preservation test
- edited-version preview/export parity test
- section/fact provenance guard test

### 다른 Task와의 의존성

- 선행: TASK-11.1, TASK-11.2
- 후속: TASK-11.7, TASK-11.10

---

## TASK-11.4 — 장면 단위 재생성·asset 교체와 비용 승인

### 목표

한 scene의 regenerate 또는 권리 보유 asset 교체를 LG-9의 existing outbox/cost approval/review 정책으로 연결하고, 다른 승인 장면과 output을 보존한 새 page version을 만든다.

### 요구사항

- `EDT-02`, `IMG-06`, `IMG-07`, `ARC-05`를 사용한다.
- scene edit preview는 해당 scene만 invalidation하고 실제 예상 비용·재승인 범위를 보여준다.
- provider 재생성은 LG-9 existing cost approval과 durable outbox를 반드시 거친다. fake/mock provider recovery는 깨지지 않아야 한다.
- seller-owned asset replacement는 기존 rights/content-hash policy를 재사용하고 provider 호출 없이 처리한다.

### Acceptance Criteria

- 한 scene regenerate는 해당 scene의 새 job만 만들며 다른 approved scene의 job/output/approval을 변경하지 않는다.
- 재생성 provider 호출은 cost approval 전에는 dispatch되지 않으며, real-provider uncertainty retry 정책을 우회하지 않는다.
- seller-owned replacement는 권리 확인·SHA-256 검증 후 해당 scene만 교체하고 새 version을 만든다.
- 새 scene asset이 승인되기 전에는 canonical final version/export로 승격되지 않는다.

### 예상 변경 파일

- `backend/src/services/langgraph_image_generation_service.py`
- `backend/src/services/image_generation_worker.py`
- `backend/src/services/page_finalization_service.py`
- `backend/src/agents/langgraph_runtime.py`
- `backend/src/api/agent_runs.py` 및 기존 image review API 파일
- 관련 frontend scene review/edit component

### 관련 테스트

- fake provider scene-only regenerate → cost approval → image review integration test
- 다른 scene output/approval 유지 test
- seller-owned replacement rights/hash test
- real provider retry/cost bypass regression test

### 다른 Task와의 의존성

- 선행: TASK-11.1, TASK-11.2
- 후속: TASK-11.10

---

## TASK-11.5 — 사실 변경의 evidence review 재진입과 selective stale 처리

### 목표

사실 변경을 일반 카피 수정과 구분해 evidence review부터 재확인하고, 그 사실에 실제로 의존하는 downstream copy/scene/assembly만 stale 처리한다.

### 요구사항

- `EDT-03`, `OPS-02`, `FACT-01`~`FACT-03`을 사용한다.
- confirmed fact의 값·근거·상태 변경은 direct renderer mutation으로 처리하지 않는다.
- 기존 fact dependency와 `mark_fact_dependents_stale` 계열 구조를 재사용한다.
- evidence review 승인 전 stale copy/scene/page는 final version/export로 승격하지 않는다.

### Acceptance Criteria

- 사실 변경 intent는 evidence review interrupt로 진입하고, approval 전 새 final version을 만들지 않는다.
- evidence review 승인 뒤 해당 fact를 참조하는 copy/scene/assembly만 stale 또는 재생성 대상으로 표시되며 무관한 artifact는 유지된다.
- 변경 영향, 사라지는 승인, 예상 scene/provider 비용이 실행 전에 보인다.
- restart/history rebuild 뒤 pending evidence review와 stale 영향 범위가 복원된다.

### 예상 변경 파일

- `backend/src/api/facts.py`
- `backend/src/services/fact_evidence_service.py`
- `backend/src/services/creative_brief_service.py`
- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- 관련 fact/edit UI component

### 관련 테스트

- fact edit → evidence review → selective invalidation production graph test
- approval 전 export/final-version guard test
- unaffected artifact preservation test
- checkpoint/rebuild pending-review test

### 다른 Task와의 의존성

- 선행: TASK-11.1, TASK-11.2
- 후속: TASK-11.10

---

## TASK-11.6 — 전체 style·Brand Kit 변경의 selective reassembly

### 목표

전체 디자인 방향 또는 Brand Kit 변경 시 승인 사실은 유지하면서 영향을 받는 Creative Brief·Visual Plan·Assembly·renderer만 갱신하고 새 version을 만든다.

### 요구사항

- `EDT-04`, `BRAND-07`, `ARC-05`를 사용한다.
- 새 style/Brand Kit은 기존 3개 LG-10 design direction과 rights-confirmed logo/watermark token 범위에서만 선택한다.
- style-only 변경은 이미지 재생성을 기본값으로 하지 않는다. 실제 image regenerate가 필요한 경우에만 TASK-11.4의 별도 비용 승인 경로를 사용한다.
- Brand Kit version과 실제 적용된 asset identity/hash는 새 frozen snapshot에 고정한다.

### Acceptance Criteria

- 전체 style 변경은 승인 fact IDs를 변경하지 않고, 영향받는 brief/visual/assembly/render refs만 새 version으로 갱신한다.
- Brand Kit 변경은 실제 영향을 받는 artifact만 stale 처리하며, 무관한 image job과 approved asset manifest를 삭제하지 않는다.
- blocked/reference-only/supplier/rights-unknown Brand asset은 새 renderer/export에 포함되지 않는다.
- 변경 preview는 layout/Brand 영향과 추가 provider 비용 여부를 명시한다.

### 예상 변경 파일

- `backend/src/services/creative_brief_service.py`
- `backend/src/services/brand_kit_service.py`
- `backend/src/services/page_finalization_service.py`
- `backend/src/services/renderer.py`
- `backend/src/agents/langgraph_runtime.py`
- 관련 design direction/Brand Kit edit UI component

### 관련 테스트

- style-only edit의 fact/asset manifest preservation test
- Brand Kit selective stale propagation test
- rights gate와 safe fallback test
- new-version preview/export Brand identity parity test

### 다른 Task와의 의존성

- 선행: TASK-11.1, TASK-11.2
- 후속: TASK-11.7, TASK-11.10

---

## TASK-11.7 — Hybrid Canvas canonical snapshot과 section 구조 편집

### 목표

absolute-position full-page editor를 만들지 않고, LG-10 canonical page의 section 순서·높이·표시 상태를 편집 가능한 Canvas draft로 저장하고 deterministic renderer에 반영한다.

### 요구사항

- `CANVAS-01`, `CANVAS-05`, `CANVAS-09`를 사용한다.
- Canvas draft는 base frozen version·section IDs·허용된 section layout bounds만 참조한다.
- reorder, height, visibility 변경은 section-level operation으로 정규화하며 final specification ordering 같은 기존 page safety rule을 유지한다.
- autosave draft, undo/redo는 같은 edit-run/version lineage를 사용하며 current mutable page state를 source로 사용하지 않는다.

### Acceptance Criteria

- section reorder/height/visibility edit가 canonical Canvas snapshot에 저장되고 새 frozen version의 renderer에 동일한 순서와 표시 상태로 반영된다.
- refresh/restart 뒤 draft와 undo/redo cursor가 복원되며, undo/redo가 다른 edit run 또는 base version을 건드리지 않는다.
- 숨김/재정렬로 필수 사양 section ordering safety rule을 위반하면 save/export 전 차단된다.
- preview/PNG/JPG/HTML/ZIP은 같은 Canvas-derived `DetailPageVersion`을 사용한다.

### 예상 변경 파일

- `backend/src/db/models.py` 및 필요한 migration
- `backend/src/services/page_finalization_service.py`
- `backend/src/services/renderer.py`
- `backend/src/api/pages.py` 또는 LG-11 edit API 파일
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- `frontend/src/components/DetailPageDocument.tsx`

### 관련 테스트

- section structural Canvas operation unit/integration test
- draft autosave/undo/redo/restart restore test
- section ordering safety guard test
- Canvas snapshot → preview/export parity test

### 다른 Task와의 의존성

- 선행: TASK-11.2
- 후속: TASK-11.8, TASK-11.9, TASK-11.10

---

## TASK-11.8 — Canvas 내부 요소 편집과 layer 제어

### 목표

각 section 안에서 허용된 text/image/background/mask/icon/decorative element를 직접 이동·크기 조절·교체하고, layer order·lock·group·duplicate·delete를 canonical Canvas snapshot으로 보존한다.

### 요구사항

- `CANVAS-02`, `CANVAS-03`을 사용한다.
- element는 stable ID와 허용된 component/layout token에 연결한다. 임의 script, external URL, unrestricted CSS 또는 raw HTML은 허용하지 않는다.
- 이미지 교체는 기존 approved asset 또는 seller-owned rights-confirmed asset만 선택할 수 있다. 생성 재요청은 TASK-11.4로 넘긴다.
- locked element는 direct Canvas와 자연어 edit 모두에서 변경할 수 없다.

### Acceptance Criteria

- text/image/background/mask/icon/decorative element edit가 target element ID를 가진 Canvas operation으로 저장되고 renderer에 반영된다.
- layer reorder, lock, group, duplicate, delete가 section 경계를 넘지 않고 deterministic한 ordering을 유지한다.
- unapproved/reference-only/supplier/blocked asset, raw HTML, external image URL은 element replacement 입력으로 차단된다.
- Canvas operation을 재적용해도 duplicate element/version이 생성되지 않는다.

### 예상 변경 파일

- `backend/src/services/page_visual_contract.py` 또는 기존 renderer contract 파일
- `backend/src/services/page_finalization_service.py`
- `backend/src/api/pages.py`
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- 기존 detail-page editor/component 파일

### 관련 테스트

- element operation validation/deterministic layer ordering test
- lock/group/duplicate/delete unit test
- approved asset replacement rights/hash guard test
- relevant Canvas direct-manipulation Playwright test

### 다른 Task와의 의존성

- 선행: TASK-11.7
- 후속: TASK-11.9, TASK-11.10

---

## TASK-11.9 — Canvas 안전 영역·채널 preview와 export 차단

### 목표

Canvas 변경에 정렬 guide·gap/snap·safe area·잘림/겹침 검사를 적용하고, 모바일·쿠팡·스마트스토어·HTML preview와 export가 같은 canonical version에서 channel safety를 보장하게 한다.

### 요구사항

- `CANVAS-04`, `CANVAS-07`, `CANVAS-08`, `CANVAS-09`를 사용한다.
- guide/snap은 UI 보조 기능이고, save/export safety 판정은 backend의 deterministic canonical snapshot validation이 source of truth다.
- channel unsafe operation은 preview에서 경고하고 export 전에는 명시적으로 차단한다.
- LG-12의 점수형 layout QA나 Golden Dataset은 도입하지 않는다.

### Acceptance Criteria

- Canvas preview가 selected channel의 safe area 및 clipping/overlap warning을 보여준다.
- unsafe Canvas snapshot은 final export API가 409 등 명시적 오류로 차단하고, 이전 final version/export는 그대로 재다운로드 가능하다.
- safe snapshot은 mobile/channel/HTML preview와 PNG/JPG/HTML/ZIP에서 같은 section/element version을 사용한다.
- client-side guide를 우회한 API 요청도 backend validation에서 차단된다.

### 예상 변경 파일

- `backend/src/services/page_visual_contract.py`
- `backend/src/services/renderer.py`
- `backend/src/services/export_service.py`
- `backend/src/api/exports.py`, `backend/src/api/pages.py`
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- preview/detail-page component 및 relevant e2e fixture

### 관련 테스트

- channel safe-area/clipping/overlap validation test
- unsafe snapshot export-block test
- preview/PNG/JPG/HTML/ZIP Canvas parity integration test
- mobile/channel preview Playwright test

### 다른 Task와의 의존성

- 선행: TASK-11.7, TASK-11.8
- 후속: TASK-11.10

---

## TASK-11.10 — 선택 요소 기반 대화형 편집, version 복원 및 LG-11 quality gate

### 목표

Canvas에서 선택한 element/section/version을 자연어 edit context에 고정하고, intent preview·명시적 confirmation·직접 editor를 하나의 version history로 연결하며, 과거 version 복원과 모든 출력 parity를 최종 검증한다.

### 요구사항

- `EDT-05`~`EDT-07`, `CANVAS-05`, `CANVAS-06`, `CANVAS-09`를 사용한다.
- 자연어는 기존 centralized provider/router로 `EditIntent`만 만들며, selected target ID와 base version ID가 없는 broad edit는 실행하지 않는다.
- 모호 명령, 사실 변경, provider 비용 발생 edit는 preview/confirmation 뒤에만 실행한다.
- restore는 과거 frozen `DetailPageVersion`을 새 mutable page로 덮어쓰는 legacy route를 사용하지 않고, LG-11 lineage에서 선택한 snapshot을 새 current final version으로 승격한다.
- fake provider E2E는 copy-only, scene-only, fact review, style/Brand, Canvas save, restore/export parity를 production LG-11 graph로 검증한다. real-provider smoke는 opt-in marker/environment gate가 없는 한 실행하지 않는다.

### Acceptance Criteria

- 선택 section/element를 대상으로 한 자연어 copy/style/scene 요청은 정확한 target/version context의 EditIntent preview를 만들고, confirmation 전 state를 변경하지 않는다.
- 모호 명령과 fact-changing 명령은 사용자 확인 또는 evidence review로 이동하며 임의로 실행되지 않는다.
- Canvas direct edit와 대화형 edit는 동일 version lineage/history에 저장되고 refresh 후 다시 표시된다.
- 과거 LG-11 version을 복원한 뒤 preview, PNG, JPG, copyable HTML, standalone HTML/ZIP, export history redownload가 동일 restored snapshot을 사용한다.
- fake provider quality gate는 외부 비용 없이 반복 실행되고, opt-in real-provider smoke는 기본 test/e2e 실행에서 skip된다.

### 예상 변경 파일

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- `backend/src/services/page_finalization_service.py`
- `backend/src/api/agent_runs.py`, `backend/src/api/pages.py`, `backend/src/api/exports.py`
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- 기존 planning/review panel 및 detail-page preview component
- `backend/tests/test_lg11_*.py`, `frontend/e2e/lg11-*.spec.ts`, existing Playwright config/fixture

### 관련 테스트

- selected-context natural-language edit/confirmation integration test
- ambiguous/fact/cost confirmation guard test
- version restore and history-redownload parity test
- LG-11 fake production LangGraph E2E and Canvas Playwright E2E
- opt-in real-provider smoke collection/skip test

### 다른 Task와의 의존성

- 선행: TASK-11.1, TASK-11.2, TASK-11.3, TASK-11.4, TASK-11.5, TASK-11.6, TASK-11.7, TASK-11.8, TASK-11.9
- 후속: 없음 (LG-11 최종 quality gate)
