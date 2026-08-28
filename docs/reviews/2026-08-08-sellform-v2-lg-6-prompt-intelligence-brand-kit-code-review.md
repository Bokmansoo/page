# Sellform V2.1 LG-6 Prompt Intelligence + Brand Kit 코드리뷰

- 검토일: 2026-08-08
- 대상 계획: `docs/superpowers/plans/2026-08-08-sellform-v2-lg-6-prompt-intelligence-brand-kit.md`
- 대상 요구사항: PRM-01~05, BRAND-01~04, BRAND-06, BRAND-08, QA-02, OPS-01, OPS-07, OPS-08
- 최종 판정: **LG-6 범위 충족**
- 미구현: 0건
- 부분 구현: 0건
- 테스트 우회: 0건
- 유료 이미지/LLM provider 호출: 0건

## 1. 검토 방법

기존 문서의 판정을 재사용하지 않고 DB 모델과 마이그레이션, 서비스, API, 프로젝트 생성 경로, LangGraph 노드와 checkpoint 상태, 운영 UI, 단위·통합·그래프·브라우저 테스트를 다시 대조했다. 특히 상태가 보인다는 이유만으로 충족 처리하지 않고, 불변 버전·활성 버전 유일성·프로젝트 snapshot 고정·workspace 격리·실제 그래프 노드 순서를 확인했다.

## 2. 요구사항별 역추적

| 요구사항 | 구현 증거 | 테스트 증거 | 판정 |
|---|---|---|---|
| PRM-01 | `prompt_intelligence_service.create_proposal`, `transition_pack_version`이 `draft_generated → validation_pending → approved → active`만 허용한다. 제안 메타데이터에 provider/model/prompt version과 `paid_provider_dispatched=false`를 기록한다. | `test_proposal_requires_separate_validation_approval_and_activation` | 충족 |
| PRM-02 | `resolve_active_pack`은 승인 후 활성화된 버전만 선택하며 카테고리 미존재 시 `other` 활성 팩으로 안전하게 fallback한다. | Golden/fallback 및 compiler 테스트 | 충족 |
| PRM-03 | `classify_category`는 프로젝트 실행 입력만 분류하고 전역 Prompt Pack을 만들거나 수정하지 않는다. confidence, rationale, fallback, classifier version을 반환한다. | `test_classifier_golden_dataset_and_safe_other_fallback` | 충족 |
| PRM-04 | 생활용품·뷰티·식품·패션·전자제품·other 6개 카테고리와 Coupang·Naver SmartStore 2개 채널 기본 팩을 제공한다. | `test_seeded_category_and_channel_packs_are_active_and_versioned` | 충족 |
| PRM-05 | `PromptPackVersion`이 content hash, version, lifecycle actor/time을 보존한다. 활성 버전 교체 시 이전 버전을 deprecated로 전환하며 부분 unique index로 동시 active를 막는다. | lifecycle 및 active 교체 테스트 | 충족 |
| BRAND-01 | workspace 범위 활성 Brand Kit는 `ix_brand_kit_one_workspace_active` 부분 unique index와 activation transaction으로 1개만 허용한다. | `test_brand_kit_version_asset_rights_workspace_snapshot_and_project_override` | 충족 |
| BRAND-02 | 프로젝트 생성 직후 `snapshot_project_brand_kit`으로 현재 workspace 활성 버전을 고정하고, 이후 기본 Kit 변경에도 기존 프로젝트 snapshot은 유지한다. | 동일 Brand Kit 통합 테스트 | 충족 |
| BRAND-03 | 프로젝트 override는 별도 immutable BrandKitVersion으로 생성하고 `brand_kit_override_version_id`로 연결한다. workspace 기본 버전은 수정하지 않는다. | 동일 Brand Kit 통합 테스트 | 충족 |
| BRAND-04 | 로고, 폰트, 색상, typography, tone, 금칙어, CTA, image/layout/background 규칙, watermark 정책을 구조화해 hash에 포함한다. | watermark 및 content hash assertion | 충족 |
| BRAND-06 | Brand Kit 자산은 `seller_owned`/`rights_confirmed`만 선택 가능하며 reference-only와 타 workspace 자산은 서비스와 API 양쪽 경계에서 차단한다. UI는 raw ID 대신 권리 확인 자산 picker를 사용한다. | reference-only 및 cross-workspace 차단 테스트, Playwright picker 테스트 | 충족 |
| BRAND-08 | Kit가 없는 프로젝트는 `brand: null` 안전 fallback으로 compile되며 생성 자체가 실패하지 않는다. | compiler 테스트 | 충족 |
| QA-02 | 고정 Golden Dataset, dataset/classifier version, input/output hash, confusion matrix, 정확도·fallback 비율을 저장한다. 현재 기준 정확도는 100%이며 요구 기준 95% 이상이다. | `test_classifier_golden_dataset_and_safe_other_fallback` | 충족 |
| OPS-01 | 모든 Prompt Pack/Brand Kit 생성·평가·상태 변경에 actor, entity, hash가 포함된 AuditLog를 남긴다. | lifecycle audit assertion 및 API 통합 테스트 | 충족 |
| OPS-07 | workspace 조건을 모든 조회·변경에 적용하고 타 workspace version/asset 접근을 거부한다. | `test_operator_api_and_cross_workspace_boundaries`, Brand asset 경계 테스트 | 충족 |
| OPS-08 | checkpoint에는 허용 필드와 compact prompt snapshot만 넣고 API key, authorization, signed URL, raw customer payload를 제외한다. | `test_checkpoint_allowlist_excludes_secrets_raw_payloads_and_signed_urls` | 충족 |

## 3. 구조 확인

### 데이터베이스

- 모델: `backend/src/db/models.py`의 `PromptPack`, `PromptPackVersion`, `CategoryEvaluationReport`, `BrandKit`, `BrandKitVersion`, `CompiledPromptArtifact`
- 마이그레이션: `backend/migrations/20260808_lg6_prompt_intelligence_brand_kit.sql`
- SQLite 개발 DB 호환 보강: `backend/src/db/database.py`
- 프로젝트 고정 참조: `ProductProject.brand_kit_version_id`, `brand_kit_override_version_id`

### 백엔드와 API

- Prompt Intelligence: `backend/src/services/prompt_intelligence_service.py`, `backend/src/api/prompt_intelligence.py`
- Brand Kit: `backend/src/services/brand_kit_service.py`, `backend/src/api/brand_kits.py`
- 신규 프로젝트 snapshot 연결: `backend/src/api/projects.py`, `backend/src/api/agent_runs.py`
- 라우터 등록: `backend/src/app.py`

### LangGraph

- `backend/src/agents/langgraph_runtime.py`에 `category_classifier`와 `prompt_pack_resolver` 노드를 추가했다.
- 실제 순서는 `evidence_review → category_classifier → prompt_pack_resolver → sales_strategy`이다.
- resolver는 category/channel/brand version ID와 hash, compiled artifact ID/hash만 checkpoint-safe state에 남긴다.
- `CompiledPromptArtifact`는 run별로 한 번 생성되며 같은 run 재개 시 동일 artifact를 재사용한다. 후속 활성 팩 변경이 진행 중 run의 결과를 바꾸지 않는다.

### 운영 UI

- `frontend/src/app/workspace/settings/intelligence/page.tsx`
- 기본 팩 준비, Golden 평가, 분류 미리보기, 임의 카테고리·채널 draft 제안, 검증·승인·활성화·폐기 흐름을 제공한다.
- Brand Kit의 구조화 필드와 로고/폰트 권리 확인 자산 picker, 버전 활성화, 프로젝트 override를 제공한다.

## 4. 자체 역검증에서 발견해 수정한 항목

1. 기획 문서의 PRM/BRAND ID 설명을 최종 설계 문서와 다시 맞췄다.
2. 운영 UI에 분류 결과의 category/confidence/rationale/fallback 표시를 추가했다.
3. 기본값만 만드는 화면이 되지 않도록 임의 category/channel draft 생성 UI를 추가했다.
4. Brand 자산을 일반 raw ID가 아닌 로고·폰트 picker로 분리했다.
5. Brand 구조화 필드와 `watermark_policy` 저장 경로를 추가했다.
6. Prompt Pack과 workspace Brand Kit의 활성 버전 유일성을 DB 부분 unique index로 강제했다.
7. 활성 버전 교체 시 unique index와 충돌하지 않도록 이전 버전 retirement를 먼저 flush하도록 수정했다.
8. LG-6 production graph 도입으로 깨진 LG-2/LG-3 테스트 주입 경계를 복구하되 production 실행은 LG-6 graph를 계속 사용하도록 했다.
9. 기존 DB의 `quality_warnings=null` 자산 때문에 설정 화면의 프로젝트 picker가 함께 실패하는 호환성 문제를 발견해 API 응답에서 빈 목록으로 안전하게 정규화했다.

## 5. 실행한 검증

| 검증 | 결과 |
|---|---|
| LG-6 백엔드 테스트 | 9 passed |
| LG-0~LG-6 + Agent Run API/graph contract 회귀 | 57 passed, 0 failed |
| LG-6 프런트 ESLint | 통과 |
| LG-6 Playwright fake API E2E | Chromium 1 passed |
| 프런트 production build | LG-6 포함 compile 성공 후 기존 비-LG-6 오류로 전체 종료 실패 |

Playwright는 실제 유료 provider 대신 API route fake로 요청·상태 전이·새로고침 복구를 검증했다. 버튼 존재만 확인하는 테스트가 아니다.

전체 Next.js build의 남은 실패는 이번 범위와 무관한 기존 파일 두 곳이다.

- `frontend/src/app/account/page.tsx`: `HeadersInit` 타입 오류
- `frontend/src/app/workspace/operations/page.tsx`: 존재하지 않는 `mockHeaders` import

두 파일은 사용자 소유의 기존 변경이므로 LG-6 작업에서 임의 수정하지 않았다. LG-6 페이지 자체 ESLint와 Next compile은 통과했다.

## 6. 완료 판정

LG-6 대상 요구사항은 코드, DB 제약, API, LangGraph production 경로, 운영 UI와 테스트에 연결됐다. 유료 provider 호출 없이 분류·Prompt Pack·Brand Kit·run snapshot 경로를 검증했으며, LG-6 범위에서 미구현·부분 구현·테스트 우회는 발견되지 않았다.
