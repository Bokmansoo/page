# Sprint 34 Figma Plugin Integration Code Review

## 1. Overview
In Sprint 34, we integrated the Figma Plugin export flow. This allows design assets and page layout specifications to be imported directly into Figma using a single-use token exchange or a fallback offline JSON package download. All frontend/backend tests pass successfully, and the production build compiles with zero errors.

---

## 2. Key Code Changes

### Database & Models
- **`backend/src/db/models.py`**: Added `FigmaPluginExportTicket` model containing `code_hash`, `payload_json`, `asset_map_json`, and temporary session token hashes (`session_token_hash`, `session_expires_at`).

### Core Services
- **`backend/src/services/figma_plugin_ticket_service.py`**: Handles ticket generation with a readable format `SF-XXXX-XXXX`, secure hmac digest hashing, and single-use `redeem` execution with row locking.
- **`backend/src/services/figma_plugin_package_service.py`**: Handles generating fallback offline packages, embedding base64 encoded binary assets, and enforcing the 20MB payload limit.

### API Endpoints
- **`backend/src/api/figma_plugin.py`**: Exposes the FastAPI routes for ticket issuance (`/projects/{id}/page/figma-plugin/tickets`), ticket redemption (`/figma-plugin/import`), secure asset streaming (`/figma-plugin/assets/{asset_ref}`), and package generation (`/projects/{id}/page/figma-plugin/package.json`).

### Figma Plugin Code
- **`integrations/figma-plugin/src/payload-validator.ts`**: Verifies schema version `1.0` and presence of required fields.
- **`integrations/figma-plugin/src/renderer.ts`**: Renders frame, padding, auto-layout flow, image slots/placeholders, and text styling using the Figma Canvas API.
- **`integrations/figma-plugin/src/ui.ts`**: Binds Figma plugin UI tabs, inputs, and fetches backend endpoints.

### Frontend UI Components
- **`frontend/src/components/figma/FigmaExportDialog.tsx`**: Updated with a dual tab interface layout ("Figma Live 자동 내보내기" and "피그마 플러그인 연동") to show generated codes, copy to clipboard action, and trigger download package file operations.

---

## 3. Test Verification Log

### Backend Unit Tests
- `backend/tests/test_figma_plugin_ticket_service.py`: Passes 4 tests verifying ticket hashing, TTL expiration, single-use logic, and session mapping.
- `backend/tests/test_figma_plugin_api.py`: Passes 5 tests verifying API tenants checks, single-use imports, session asset downloads, and package file sizes limits.
```
backend/tests/test_figma_plugin_ticket_service.py::test_ticket_stores_hash_not_plain_code PASSED
backend/tests/test_figma_plugin_ticket_service.py::test_ticket_expires_after_ten_minutes PASSED
backend/tests/test_figma_plugin_ticket_service.py::test_ticket_can_be_redeemed_only_once PASSED
backend/tests/test_figma_plugin_ticket_service.py::test_redeem_returns_asset_session_without_persisting_plain_token PASSED

backend/tests/test_figma_plugin_api.py::test_issue_ticket_requires_project_tenant PASSED
backend/tests/test_figma_plugin_api.py::test_plugin_redeem_is_single_use PASSED
backend/tests/test_figma_plugin_api.py::test_asset_requires_matching_session PASSED
backend/tests/test_figma_plugin_api.py::test_json_package_embeds_assets PASSED
backend/tests/test_figma_plugin_api.py::test_json_package_rejects_over_twenty_megabytes PASSED
```

### Figma Plugin Unit Tests
- `integrations/figma-plugin/scripts/configure-manifest.test.mjs`: Passes 2 tests verifying interactive plugin ID inputs.
- `integrations/figma-plugin/tests/payload-validator.test.ts`: Passes 4 tests verifying contract version checks.
- `integrations/figma-plugin/tests/renderer.test.ts`: Passes 2 tests verifying auto-layout rendering and warning placeholders.
- `integrations/figma-plugin/tests/ui-client.test.ts`: Passes 2 tests verifying fetch calls normalization.
```
PASS scripts/configure-manifest.test.mjs (10 passed)
PASS tests/ui-client.test.ts
PASS tests/renderer.test.ts
PASS tests/payload-validator.test.ts
```

### Frontend Production Build
```
next build -> Compiled successfully with zero compilation or ESLint errors.
```

---

## 4. 보완 재검토 결과 (2026-06-28)

최초 리뷰는 단위 테스트 통과만으로 완료 판정을 내려 실제 API와 플러그인
사이의 응답 계약 불일치를 놓쳤다. 보완 검토에서 아래 항목을 수정했다.

- 교환 API와 UI client의 `schema_version` 계약 통일
- 32자 미만 ticket secret fail-closed
- 티켓 코드 entropy 40bit 이상 확보
- 잘못된 코드 5분당 10회 제한
- Base64 포함 최종 JSON 크기 제한
- API와 validator의 canonical 7단 강제
- Figma 여백 좌우 56px·상하 64px 적용
- 요청 폰트 실패 시 Inter fallback
- Remote MCP 대신 플러그인 흐름을 기본 화면으로 전환
- Sprint 34 Playwright E2E, 테스트 로그, 트러블슈팅 문서 추가

### 보완 후 판정

- 자동화 범위: 통과
- 실제 Figma Desktop 수동 검수: 미실행
- 최종 상태: **자동 구현 완료, 실제 Figma 수동 QA 증적 대기**
