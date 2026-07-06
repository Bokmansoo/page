# Sellform Sprint 33 공식 Figma MCP 연동 보완 설계

작성일: 2026-06-28  
상태: 사용자 설계 방향 승인, 문서 검토 대기

## 1. 목표

Sprint 32에서 생성한 Sellform 상세페이지 디자인 payload를 기존 Figma Design 파일에 편집 가능한 프레임으로 내보낸다.

이번 보완의 핵심은 테스트용 모의 구현을 실제 연동으로 오인하지 않도록 하는 것이다. 실제 Figma MCP 호출이 성공하고 생성된 node ID가 확인된 경우에만 작업을 `completed`로 기록한다. 인증, 권한, MCP 도구, 이미지 업로드 중 하나라도 실패하면 구체적인 오류와 복구 경로를 제공하고 Sellform 편집 및 PNG 내보내기는 계속 사용할 수 있어야 한다.

## 2. 공식 계약 기준

구현 기준은 2026-06-28 현재 Figma 공식 문서로 고정한다.

- Remote MCP endpoint: `https://mcp.figma.com/mcp`
- 전송 방식: Streamable HTTP
- 캔버스 생성·편집 도구: `use_figma`
- 이미지 업로드 도구: `upload_assets`
- 인증: MCP SDK의 OAuth 흐름과 PKCE·state 검증 사용
- 수정 조건: Figma Full seat와 대상 파일 편집 권한 필요

기존 코드의 `write-to-canvas`, `create-frame`, SSE 전송, 직접 조립한 Figma OAuth URL, 모의 access token은 제거한다.

참고:

- https://developers.figma.com/docs/figma-mcp-server/write-to-canvas/
- https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/
- https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/

## 3. 선택한 아키텍처

```text
page-editor
  -> Sellform FastAPI
     -> FigmaExportJob 생성/재사용
     -> canonical Figma payload 생성
     -> local figma-bridge 호출
        -> Streamable HTTP MCP 연결
        -> OAuth 필요 시 공식 인증 URL 반환
        -> use_figma로 프레임·텍스트·이미지 슬롯 생성
        -> upload_assets로 공개 HTTPS 이미지를 슬롯에 적용
        -> 실제 생성 node ID와 URL 반환
     -> 작업 상태 및 결과 저장
  -> UI polling
     -> 완료 시 Figma node 열기
     -> 실패 시 원인·재인증·재시도·PNG 대안 제공
```

Figma 연동은 선택 기능이다. 브리지가 꺼져 있거나 Figma가 장애 상태여도 기존 상세페이지 편집, 저장, PNG 내보내기는 영향을 받지 않는다.

## 4. Canonical payload

백엔드와 브리지는 아래 필드만 사용하는 하나의 계약을 공유한다.

```json
{
  "schema_version": "1.0",
  "project": {
    "id": "project-id",
    "name": "상품명",
    "category": "Living"
  },
  "brand": {
    "name": "Default Brand",
    "primary_color": "#5B7CFA",
    "font_family": "Inter"
  },
  "page": {
    "canvas_width": 860,
    "channel": "smartstore",
    "style_key": "problem_solution"
  },
  "cuts": [
    {
      "section_id": "section-id",
      "section_type": "problem_statement",
      "layout_type": "hero",
      "headline": "제목",
      "subcopy": "설명",
      "supporting_text": "보조 문구",
      "image_url": "https://public.example/image.png",
      "background_style": "clean_problem_statement"
    }
  ]
}
```

브리지는 임의의 `type`, `supporting_copy`, `theme_color`, `sort_order` 필드를 기대하지 않는다. `canvas_width`, 브랜드 색상, 폰트, cut 배열 순서를 그대로 사용한다.

## 5. Figma 생성 절차

1. 대상 URL이 `https://www.figma.com/design/{fileKey}/...` 형식인지 검증한다.
2. MCP 연결과 OAuth 상태를 확인한다.
3. `listTools()`에서 `use_figma` 존재 여부를 확인한다.
4. `use_figma`를 작은 단계로 호출한다.
   - 최상위 `Sellform / {상품명}` 프레임 생성
   - cut별 Auto Layout 프레임과 편집 가능한 TextNode 생성
   - 이미지가 있는 cut에는 이미지 슬롯을 만들고 슬롯 node ID 수집
5. 이미지가 있으면 `upload_assets` 지원 여부를 확인하고 공개 HTTPS URL을 각 슬롯에 업로드한다.
6. MCP 응답에서 실제 최상위 node ID를 파싱하고 검증한다.
7. node ID가 없거나 Figma 오류가 포함되면 성공으로 처리하지 않는다.

한 번의 `use_figma` 응답 제한을 피하기 위해 큰 상세페이지는 여러 호출로 나눈다. 동일 payload 작업을 재요청하면 완료된 기존 작업을 반환한다.

## 6. OAuth와 보안

- OAuth 토큰은 `.sellform/figma-oauth.json`에만 저장하며 `.gitignore`에 포함한다.
- 토큰, client secret, bridge token을 API 응답이나 로그에 기록하지 않는다.
- 직접 만든 `figma_access_token_*` 같은 모의 토큰은 사용하지 않는다.
- OAuth callback은 PKCE verifier와 `state`를 검증한 뒤에만 토큰을 저장한다.
- bridge는 기본적으로 `127.0.0.1`에만 바인딩한다.
- bridge token이 비어 있으면 export endpoint를 활성화하지 않는다.
- 브라우저가 bridge를 직접 호출하지 않으므로 광범위한 CORS 허용을 제거한다.
- 공개 HTTPS 이미지 URL만 허용한다.

## 7. 작업 상태와 오류

정상 상태 전이:

```text
queued -> authenticating -> rendering -> completed
```

재인증:

```text
queued -> authenticating -> failed(AUTH_REQUIRED, auth_url)
failed -> queued
```

지원 오류:

- `AUTH_REQUIRED`
- `AUTH_DENIED`
- `INVALID_FIGMA_URL`
- `FILE_PERMISSION_DENIED`
- `ASSET_URL_NOT_PUBLIC`
- `MCP_UNAVAILABLE`
- `MCP_TOOL_UNSUPPORTED`
- `IMAGE_UPLOAD_UNSUPPORTED`
- `RENDER_FAILED`
- `INVALID_MCP_RESPONSE`

`FigmaExportJob`은 `auth_url`과 단계별 오류를 저장할 수 있어야 한다. `retry`는 `failed` 작업에서만 허용하며 완료 작업을 다시 렌더링하지 않는다. DB의 unique constraint 또는 동등한 동시성 보호로 중복 작업 생성을 방지한다.

## 8. 프론트엔드

Figma 기능은 다음 두 컴포넌트로 분리한다.

- `FigmaExportDialog`: URL 입력, 시작, 재인증, 재시도, PNG 대안
- `FigmaExportStatus`: 상태 단계와 오류 안내

동작 규칙:

- API 호출 전에 Figma Design URL을 검증한다.
- 공통 API base URL과 실제 tenant header를 사용한다.
- 약 1초 간격으로 polling하되 2분 후 명시적인 timeout을 표시한다.
- API가 제공한 `auth_url`만 사용하고 임의의 OAuth URL을 만들지 않는다.
- 완료 시 실제 `result_node_url`을 제공한다.
- 모달을 닫아도 페이지 편집 상태는 유지한다.

## 9. 테스트 전략

### 백엔드

- builder 출력과 bridge canonical payload 계약 테스트
- 상태 전이 `queued -> authenticating -> rendering -> completed`
- `auth_url` 보존 테스트
- failed가 아닌 작업의 retry 거부
- 같은 payload의 idempotency 및 동시 요청 방어
- 기존 `FigmaMcpAdapter` 회귀 테스트

### Bridge

- Streamable HTTP transport 사용
- `use_figma`와 `upload_assets` 도구 탐색
- 공식 OAuth redirect와 callback 검증
- 모의 토큰 생성 금지
- canonical payload를 실제 Figma 명령으로 변환
- node ID가 없을 때 `INVALID_MCP_RESPONSE`
- 이미지 슬롯과 `upload_assets` 호출 계약
- bridge token 필수 및 localhost 바인딩

### Frontend

- 잘못된 URL은 API를 호출하지 않음
- queued → authenticating → rendering → completed
- API의 `auth_url` 사용
- polling timeout
- 실패 후 retry 및 PNG 화면 이동
- Sprint 32 payload-only fallback 회귀

### 수동 QA

자동 테스트는 실제 Figma 생성을 증명하지 않는다. Full seat와 편집 권한이 있는 실제 파일에서 다음을 별도 확인한다.

- 860px 최상위 프레임
- 7개 cut 순서
- 편집 가능한 텍스트
- 실제 상품 이미지
- 실제 node URL
- 동일 payload 재시도 시 중복 없음
- Figma 장애 중 Sellform PNG 내보내기 정상

실제 계정 QA를 수행하지 못한 경우 리뷰 문서는 `조건부 완료`로 기록한다.

## 10. 완료 기준

- 가짜 OAuth, 가짜 node ID, 존재하지 않는 MCP 도구 호출이 없다.
- 백엔드와 브리지 payload가 단일 계약을 사용한다.
- 이미지가 `upload_assets`를 통해 실제 Figma 파일에 반영된다.
- 전체 백엔드 테스트, bridge 테스트·빌드, frontend 빌드, Sprint 32·33 E2E가 모두 통과한다.
- `.sellform/`과 `node_modules/`가 Git에서 제외된다.
- 코드리뷰·테스트 로그·트러블슈팅·runbook이 실제 구현과 일치한다.
- 실제 Figma 수동 QA 여부와 제한 사항이 문서에 정직하게 기록된다.
