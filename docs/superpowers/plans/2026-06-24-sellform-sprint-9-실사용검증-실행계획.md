# Sellform Sprint 9 실사용 검증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint 0~8로 구현된 Sellform 1.0 내부 도구를 실제 또는 현실적인 소싱 상품 10~20개로 끝까지 검증하고, 제품화 전에 고쳐야 할 품질·UX·운영 리스크를 구체적인 증거로 정리한다.

**Architecture:** 이번 스프린트는 새 기능 개발보다 검증과 안정화가 중심이다. 기존 Next.js/FastAPI 기능을 실제 상품 흐름에 태워보고, 상품별 결과를 문서화한 뒤, 발견된 결함만 작은 보완 작업으로 분리한다. MCP, 결제, 판매처 자동등록 같은 확장 기능은 범위 밖으로 두고 핵심 상세페이지 제작 엔진의 실사용 품질을 먼저 판단한다.

**Tech Stack:** Next.js, TypeScript, React, Tailwind CSS, FastAPI, Python, SQLite/PostgreSQL 호환 DB 계층, 로컬 파일 업로드, AI Adapter, HTML/CSS 렌더러, pytest, Next.js production build.

---

## 0. Sprint 9의 위치

Sprint 9는 “새 기능 스프린트”가 아니라 “1.0 실사용 검증 스프린트”다. 최종 기획서의 1.0 검증 기준은 다음과 같다.

- 실제 소싱 상품 10~20개로 프로젝트를 완성한다.
- 각 상품마다 판매처에 올릴 수 있는 이미지형 상세페이지 결과물을 최소 1개 생성한다.
- 사용자 수정 이유, 사실·카피·섹션 변경 이유를 기록한다.
- 입력부터 출력까지 걸린 시간과 기존 수작업 대비 절감 시간을 측정한다.
- 확인되지 않은 사실이 최종 상세페이지에 단정적으로 쓰인 사례를 기록한다.

## 1. 파일 구조

### 새로 만들 문서

- `docs/testing/2026-06-24-sellform-sprint-9-baseline-test-log.md`
  - Sprint 9 시작 전 현재 빌드/테스트 기준선 기록.
- `docs/testing/2026-06-24-sellform-sprint-9-product-validation-pack.md`
  - 실제 검증에 사용할 10~20개 상품 목록과 카테고리, 입력 자료, 기대 검증 포인트 정의.
- `docs/testing/2026-06-24-sellform-sprint-9-product-run-log.md`
  - 상품별 end-to-end 실행 기록.
- `docs/reviews/2026-06-24-sellform-sprint-9-code-review.md`
  - Sprint 9 종료 시 실제 검증 결과와 발견 이슈 리뷰.
- `docs/troubleshooting/2026-06-24-sellform-sprint-9-troubleshooting.md`
  - 실상품 검증 중 발생한 장애·품질 문제·복구 절차 기록.
- `docs/releases/2026-06-24-sellform-sprint-9.md`
  - Sellform 1.0 실사용 검증 릴리스 노트.
- `memory/2026-06-24-sellform-sprint-9-lessons.md`
  - 반복적으로 나타난 제품 교훈과 다음 스프린트 판단 기준.

### 수정 가능 파일

Sprint 9 중 실제 결함이 발견될 때만 수정한다.

- `backend/src/api/*.py`
- `backend/src/services/*.py`
- `backend/tests/*.py`
- `frontend/src/app/**/*.tsx`
- `docs/superpowers/plans/2026-06-23-sellform-sprint-roadmap.md`

## 2. 검증 상품 구성

최소 12개, 가능하면 16개 상품으로 시작한다.

| 카테고리 | 최소 개수 | 필수 시나리오 |
| --- | ---: | --- |
| 패션/잡화 | 3개 | 정상 상품, 필수 정보 누락 상품, 과장 표현 위험 상품 |
| 뷰티/화장품 | 3개 | 정상 상품, 전성분/주의사항 누락 상품, 의학적 표현 위험 상품 |
| 식품/건강식품 | 3개 | 정상 상품, 원재료/알레르기 누락 상품, 질병 효능 표현 위험 상품 |
| 생활/리빙 | 3개 | 정상 상품, 인증/규격 누락 상품, 안전/호환 과장 표현 위험 상품 |

각 상품은 다음 정보를 가진다.

```markdown
| ID | 카테고리 | 상품명 | 공급처/자료 출처 | 입력 자료 | 샘플 사진 여부 | 목표 판매처 | 리스크 포인트 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S9-FASHION-01 | Fashion | 예: 남성 코튼 셔츠 | 1688/도매처/직접촬영 | URL + 텍스트 + 이미지 | 없음/있음 | 쿠팡/스마트스토어 | 소재/사이즈 |
```

## 3. 완료 기준

Sprint 9는 “모든 상품을 성공시키는 기능 개발 스프린트”가 아니라 “실사용 검증과 안정화 스프린트”다. 따라서 완료 기준은 단순 성공 수보다, 충분한 상품을 실제 흐름에 태우고 성공·차단·실패 원인을 분류했는지를 중심으로 판단한다.

- [ ] 실제 또는 현실적인 상품 10개 이상을 Sellform 전체 흐름으로 검증했다.
- [ ] 4개 카테고리 모두 최소 2개 이상 검증했다.
- [ ] 각 상품마다 입력 자료, AI 결과, 사용자 수정, 검수 이슈, export 결과를 기록했다.
- [ ] 최소 5개 상품에서 이미지형 상세페이지 export를 생성했다.
- [ ] 최소 4개 상품에서 공개 랜딩형 페이지 발행을 검증했다.
- [ ] export 또는 발행까지 가지 못한 상품은 compliance 차단, 입력 부족, AI 실패, 수동 보완 필요 등으로 원인을 분류했다.
- [ ] 실패·차단·보류 상품은 실패 원인과 복구 가능 여부를 `docs/troubleshooting/`에 기록했다.
- [ ] 테스트 명령과 프론트 빌드가 통과했다.
- [ ] Sprint 10의 방향을 결정했다.

> 정정 기준: 원래 계획의 “10개 이상 end-to-end 완료”와 “10개 이상 이미지 export”는 실사용 검증 스프린트의 성격상 과도하게 성공 수 중심이었다. Sprint 9에서는 규정 위반 상품이 정상 차단되는 것도 중요한 검증 결과이므로, 조건부 완료 기준을 “10개 이상 검증 + 5개 이상 성공 산출물 + 실패/차단 원인 문서화”로 조정한다.

---

## Task 1: Sprint 9 기준선 검증 기록 생성

**Files:**
- Create: `docs/testing/2026-06-24-sellform-sprint-9-baseline-test-log.md`

- [ ] **Step 1: 백엔드 전체 테스트 실행**

Run:

```powershell
cd C:\page\backend
uv run --project . pytest -q
```

Expected:

```text
50 passed
```

- [ ] **Step 2: 프론트 프로덕션 빌드 실행**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
Generating static pages (9/9)
```

- [ ] **Step 3: 기준선 로그 문서 작성**

Create `docs/testing/2026-06-24-sellform-sprint-9-baseline-test-log.md`:

```markdown
# 테스트 실행 로그: Sellform Sprint 9 기준선

- 날짜: 2026-06-24
- 목적: Sprint 9 실사용 검증 시작 전 현재 코드 상태의 테스트/빌드 기준선을 고정한다.

## 1. 백엔드 테스트

```text
uv run --project . pytest -q

결과:
50 passed
```

## 2. 프론트 빌드

```text
npm.cmd run build

결과:
Compiled successfully
Generating static pages (9/9)
```

## 3. 기준선 판단

Sprint 9 실사용 검증은 현재 자동 테스트와 프론트 빌드가 통과한 상태에서 시작한다.
```

## Task 2: Sprint 9 상품 검증팩 작성

**Files:**
- Create: `docs/testing/2026-06-24-sellform-sprint-9-product-validation-pack.md`

- [ ] **Step 1: 상품 검증팩 문서 생성**

Create `docs/testing/2026-06-24-sellform-sprint-9-product-validation-pack.md`:

```markdown
# Sellform Sprint 9 상품 검증팩

- 날짜: 2026-06-24
- 목적: Sellform 1.0을 실제 또는 현실적인 소싱 상품으로 검증하기 위한 테스트 상품 목록을 정의한다.

## 1. 상품 선정 기준

- 실제 판매를 고려할 수 있는 상품이거나, 실제 도매처 자료와 유사한 현실적인 상품이어야 한다.
- 카테고리는 Fashion, Beauty, Food, Living 중 하나로 분류한다.
- 최소 입력 자료는 상품명, 설명 텍스트, 이미지 1개 이상이다.
- URL이 막히거나 자료가 부족한 경우 수동 텍스트 입력과 이미지 업로드 흐름을 검증한다.
- 위험 표현이나 필수 정보 누락이 있는 상품을 일부 포함해 검수 기능을 확인한다.

## 2. 검증 상품 목록

| ID | 카테고리 | 상품명 | 자료 출처 | 입력 자료 | 샘플 사진 | 목표 판매처 | 검증 포인트 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S9-FASHION-01 | Fashion | 남성 코튼 셔츠 | 공급처 URL | URL + 텍스트 + 이미지 | 없음 | 스마트스토어 | 소재/사이즈/착용 컷 |
| S9-FASHION-02 | Fashion | 여성 데일리 로퍼 | 공급처 텍스트 | 텍스트 + 이미지 | 없음 | 쿠팡 | 소재 누락 감지 |
| S9-FASHION-03 | Fashion | 방수 여행 파우치 | 직접 입력 | 텍스트 + 이미지 | 있음 | 스마트스토어 | 과장 표현 경고 |
| S9-BEAUTY-01 | Beauty | 수분 진정 크림 | 공급처 URL | URL + 이미지 | 없음 | 스마트스토어 | 전성분/용량 |
| S9-BEAUTY-02 | Beauty | 비타민 세럼 | 공급처 텍스트 | 텍스트 + 이미지 | 없음 | 쿠팡 | 의학적 표현 차단 |
| S9-BEAUTY-03 | Beauty | 립밤 세트 | 직접 입력 | 텍스트 + 이미지 | 있음 | 스마트스토어 | 사용법/주의사항 |
| S9-FOOD-01 | Food | 착즙 사과주스 | 공급처 URL | URL + 텍스트 | 없음 | 스마트스토어 | 원재료/보관법 |
| S9-FOOD-02 | Food | 견과 믹스 | 공급처 텍스트 | 텍스트 + 이미지 | 없음 | 쿠팡 | 알레르기 정보 |
| S9-FOOD-03 | Food | 단백질 쉐이크 | 직접 입력 | 텍스트 + 이미지 | 있음 | 스마트스토어 | 건강 효능 표현 경고 |
| S9-LIVING-01 | Living | 자석 차량 거치대 | 공급처 URL | URL + 이미지 | 없음 | 쿠팡 | 호환/안전 표현 |
| S9-LIVING-02 | Living | 실리콘 밀폐용기 | 공급처 텍스트 | 텍스트 + 이미지 | 없음 | 스마트스토어 | 소재/내열 정보 |
| S9-LIVING-03 | Living | 어린이 식기 세트 | 직접 입력 | 텍스트 + 이미지 | 있음 | 스마트스토어 | KC/안전 정보 |

## 3. 상품별 기록 양식

```markdown
## 상품 ID

- 상품명:
- 카테고리:
- 자료 출처:
- 입력 방식:
- 시작 시각:
- 종료 시각:
- 총 소요 시간:
- AI 비용:
- 사용자 수정 횟수:
- 검수 이슈:
- export 결과:
- 공개 페이지 결과:
- 판매처 업로드 가능 판단:
- 남은 문제:
```
```

## Task 3: 상품별 end-to-end 실행 로그 작성

**Files:**
- Create: `docs/testing/2026-06-24-sellform-sprint-9-product-run-log.md`

- [ ] **Step 1: 개발 서버 실행**

Run backend:

```powershell
cd C:\page\backend
uv run --project . uvicorn src.app:app --reload --port 8000
```

Run frontend:

```powershell
cd C:\page\frontend
npm.cmd run dev
```

Expected:

```text
FastAPI: http://localhost:8000
Next.js: http://localhost:3000
```

- [ ] **Step 2: 각 상품의 전체 흐름 실행**

각 상품마다 브라우저에서 다음 순서로 진행한다.

```text
/workspace/projects/new
→ 상품 생성
→ 자료 입력 또는 파일 업로드
→ /workspace/projects/{id}/facts
→ 사실 확인 및 카테고리 확정
→ /workspace/projects/{id}/page-editor
→ 상세페이지 생성 및 섹션 편집
→ /workspace/projects/{id}/export
→ 검수 및 이미지 export
→ /workspace/projects/{id}/publish
→ 공개 페이지 발행
```

- [ ] **Step 3: 실행 로그 문서 생성**

Create `docs/testing/2026-06-24-sellform-sprint-9-product-run-log.md`:

```markdown
# Sellform Sprint 9 상품별 실행 로그

- 날짜: 2026-06-24
- 검증 범위: 실제 또는 현실적인 상품 10~20개 end-to-end 실사용 검증

## 요약

| 지표 | 값 |
| --- | ---: |
| 총 상품 수 | 0 |
| 완료 상품 수 | 0 |
| 실패 상품 수 | 0 |
| 평균 소요 시간 | 0분 |
| 평균 사용자 수정 횟수 | 0회 |
| export 성공 수 | 0 |
| 공개 페이지 발행 성공 수 | 0 |

## 상품별 기록

### S9-FASHION-01

- 상품명:
- 카테고리: Fashion
- 입력 방식:
- 시작 시각:
- 종료 시각:
- 총 소요 시간:
- AI 비용:
- 사용자 수정 횟수:
- 사실 확인 결과:
- 카테고리 확정 결과:
- 상세페이지 생성 결과:
- 검수 결과:
- 이미지 export 결과:
- 공개 페이지 결과:
- 판매처 업로드 가능 판단:
- 남은 문제:
```

나머지 상품은 같은 형식으로 이어서 기록한다.

## Task 4: 실사용 중 발견된 결함만 작은 보완으로 처리

**Files:**
- Modify only when a confirmed defect exists:
  - `backend/src/api/*.py`
  - `backend/src/services/*.py`
  - `backend/tests/*.py`
  - `frontend/src/app/**/*.tsx`
- Create or modify:
  - `docs/troubleshooting/2026-06-24-sellform-sprint-9-troubleshooting.md`

- [ ] **Step 1: 결함 기준을 분류한다**

다음 기준으로만 코드 수정을 허용한다.

| 등급 | 기준 | 처리 |
| --- | --- | --- |
| Blocker | 상품 흐름을 끝까지 완료할 수 없음 | Sprint 9 안에서 수정 |
| Major | 판매처 업로드 판단을 막는 품질 문제 | Sprint 9 안에서 수정 가능 |
| Minor | 불편하지만 우회 가능 | 문서화 후 Sprint 10 후보 |
| Idea | 개선 아이디어 | memory 또는 backlog 기록 |

- [ ] **Step 2: 결함마다 재현 테스트를 먼저 작성한다**

예시:

```powershell
cd C:\page\backend
uv run --project . pytest tests/test_exports.py::test_specific_failure_case -q
```

Expected before fix:

```text
FAILED
```

- [ ] **Step 3: 최소 코드로 수정한다**

수정은 결함 재현 테스트를 통과시키는 범위로 제한한다. 기능 확장은 Sprint 10 이후로 넘긴다.

- [ ] **Step 4: 수정 후 전체 검증을 실행한다**

Run:

```powershell
cd C:\page\backend
uv run --project . pytest -q
```

Expected:

```text
50 passed
```

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

- [ ] **Step 5: 트러블슈팅 문서 작성**

Create or update `docs/troubleshooting/2026-06-24-sellform-sprint-9-troubleshooting.md`:

```markdown
# 트러블슈팅: Sellform Sprint 9

## 이슈 목록

### B1. 이슈 제목

- 상품 ID:
- 증상:
- 재현 절차:
- 원인:
- 조치:
- 검증 명령:
- 결과:
- 남은 위험:
```

## Task 5: Sprint 9 코드리뷰 문서 작성

**Files:**
- Create: `docs/reviews/2026-06-24-sellform-sprint-9-code-review.md`

- [ ] **Step 1: 코드리뷰 문서 생성**

Create `docs/reviews/2026-06-24-sellform-sprint-9-code-review.md`:

```markdown
# 코드 리뷰: Sellform Sprint 9 (1.0 실사용 검증과 안정화)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | 실제 상품 10~20개 end-to-end 검증, 발견 결함 보완, 테스트/빌드/문서화 |
| 리뷰어 | Codex |
| 상태 | 검증 전 |

## 1. 검증 요약

- 총 검증 상품 수:
- 완료 상품 수:
- 실패 상품 수:
- 이미지 export 성공 수:
- 공개 페이지 발행 성공 수:
- 평균 소요 시간:
- 평균 사용자 수정 횟수:

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| 10개 이상 상품 실사용 검증 | 미확인 | `docs/testing/2026-06-24-sellform-sprint-9-product-run-log.md` |
| 4개 카테고리 검증 | 미확인 | 동일 |
| 5개 이상 이미지 export 생성 | 미확인 | 동일 |
| 공개 페이지 발행 검증 | 미확인 | 동일 |
| 보류/차단/실패 원인 분류 | 미확인 | 동일 |
| 실패/복구 기록 | 미확인 | `docs/troubleshooting/2026-06-24-sellform-sprint-9-troubleshooting.md` |
| Sprint 10 방향 결정 | 미확인 | `docs/decisions/2026-06-24-sellform-sprint-10-direction.md` |

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 이슈 없음 / 또는 아래에 기록

## 4. 테스트 증적

```text
uv run --project . pytest -q
결과:
```

```text
npm.cmd run build
결과:
```

## 5. 결론

- 결론:
- Sprint 10 권장 방향:
```

## Task 6: 릴리스 노트와 장기 교훈 기록

**Files:**
- Create: `docs/releases/2026-06-24-sellform-sprint-9.md`
- Create: `memory/2026-06-24-sellform-sprint-9-lessons.md`

- [ ] **Step 1: 릴리스 노트 작성**

Create `docs/releases/2026-06-24-sellform-sprint-9.md`:

```markdown
# Sellform Sprint 9 릴리스 노트

- 날짜: 2026-06-24
- 릴리스 성격: 1.0 실사용 검증 / 안정화

## 1. 무엇을 검증했나

- 실제 또는 현실적인 상품 10~20개로 Sellform 전체 흐름을 검증했다.
- 카테고리별 상세페이지 생성, 검수, export, 공개 페이지 발행을 확인했다.

## 2. 주요 결과

- 완료 상품 수:
- 실패 상품 수:
- 평균 소요 시간:
- 평균 수정 횟수:
- 판매처 업로드 가능 판단:

## 3. 알려진 제한

- 이미지 기반 AI 실분석:
- 실제 인증/배포:
- S3/CDN:
- 실판매처 자동등록:

## 4. 다음 Sprint 후보

1. 운영 배포 안정화
2. 이미지 AI 분석/보정 고도화
3. Figma 또는 Google Sheets MCP 연동
4. 외부 셀러 베타 온보딩
```

- [ ] **Step 2: memory 문서 작성**

Create `memory/2026-06-24-sellform-sprint-9-lessons.md`:

```markdown
# Memory: Sellform Sprint 9 실사용 검증 교훈

## 1. 반복적으로 드러난 문제

- 

## 2. 가장 가치 있었던 기능

- 

## 3. 사용자가 가장 많이 수정한 영역

- 사실:
- 카피:
- 이미지:
- 섹션 구성:
- 검수 경고:

## 4. Sprint 10 판단 기준

다음 기준 중 가장 큰 병목을 Sprint 10으로 선택한다.

| 후보 | 선택 조건 |
| --- | --- |
| 운영 배포 안정화 | 로컬에서는 되지만 실제 사용 환경 구성이 불안정할 때 |
| 이미지 AI 고도화 | 상품 사진만으로 자동 추출 품질이 낮을 때 |
| Figma MCP | 디자인 품질/협업 수요가 가장 클 때 |
| Google Sheets/Drive MCP | 상품 수가 많아져 운영 관리가 병목일 때 |
| 외부 셀러 베타 | 내부 사용에서 10개 이상 상품이 안정적으로 통과했을 때 |
```

## Task 7: Sprint 10 방향 결정

**Files:**
- Create or modify: `docs/decisions/2026-06-24-sellform-sprint-10-direction.md`

- [ ] **Step 1: Sprint 9 결과를 기반으로 선택지를 평가한다**

평가 기준:

| 후보 | 선택 기준 | 선택 시 Sprint 10 목표 |
| --- | --- | --- |
| AI 사실 카드 자동 추출 | 사용자가 사실 카드를 수기로 작성하는 시간이 가장 큰 병목 | URL/텍스트/이미지에서 사실 후보 자동 생성 후 사용자 검수 |
| 운영 배포 안정화 | 로컬 의존성이 가장 큰 위험 | 실제 배포 가능한 DB/스토리지/환경 구성 |
| 이미지 AI 고도화 | 이미지에서 사실 추출 품질이 낮음 | 공개 URL/base64/멀티모달 분석 파이프라인 |
| Figma MCP | 디자인 협업/템플릿 관리가 병목 | 상세페이지 초안을 Figma 프레임으로 export |
| Google Sheets/Drive MCP | 상품 관리/작업 상태가 병목 | 소싱 목록과 결과물 폴더 연동 |
| 외부 셀러 베타 | 내부 상품 검증이 안정적 | 3~5명 베타 초대와 피드백 운영 |

- [ ] **Step 2: 결정 문서 작성**

Create `docs/decisions/2026-06-24-sellform-sprint-10-direction.md`:

```markdown
# 결정 기록: Sellform Sprint 10 방향

- 날짜: 2026-06-24
- 상태: 제안

## 1. Sprint 9 결과 요약

- 검증 상품 수:
- 완료 상품 수:
- 실패 상품 수:
- 가장 큰 병목:

## 2. 후보 비교

| 후보 | 장점 | 위험 | Sprint 9 근거 |
| --- | --- | --- | --- |
| AI 사실 카드 자동 추출 | 자료 입력 시간이 크게 줄고 사용자는 검수 중심으로 전환 | URL 수집 정책/AI 오인식/미확정 사실 사용 위험 |  |
| 운영 배포 안정화 | 실제 사용 가능성 증가 | 기능 개발 속도 저하 |  |
| 이미지 AI 고도화 | 입력 자동화 품질 증가 | AI 비용/정책 이슈 |  |
| Figma MCP | 디자인 협업 가치 증가 | 핵심 엔진 외부 의존성 |  |
| Google Sheets/Drive MCP | 소싱 운영 효율 증가 | 외부 인증/권한 관리 |  |
| 외부 셀러 베타 | 빠른 시장 검증 | 지원 부담 증가 |  |

## 3. 결정

- 선택:
- 이유:
- 다음 Sprint 목표:
- 제외한 후보를 다시 검토할 조건:
```

---

## 4. Sprint 9 실행 순서

1. Task 1로 기준선 테스트/빌드 기록을 만든다.
2. Task 2로 상품 검증팩을 확정한다.
3. Task 3으로 상품별 end-to-end 검증을 실행한다.
4. Task 4로 Blocker/Major 결함만 보완한다.
5. Task 5로 코드리뷰 문서를 작성한다.
6. Task 6으로 릴리스 노트와 memory를 남긴다.
7. Task 7로 Sprint 10 방향을 결정한다.

## 5. Sprint 9 제외 범위

- 쿠팡/스마트스토어 자동 상품 등록
- 결제/구독 실제 연동
- Figma, Google Drive, Notion, Browser MCP 실제 구현
- 완전한 운영 인증 시스템
- S3/CDN 운영 스토리지 전환
- 실제 상품 형태를 바꾸는 생성형 이미지 편집

위 항목은 Sprint 9 결과를 보고 Sprint 10 이후 별도 계획으로 분리한다.
