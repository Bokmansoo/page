# Sellform Sprint 14 Template Quality Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 패션·뷰티·식품·리빙의 실제 또는 현실적인 소싱 상품 4개로 `카테고리 기본형`과 `문제 해결형` 상세페이지를 비교하여, 카테고리별 권장 템플릿과 다음 고도화 우선순위를 증거 기반으로 결정한다.

**Architecture:** Sprint 14는 새 기능을 추가하는 스프린트가 아니라, Sprint 10~13의 사실 추출·이미지 텍스트·내러티브 템플릿을 실제 입력 자료에 적용하는 품질 검증 스프린트다. 각 상품은 같은 확정 사실 카드와 이미지를 사용해 두 템플릿을 생성하고, 사실성·카테고리 적합성·설득 구조·모바일 가독성·판매처 출력 적합성을 같은 평가표로 기록한다. 발견한 Blocker 또는 Major 결함은 재현 증적만 남기고 별도 보완 스프린트로 분리한다.

**Tech Stack:** Sellform Next.js UI, FastAPI API, Chrome, local filesystem documentation, 쿠팡·네이버 스마트스토어 업로드 규격 문서.

---

## 0. 범위와 제외 범위

### 포함

- Fashion, Beauty, Food, Living 카테고리에서 각 1개 상품을 검증한다.
- 각 상품의 원문 스펙·공급처 이미지·출처를 기록한다.
- 사실 카드 자동 생성 후 사람이 확인한 `confirmed` 사실만 두 템플릿의 공통 입력으로 사용한다.
- `category_default`와 `problem_solution` 결과를 비교한다.
- 모바일 화면, 공개 미리보기, 이미지 export까지 확인한다.
- 상품·템플릿별 판정과 다음 Sprint 후보를 결정 기록으로 남긴다.

### 제외

- 쿠팡·스마트스토어 실제 상품 등록 또는 계정 자동화.
- 신규 OCR/LLM 제공자 연결.
- Figma·Notion·Google Drive MCP 연동.
- 결과가 마음에 들지 않는다는 이유만으로 즉시 템플릿 기능을 확장하는 작업.

## 1. 산출물과 파일 구조

| 파일 | 책임 |
| --- | --- |
| `docs/testing/2026-06-24-sellform-sprint-14-validation-pack.md` | 검증 상품 4개와 입력 자료·리스크·목표 판매처 정의 |
| `docs/testing/2026-06-24-sellform-sprint-14-template-comparison-log.md` | 상품별 두 템플릿 생성 결과와 평가 기록 |
| `docs/testing/2026-06-24-sellform-sprint-14-baseline-test-log.md` | Sprint 시작/종료 시 자동 테스트와 프론트 빌드 증적 |
| `docs/reviews/2026-06-24-sellform-sprint-14-quality-review.md` | 계획 대비 결과, 발견 이슈와 최종 판정 |
| `docs/troubleshooting/2026-06-24-sellform-sprint-14-template-validation.md` | 재현 가능한 장애·품질 문제와 복구 절차 |
| `docs/decisions/2026-06-24-sellform-template-recommendation.md` | 카테고리별 권장 템플릿과 Sprint 15 후보 결정 |
| `docs/releases/2026-06-24-sellform-sprint-14.md` | 검증 범위와 알려진 제한을 요약한 릴리스 노트 |
| `memory/2026-06-24-sellform-sprint-14-lessons.md` | 반복 교훈과 다음 작업의 판단 기준 |

## 2. 공통 평가 기준

각 항목은 `통과`, `수정 후 사용 가능`, `사용 불가` 중 하나로 기록한다.

| 항목 | 통과 기준 |
| --- | --- |
| 사실성 | 본문 카피와 `associated_fact_ids`가 confirmed 사실과 모순되지 않는다. |
| 카테고리 적합성 | Fashion/Beauty/Food/Living의 금지·주의 표현을 사용하지 않는다. |
| 설득 구조 | 첫 3개 섹션 안에서 고객 문제와 상품 선택 이유가 이해된다. |
| 이미지 연계 | 업로드한 소싱 이미지가 상품 정보·카피와 혼동 없이 배치된다. |
| 모바일 가독성 | 390px 폭에서 제목·본문·버튼·이미지가 가려지거나 가로 스크롤되지 않는다. |
| 출력 적합성 | 공개 미리보기와 이미지 export가 생성되고, 링크·이미지·한글이 깨지지 않는다. |

## 3. Task 1: 시작 기준선과 검증 상품팩을 고정한다

**Files:**

- Create: `docs/testing/2026-06-24-sellform-sprint-14-baseline-test-log.md`
- Create: `docs/testing/2026-06-24-sellform-sprint-14-validation-pack.md`

- [ ] **Step 1: 시작 전 백엔드 전체 테스트를 실행한다.**

Run:

```powershell
uv run --project backend pytest -q
```

Expected: `61 passed` 이상이며 실패는 0건이다. 실제 수치와 경고 수를 baseline test log에 기록한다.

- [ ] **Step 2: 시작 전 프론트 프로덕션 빌드를 실행한다.**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected: `Compiled successfully`와 exit code 0이다. 결과를 baseline test log에 기록한다.

- [ ] **Step 3: 검증 상품팩을 작성한다.**

`docs/testing/2026-06-24-sellform-sprint-14-validation-pack.md`에 아래 4개 행을 만들고, 실행 전에 실제 선택 상품의 정보로 채운다.

| ID | 카테고리 | 선택 기준 | 필수 입력 | 목표 판매처 | 필수 확인 포인트 |
| --- | --- | --- | --- | --- | --- |
| S14-FASHION-01 | Fashion | 옵션 또는 소재 정보가 있는 잡화/의류 | 원문 스펙, 이미지 2장 이상, 출처 URL | 쿠팡·스마트스토어 | 체형 보정·효과 보장 표현이 없는가 |
| S14-BEAUTY-01 | Beauty | 성분 또는 사용법 정보가 있는 화장품 | 전성분/사용법 원문, 이미지 2장 이상, 출처 URL | 쿠팡·스마트스토어 | 치료·의학적 효능 표현이 없는가 |
| S14-FOOD-01 | Food | 원재료·구성·보관 정보가 있는 식품 | 원재료/구성 원문, 이미지 2장 이상, 출처 URL | 쿠팡·스마트스토어 | 건강·질병 효능 표현이 없는가 |
| S14-LIVING-01 | Living | 규격 또는 사용 환경 정보가 있는 리빙 상품 | 규격/사용법 원문, 이미지 2장 이상, 출처 URL | 쿠팡·스마트스토어 | 안전·내구성 보장 표현이 없는가 |

- [ ] **Step 4: 각 상품의 입력 자료 출처와 사용 권한 상태를 기록한다.**

공급처 제공 이미지인지, 직접 촬영 이미지인지, 출처 링크가 있는지, 판매용 사용 가능 여부를 상품별로 기록한다. 사용 권한이 불명확한 이미지는 검증에 쓸 수는 있어도 export/공개 발행 결과를 외부 판매에 사용하지 않는다.

## 4. Task 2: 상품별 사실 입력과 확정 상태를 만든다

**Files:**

- Modify: `docs/testing/2026-06-24-sellform-sprint-14-validation-pack.md`
- Create: `docs/testing/2026-06-24-sellform-sprint-14-template-comparison-log.md`

- [ ] **Step 1: Sellform에서 상품 프로젝트를 4개 만든다.**

각 프로젝트에 상품명·공급처 원본 링크·원문 스펙·이미지를 입력한다. 카테고리는 AI 추천 뒤 사람이 Fashion, Beauty, Food, Living으로 최종 확정한다.

- [ ] **Step 2: 사실 카드 자동 생성을 실행하고 직접 검토한다.**

각 상품에서 자동 후보를 확인하고, 원문 또는 이미지에서 근거를 다시 찾을 수 있는 사실만 `confirmed`로 변경한다. 원문 근거가 없는 후보는 `unknown` 또는 `rejected`로 둔다.

- [ ] **Step 3: 비교 로그의 공통 입력을 기록한다.**

각 상품마다 아래 양식을 작성한다.

```markdown
## S14-FASHION-01

- 상품명:
- 출처 URL:
- 이미지 권한 상태:
- 확정 사실 카드 수:
- 미확정/거절 카드 수:
- 확정 사실 요약:
- 카테고리 확정 근거:
- 광고·규정 주의사항:
```

## 5. Task 3: 두 내러티브 템플릿을 같은 조건으로 생성한다

**Files:**

- Modify: `docs/testing/2026-06-24-sellform-sprint-14-template-comparison-log.md`

- [ ] **Step 1: `카테고리 기본형`을 생성한다.**

각 상품의 page editor에서 style preset과 confirmed 사실 카드를 유지한 채 `카테고리 기본형`을 선택해 생성한다. 생성된 섹션 수, 첫 3개 섹션, 수동 수정 횟수, warnings를 비교 로그에 기록한다.

- [ ] **Step 2: `문제 해결형`을 생성한다.**

같은 상품·같은 confirmed 사실·같은 스타일에서 `문제 해결형`을 선택해 재생성한다. 아래 7개 section type이 순서대로 존재하는지 확인한다.

```text
problem_statement
main_claim
secondary_benefit
main_claim_support
benefit_list
summary_claim
product_information
```

- [ ] **Step 3: 템플릿 비교 표를 채운다.**

| 상품 ID | 템플릿 | 사실성 | 카테고리 적합성 | 설득 구조 | 수동 수정량 | 1차 판정 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S14-… | 카테고리 기본형 | 통과/수정/불가 | 통과/수정/불가 | 통과/수정/불가 | 섹션 수·문장 수 | 통과/수정/불가 | 화면·카드·문구 근거 |
| S14-… | 문제 해결형 | 통과/수정/불가 | 통과/수정/불가 | 통과/수정/불가 | 섹션 수·문장 수 | 통과/수정/불가 | 화면·카드·문구 근거 |

## 6. Task 4: 모바일·출력 품질을 확인한다

**Files:**

- Modify: `docs/testing/2026-06-24-sellform-sprint-14-template-comparison-log.md`
- Modify: `docs/troubleshooting/2026-06-24-sellform-sprint-14-template-validation.md`

- [ ] **Step 1: 390px 폭에서 두 템플릿을 확인한다.**

Chrome 개발자 도구의 responsive mode를 390px 폭으로 설정한다. 각 결과에서 가로 스크롤, 텍스트 겹침, 잘린 버튼, 깨진 한글, 이미지 비율 문제를 확인한다.

- [ ] **Step 2: 공개 미리보기와 이미지 export를 확인한다.**

각 카테고리에서 최소 한 상품은 공개 미리보기와 이미지 export를 실행한다. 링크 접근, 이미지 로딩, 한글 렌더링, export 파일 생성 여부를 기록한다.

- [ ] **Step 3: 발견 이슈를 심각도로 분류한다.**

아래 형식으로 troubleshooting 문서에 기록한다.

```markdown
### [심각도] 이슈 제목

- 재현 상품/템플릿:
- 재현 단계:
- 기대 결과:
- 실제 결과:
- 증적:
- 즉시 우회 방법:
- 후속 조치: Sprint 15 후보 / 현재 Sprint에서 해결하지 않음
```

## 7. Task 5: 결과를 판단하고 다음 Sprint를 결정한다

**Files:**

- Create: `docs/decisions/2026-06-24-sellform-template-recommendation.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-14-quality-review.md`
- Create: `docs/releases/2026-06-24-sellform-sprint-14.md`
- Create: `memory/2026-06-24-sellform-sprint-14-lessons.md`

- [ ] **Step 1: 카테고리별 권장 템플릿을 결정한다.**

결정 문서에 아래 표를 채운다. `문제 해결형`, `카테고리 기본형`, `둘 다 사용 가능`, `추가 템플릿 필요` 중 하나만 선택하고 비교 로그의 근거를 연결한다.

| 카테고리 | 권장 템플릿 | 근거 | 다음 개선 필요 여부 |
| --- | --- | --- | --- |
| Fashion |  |  |  |
| Beauty |  |  |  |
| Food |  |  |  |
| Living |  |  |  |

- [ ] **Step 2: Sprint 15 후보를 하나로 좁힌다.**

다음 후보 중 비교 로그의 반복 문제를 가장 직접적으로 해결하는 하나만 선택한다.

| 후보 | 선택 조건 |
| --- | --- |
| 실제 OCR/멀티모달 제공자 연결 | 이미지 속 스펙 누락이 반복되어 수동 입력 비용이 큰 경우 |
| 카테고리별 추가 템플릿 | 특정 카테고리에서 두 템플릿 모두 설득 구조가 부적합한 경우 |
| 카피 편집 UX 고도화 | 생성 결과는 유효하지만 사용자의 반복 수정량이 큰 경우 |
| 출력/모바일 렌더링 보완 | 카피는 유효하지만 export 또는 모바일 화면이 불안정한 경우 |

- [ ] **Step 3: 리뷰·릴리스·교훈 문서를 작성한다.**

리뷰에는 계획 대비 충족 여부와 Blocker/Major/Minor 이슈를 기록한다. 릴리스 노트에는 검증한 범위·알려진 제한·실판매 전 주의사항을 적는다. memory 문서에는 반복 수정 영역과 다음 Sprint 선택 기준만 남긴다.

## 8. 완료 기준

- [ ] Fashion, Beauty, Food, Living에서 각 1개 상품의 전체 흐름을 검증했다.
- [ ] 각 상품에 대해 같은 confirmed 사실을 사용한 두 템플릿 비교 결과가 있다.
- [ ] 문제 해결형의 7개 섹션 순서와 사실 카드 연결을 확인했다.
- [ ] 모바일 390px 확인과 공개 미리보기 또는 이미지 export 확인을 남겼다.
- [ ] 발견 이슈를 심각도와 재현 절차로 기록했다.
- [ ] 카테고리별 권장 템플릿과 Sprint 15 후보 하나를 결정 기록으로 남겼다.
- [ ] 시작/종료 기준선의 백엔드 전체 테스트와 프론트 빌드가 통과했다.

## 9. 실행 순서 요약

1. 자동 테스트·프론트 빌드 기준선을 기록한다.
2. 4개 카테고리의 실제 또는 현실적인 상품과 사용 가능한 자료를 확정한다.
3. 사실 카드를 사람이 확인하고 두 템플릿을 같은 조건으로 생성한다.
4. 모바일·공개 미리보기·export를 검증한다.
5. 이슈를 문서화하고 카테고리별 권장 템플릿 및 Sprint 15를 결정한다.
