# Sellform V2.1 AI Commerce Studio 최종 기획

작성일: 2026-08-07  
개정일: 2026-08-20
상태: **현재 제품·구현 기준이 되는 최종 기획**
구현 로드맵: [Sellform V2.1 Sprint 로드맵](../plans/2026-08-07-sellform-v2-ai-commerce-studio-v2.1-roadmap.md)  
이전 기준: [2026-08-06 LangGraph 최종 기획](./2026-08-06-sellform-v2-langgraph-agent-system-final-design.md)

## 1. 문서의 역할

이 문서는 Sellform을 단순한 “LangGraph 데모”나 상세페이지 생성기 하나가 아니라, 판매자가 상품을 한 번 입력하면 판매 가능한 상세페이지를 만들고 이후 같은 상품 기준에서 소셜 소재와 영상까지 파생할 수 있는 AI Commerce Content Studio로 완성하기 위한 단일 제품·기술 기준이다.

기존 LG-0~LG-5에서 만든 LangGraph 실행 기반, 자료 수집, 사실 보드, 기획, 승인 대기, 이미지 작업 자산을 폐기하지 않는다. 다만 기존 기획에서 약했던 카테고리별 프롬프트 지능, 제품별 Creative Brief, 디자인 품질, 부분 재생성, 조립 렌더러, 평가 체계와 운영 복구 계약을 이 문서에서 다시 고정한다.

이 문서와 이전 문서가 충돌하면 이 문서가 우선한다. 이전 문서는 구현 이력과 의사결정 배경으로만 사용한다.

## 2. 최종 제품 정의

Sellform의 제품 포지셔닝은 다음과 같다.

> 상품 입력 한 번으로 판매 콘텐츠의 모든 것을 만드는 AI Commerce Content Studio

Sellform의 최종 사용자 약속은 다음과 같다.

> 판매자가 상품 URL, 상품 사진 또는 수동 상품 정보를 한 번 입력하면, AI가 검증 가능한 하나의 상품 기준을 만들고 카테고리·상품·판매 채널에 맞는 전략과 장면을 설계한다. 이 기준에서 제품 정체성을 보존한 이미지와 정확한 한국어 카피를 조립해 수정 가능한 상세페이지를 만들고, 후속 단계에서는 동일 기준에서 소셜 소재와 숏폼 영상을 파생한다.

핵심 고객은 스마트스토어·쿠팡 판매자, 소상공인, D2C·자사몰 운영자, 브랜드 마케터와 콘텐츠 크리에이터다.

최종 제품은 다음 경험을 제공해야 한다.

1. `owned_product_url`, `photo_only`, `manual` 중 하나로 시작할 수 있다.
2. 모든 입력 모드는 동일한 normalized product contract로 수렴하며, 링크 수집에 실패해도 직접 업로드 사진과 판매자 입력으로 계속할 수 있다.
3. 확인된 사실과 창작 방향을 분리해 허위·과장 표현을 막는다.
4. 카테고리별 구매 심리와 상세페이지 관습을 반영한다.
5. API 키나 잔액이 없어도 기획·카피·장면 계획을 완성하고 같은 실행을 안전하게 대기시킨다.
6. API가 준비되면 같은 LangGraph thread를 재개해 필요한 이미지만 만든다.
7. AI 이미지 안에 깨진 한국어를 그리지 않고 정확한 문구를 렌더러가 배치한다.
8. 판매자는 “3번 장면만 고급스럽게”처럼 자연어로 일부만 수정할 수 있다.
9. 미리보기, 편집기, JPG·PNG·분할 ZIP은 동일한 승인 버전을 사용한다.
10. 실패·새로고침·서버 재시작·중복 클릭 이후에도 작업과 비용 상태가 복구된다.
11. 상세페이지, 소셜 소재와 영상은 서로를 재분석하지 않고 동일한 `CommerceCreativeMasterVersion`에서 파생된다.

## 3. 범위와 비범위

### 3.1 포함 범위

- 상품 입력, 자산 분류, OCR, URL·참고 자료 수집
- 확인 사실·충돌·불확실성 관리
- 카테고리 분류와 Category Prompt Pack
- 제품별 Product Creative Brief
- 판매 전략, 섹션 흐름, 한국어 카피, 장면 계획
- 장면별 Visual Prompt Compiler
- 제품 정체성 기반 이미지 생성과 판매자 검수
- HTML/CSS 기반 상세페이지 조립과 이미지 출력
- 자연어 기반 부분 수정과 선택적 재실행
- 자동 QA, Golden Dataset, 운영 관측과 복구
- 쿠팡·스마트스토어 채널별 출력
- 동일 Commerce Creative Master에서 파생되는 소셜 크리에이티브, 숏폼 영상과 캠페인 콘텐츠 팩

### 3.2 제외 범위

- 승인되지 않은 경쟁사 사진·카피·레이아웃의 복제
- 사용자의 상품 사진이나 결과물을 모델 학습에 자동 사용
- 확인되지 않은 효능·인증·가격 우위의 자동 생성
- LLM이 운영 정책과 금지 표현을 임의로 변경하는 기능
- 모든 카테고리를 첫 출시부터 개별 최적화하는 작업
- 이미지 모델이 최종 한국어 본문과 표를 직접 그리는 방식
- 상세페이지 PNG·JPG를 다시 분석해 소셜·영상의 상품 사실을 추출하는 방식

## 4. 핵심 설계 원칙

| ID | 원칙 | 고정 결정 |
| --- | --- | --- |
| ARC-01 | LangGraph의 역할 | LangGraph는 상태·분기·승인·재개·재작업을 조정하며, 이미지 품질 자체를 대신하지 않는다. |
| ARC-02 | 11개 전문 에이전트 | 기존 11개 역할을 유지하고 Prompt Compiler·Category Router 등은 명시적 내부 노드 또는 도메인 서비스로 둔다. |
| ARC-03 | 사실과 창작 분리 | `approved_facts`와 `seller_creative_direction`은 별도 스키마·저장소·UI로 관리한다. |
| ARC-04 | 생성과 타이포 분리 | AI는 제품·배경·연출 이미지를 만들고 한국어 카피·표·아이콘은 HTML/CSS 렌더러가 배치한다. |
| ARC-05 | 선택적 재실행 | 수정 범위를 dependency graph로 계산해 영향받은 artifact와 장면만 무효화한다. |
| ARC-06 | 버전 우선 | prompt, pack, fact, brief, plan, copy, scene, asset, page, export를 모두 불변 버전으로 연결한다. |
| ARC-07 | 비용 전 명시 승인 | 실제 유료 provider 호출 전에 장면 수·예상 비용·재시도 범위를 표시하고 승인받는다. |
| ARC-08 | 품질을 완료 조건으로 | API 성공이 아니라 사실성·정체성·가독성·디자인·출력 일치 QA 통과를 완료로 본다. |
| ARC-09 | 입력 snapshot 우선 | URL·사진·수동 입력은 불변 source/truth/confirmation version으로 정규화하며 mutable current state를 파생 콘텐츠의 기준으로 사용하지 않는다. |
| ARC-10 | Creative Master 파생 | 상세페이지·소셜·영상·캠페인은 거대한 복사본이 아니라 동일한 불변 Commerce Creative Master의 version/hash 참조에서 파생한다. |

## 5. 최종 사용자 흐름

```text
상품 입력 모드 선택
      ├─ owned_product_url
      ├─ photo_only
      └─ manual
  → ProductSourceSnapshotVersion
  → ProductTruthVersion
  → SellerConfirmationVersion
  → ProductCreativeBriefVersion
  → CommerceCreativeMasterVersion
  → 생성 방식 선택
      ├─ 빠른 생성(추천)
      └─ 단계별 검토
  → 입력 검토
  → 자료 수집·OCR·상품 이해
  → 사실·증거 검토
  → 카테고리 분류와 Prompt Pack 선택
  → Product Creative Brief 생성
  → 판매 전략·스토리보드·카피·비주얼 계획
  → 기획 검토
  → 이미지 생성 비용 검토
      ├─ API/잔액 없음 → generation_pending으로 안전 대기
      ├─ 기존 사진·HTML만 사용 → 페이지 조립
      └─ 생성 승인 → 장면별 이미지 생성·검사
  → 이미지 검토
  → HTML/CSS 페이지 조립
  → 자동 QA와 필요한 노드만 재작업
  → 최종 검토
  → 대화형 부분 수정
  → JPG·PNG·분할 ZIP 출력
  → 같은 Commerce Creative Master에서 후속 콘텐츠 파생
      ├─ SocialKitVersion
      ├─ VideoProjectVersion
      └─ CampaignContentPackVersion
```

사용자는 내부 에이전트 이름을 알 필요가 없다. 화면은 항상 “현재 확인할 내용”, “왜 멈췄는지”, “다음에 누를 버튼”, “비용 발생 여부”를 한국어로 보여준다.

### 5.1 빠른 생성과 단계별 검토

프로젝트 시작 시 사용자는 두 모드 중 하나를 선택한다. 기본 추천은 `quick`이지만 사용자의 명시적 선택을 저장한다.

| 모드 | 동작 |
| --- | --- |
| `quick` | 비용 승인 뒤 확실한 source-backed fact와 deterministic image QA `PASS` 장면을 정책에 따라 자동 채택하며 기획·카피·이미지·조립·QA까지 진행한다. 모든 중간 장면의 수동 승인을 강제하지 않지만 사실 모호성, 권리, 제품 정체성, 안전, 비용 또는 critical quality 문제가 있으면 HITL interrupt에서 멈춘다. |
| `expert` | product understanding, planning, storyboard, scene review, 비용과 최종 결과를 기존 검수 기능으로 단계별 확인한다. |

FAST-01. 시작 화면에서 `빠른 생성`과 `단계별 검토`를 선택하며 빠른 생성을 추천값으로 표시한다.  
FAST-02. 선택한 모드는 run snapshot과 checkpoint에 저장하고 새로고침·재개 후 유지한다.  
FAST-03. 빠른 생성은 승인 gate를 삭제하지 않고 확실한 source-backed fact와 deterministic image QA `PASS` 장면만 정책에 따라 자동 채택한다. 모든 중간 장면의 사용자 승인을 요구하지 않는다.
FAST-04. 사실 모호성·충돌, 승인되지 않은 claim, 권리, 제품 정체성, 안전, 비용과 critical quality 문제는 모드와 관계없이 HITL interrupt에서 사용자에게 확인한다.
FAST-05. 단계별 검토는 기존 LG-7 기획 검수와 LG-9 장면 검수를 유지하며 product understanding, planning, storyboard, scene review를 포함한 각 interrupt의 근거·비용·영향 범위를 보여준다.
FAST-06. 실행 도중 빠른 생성에서 단계별 검토로 전환할 수 있으며 기존 artifact와 승인 결과를 잃지 않는다.  
FAST-07. 자동 승인된 gate와 그 근거를 history에 남겨 사용자가 사후 확인할 수 있게 한다.  
FAST-08. 빠른 생성에서도 완료된 섹션부터 미리보기와 실제 진행 상태를 제공한다.

### 5.2 Unified Product Intake와 불변 상품 기준

세 입력 모드는 서로 다른 임시 경로가 아니라 동일한 production LangGraph intake subgraph로 들어가 다음 불변 version chain을 만든다.

```text
owned_product_url | photo_only | manual
  → ProductSourceSnapshotVersion
  → ProductTruthVersion
  → SellerConfirmationVersion
  → ProductCreativeBriefVersion
  → CommerceCreativeMasterVersion
```

`ProductCreativeBriefVersion` compiler는 `ProductTruthVersion`, `SellerConfirmationVersion`, `BrandKitVersion`, 기존 review/reference provenance를 직접 사용한다. `CommerceCreativeMasterVersion`은 compile된 Brief 결과를 reference하며 Creative Brief의 입력이 되지 않는다. Category/Channel Pack과 Brand Kit는 이 단방향 compiler 입력에 포함된다.

`ProductSourceSnapshotVersion`은 입력 모드, 원본 asset/document의 ID와 SHA-256, URL capture identity, OCR/VLM 결과 참조, 수집 시각, parser/model version, 권리·provenance, source fidelity와 canonical hash를 보존한다. 원본 bytes나 전체 문서를 graph state에 복사하지 않는다.

`ProductTruthVersion`은 source snapshot을 참조해 승인 후보 fact, unknown fact, conflict, prohibited inference, evidence edge와 정규화된 상품 identity를 기록한다. OCR·VLM·LLM이 관찰하지 못한 구성·효능·인증·수치를 추측해 사실로 만들 수 없다.

`SellerConfirmationVersion`은 truth version, 판매자에게 제시한 최대 3개의 핵심 확인 질문, 답변, confirmed/rejected/unknown fact, 권리 확인, actor와 canonical hash를 보존한다. 확인되지 않은 사실이나 권리는 후속 master의 승인 입력이 될 수 없다.

`CommerceCreativeMasterVersion`은 내용을 복제하는 aggregate가 아니라 아래 artifact의 stable ID/version/hash와 target channel만 참조하는 불변 인덱스다. 현재 production planning 계약의 실제 명칭은 `page_planning`과 `copywriting`이며, 별도 DB class를 가정하지 않고 각각 generic stable artifact reference(`artifact_id`, `artifact_version` 또는 `schema_version`, `artifact_hash`)로 고정한다.

- `ProductSourceSnapshotVersion`: id/version/hash
- `ProductTruthVersion`: id/version/hash
- `SellerConfirmationVersion`: id/version/hash
- `ProductCreativeBriefVersion`: id/version/hash
- `BrandKitVersion`: id/version/hash
- evidence artifact와 approved fact snapshot: 각각 id/version/hash
- approved asset manifest: id/version/hash
- production `copywriting` artifact: stable artifact id/version/hash
- production `page_planning` artifact: stable artifact id/version/hash
- target channels

최초 master는 source/truth/confirmation/brief/Brand Kit/evidence/fact와 target channel reference를 고정한다. approved asset manifest, `copywriting`, `page_planning` 또는 downstream output이 뒤에 확정되면 기존 master를 수정하지 않고 successor master version을 만든다. `DetailPageVersion`, `SocialKitVersion`, `VideoProjectVersion` 같은 downstream output reference는 successor master에만 추가한다. 원문·OCR·이미지·카피 본문은 master에 중복 저장하지 않는다.

INTAKE-01. `owned_product_url`, `photo_only`, `manual`을 first-class input mode로 지원한다.
INTAKE-02. 세 모드는 동일한 normalized product contract와 이후 Creative Brief·planning contract로 수렴한다.
INTAKE-03. 입력 시작 시 선택한 mode를 run, checkpoint, source snapshot과 durable projection에 고정한다.
INTAKE-04. URL 수집 실패는 다른 입력 모드로 안전하게 보완할 수 있지만 이미 생성한 source version을 덮어쓰지 않는다.
INTAKE-05. 판매자 확인 질문은 한 번의 confirmation cycle에서 우선순위가 높은 최대 3개로 제한한다.
INTAKE-06. unsupported inference, unknown fact와 rights 미확정은 명시적 상태로 남기며 사실처럼 채우지 않는다.
INTAKE-07. 새로고침·restart·resume 후 같은 input mode와 pending confirmation을 복원한다.
INTAKE-08. intake 완료만으로 이미지·LLM provider 비용을 발생시키지 않으며 유료 호출은 기존 승인 계약을 따른다.
INTAKE-09. mode, version IDs, source fidelity, prohibited inference count, unknown fact count와 clarification count를 event·quality metadata에 남긴다.
INTAKE-10. 동일 normalized contract의 fake-provider 실행은 입력 순서와 무관하게 동일 canonical identity를 만든다.

SOURCE-01. source, truth와 seller confirmation은 각각 immutable version과 canonical hash를 가진다.
SOURCE-02. owned URL mode는 URL 문자열이 아니라 소유·사용 권리, capture 시각, capture content hash와 수집 결과를 snapshot한다.
SOURCE-03. photo-only mode는 권리 확인된 사진의 OCR/VLM 관찰 결과와 관찰 불가 영역을 구분한다.
SOURCE-04. manual mode는 판매자 입력을 fact candidate와 creative direction으로 분리한다.
SOURCE-05. 모든 source asset/document는 asset ID, SHA-256, provenance와 rights status를 가진다.
SOURCE-06. source fidelity와 evidence가 부족한 값은 unknown이며 자동 보완·추론하지 않는다.
SOURCE-07. truth와 confirmation 변경은 기존 version을 수정하지 않고 successor version을 만든다.
SOURCE-08. source/truth/confirmation hash 불일치나 lineage 단절은 master 생성과 품질 승격을 차단한다.

MASTER-01. seller confirmation·rights gate와 Product Creative Brief compiler를 통과한 입력만 Commerce Creative Master를 만들 수 있다.
MASTER-02. master는 source/truth/confirmation/brief/Brand Kit/evidence/fact/approved asset manifest와 production `copywriting`·`page_planning` artifact의 stable ID/version/hash 및 target channels를 가진 불변 reference index이며 대용량 원문·bytes·카피 본문을 중복 저장하지 않는다.
MASTER-03. master가 참조하는 모든 artifact는 실제 canonical source와 ID/version/hash parity를 재검증한다. 현재 `copywriting`·`page_planning`에 독립 class가 없으면 generic stable artifact ref를 사용하되 id/version/hash를 생략하지 않는다.
MASTER-04. `DetailPageVersion`, `SocialKitVersion`, `VideoProjectVersion`은 source master ID/version/hash를 고정한다.
MASTER-05. source/truth/confirmation 변경이나 approved asset manifest·`copywriting`·`page_planning`·파생 output reference 추가는 기존 master를 수정하지 않고 successor master version과 필요한 선택적 downstream stale 범위를 만든다. downstream output reference는 successor master에만 추가한다.
MASTER-06. 소셜·영상은 상세페이지 PNG·JPG를 재분석하지 않고 master의 fact, brief, brand와 asset reference를 사용한다.
MASTER-07. restart/history rebuild 후 동일 master lineage와 downstream version reference가 복원돼야 한다.
MASTER-08. reference-only, supplier, blocked 또는 rights 미확정 asset은 master의 final-use asset reference가 될 수 없다.

### 5.3 Product Experience / Commerce Content Studio UX Principles

Sellform의 primary UX는 내부 AI pipeline을 보여 주는 개발자용 graph dashboard가 아니라, 판매자가 상품을 한 번 가져온 뒤 필요한 판매 콘텐츠를 차례로 만들고 관리하는 Commerce Content Studio다. 내부 version·checkpoint·node·lineage 용어는 사용자 화면의 primary label로 노출하지 않는다.

1. 상품 진입은 `owned_product_url`, `photo_only`(상품 사진 1~2장), `manual` 세 방식뿐이며, 서로 다른 제품 기능이 아니라 같은 상품을 가져오는 세 input mode로 안내한다.
2. 진행 상태는 기술 용어 대신 `상품 분석 중`, `상품 정보를 확인했어요`, `몇 가지만 확인해주세요`, `콘텐츠 기준을 준비하고 있어요`, `상세페이지가 준비됐어요`처럼 현재 할 일과 결과를 중심으로 설명한다.
3. 상품 입력 한 번으로 만든 동일 Commerce Creative Master에서 상세페이지, 소셜 소재, 영상, 캠페인 팩이 각각의 immutable output lineage로 파생된다. Social/Video는 Detail Page PNG·JPG를 다시 분석해 만들지 않는다.
4. 결과 화면의 정보 hierarchy는 `상품 → 생성 가능한 콘텐츠 → 생성 결과 → 품질 상태 → 편집/재생성 → export` 순서로 둔다. 내부 pipeline/debug 정보는 일반 판매자의 primary UI에서 숨긴다.
5. LG-14 Detail Page Beta는 상품 입력 → AI 상품 이해 → 필요한 seller confirmation → 상세페이지 생성 → preview/edit → SmartStore/Coupang export를 하나의 자연스러운 판매자 workflow로 제공한다. 결과 중심 화면에는 상세페이지 준비 상태, preview, 품질 상태, 편집, 재생성, export를 표시한다.
6. LG-15에서는 같은 Master의 카드뉴스 초안을 카드형 visual preview로 보여 주고, 판매자가 개별 카드 미리보기·수정·재생성·다운로드/export를 할 수 있게 한다.
7. LG-16에서는 같은 Master의 confirmed facts, approved assets, visual direction, Brand Kit, Creative Brief를 사용해 독립적인 VideoProject lineage를 만든다. 영상은 상세페이지 이미지를 단순 영상화한 결과로 제한하지 않는다.
8. LG-17에서는 하나의 상품 workspace에서 Detail Page, Social Kit, Video Project의 생성 가능 상태와 완료 결과를 함께 보여 주고, 각 결과의 미리보기·편집·내보내기로 이어지게 한다.
9. Mirr, 후커블, 드랩아트, 크리에이지 등 동종 제품의 단순한 입력·결과 중심·카드형 preview 같은 UX 원칙은 참고할 수 있으나, 특정 서비스의 layout·문구·브랜드 표현·icon/visual asset·pixel-level 화면 구조를 복제하지 않는다. Sellform 고유 design system과 information architecture를 사용한다.

UX-01. 세 input mode는 하나의 상품 가져오기 진입점과 동일한 downstream product contract로 안내한다.
UX-02. 일반 판매자의 primary UI는 내부 graph/version/checkpoint/node/lineage 용어 대신 task/result 중심의 한국어 상태와 다음 행동을 제공한다.
UX-03. 동일 Commerce Creative Master에서 Detail Page, Social Kit, Video Studio, Campaign Pack이 파생되며, downstream 콘텐츠는 Detail Page PNG·JPG를 상품 source로 재분석하지 않는다.
UX-04. 결과 화면은 상품, 생성 가능한 콘텐츠, 생성 결과, 품질 상태, 편집/재생성, export의 순서를 유지한다.
UX-05. LG-14는 세 input mode부터 preview/edit와 SmartStore/Coupang export까지의 단일 판매자 workflow를 제공한다.
UX-06. LG-15는 카드형 preview와 개별 카드 수정·재생성·export를 제공한다.
UX-07. LG-16은 Master 기반의 독립 VideoProject lineage와 영상 preview/edit/export 경험을 제공한다.
UX-08. LG-17은 하나의 상품 workspace에서 Detail Page, Social Kit, Video Project를 통합 관리한다.
UX-09. 경쟁 제품은 UX 원칙만 참고하고 Sellform 고유 design system과 information architecture를 유지한다.

## 6. 시스템 계층

| 계층 | 책임 |
| --- | --- |
| Experience | 입력, 승인, 진행률, 스토리보드, 결과, 대화형 편집, 다운로드 |
| LangGraph Runtime | 노드 순서, 조건 분기, interrupt/resume, checkpoint, 재작업 |
| Intelligence | 카테고리 분류, 전략, 카피, Creative Brief, Prompt Compiler, QA 판단 |
| Media | OCR, 자산 분류, 컷아웃, 이미지 provider, 정체성·안전 검사 |
| Composition | 디자인 토큰, HTML/CSS section renderer, 미리보기, 이미지 캡처 |
| Domain Data | source/truth/confirmation/master, 사실, Prompt Pack, artifact version, job, page version, export history |
| Operations | durable worker, outbox, lease, recovery sweep, 비용·로그·메트릭 |

## 7. LangGraph 최종 구조

### 7.1 루트 그래프

```text
START
  → bootstrap_run
  → input_router
  → product_source_snapshot
  → input_review_interrupt?
  → discovery_subgraph
  → product_truth
  → seller_confirmation_interrupt? / evidence_review_interrupt?
  → category_intelligence
  → creative_brief_compiler
  → commerce_creative_master
  → commerce_planning_subgraph
  → planning_review_interrupt
  → generation_gate
      ├─ defer → generation_pending_interrupt
      ├─ existing_only → assembly_qa_subgraph
      └─ approve → image_generation_subgraph
  → image_review_interrupt?
  → assembly_qa_subgraph
      ├─ COPY_REWORK → copywriting
      ├─ PLAN_REWORK → page_planning
      ├─ VISUAL_REWORK → visual_planning / prompt compiler
      ├─ IMAGE_REWORK → 해당 장면 생성
      ├─ SELLER_REVIEW → final_review_interrupt
      └─ PASS → finalize_version
  → conversational_edit_loop?
  → export
  → END
```

### 7.2 11개 전문 에이전트

| 번호 | 에이전트 | 최종 책임 |
| --- | --- | --- |
| 1 | Input Router | 입력 유형·누락·라우팅 결정 |
| 2 | Source Collection | 승인 자료 수집과 실패·권리 상태 기록 |
| 3 | Product Understanding | OCR·판매자 정보·사진으로 승인 후보 사실과 정체성 요소 생성 |
| 4 | Reference Analysis | 참고 자료의 구조·스타일을 분석하되 복제 위험을 차단 |
| 5 | Sales Strategy | Category Prompt Pack과 Creative Brief로 구매 설득 전략 생성 |
| 6 | Page Planning | 채널·전략에 맞는 섹션 순서와 목적 생성 |
| 7 | Copywriting | 승인 사실에 연결된 한국어 카피와 비사실 서사 생성 |
| 8 | Visual Planning | 장면 구성·레이아웃·이미지 필요 여부와 시각 방향 생성 |
| 9 | Image Generation | 장면별 prompt 실행, 결과 수집, 정체성·안전 검증 |
| 10 | Page Assembly | 승인 카피·자산·디자인 토큰을 canonical page로 조립 |
| 11 | QA Review | 사실·정책·정체성·디자인·출력 검사와 재작업 라우팅 |

11개 역할을 유지하되 다음은 독립된 계약을 가진 내부 노드로 구현한다.

- `category_classifier`
- `prompt_pack_resolver`
- `creative_brief_compiler`
- `visual_prompt_compiler`
- `assembly_prompt_compiler`
- `edit_intent_router`
- `quality_evaluator`

각 미세 작업을 별도 자율 에이전트로 늘리지 않는다. 새 에이전트 수가 아니라 검증 가능한 artifact 계약을 우선한다.

## 8. 프롬프트 지능 아키텍처

### 8.1 프롬프트 우선순위

프롬프트는 다음 순서로 합성하며 상위 규칙이 하위 규칙보다 항상 우선한다.

```text
System Safety Policy
  > Approved Facts and Legal Policy
  > Product Identity Lock
  > Channel Pack
  > Category Prompt Pack
  > Seller Creative Direction
  > Product Creative Brief
  > Section/Scene Instruction
  > Provider-specific Adapter
```

LLM은 이 우선순위를 바꾸거나 system policy·금지 표현을 새로 작성할 수 없다.

### 8.2 Category Prompt Pack

`CategoryPromptPackVersion`은 최소 다음 필드를 가진다.

```text
pack_id / version / status / category_path / locale
classification_rules
buyer_psychology
recommended_narrative_patterns
required_sections / optional_sections
copy_tone / visual_tone / palette_hints
recommended_scene_types
required_fact_types
forbidden_claims / caution_rules
channel_overrides
prompt_fragments
evaluation_score / golden_dataset_version
created_by / approved_by / created_at
content_hash
```

상태는 `draft_generated → validation_pending → approved → active → deprecated`다.

PRM-01. LLM은 새 카테고리 pack 초안을 제안할 수 있지만 자동으로 전역 `active` 상태로 승격할 수 없다.  
PRM-02. 실행 시 승인된 최신 pack을 사용하고, 없으면 `other` pack으로 진행한다.  
PRM-03. 새로운 분류 결과는 해당 실행의 임시 product instruction으로 사용할 수 있지만 운영자 승인 전 다른 프로젝트에 재사용하지 않는다.  
PRM-04. 최초 범위는 생활용품, 뷰티, 식품, 패션, 전자제품과 `other`다.  
PRM-05. pack 변경은 기존 결과를 덮어쓰지 않고 새 버전을 만든다.

### 8.3 Channel Pack

채널 규격은 카테고리와 분리한다. 쿠팡·스마트스토어 pack은 다음을 포함한다.

- 캔버스 폭, 파일 형식, 분할 규칙, 최대 높이·용량
- 금지·필수 고지와 문구 규칙
- 권장 섹션 길이와 모바일 가독성
- 출력 파일명과 ZIP manifest

### 8.4 Product Creative Brief

`ProductCreativeBriefVersion`은 제품별 생성 방향의 단일 기준이다.

```text
approved_fact_snapshot_id / hash
category_prompt_pack_version_id
channel_pack_version_id
target_audience
customer_problem / desired_outcome
positioning / selling_points
fact_claim_map
seller_creative_direction
desired_mood / visual_keywords
identity_lock
narrative_arc
section_intents
required_scenes / forbidden_scenes
copy_guardrails / visual_guardrails
estimated_generation_scope
input_hash / prompt_hash / output_hash
```

PRM-06. 판매자 입력은 `fact_candidate`와 `creative_direction`으로 분리한다.  
PRM-07. Creative Brief는 승인 사실을 수정하지 않고 ID로 참조한다.  
PRM-08. 판매자가 선택한 분위기·타깃·강조 방향은 사실 검증 과정에서 삭제하지 않는다.  
PRM-09. 동일 입력·pack·prompt version의 mock 실행은 동일 output hash를 만든다.

### 8.5 Visual Prompt Compiler

각 장면은 공통 프롬프트 한 개가 아니라 독립된 `ScenePromptVersion`을 가진다.

```text
scene_id / section_id / scene_type / objective
approved_fact_ids
reference_asset_ids / reference_hash
identity_constraints
composition / camera / lighting / background
palette / material / negative_constraints
text_policy
provider / model / size / quality
prompt_version / prompt_hash
expected_cost
```

PRM-10. HERO, 사용 장면, 기능, 소재, 구성품, 크기, 사용 방법, 구매 유도 장면을 구분한다.  
PRM-11. 제품 형태·색상·버튼·포트·구성품·로고 정책을 모든 관련 장면에 주입한다.  
PRM-12. 기본 `text_policy`는 `no_rasterized_copy`이며 생성 이미지에 한국어 본문·사양표를 넣지 않는다.  
PRM-13. provider별 차이는 adapter에서 처리하고 canonical scene prompt는 provider 중립적으로 보존한다.

### 8.6 리뷰·레퍼런스 전용 입력

리뷰와 레퍼런스는 목적과 신뢰도가 다르므로 서로 다른 입력 영역, schema와 provenance를 사용한다.

REV-01. 리뷰 입력은 XLSX·CSV·TXT 업로드, 직접 붙여넣기와 허용된 수집 자료를 지원한다.  
REV-02. 리뷰 분석은 반복 불만, 구매 이유, 자주 쓰는 표현과 추정 타깃을 구조화한다.  
REV-03. 리뷰에 나온 효능·수치·인증·구성은 판매자가 확인하기 전 승인 사실로 승격하지 않는다.  
REV-04. 리뷰 원문과 분석 결과는 출처, 수집 시각, 동의·권리 상태와 content hash를 가진다.  
REV-05. 레퍼런스 입력은 상세페이지 URL, 긴 이미지, 복수 이미지, PDF 기획안과 텍스트 방향을 지원한다.  
REV-06. 사용자는 색감, 레이아웃, 섹션 흐름, 촬영 분위기, 카피 톤 중 참고할 항목을 지정할 수 있다.  
REV-07. 레퍼런스의 카피·로고·제품 이미지·고유 디자인을 복제하지 않고 추상화된 스타일·구조 신호만 사용한다.  
REV-08. 권리 미확인 레퍼런스는 분석 전용이며 최종 출력 asset으로 승격할 수 없다.  
REV-09. 리뷰·레퍼런스 분석 결과는 Product Creative Brief의 근거 artifact로 연결하고 사용 여부를 화면에 표시한다.

### 8.7 Brand Kit

`BrandKitVersion`은 워크스페이스 기본값이며 프로젝트가 선택적으로 override할 수 있다.

```text
brand_kit_id / version / status
workspace_id
brand_name / logo_asset_ids
primary_colors / secondary_colors / forbidden_colors
font_family / font_weights / fallback_fonts
copy_tone / preferred_terms / forbidden_terms
visual_keywords / forbidden_visuals
watermark_policy
asset_rights / content_hash
```

BRAND-01. 워크스페이스는 하나의 active 기본 Brand Kit version을 가질 수 있다.  
BRAND-02. 새 프로젝트는 기본 Brand Kit을 snapshot으로 참조하며 프로젝트별 override를 별도 version으로 저장한다.  
BRAND-03. 프로젝트 override는 워크스페이스 기본 Brand Kit을 수정하지 않는다.  
BRAND-04. 로고·색상·폰트·말투·선호·금지 요소와 워터마크 정책을 구조화한다.  
BRAND-05. Brand Kit은 Creative Brief, Copywriting, Visual Prompt와 Page Assembly에 동일 version으로 전달된다.  
BRAND-06. 로고와 폰트 asset은 권리·라이선스 상태가 확인돼야 최종 출력에 사용할 수 있다.  
BRAND-07. Brand Kit 변경은 카피·비주얼·조립 중 실제 영향받는 artifact만 stale 처리한다.  
BRAND-08. Brand Kit이 없어도 카테고리 pack의 안전한 기본 디자인으로 진행할 수 있다.

## 9. 사실·창작·권리 계약

| 데이터 | 허용 용도 | 최종 사실 문구 사용 |
| --- | --- | --- |
| 승인 사실 | 전략, 카피, 표, QA | 가능 |
| 판매자 사실 후보 | 검토 화면과 확인 요청 | 승인 전 불가 |
| LLM 추론 | 질문·분류·창작 방향 | 사실 표현 불가 |
| 판매자 창작 지시 | 분위기·구도·타깃·문체 | 사실을 변경하지 않는 범위에서 가능 |
| 공급처 참고 이미지 | 분석·정체성 참고 | 권리 확인 전 최종 출력 불가 |
| 판매자 보유 이미지 | 생성 기준·최종 출력 | 권리 상태가 확인된 경우 가능 |

FACT-01. 모든 수치·효능·인증·구성·가격 카피는 승인 사실 ID를 가진다.  
FACT-02. 비사실 서사는 `narrative_non_claim`으로 명시한다.  
FACT-03. 충돌 사실은 자동 선택하지 않고 evidence review로 보낸다.  
FACT-04. 원본의 중국어·상표·QR·워터마크·가격 문구를 새 이미지나 최종 결과에 복제하지 않는다.  
FACT-05. 최종 출력에 사용되는 모든 자산은 권리 상태와 provenance를 가진다.

## 10. 이미지 생성과 정체성 보존

IMG-01. 유료 호출 전 장면 수, 모델, 장면별·총 예상 비용과 재시도 범위를 표시한다.  
IMG-02. idempotency key는 최소 `project_id + scene_id + prompt_version + reference_hash + attempt`를 포함한다.  
IMG-03. 동일 key의 성공·진행 작업은 중복 dispatch하지 않는다.  
IMG-04. worker는 durable queue 또는 DB outbox·lease로 실행하며 daemon thread만으로 내구성을 주장하지 않는다.  
IMG-05. 서버 시작 시 queued/running lease 만료 작업을 복구한다.  
IMG-06. 승인·실패·재생성은 장면별이며 한 장면 승인으로 전체 장면이 승인되지 않는다.  
IMG-07. 기본 재시도는 실패 장면만 대상으로 하고 성공·승인 장면은 보존한다.  
IMG-08. API 키 없음, 잔액·한도, timeout, provider safety, 정체성 불일치, OCR 오염, 권리 차단을 구분한다.  
IMG-09. 직접 업로드 이미지는 asset picker로 선택하며 사용자가 raw asset ID를 입력하지 않는다.  
IMG-10. 승인되지 않은 이미지와 공급처 참고 이미지는 Page Assembly 입력이 될 수 없다.

정체성 검사는 최소 형태, 색상, 버튼·포트, 구성품, 로고 정책, 비정상 텍스트, 제품 잘림을 다룬다. 자동 점수가 임계값 미만이면 최종 결과로 승격하지 않고 판매자 검수로 보낸다.

## 11. Page Assembly와 디자인 시스템

### 11.1 Hybrid Composition

최종 페이지는 다음 레이어를 조립한다.

1. 승인된 원본 또는 생성 제품 이미지
2. 배경·장식·마스크·그라디언트
3. 정확한 한국어 제목·본문·사양·고지
4. 아이콘·구분선·카드·표
5. 채널별 여백·폭·분할 경계

ASM-01. canonical page schema는 section, copy version, asset version, layout token, channel override를 ID로 참조한다.  
ASM-02. 미리보기와 다운로드는 동일 `DetailPageVersion`을 렌더링한다.  
ASM-03. Page Assembly prompt는 직접 HTML을 자유 생성하는 지시가 아니라 승인된 component와 token을 선택하는 구조화 계약이다.  
ASM-04. 이미지 없는 정보 섹션은 HTML/CSS로 만들 수 있어야 한다.  
ASM-05. 생성 이미지가 없는 상태에서도 원본 사진과 정보형 그래픽으로 안전한 페이지를 완성할 수 있다.  
ASM-06. 한국어 카피는 이미지와 분리된 편집 가능한 텍스트 레이어로 유지한다.  
ASM-07. 첫 출시에서는 검증된 3개 디자인 방향을 제공하고 무제한 자유 레이아웃 생성을 하지 않는다.

권장 초기 디자인 방향은 `안전 정보형`, `이미지 중심형`, `균형 판매형`이다. 카테고리 pack은 방향을 추천하지만 판매자가 변경할 수 있다.

## 12. 대화형 편집과 선택적 재생성

판매자 명령은 `EditIntent`로 구조화한다.

```text
scope             # page | section | scene | copy | style | fact
target_ids
operation         # rewrite | regenerate | reorder | replace | restyle | add | remove
instruction
preserve_constraints
requires_cost_approval
affected_artifacts
```

EDT-01. 카피 수정은 기본적으로 이미지 재생성을 유발하지 않는다.  
EDT-02. 한 장면 재생성은 다른 승인 장면을 삭제하지 않는다.  
EDT-03. 사실 변경은 evidence review부터 downstream artifact를 무효화한다.  
EDT-04. 전체 스타일 변경은 Creative Brief·Visual Plan·Assembly를 갱신하되 승인 사실은 유지한다.  
EDT-05. 실행 전 변경 범위, 사라질 승인, 예상 비용을 사용자에게 보여준다.  
EDT-06. 모든 수정은 새 버전으로 저장하고 이전 버전으로 복원할 수 있다.  
EDT-07. 자연어 명령이 모호하거나 사실을 변경하려 하면 명시적 확인을 요청한다.

### 12.1 Hybrid Canvas Editor

Canvas Editor는 전체 페이지를 절대 좌표로 자유 배치하는 방식이 아니라, 채널 안정성을 지키는 section layout과 section 내부의 자유 편집을 결합한다.

CANVAS-01. 섹션 순서·높이·표시 상태를 변경하고 섹션 내부 요소를 이동·크기 조절할 수 있다.  
CANVAS-02. 텍스트, 이미지, 배경, 마스크, 아이콘과 장식 요소를 직접 편집·교체할 수 있다.  
CANVAS-03. 레이어 순서, 요소 잠금, 그룹, 복제와 삭제를 제공한다.  
CANVAS-04. 정렬 가이드, 간격 표시, snap, 안전 영역과 잘림·겹침 경고를 제공한다.  
CANVAS-05. undo/redo, 자동 저장, 충돌 없는 draft와 이전 page version 복원을 제공한다.  
CANVAS-06. 선택 요소를 편집 컨텍스트로 고정한 뒤 채팅으로 카피 수정·이미지 재생성·스타일 변경을 요청할 수 있다.  
CANVAS-07. 모바일·쿠팡·스마트스토어·HTML preview를 전환해 채널별 결과를 확인한다.  
CANVAS-08. 채널 안전 영역을 벗어난 변경은 경고하고 export 전 QA에서 차단한다.  
CANVAS-09. Canvas 저장 결과와 preview·JPG·PNG·HTML은 동일한 canonical page version에서 렌더링한다.

## 13. QA와 Golden Dataset

QA는 단일 점수 대신 영역별 report와 routing code를 만든다.

| 영역 | 검사 내용 |
| --- | --- |
| Fact | 승인 사실 추적, 수치·효능·인증·금지 표현 |
| Identity | 형태, 색상, 버튼·포트, 구성품, 로고 정책 |
| Copy | 한국어 맞춤법, 중복, 과장, 가독성, CTA |
| Visual | 잘림, 해상도, 반복 장면, 배색, 대비, 일관성 |
| Layout | 모바일 폭, 위계, 여백, 섹션 흐름, 표 가독성 |
| Rights | 출처, 권리 상태, 워터마크·QR·상표 복제 |
| Channel | 파일 형식, 폭, 높이, 용량, 분할 경계, 필수 고지 |
| Parity | 미리보기·편집기·다운로드 버전 일치 |

QA-01. 최종 사실성 치명 오류와 금지 표현은 0건이어야 한다.  
QA-02. category classifier는 Golden Dataset에서 목표 정확도 95% 이상 또는 `other` 안전 폴백을 만족해야 한다.  
QA-03. 생성 이미지의 정체성·OCR·잘림 검사는 설정된 임계값을 통과하거나 판매자가 명시적으로 승인해야 한다.  
QA-04. 동일 page version의 preview와 export는 section/copy/asset manifest가 완전히 일치해야 한다.  
QA-05. QA 재작업은 `COPY_REWORK`, `PLAN_REWORK`, `VISUAL_REWORK`, `IMAGE_REWORK`, `SELLER_REVIEW`, `BLOCKED_POLICY`, `PASS` 중 하나를 반환한다.  
QA-06. 자동 재작업은 노드별 최대 2회이며 초과 시 사용자 검수로 보낸다.

### 13.1 Visual Quality Bar

다음 치명 오류는 점수와 관계없이 최종 완료를 차단한다.

- 제품 형태·색상·버튼·포트·구성품 왜곡
- 승인되지 않은 수치·효능·인증·가격 claim
- source/evidence 범위를 벗어난 unsupported claim 또는 prohibited inference
- 필수 seller confirmation 누락 또는 확인되지 않은 권리
- source snapshot과 결과 사이의 product identity drift
- 깨진 한글·중국어·워터마크·QR·타사 로고
- 제품·문구 잘림, 겹침 또는 읽을 수 없는 대비
- 권리 미확인 asset의 최종 사용
- 미리보기와 다운로드의 version·manifest 불일치

품질 점수는 다음 가중치로 100점을 구성한다.

| 영역 | 배점 |
| --- | ---: |
| 제품 정체성 | 20 |
| 사실·정책 안전성 | 20 |
| 레이아웃·시각적 완성도 | 20 |
| 한국어 카피·가독성 | 15 |
| Brand Kit 일치 | 10 |
| 장면 다양성·섹션 흐름 | 10 |
| 채널 출력 품질 | 5 |

VQB-01. 치명 오류가 1건이라도 있으면 최종 완료와 export 승격을 차단한다.  
VQB-02. 전체 점수 85점 이상이고 모든 개별 영역이 70점 이상이어야 자동 PASS가 가능하다.  
VQB-03. 점수와 검사 근거, 대상 section·scene·asset·copy ID를 versioned QA report에 저장한다.  
VQB-04. 기준 미달 시 문제 영역에 연결된 카피·장면·레이아웃만 재작업한다.  
VQB-05. 자동 재작업은 최대 2회이며 계속 미달이면 비교 후보와 문제 설명을 판매자에게 제공한다.  
VQB-06. 빠른 생성 모드도 Visual Quality Bar를 생략할 수 없다.  
VQB-07. Golden Dataset의 자동 지표와 사람 평가 rubric을 함께 사용해 evaluator와 threshold를 교정한다.  
VQB-08. 모델·Prompt Pack·renderer 변경은 배포 전에 기준 버전 대비 품질 회귀를 통과해야 한다.
VQB-09. QA report는 `input_mode`, source/truth/confirmation/master version ID, `source_fidelity`, `prohibited_inference_count`, `unknown_fact_count`, `clarification_count`를 frozen metadata로 포함한다.
VQB-10. unsupported claim, prohibited inference, missing seller confirmation, unconfirmed rights와 product identity drift는 점수로 상쇄할 수 없는 critical finding이다.

Golden Dataset은 용도를 분리해 versioned contract로 관리한다.

- Contract Golden Dataset v1은 TASK-12.1에서 확정한 기존 LG-10/LG-11 frozen version·asset·manifest·copy·channel 회귀 계약이다. trusted hash와 15개 case를 수정하거나 새 input mode 요구사항을 소급 적용하지 않는다.
- Product Intake Golden Dataset v2는 TASK-12.1R에서 생활용품·뷰티·식품·패션·전자제품 5개 카테고리와 `owned_product_url`·`photo_only`·`manual` 3개 입력 모드의 정확히 15개 case를 별도 version으로 만든다.
- v2 각 case는 source/truth/confirmation/master identity, source fidelity, 허용 evidence, prohibited inference, unknown fact, 최대 3개 clarification, rights와 기대 downstream contract를 포함한다.
- LG-12 evaluator와 threshold 작업은 LG-12I 및 Product Intake Golden Dataset v2가 완료된 뒤 시작한다.

## 14. 승인·비용·API 대기 계약

최소 interrupt는 다음과 같다.

- `input_review`
- `evidence_review`
- `planning_review`
- `cost_approval`
- `generation_pending`
- `image_review`
- `final_review`

HITL-01. 모든 interrupt와 resume payload는 schema version과 동일 thread ID를 가진다.  
HITL-02. 새로고침 후 동일 pending interrupt와 사용자 행동을 복원한다.  
HITL-03. API 미설정·잔액 부족은 실패 이미지로 대체하지 않고 `generation_pending` 또는 복구 가능한 오류로 보존한다.  
HITL-04. `generation_pending`에서 defer하면 provider 호출과 비용은 0이다.  
HITL-05. 승인 버튼의 성공·진행·실패·다음 interrupt를 UI가 명확히 표시한다.  
HITL-06. 승인 응답이 현재 interrupt와 맞지 않으면 409와 복구 안내를 반환한다.

## 15. 버전·상태·멱등 계약

graph state에는 JSON 직렬화 가능한 작은 상태와 artifact ID/hash만 둔다. 원본 이미지 bytes, ORM session, API client, secret, 전체 OCR 원문은 넣지 않는다.

필수 버전 체인은 다음과 같다.

```text
ProductSourceSnapshotVersion
  → ProductTruthVersion
  → SellerConfirmationVersion
  → FactSnapshot + CategoryPromptPackVersion + ChannelPackVersion + BrandKitVersion
  → ProductCreativeBriefVersion
  → CommerceCreativeMasterVersion
  → SalesStrategyVersion
  → PagePlanVersion
  → CopySetVersion
  → VisualPlanVersion
  → ScenePromptVersion
  → GeneratedAssetVersion
  → DetailPageVersion
  → ExportVersion

CommerceCreativeMasterVersion
  ├─ DetailPageVersion
  ├─ SocialKitVersion
  ├─ VideoProjectVersion
  └─ CampaignContentPackVersion
```

OPS-01. 각 artifact는 input hash, prompt/pack version, output hash, creator run ID를 기록한다.  
OPS-02. 상위 artifact 변경 시 영향받는 하위 artifact만 stale 처리한다.  
OPS-03. 같은 idempotency key로 재요청해도 외부 호출·DB version·비용 기록은 하나만 생성된다.  
OPS-04. checkpoint와 업무 projection이 불일치하면 checkpoint event로 projection을 재구축할 수 있다.

## 16. 운영·보안·관측성

OPS-05. graph version, run/thread/checkpoint ID, 노드 시작·완료·중단·재개·실패를 기록한다.  
OPS-06. provider/model/token/장면/attempt별 예상·실제 비용과 latency를 기록한다.  
OPS-07. secret, 원본 고객 자료, signed URL은 checkpoint와 일반 로그에 기록하지 않는다.  
OPS-08. 모든 graph, asset, prompt pack, page, export 접근에 workspace·actor 권한을 검사한다.  
OPS-09. worker lease, outbox, recovery sweep, dead-letter와 운영자 재시도 도구를 제공한다.  
OPS-10. 사용자는 실패 코드가 아니라 원인과 다음 행동을 한국어로 확인한다.
OPS-11. intake mode, source/truth/confirmation/master version, source fidelity, unknown/prohibited inference/clarification count의 상태 전이를 event로 기록한다.
OPS-12. LG-13은 input mode별 intake 성공률·확인 요청 수·unsupported inference 차단률·source fidelity·완료 시간·실패 원인을 측정하되 이를 Visual Quality Bar 점수에 합산하지 않는다.

### 16.1 생성 시간·응답성 목표

다음은 정상 provider 상태와 사용자 승인 대기 시간을 제외한 빠른 생성 모드의 서로 다른 단계별 제품 목표다. provider 장애 시 거짓 완료 시간을 약속하지 않고 지연 원인과 갱신된 예상 시간을 표시한다.

- product understanding p90 <= 60초
- planning/copy draft p90 <= 3분
- first usable detail-page draft p90 <= 5분
- high-quality final p90 <= 10~15분
- 정상 실행의 90% <= 20분

`first usable detail-page draft`는 사용자가 실제로 보고 수정 가능한 상세페이지 초안이다. `high-quality final`은 생성 이미지, QA, 최종 승격까지 완료된 결과다. 따라서 3~5분은 모든 생성 이미지와 최종 QA까지 포함한 final 보장이 아니다.

SLO-01. product understanding의 p90 목표 시간은 60초 이하다.
SLO-02. planning/copy draft의 p90 목표 시간은 3분 이하다.
SLO-03. high-quality final의 p90 목표 시간은 10~15분 이하다.
SLO-04. 정상 provider 조건에서 실행의 90%가 20분 이내 완료되도록 측정·개선한다.  
SLO-05. 예상 시간을 초과하면 현재 노드·장면, 지연 원인과 갱신 ETA를 표시한다.  
SLO-06. 완료된 섹션은 전체 실행 종료 전부터 안전한 부분 미리보기로 제공한다.  
SLO-07. 실패 장면만 최대 2회 자동 재시도하며 성공·승인 장면은 다시 생성하지 않는다.  
SLO-08. 2회 실패 후 기존 사진·정보형 그래픽 폴백과 대기 중 하나를 사용자가 선택한다.
SLO-09. first usable detail-page draft의 p90 목표 시간은 5분 이하다.

### 16.2 Progressive generation 계약

Progressive generation은 seller-owned asset, 정보형 section, 이미 완료된 approved scene만으로 first usable frozen draft를 만든다. 아직 생성 중인 고품질 scene 때문에 first draft 전체를 기다리지 않으며, first usable draft는 immutable `DetailPageVersion`으로 freeze한다.

이후 고품질 scene이 완료되고 QA를 통과하면 기존 source frozen version을 수정하지 않고 LG-10/LG-11 lineage contract로 새 immutable child `DetailPageVersion`을 생성한다. 이 child version은 완료된 scene만 선택적으로 교체·reassembly하며 사용자는 이전 version으로 restore할 수 있다.

Quick mode는 확실한 source-backed fact와 안전한 deterministic image QA `PASS` scene을 자동 채택·반영할 수 있고 모든 중간 장면 승인을 강제하지 않는다. fact ambiguity, rights, identity, safety, cost, critical quality 문제는 HITL interrupt로 전환한다. Expert mode는 기존 product understanding, planning, storyboard, scene review 등 단계별 검토를 제공하며 기존 LG-7/LG-9 검수 기능을 유지한다.

## 17. API와 화면 계약

핵심 API는 resource 중심으로 통일한다.

- graph run 생성·조회·history·events·resume·retry·cancel
- pending review 조회와 versioned response
- category pack 조회·제안·평가·승인·활성화
- Creative Brief 조회·수정·승인
- scene prompt·image job·asset review
- edit command preview·apply·rollback
- page version·QA report·export

화면은 다음 순서를 제공한다.

1. 상품 입력
2. 사실·증거 확인
3. 카테고리·Creative Brief 확인
4. 스토리보드·카피·비주얼 기획 확인
5. 이미지 비용·대기·검수
6. 완성 페이지와 QA
7. 자연어·직접 편집
8. 채널별 다운로드와 이력

### 17.1 사용자용 HTML 출력

HTML 출력은 내부 renderer 구현물이 아니라 사용자가 실제 쇼핑몰과 개발 환경에서 사용할 수 있는 제품 산출물이다.

HTML-01. 카페24·자사몰 등에 붙여넣을 수 있는 정제된 HTML 코드 복사를 제공한다.  
HTML-02. HTML, CSS, 이미지, 폰트 manifest와 사용 안내를 포함한 ZIP 다운로드를 제공한다.  
HTML-03. ZIP은 만료되는 signed URL에 의존하지 않고 필요한 승인 asset 파일을 포함한다.  
HTML-04. 스크립트, event handler, 위험 URL과 채널이 지원하지 않는 태그·스타일을 sanitization한다.  
HTML-05. 채널 제약으로 표현할 수 없는 요소는 내보내기 전에 경고하거나 안전한 정적 이미지로 변환한다.  
HTML-06. HTML 코드, ZIP, preview와 이미지 출력은 동일 DetailPageVersion과 asset manifest를 사용한다.  
HTML-07. 내보낸 ZIP의 `index.html`은 외부 API 없이 로컬 preview에서 열려야 한다.  
HTML-08. export history에서 동일 version의 HTML과 이미지 패키지를 다시 다운로드할 수 있다.

### 17.2 Commerce Creative Master 파생 산출물

상세페이지 이후의 콘텐츠는 같은 상품을 다시 입력하거나 상세페이지 이미지를 재분석하지 않고 Commerce Creative Master에서 파생한다. LG-14 Detail Page Beta까지만 닫고, 소셜·영상·캠페인 구현은 각각 LG-15~LG-17에서 진행한다.

SOCIAL-01. `SocialKitVersion`은 source master ID/version/hash, 대상 채널, format, copy/asset/Brand Kit reference와 output hash를 고정한다.
SOCIAL-02. 소셜 카드·피드·스토리 소재는 master의 승인 fact와 rights-confirmed asset만 사용한다.
SOCIAL-03. 소셜 카피가 새 사실이나 효능을 만들지 않으며 fact/evidence provenance를 유지한다.
SOCIAL-04. 상세페이지 PNG·JPG를 상품 사실 source로 재분석하지 않는다.
SOCIAL-05. 채널별 크기·safe area·copy 길이·export parity를 versioned contract로 검증한다.
SOCIAL-06. 동일 master와 template/evaluator version의 fake 실행은 결정론적 결과를 만든다.

VIDEO-01. `VideoProjectVersion`은 source master ID/version/hash, storyboard, shot/scene, audio/caption, asset reference와 output hash를 고정한다.
VIDEO-02. 영상의 상품 claim과 자산은 master의 승인 fact·rights contract를 따른다.
VIDEO-03. 영상 생성·재생성 비용은 장면별 명시 승인과 기존 durable outbox/idempotency 계약을 따른다.
VIDEO-04. 상세페이지 이미지가 아니라 master의 scene/asset/brief reference에서 영상 장면을 파생한다.
VIDEO-05. 자막과 한국어 카피는 편집 가능한 정확한 text layer로 유지한다.
VIDEO-06. preview와 최종 영상·자막·thumbnail은 동일 frozen VideoProjectVersion을 사용한다.

CAMPAIGN-01. `CampaignContentPackVersion`은 하나의 master에서 선택된 DetailPage/SocialKit/VideoProject version을 불변 참조한다.
CAMPAIGN-02. 캠페인 팩은 채널·기간·메시지 목적을 기록하되 승인 fact와 Brand Kit을 수정하지 않는다.
CAMPAIGN-03. 일부 파생 산출물 실패가 다른 승인 산출물을 삭제하거나 재생성하지 않는다.
CAMPAIGN-04. 팩 manifest와 다운로드 이력은 포함 artifact의 version/hash parity를 검증한다.
CAMPAIGN-05. 캠페인 생성으로 원본 master나 과거 frozen 파생 version을 수정하지 않는다.

## 18. 테스트 전략

### 18.1 계약 테스트

- 모든 node가 허용된 state delta만 반환
- mock/real provider의 동일 output schema
- prompt priority와 fact/creative separation
- Category Prompt Pack·Creative Brief·Scene Prompt schema와 hash

### 18.2 그래프 테스트

- 조건 분기, 모든 interrupt/resume, QA 재작업, retry limit
- API 없음 → 대기 → 같은 thread 재개
- 한 장면 수정 시 해당 장면만 재생성
- 사실 수정 시 evidence부터 downstream stale 처리

### 18.3 내구성 테스트

- 서버·worker 강제 종료와 lease 복구
- 중복 클릭·webhook·poll 응답에도 중복 청구 0건
- checkpoint projection rebuild
- 진행·성공 장면 보존과 실패 장면 재시도

### 18.4 시각·출력 테스트

- Golden Dataset 자동 평가
- 이미지 identity/OCR/crop 검사
- 한국어 text layer와 이미지 분리
- preview·JPG·PNG·ZIP manifest parity
- Playwright로 실제 승인·편집·다운로드 흐름 검증

외부 API가 필요한 테스트는 비용 승인 표식을 가진 별도 suite로 분리한다. 핵심 완료 판정은 fake provider로도 worker·resume·검수·조립·QA 전체를 증명해야 한다.

## 19. 완료 정의

다음 항목이 모두 충족되어야 V2.1을 완료로 판정한다.

1. 신규 생성의 모든 쓰기 경로가 compiled LangGraph를 통과한다.
2. 최초 5개 카테고리와 `other` Prompt Pack이 versioned·평가·승인된다.
3. 판매자 사실과 창작 방향이 분리되고 Creative Brief에 보존된다.
4. 장면별 prompt와 제품 정체성 lock이 버전으로 추적된다.
5. API 미준비 상태에서 계획을 보존하고 같은 run을 재개한다.
6. durable worker와 idempotency가 서버 재시작·중복 응답에서 중복 비용을 막는다.
7. 장면별 이미지 승인·실패·재생성·직접 업로드가 동작한다.
8. 정확한 한국어 카피를 HTML/CSS로 조립하고 이미지 안의 한글 생성에 의존하지 않는다.
9. 자연어 부분 수정이 영향받은 노드·장면만 재실행한다.
10. QA PASS와 판매자 최종 승인 전에는 최종 버전을 만들지 않는다.
11. Golden Dataset 품질 기준과 보안·권한·비용 회귀 테스트가 통과한다.
12. 미리보기·편집기·JPG·PNG·ZIP가 같은 DetailPageVersion을 가리킨다.
13. 빠른 생성·단계별 검토가 같은 안전·품질 gate와 결과 계약을 사용한다.
14. Brand Kit과 리뷰·레퍼런스가 Creative Brief·카피·비주얼에 provenance와 함께 반영된다.
15. Hybrid Canvas의 저장 결과와 HTML·이미지 출력이 동일 page version으로 재현된다.
16. 생성 시간 SLO와 Visual Quality Bar가 운영 지표와 release gate로 검증된다.
17. 요구사항 추적표의 미구현·부분 구현 항목이 0건이다.
18. 각 Sprint의 requirement ID, 변경 파일, 실행 테스트·로그, git diff 검토, severity/verdict, 필요한 수동·회귀 검증과 다음 Sprint 진입 판정이 추적 가능하다. 별도 코드리뷰 Markdown 문서는 Sprint 기획이나 명시적 요청이 요구할 때만 만든다.
19. 세 입력 모드가 source/truth/confirmation/Product Creative Brief/master 불변 체인으로 수렴하고 unsupported inference와 미확인 권리를 차단한다.
20. LG-14 Detail Page Beta는 `owned_product_url`, `photo_only`, `manual` 3개 input mode × SmartStore, Coupang 2개 channel의 총 6개 mandatory production Golden Path를 통과한다. 각 조합은 product intake → seller confirmation → Commerce Creative Master → planning → detail page → Quality Bar → JPG/PNG/ZIP을 검증하고 HTML은 사용자용 output parity 공통 contract로 별도 검증한다. 소셜·영상·캠페인은 LG-15~LG-17에서 같은 master를 재사용한다.

## 20. 구현 범위 통제 규칙

- 새 스프린트 구현 전 이 문서의 요구사항 ID를 구현 계획에 복사한다.
- 코드리뷰는 “구현됨” 서술만으로 통과하지 않는다. 각 ID마다 코드와 실행된 테스트 증거가 필요하다.
- 테스트가 provider·worker·resume을 monkeypatch로 우회하면 해당 실제 경로의 완료 증거로 사용할 수 없다.
- 프런트 버튼은 렌더링만으로 완료 처리하지 않고 네트워크 요청·상태 전이·새로고침 복구 E2E가 필요하다.
- 미완료가 발견되면 새 기능 Sprint로 넘어가기 전에 `R` 보완 Sprint로 닫는다.
- 기획 변경은 이 문서를 직접 덮어쓰지 않고 변경 사유와 요구사항 diff를 기록한다.
- Sprint 완료 증거는 requirement ID, 변경 파일, 실행 명령·로그, diff 검토, severity/verdict, 수동·회귀 검증과 다음 Sprint 판정을 포함한다. 별도 리뷰 문서 생성 자체를 완료 조건으로 강제하지 않는다.
