# LG-10 작업 분해: 조립·렌더링·HTML/ZIP 산출

## 범위와 공통 원칙

LG-10의 목표는 LG-9에서 승인된 이미지와 확정된 한국어 카피·표·그래픽을 하나의 수정 가능한 canonical detail page로 조립하고, 동일한 페이지 버전에서 미리보기·이미지·복사 가능한 HTML·독립 실행 ZIP을 산출하는 것이다.

- 모든 작업은 현재 production LangGraph 경로를 대상으로 한다.
- LG-9의 `approved_asset_manifest`와 승인된 seller-owned asset을 입력 계약으로 재사용한다. 미승인·실패·supplier 원본 asset을 export 입력으로 다시 허용하지 않는다.
- 기존 page finalization, renderer, export, asset policy, version/history 구조를 우선 확장한다. legacy page-assembly/mock execution path와 compatibility layer는 변경하거나 새로 만들지 않는다.
- LLM은 구조화된 component/layout token 선택에만 사용할 수 있으며, HTML을 직접 생성하거나 이미지 안에 한국어 문구를 그리는 용도로 사용하지 않는다.
- LG-11의 자유형 캔버스 편집, 자연어 수정, 상세 버전 복원 UI는 이 문서의 범위가 아니다.

---

## TASK-10.1 — Canonical page assembly 입력 계약과 immutable snapshot 기반

### 목표

LG-9 승인 결과, 확정 카피/스펙, Brand Kit, 레이아웃 토큰을 하나의 deterministic한 canonical page assembly 입력으로 정규화하고, 이후 renderer/export가 참조할 immutable page snapshot의 최소 계약을 확정한다.

### 요구사항

- ASM-01의 section/copy version/asset version/layout token/channel override 참조를 canonical page에 보존한다.
- LG-9 `approved_asset_manifest`의 scene·section·asset ID·SHA-256 hash만 asset 입력으로 사용한다.
- API 이미지가 하나도 없어도 원본 사진 또는 정보성 HTML/CSS section으로 안전한 조립 입력을 만들 수 있어야 한다(ASM-05).
- 동일한 입력은 동일한 참조와 정렬 순서를 갖고, unapproved/partial-failure 입력은 canonical final snapshot으로 승격되지 않아야 한다.

### Acceptance Criteria

- canonical 입력에 section ID, copy/version 참조, approved asset identity, layout token, Brand Kit/channel override 참조가 명시적으로 저장된다.
- approved asset entry는 non-null lowercase SHA-256 64자리 hash를 유지하며, 이 계약을 만족하지 않는 entry는 final assembly 입력에서 제외 또는 차단된다.
- 승인된 생성 이미지가 없는 경우에도 이미지 없는 정보 section 또는 권리 보유 원본 사진 fallback만 포함한 안전한 입력을 생성한다.
- snapshot은 재시작/재투영 후 동일한 값으로 복원될 수 있는 durable projection 계약을 가진다.

### 예상 변경 파일

- `backend/src/services/page_finalization_service.py`
- `backend/src/services/page_visual_contract.py`
- `backend/src/services/page_asset_policy.py`
- `backend/src/db/models.py` 및 필요한 migration
- `backend/src/services/langgraph_image_generation_service.py`
- 관련 schema/API projection 파일

### 관련 테스트

- 승인 manifest에서 canonical assembly 입력을 만드는 unit/integration test
- 이미지 0개·seller-owned asset·partial failure 입력 경계 test
- content hash와 stable ordering test
- snapshot durable projection/restart restore test

### 다른 Task와의 의존성

- 선행: LG-9 approved asset manifest contract
- 후속: TASK-10.2, TASK-10.3, TASK-10.4, TASK-10.5, TASK-10.6

---

## TASK-10.2 — Production LangGraph Page Assembly 단계

### 목표

LG-9 image review 완료 후 production LangGraph가 canonical assembly 입력을 받아, 허용된 component와 layout token만 선택하는 LG-10 Page Assembly 상태 전이를 수행하게 한다.

### 요구사항

- ASM-03에 따라 model 출력은 component 선택과 token 선택으로 제한한다.
- 기존 centralized provider/router 및 production LangGraph runtime을 사용한다.
- LG-9의 image review/approved manifest 이후에만 실행하며, legacy `page_assembly` mock node를 새 기능 경로로 사용하지 않는다.
- 구조화 결과와 canonical 입력 참조를 LangGraph state 및 `AgentRun.outputs_json` durable projection에 저장한다.

### Acceptance Criteria

- production compiled graph에서 LG-10 Page Assembly node가 실제로 실행되고, 이전 LG-9 state의 approved manifest를 소비한다.
- state delta에는 허용 component ID·layout token·선택 근거와 immutable 입력 참조만 있으며 임의 HTML은 없다.
- checkpoint/restart/history rebuild 후 assembly state와 projection이 동일하게 복원된다.
- 미승인 필수 scene 또는 불완전한 manifest가 있으면 Page Assembly로 진행하지 않는다.

### 예상 변경 파일

- `backend/src/agents/langgraph_runtime.py`
- `backend/src/services/langgraph_run_service.py`
- 기존 production commerce-planning/page-finalization service 및 state schema 파일
- `backend/src/api/agent_runs.py` 또는 현재 run projection API 파일

### 관련 테스트

- production compiled graph가 LG-9 image review 완료 뒤 LG-10 state로 전이하는 integration test
- 구조화 assembly output validation test(임의 HTML 거부 포함)
- checkpoint/history rebuild projection test
- incomplete approval guard test

### 다른 Task와의 의존성

- 선행: TASK-10.1
- 후속: TASK-10.3, TASK-10.4, TASK-10.5, TASK-10.7

---

## TASK-10.3 — Deterministic canonical renderer와 한국어 text layer

### 목표

선택된 component/token과 canonical 입력을 기존 renderer 계약으로 조립해, 한국어 제목·본문·스펙 표·주의사항을 이미지와 분리된 HTML/CSS text layer로 렌더링한다.

### 요구사항

- ARC-04, ASM-04, ASM-06을 구현한다.
- 생성 이미지에는 한국어 문구·표·아이콘을 의존하지 않고, HTML/CSS renderer가 정확한 원문을 책임진다.
- 이미지 없는 정보 section, 표, 주의사항, 핵심 사양을 안정적으로 렌더링한다.
- renderer는 TASK-10.1 snapshot과 TASK-10.2 구조화 assembly 결과만 소비한다.

### Acceptance Criteria

- canonical page section은 asset layer와 editable Korean text layer를 구분해 보존한다.
- 카피/표/주의사항의 원문이 renderer 출력 HTML에 그대로 존재하며 이미지 asset에 텍스트를 합성하지 않는다.
- asset이 없는 정보 section은 broken image 없이 HTML/CSS만으로 정상 렌더링된다.
- 동일 snapshot과 renderer token으로 재실행한 출력은 section 순서·카피·asset 참조가 동일하다.

### 예상 변경 파일

- `backend/src/services/renderer.py`
- `backend/src/services/commerce_renderer_service.py`
- `backend/src/services/page_finalization_service.py`
- `backend/src/services/page_visual_contract.py`
- renderer template/static asset 파일(기존 구조 안에서 필요한 경우)

### 관련 테스트

- Korean copy/spec table/caution text layer unit test
- image-free information section rendering test
- approved asset + text layer separation test
- deterministic section ordering/render snapshot test

### 다른 Task와의 의존성

- 선행: TASK-10.1, TASK-10.2
- 후속: TASK-10.5, TASK-10.6, TASK-10.7

---

## TASK-10.4 — 3개 검증 디자인 방향과 Brand Kit renderer token 적용

### 목표

LG-10에서 허용된 세 가지 디자인 방향을 fixed renderer/token 조합으로 제공하고, 동일 Brand Kit version의 색상·폰트·로고·워터마크 정책을 조립 및 렌더링에 일관되게 적용한다.

### 요구사항

- ASM-07의 `safe_information`, `image_centric`, `balanced_sale` 세 방향만 지원한다.
- BRAND-05에 따라 upstream Creative Brief/Copy/Visual Prompt와 같은 Brand Kit version을 사용한다.
- 권리·라이선스가 확인된 logo/watermark asset만 renderer token에 연결한다.
- 임의 자유형 레이아웃, 무제한 스타일, LG-11 canvas editing은 추가하지 않는다.

### Acceptance Criteria

- 세 방향 각각이 허용된 component/layout token 조합으로 렌더링되고, renderer가 임의 layout 값을 수용하지 않는다.
- snapshot에 Brand Kit version과 적용된 brand token/asset identity가 남는다.
- Brand Kit가 없거나 사용할 수 없는 brand asset은 안전한 기본 token으로 fallback하며, 권리 미확인 asset을 포함하지 않는다.
- 동일 Brand Kit version은 page assembly·renderer·export에서 일관되게 사용된다.

### 예상 변경 파일

- `backend/src/services/commerce_renderer_service.py`
- `backend/src/services/page_visual_contract.py`
- `backend/src/services/page_asset_policy.py`
- `backend/src/services/page_finalization_service.py`
- Brand Kit schema/조회에 쓰이는 기존 service 또는 model 파일

### 관련 테스트

- 세 direction golden render/snapshot test
- 허용되지 않은 token/layout 거부 test
- Brand Kit version propagation test
- logo/watermark 권리 gate 및 safe fallback test

### 다른 Task와의 의존성

- 선행: TASK-10.1, TASK-10.2
- 후속: TASK-10.5, TASK-10.6, TASK-10.7

---

## TASK-10.5 — DetailPageVersion 저장, preview 및 이미지 export parity

### 목표

canonical page snapshot을 `DetailPageVersion` 중심의 immutable output으로 저장하고, 웹 미리보기와 PNG/JPG rendering이 같은 version의 section·카피·asset manifest를 사용하도록 연결한다.

### 요구사항

- ASM-01, ASM-02, QA-04를 만족한다.
- preview/download/image rendering이 같은 DetailPageVersion을 참조한다.
- immutable snapshot에는 canonical section, copy/version ref, asset identity, layout token, Brand Kit/direction ref를 보존한다.
- 재시작/resume/history projection에서도 선택된 page version을 다시 찾을 수 있어야 한다.

### Acceptance Criteria

- 완료된 assembly는 하나의 immutable `DetailPageVersion`으로 저장되고 API/UI가 해당 version ID를 노출한다.
- preview, PNG/JPG output의 section order, Korean copy, approved asset manifest가 version snapshot과 일치한다.
- 이전 DetailPageVersion을 재렌더링해도 현재 프로젝트의 새 카피/asset으로 섞이지 않는다.
- checkpoint/restart/history rebuild 후 해당 version과 immutable refs가 유지된다.

### 예상 변경 파일

- `backend/src/db/models.py` 및 필요한 migration
- `backend/src/services/page_finalization_service.py`
- `backend/src/services/renderer.py`
- `backend/src/services/export_service.py`
- `backend/src/api/pages.py`, `backend/src/api/exports.py`
- `frontend/src/components/GeneratedDetailPageResult.tsx` 또는 현재 preview component

### 관련 테스트

- DetailPageVersion immutable persistence test
- preview/PNG/JPG section-copy-asset parity integration test
- version isolation and rerender test
- restart/history restore test
- relevant frontend component/Playwright preview test

### 다른 Task와의 의존성

- 선행: TASK-10.1, TASK-10.2, TASK-10.3, TASK-10.4
- 후속: TASK-10.6, TASK-10.7

---

## TASK-10.6 — Sanitized copyable HTML, standalone ZIP 및 export history

### 목표

저장된 DetailPageVersion에서 clean HTML과 standalone ZIP을 만들고, 재다운로드 가능한 export history를 같은 version/asset manifest에 고정한다.

### 요구사항

- HTML-01~HTML-08을 구현한다.
- HTML은 Cafe24/self-hosted 환경에 붙여넣을 수 있는 clean markup이고, ZIP은 HTML/CSS/승인 이미지/font manifest/guide를 포함한다.
- ZIP asset은 approved manifest에서 번들링하며 signed URL이나 외부 API 재호출에 의존하지 않는다.
- script, event handler, 위험 URL, unsupported tag/style을 sanitize하고 channel unsupported component는 warn/안전한 static fallback 처리한다.
- `index.html`은 로컬 압축 해제 후 동작하고, export history는 동일 DetailPageVersion의 HTML/image package를 다시 내려받게 한다.

### Acceptance Criteria

- 복사 HTML과 ZIP이 동일 DetailPageVersion ID 및 asset manifest를 기록하고, 미승인/supplier asset이나 expiring signed URL을 포함하지 않는다.
- ZIP을 임시 로컬 경로에 압축 해제했을 때 `index.html`이 API 호출이나 재다운로드 없이 bundled CSS/images를 참조한다.
- sanitizer는 script/event handler/risky URL/unsupported markup을 차단 또는 제거한다.
- unsupported channel component는 명시적 warning과 정해진 static fallback을 사용한다.
- export history에서 과거 version의 HTML/ZIP/image output을 재다운로드해도 새 version과 섞이지 않는다.

### 예상 변경 파일

- `backend/src/services/export_service.py`
- `backend/src/services/renderer.py`
- `backend/src/services/page_asset_policy.py`
- `backend/src/api/exports.py`, `backend/src/api/pages.py`
- export/version model 및 필요한 migration
- `frontend/src/components/GeneratedDetailPageResult.tsx` 또는 현재 export UI component

### 관련 테스트

- HTML sanitizer unit test
- ZIP contents/relative asset paths/no-signed-URL test
- local `index.html` fixture/browser test
- unsupported component fallback test
- export history/version isolation API test
- relevant Playwright copy/download flow test

### 다른 Task와의 의존성

- 선행: TASK-10.3, TASK-10.4, TASK-10.5
- 후속: TASK-10.7

---

## TASK-10.7 — LG-10 production golden matrix 및 end-to-end quality gate

### 목표

LG-9 승인 결과부터 LG-10 assembly, preview, image export, HTML/ZIP까지의 production LangGraph 흐름을 fake-provider 기반으로 반복 검증하고, 세 디자인 방향과 주요 시각 회귀를 고정한다.

### 요구사항

- fake provider/fixture만 사용해 외부 provider 비용 없이 반복 가능하게 만든다.
- LG-9 approved manifest를 실제 입력으로 사용하며 legacy/mock execution path를 우회 경로로 사용하지 않는다.
- 세 design direction, Korean text/table wrapping, mobile width, image-free fallback, preview/export manifest parity를 golden matrix에 포함한다.
- real provider smoke가 필요하다면 기본 suite와 분리된 explicit opt-in smoke로만 둔다. LG-10 구현/검증 중 자동 real provider 호출은 하지 않는다.

### Acceptance Criteria

- production LangGraph E2E가 LG-9 final approved state에서 LG-10 DetailPageVersion과 preview/PNG/JPG/HTML/ZIP을 생성한다.
- 세 direction에 대해 preview와 모든 export의 section/copy/asset manifest parity가 직접 검증된다.
- Korean copy, table/wrap, mobile-width, image-free info section에 대한 visual/regression assertion이 있다.
- 기본 backend/E2E 실행은 외부 provider를 호출하지 않으며, opt-in real smoke는 기본 수집 또는 실행에서 제외된다.

### 예상 변경 파일

- `backend/tests/test_lg10_*.py` 또는 기존 LG-8/LG-9 production integration test 파일
- `frontend/e2e/lg10-*.spec.ts`
- 기존 Playwright fixture/config 및 renderer golden fixture(필요한 범위만)

### 관련 테스트

- LG-10 fake production LangGraph integration suite
- renderer/export golden and parity suite
- Playwright assembly → preview → copy/download E2E
- responsive visual regression test
- opt-in real-provider smoke selection/skip test(실제 호출은 CI/명시 실행에서만)

### 다른 Task와의 의존성

- 선행: TASK-10.2, TASK-10.3, TASK-10.4, TASK-10.5, TASK-10.6
- 후속: 없음(LG-10 quality gate)
