# Sprint 39 - 네이버 스마트스토어 승인형 등록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint 38의 공통 상품 패키지를 네이버 상품 등록 요청으로 변환하고, 사용자 승인 후에만 스마트스토어 API로 전송한다.

**Architecture:** 계정·비밀 관리, 순수 변환기, 검증기, HTTP 어댑터, 승인 서비스의 경계를 분리한다. 초안 생성과 검증에는 외부 상태 변경이 없으며 승인된 payload hash와 현재 package hash가 일치할 때만 어댑터를 호출한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pydantic, `cryptography`, `httpx`, Next.js 14, Pytest, Playwright.

---

## 공식 기준

- [네이버 커머스API 소개](https://apicenter.commerce.naver.com/docs/introduction)
- [네이버 상품 등록 API](https://apicenter.commerce.naver.com/docs/commerce-api/current/create-product-product)

API 버전과 필수 필드는 구현 시작일에 다시 확인하고 테스트 fixture에 문서 확인일을 기록한다.

## 파일 구조

- Modify: `backend/pyproject.toml`
- Modify: `backend/src/config.py`
- Modify: `backend/src/db/models.py`
- Create: `backend/src/services/marketplace_secret_service.py`
- Create: `backend/src/services/smartstore_transformer.py`
- Create: `backend/src/services/smartstore_validator.py`
- Create: `backend/src/services/smartstore_adapter.py`
- Modify: `backend/src/api/marketplaces.py`
- Create: `backend/tests/test_marketplace_secrets.py`
- Create: `backend/tests/test_smartstore_transformer.py`
- Create: `backend/tests/test_smartstore_adapter.py`
- Create: `backend/tests/test_smartstore_registration_api.py`
- Modify: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Create: `frontend/e2e/sprint39-smartstore-registration.spec.ts`
- Create: `docs/testing/2026-06-29-sellform-sprint-39-smartstore-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-39-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-39-smartstore.md`
- Create: `docs/runbooks/2026-06-29-sellform-smartstore-connection-runbook.md`

### Task 1: 계정과 암호화된 자격 증명

**Files:**

- Modify: `backend/pyproject.toml`
- Modify: `backend/src/config.py`
- Modify: `backend/src/db/models.py`
- Create: `backend/src/services/marketplace_secret_service.py`
- Test: `backend/tests/test_marketplace_secrets.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_marketplace_secret_is_encrypted_at_rest(secret_service):
    encrypted = secret_service.encrypt({"client_id": "id", "client_secret": "secret"})
    assert b"client_secret" not in encrypted.encode()
    assert secret_service.decrypt(encrypted)["client_secret"] == "secret"
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_secrets.py -q`

- [ ] **Step 3: 의존성과 설정 추가**

`cryptography`를 추가하고 `SELLFORM_MARKETPLACE_CREDENTIAL_KEY`를 필수 운영 설정으로 정의한다. 키가 비어 있으면 계정 연결 API는 `503 MARKETPLACE_CREDENTIAL_KEY_MISSING`을 반환한다.

- [ ] **Step 4: 계정 모델 구현**

`MarketplaceAccount`는 `workspace_id`, `channel`, `external_seller_id`, `encrypted_credentials`, `connection_status`, `last_verified_at`을 저장한다. `(workspace_id, channel, external_seller_id)`에 unique constraint를 둔다.

- [ ] **Step 5: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_secrets.py -q`

### Task 2: 네이버 변환기와 검증기

**Files:**

- Create: `backend/src/services/smartstore_transformer.py`
- Create: `backend/src/services/smartstore_validator.py`
- Test: `backend/tests/test_smartstore_transformer.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_transformer_maps_common_package_without_http(valid_package):
    request = transform_to_smartstore(valid_package, channel_inputs)
    assert request["originProduct"]["statusType"] == "SALE"
    assert request["originProduct"]["name"] == valid_package["title"]
    assert request["originProduct"]["salePrice"] == valid_package["pricing"]["sale_price"]

def test_validator_reports_missing_leaf_category(valid_package):
    result = validate_smartstore(valid_package, {"leaf_category_id": ""})
    assert result.issues[0].code == "SMARTSTORE_CATEGORY_REQUIRED"
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_smartstore_transformer.py -q`

- [ ] **Step 3: 순수 변환 구현**

변환기는 네트워크를 호출하지 않는다. 자동 변환값과 사용자가 직접 입력한 카테고리·배송·반품·고시정보를 합치고, 자동 보정 내역을 별도 배열로 반환한다.

- [ ] **Step 4: 검증 구현**

`field_path`, `code`, `severity`, `message`, `suggested_action`을 제공한다. 카테고리, 가격, 재고, 대표 이미지, 상세 설명, 배송 정보 누락은 `error`다.

- [ ] **Step 5: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_smartstore_transformer.py -q`

### Task 3: OAuth·HTTP 어댑터와 테스트 전송 차단

**Files:**

- Create: `backend/src/services/smartstore_adapter.py`
- Modify: `backend/src/config.py`
- Test: `backend/tests/test_smartstore_adapter.py`

- [ ] **Step 1: mock transport 기반 실패 테스트 작성**

```python
def test_adapter_does_not_send_when_live_submission_is_disabled(httpx_mock):
    adapter = SmartStoreAdapter(live_submission_enabled=False)
    with pytest.raises(SmartStoreAdapterError, match="LIVE_SUBMISSION_DISABLED"):
        adapter.create_product(token="token", payload={"originProduct": {}})
    assert httpx_mock.get_requests() == []
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_smartstore_adapter.py -q`

- [ ] **Step 3: 어댑터 구현**

`SELLFORM_SMARTSTORE_LIVE_SUBMISSION_ENABLED=false`를 기본값으로 둔다. `httpx.Client`를 생성자에서 주입받고 OAuth 토큰 교환, 상품 생성, 상품 조회만 구현한다. 로그에는 Authorization과 client secret을 남기지 않는다.

- [ ] **Step 4: 어댑터 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_smartstore_adapter.py -q`

### Task 4: 초안·승인·전송 API

**Files:**

- Modify: `backend/src/db/models.py`
- Modify: `backend/src/api/marketplaces.py`
- Test: `backend/tests/test_smartstore_registration_api.py`

- [ ] **Step 1: 승인 없는 전송 차단 테스트 작성**

```python
def test_smartstore_submit_requires_current_user_approval(client, draft, headers):
    response = client.post(
        f"/api/v1/marketplace/drafts/{draft.id}/submit",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "USER_APPROVAL_REQUIRED"
```

- [ ] **Step 2: 모델 추가**

`MarketplaceListingDraft`에 package, channel, request JSON, validation JSON, payload hash, approval 상태를 저장한다. `MarketplaceSubmission`에는 idempotency key, external product ID, 상태, 요청 스냅샷을 저장한다.

- [ ] **Step 3: API 구현**

```text
POST /api/v1/projects/{project_id}/marketplace/smartstore/drafts
GET  /api/v1/projects/{project_id}/marketplace/drafts/{draft_id}
POST /api/v1/projects/{project_id}/marketplace/drafts/{draft_id}/approve
POST /api/v1/projects/{project_id}/marketplace/drafts/{draft_id}/submit
```

승인 시 package hash를 저장한다. submit 시 hash가 바뀌었으면 `409 APPROVAL_STALE`을 반환한다.

- [ ] **Step 4: API 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_smartstore_registration_api.py -q`

### Task 5: 스마트스토어 검토 UI

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Create: `frontend/e2e/sprint39-smartstore-registration.spec.ts`

- [ ] **Step 1: E2E 실패 테스트**

계정 미연결 안내, 필수값 입력, 오류 수정, 요청 JSON 요약, 승인 체크박스, live flag가 꺼졌을 때 전송 버튼 비활성화를 검증한다.

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint39-smartstore-registration.spec.ts`

- [ ] **Step 3: UI 구현**

승인 체크박스 문구에 대상 계정, 판매가, 재고를 표시한다. 승인과 전송은 별도 버튼으로 둔다.

- [ ] **Step 4: E2E·빌드 검증**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint39-smartstore-registration.spec.ts && npm.cmd run build`

### Task 6: 통합 검증과 문서

**Files:**

- Create: `docs/testing/2026-06-29-sellform-sprint-39-smartstore-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-39-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-39-smartstore.md`
- Create: `docs/runbooks/2026-06-29-sellform-smartstore-connection-runbook.md`

- [ ] **Step 1: 전체 테스트**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_secrets.py tests/test_smartstore_transformer.py tests/test_smartstore_adapter.py tests/test_smartstore_registration_api.py -q`

- [ ] **Step 2: 민감정보 검수**

DB, 로그, API 응답에 평문 secret·access token·Authorization 헤더가 없는지 확인한다.

- [ ] **Step 3: 실제 계정 검증**

사용자가 제공한 테스트 판매자 계정과 명시적 승인 아래에서만 live flag를 켠다. 상품명 앞에 `[SELLFORM TEST]`를 붙이고 등록 결과와 외부 상품 ID를 테스트 로그에 기록한다.

## 완료 기준

- 스마트스토어 초안 생성과 외부 전송이 분리된다.
- 사용자 승인 전에는 HTTP 상품 등록 요청이 0건이다.
- 승인 후 전송 데이터가 승인 스냅샷과 일치한다.
- 자격 증명이 암호화되고 로그에서 마스킹된다.
- 성공·검증 실패·인증 실패가 서로 다른 상태로 저장된다.
