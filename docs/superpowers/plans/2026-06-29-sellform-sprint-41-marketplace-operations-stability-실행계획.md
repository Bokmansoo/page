# Sprint 41 - 마켓 게시 상태·재시도·운영 안정화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스마트스토어와 쿠팡 등록 요청의 상태를 일관되게 추적하고, 실패해도 중복 상품 없이 진단·수정·재시도할 수 있게 한다.

**Architecture:** 채널 어댑터의 응답을 공통 상태 머신과 이벤트 로그로 정규화한다. 자동 재시도는 명백한 일시 오류에만 제한하고, 내용 변경이 필요한 실패는 새 draft와 재승인을 요구한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, `httpx`, Next.js 14, Pytest, Playwright.

---

## 상태 규칙

```text
draft → validating → needs_input | ready
ready → awaiting_user_approval → submitting → submitted
submitted → approval_pending → published
```

오류 코드는 상태와 분리한다.

```text
validation_failed
authentication_failed
submission_failed
remote_rejected
status_check_failed
```

## 파일 구조

- Create: `backend/src/services/marketplace_state_machine.py`
- Create: `backend/src/services/marketplace_retry_policy.py`
- Create: `backend/src/services/marketplace_submission_service.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/api/marketplaces.py`
- Modify: `backend/src/api/operations.py`
- Create: `backend/tests/test_marketplace_state_machine.py`
- Create: `backend/tests/test_marketplace_retry_policy.py`
- Create: `backend/tests/test_marketplace_submission_service.py`
- Create: `backend/tests/test_marketplace_operations_api.py`
- Modify: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Modify: `frontend/src/app/workspace/operations/page.tsx`
- Create: `frontend/e2e/sprint41-marketplace-recovery.spec.ts`
- Create: `docs/testing/2026-06-29-sellform-sprint-41-marketplace-stability-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-41-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-41-marketplace-stability.md`
- Create: `docs/runbooks/2026-06-29-sellform-marketplace-recovery-runbook.md`

### Task 1: 공통 상태 머신과 이벤트 모델

**Files:**

- Create: `backend/src/services/marketplace_state_machine.py`
- Modify: `backend/src/db/models.py`
- Test: `backend/tests/test_marketplace_state_machine.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("submitted", "approval_pending", True),
        ("approval_pending", "published", True),
        ("published", "submitting", False),
        ("needs_input", "submitted", False),
    ],
)
def test_submission_state_transitions(current, target, allowed):
    assert can_transition(current, target) is allowed
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_state_machine.py -q`

- [ ] **Step 3: 상태 머신 구현**

허용 목록 밖의 전이는 `InvalidMarketplaceTransition`을 발생시킨다. 상태 변경은 서비스에서만 수행하고 API router가 DB 상태를 직접 수정하지 않는다.

- [ ] **Step 4: 이벤트 모델 추가**

`MarketplaceSubmissionEvent`는 submission ID, event type, previous status, next status, sanitized payload, error code, created_at을 저장한다.

- [ ] **Step 5: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_state_machine.py -q`

### Task 2: 재시도 정책과 중복 방지

**Files:**

- Create: `backend/src/services/marketplace_retry_policy.py`
- Create: `backend/src/services/marketplace_submission_service.py`
- Test: `backend/tests/test_marketplace_retry_policy.py`
- Test: `backend/tests/test_marketplace_submission_service.py`

- [ ] **Step 1: 재시도 분류 테스트 작성**

```python
@pytest.mark.parametrize(
    ("error_code", "retryable"),
    [
        ("HTTP_429", True),
        ("HTTP_503", True),
        ("TIMEOUT", True),
        ("INVALID_CATEGORY", False),
        ("AUTHENTICATION_FAILED", False),
    ],
)
def test_retry_classification(error_code, retryable):
    assert classify_retry(error_code).retryable is retryable
```

- [ ] **Step 2: timeout 중복 방지 테스트**

```python
def test_timeout_checks_remote_status_before_resubmitting(service, adapter):
    adapter.create_product.side_effect = TimeoutError()
    service.submit(approved_draft)
    adapter.lookup_by_idempotency_key.assert_called_once()
    assert adapter.create_product.call_count == 1
```

- [ ] **Step 3: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_retry_policy.py tests/test_marketplace_submission_service.py -q`

- [ ] **Step 4: 재시도 구현**

최대 3회, 지연 2초·8초·30초를 기록하되 HTTP 요청 안에서 sleep하지 않는다. `next_retry_at`을 저장하고 사용자가 `재시도`를 누르거나 운영 점검 endpoint가 due submission을 처리한다.

- [ ] **Step 5: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_retry_policy.py tests/test_marketplace_submission_service.py -q`

### Task 3: 상태 조회·재시도·취소 API

**Files:**

- Modify: `backend/src/api/marketplaces.py`
- Test: `backend/tests/test_marketplace_operations_api.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_retry_requires_same_payload_and_retryable_error(client, failed_submission, headers):
    response = client.post(
        f"/api/v1/marketplace/submissions/{failed_submission.id}/retry",
        headers=headers,
    )
    assert response.status_code == 202
    assert response.json()["attempt_count"] == 2
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_operations_api.py -q`

- [ ] **Step 3: API 구현**

```text
GET  /api/v1/projects/{project_id}/marketplace/submissions
GET  /api/v1/marketplace/submissions/{submission_id}
POST /api/v1/marketplace/submissions/{submission_id}/refresh
POST /api/v1/marketplace/submissions/{submission_id}/retry
POST /api/v1/marketplace/submissions/{submission_id}/cancel-retry
GET  /api/v1/marketplace/submissions/{submission_id}/events
```

권한 없는 submission은 `404`, 재시도 불가 오류는 `409 NOT_RETRYABLE`, 변경된 package는 `409 REAPPROVAL_REQUIRED`를 반환한다.

- [ ] **Step 4: API 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_operations_api.py -q`

### Task 4: 운영 리포트와 사용자 복구 UI

**Files:**

- Modify: `backend/src/api/operations.py`
- Modify: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Modify: `frontend/src/app/workspace/operations/page.tsx`
- Create: `frontend/e2e/sprint41-marketplace-recovery.spec.ts`

- [ ] **Step 1: E2E 실패 테스트**

등록 상태 타임라인, 수정 가능한 오류 메시지, 상태 새로고침, 재시도 버튼, published 외부 URL을 검증한다.

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint41-marketplace-recovery.spec.ts`

- [ ] **Step 3: 프로젝트 UI 구현**

사용자 메시지는 `카테고리를 다시 선택해 주세요`처럼 조치 중심으로 보여주고 외부 원문 오류는 접을 수 있는 기술 상세에 둔다.

- [ ] **Step 4: 운영 화면 구현**

채널별 성공률, 승인 대기, 재시도 대기, 인증 실패, 원격 거절 수를 표시한다. 비밀값과 전체 요청 payload는 노출하지 않는다.

- [ ] **Step 5: E2E·빌드 검증**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint41-marketplace-recovery.spec.ts && npm.cmd run build`

### Task 5: 장애 시나리오 통합 테스트

**Files:**

- Test: `backend/tests/test_marketplace_submission_service.py`
- Test: `backend/tests/test_marketplace_operations_api.py`

- [ ] **Step 1: 429 후 성공 시나리오**

첫 호출 429, 재시도 호출 성공을 mock하고 event가 `submission_failed → submitted` 순서로 남는지 검증한다.

- [ ] **Step 2: timeout 후 원격 생성 확인 시나리오**

create timeout 뒤 lookup에서 외부 상품 ID가 반환될 때 create를 반복하지 않고 `submitted`로 복구하는지 검증한다.

- [ ] **Step 3: 인증 실패 시나리오**

401은 자동 재시도하지 않고 계정 상태를 `reauth_required`로 바꾸는지 검증한다.

- [ ] **Step 4: package 변경 시나리오**

승인 후 판매가가 바뀌면 재시도가 아닌 새 draft와 재승인을 요구하는지 검증한다.

- [ ] **Step 5: 통합 테스트 실행**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_state_machine.py tests/test_marketplace_retry_policy.py tests/test_marketplace_submission_service.py tests/test_marketplace_operations_api.py -q`

### Task 6: 문서와 최종 회귀 검증

**Files:**

- Create: `docs/testing/2026-06-29-sellform-sprint-41-marketplace-stability-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-41-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-41-marketplace-stability.md`
- Create: `docs/runbooks/2026-06-29-sellform-marketplace-recovery-runbook.md`

- [ ] **Step 1: 전체 마켓 회귀 테스트**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_api.py tests/test_smartstore_registration_api.py tests/test_coupang_registration_api.py tests/test_marketplace_operations_api.py -q`

- [ ] **Step 2: 프론트 최종 검증**

Run: `cd C:\page\frontend && npm.cmd run build && npx.cmd playwright test e2e/sprint38-marketplace-package.spec.ts e2e/sprint39-smartstore-registration.spec.ts e2e/sprint40-coupang-registration.spec.ts e2e/sprint41-marketplace-recovery.spec.ts`

- [ ] **Step 3: 복구 런북 작성**

인증 만료, 429, timeout, 외부 거절, 중복 의심, 상태 조회 실패 각각의 확인 명령과 안전한 복구 순서를 기록한다.

## 완료 기준

- 스마트스토어와 쿠팡의 상태가 공통 상태 모델로 표시된다.
- timeout과 더블클릭이 중복 상품을 만들지 않는다.
- 자동 재시도는 429·5xx·timeout에만 제한된다.
- 상품 내용이 변경되면 반드시 새 승인을 받는다.
- 운영자가 이벤트 이력만으로 실패 지점과 복구 여부를 판단할 수 있다.
