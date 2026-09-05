# Sellform V2.1 LG-6 Prompt Intelligence + Brand Kit 구현 계획

작성일: 2026-08-08  
상태: 구현 기준선 확정  
대상: `PRM-01~05`, `BRAND-01~04`, `BRAND-06`, `BRAND-08`, `QA-02`, `OPS-01`, `OPS-07`, `OPS-08`

## 1. 선행 구현 실사

- LG-5R의 durable image worker, outbox/lease, checkpoint/resume, 장면별 검수 흐름은 현재 코드에 존재한다.
- 현재 활성 LangGraph는 `evidence_review -> sales_strategy`로 바로 연결되며 LG-6의 `category_classifier`, `prompt_pack_resolver` 노드는 없다.
- Category/Channel Prompt Pack, 불변 버전, Golden Dataset 평가, compiled prompt artifact 모델과 API는 없다.
- 기존 `Brand`는 단일 mutable 레코드이며 Brand Kit 불변 버전, 워크스페이스 활성 버전, 프로젝트 override snapshot은 없다.
- 운영자 Prompt Pack UI와 사용자 Brand Kit UI가 없다.

따라서 LG-6은 기존 LG-5R 그래프의 이미지 생성 영역을 변경하지 않고, evidence review와 commerce planning 사이에 prompt intelligence subgraph를 추가한다.

## 2. 구현 원칙

1. 모든 런은 분류 결과, category/channel pack ID·version·hash, Brand Kit version/hash, compiled artifact ID/hash를 처음 해석할 때 고정한다.
2. resume은 고정된 snapshot만 사용하며 이후 active pack/kit 변경을 따라가지 않는다.
3. 버전 본문은 생성 후 수정하지 않는다. 변경은 새 버전 생성으로만 수행한다.
4. LLM 제안은 `draft_generated`까지만 만들 수 있다. 검증·승인·활성화는 서로 다른 명시 API와 actor audit를 요구한다.
5. 프롬프트 우선순위는 `system safety > approved facts/legal > identity > channel > category > seller direction > brief > scene > provider`로 고정한다.
6. checkpoint와 로그에는 ID/hash/판정 요약만 넣고 원문 고객 입력, 서명 URL, 비밀키, 전체 prompt body는 넣지 않는다.
7. 미등록 category는 안전하게 `other`로 fallback한다.

## 3. 데이터 모델 및 마이그레이션

### Prompt intelligence

- `prompt_packs`: workspace, kind(category/channel), key, locale의 논리 팩.
- `prompt_pack_versions`: 불변 version body, lifecycle status, content hash, 평가 결과, 생성/검증/승인/활성 actor와 시각.
- `category_evaluation_reports`: Golden Dataset 버전·입력/출력 hash·정확도·fallback 비율·confusion matrix.
- `compiled_prompt_artifacts`: run/project, 선택된 category/channel/brand version과 hash, compiler input/output hash, 안전한 compile manifest.

### Brand Kit

- `brand_kits`: workspace별 kit identity.
- `brand_kit_versions`: workspace 기본 또는 project override 범위의 불변 버전. 로고/컬러/서체/톤/금지어/CTA/이미지 스타일/레이아웃/배경/워터마크/제약/권리 메타데이터와 hash를 보존한다.
- `product_projects`: `brand_kit_version_id`, `brand_kit_override_version_id` snapshot 참조를 추가한다.
- 워크스페이스당 active workspace Brand Kit version은 하나만 허용한다.

## 4. 서비스와 API

### Pack API

- `GET /api/v1/prompt-intelligence/packs`
- `POST /api/v1/prompt-intelligence/packs/seed`
- `POST /api/v1/prompt-intelligence/packs/propose`
- `POST /api/v1/prompt-intelligence/versions/{id}/validate`
- `POST /api/v1/prompt-intelligence/versions/{id}/approve`
- `POST /api/v1/prompt-intelligence/versions/{id}/activate`
- `POST /api/v1/prompt-intelligence/versions/{id}/deprecate`
- `POST /api/v1/prompt-intelligence/evaluate`
- `POST /api/v1/prompt-intelligence/classify`

Pack lifecycle은 `draft_generated -> validation_pending -> approved -> active -> deprecated`만 허용한다. seed는 6개 category(`생활용품`, `뷰티`, `식품`, `패션`, `전자제품`, `other`)와 2개 channel(`coupang`, `naver_smartstore`)의 승인된 active version을 만든다.

### Brand Kit API

- `GET/POST /api/v1/brand-kits`
- `GET /api/v1/brand-kits/assets`
- `POST /api/v1/brand-kits/{id}/versions`
- `POST /api/v1/brand-kits/versions/{id}/activate`
- `POST /api/v1/brand-kits/projects/{project_id}/overrides`
- `GET /api/v1/brand-kits/projects/{project_id}/resolved`

모든 asset ID는 현재 workspace의 seller-owned/권리 확인 가능 asset인지 검증한다. UI는 raw ID 텍스트 입력 대신 asset picker를 사용한다.

## 5. LangGraph 연결

활성 LG-6 경로:

`evidence_review -> category_classifier -> prompt_pack_resolver -> sales_strategy -> ... -> LG-5R image subgraph`

- `category_classifier`: 독립 분류 로직으로 category, confidence, rationale, fallback 여부를 생성한다.
- `prompt_pack_resolver`: active pack만 해석하고 category가 없으면 `other`를 사용한다. Brand Kit snapshot과 compiled artifact도 여기서 고정한다.
- graph state의 `prompt_intelligence`에는 식별자·version·hash·confidence만 저장한다.
- 실제 compile body는 DB artifact에만 저장한다.
- 기존 LG-5R interrupt, worker, resume, image review 노드는 그대로 사용한다.

## 6. 프런트엔드

`/workspace/settings/intelligence`에 다음을 제공한다.

- 운영자용 category/channel pack 목록, seed, draft 제안, validate, approve, activate/deprecate, Golden Dataset 평가 리포트.
- 사용자용 workspace Brand Kit 생성/버전/활성화와 project override.
- logo/font는 workspace asset picker에서만 선택.
- 현재 활성 버전, hash, 분류 confidence/rationale/fallback, 컴파일 우선순위 안내.
- 한국어 상태/권한/검증 오류와 빈 상태.

기존 설정 화면에는 위 페이지로 이동하는 링크를 추가한다.

## 7. 요구사항-구현-테스트 매핑

| 요구사항 | 구현 | 필수 검증 |
|---|---|---|
| PRM-01 | proposal/validate/approve/activate 분리 API | LLM/내부 draft 자동 활성화 0건, actor audit |
| PRM-02 | active-only resolver와 `other` fallback | 승인된 최신 팩 사용, 미존재 시 안전한 `other` |
| PRM-03 | 분류 결과와 compiled artifact의 AgentRun snapshot pin | 현재 실행에서만 사용되고 운영자 승인 전 다른 프로젝트에 재사용되지 않음 |
| PRM-04 | 초기 category pack seed | 생활용품·뷰티·식품·패션·전자제품·`other` 6종 |
| PRM-05 | `PromptPackVersion` 불변 버전·hash | 변경 시 기존 결과를 덮지 않고 새 version 생성 |
| BRAND-01 | workspace active unique | 워크스페이스당 active 기본 version 하나 |
| BRAND-02 | 새 프로젝트 snapshot + project override version | 생성 시 active snapshot 고정 및 별도 override |
| BRAND-03 | project override immutable version | override가 workspace 기본 version을 수정하지 않음 |
| BRAND-04 | 로고·색상·폰트·말투·선호·금지·watermark 구조화 | API/UI round trip |
| BRAND-06 | logo/font asset rights validation | reference-only/cross-workspace 차단 |
| BRAND-08 | Brand Kit 없는 안전한 기본 동작 | category pack 기반으로 계속 진행 |
| QA-02 | Golden Dataset evaluation report | 독립 classifier 평가와 confusion matrix |
| OPS-01 | model/provider/prompt version 및 artifact audit | run/compiled artifact 추적 |
| OPS-07 | 비밀/원문/서명 URL 미저장 | checkpoint/log serialization 검사 |
| OPS-08 | workspace auth/role/cross-tenant filter | cross-workspace 403/404, role별 mutate 차단 |

## 8. 테스트 계획

### Backend unit/integration

- seed pack 개수·channel 분리·content hash 재현성.
- lifecycle transition 및 immutable body 검증.
- draft 제안이 active가 되지 않음.
- active-only resolver와 `other` fallback.
- Golden Dataset accuracy/fallback/confusion matrix.
- injection 문장이 system safety/approved facts를 덮어쓰지 못함.
- workspace kit active uniqueness, project snapshot, override, no-kit fallback.
- asset rights와 cross-workspace 차단.

### LangGraph

- 실제 `category_classifier -> prompt_pack_resolver -> sales_strategy` 순서.
- checkpoint에는 compact IDs/hashes만 존재.
- interrupt/resume 후 pack/Brand Kit snapshot hash 유지.
- 기존 LG-5R image generation/resume/review 회귀 통과.

### Frontend/Playwright

- pack seed/제안/검증/승인/활성화 요청과 새로고침 복구.
- Brand Kit 생성/활성화/project override와 asset picker.
- 권한 거절·빈 상태·fallback 한국어 표시.
- 유료 LLM/이미지 provider 호출은 0건.

## 9. 자체 누락 검토

- [x] category와 channel을 별도 pack/version으로 설계했다.
- [x] 분류기가 LLM/정답 lookup에 종속되지 않는다.
- [x] lifecycle과 actor audit가 분리되어 있다.
- [x] immutable snapshot/resume 안정성을 명시했다.
- [x] Brand Kit 없는 기존 workspace fallback을 포함했다.
- [x] raw asset ID 없는 picker와 권리 검증을 포함했다.
- [x] 기존 LG-5R 보존과 LG-7+ 미구현 경계를 명시했다.
- [x] API/DB/graph/frontend/Playwright 검증을 모두 매핑했다.

## 10. 완료 기준

- 대상 요구사항 미구현 0건, 부분 구현 0건, 테스트 우회 0건.
- LG-6 대상 테스트 실패 0건과 핵심 LG-5R 회귀 통과.
- 코드리뷰 문서에 요구사항별 실제 코드 위치와 실행 테스트 증거 기록.
- 브라우저 주소, 입력값, 버튼 순서, 기대 결과가 포함된 사용자 검증 가이드 제공.
