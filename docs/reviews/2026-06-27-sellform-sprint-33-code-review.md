# 코드 리뷰: Sellform Sprint 33 공식 Figma MCP 보완

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-28 |
| 리뷰 범위 | FastAPI Figma export, job 상태, 공식 MCP bridge/OAuth, 이미지 업로드, 프론트 내보내기 UI |
| 결론 | 조건부 승인 — 자동 단위·통합·빌드 통과, Playwright 재실행 및 실제 Figma QA 대기 |

## 1. 보완 결과

- 비공식 `write-to-canvas`/SSE 가정을 제거하고 공식 Streamable HTTP MCP 클라이언트로 교체했다.
- 공식 `use_figma`로 편집 가능한 Frame/TextNode를 만들고, 이미지 컷은
  `upload_assets`가 반환한 업로드 URL에 바이트를 전송한다.
- canonical payload를 `schema_version=1.0`으로 고정하고 백엔드와 브리지가 동일한
  필드명을 사용한다.
- OAuth PKCE verifier, state, client 정보, token을 로컬 저장하며 state 검증 후에만
  `finishAuth(code)`를 호출한다. 가짜 access token과 dummy OAuth URL을 제거했다.
- 실제 root node ID가 없으면 `INVALID_MCP_RESPONSE`로 실패하며 가짜 `0-1` 성공을
  만들지 않는다.
- 작업 상태를 `authenticating → rendering → completed`로 구분하고 API의 `auth_url`을
  보존한다.
- 실패 작업만 재시도할 수 있고 완료 작업 재시도는 409로 막는다.
- 브리지 token이 비어 있으면 503으로 fail-closed하며 `127.0.0.1`에만 바인딩한다.
- 프론트 대화상자와 상태 표시를 별도 컴포넌트로 분리하고 URL 검증, 2분 timeout,
  API 제공 OAuth URL, PNG 대체 경로를 제공한다.
- Sprint 32 payload-only preflight 요청을 유지했다.

## 2. 주요 이슈와 조치

### 🔴 B1. 존재하지 않는 도구와 가짜 성공

기존 리뷰는 `write-to-canvas`와 고정 node ID를 실제 연동으로 잘못 승인했다.
공식 `use_figma` 계약과 실제 반환 node ID 검증으로 교체했다.

### 🔴 B2. OAuth 위조 가능성

기존 콜백은 state 검증 없이 가짜 token을 저장할 수 있었다. SDK OAuth provider,
PKCE/state 검증, `finishAuth`로 교체했다.

### 🟠 M1. 백엔드·브리지 payload 불일치

`schema_version`, `section_type`, `supporting_text`, brand/page 필드를 하나의 canonical
계약으로 통합하고 양쪽 테스트를 추가했다.

### 🟠 M2. 이미지가 URL 문자열로만 전달됨

이미지 슬롯을 실제 node ID로 반환하고 `upload_assets` 업로드 흐름을 구현했다.
공개 HTTPS/10MB 정책 위반은 명시적인 오류로 처리한다.

### 🟡 M3. 운영 보안 및 문서

bridge token 필수화, loopback 바인딩, CORS 제거, `.sellform`/build artifact ignore,
공식 MCP 기준 런북과 트러블슈팅 문서를 반영했다.

## 3. 검증 증적

- 백엔드 전체: `152 passed`
- Figma 집중 백엔드: `19 passed`
- Figma bridge Jest: `16 passed`
- Figma bridge TypeScript build: 성공
- Next.js production build: 성공
- Playwright 재실행: 실행 승인 사용량 제한으로 미수행
- 실제 Figma 계정/Design 파일 생성 검수: 미수행

상세 명령과 출력은
`docs/testing/2026-06-27-sellform-sprint-33-live-figma-export-test-log.md`에 기록했다.

## 4. 남은 위험

- 실제 Figma 계정의 seat/편집 권한과 현재 Remote MCP 제공 도구는 로컬 mock으로
  완전히 대체할 수 없다.
- page-editor 하단의 이전 인라인 `FigmaExportDialog` 구현은 더 이상 렌더링되지 않지만
  후속 정리 대상으로 남아 있다. 활성 화면은 분리된 공식 MCP 컴포넌트만 사용한다.
- OAuth token은 로컬 JSON에 저장되므로 OS 파일 권한과 백업 정책이 필요하다.
- JavaScript 의존성 검사에서 기존 moderate 취약점이 보고될 수 있어 별도 의존성
  정리 작업이 필요하다. 강제 `audit fix`는 수행하지 않았다.

## 5. 최종 판정

코드와 자동 단위·통합·빌드는 보완 설계에 맞게 구현됐다. 다만 실제 계정 검증 없는
상태를 `Approved`로 과장하지 않는다. Sprint 32/33 Playwright 재실행과 실제 Figma
파일에서 frame/text/image 생성 확인 후 최종 승인으로 전환한다.
