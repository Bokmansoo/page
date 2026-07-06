# Sellform Sprint 11 Facts UX Copy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사실 확인 보드의 깨진 한글 문구를 정상화하고, Sprint 10의 자동 사실 카드 생성 흐름을 사용자가 헷갈리지 않고 쓸 수 있게 만든다.

**Architecture:** Sprint 11은 새 AI 기능을 추가하지 않는다. 기존 facts page의 UI copy, 상태 설명, 빈 상태, 자동 생성 결과 안내, 검수 액션 문구를 정리하고, 사용자가 “AI 후보”와 “확정 사실”의 차이를 이해하도록 UX를 개선한다. 데이터 모델과 API 계약은 Sprint 10 구현을 그대로 사용한다.

**Tech Stack:** Next.js 14 App Router, React, TypeScript, Tailwind CSS, FastAPI existing API, `npm.cmd run build`.

---

## 0. Sprint 11 범위 원칙

### 포함

- facts 페이지 깨진 한글 문구 정상화.
- `AI로 사실 카드 자동 생성` 버튼과 결과 배너 문구 개선.
- 자동 후보/확정 사실/수정 필요/모름 상태 설명 강화.
- URL fallback 안내를 사용자가 이해하기 쉽게 표시.
- 빈 상태에서 “AI 자동 생성”과 “수동 추가” 선택지를 함께 제공.
- 모바일 폭에서 버튼과 카드가 어색하게 깨지지 않는지 확인.
- 프론트 빌드와 수동 QA 증적 문서 작성.

### 제외

- 새로운 AI 추출 로직.
- 실제 URL 직접 수집.
- OCR/멀티모달 이미지 내용 분석.
- 백엔드 데이터 모델 변경.
- 판매처 자동 업로드.

## 1. 파일 구조

### 수정 대상

- `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
  - 깨진 한글 문구 정상화.
  - 자동 생성 UX 문구 개선.
  - 상태 배지/도움말/빈 상태 UI 개선.

### 신규 문서

- `docs/testing/2026-06-24-sellform-sprint-11-facts-ux-test-log.md`
  - 프론트 빌드와 수동 QA 기록.
- `docs/reviews/2026-06-24-sellform-sprint-11-code-review.md`
  - 계획 대비 충족 여부와 남은 UX 이슈 기록.
- `docs/troubleshooting/2026-06-24-sellform-sprint-11-facts-ux.md`
  - 깨진 한글/문구 혼선/빈 상태 복구 기록.

## 2. UX 문구 기준

다음 용어를 일관되게 사용한다.

| 개념 | 표준 문구 |
| --- | --- |
| 수동 입력 자료 | 소싱 근거 자료 |
| AI 생성 후보 | AI 후보 |
| 사용자 승인 사실 | 확인된 사실 |
| unknown | 모름 |
| confirmed | 확인됨 |
| needs_revision | 수정 필요 |
| 자동 생성 버튼 | AI로 사실 카드 자동 생성 |
| 수동 추가 버튼 | 사실 카드 수동 추가 |
| 다음 단계 버튼 | 검증 완료 및 다음 단계 |
| URL fallback | 링크 직접 수집은 아직 지원하지 않아 입력 텍스트와 업로드 이미지를 우선 분석했습니다. |

## 3. Task 1: facts 페이지 깨진 한글 문구 정상화

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: 깨진 문자열 목록을 추출한다**

Run:

```powershell
Select-String -LiteralPath "frontend\src\app\workspace\projects\[id]\facts\page.tsx" -Pattern "�|\?꾨|\?ъ|\?뺤|紐|寃|洹|怨|移|蹂|遺|異|濡|?|?ㅼ|?섏|?대|?곗" -AllMatches
```

Expected:

```text
기존 깨진 한글 문자열 위치가 출력된다.
```

- [ ] **Step 2: 오류/로딩/빈 상태 문구를 정상화한다**

다음 의미로 교체한다.

```tsx
// examples
throw new Error("프로젝트 정보를 불러오지 못했습니다.");
throw new Error("사실 검증 데이터를 불러오지 못했습니다.");
setError(err instanceof Error ? err.message : "데이터 로딩 실패");

// loading
<p className="text-slate-400 text-sm">사실 확인 및 원본 자료를 불러오는 중...</p>

// empty state
<p className="font-semibold text-xs">등록된 상품 사실 카드가 없습니다.</p>
<p className="text-[10px] mt-1 mb-4">
  먼저 AI로 사실 후보를 자동 생성하거나, 중요한 정보를 수동으로 추가해 주세요.
</p>
```

- [ ] **Step 3: 버튼/폼 라벨 문구를 정상화한다**

다음 표준 문구를 적용한다.

```tsx
"사실 카드 수동 추가"
"새로운 사실 카드 추가"
"한글 상품 사실 (필수)"
"매핑 근거 텍스트 (선택)"
"매핑 이미지 자산 (선택)"
"관련 이미지 선택 없음"
"사실 카드 저장"
"취소"
"수정"
"삭제"
"변경 이력"
```

- [ ] **Step 4: 상태 버튼 문구를 정상화한다**

```tsx
"검증 상태:"
"확인됨"
"수정 필요"
"모름"
```

- [ ] **Step 5: 프론트 빌드를 실행한다**

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

## 4. Task 2: 자동 사실 생성 UX 안내 개선

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: 자동 생성 버튼 주변 안내 문구를 추가한다**

상단 버튼 그룹 또는 우측 보드 상단에 다음 설명을 표시한다.

```tsx
<p className="text-[11px] text-slate-400">
  AI가 소싱 텍스트와 업로드 이미지를 바탕으로 사실 후보를 만듭니다.
  후보는 자동 확정되지 않으며, 확인됨으로 승인한 사실만 상세페이지에 사용됩니다.
</p>
```

- [ ] **Step 2: 자동 생성 결과 배너 문구를 정리한다**

현재 결과 배너를 다음 의미로 정리한다.

```tsx
<div className="font-bold text-indigo-300">AI 사실 카드 자동 생성 결과</div>
<span>신규 후보 {autoExtractResult.created_count}개</span>
<span>중복 제외 {autoExtractResult.skipped_duplicates}개</span>
<span>링크 fallback {autoExtractResult.failed_sources.length}건</span>
<p>
  자동 생성된 사실은 아직 후보입니다. 최종 상세페이지에는 사용자가 확인됨으로 승인한 사실만 사용됩니다.
</p>
```

- [ ] **Step 3: URL fallback 문구를 사용자 친화적으로 변환한다**

`failed_sources`의 `reason === "url_collection_deferred"`는 다음처럼 표시한다.

```tsx
"링크 직접 수집은 아직 지원하지 않아 입력 텍스트와 업로드 이미지를 우선 분석했습니다."
```

- [ ] **Step 4: 프론트 빌드를 실행한다**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

## 5. Task 3: 사실 카드 정보 구조 개선

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

- [ ] **Step 1: AI 후보 배지를 명확히 표시한다**

카드 내 `extraction_source`가 있을 때 다음 정보를 표시한다.

```tsx
AI 후보 · 텍스트 근거
AI 후보 · 이미지 근거
AI 후보 · 메타데이터
```

매핑:

```tsx
const EXTRACTION_SOURCE_LABELS = {
  manual_text: "텍스트 근거",
  image: "이미지 근거",
  metadata: "메타데이터",
  url: "링크 근거",
} as const;
```

- [ ] **Step 2: 신뢰도 표기를 사용자 친화적으로 바꾼다**

```tsx
{typeof fact.confidence === "number" ? `신뢰도 ${Math.round(fact.confidence * 100)}%` : ""}
```

- [ ] **Step 3: 위험 플래그 문구를 한국어로 변환한다**

```tsx
const RISK_FLAG_LABELS: Record<string, string> = {
  certification_review: "인증/표기 확인 필요",
  low_confidence: "낮은 신뢰도",
};
```

알 수 없는 플래그는 원문을 그대로 보여준다.

- [ ] **Step 4: 프론트 빌드를 실행한다**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

## 6. Task 4: 모바일 수동 QA

**Files:**

- Create: `docs/testing/2026-06-24-sellform-sprint-11-facts-ux-test-log.md`

- [ ] **Step 1: 로컬 서버를 실행한다**

Run backend:

```powershell
cd C:\page
.\run_backend.ps1
```

Run frontend:

```powershell
cd C:\page\frontend
npm.cmd run dev
```

- [ ] **Step 2: 데스크톱 폭에서 확인한다**

확인 경로:

```text
http://localhost:3000/workspace/projects/{project_id}/facts
```

체크:

- 깨진 한글 문구가 보이지 않는다.
- AI 자동 생성 버튼을 찾을 수 있다.
- 자동 생성 결과가 이해 가능한 문장으로 표시된다.
- 후보/확정/수정 필요/모름 차이가 이해된다.

- [ ] **Step 3: 모바일 폭에서 확인한다**

브라우저 DevTools 또는 창 크기 축소로 390px 폭을 확인한다.

체크:

- 상단 버튼이 화면 밖으로 밀리지 않는다.
- 사실 카드의 근거/상태 버튼이 읽힌다.
- 빈 상태에서 AI 자동 생성과 수동 추가 선택지가 보인다.

- [ ] **Step 4: 테스트 로그 문서를 작성한다**

Create `docs/testing/2026-06-24-sellform-sprint-11-facts-ux-test-log.md`:

```markdown
# 테스트 실행 로그: Sellform Sprint 11 Facts UX

- 날짜: 2026-06-24
- 목적: 사실 확인 보드 문구 정상화와 자동 사실 생성 UX를 검증한다.

## 1. 프론트 빌드

```text
npm.cmd run build
결과:
```

## 2. 데스크톱 수동 QA

- 경로:
- 결과:
- 발견 이슈:

## 3. 모바일 수동 QA

- 기준 폭:
- 결과:
- 발견 이슈:

## 4. 판단

```
```

## 7. Task 5: 리뷰·트러블슈팅 문서 작성

**Files:**

- Create: `docs/reviews/2026-06-24-sellform-sprint-11-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-11-facts-ux.md`

- [ ] **Step 1: 코드리뷰 문서를 작성한다**

Create `docs/reviews/2026-06-24-sellform-sprint-11-code-review.md`:

```markdown
# 코드 리뷰: Sellform Sprint 11 (Facts UX Copy Cleanup)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | facts 페이지 한글 문구 정상화, 자동 사실 생성 UX, 상태/배지/빈 상태 안내 |
| 리뷰어 | Codex |
| 상태 | 검토 필요 |

## 1. 변경 요약

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| 깨진 한글 문구 제거 | 미확인 | facts page |
| 자동 생성 UX 안내 개선 | 미확인 | facts page |
| 후보/확정 사실 차이 안내 | 미확인 | facts page |
| 모바일 QA | 미확인 | testing log |
| 프론트 빌드 | 미확인 | testing log |

## 3. 이슈 목록

## 4. 테스트 증적

## 5. 결론
```

- [ ] **Step 2: 트러블슈팅 문서를 작성한다**

Create `docs/troubleshooting/2026-06-24-sellform-sprint-11-facts-ux.md`:

```markdown
# 트러블슈팅: Sellform Sprint 11 Facts UX

## 1. 개요

## 2. 발견 이슈

### N1. 기존 facts page 한글 문구 깨짐

- 증상:
- 원인:
- 조치:

### N2. 자동 후보와 확정 사실 구분 부족

- 증상:
- 원인:
- 조치:

## 3. 남은 위험

## 4. 결론
```

## 8. 완료 기준

- facts 페이지에서 깨진 한글 문구가 보이지 않는다.
- 사용자가 AI 자동 생성 버튼의 목적을 이해할 수 있다.
- 자동 생성 후보와 확인된 사실의 차이가 명확히 표시된다.
- URL fallback 안내가 사용자 친화적인 한국어로 표시된다.
- 빈 상태에서 AI 자동 생성 또는 수동 추가 중 하나를 선택할 수 있다.
- 데스크톱과 모바일 폭에서 주요 흐름이 읽힌다.
- `npm.cmd run build`가 통과한다.
- 테스트 로그, 코드리뷰, 트러블슈팅 문서가 남는다.

