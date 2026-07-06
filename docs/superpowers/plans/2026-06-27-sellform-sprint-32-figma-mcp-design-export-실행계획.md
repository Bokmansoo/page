# Sprint 32 - Figma MCP 디자인 내보내기 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sellform에서 생성한 상세페이지 컷 구조를 Figma 편집 가능한 프레임으로 내보내고, 팀/디자이너가 Figma에서 상세페이지 시안을 수정할 수 있는 디자인 협업 경로를 만든다.

**Architecture:** Sellform은 상품 정보, 사실 카드, 판매 구조, 컷 데이터, export를 책임지고 Figma MCP는 디자인 협업/템플릿 관리용 외부 플러그인처럼 사용한다. 핵심 export는 Sellform 자체에서 유지하며, Figma는 선택적 고도화 경로로 둔다.

**Tech Stack:** Next.js, FastAPI, Figma MCP, Sellform page/section/visual cut model, JSON design payload.

---

## 1. 배경

Sellform의 최종 목적은 셀러가 상품 URL/이미지를 넣으면 상세페이지를 자동으로 만드는 것이다. 하지만 외부 셀러용 구독 서비스나 대행사/팀 고객까지 확장하려면 디자인 협업이 중요해진다.

Figma MCP를 붙이면 다음 흐름이 가능해진다.

```text
상품 정보 입력
→ Sellform이 상세페이지 구조와 컷 생성
→ Figma로 내보내기
→ 디자이너가 Figma에서 수정
→ Sellform 또는 Figma에서 최종 이미지 export
```

단, Figma를 핵심 엔진 안에 깊게 넣으면 Figma를 쓰지 않는 셀러에게 불필요한 복잡도가 생긴다. 따라서 Figma는 “선택 가능한 디자인 협업 플러그인”으로 둔다.

## 2. 범위

### 포함

- Sellform 페이지 컷 데이터를 Figma용 design payload로 변환
- “Figma로 내보내기” 진입점 추가
- Figma 프레임 생성용 데이터 구조 정의
- 카테고리/스타일/브랜드 토큰을 Figma로 전달
- Figma MCP 연결 실패 시 안전한 안내 표시
- Figma 연동이 없어도 기존 Sellform export 흐름은 정상 동작
- 연동 정책/권한/토큰 보안 문서화

### 제외

- Figma에서 수정한 결과를 다시 Sellform으로 완전 동기화
  - 후속 Sprint 후보로 분리한다.
- Figma 플러그인 자체 개발
- Figma 파일 내 복잡한 컴포넌트 라이브러리 자동 생성
- 쿠팡/스마트스토어 자동 업로드

## 3. 설계 원칙

1. Figma는 선택 기능이다.
   - Figma MCP가 없어도 Sellform은 상세페이지를 만들고 export할 수 있어야 한다.

2. Sellform 데이터가 원본이다.
   - 상품 정보, 사실 카드, 섹션 구조, 최종 export 이력은 Sellform DB가 기준이다.

3. Figma는 편집 가능한 디자인 사본이다.
   - Figma 결과물은 협업/디자인 수정용으로 사용한다.

4. 민감 정보는 Figma로 보내지 않는다.
   - API key, 내부 user/workspace id, 비용 정보, 비공개 로그는 전달하지 않는다.

## 4. Figma 내보내기 데이터 구조

Figma에 보낼 payload 예시:

```json
{
  "project": {
    "id": "project-id",
    "name": "루메나 휴대용 무선 냉각선풍기",
    "category": "Living"
  },
  "brand": {
    "name": "Default Brand",
    "primary_color": "#5B7CFA",
    "font_family": "Sans-Serif"
  },
  "page": {
    "canvas_width": 860,
    "channel": "smartstore",
    "style_key": "problem_solution_living"
  },
  "cuts": [
    {
      "section_id": "section-id",
      "layout_type": "problem_visual",
      "headline": "작은 불편이 쌓이면 일상이 번거로워집니다",
      "subcopy": "고객이 실제로 느끼는 불편과 구매 전 고민을 먼저 짚어줍니다.",
      "image_url": "http://localhost:8000/uploads/...",
      "background_style": "cool_clean_living"
    }
  ]
}
```

## 5. 구현 작업

### Task 1. Figma design payload builder 추가

**Files:**

- Create: `backend/src/services/figma_design_payload_builder.py`
- Test: `backend/tests/test_figma_design_payload_builder.py`

작업:

- [ ] project/page/sections/assets를 받아 Figma payload를 만든다.
- [ ] Sprint 31의 `CommerceVisualCut` 구조가 있으면 우선 사용한다.
- [ ] 없으면 기존 page sections에서 최소 payload를 만든다.
- [ ] 이미지 asset은 Figma에서 접근 가능한 URL 형태로 변환한다.
- [ ] 민감 정보는 payload에서 제외한다.

완료 기준:

- [ ] project name/category가 payload에 포함된다.
- [ ] brand primary color/font가 payload에 포함된다.
- [ ] cuts 배열이 section 순서대로 생성된다.
- [ ] image_asset_id가 있으면 image_url이 포함된다.

### Task 2. Figma export API 추가

**Files:**

- Modify: `backend/src/api/pages.py`
- Test: `backend/tests/test_figma_export_api.py`

엔드포인트:

```http
POST /api/v1/projects/{project_id}/page/figma/export
```

응답 예시:

```json
{
  "status": "ready",
  "payload": {
    "project": {},
    "brand": {},
    "page": {},
    "cuts": []
  },
  "message": "Figma MCP에서 사용할 디자인 payload가 생성되었습니다."
}
```

작업:

- [ ] 프로젝트 권한을 검증한다.
- [ ] page가 없으면 409를 반환한다.
- [ ] Figma MCP가 실제 연결되지 않아도 payload 생성은 가능해야 한다.
- [ ] MCP 직접 호출이 가능한 환경에서는 별도 adapter로 호출할 수 있게 분리한다.

### Task 3. Figma MCP adapter 인터페이스 정의

**Files:**

- Create: `backend/src/services/figma_mcp_adapter.py`
- Test: `backend/tests/test_figma_mcp_adapter.py`

작업:

- [ ] `FigmaMcpAdapter` 인터페이스를 만든다.
- [ ] 기본 구현은 `disabled` 상태로 둔다.
- [ ] 환경변수 `SELLFORM_FIGMA_MCP_ENABLED`가 false면 호출하지 않는다.
- [ ] 연결 실패 시 사용자에게 “Figma 연동이 설정되지 않음” 메시지를 반환한다.
- [ ] 실제 MCP 호출은 후속 구현에서 확장 가능한 형태로 둔다.

완료 기준:

- [ ] Figma 비활성 상태에서 Sellform 기능이 깨지지 않는다.
- [ ] 연동 비활성/실패 이유가 응답에 포함된다.

### Task 4. Page editor에 Figma 내보내기 버튼 추가

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

작업:

- [ ] page-editor 상단 또는 export 준비 패널에 `Figma로 내보내기` 버튼을 추가한다.
- [ ] 버튼 클릭 시 `/page/figma/export` API를 호출한다.
- [ ] 성공 시 payload 생성 완료 메시지를 표시한다.
- [ ] Figma MCP가 비활성인 경우 “현재는 Figma payload 생성만 지원합니다” 안내를 표시한다.
- [ ] 실패 시 page 없음, 권한 없음, 서버 오류를 구분해 보여준다.

완료 기준:

- [ ] 사용자가 Figma 연동 상태를 이해할 수 있다.
- [ ] Figma 연동이 없어도 page-editor가 깨지지 않는다.

### Task 5. Figma 연동 정책 문서 작성

**Files:**

- Create: `docs/decisions/2026-06-27-sellform-figma-mcp-integration-strategy.md`
- Create: `docs/runbooks/2026-06-27-sellform-figma-mcp-runbook.md`

문서 내용:

- [ ] Figma를 핵심 엔진이 아닌 선택 플러그인으로 두는 이유
- [ ] 어떤 데이터가 Figma로 전달되는지
- [ ] 어떤 데이터는 전달하지 않는지
- [ ] Figma MCP 설정 방법
- [ ] 연결 실패 시 fallback
- [ ] 향후 Figma → Sellform 동기화 후보

## 6. 테스트 계획

### 백엔드

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

검증:

- [ ] Figma payload builder 테스트 통과
- [ ] Figma export API 테스트 통과
- [ ] Figma disabled adapter 테스트 통과
- [ ] 기존 page/export 테스트 회귀 없음

### 프론트엔드

```cmd
cd frontend
npm.cmd run build
```

검증:

- [ ] Figma 버튼 추가 후 빌드 성공
- [ ] API 실패/비활성 상태 UI 타입 오류 없음

### 수동 QA

1. 상세페이지 초안이 있는 프로젝트를 연다.
2. page-editor에서 `Figma로 내보내기` 버튼을 누른다.
3. Figma MCP 비활성 상태에서는 payload 생성 안내가 표시된다.
4. API 응답에 project/brand/page/cuts 구조가 포함되는지 확인한다.
5. 기존 export 흐름이 그대로 동작하는지 확인한다.

## 7. 산출 문서

구현 완료 후 다음 문서를 작성한다.

- `docs/testing/2026-06-27-sellform-sprint-32-figma-mcp-test-log.md`
- `docs/reviews/2026-06-27-sellform-sprint-32-code-review.md`
- `docs/troubleshooting/2026-06-27-sellform-sprint-32-figma-mcp.md`
- `docs/decisions/2026-06-27-sellform-figma-mcp-integration-strategy.md`
- `docs/runbooks/2026-06-27-sellform-figma-mcp-runbook.md`

## 8. 리스크와 대응

### R1. Figma MCP가 현재 환경에서 바로 호출되지 않을 수 있음

대응:

- Sprint 32의 1차 목표는 “payload 생성 + 선택 연동 구조”로 둔다.
- MCP 연결이 없어도 Sellform 자체 export는 유지한다.

### R2. Figma가 핵심 흐름을 복잡하게 만들 수 있음

대응:

- Figma 버튼은 선택 기능으로 둔다.
- 기본 사용자 흐름은 Sellform 안에서 끝나게 한다.

### R3. 디자인 원본과 Sellform 데이터가 불일치할 수 있음

대응:

- Sprint 32에서는 Sellform → Figma 단방향으로 제한한다.
- Figma → Sellform 동기화는 후속 Sprint로 분리한다.

## 9. 완료 정의

- [ ] Sellform page data를 Figma design payload로 변환할 수 있다.
- [ ] page-editor에서 Figma 내보내기 진입점이 보인다.
- [ ] Figma MCP 비활성 상태에서도 명확한 안내가 표시된다.
- [ ] Sellform 자체 export 흐름이 깨지지 않는다.
- [ ] 백엔드 테스트가 통과한다.
- [ ] 프론트 빌드가 통과한다.
- [ ] 테스트 로그, 코드 리뷰, 트러블슈팅, 연동 정책 문서가 작성된다.

## 10. 후속 Sprint 후보

- Sprint 33 - Figma 템플릿 라이브러리 관리
- Sprint 34 - Figma에서 수정한 디자인을 Sellform 템플릿으로 반영
- Sprint 35 - 외부 셀러/대행사용 디자인 협업 워크스페이스
