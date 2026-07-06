# Sprint 40 - 쿠팡 승인형 등록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공통 상품 패키지를 쿠팡 상품 생성 규격으로 변환하고, 사용자 승인 후에만 쿠팡 Open API로 전송한다.

**Architecture:** Sprint 39의 계정·초안·승인·submission 모델을 재사용한다. 쿠팡 전용 HMAC 서명기, 카테고리·고시 검증기, 요청 변환기, 어댑터만 추가하여 네이버 로직과 결합하지 않는다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pydantic, `httpx`, Python `hmac`/`hashlib`, Next.js 14, Pytest, Playwright.

---

## 공식 기준

- [쿠팡 상품 생성 API](https://developers.coupangcorp.com/hc/ko/articles/360033877853-%EC%83%81%ED%92%88-%EC%83%9D%EC%84%B1)
- [쿠팡 OPEN API 상품 등록 가이드](https://developers.coupangcorp.com/hc/ko/articles/360034889893-OPEN-API-%EC%83%81%ED%92%88-%EB%93%B1%EB%A1%9D-%EA%B0%80%EC%9D%B4%EB%93%9C)

## 파일 구조

- Modify: `backend/src/config.py`
- Create: `backend/src/services/coupang_signer.py`
- Create: `backend/src/services/coupang_transformer.py`
- Create: `backend/src/services/coupang_validator.py`
- Create: `backend/src/services/coupang_adapter.py`
- Modify: `backend/src/api/marketplaces.py`
- Create: `backend/tests/test_coupang_signer.py`
- Create: `backend/tests/test_coupang_transformer.py`
- Create: `backend/tests/test_coupang_adapter.py`
- Create: `backend/tests/test_coupang_registration_api.py`
- Modify: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Create: `frontend/e2e/sprint40-coupang-registration.spec.ts`
- Create: `docs/testing/2026-06-29-sellform-sprint-40-coupang-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-40-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-40-coupang.md`
- Create: `docs/runbooks/2026-06-29-sellform-coupang-connection-runbook.md`

### Task 1: 쿠팡 서명기

**Files:**

- Create: `backend/src/services/coupang_signer.py`
- Test: `backend/tests/test_coupang_signer.py`

- [ ] **Step 1: 고정 시각 서명 실패 테스트 작성**

```python
def test_signer_is_deterministic_for_fixed_datetime():
    signer = CoupangSigner("access-key", "secret-key")
    header = signer.authorization(
        method="POST",
        path="/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        query="",
        datetime_value="260629T010203Z",
    )
    assert header.startswith("CEA algorithm=HmacSHA256")
    assert "access-key=access-key" in header
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_signer.py -q`

- [ ] **Step 3: 서명기 구현**

서명 입력 문자열과 헤더 형식은 공식 문서를 그대로 캡슐화한다. secret key와 완성된 Authorization 값은 `repr`, 예외, 로그에 포함하지 않는다.

- [ ] **Step 4: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_signer.py -q`

### Task 2: 쿠팡 변환기와 필수값 검증

**Files:**

- Create: `backend/src/services/coupang_transformer.py`
- Create: `backend/src/services/coupang_validator.py`
- Test: `backend/tests/test_coupang_transformer.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_transformer_maps_required_seller_product_fields(valid_package):
    request = transform_to_coupang(valid_package, coupang_inputs)
    assert request["displayCategoryCode"] == coupang_inputs["display_category_code"]
    assert request["sellerProductName"] == valid_package["title"]
    assert request["returnCenterCode"] == coupang_inputs["return_center_code"]
    assert request["items"][0]["salePrice"] == valid_package["pricing"]["sale_price"]

def test_validator_requires_notice_and_shipping_centers(valid_package):
    result = validate_coupang(valid_package, {"display_category_code": "123"})
    codes = {issue.code for issue in result.issues}
    assert "COUPANG_OUTBOUND_CENTER_REQUIRED" in codes
    assert "COUPANG_NOTICE_REQUIRED" in codes
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_transformer.py -q`

- [ ] **Step 3: 변환·검증 구현**

출고지, 반품지, 카테고리, 고시정보, 옵션, 판매가, 재고, 대표 이미지, 상세 이미지가 모두 준비되어야 `ready`다. 한 공통 필드를 여러 쿠팡 필드에 복사한 경우 `transform_notes`에 기록한다.

- [ ] **Step 4: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_transformer.py -q`

### Task 3: 쿠팡 HTTP 어댑터

**Files:**

- Create: `backend/src/services/coupang_adapter.py`
- Modify: `backend/src/config.py`
- Test: `backend/tests/test_coupang_adapter.py`

- [ ] **Step 1: mock transport 실패 테스트**

```python
def test_adapter_signs_exact_request_and_normalizes_success(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api-gateway.coupang.com/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        json={"code": "SUCCESS", "data": 123456},
    )
    result = adapter.create_product(payload)
    assert result.external_product_id == "123456"
    assert result.status == "submitted"
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_adapter.py -q`

- [ ] **Step 3: 어댑터 구현**

`SELLFORM_COUPANG_LIVE_SUBMISSION_ENABLED=false`를 기본값으로 둔다. 어댑터는 create, approval request, status lookup 세 메서드만 제공한다. 4xx는 재시도 불가, 429·5xx·timeout은 재시도 가능으로 정규화한다.

- [ ] **Step 4: 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_adapter.py -q`

### Task 4: 쿠팡 초안·승인·전송 API

**Files:**

- Modify: `backend/src/api/marketplaces.py`
- Test: `backend/tests/test_coupang_registration_api.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_coupang_submit_uses_one_idempotency_key(client, approved_draft, headers):
    first = client.post(
        f"/api/v1/projects/{approved_draft.project_id}/marketplace/drafts/{approved_draft.id}/submit",
        headers=headers,
    )
    second = client.post(
        f"/api/v1/projects/{approved_draft.project_id}/marketplace/drafts/{approved_draft.id}/submit",
        headers=headers,
    )
    assert first.json()["submission_id"] == second.json()["submission_id"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_registration_api.py -q`

- [ ] **Step 3: API 확장**

```text
POST /api/v1/projects/{project_id}/marketplace/coupang/drafts
POST /api/v1/projects/{project_id}/marketplace/drafts/{draft_id}/approve
POST /api/v1/projects/{project_id}/marketplace/drafts/{draft_id}/submit
GET  /api/v1/projects/{project_id}/marketplace/submissions/{submission_id}
```

동일 draft와 payload hash의 submit은 기존 submission을 반환한다. 다른 hash면 새 승인 없이는 차단한다.

- [ ] **Step 4: API 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_registration_api.py -q`

### Task 5: 쿠팡 검토 UI

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Create: `frontend/e2e/sprint40-coupang-registration.spec.ts`

- [ ] **Step 1: E2E 실패 테스트**

출고지·반품지 선택, 카테고리·고시 입력, 옵션 미리보기, 승인 전 차단, 중복 클릭 방지를 검증한다.

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint40-coupang-registration.spec.ts`

- [ ] **Step 3: UI 구현**

스마트스토어와 쿠팡 입력값을 한 폼에 섞지 않는다. 마켓 탭을 분리하고 공통값은 읽기 전용 요약으로 표시한다.

- [ ] **Step 4: E2E·빌드 검증**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint40-coupang-registration.spec.ts && npm.cmd run build`

### Task 6: 통합 검증과 문서

**Files:**

- Create: `docs/testing/2026-06-29-sellform-sprint-40-coupang-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-40-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-40-coupang.md`
- Create: `docs/runbooks/2026-06-29-sellform-coupang-connection-runbook.md`

- [ ] **Step 1: 전체 테스트**

Run: `cd C:\page\backend && uv run pytest tests/test_coupang_signer.py tests/test_coupang_transformer.py tests/test_coupang_adapter.py tests/test_coupang_registration_api.py -q`

- [ ] **Step 2: 비밀·중복 검수**

secret key와 Authorization 마스킹, 더블클릭·timeout 후 재시도 시 submission 1개 유지를 확인한다.

- [ ] **Step 3: 테스트 계정 수동 검증**

명시적 승인과 live flag 아래 테스트 상품 1건만 생성하고 외부 상품 ID 및 상태 조회 결과를 기록한다.

## 완료 기준

- 쿠팡 필수값 누락을 외부 호출 전에 모두 표시한다.
- 사용자 승인 전 상품 생성 요청은 0건이다.
- 동일 승인 요청의 반복 실행이 중복 상품을 만들지 않는다.
- 쿠팡 자격 증명과 서명값이 노출되지 않는다.
- 네이버 연동 코드 변경 없이 쿠팡 채널이 추가된다.
