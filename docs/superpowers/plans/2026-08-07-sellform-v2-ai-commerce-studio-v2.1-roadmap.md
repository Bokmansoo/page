# Sellform V2.1 AI Commerce Studio Sprint 로드맵

작성일: 2026-08-07  
상태: **현재 구현 로드맵**  
상위 기획: [Sellform V2.1 AI Commerce Studio 최종 기획](../specs/2026-08-07-sellform-v2-ai-commerce-studio-v2.1-final-design.md)  
이전 로드맵: [2026-08-06 LangGraph 전환 로드맵](./2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 1. 로드맵 결정

기존 LG-0~LG-4는 LangGraph 기반층으로 보존한다. LG-5는 구현 자산은 있으나 최종 기획의 이미지 내구성·멱등·장면별 승인 완료 조건을 모두 증명하지 못했으므로 `LG-5R`에서 먼저 닫는다.

기존 로드맵의 LG-6~LG-8은 아직 구현 기준으로 사용하지 않고 이 로드맵의 LG-6~LG-14로 대체한다. 번호를 새로 처음부터 시작하지 않는 이유는 기존 코드·테스트·리뷰 문서의 이력을 보존하기 위해서다.

2026-08-07 제품 인터뷰에서 다음 일곱 기능을 필수 범위로 확정했다.

1. 빠른 생성과 단계별 검토 선택
2. 워크스페이스 기본값과 프로젝트 override를 가진 Brand Kit
3. section 구조와 내부 자유 편집을 결합한 Hybrid Canvas Editor
4. 복사 가능한 HTML과 HTML·이미지 ZIP 출력
5. 1분·3분·10~15분·20분 상한 목표와 진행·지연 안내
6. 서로 분리된 리뷰·레퍼런스 전용 입력
7. 치명 오류 0건, 총점 85점, 영역별 70점을 요구하는 Visual Quality Bar

## 2. 현재 기준선

| Sprint | 판정 | V2.1에서의 역할 |
| --- | --- | --- |
| LG-0 | 완료 기준선 | LangGraph 의존성, feature flag, legacy characterization |
| LG-1 | 완료 기준선 | StateGraph, PostgreSQL checkpoint, run projection |
| LG-2 | 완료 기준선 | Discovery와 승인 사실 snapshot |
| LG-3 | 완료 기준선 | 기본 판매 전략·페이지·카피·비주얼 planning |
| LG-4 | 완료 기준선 | input/evidence/planning/generation interrupt·resume |
| LG-5 | 부분 구현 | 이미지 job·review 흐름의 기반, LG-5R 보완 필요 |

LG-3의 기존 결과는 폐기하지 않고 V2.1 Prompt Intelligence artifact로 확장한다. LG-5의 job·화면·테스트도 폐기하지 않고 내구성·멱등·장면별 승인 계약을 바로잡는다.

## 3. 전체 Sprint

| Sprint | 목표 | 사용자 결과 | 실제 API 비용 |
| --- | --- | --- | --- |
| LG-5R | 이미지 생성 기반 완결 | 중복 비용 없이 장면별 생성·승인·복구 | fake 필수, real 선택 |
| LG-6 | Prompt Intelligence·Brand Kit 기반 | 카테고리와 브랜드에 맞는 검증 가능한 생성 기준 | 텍스트 선택 |
| LG-7 | 입력 확장·Creative Brief·기획 V2 | 리뷰·레퍼런스를 반영한 제품별 전략과 두 생성 모드 | 텍스트 선택 |
| LG-8 | Visual Prompt Compiler | 장면별 정체성 보존 프롬프트와 비용 계획 | 없음/텍스트 선택 |
| LG-9 | Image Production V2 | 필요한 장면만 생성·재생성·검수 | 이미지 선택 |
| LG-10 | Hybrid Page Assembly·HTML | 정확한 한글 상세페이지와 사용자용 HTML | 없음 |
| LG-11 | Hybrid Canvas·대화형 편집 | 직접 또는 자연어로 일부만 수정하고 버전 복원 | 텍스트/이미지 선택 |
| LG-12 | Visual Quality Bar·Golden Dataset | 치명 오류 없이 품질 기준을 통과한 결과 | 텍스트 선택 |
| LG-13 | 운영 내구성·SLO·비용 | 재시작 복구와 정확한 진행 시간·비용 상태 | 없음 |
| LG-14 | 전환·전체 출력·베타 E2E | 빠른 생성부터 HTML·이미지 출력까지 단일 흐름 | 제한적 |

## 4. 공통 Sprint Gate

모든 Sprint는 아래 산출물과 증거를 남긴다.

1. 요구사항 ID가 명시된 구현 계획
2. schema·migration·API·UI 변경 목록
3. 단위·통합·그래프·필요 E2E 테스트
4. 실행한 명령과 실제 결과
5. 요구사항별 코드 위치와 테스트를 연결한 코드리뷰 문서
6. 자동 검증과 사용자가 확인할 수동 검증 절차
7. 미구현·부분 구현·테스트 우회 항목 0건 확인
8. 회귀 실패와 다음 Sprint 진입 가능 여부

다음은 완료 증거로 인정하지 않는다.

- provider worker를 동기 함수로 바꿔 실제 대기·재개를 우회한 테스트
- UI 버튼이 보이는지만 확인하고 요청·상태 전이를 검증하지 않은 테스트
- API 성공 여부만 보고 품질·버전·권리 검사를 생략한 결과
- 코드리뷰 문서의 주장만 있고 실행 로그가 없는 항목

## 5. LG-5R — 이미지 생성 기반 보완

### 목표

LG-5에서 남은 중복 비용, 작업 복구, 장면별 승인, 실패 장면 재시도와 UI 계약을 먼저 완결한다.

### 대상 요구사항

`ARC-07`, `IMG-01`~`IMG-10`, `HITL-03`~`HITL-06`, `OPS-03`, `OPS-09`

### 주요 작업

1. job idempotency key를 `project + scene + prompt version + reference hash + attempt`로 교체하고 migration·호환 adapter를 만든다.
2. 기존 job의 prompt가 planning 변경 후 재사용되지 않도록 input hash를 검증한다.
3. prepare 전에 장면별·총 예상 비용을 계산하고 cost approval interrupt에서 표시한다.
4. daemon thread 의존을 제거하고 DB outbox·lease 또는 durable worker queue를 적용한다.
5. 서버 시작 recovery sweep과 lease 만료 재처리를 만든다.
6. 장면별 approve/reject/regenerate/upload 상태를 분리한다.
7. 모든 장면이 승인되기 전 graph 전체 승인을 금지한다.
8. 대상이 없을 때 regenerate는 실패 장면만 선택한다.
9. 직접 업로드는 asset picker와 권리 상태를 사용한다.
10. provider wait·worker 완료·동일 thread resume을 우회하지 않는 통합 테스트를 만든다.

### 완료 조건

- 비용 승인 전 provider dispatch 0건
- 서버·worker 재시작 후 같은 job 복구와 중복 청구 0건
- 한 장면 승인으로 전체 run이 완료되지 않음
- 실패 장면만 재시도되고 성공·승인 장면 보존
- planning 또는 prompt hash 변경 시 새 job version 생성
- API 없음·잔액 부족·timeout·안전·정체성 오류 구분
- Playwright로 비용 승인→대기→장면별 검수→새로고침 복구 통과

## 6. LG-6 — Prompt Intelligence와 Brand Kit 기반

### 목표

LLM이 카테고리 규칙을 매번 즉흥 생성하지 않고, 버전·평가·승인된 Prompt Pack을 선택·제안한다. 워크스페이스 Brand Kit과 프로젝트 override의 불변 버전 기반도 함께 만든다.

### 대상 요구사항

`PRM-01`~`PRM-05`, `BRAND-01`~`BRAND-04`, `BRAND-06`, `BRAND-08`, `QA-02`, `OPS-01`, `OPS-07`, `OPS-08`

### 주요 작업

1. Category·Channel Pack schema, migration, repository, version hash를 만든다.
2. `category_classifier`와 confidence·`other` 폴백을 구현한다.
3. `prompt_pack_resolver`가 active pack만 실행에 고정하도록 한다.
4. LLM pack proposal과 운영자 validation/approve/activate API를 분리한다.
5. 생활용품·뷰티·식품·패션·전자제품·other seed pack을 만든다.
6. system safety와 pack prompt의 우선순위 compiler를 만든다.
7. pack 변경이 기존 실행을 덮어쓰지 않는 버전 테스트를 만든다.
8. 카테고리 Golden Dataset과 분류 평가 report를 만든다.
9. BrandKitVersion schema, workspace active version과 project override migration을 만든다.
10. 로고·색상·폰트·말투·금지 요소·워터마크와 asset 권리 계약을 만든다.

### 완료 조건

- 미승인 pack이 다른 프로젝트 실행에 사용되지 않음
- 5개 카테고리와 other가 active version을 가짐
- classifier 목표 정확도 95% 또는 안전한 other 폴백
- run에서 사용한 pack ID/version/hash가 재현 가능
- system safety와 승인 사실을 category 지시가 덮어쓸 수 없음
- 새 프로젝트가 workspace Brand Kit snapshot을 참조하고 프로젝트 override가 원본을 수정하지 않음
- Brand Kit이 없어도 category 기본값으로 안전하게 진행

## 7. LG-7 — 리뷰·레퍼런스, Product Creative Brief와 생성 모드

### 목표

리뷰·레퍼런스 입력을 분리해 분석하고, 확인 사실과 판매자 창작 방향을 구분한 Creative Brief와 판매 흐름을 만든다. 빠른 생성과 단계별 검토의 mode snapshot·안전한 자동 진행 계약도 시작한다.

### 대상 요구사항

`ARC-03`, `PRM-06`~`PRM-09`, `FACT-01`~`FACT-05`, `REV-01`~`REV-09`, `BRAND-05`, `FAST-01`~`FAST-07`

### 주요 작업

1. 판매자 입력을 fact candidate와 creative direction으로 분리한다.
2. ProductCreativeBriefVersion schema·migration·hash를 만든다.
3. LG-3 Sales Strategy 앞에 Creative Brief compiler를 연결한다.
4. desired mood, target, emphasis, forbidden scene을 UI에서 확인·수정한다.
5. Page Planning과 Copywriting을 pack·brief version 입력으로 갱신한다.
6. 모든 claim에 fact ID 또는 `narrative_non_claim`을 강제한다.
7. brief 변경 시 필요한 downstream artifact만 stale 처리한다.
8. 동일 mock 입력 재현성과 real LLM schema repair 한계를 테스트한다.
9. 리뷰 XLSX·CSV·TXT·붙여넣기와 레퍼런스 URL·이미지·PDF·텍스트 intake를 만든다.
10. 리뷰 claim의 사실 승격 차단과 레퍼런스 복제 방지·권리 상태를 연결한다.
11. 시작 화면에 quick/expert 선택을 제공하고 run snapshot에 저장한다.
12. 빠른 생성의 안전한 gate 자동 응답과 위험 시 interrupt 전환·history를 구현한다.
13. Brand Kit, 리뷰와 레퍼런스 artifact를 Creative Brief에 provenance로 연결한다.

### 완료 조건

- 판매자 creative direction이 사실 검증 과정에서 사라지지 않음
- 승인 사실을 Creative Brief가 수정하거나 새로 만들지 않음
- section별 target·objective·fact IDs·copy classification 존재
- 금지 표현과 승인되지 않은 수치 claim 0건
- planning 화면에서 Category Pack과 Creative Brief 근거 확인 가능
- 리뷰와 레퍼런스가 별도 입력·schema·권리 상태로 저장됨
- 리뷰 속 미확인 claim이 사실 카피로 승격되지 않음
- quick/expert 선택이 새로고침·resume 뒤에도 유지되고 위험 gate는 자동 승인하지 않음

## 8. LG-8 — Visual Prompt Compiler와 정체성 계약

### 목표

공통 이미지 프롬프트를 장면별 versioned prompt로 바꾸고 제품 정체성·권리·텍스트 정책을 고정한다.

### 대상 요구사항

`ARC-04`, `PRM-10`~`PRM-13`, `IMG-08`~`IMG-10`, `BRAND-05`, `BRAND-07`

### 주요 작업

1. ScenePromptVersion과 identity lock schema를 만든다.
2. scene type별 canonical prompt compiler를 만든다.
3. provider-specific adapter를 canonical prompt와 분리한다.
4. reference asset ID/hash, 권리 상태, 제품 형태·색상·부품 constraint를 주입한다.
5. `no_rasterized_copy`와 negative text/QR/watermark 정책을 적용한다.
6. 장면별 모델·크기·예상 비용을 계산한다.
7. 스토리보드에서 장면 prompt 요약과 기준 사진을 검토할 수 있게 한다.
8. prompt 또는 reference 변경 시 해당 장면 job만 stale 처리한다.
9. Brand Kit의 색상·시각 키워드·금지 요소와 로고 정책을 scene prompt에 주입한다.
10. Brand Kit 변경 시 영향받는 visual artifact와 scene job만 stale 처리한다.

### 완료 조건

- 모든 생성 장면에 prompt version/hash와 reference hash 존재
- HERO·사용·기능·소재·구성품·크기·사용법 장면 구분
- 정체성 고정 요소가 모든 관련 prompt에 포함
- 이미지 모델에 최종 한국어 카피·사양표 생성을 요청하지 않음
- 한 장면 prompt 수정이 다른 장면 job을 무효화하지 않음

## 9. LG-9 — Image Production V2와 장면 검수

### 목표

LG-5R의 내구성 위에서 ScenePromptVersion을 실제 생성·검수에 연결하고 품질이 부족한 장면만 재작업한다.

### 대상 요구사항

`IMG-01`~`IMG-10`, `QA-03`, `EDT-02`

### 주요 작업

1. LG-8 scene prompt를 job 입력 snapshot으로 고정한다.
2. identity, OCR, crop, resolution, safety, rights validator를 연결한다.
3. 결과별 자동 검사 report와 판매자 비교 UI를 만든다.
4. 장면별 후보 선택·승인·거절·재생성·직접 업로드를 완성한다.
5. 부분 실패와 provider fallback 정책을 적용한다.
6. 승인 자산 manifest를 Page Assembly 입력으로 고정한다.
7. fake provider 전체 E2E와 비용 승인 real smoke suite를 분리한다.

### 완료 조건

- 자동 검사 실패 자산이 최종 조립에 들어가지 않음
- 판매자 승인 자산만 approved manifest에 포함
- 일부 장면 실패가 다른 승인 자산을 삭제하지 않음
- 직접 업로드가 raw ID 입력 없이 동작
- 실제 API 테스트를 실행하지 않아도 fake worker 전체 흐름이 검증됨

## 10. LG-10 — Hybrid Page Assembly와 사용자용 HTML

### 목표

AI 장면 이미지와 정확한 한국어 카피·표·그래픽을 수정 가능한 canonical page로 조립하고, 복사 가능한 HTML과 독립 실행 가능한 HTML·이미지 ZIP으로 출력한다.

### 대상 요구사항

`ASM-01`~`ASM-07`, `ARC-04`, `QA-04`, `BRAND-05`, `HTML-01`~`HTML-08`

### 주요 작업

1. canonical page/section/layout token schema를 고정한다.
2. Page Assembly prompt를 component·token 선택 output으로 제한한다.
3. 안전 정보형·이미지 중심형·균형 판매형 renderer를 구현한다.
4. 한국어 카피·사양·주의사항을 HTML/CSS text layer로 렌더링한다.
5. 이미지 없는 정보 섹션과 기존 사진 폴백을 지원한다.
6. preview와 headless export가 같은 page snapshot을 읽게 한다.
7. 폰트·줄바꿈·표·모바일 폭 visual regression을 만든다.
8. Brand Kit 색상·폰트·로고·워터마크를 renderer token과 license gate에 연결한다.
9. HTML code copy와 HTML·CSS·승인 이미지·manifest ZIP export를 만든다.
10. sanitization, unsupported element fallback과 로컬 `index.html` preview를 검증한다.
11. HTML과 이미지 export history가 같은 DetailPageVersion을 참조하게 한다.

### 완료 조건

- 생성 이미지 안 한글에 의존하지 않고 정확한 본문 렌더링
- page version이 copy/asset/layout version을 ID로 고정
- API 이미지 0장이어도 안전한 상세페이지 생성 가능
- preview와 PNG/JPG의 section·copy·asset manifest 일치
- 세 디자인 방향 모두 Golden 제품에서 렌더링 통과
- 복사 HTML과 ZIP이 만료 signed URL·위험 script에 의존하지 않음
- ZIP의 `index.html`이 외부 API 없이 열리고 export history에서 재다운로드 가능

## 11. LG-11 — Hybrid Canvas, 대화형 부분 편집과 버전 복원

### 목표

section 구조와 내부 자유 배치를 결합한 Hybrid Canvas와 자연어 수정 경험을 제공하되 변경 범위·채널 안전성과 비용을 예측 가능하게 만든다.

### 대상 요구사항

`ARC-05`, `EDT-01`~`EDT-07`, `CANVAS-01`~`CANVAS-09`, `OPS-02`

### 주요 작업

1. EditIntent schema와 intent router를 만든다.
2. 명령 preview에서 target, invalidation, 비용, 필요한 재승인을 표시한다.
3. copy·scene·style·fact별 dependency invalidation을 구현한다.
4. 부분 regenerate와 같은 thread/fork 정책을 고정한다.
5. 새 page version 생성과 이전 버전 rollback을 만든다.
6. 자연어 수정 UI와 직접 section editor를 연결한다.
7. 모호함·사실 변경·비용 발생 확인 흐름을 만든다.
8. section 순서·높이와 내부 요소 이동·크기·레이어·잠금·그룹 편집을 만든다.
9. 정렬 가이드, snap, 안전 영역, 잘림·겹침 경고와 채널 preview를 만든다.
10. undo/redo, 자동 저장, draft와 page version 복원을 만든다.
11. 선택 요소의 ID·version을 채팅 edit context로 고정한다.
12. Canvas canonical snapshot을 모든 preview·image·HTML renderer가 공유하게 한다.

### 완료 조건

- 카피 수정 시 이미지 provider 호출 0건
- 한 장면 수정 시 해당 장면만 새 job 생성
- 사실 수정 시 evidence review부터 재승인
- 수정 전 영향 범위와 예상 비용 표시
- 새로고침 후 수정 run·version 복원
- 이전 page version rollback과 export 재현
- Canvas 직접 편집과 선택 요소 채팅 수정이 동일 version history에 저장
- 채널 안전 영역 위반이 export 전에 경고·차단되고 preview와 출력 parity 유지

## 12. LG-12 — Visual Quality Bar와 Golden Dataset 품질 게이트

### 목표

“생성 성공”이 아니라 판매 가능한 사실·정체성·디자인·브랜드·채널 품질을 수치와 치명 오류 gate로 판정한다.

### 대상 요구사항

`ARC-08`, `QA-01`~`QA-06`, `FACT-01`~`FACT-05`, `VQB-01`~`VQB-08`

### 주요 작업

1. 5개 카테고리×최소 3개 제품 Golden Dataset을 고정한다.
2. fact, identity, copy, visual, layout, rights, channel, parity evaluator를 만든다.
3. QA routing code와 대상 노드 재실행을 연결한다.
4. 노드별 최대 2회와 seller review escalation을 구현한다.
5. 자동 점수와 사람 rubric을 같은 report로 저장한다.
6. prompt pack·model·renderer 변경 전후 비교 도구를 만든다.
7. 정체성·사실·레이아웃·한국어·Brand Kit·장면 흐름·채널 품질의 가중 점수를 만든다.
8. 치명 오류 0건, 총점 85점, 영역별 70점 gate를 적용한다.
9. section·scene·copy별 품질 근거와 선택적 재작업 대상을 report에 기록한다.
10. 빠른 생성 모드가 QA를 우회하지 못하는 그래프 테스트를 만든다.

### 완료 조건

- 치명 사실 오류·금지 표현 0건
- QA 사유와 맞는 노드만 재실행
- 자동 루프 최대 2회 후 사용자 행동 제공
- Golden Dataset 결과가 version별 비교 가능
- 품질 기준 미달 결과가 final version으로 승격되지 않음
- 치명 오류 1건 또는 총점·영역별 threshold 미달 시 export 승격 차단
- 최대 2회 선택적 재작업 후 비교 후보와 문제 설명을 판매자에게 제공

## 13. LG-13 — 운영 내구성·생성 시간 SLO·관측·비용

### 목표

장시간 graph와 provider 작업을 실제 운영에서 복구하고 생성 시간·비용·실패 원인을 사용자에게 설명할 수 있게 한다.

### 대상 요구사항

`OPS-01`~`OPS-10`, `HITL-01`~`HITL-06`, `SLO-01`~`SLO-08`, `FAST-08`

### 주요 작업

1. event stream과 graph state projection adapter를 완성한다.
2. SSE 재연결과 last event cursor를 구현한다.
3. checkpoint projection rebuild와 recovery sweep을 운영 명령으로 만든다.
4. outbox·lease·dead-letter 상태와 재처리 UI를 만든다.
5. 장면·attempt·provider별 예상/실제 비용을 집계한다.
6. 로그·checkpoint·event의 secret·민감 자료 마스킹을 검증한다.
7. workspace 권한과 자산 signed URL 만료를 점검한다.
8. 사용자용 복구 메시지와 운영자용 원인 정보를 분리한다.
9. 분석 1분, planning 3분, 일반 이미지 페이지 10~15분과 정상 실행 90% 20분 목표를 계측한다.
10. 노드·장면별 ETA와 지연 원인을 event projection으로 제공한다.
11. 완료 section의 부분 preview와 실패 장면 2회 재시도·폴백 선택을 연결한다.

### 완료 조건

- 서버·worker 강제 종료 후 마지막 안전 상태 재개
- SSE 끊김과 새로고침 후 동일 진행·interrupt 복원
- 로그만으로 실패 노드·원인·비용·재시도 확인
- projection rebuild가 중복 page/job을 만들지 않음
- secret과 고객 원문이 일반 로그·checkpoint에 없음
- SLO dashboard에서 단계별 p50/p90·provider 지연과 20분 초과 원인을 확인 가능
- 사용자가 완료된 section, 현재 단계, ETA와 재시도·폴백 행동을 확인 가능

## 14. LG-14 — 전체 전환·채널 출력·베타 E2E

### 목표

모든 신규 생성 진입점을 V2.1 LangGraph로 통일하고 실제 사용 가능한 출력과 운영 가이드를 완성한다.

### 대상 요구사항

최종 기획의 모든 요구사항과 완료 정의 1~18

### 주요 작업

1. quick/expert 시작, planning, result, Canvas, history를 단일 graph/page version 흐름으로 연결한다.
2. 신규 쓰기 경로의 legacy 직접 orchestration을 제거한다.
3. 기존 프로젝트 읽기·다운로드 호환과 rollback 절차를 보존한다.
4. 쿠팡·스마트스토어 JPG·PNG·분할 ZIP과 사용자용 HTML·ZIP 규격을 검증한다.
5. 리뷰·레퍼런스·Brand Kit 입력→빠른 생성→이미지 검수→조립→Canvas 수정→HTML·이미지 출력 E2E를 실행한다.
6. 중복 클릭, 브라우저 새로고침, 서버 재시작, provider 실패 E2E를 실행한다.
7. Golden Dataset, 보안, 비용, 데이터 격리, 접근성 최종 gate를 실행한다.
8. 사용자 가이드·운영 runbook·최종 코드리뷰를 작성한다.

### 완료 조건

- 신규 생성 경로의 legacy 호출 0건
- 모든 요구사항 ID가 코드·테스트 증거와 연결됨
- 미구현·부분 구현·우회 테스트 0건
- API 미준비 포함 전체 제품 흐름 통과
- 빠른 생성과 단계별 검토가 같은 사실·비용·Visual Quality Bar를 사용
- preview·Canvas·HTML·JPG·PNG·ZIP 동일 version parity
- 정상 provider mock 시간과 품질 threshold의 release gate 통과
- 사용자가 주소와 버튼만으로 전체 흐름을 재현하는 검증 가이드 존재

## 15. 의존 관계

```text
완료 기반: LG-0 → LG-1 → LG-2 → LG-3 → LG-4
                                      ↓
                                    LG-5
                                      ↓
                                    LG-5R
                                      ↓
LG-6 Prompt Intelligence
  → LG-7 Creative Brief & Planning V2
      → LG-8 Visual Prompt Compiler
          → LG-9 Image Production V2
              → LG-10 Hybrid Assembly
                  → LG-11 Conversational Editing
                      → LG-12 QA & Golden Dataset
                          → LG-13 Operations
                              → LG-14 Final Migration & Beta E2E
```

LG-6과 LG-5R의 일부 schema 작업은 병렬 설계할 수 있지만, 다음 Sprint 진입은 앞 Sprint의 공통 Gate를 통과한 뒤에만 허용한다.

## 16. 요구사항 추적표

| 요구사항 | 구현 Sprint |
| --- | --- |
| ARC-01, ARC-02 | 기존 LG-0~LG-4, LG-14 최종 확인 |
| ARC-03 | LG-7 |
| ARC-04 | LG-8, LG-10 |
| ARC-05 | LG-11 |
| ARC-06 | LG-6~LG-14 공통 |
| ARC-07 | LG-5R, LG-9 |
| ARC-08 | LG-12 |
| PRM-01, PRM-02, PRM-03, PRM-04, PRM-05 | LG-6 |
| PRM-06, PRM-07, PRM-08, PRM-09 | LG-7 |
| PRM-10, PRM-11, PRM-12, PRM-13 | LG-8 |
| FACT-01, FACT-02, FACT-03, FACT-04, FACT-05 | LG-7, LG-12 |
| IMG-01, IMG-02, IMG-03, IMG-04, IMG-05, IMG-06, IMG-07, IMG-08, IMG-09, IMG-10 | LG-5R, LG-9 |
| ASM-01, ASM-02, ASM-03, ASM-04, ASM-05, ASM-06, ASM-07 | LG-10 |
| EDT-01, EDT-02, EDT-03, EDT-04, EDT-05, EDT-06, EDT-07 | LG-11 |
| QA-01, QA-02, QA-03, QA-04, QA-05, QA-06 | LG-12 |
| HITL-01, HITL-02, HITL-03, HITL-04, HITL-05, HITL-06 | 기존 LG-4, LG-5R, LG-13 |
| OPS-01, OPS-02, OPS-03, OPS-04 | LG-6~LG-12 공통 |
| OPS-05, OPS-06, OPS-07, OPS-08, OPS-09, OPS-10 | LG-13 |
| FAST-01, FAST-02, FAST-03, FAST-04, FAST-05, FAST-06, FAST-07 | LG-7, LG-14 |
| FAST-08 | LG-13, LG-14 |
| BRAND-01, BRAND-02, BRAND-03, BRAND-04, BRAND-06, BRAND-08 | LG-6 |
| BRAND-05 | LG-7, LG-8, LG-10 |
| BRAND-07 | LG-8, LG-11 |
| REV-01, REV-02, REV-03, REV-04, REV-05, REV-06, REV-07, REV-08, REV-09 | LG-7 |
| CANVAS-01, CANVAS-02, CANVAS-03, CANVAS-04, CANVAS-05, CANVAS-06, CANVAS-07, CANVAS-08, CANVAS-09 | LG-11 |
| HTML-01, HTML-02, HTML-03, HTML-04, HTML-05, HTML-06, HTML-07, HTML-08 | LG-10, LG-14 |
| SLO-01, SLO-02, SLO-03, SLO-04, SLO-05, SLO-06, SLO-07, SLO-08 | LG-13, LG-14 |
| VQB-01, VQB-02, VQB-03, VQB-04, VQB-05, VQB-06, VQB-07, VQB-08 | LG-12, LG-14 |

## 17. 다음 착수 항목

다음 구현은 LG-6이 아니라 **LG-5R**이다. LG-5R 코드리뷰에서 이미지 job 멱등 키, durable worker, cost approval, 장면별 승인, 실패 장면만 재시도, 직접 업로드 UI와 실제 대기·재개 E2E를 모두 닫은 뒤 LG-6 Prompt Intelligence·Brand Kit 기반으로 이동한다. 인터뷰에서 확정한 일곱 기능은 LG-6~LG-14에 분산 구현하며 LG-14 전체 E2E가 통과하기 전에는 경쟁 서비스 수준의 제품 경험이 완료됐다고 판정하지 않는다.
