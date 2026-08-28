# Sellform V2.1 LG-8 Visual Prompt Compiler 구현 계획

작성일: 2026-08-08  
상태: 구현 기준선

## 1. 목표

LG-8은 승인된 스토리보드의 각 생성 장면을 공급자 중립적인 `ScenePromptVersion`으로 컴파일한다. 장면별 프롬프트, 제품 정체성, 권리 상태, Brand Kit, 참조 사진, 텍스트 정책과 예상 비용을 불변 버전으로 고정하고, 실제 이미지 공급자 문법은 dispatch 직전 adapter에서만 변환한다.

## 2. 요구사항 매핑

| 요구사항 | 구현 항목 | 필수 테스트 |
|---|---|---|
| ARC-04 | AI 생성 이미지와 정확한 한국어 문구/표 렌더링 분리, 기본 `no_rasterized_copy` | canonical prompt에 최종 문구·표 생성 지시가 없고 adapter에도 정책이 유지됨 |
| PRM-10 | HERO, use, function, material, components, size, how-to, final CTA/purchase 장면별 compiler template | 모든 장면 유형 contract test |
| PRM-11 | shape/color/buttons/ports/components/logo identity lock을 관련 장면마다 저장 | 모든 생성 장면 identity constraint 검증 |
| PRM-12 | `text_policy=no_rasterized_copy`, OCR/중국어/QR/가격/워터마크 negative policy | text policy 및 negative constraint test |
| PRM-13 | canonical JSON과 provider adapter 분리 | canonical hash가 provider 표현 변경에 영향받지 않는 test |
| IMG-08 | API key, balance/limit, timeout, safety, identity mismatch, OCR contamination, rights block 오류 코드 유지 | 오류 분류 contract/regression test |
| IMG-09 | 직접 업로드는 화면 asset picker만 사용 | API와 UI에서 raw asset ID 직접 입력 경로 미노출 test |
| IMG-10 | 권리 미확인/공급자 전용 이미지는 최종 조립 금지 | reference validation 및 assembly eligibility test |
| BRAND-05 | Brief/Copy/Visual Prompt/Assembly가 동일 Brand Kit version/hash 추적 | prompt record와 graph state의 Brand Kit ID/hash 일치 test |
| BRAND-07 | Brand Kit 변경 시 영향받는 visual prompt/job만 stale | 시각 필드 변경과 비시각 필드 변경 선택적 stale test |

## 3. DB와 버전 계약

`scene_prompt_versions`를 추가한다. 각 레코드는 다음을 저장한다.

- 소유권: workspace_id, project_id, run_id, scene_id, section_id
- 장면: scene_type, objective, approved_fact_ids
- 참조: reference_asset_ids, reference_hash, rights_snapshot
- 정체성: identity_constraints
- 미술 지시: composition, camera, lighting, background, palette, material
- 안전: negative_constraints, text_policy
- 실행 예고: provider, model, size, quality, expected_cost
- 추적: brand_kit_version_id/hash, prompt_version, prompt_hash, canonical_json
- 수명: status(active/stale), stale_reason, stale_impact, supersedes_id, created_at

`image_generation_jobs.scene_prompt_version_id`가 실제 사용한 버전을 참조한다. prompt hash는 provider-neutral canonical JSON만으로 계산한다.

## 4. 컴파일 및 그래프 연결

1. `visual_planning` 다음에 내부 서비스 노드 `visual_prompt_compiler`를 둔다.
2. 승인 fact, Creative Brief, 적용 Prompt Pack, 적용 Brand Kit, 각 카드와 참조 사진을 읽는다.
3. 장면별 canonical JSON과 hash를 만들고 동일 입력은 재사용한다.
4. graph state에는 prompt version ID/hash 요약만 기록한다.
5. `planning_review`와 비용 승인 이후 job 준비 시 저장된 active prompt version을 다시 검증한다.
6. provider adapter는 job 생성 시 provider/model 전용 문자열로 변환하며 canonical record는 변경하지 않는다.

## 5. 선택적 stale 규칙

- 장면의 목적·참조 사진·승인 fact·seller adjustment 변경: 그 장면 prompt와 미승인 job만 stale.
- Brand Kit의 color/image_style/layout/background/watermark/logo 변경: 해당 Brand Kit를 사용한 visual prompt와 미승인 job stale.
- tone/CTA 등 이미지에 영향을 주지 않는 필드만 변경: visual prompt/job은 유지.
- 이미 승인된 출력은 보존하되 새 버전에서 재사용 여부를 명시적으로 다시 선택한다.
- 다른 장면 prompt/job과 worker outbox는 변경하지 않는다.

## 6. API·UI

- `GET /api/v1/projects/{project_id}/scene-prompts`: 현재/과거 장면별 prompt version 조회
- `PATCH /api/v1/projects/{project_id}/scene-prompts/{scene_id}`: seller adjustment를 새 버전으로 저장하고 그 장면만 stale
- Planning에 장면별 prompt 요약, version/hash, reference hash/사진, identity lock, text policy, Brand Kit ID/version/hash, model/size/cost를 표시
- 공급자 prompt 원문보다 사람이 읽는 요약을 우선 표시하고 추적 상세를 펼칠 수 있게 한다.

## 7. 테스트 계획

1. migration 적용과 재실행 안전성
2. 모든 장면 유형 compiler contract
3. identity/rights/text policy/provider-neutral hash
4. 같은 입력 멱등성, 한 장면 수정의 선택적 stale, planning/reference/Brand Kit 변경 감지
5. 비용 승인 후에도 prompt/reference가 변하면 dispatch 0건 및 stale cost plan
6. 실제 DB + fake provider + LangGraph interrupt/checkpoint/Command(resume) E2E
7. worker 재시작/중복 poll/webhook 회귀
8. 프런트 타입/렌더링/API 오류 및 새로고침 복구
9. Playwright에서 실제 백엔드·DB·LangGraph 상태 전이 검증
10. LG-5R, LG-6, LG-7R 핵심 회귀

## 8. 자체 누락 검토

- 유료 provider 호출은 테스트 범위에서 금지한다.
- 범용 prompt 문자열만 바꾸는 구현은 불충분하다. DB 버전과 job FK가 필수다.
- planning 전체 hash를 scene prompt version에 사용하지 않는다.
- UI 표시만 추가하고 worker가 저장 버전을 사용하지 않는 우회를 허용하지 않는다.
- graph node unit test만으로 완료하지 않고 interrupt/resume 이후 같은 version ID가 job과 worker까지 전달되는지 검증한다.
- 직접 업로드와 최종 조립의 권리 검증을 기존 LG-5R 경로에서 회귀 검증한다.

