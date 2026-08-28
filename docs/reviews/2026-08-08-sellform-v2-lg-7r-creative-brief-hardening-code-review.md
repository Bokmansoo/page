# Sellform V2.1 LG-7R Creative Brief Hardening 코드리뷰

## 1. 판정

LG-7R 범위는 **완료**다. 문서의 기존 판정을 재사용하지 않고 DB 모델과 migration, API, Creative Brief compiler, 실제 LangGraph interrupt/checkpoint/resume, Planning UI, 실제 백엔드 기반 Playwright를 역추적했다.

- 미구현: 0건
- 부분 구현: 0건
- 테스트 우회: 0건
- LG-7R 대상 실패 테스트: 0건
- 실제 유료 LLM·이미지 provider 호출: 0건

## 2. 요구사항별 역검증

| 요구사항 | 실제 구현 증거 | 테스트 증거 | 판정 |
|---|---|---|---|
| R1 fake real-LLM 구조화 출력 | `backend/src/agents/schemas.py`의 `CreativeBriefStructuredOutput`, `backend/src/services/creative_brief_llm_service.py`의 `generate_structured_creative_brief`, `backend/src/services/provider_adapters.py`의 `creative_brief` schema 등록 | `test_fake_real_llm_accepts_valid_schema_without_repair`, `test_fake_real_llm_repairs_one_schema_error_once`, `test_fake_real_llm_stops_after_repair_budget_and_never_loops` | 충족 |
| R2 기존 수집 리뷰 자료 선택 | `ReviewInputVersion.source_asset_id`, `20260808_lg7r_creative_brief_hardening.sql`, `allowed_review_assets`, `review_text_from_asset`, `POST /review-inputs`, Planning의 `기존 수집 리뷰 자료` 선택기 | `test_review_content_hash_deduplicates_paste_file_and_collected_asset`, 실제 Playwright의 sourced TXT 업로드·선택·연결 | 충족 |
| R3 Planning 추적 정보 | `project_intelligence`가 generation/interaction mode, Prompt Pack, Brand Kit, Creative Brief, fact/candidate, direction, review/reference usage, section contract, auto approval, stale impact를 반환하고 `CreativeBriefInputPanel`이 모두 표시 | `test_planning_trace_exposes_versions_facts_modes_and_stale_impact`, 실제 Playwright의 reload 후 trace 표시 | 충족 |
| R4 리뷰 파일 견고성·중복 | `parse_review_bytes`의 빈 파일, 확장자, 인코딩, CSV/XLSX 손상 검사와 `create_review_input`의 project+content hash 멱등 재사용 | `test_review_file_validation_has_stable_korean_error_contract`, paste/file/asset 중복 테스트, 실제 브라우저 손상 XLSX 업로드 | 충족 |
| R5 실제 interrupt/resume | 운영 graph/checkpointer 경로와 `/api/v1/graph-runs/{run_id}/resume`가 `Command(resume=...)`를 사용 | `test_fake_llm_creative_brief_flows_through_real_interrupt_and_command_resume`에서 `input_review → evidence_review → planning_review → generation_pending` 검증 | 충족 |
| R6 fake LLM 전체 E2E | fake-real provider가 실제 Creative Brief compiler와 commerce planning node에 연결되고 checkpoint에 결과가 저장됨 | 위 graph E2E에서 provider 요청 수 1, brief hash, page planning, 동일 checkpoint 복구 확인 | 충족 |
| R7 실제 API·DB·LangGraph Playwright | `frontend/e2e/lg7r-real-backend-state.spec.ts`; 대상 API에 `page.route`를 사용하지 않음 | 개발 로그인, run/asset 생성, 실제 graph start, UI interrupt 승인, DB 결과 조회, 새로고침 복구 통과 | 충족 |
| R8 구조화 한국어 오류 | `responseMessage`가 `detail.code/message/remedy`를 안전하게 조합하고 객체를 직접 문자열화하지 않음 | 실제 손상 XLSX를 API에 제출하여 코드·한국어 원인·해결 방법 및 `[object Object]` 부재 확인 | 충족 |

## 3. DB 및 migration 검증

- migration: `backend/migrations/20260808_lg7r_creative_brief_hardening.sql`
- 추가 컬럼: `review_input_versions.source_asset_id`
- 추가 인덱스: `ix_review_input_versions_source_asset_id`
- PostgreSQL migration은 `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`를 사용한다.
- SQLite/runtime 호환 경로도 컬럼과 인덱스를 각각 독립 검사한다.
- `test_lg7r_runtime_migration_is_reentrant_and_repairs_missing_index`가 같은 migration 경로를 두 번 실행하고 컬럼·인덱스를 확인했다.
- 실제 Playwright가 현재 실행 DB에 sourced review asset을 저장하고 다시 읽었으므로 실행 환경 schema 연결도 확인됐다.

## 4. 주요 보완 사항

1. Creative Brief용 Pydantic 구조화 schema와 최대 1회 repair executor를 추가했다.
2. LLM schema 오류는 `CREATIVE_BRIEF_SCHEMA_REPAIR_EXHAUSTED`로 제한된 횟수 뒤 종료한다.
3. 기존 프로젝트 수집 자료를 리뷰로 연결할 때 프로젝트 소속·usage 상태·텍스트 존재 여부를 검증한다.
4. supplier/reference 수집 경로에서만 TXT/CSV/XLSX 업로드를 허용하고, 상품 입력 업로드는 기존 이미지 제한을 유지한다.
5. 리뷰의 동일 정규화 content hash는 새 버전과 새 insight를 만들지 않고 기존 row를 반환한다.
6. Planning에서 적용 산출물의 ID/version/hash와 provenance/stale 범위를 확인할 수 있게 했다.
7. API 오류 객체를 한국어 코드·원인·해결 방법으로 렌더링한다.
8. 기존 LG-7 Playwright의 query string 누락 route 패턴도 수정해 해당 회귀 테스트가 다시 통과하도록 했다.

## 5. 실행한 검증과 결과

### 백엔드 LG-7R + LG-6 회귀

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest -q tests\test_lg7_creative_brief_input_modes.py tests\test_lg6_prompt_intelligence_brand_kit.py --disable-warnings --maxfail=10
```

결과: **31 passed**

### LG-5R 핵심 회귀

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest -q tests\test_lg5_image_generation_subgraph.py --disable-warnings --maxfail=10
```

결과: **12 passed**

### 실제 백엔드·DB·LangGraph Playwright

```powershell
cd C:\page\frontend
$env:SELLFORM_E2E_EXTERNAL_SERVER='1'
$env:SELLFORM_E2E_REAL_BACKEND='1'
.\node_modules\.bin\playwright.cmd test "lg7r-real-backend-state.spec.ts" --project=chromium --workers=1
```

결과: **1 passed**. 실제 손상 XLSX 오류, sourced TXT 연결, `input_review → evidence_review`, 새로고침 복구, DB trace를 검증했다.

### LG-7 UI 회귀와 정적 검사

```powershell
cd C:\page\frontend
$env:SELLFORM_E2E_EXTERNAL_SERVER='1'
$env:SELLFORM_E2E_PORT='3000'
.\node_modules\.bin\playwright.cmd test "lg7-creative-brief-input-modes.spec.ts" --project=chromium --workers=1
.\node_modules\.bin\eslint.cmd src\components\planning\CreativeBriefInputPanel.tsx e2e\lg7r-real-backend-state.spec.ts e2e\lg7-creative-brief-input-modes.spec.ts
```

결과: Playwright **1 passed**, ESLint **0 errors**.

## 6. 비대상 기준선 확인

전체 `tsc --noEmit`에는 LG-7R 이전부터 존재하던 다음 비대상 오류가 남아 있다.

- `e2e/lg5-image-generation-review.spec.ts`
- `e2e/upload-ready-golden-path.spec.ts`
- `e2e/ux2c-uploaded-photo-composition.spec.ts`
- `src/app/account/page.tsx`
- `src/app/workspace/operations/page.tsx`

LG-7R 대상 파일에는 TypeScript 오류가 없고 대상 ESLint와 두 Playwright가 통과했다. 사용자 지시대로 이 작업과 무관한 기준선 파일은 수정하지 않았다.

## 7. 최종 역검증 결론

테스트가 provider를 동기 완료 함수로 바꾸지 않았고, 실제 graph의 interrupt와 resume API를 통과한다. 브라우저 테스트도 대상 API를 `page.route`로 대체하지 않는다. fake-real LLM 외의 유료 provider는 호출하지 않았다. 따라서 LG-7R의 8개 보완 항목은 모두 실제 실행 경로에서 충족되며 LG-8 착수 전 게이트를 통과한다.
