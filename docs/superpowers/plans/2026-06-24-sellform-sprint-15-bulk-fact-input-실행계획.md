# Sellform Sprint 15 Bulk Fact Input UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 상품 사실 카드를 하나씩 입력하지 않고, 여러 사실과 근거를 한 번에 붙여넣어 검수 가능한 카드로 만들 수 있게 한다.

**Architecture:** Sprint 15는 AI/크롤링 고도화 전에 입력 병목을 제거하는 UX 스프린트다. 기존 facts 보드의 단일 카드 추가 흐름은 유지하고, “여러 사실 한번에 추가” 모달과 백엔드 일괄 생성 API를 추가한다. 이미지 자산이 없을 때는 빈 드롭다운 대신 안내와 업로드 유도 문구를 제공한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pytest, Next.js App Router, TypeScript, React, existing Sellform facts board UI.

---

## 0. 배경

Sprint 14 실사용 테스트에서 사용자가 소싱 페이지의 정보를 사실 카드로 쪼개 입력해야 하는 부담이 확인됐다. 현재는 카드 1개마다 사실 문장, 근거 문장, 이미지 매핑을 입력해야 해서 실제 상품 1개를 검증하는 데 시간이 오래 걸린다.

이 스프린트는 링크 자동 수집이나 실제 AI 연동을 다루지 않는다. 사람이 복사해 온 텍스트를 빠르게 카드 여러 개로 등록하는 데 집중한다.

## 1. 범위

### 포함

- facts 페이지에 `여러 사실 한번에 추가` 진입점 추가.
- 여러 줄 입력을 파싱해 사실 카드 여러 개 생성.
- `사실 | 근거: ...` 형식 지원.
- 근거가 없는 줄은 사실과 동일한 근거로 저장하거나 경고 표시.
- 완전 동일한 사실 문장은 중복 제외.
- 생성된 카드는 기본 `confirmed` 또는 사용자가 선택한 상태로 저장.
- 매핑 이미지 자산이 없을 때 안내 문구 표시.
- 일괄 추가 결과로 생성 수, 중복 제외 수, 실패 수를 표시.

### 제외

- 쿠팡/스마트스토어 링크 직접 수집.
- 실제 LLM API 호출.
- 이미지 OCR 신규 구현.
- 상세페이지 생성 로직 변경.

## 2. 대상 파일

| 파일 | 역할 |
| --- | --- |
| `backend/src/api/facts.py` 또는 현재 facts API 라우터 | 일괄 사실 카드 생성 endpoint 추가 |
| `backend/tests/test_facts.py` 또는 기존 facts 테스트 파일 | 일괄 생성, 중복 제외, 검증 상태 테스트 |
| `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx` 또는 현재 facts page | 일괄 추가 버튼과 모달 연결 |
| `frontend/src/components/facts/BulkFactModal.tsx` | 필요 시 bulk modal 분리 |
| `frontend/src/lib/api.ts` 또는 현재 API client | bulk create API 함수 추가 |
| `docs/testing/2026-06-24-sellform-sprint-15-bulk-fact-input-test-log.md` | 테스트 증적 |
| `docs/reviews/2026-06-24-sellform-sprint-15-code-review.md` | 코드 리뷰 |
| `docs/troubleshooting/2026-06-24-sellform-sprint-15-bulk-fact-input.md` | 문제 해결 기록 |

## 3. 데이터 입력 형식

일괄 입력 textarea는 아래 형식을 지원한다.

```text
4,800mAh 배터리를 탑재했습니다. | 근거: 4,800mAh 대용량 배터리
최대 18시간 무선 사용이 가능합니다. | 근거: 최대 18시간 무선 사용이 가능한 FAN JET ULTRA
FAN JET ULTRA 모델입니다. | 근거: FAN JET ULTRA
휴대용 무선 냉각 선풍기입니다. | 근거: 루메나 휴대용 무선 냉각선풍기
```

파싱 규칙:

- 빈 줄은 무시한다.
- `| 근거:` 앞은 `fact_text`로 저장한다.
- `| 근거:` 뒤는 `source_text`로 저장한다.
- `| 근거:`가 없으면 전체 줄을 `fact_text`로 저장하고 `source_text`는 같은 값으로 저장한다.
- 앞뒤 공백은 제거한다.
- 같은 프로젝트 안에 같은 `fact_text`가 이미 있으면 새로 만들지 않는다.

## 4. Task 1: 백엔드 bulk create API를 추가한다

**Files:**

- Modify: `backend/src/api/facts.py` 또는 현재 facts 라우터 파일
- Test: `backend/tests/test_facts.py` 또는 현재 facts 테스트 파일

- [ ] **Step 1: 실패하는 테스트를 작성한다.**

테스트는 한 요청으로 3개 후보를 보내면 2개가 생성되고 1개 중복이 제외되는 동작을 검증한다.

```python
def test_bulk_create_facts_deduplicates_existing_fact(client, project_id):
    client.post(
        f"/api/projects/{project_id}/facts",
        json={
            "fact_text": "4,800mAh 배터리를 탑재했습니다.",
            "source_text": "4,800mAh 대용량 배터리",
            "status": "confirmed",
        },
    )

    response = client.post(
        f"/api/projects/{project_id}/facts/bulk",
        json={
            "items": [
                {
                    "fact_text": "4,800mAh 배터리를 탑재했습니다.",
                    "source_text": "4,800mAh 대용량 배터리",
                },
                {
                    "fact_text": "최대 18시간 무선 사용이 가능합니다.",
                    "source_text": "최대 18시간 무선 사용",
                },
                {
                    "fact_text": "FAN JET ULTRA 모델입니다.",
                    "source_text": "FAN JET ULTRA",
                },
            ],
            "default_status": "confirmed",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 2
    assert body["duplicate_count"] == 1
    assert len(body["created"]) == 2
```

- [ ] **Step 2: 테스트 실패를 확인한다.**

Run:

```powershell
uv run --project backend pytest backend/tests/test_facts.py -q
```

Expected: bulk endpoint가 없어 404 또는 route 없음으로 실패한다.

- [ ] **Step 3: request/response schema와 endpoint를 구현한다.**

구현 요구사항:

- `items`는 1개 이상 50개 이하로 제한한다.
- `fact_text`가 비어 있으면 해당 item은 실패 목록에 넣는다.
- `default_status`는 `confirmed`, `needs_revision`, `unknown` 중 하나만 허용한다.
- 중복 기준은 같은 project 안의 trim된 `fact_text` 완전 일치다.

- [ ] **Step 4: 테스트 통과를 확인한다.**

Run:

```powershell
uv run --project backend pytest backend/tests/test_facts.py -q
```

Expected: facts 관련 테스트가 모두 통과한다.

## 5. Task 2: 프론트엔드 일괄 추가 모달을 만든다

**Files:**

- Modify: `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx`
- Modify or Create: `frontend/src/components/facts/BulkFactModal.tsx`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: API client 함수를 추가한다.**

함수 이름은 기존 컨벤션에 맞춰 `bulkCreateFacts`로 둔다.

```ts
export type BulkFactInput = {
  fact_text: string;
  source_text?: string;
};

export type BulkCreateFactsRequest = {
  items: BulkFactInput[];
  default_status: "confirmed" | "needs_revision" | "unknown";
};
```

- [ ] **Step 2: textarea parser를 구현한다.**

예상 동작:

```ts
parseBulkFacts("A | 근거: B\nC")
// [
//   { fact_text: "A", source_text: "B" },
//   { fact_text: "C", source_text: "C" }
// ]
```

- [ ] **Step 3: facts 페이지에 `여러 사실 한번에 추가` 버튼을 추가한다.**

버튼 위치는 `사실 카드 수동 추가` 옆으로 둔다.

- [ ] **Step 4: 저장 후 결과 요약을 표시한다.**

예시 문구:

```text
사실 카드 4개를 추가했습니다. 중복 1개는 제외했습니다.
```

- [ ] **Step 5: 프론트 빌드를 확인한다.**

Run:

```powershell
cd C:\page\frontend
npm.cmd run build
```

Expected: build succeeds.

## 6. Task 3: 이미지 자산 없음 UX를 보완한다

**Files:**

- Modify: `frontend/src/app/workspace/projects/[projectId]/facts/page.tsx` 또는 fact form component

- [ ] **Step 1: 이미지 드롭다운 empty state를 바꾼다.**

현재:

```text
-- 관련 이미지 선택 없음 --
```

이미지 0개일 때:

```text
업로드된 이미지가 없습니다. 상품 이미지 업로드 후 선택할 수 있습니다.
```

- [ ] **Step 2: 이미지 없이도 사실 카드 저장은 가능하게 둔다.**

이미지 매핑은 선택 사항이다. 이미지가 없어도 `fact_text`와 `source_text`가 있으면 저장되어야 한다.

- [ ] **Step 3: 수동 QA를 기록한다.**

다음 케이스를 `docs/testing/2026-06-24-sellform-sprint-15-bulk-fact-input-test-log.md`에 기록한다.

- 이미지 0개 프로젝트에서 단일 사실 저장.
- 이미지 0개 프로젝트에서 일괄 사실 저장.
- 이미지 있는 프로젝트에서 매핑 이미지 선택.

## 7. 완료 기준

- 한 번의 입력으로 5개 이상 사실 카드를 생성할 수 있다.
- 중복 사실은 새로 생성되지 않고 결과 요약에 표시된다.
- 이미지가 없어도 사용자가 왜 선택지가 없는지 이해할 수 있다.
- 기존 단일 사실 카드 추가 기능은 그대로 동작한다.
- 백엔드 facts 테스트가 통과한다.
- 프론트 빌드가 통과한다.
- 테스트 로그, 코드 리뷰, 트러블슈팅 문서가 남는다.
