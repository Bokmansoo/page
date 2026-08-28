# 2026-08-09 정정 공지

이 문서의 기존 `Playwright 1 passed`, `미구현 0건`, `완료` 판정은 반복 실행에서 재현된 `validate_generated_images -> image_review` 정체 결함을 반영하지 못했으므로 철회한다. 단발성 성공을 안정성 완료 근거로 사용한 것이 잘못이었다.

실패 재현, DB 원인 증거, 수정 코드, 반복 Playwright 결과와 최신 완료 판정은 `docs/reviews/2026-08-09-sellform-v2-lg-8r-provider-resume-stability-code-review.md`를 기준으로 한다.

---

# Sellform V2.1 LG-8 Visual Prompt Compiler 코드리뷰

작성일: 2026-08-08  
판정: **완료 — 미구현 0건, 부분 구현 0건, 테스트 우회 0건**

## 1. 검토 방식

기존 완료 문구를 근거로 사용하지 않았다. 최종 기획, 전체 로드맵, LG-8 세부 계획을 다시 읽고 DB schema, migration, API, 서비스, LangGraph node/edge, 이미지 worker 입력, Planning UI 및 실제 백엔드 Playwright 경로를 역방향으로 대조했다. 실제 유료 LLM·이미지 provider는 호출하지 않았고 이미지 생성은 fake provider를 사용했다.

## 2. 요구사항별 구현 및 테스트 증거

| 요구사항 | 판정 | 실제 구현 근거 | 테스트 증거 |
| --- | --- | --- | --- |
| ARC-04 생성과 타이포 분리 | 충족 | `visual_prompt_compiler_service.py:31-42, 342-371`의 `no_rasterized_copy`와 provider adapter, renderer 소유 정책 | `test_lg8_compiles_every_required_scene_template_and_keeps_copy_out_of_provider_prompt` |
| PRM-10 장면 유형별 prompt | 충족 | `visual_prompt_compiler_service.py:59-96`의 HERO·사용·기능·소재·구성품·크기/사양·사용법·구매 장면 profile과 production role alias | 같은 compiler contract 테스트 및 실제 8장면 E2E |
| PRM-11 정체성 고정 | 충족 | `visual_prompt_compiler_service.py:222-231, 277-299`에서 형태·색상·소재·버튼·포트·구성품과 기준 asset을 모든 관련 prompt에 주입 | compiler contract, reference 변경 및 fake worker E2E |
| PRM-12 이미지 내 카피 금지 | 충족 | `visual_prompt_compiler_service.py:31-42, 102-145, 342-371`에서 한국어 본문·사양표·가격·CTA·로고·워터마크·QR을 차단 | raster copy/API validation 테스트 |
| PRM-13 provider 중립 canonical prompt | 충족 | `visual_prompt_compiler_service.py:256-333`은 canonical JSON/hash를 저장하고 `provider_prompt()`에서만 provider 문자열로 변환 | provider 설정을 바꿔도 canonical hash가 유지되는 테스트 |
| IMG-08 오류 구분 | 충족 | `image_generation_worker.py:28-63`의 API key, 잔액·한도, timeout, safety, identity, OCR, rights 오류 정규화 | LG-5R 회귀 테스트와 LG-8 실제 fake worker 회귀 |
| IMG-09 직접 업로드 asset picker | 충족 | `StoryboardImageGenerationPanel.tsx`의 권리 보유 사진 선택 UI와 `storyboard_image_generation_service.py:1000-1090`의 서버 검증 | LG-5R 직접 업로드/권리 회귀 테스트 |
| IMG-10 미승인·공급처 이미지 조립 차단 | 충족 | `storyboard_image_generation_service.py:372-449, 1000-1090`의 supplier/reference-only 및 승인 상태 차단 | LG-5R final-output/rights 회귀 테스트 |
| BRAND-05 동일 Brand Kit version 전달 | 충족 | `visual_prompt_compiler_service.py:256-383`가 Creative Brief의 정확한 Brand Kit ID/hash를 검증해 고정하고, `langgraph_runtime.py:460-502`와 `langgraph_image_generation_service.py:186-333`가 prompt compile·비용 계획·job 준비에 같은 고정값을 전달한다. `scene_prompt_versions.brand_kit_version_id/brand_kit_visual_hash`와 image job prompt FK가 실제 사용 버전을 보존한다. | `test_lg8_pins_the_creative_brief_brand_version_across_later_activation`, 실제 graph 테스트에서 generation pending 뒤 v2를 활성화해도 v1 prompt/job 계약을 유지하는 검증 |
| BRAND-07 영향 범위만 stale | 충족 | `visual_prompt_compiler_service.py:171-173, 235-253, 304-326`; 비시각 tone은 visual hash에서 제외하고 색상 등 시각 필드만 장면 prompt/job/outbox를 stale 처리 | tone 유지·palette 변경 테스트 및 장면 단독 수정 테스트 |

## 3. 계층별 검토 결과

### DB와 migration

- `scene_prompt_versions`는 workspace/project/run/scene, reference hash, identity lock, rights snapshot, visual direction, text/negative policy, provider plan, Brand Kit version/hash, immutable prompt/input hash, supersedes와 stale 범위를 저장한다.
- `image_generation_jobs.scene_prompt_version_id`가 worker가 실제 사용한 prompt version을 고정한다.
- `backend/migrations/20260808_lg8_visual_prompt_compiler.sql`과 runtime compatibility 경로를 연속 두 번 실행해 재실행 안전성과 FK/index 존재를 검증했다.

### 백엔드와 API

- `GET /api/v1/projects/{project_id}/scene-prompts`는 현재 및 선택적으로 stale 이력을 반환한다.
- `POST /api/v1/projects/{project_id}/scene-prompts/compile`은 프로젝트 장면 전체를 deterministic하게 컴파일한다.
- `PATCH /api/v1/projects/{project_id}/scene-prompts/{scene_id}`는 시각 지시만 허용하고 새 불변 version을 만든다. 글자·로고·가격·검증되지 않은 claim 요청은 한국어 오류 코드와 해결 방법을 포함한 422로 차단한다.
- 동일 입력은 기존 active version을 재사용하고 변경 입력만 새 version을 만든다.

### LangGraph와 worker

- `visual_planning -> visual_prompt_compiler -> planning_review -> generation_pending` 순서가 실제 graph에 연결돼 있다.
- Creative Brief가 선택한 Brand Kit ID/hash를 graph prompt compiler와 비용·job 준비가 함께 사용한다. 실행 도중 더 최신 Brand Kit가 활성화되어도 같은 run/thread는 기존 고정 버전을 유지하고, ID/hash가 불일치하면 구조화 오류로 중단한다.
- generation pending 이후 비용 승인 전 provider dispatch는 0건이다.
- fake worker가 `scene_prompt_version_id`가 연결된 job을 lease·완료하고 같은 run/thread/checkpoint를 `Command(resume=...)` 경로로 `image_review`까지 재개한다.
- 실제 검증 run `b2444be6-a332-4822-ab5d-948fa225878e`는 `image_review` interrupt에 도달했고, 8개 job 모두 output asset과 prompt version FK를 가졌다. outbox 8건은 각각 dispatch 1회, completion resume 1회였고 중복 비용은 없었다.

### 프런트엔드

- Planning 화면에서 장면별 prompt version/hash, reference hash/asset, identity lock, 권리 snapshot, Brand Kit version/hash, text/negative policy, 모델·크기·비용을 접어보기로 확인할 수 있다.
- 판매자 시각 지시를 수정하면 해당 장면만 새 version이 되고 이전 version은 stale로 보인다.
- 새로고침 뒤에도 prompt version, 비용 승인, provider wait, image review가 실제 DB 상태에서 복구된다.

## 4. 실행한 검증

### 백엔드 단위·통합·그래프·회귀

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_lg8_visual_prompt_compiler.py tests/test_lg7_creative_brief_input_modes.py tests/test_lg6_prompt_intelligence_brand_kit.py tests/test_lg5_image_generation_subgraph.py
```

결과: **50 passed**, 실패 0. LG-8 전용 테스트는 **7 passed**다. 표시된 deprecation warning은 기존 Starlette/Pydantic/Pillow/Google SDK 사용 경고이며 LG-8 상태 전이나 결과를 우회하지 않는다.

### 실제 백엔드·DB·LangGraph Playwright

```powershell
cd C:\page\frontend
$env:SELLFORM_E2E_REAL_BACKEND='1'
$env:SELLFORM_E2E_EXTERNAL_SERVER='1'
$env:SELLFORM_E2E_REAL_APP_URL='http://localhost:3000'
$env:SELLFORM_E2E_REAL_API_URL='http://localhost:8001'
npm.cmd run test:e2e -- e2e/lg8-real-backend-state.spec.ts
```

결과: **1 passed (46.6s)**. `page.route` 전면 mocking 없이 실제 업로드, DB, graph interrupt/resume, prompt edit/stale, 새로고침, 비용 승인, durable outbox/worker, image review 상태를 검증했다.

### 프런트 정적·빌드 가드

```powershell
npm.cmd run lint -- --file src/components/planning/ScenePromptReviewPanel.tsx --file src/components/planning/StoryboardImageGenerationPanel.tsx --file src/components/planning/PlanningDraftEditor.tsx --file e2e/lg8-real-backend-state.spec.ts --file playwright.config.ts
npm.cmd run test:build-guard
```

결과: ESLint 실패 0(기존 raw image 최적화 권고 warning 4건), build guard **3 passed**.

## 5. 최종 역검증

- 모든 생성 장면에 prompt version/hash와 reference hash가 있음: 충족
- HERO·사용·기능·소재·구성품·크기·사용법·구매 장면 구분: 충족
- 정체성 고정 요소가 관련 prompt에 포함됨: 충족
- 이미지 provider에 최종 한국어 카피·사양표를 요청하지 않음: 충족
- 한 장면 prompt 수정이 다른 장면 job을 무효화하지 않음: 충족
- Brand Kit의 비시각 tone 변경은 visual job을 stale 처리하지 않음: 충족
- Creative Brief 이후 더 최신 Brand Kit 활성화 시 같은 실행이 새 버전으로 drift하지 않음: 충족
- 실제 checkpoint/interrupt/resume과 worker 완료 재개 경로: 충족
- 유료 provider 호출: 0건

최종 누락 수는 **미구현 0건, 부분 구현 0건, 테스트 우회 0건**이다. LG-8 범위는 완료됐지만, 실제 이미지 품질 검사·후보 비교·승인 manifest 고도화는 로드맵대로 LG-9 범위이며 LG-8 완료를 경쟁 서비스 수준 전체 제품 완료로 해석하지 않는다.
