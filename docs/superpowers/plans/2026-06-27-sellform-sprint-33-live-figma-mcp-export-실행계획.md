# Sprint 33 - 실제 Figma MCP 프레임 내보내기 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint 32에서 생성한 Figma design payload를 실제 Figma 파일의 편집 가능한 상세페이지 프레임으로 전송하고, 사용자가 Sellform에서 결과 링크와 실패 원인을 확인할 수 있게 한다.

**Architecture:** Sellform 백엔드는 프로젝트 권한, payload 생성, 내보내기 작업 상태를 책임지고, 선택형 로컬 `figma-bridge`가 Figma 원격 MCP의 OAuth 인증과 write-to-canvas 호출을 담당한다. Figma 연동이 꺼져 있거나 실패해도 Sellform의 페이지 편집과 PNG 내보내기는 계속 동작한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Next.js 14, TypeScript, Model Context Protocol TypeScript SDK v1, Figma Remote MCP, Playwright, pytest.

---

## 1. 배경과 결정

Sprint 32의 완료 범위는 다음과 같다.

- Sellform 페이지와 커머스 컷을 Figma design payload로 변환한다.
- page-editor에 `Figma로 내보내기` 버튼이 있다.
- MCP 연결이 없으면 `disabled` 또는 `not_configured` 상태와 payload를 반환한다.

아직 실제 Figma 캔버스에는 프레임이 생성되지 않는다. Sprint 33은 이 간극만 닫는다.

Figma 원격 MCP는 AI/MCP 클라이언트가 네이티브 Figma 콘텐츠를 캔버스에 작성할 수 있다. 원격 서버 주소는 `https://mcp.figma.com/mcp`이며 사용자 OAuth 인증이 필요하다. Sellform API 서버가 사용자 브라우저 인증 상태를 직접 소유하지 않도록, 로컬에서 실행하는 별도 브리지가 인증과 MCP 호출을 담당한다.

### 이번 Sprint의 고정 결정

1. 사용자가 편집 권한을 가진 **기존 Figma Design 파일 URL**을 입력한다.
2. 해당 파일 안에 `Sellform / {상품명}` 최상위 프레임을 만든다.
3. 프레임 너비는 Sellform payload의 `canvas_width`를 사용하며 기본값은 `860px`이다.
4. 각 커머스 컷은 세로 Auto Layout 하위 프레임으로 생성한다.
5. 제목, 설명, 배지는 Figma TextNode로 생성해 편집 가능하게 유지한다.
6. 공개 HTTPS 이미지 URL만 Figma 이미지로 삽입한다.
7. 동일한 내보내기 작업을 재시도해도 같은 작업 ID로 중복 프레임을 만들지 않는다.
8. Figma가 실패해도 기존 Sellform 저장·PNG export에는 영향을 주지 않는다.

## 2. 범위

### 포함

- Figma 원격 MCP OAuth 연결 상태 확인
- 기존 Figma 파일 URL 검증
- 실제 Figma 캔버스에 상세페이지 프레임 생성
- 텍스트, 색상, 폰트, Auto Layout, 상품 이미지 반영
- 비동기 내보내기 작업과 상태 저장
- 성공 시 Figma 결과 URL 제공
- 인증 필요, 권한 부족, 이미지 접근 불가, MCP 장애를 구분한 오류 표시
- 재시도와 중복 생성 방지
- 백엔드·브리지·프론트 테스트와 실제 Figma 수동 QA

### 제외

- Figma 새 파일 자동 생성
- Figma에서 수정한 내용을 Sellform으로 가져오는 역동기화
- Figma 컴포넌트 라이브러리와 Code Connect
- 팀별 Figma OAuth 계정 관리
- 쿠팡·스마트스토어 자동 업로드
- Figma가 Sellform의 필수 렌더링 엔진이 되는 구조

## 3. 사용자 흐름

```text
page-editor
  → Figma로 내보내기
  → Figma 파일 URL 입력
  → 연결 상태 확인
  → 인증이 없으면 Figma 로그인/권한 승인
  → 내보내기 작업 생성
  → figma-bridge가 payload를 실제 프레임으로 변환
  → 성공: “Figma에서 열기”
  → 실패: 원인 표시 + 재시도
```

성공 기준 사용자 경험:

- 사용자는 버튼을 누른 뒤 Figma 파일 URL 한 번만 입력한다.
- 처리 중에는 `인증 확인 → 프레임 생성 → 이미지 삽입 → 완료` 상태가 보인다.
- 완료되면 새 프레임으로 이동하는 Figma URL을 바로 열 수 있다.

## 4. 파일 구조

### Backend

- Create: `backend/src/services/figma_bridge_client.py`
  - 브리지 HTTP 호출, 타임아웃, 오류 매핑을 전담한다.
- Create: `backend/src/services/figma_export_job_service.py`
  - 작업 생성, 상태 전이, 재시도, 멱등성을 전담한다.
- Modify: `backend/src/services/figma_mcp_adapter.py`
  - 주입형 sender 대신 운영용 bridge client를 선택적으로 사용한다.
- Modify: `backend/src/api/pages.py`
  - 실제 내보내기 요청·상태 조회·재시도 API를 제공한다.
- Modify: `backend/src/db/models.py`
  - `FigmaExportJob` 모델을 추가한다.
- Modify: `backend/src/config.py`
  - 브리지 URL, 타임아웃, OAuth callback 관련 설정을 추가한다.
- Test: `backend/tests/test_figma_bridge_client.py`
- Test: `backend/tests/test_figma_export_job_service.py`
- Test: `backend/tests/test_figma_live_export_api.py`

### Figma bridge

- Create: `integrations/figma-bridge/package.json`
- Create: `integrations/figma-bridge/tsconfig.json`
- Create: `integrations/figma-bridge/src/config.ts`
- Create: `integrations/figma-bridge/src/oauth-store.ts`
- Create: `integrations/figma-bridge/src/figma-mcp-client.ts`
- Create: `integrations/figma-bridge/src/figma-renderer.ts`
- Create: `integrations/figma-bridge/src/server.ts`
- Create: `integrations/figma-bridge/tests/figma-renderer.test.ts`
- Create: `integrations/figma-bridge/tests/server.test.ts`

### Frontend

- Create: `frontend/src/components/figma/FigmaExportDialog.tsx`
- Create: `frontend/src/components/figma/FigmaExportStatus.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/e2e/sprint33-live-figma-export.spec.ts`

### Documentation

- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Create: `docs/testing/2026-06-27-sellform-sprint-33-live-figma-export-test-log.md`
- Create: `docs/reviews/2026-06-27-sellform-sprint-33-code-review.md`
- Create: `docs/troubleshooting/2026-06-27-sellform-sprint-33-live-figma-export.md`
- Modify: `docs/runbooks/2026-06-27-sellform-figma-mcp-runbook.md`

## 5. 데이터 모델과 API 계약

### FigmaExportJob

```python
class FigmaExportJob(Base):
    __tablename__ = "figma_export_jobs"

    id: str
    project_id: str
    workspace_id: str
    target_file_url: str
    payload_hash: str
    status: str  # queued | authenticating | rendering | completed | failed
    result_file_url: str | None
    result_node_url: str | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime
```

허용 상태 전이:

```text
queued → authenticating → rendering → completed
queued → failed
authenticating → failed
rendering → failed
failed → queued
```

### 실제 내보내기 요청

```http
POST /api/v1/projects/{project_id}/page/figma/live-export
Content-Type: application/json

{
  "target_file_url": "https://www.figma.com/design/FILE_KEY/FILE_NAME"
}
```

성공 접수:

```json
{
  "job_id": "job-uuid",
  "status": "queued",
  "message": "Figma 내보내기 작업을 시작했습니다."
}
```

### 작업 상태 조회

```http
GET /api/v1/projects/{project_id}/page/figma/exports/{job_id}
```

완료 응답:

```json
{
  "job_id": "job-uuid",
  "status": "completed",
  "result_file_url": "https://www.figma.com/design/FILE_KEY/FILE_NAME",
  "result_node_url": "https://www.figma.com/design/FILE_KEY/FILE_NAME?node-id=12-34",
  "error_code": null,
  "error_message": null
}
```

### 브리지 내부 API

```http
POST http://127.0.0.1:3417/v1/exports
X-Sellform-Bridge-Token: <local-random-token>

{
  "job_id": "job-uuid",
  "target_file_url": "https://www.figma.com/design/FILE_KEY/FILE_NAME",
  "payload": {
    "project": {},
    "brand": {},
    "page": {},
    "cuts": []
  }
}
```

브리지의 오류 코드는 다음 값으로 제한한다.

- `AUTH_REQUIRED`
- `AUTH_DENIED`
- `INVALID_FIGMA_URL`
- `FILE_PERMISSION_DENIED`
- `ASSET_URL_NOT_PUBLIC`
- `MCP_UNAVAILABLE`
- `MCP_TOOL_UNSUPPORTED`
- `RENDER_FAILED`

## 6. 구현 작업

### Task 1. 실패하는 계약 테스트와 설정 추가

**Files:**

- Modify: `backend/src/config.py`
- Modify: `.env.example`
- Create: `backend/tests/test_figma_bridge_client.py`

- [ ] `SELLFORM_FIGMA_BRIDGE_URL`, `SELLFORM_FIGMA_BRIDGE_TOKEN`, `SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS` 설정을 읽는 테스트를 작성한다.
- [ ] 브리지가 `AUTH_REQUIRED`를 반환하면 클라이언트가 인증 필요 오류로 매핑하는 테스트를 작성한다.
- [ ] 브리지가 타임아웃되면 `MCP_UNAVAILABLE`로 매핑하는 테스트를 작성한다.
- [ ] 테스트가 구현 부재로 실패하는지 확인한다.

Run:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_figma_bridge_client.py -q
```

Expected: `figma_bridge_client` 모듈 부재 또는 설정 부재로 FAIL.

- [ ] 최소 구현을 추가하고 동일 명령이 통과하도록 한다.

### Task 2. 내보내기 작업 모델과 멱등성 구현

**Files:**

- Modify: `backend/src/db/models.py`
- Create: `backend/src/services/figma_export_job_service.py`
- Create: `backend/tests/test_figma_export_job_service.py`

- [ ] 동일 `project_id + target_file_url + payload_hash` 요청이 진행 중이면 기존 작업을 반환하는 실패 테스트를 작성한다.
- [ ] 완료 작업과 payload가 같으면 기존 결과 링크를 반환하는 실패 테스트를 작성한다.
- [ ] payload가 변경되면 새 작업을 만드는 실패 테스트를 작성한다.
- [ ] `failed` 작업 재시도 시 `attempt_count`가 증가하고 `queued`로 전이되는 테스트를 작성한다.
- [ ] PostgreSQL에서 동작하는 모델과 서비스의 최소 구현을 추가한다.

Run:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_figma_export_job_service.py -q
```

Expected: 모든 작업 상태·멱등성 테스트 PASS.

### Task 3. Figma bridge MCP 클라이언트와 OAuth 저장소 구현

**Files:**

- Create: `integrations/figma-bridge/package.json`
- Create: `integrations/figma-bridge/tsconfig.json`
- Create: `integrations/figma-bridge/src/config.ts`
- Create: `integrations/figma-bridge/src/oauth-store.ts`
- Create: `integrations/figma-bridge/src/figma-mcp-client.ts`
- Create: `integrations/figma-bridge/tests/server.test.ts`

- [ ] MCP 서버 URL 기본값을 `https://mcp.figma.com/mcp`로 둔다.
- [ ] OAuth 토큰은 저장소 파일 경로만 설정으로 받고 저장소 파일은 Git에 포함하지 않는다.
- [ ] 미인증 연결은 `AUTH_REQUIRED`와 인증 URL을 반환한다.
- [ ] 인증 완료 후 `listTools()` 결과에서 write-to-canvas 도구 지원 여부를 확인한다.
- [ ] 필요한 쓰기 도구가 없으면 `MCP_TOOL_UNSUPPORTED`를 반환한다.
- [ ] 브리지 토큰이 틀리면 `401`을 반환한다.

Run:

```cmd
cd integrations\figma-bridge
npm.cmd test
```

Expected: mock MCP transport를 사용하는 인증·도구 탐색 테스트 PASS.

### Task 4. Sellform payload를 네이티브 Figma 프레임으로 렌더링

**Files:**

- Create: `integrations/figma-bridge/src/figma-renderer.ts`
- Create: `integrations/figma-bridge/tests/figma-renderer.test.ts`

- [ ] payload의 `cuts` 순서를 유지하는 렌더 명령 생성 테스트를 작성한다.
- [ ] 최상위 프레임은 세로 Auto Layout, payload 너비, 24px 기본 간격을 사용한다.
- [ ] 각 컷은 `headline`, `subcopy`, `supporting_copy`를 별도 편집 가능한 텍스트 노드로 만든다.
- [ ] `brand.primary_color`와 `font_family`를 적용한다.
- [ ] `https://` 이미지 URL만 허용하고 `localhost`, `127.0.0.1`, `file://`는 `ASSET_URL_NOT_PUBLIC`로 거부한다.
- [ ] 이미지 비율은 원본을 유지하고 컷의 이미지 슬롯에 `FILL`로 배치한다.
- [ ] 결과에서 생성된 최상위 node ID와 node URL을 반환한다.

Run:

```cmd
cd integrations\figma-bridge
npm.cmd test
```

Expected: 렌더 명령, 이미지 URL 검증, 결과 URL 테스트 PASS.

### Task 5. 실제 내보내기 API와 adapter 연결

**Files:**

- Modify: `backend/src/services/figma_mcp_adapter.py`
- Modify: `backend/src/api/pages.py`
- Create: `backend/tests/test_figma_live_export_api.py`

- [ ] 다른 workspace의 프로젝트에는 `404`를 반환하는 테스트를 작성한다.
- [ ] page가 없으면 `409`를 반환하는 테스트를 작성한다.
- [ ] 유효한 요청이 job을 생성하고 bridge를 호출하는 테스트를 작성한다.
- [ ] 브리지 인증 필요·권한 부족·장애 응답이 작업 상태에 저장되는 테스트를 작성한다.
- [ ] 기존 `/page/figma/export` payload 준비 API는 그대로 유지한다.
- [ ] `FigmaMcpAdapter`가 설정이 있을 때만 `FigmaBridgeClient`를 사용하도록 구현한다.

Run:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_figma_export_api.py backend\tests\test_figma_live_export_api.py -q
```

Expected: 기존 Sprint 32 API와 신규 live export API 모두 PASS.

### Task 6. page-editor 내보내기 대화상자와 상태 UI 구현

**Files:**

- Create: `frontend/src/components/figma/FigmaExportDialog.tsx`
- Create: `frontend/src/components/figma/FigmaExportStatus.tsx`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

- [ ] `Figma로 내보내기` 클릭 시 파일 URL 입력 대화상자를 연다.
- [ ] `figma.com/design/` 형식이 아니면 요청 전에 오류를 표시한다.
- [ ] 접수 후 1초 간격으로 상태를 조회하되 2분 후 타임아웃한다.
- [ ] `AUTH_REQUIRED`이면 인증 URL을 새 탭으로 여는 버튼을 제공한다.
- [ ] 완료되면 `Figma에서 열기` 링크를 제공한다.
- [ ] 실패하면 오류 코드별 한국어 안내와 `재시도` 버튼을 제공한다.
- [ ] 대화상자를 닫아도 Sellform 페이지 편집 상태는 유지한다.

### Task 7. 프론트 E2E와 회귀 검증

**Files:**

- Create: `frontend/e2e/sprint33-live-figma-export.spec.ts`

- [ ] 파일 URL 검증 실패 시 API가 호출되지 않는 테스트를 작성한다.
- [ ] queued → rendering → completed 상태를 mock하고 결과 링크가 보이는지 테스트한다.
- [ ] `AUTH_REQUIRED` 응답에서 인증 버튼이 보이는지 테스트한다.
- [ ] Figma 실패 후에도 기존 PNG export 화면으로 이동 가능한지 테스트한다.

Run:

```cmd
cd frontend
npm.cmd run test:e2e -- sprint33-live-figma-export.spec.ts --output=test-results-sprint33
npm.cmd run build
```

Expected: Sprint 33 E2E PASS, production build PASS.

### Task 8. 실제 Figma 수동 승인 테스트

**Prerequisites:**

- 편집 권한이 있는 테스트용 Figma Design 파일
- Figma Remote MCP OAuth 완료
- 외부 접근 가능한 HTTPS 이미지 URL
- 실제 비밀값은 `.env`에만 저장

- [ ] 생활/리빙 프로젝트 하나를 상세페이지 편집 단계까지 진행한다.
- [ ] 최소 7개 커머스 컷과 3개 이상의 상품 이미지를 준비한다.
- [ ] 기존 Figma 파일 URL을 입력하고 live export를 실행한다.
- [ ] 최상위 프레임 너비가 860px인지 확인한다.
- [ ] 컷 순서가 Sellform과 같은지 확인한다.
- [ ] 텍스트를 Figma에서 직접 수정할 수 있는지 확인한다.
- [ ] 상품 이미지가 깨지지 않고 보이는지 확인한다.
- [ ] 성공 링크가 생성된 프레임으로 이동하는지 확인한다.
- [ ] 같은 작업을 재시도해 중복 프레임이 생기지 않는지 확인한다.
- [ ] Figma bridge를 끈 상태에서도 Sellform PNG export가 정상인지 확인한다.

## 7. 환경 변수

`.env.example`에는 값이 없는 안전한 예시만 추가한다.

```dotenv
# Optional live Figma MCP export (Sprint 33)
SELLFORM_FIGMA_MCP_ENABLED=false
SELLFORM_FIGMA_BRIDGE_URL=http://127.0.0.1:3417
SELLFORM_FIGMA_BRIDGE_TOKEN=
SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS=120
SELLFORM_FIGMA_MCP_URL=https://mcp.figma.com/mcp
SELLFORM_FIGMA_OAUTH_STORE_PATH=.sellform/figma-oauth.json
SELLFORM_PUBLIC_ASSET_BASE_URL=https://assets.example.com
```

보안 규칙:

- OAuth access/refresh token을 PostgreSQL, API 응답, 로그에 저장하지 않는다.
- 브리지 토큰과 OAuth 저장소를 Git에 포함하지 않는다.
- payload에 LLM API key, 내부 user ID, 결제 정보, 비공개 운영 로그를 포함하지 않는다.
- 운영 환경에서는 `localhost` 이미지 URL을 허용하지 않는다.

## 8. 전체 검증 명령

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q --basetemp=.pytest-tmp-sprint33

cd integrations\figma-bridge
npm.cmd test
npm.cmd run build

cd ..\..\frontend
npm.cmd run build
npm.cmd run test:e2e -- sprint32-figma-export.spec.ts sprint33-live-figma-export.spec.ts --output=test-results-sprint33
```

필수 통과 조건:

- 백엔드 전체 테스트 실패 0건
- bridge 단위·계약 테스트 실패 0건
- bridge TypeScript 빌드 성공
- 프론트 프로덕션 빌드 성공
- Sprint 32·33 E2E 실패 0건
- 실제 Figma 파일 수동 QA 증적 1건 이상

## 9. 완료 정의

- [ ] Sellform에서 기존 Figma 파일 URL을 지정할 수 있다.
- [ ] 실제 Figma 파일에 860px 너비의 편집 가능한 상세페이지 프레임이 생성된다.
- [ ] 7단 구조의 컷, 텍스트, 색상, 이미지가 Figma에 반영된다.
- [ ] 성공 결과로 실제 node URL을 반환한다.
- [ ] 인증·권한·이미지·MCP 오류가 구분되어 표시된다.
- [ ] 재시도 시 같은 payload의 중복 프레임이 생성되지 않는다.
- [ ] Figma 비활성화·장애 상태에서도 Sellform 기본 편집과 PNG export가 정상 동작한다.
- [ ] 테스트 로그, 코드 리뷰, 트러블슈팅, runbook이 갱신된다.

## 10. 남은 위험과 후속 Sprint 후보

### 남은 위험

- Figma 원격 MCP의 write-to-canvas 기능과 도구 계약은 베타 중 변경될 수 있다.
- 사용자 Figma 요금제와 seat에 따라 호출량 또는 편집 권한 제한이 다를 수 있다.
- 외부 공개 이미지 URL이 없으면 이미지가 포함된 실제 Figma 결과를 만들 수 없다.
- 로컬 bridge 방식은 내부 도구에는 적합하지만 외부 구독형 서비스에는 계정별 OAuth 저장소가 필요하다.

### 후속 후보

- Sprint 34: Figma 템플릿·컴포넌트 라이브러리 적용
- Sprint 35: Figma 수정 결과를 Sellform 템플릿으로 가져오는 선택적 역동기화
- Sprint 36: 외부 셀러 계정별 Figma OAuth와 팀 협업 권한

## 11. 공식 참고 자료

- Figma MCP 소개 및 write-to-canvas: https://developers.figma.com/docs/figma-mcp-server/
- Figma 원격 MCP 설정: https://help.figma.com/hc/en-us/articles/39890361040535
- MCP TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk

