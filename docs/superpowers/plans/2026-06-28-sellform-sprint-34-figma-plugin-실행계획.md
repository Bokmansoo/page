# Sprint 34 Sellform Figma Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일회용 코드 또는 JSON 패키지를 사용해 Sellform 상세페이지를 현재 열린 Figma Design 파일에 편집 가능한 네이티브 노드로 생성한다.

**Architecture:** FastAPI는 tenant 검증, canonical payload snapshot, 단일 사용 ticket과 임시 asset session을 담당한다. Figma Plugin iframe UI는 API/파일 입력을 처리하고, Plugin main thread는 네트워크와 분리된 renderer로 Frame, TextNode, ImagePaint를 생성한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Next.js 14, TypeScript, esbuild, Jest, Figma Plugin API, Playwright, pytest.

---

## File map

### Backend

- Create: `backend/src/services/figma_plugin_ticket_service.py`
- Create: `backend/src/services/figma_plugin_package_service.py`
- Create: `backend/src/api/figma_plugin.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/db/database.py`
- Modify: `backend/src/app.py`
- Modify: `backend/src/config.py`
- Test: `backend/tests/test_figma_plugin_ticket_service.py`
- Test: `backend/tests/test_figma_plugin_api.py`

### Figma Plugin

- Create: `integrations/figma-plugin/manifest.template.json`
- Create: `integrations/figma-plugin/package.json`
- Create: `integrations/figma-plugin/tsconfig.json`
- Create: `integrations/figma-plugin/scripts/configure-manifest.mjs`
- Create: `integrations/figma-plugin/src/contracts.ts`
- Create: `integrations/figma-plugin/src/payload-validator.ts`
- Create: `integrations/figma-plugin/src/renderer.ts`
- Create: `integrations/figma-plugin/src/code.ts`
- Create: `integrations/figma-plugin/src/ui.ts`
- Create: `integrations/figma-plugin/src/ui.html`
- Test: `integrations/figma-plugin/tests/payload-validator.test.ts`
- Test: `integrations/figma-plugin/tests/renderer.test.ts`
- Test: `integrations/figma-plugin/tests/ui-client.test.ts`

### Frontend and docs

- Create: `frontend/src/components/figma/FigmaPluginExportDialog.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/e2e/sprint34-figma-plugin-export.spec.ts`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `docs/superpowers/plans/2026-06-23-sellform-sprint-roadmap.md`
- Create: `docs/runbooks/2026-06-28-sellform-figma-plugin-runbook.md`
- Create: `docs/testing/2026-06-28-sellform-sprint-34-figma-plugin-test-log.md`
- Create: `docs/troubleshooting/2026-06-28-sellform-sprint-34-figma-plugin.md`
- Create: `docs/reviews/2026-06-28-sellform-sprint-34-code-review.md`

### Task 1: Ticket 모델과 보안 계약

**Files:**
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/db/database.py`
- Modify: `backend/src/config.py`
- Test: `backend/tests/test_figma_plugin_ticket_service.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_ticket_stores_hash_not_plain_code(db, project):
    issued = service.issue(project, user_id, payload, asset_map={})
    row = db.get(FigmaPluginExportTicket, issued.ticket_id)
    assert issued.code.startswith("SF-")
    assert issued.code not in row.code_hash
    assert row.status == "issued"

def test_ticket_expires_after_ten_minutes(db, project, frozen_time):
    issued = service.issue(project, user_id, payload, asset_map={})
    frozen_time.tick(datetime.timedelta(minutes=11))
    with pytest.raises(TicketExpired):
        service.redeem(issued.code)
```

- [ ] **Step 2: RED 확인**

Run:

```cmd
cd C:\page\backend
uv run pytest tests/test_figma_plugin_ticket_service.py -q
```

Expected: model과 service가 없어 FAIL.

- [ ] **Step 3: 모델·설정 구현**

```python
class FigmaPluginExportTicket(Base):
    __tablename__ = "figma_plugin_export_tickets"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    code_hash = Column(String(64), unique=True, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    asset_map_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="issued")
    expires_at = Column(DateTime, nullable=False)
    redeemed_at = Column(DateTime, nullable=True)
    session_token_hash = Column(String(64), nullable=True)
    session_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
```

`Settings`에 다음 필드를 추가한다.

```python
SELLFORM_FIGMA_PLUGIN_TICKET_SECRET: str = ""
SELLFORM_FIGMA_PLUGIN_TICKET_TTL_SECONDS: int = 600
SELLFORM_FIGMA_PLUGIN_SESSION_TTL_SECONDS: int = 600
SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES: int = 20 * 1024 * 1024
```

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_figma_plugin_ticket_service.py -q`

Expected: ticket hash·만료 테스트 PASS.

### Task 2: 일회용 코드 발급·교환 서비스

**Files:**
- Create: `backend/src/services/figma_plugin_ticket_service.py`
- Test: `backend/tests/test_figma_plugin_ticket_service.py`

- [ ] **Step 1: 재사용·동시 교환 실패 테스트 추가**

```python
def test_ticket_can_be_redeemed_only_once(db, issued):
    first = service.redeem(issued.code)
    assert first.payload["schema_version"] == "1.0"
    with pytest.raises(TicketAlreadyRedeemed):
        service.redeem(issued.code)

def test_redeem_returns_asset_session_without_persisting_plain_token(db, issued):
    result = service.redeem(issued.code)
    row = db.get(FigmaPluginExportTicket, issued.ticket_id)
    assert result.asset_session_token
    assert result.asset_session_token not in row.session_token_hash
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_figma_plugin_ticket_service.py -q`

Expected: redeem 동작이 없어 FAIL.

- [ ] **Step 3: 최소 구현**

```python
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"SF-{raw[:4]}-{raw[4:]}"

def _digest(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
```

`redeem()`은 정규화된 코드 hash로 row를 조회하고 PostgreSQL에서는
`with_for_update()`를 적용한다. 성공 시 `redeemed`, `redeemed_at`,
`session_token_hash`, `session_expires_at`을 한 transaction에서 저장한다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_figma_plugin_ticket_service.py -q`

Expected: 단일 사용·session 테스트 PASS.

### Task 3: Plugin API와 asset binary endpoint

**Files:**
- Create: `backend/src/api/figma_plugin.py`
- Modify: `backend/src/app.py`
- Test: `backend/tests/test_figma_plugin_api.py`

- [ ] **Step 1: API 실패 테스트 작성**

```python
def test_issue_ticket_requires_project_tenant(client, other_workspace_headers, project):
    response = client.post(
        f"/api/v1/projects/{project.id}/page/figma-plugin/tickets",
        headers=other_workspace_headers,
    )
    assert response.status_code == 404

def test_plugin_redeem_is_single_use(client, issued_code):
    assert client.post("/api/v1/figma-plugin/import", json={"code": issued_code}).status_code == 200
    assert client.post("/api/v1/figma-plugin/import", json={"code": issued_code}).status_code == 409

def test_asset_requires_matching_session(client, asset_ref):
    response = client.get(f"/api/v1/figma-plugin/assets/{asset_ref}")
    assert response.status_code == 401
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_figma_plugin_api.py -q`

Expected: router가 없어 FAIL.

- [ ] **Step 3: endpoint 구현**

```python
@router.post("/projects/{project_id}/page/figma-plugin/tickets")
def issue_ticket(project_id: str, db: Session = Depends(get_db), ctx=Depends(require_editor)):
    project = get_tenant_project(db, project_id, ctx.workspace_id)
    page = require_project_page(db, project_id)
    payload, asset_map = build_plugin_snapshot(project, page, db)
    return FigmaPluginTicketService(db).issue(project, ctx.user_id, payload, asset_map)

@public_router.post("/figma-plugin/import")
def redeem_ticket(body: RedeemTicketRequest, db: Session = Depends(get_db)):
    return FigmaPluginTicketService(db).redeem(body.code)
```

asset endpoint는 bearer session HMAC과 `asset_ref` 소속을 확인한 뒤 `FileResponse`로
반환한다. import/assets/OPTIONS 경로에만 `Access-Control-Allow-Origin: *`,
허용 method, `Content-Type, Authorization` header를 설정한다. 쿠키는 사용하지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_figma_plugin_api.py -q`

Expected: tenant, single-use, asset auth 테스트 PASS.

### Task 4: JSON + embedded asset fallback

**Files:**
- Create: `backend/src/services/figma_plugin_package_service.py`
- Modify: `backend/src/api/figma_plugin.py`
- Test: `backend/tests/test_figma_plugin_api.py`

- [ ] **Step 1: package 테스트 작성**

```python
def test_json_package_embeds_assets(client, headers, project, png_asset):
    response = client.get(
        f"/api/v1/projects/{project.id}/page/figma-plugin/package.json",
        headers=headers,
    )
    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["embedded_assets"][0]["mime_type"] == "image/png"
    assert base64.b64decode(body["embedded_assets"][0]["base64"])

def test_json_package_rejects_over_twenty_megabytes(client, headers, oversized_assets):
    response = client.get(package_url, headers=headers)
    assert response.status_code == 413
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_figma_plugin_api.py -q`

Expected: package endpoint 부재로 FAIL.

- [ ] **Step 3: package service 구현**

package service는 canonical payload의 `image_url`을 `asset_ref`로 바꾸고 다음 구조를
만든다.

```json
{
  "schema_version": "1.0",
  "payload": {"project": {}, "brand": {}, "page": {}, "cuts": []},
  "embedded_assets": [
    {"asset_ref": "asset_01", "mime_type": "image/png", "base64": "..."}
  ]
}
```

누적 byte가 설정 상한을 넘으면 `PackageTooLarge`를 발생시킨다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_figma_plugin_api.py -q`

Expected: JSON fallback 테스트 PASS.

### Task 5: Figma Plugin 프로젝트와 manifest 구성

**Files:**
- Create: `integrations/figma-plugin/package.json`
- Create: `integrations/figma-plugin/tsconfig.json`
- Create: `integrations/figma-plugin/manifest.template.json`
- Create: `integrations/figma-plugin/scripts/configure-manifest.mjs`
- Modify: `.gitignore`

- [ ] **Step 1: manifest 생성 스크립트 테스트 작성**

`scripts/configure-manifest.test.mjs`에서 숫자가 아닌 ID를 거부하고 숫자 ID를 넣었을
때 `manifest.json`에 `documentAccess: dynamic-page`, `editorType: ["figma"]`,
`devAllowedDomains: ["http://127.0.0.1:8000"]`가 생성되는지 검증한다.

- [ ] **Step 2: RED 확인**

Run:

```cmd
cd C:\page\integrations\figma-plugin
npm.cmd test
```

Expected: package와 script가 없어 FAIL.

- [ ] **Step 3: 프로젝트 구성**

`package.json` script:

```json
{
  "scripts": {
    "configure": "node scripts/configure-manifest.mjs",
    "build": "node esbuild.mjs",
    "test": "jest --runInBand",
    "watch": "node esbuild.mjs --watch"
  }
}
```

`manifest.template.json`:

```json
{
  "name": "Sellform Detail Page Importer",
  "api": "1.0.0",
  "editorType": ["figma"],
  "main": "dist/code.js",
  "ui": "dist/ui.html",
  "documentAccess": "dynamic-page",
  "networkAccess": {
    "allowedDomains": ["none"],
    "devAllowedDomains": ["http://127.0.0.1:8000"]
  }
}
```

configure script는 대화형으로 Figma가 발급한 숫자 plugin ID를 받고 template에 `id`를
추가해 untracked `manifest.json`을 생성한다.

- [ ] **Step 4: GREEN 확인**

Run: `npm.cmd test`

Expected: manifest 구성 테스트 PASS.

### Task 6: Payload validator와 네이티브 Figma renderer

**Files:**
- Create: `integrations/figma-plugin/src/contracts.ts`
- Create: `integrations/figma-plugin/src/payload-validator.ts`
- Create: `integrations/figma-plugin/src/renderer.ts`
- Test: `integrations/figma-plugin/tests/payload-validator.test.ts`
- Test: `integrations/figma-plugin/tests/renderer.test.ts`

- [ ] **Step 1: validator·renderer 실패 테스트 작성**

```ts
expect(() => validatePackage({ schema_version: '2.0' }))
  .toThrow('UNSUPPORTED_SCHEMA_VERSION');

const result = await renderDetailPage(validPackage, imageBytes, figmaMock);
expect(result.root.width).toBe(860);
expect(result.root.layoutMode).toBe('VERTICAL');
expect(result.sections).toHaveLength(7);
expect(result.warnings).toContainEqual(
  expect.objectContaining({ code: 'IMAGE_PLACEHOLDER_USED' }),
);
```

- [ ] **Step 2: RED 확인**

Run: `npm.cmd test -- renderer.test.ts payload-validator.test.ts`

Expected: validator와 renderer가 없어 FAIL.

- [ ] **Step 3: renderer 구현**

renderer는 다음 순서로 실행한다.

```ts
const root = figma.createFrame();
root.name = `Sellform / ${payload.project.name}`;
root.resize(860, 100);
root.layoutMode = 'VERTICAL';
root.primaryAxisSizingMode = 'AUTO';
root.counterAxisSizingMode = 'FIXED';
```

각 cut마다 section frame, headline, subcopy, supporting text를 만들고
`figma.loadFontAsync()` 후 characters를 설정한다. 이미지 byte가 있으면
`figma.createImage(bytes)` hash를 RectangleNode ImagePaint에 적용하고, 없으면
placeholder를 만든다.

- [ ] **Step 4: GREEN 확인**

Run: `npm.cmd test -- renderer.test.ts payload-validator.test.ts`

Expected: 860px, 7단, 텍스트, 이미지 격리 테스트 PASS.

### Task 7: Plugin UI 코드 교환과 JSON import

**Files:**
- Create: `integrations/figma-plugin/src/ui.html`
- Create: `integrations/figma-plugin/src/ui.ts`
- Create: `integrations/figma-plugin/src/code.ts`
- Test: `integrations/figma-plugin/tests/ui-client.test.ts`

- [ ] **Step 1: 실패 테스트 작성**

```ts
it('normalizes and redeems a Sellform code', async () => {
  const result = await client.importCode('sf 8k4p 2m7q');
  expect(fetchMock).toHaveBeenCalledWith(
    'http://127.0.0.1:8000/api/v1/figma-plugin/import',
    expect.objectContaining({ method: 'POST' }),
  );
  expect(result.payload.schema_version).toBe('1.0');
});

it('parses the JSON fallback through the same validator', async () => {
  expect(await client.importJson(file)).toEqual(validatedPackage);
});
```

- [ ] **Step 2: RED 확인**

Run: `npm.cmd test -- ui-client.test.ts`

Expected: UI client가 없어 FAIL.

- [ ] **Step 3: UI와 message bridge 구현**

UI는 code 제출 후 payload를 받고 asset endpoint를 bearer session으로 호출한다.
이미지는 `Uint8Array`로 변환해 다음 메시지를 보낸다.

```ts
parent.postMessage({
  pluginMessage: {
    type: 'render-package',
    package: validatedPackage,
    imageBytesByRef,
  },
}, '*');
```

main thread는 renderer 결과를 UI로 반환하고 root를 선택한다.

```ts
figma.currentPage.selection = [result.root];
figma.viewport.scrollAndZoomIntoView([result.root]);
figma.ui.postMessage({ type: 'render-complete', warnings: result.warnings });
```

- [ ] **Step 4: build와 GREEN 확인**

Run:

```cmd
npm.cmd test
npm.cmd run build
```

Expected: plugin 테스트와 esbuild 성공.

### Task 8: Sellform 발급·복사·JSON UI

**Files:**
- Create: `frontend/src/components/figma/FigmaPluginExportDialog.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/e2e/sprint34-figma-plugin-export.spec.ts`

- [ ] **Step 1: E2E 실패 테스트 작성**

테스트는 `Figma 플러그인으로 보내기` 클릭, code 발급, 복사, 만료 표시, JSON 다운로드
링크를 검증한다. 화면에는 OAuth 링크와 기존 `Figma Live 내보내기` 입력창이 없어야 한다.

- [ ] **Step 2: RED 확인**

Run:

```cmd
cd C:\page\frontend
npx.cmd playwright test e2e/sprint34-figma-plugin-export.spec.ts
```

Expected: 새 dialog가 없어 FAIL.

- [ ] **Step 3: UI 구현**

dialog 상태는 `idle`, `issuing`, `issued`, `expired`, `failed`만 사용한다. issued 화면은
코드, 남은 시간, 복사 버튼, 새 코드 버튼, JSON 다운로드 버튼, 플러그인 실행 안내를
표시한다. 기존 Remote MCP 버튼은 기본 화면에서 제거한다.

- [ ] **Step 4: GREEN과 빌드 확인**

Run:

```cmd
npx.cmd playwright test e2e/sprint34-figma-plugin-export.spec.ts
npm.cmd run build
```

Expected: E2E와 production build PASS.

### Task 9: 환경·운영 문서·실제 Figma 검수

**Files:**
- Modify: `.env.example`
- Modify: `.gitignore`
- Create: `docs/runbooks/2026-06-28-sellform-figma-plugin-runbook.md`
- Create: `docs/testing/2026-06-28-sellform-sprint-34-figma-plugin-test-log.md`
- Create: `docs/troubleshooting/2026-06-28-sellform-sprint-34-figma-plugin.md`
- Create: `docs/reviews/2026-06-28-sellform-sprint-34-code-review.md`

- [ ] **Step 1: 환경 예시 추가**

```dotenv
SELLFORM_FIGMA_MCP_ENABLED=false
SELLFORM_FIGMA_PLUGIN_TICKET_SECRET=
SELLFORM_FIGMA_PLUGIN_TICKET_TTL_SECONDS=600
SELLFORM_FIGMA_PLUGIN_SESSION_TTL_SECONDS=600
SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES=20971520
```

운영에서는 빈 secret으로 서버가 시작되지 않게 fail-closed 처리한다.

- [ ] **Step 2: 로컬 플러그인 설치 runbook 작성**

Figma 메뉴 `Plugins → Development → New plugin`, 생성된 plugin ID 확인,
`npm.cmd run configure`, `npm.cmd run build`, 개발 플러그인 실행 순서를 기록한다.

- [ ] **Step 3: 실제 수동 QA**

- 빈 Figma Design 파일에 코드를 입력한다.
- 860px 루트와 7개 섹션이 생성되는지 확인한다.
- 텍스트를 직접 수정한다.
- 이미지가 Image Fill인지 확인한다.
- 같은 코드를 다시 입력해 거부되는지 확인한다.
- 서버를 끄고 JSON fallback으로 같은 구조가 생성되는지 확인한다.
- 결과 스크린샷을 테스트 로그에 연결한다.

- [ ] **Step 4: 전체 검증**

```cmd
cd C:\page\backend
uv run pytest tests -q --basetemp=.pytest-tmp-sprint34

cd C:\page\integrations\figma-plugin
npm.cmd test
npm.cmd run build

cd C:\page\frontend
npm.cmd run build
npx.cmd playwright test e2e/sprint34-figma-plugin-export.spec.ts
```

Expected: 자동 테스트·빌드 PASS와 실제 Figma QA 증적 1건.

## 최종 완료 기준

- [ ] code 원문과 session token 원문이 DB·로그에 남지 않는다.
- [ ] code는 10분 유효하고 한 번만 교환된다.
- [ ] plugin은 canonical payload 1.0만 렌더링한다.
- [ ] 860px 편집 가능한 7단 상세페이지가 생성된다.
- [ ] 이미지 실패가 전체 생성을 막지 않는다.
- [ ] JSON fallback이 같은 renderer를 사용한다.
- [ ] MCP 403과 무관하게 Plugin과 PNG export가 동작한다.
- [ ] 리뷰·테스트·트러블슈팅·runbook 문서가 갱신된다.

