# Sprint 38 - 마켓 등록 공통 상품 패키지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 상세페이지와 상품 정보를 외부 API 호출 없이 재현 가능한 공통 마켓 등록 패키지로 만든다.

**Architecture:** 최종 `DetailPageVersion`, 확인된 `ProductFact`, `ExportArtifact`, 프로젝트 데이터를 하나의 불변 JSON 스냅샷으로 조립한다. 패키지 생성, 공통 검증, ZIP 다운로드를 별도 서비스로 나누고 Sprint 39·40의 마켓 변환기가 이 패키지만 입력받게 한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pydantic, Python `hashlib`/`zipfile`, Next.js 14, Pytest, Playwright.

---

## 선행 조건

- Sprint 36의 최종 이미지 매핑
- Sprint 37의 `selected_style`
- 최종 지정된 `DetailPageVersion`
- 스마트스토어 또는 쿠팡 프리셋으로 완료된 `ExportArtifact`

## 파일 구조

- Create: `backend/src/schemas/marketplace.py`
- Create: `backend/src/services/marketplace_package_builder.py`
- Create: `backend/src/services/marketplace_package_validator.py`
- Create: `backend/src/services/marketplace_package_archive.py`
- Create: `backend/src/api/marketplaces.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/app.py`
- Create: `backend/tests/test_marketplace_package_builder.py`
- Create: `backend/tests/test_marketplace_package_api.py`
- Create: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/export/page.tsx`
- Create: `frontend/e2e/sprint38-marketplace-package.spec.ts`
- Create: `docs/testing/2026-06-29-sellform-sprint-38-marketplace-package-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-38-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-38-marketplace-package.md`

### Task 1: 공통 패키지 계약과 DB 스냅샷

**Files:**

- Create: `backend/src/schemas/marketplace.py`
- Modify: `backend/src/db/models.py`
- Test: `backend/tests/test_marketplace_package_builder.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_marketplace_package_snapshot_has_stable_hash(package_factory):
    first = package_factory()
    second = package_factory()
    assert first.payload_hash == second.payload_hash
    assert first.payload_json["schema_version"] == "marketplace_product_v1"
    assert first.payload_json["evidence"]["verified_fact_ids"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_builder.py -q`

Expected: `MarketplaceProductPackage` 또는 builder import failure.

- [ ] **Step 3: Pydantic 계약 정의**

`MarketplaceProductPayload`는 `title`, `category`, `brand`, `pricing`, `options`, `delivery`, `returns`, `compliance`, `assets`, `evidence`, `selected_style`, `page_version_id`를 필수 키로 정의한다. 금액과 재고는 음수를 거부한다.

- [ ] **Step 4: DB 모델 추가**

```python
class MarketplaceProductPackage(Base):
    __tablename__ = "marketplace_product_packages"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    page_version_id = Column(String(36), ForeignKey("detail_page_versions.id", ondelete="RESTRICT"), nullable=False)
    schema_version = Column(String(30), nullable=False, default="marketplace_product_v1")
    payload_json = Column(JSON, nullable=False)
    payload_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
```

- [ ] **Step 5: 모델 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_builder.py -q`

Expected: payload contract tests PASS.

### Task 2: 패키지 조립기와 공통 검증기

**Files:**

- Create: `backend/src/services/marketplace_package_builder.py`
- Create: `backend/src/services/marketplace_package_validator.py`
- Test: `backend/tests/test_marketplace_package_builder.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_builder_rejects_project_without_final_version(db_session, project):
    with pytest.raises(MarketplacePackageError, match="FINAL_VERSION_REQUIRED"):
        build_marketplace_package(db_session, project, user_id="user-1")

def test_validator_reports_actionable_field_paths(valid_payload):
    valid_payload["pricing"]["sale_price"] = None
    result = validate_common_package(valid_payload)
    assert result.status == "error"
    assert result.issues[0].field_path == "pricing.sale_price"
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_builder.py -q`

- [ ] **Step 3: 조립기 구현**

정렬된 JSON을 `json.dumps(payload, sort_keys=True, separators=(",", ":"))`로 직렬화하고 SHA-256 해시를 만든다. 확인된 사실 ID, 최종 버전 ID, 대표 이미지, 상세페이지 artifact 경로를 스냅샷에 포함한다.

- [ ] **Step 4: 공통 검증 구현**

필수 오류는 상품명, 카테고리, 판매가, 재고, 최종 버전, 대표 이미지, 상세페이지 artifact 누락이다. 경고는 브랜드·제조사·반품 정보 누락이다.

- [ ] **Step 5: 서비스 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_builder.py -q`

Expected: PASS.

### Task 3: 생성·조회·다운로드 API

**Files:**

- Create: `backend/src/services/marketplace_package_archive.py`
- Create: `backend/src/api/marketplaces.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_marketplace_package_api.py`

- [ ] **Step 1: API 실패 테스트 작성**

```python
def test_create_and_download_package(client, ready_project, headers):
    created = client.post(
        f"/api/v1/projects/{ready_project.id}/marketplace/packages",
        headers=headers,
    )
    assert created.status_code == 201
    package_id = created.json()["id"]
    downloaded = client.get(
        f"/api/v1/projects/{ready_project.id}/marketplace/packages/{package_id}/download",
        headers=headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
```

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_api.py -q`

Expected: 404 because router is not registered.

- [ ] **Step 3: API 구현**

```text
POST /api/v1/projects/{project_id}/marketplace/packages
GET  /api/v1/projects/{project_id}/marketplace/packages
GET  /api/v1/projects/{project_id}/marketplace/packages/{package_id}
GET  /api/v1/projects/{project_id}/marketplace/packages/{package_id}/download
```

ZIP에는 `product.json`, `validation.json`, `images/representative/`, `images/detail/`, `README.txt`만 포함한다. workspace 소유권이 다른 package는 `404`로 숨긴다.

- [ ] **Step 4: API 테스트 통과**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_api.py -q`

Expected: PASS.

### Task 4: 등록 준비 UI

**Files:**

- Create: `frontend/src/app/workspace/projects/[id]/marketplace/page.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/export/page.tsx`
- Create: `frontend/e2e/sprint38-marketplace-package.spec.ts`

- [ ] **Step 1: E2E 실패 테스트 작성**

테스트는 `마켓 등록 준비` 버튼, 공통 필수값 상태, 오류의 수정 링크, `등록 패키지 다운로드`를 검증한다.

- [ ] **Step 2: 실패 확인**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint38-marketplace-package.spec.ts`

- [ ] **Step 3: UI 구현**

외부 전송 버튼은 표시하지 않는다. 패키지 생성 결과가 `error`면 다운로드는 허용하되 “등록 불가 초안” 표시를 넣고, Sprint 39·40 진입 버튼은 비활성화한다.

- [ ] **Step 4: E2E 및 빌드 검증**

Run: `cd C:\page\frontend && npx.cmd playwright test e2e/sprint38-marketplace-package.spec.ts && npm.cmd run build`

Expected: E2E PASS, build succeeds.

### Task 5: 회귀 검증과 문서화

**Files:**

- Create: `docs/testing/2026-06-29-sellform-sprint-38-marketplace-package-test-log.md`
- Create: `docs/reviews/2026-06-29-sellform-sprint-38-code-review.md`
- Create: `docs/troubleshooting/2026-06-29-sellform-sprint-38-marketplace-package.md`

- [ ] **Step 1: 백엔드 회귀 테스트**

Run: `cd C:\page\backend && uv run pytest tests/test_marketplace_package_builder.py tests/test_marketplace_package_api.py tests/test_exports.py tests/test_pages.py -q`

- [ ] **Step 2: 보안 확인**

다른 workspace 접근이 `404`, ZIP 경로 순회가 차단되고 package JSON에 API 키가 없음을 기록한다.

- [ ] **Step 3: 문서 산출물 작성**

테스트 명령·결과, 발견 이슈, 남은 위험, 수동 복구 절차를 각 문서에 남긴다.

## 완료 기준

- 최종 상세페이지를 불변 공통 상품 패키지로 생성한다.
- 같은 입력은 같은 해시를 만들고, 입력 변경은 새 패키지를 만든다.
- 외부 마켓 API를 호출하지 않는다.
- ZIP만으로 상품 데이터와 이미지 산출물을 재현할 수 있다.
- Sprint 39·40이 동일한 패키지 ID를 입력으로 사용한다.
