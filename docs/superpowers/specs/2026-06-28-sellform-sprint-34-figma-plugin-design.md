# Sprint 34 Sellform Figma Plugin 설계

## 1. 배경

Sprint 33은 Sellform의 자체 MCP bridge에서 Figma Remote MCP로 직접 연결하도록
설계됐다. 실제 검증에서 Figma OAuth 동적 클라이언트 등록이 `403 Forbidden`으로
차단됐다. 이는 Figma Design URL이나 사용자 파일의 문제가 아니라, Figma가 승인한
MCP 클라이언트만 Remote MCP에 연결할 수 있는 정책 때문이다.

Sprint 34는 승인 대기 상태인 MCP를 우회하지 않는다. Figma가 공식적으로 제공하는
Plugin API로 전환해 사용자가 실행한 플러그인이 현재 열린 Figma Design 파일에
편집 가능한 상세페이지를 생성한다.

## 2. 목표

사용자가 Sellform에서 일회용 코드를 발급하고 Figma 플러그인에 입력하면, 현재 열린
빈 Figma Design 파일에 860px 상세페이지가 자동 생성되어야 한다.

사용자가 직접 만드는 것은 빈 Figma Design 파일뿐이다. 프레임, 섹션, 텍스트,
색상, 이미지 배치와 Auto Layout은 플러그인이 생성한다.

## 3. 핵심 사용자 흐름

1. Sellform 페이지 에디터에서 `Figma 플러그인으로 보내기`를 누른다.
2. Sellform이 `SF-8K4P-2M7Q` 형식의 일회용 코드를 발급한다.
3. 사용자는 Figma Design 파일에서 개발용 Sellform 플러그인을 실행한다.
4. 플러그인에 코드를 붙여넣고 `상세페이지 가져오기`를 누른다.
5. 플러그인 UI가 Sellform API에서 canonical payload와 임시 asset session을 받는다.
6. 플러그인이 현재 페이지에 편집 가능한 860px 루트 프레임과 7단 섹션을 만든다.
7. 상품 이미지는 임시 세션으로 내려받아 Figma Image Fill로 삽입한다.
8. 생성이 끝나면 루트 프레임을 선택하고 화면 중앙으로 이동한다.

네트워크나 코드 문제가 있으면 Sellform에서 내려받은 JSON 패키지를 플러그인에
불러와 동일한 렌더러를 실행한다.

## 4. 범위

### 포함

- 10분 유효, 1회 사용 일회용 코드
- 코드 원문을 저장하지 않는 HMAC-SHA256 저장
- 현재 프로젝트의 canonical Figma payload snapshot
- Figma Plugin UI와 Plugin main thread 간 메시지 계약
- 860px 세로 Auto Layout 루트 프레임
- 기본 7단 섹션, 제목, 본문, 배지, 배경색
- 공개 URL에 의존하지 않는 임시 asset binary API
- 섹션별 이미지 실패 격리와 placeholder
- JSON + base64 asset fallback
- Sellform 발급·복사·만료·JSON 다운로드 UI
- 로컬 개발 플러그인 설치/실행 runbook
- 백엔드, 플러그인, 프론트 테스트와 실제 Figma 수동 검수

### 제외

- Figma 변경 내용을 Sellform으로 역동기화
- Figma Community 공개 배포
- 다중 사용자 동시 편집 동기화
- 팀 디자인 시스템 및 컴포넌트 라이브러리 연결
- Figma 파일 자체 자동 생성
- Remote MCP 승인 우회

## 5. 아키텍처

```text
Sellform Page Editor
  └─ POST /projects/{id}/page/figma-plugin/tickets
       └─ FigmaPluginExportTicket
            ├─ canonical payload snapshot
            ├─ internal asset map
            └─ HMAC(code), 10분 만료

Figma Plugin UI
  └─ POST /figma-plugin/import { code }
       ├─ ticket 원자적 1회 사용 처리
       ├─ payload 반환
       └─ 10분 asset session 반환

Figma Plugin UI
  └─ GET /figma-plugin/assets/{asset_ref}
       └─ Authorization: Bearer <asset_session>

Figma Plugin Main
  ├─ Frame/Text/Rectangle 생성
  ├─ Uint8Array → figma.createImage()
  └─ root frame 선택 및 viewport 이동
```

Figma Plugin의 iframe UI만 네트워크 요청을 수행한다. Figma document를 수정하는 main
thread에는 직렬화 가능한 payload와 `Uint8Array` 이미지가 `postMessage`로 전달된다.

## 6. 데이터 모델

`FigmaPluginExportTicket`:

| 필드 | 의미 |
| --- | --- |
| `id` | UUID |
| `project_id` | 원본 상품 프로젝트 |
| `workspace_id` | 테넌트 경계 |
| `created_by` | 코드 발급 사용자 |
| `code_hash` | HMAC-SHA256, unique |
| `payload_json` | 발급 시점 canonical snapshot |
| `asset_map_json` | 외부에 노출하지 않는 asset ref → asset ID 매핑 |
| `status` | `issued`, `redeemed`, `expired`, `revoked` |
| `expires_at` | 발급 후 10분 |
| `redeemed_at` | 최초 교환 시각 |
| `session_token_hash` | asset session HMAC |
| `session_expires_at` | 교환 후 10분 |
| `created_at` | 발급 시각 |

코드와 asset session의 원문은 응답 시 한 번만 반환하며 DB에는 저장하지 않는다.

## 7. API 계약

### 코드 발급

```http
POST /api/v1/projects/{project_id}/page/figma-plugin/tickets
```

```json
{
  "ticket_id": "uuid",
  "code": "SF-8K4P-2M7Q",
  "expires_at": "2026-06-28T12:10:00Z",
  "status": "issued"
}
```

프로젝트 접근 권한과 페이지 존재 여부를 확인하고, 기존
`build_figma_design_payload()` 결과를 snapshot으로 저장한다.

### 코드 교환

```http
POST /api/v1/figma-plugin/import
Content-Type: application/json

{"code":"SF-8K4P-2M7Q"}
```

```json
{
  "schema_version": "1.0",
  "payload": {},
  "asset_session_token": "one-time-random-session",
  "asset_session_expires_at": "2026-06-28T12:20:00Z"
}
```

코드 교환은 `SELECT ... FOR UPDATE`로 보호한다. 만료·재사용·폐기 코드는 각각
`410`, `409`, `410`으로 응답한다. 잘못된 코드는 존재 여부를 노출하지 않고 `404`를
반환한다.

### 이미지 조회

```http
GET /api/v1/figma-plugin/assets/{asset_ref}
Authorization: Bearer <asset_session_token>
```

세션과 asset ref가 같은 ticket에 속하는지 확인하고 MIME type과 binary를 반환한다.
경로 문자열을 직접 요청에 사용하지 않는다.

### JSON fallback

```http
GET /api/v1/projects/{project_id}/page/figma-plugin/package.json
```

테넌트 인증 후 canonical payload와 base64 이미지가 포함된 JSON attachment를
반환한다. 전체 패키지는 20MB로 제한하며 초과 시 `413`과 압축 안내를 반환한다.

## 8. 플러그인 구조

```text
integrations/figma-plugin/
  manifest.template.json
  package.json
  tsconfig.json
  scripts/configure-manifest.mjs
  src/code.ts
  src/ui.html
  src/ui.ts
  src/contracts.ts
  src/payload-validator.ts
  src/renderer.ts
  src/image-loader.ts
  tests/
```

- `manifest.json`은 Figma가 발급한 숫자 ID로 로컬에서 생성하고 Git에서 제외한다.
- `documentAccess`는 `dynamic-page`, `editorType`은 `figma`만 사용한다.
- 개발 API `http://127.0.0.1:8000`은 `devAllowedDomains`로 제한한다.
- 운영 배포 시 `allowedDomains`에는 Sellform API 도메인만 등록한다.
- UI는 코드 입력, JSON 선택, 진행 상태, 섹션별 경고만 담당한다.
- renderer는 API를 알지 못하며 canonical payload와 이미지 byte map만 입력받는다.

## 9. Figma 렌더링 규칙

- 루트 Frame: 폭 860px, Vertical Auto Layout, 높이 자동
- 섹션 Frame: 폭 Fill container, Vertical Auto Layout
- 기본 여백: 좌우 56px, 상하 64px
- 섹션 간격: 0px, 섹션 내부 간격 20px
- 제목과 본문: 독립 TextNode
- 이미지: RectangleNode + ImagePaint `FILL`
- 이미지 실패: 회색 placeholder + `이미지를 확인해 주세요` 레이블
- 폰트: payload 요청 폰트 → `Noto Sans KR` → `Inter` 순서로 로드
- 긴 텍스트: 자동 높이, 고정 폭, 잘라내지 않음
- 노드명: `SELLFORM/{sort}/{section_type}/{section_id}`
- 생성 루트 pluginData: schema version, project ID, ticket ID

개별 이미지나 섹션 생성 실패는 전체 작업을 중단하지 않는다. 루트 프레임 생성 자체가
실패하거나 payload schema가 다를 때만 전체 실패로 처리한다.

## 10. 보안

- 코드 entropy는 40bit 이상이며 10분 후 만료한다.
- 평문 코드와 session token을 로그·DB에 남기지 않는다.
- 교환은 한 번만 성공한다.
- asset session은 교환된 ticket의 asset에만 접근한다.
- import API는 쿠키를 사용하지 않고 bearer code만 사용한다.
- plugin API 경로에만 제한된 CORS 응답을 적용한다.
- 잘못된 코드 시도는 클라이언트별 5분 10회로 제한한다.
- JSON 파일에는 공급처 URL, API key, 내부 파일 경로를 넣지 않는다.

## 11. 오류 UX

| 상황 | 사용자 안내 |
| --- | --- |
| 코드 만료 | Sellform에서 새 코드를 발급해 주세요 |
| 코드 재사용 | 이미 사용한 코드입니다 |
| 서버 연결 실패 | 서버 주소를 확인하거나 JSON으로 가져오세요 |
| 이미지 일부 실패 | 프레임은 생성하고 실패한 이미지만 표시 |
| payload 버전 불일치 | Sellform과 플러그인을 최신 버전으로 맞춰 주세요 |
| 폰트 미지원 | Noto Sans KR 또는 Inter로 자동 대체 |

## 12. 완료 기준

- 코드 발급 후 10분 안에 한 번만 교환할 수 있다.
- 빈 Figma Design 파일에서 7단 상세페이지가 자동 생성된다.
- 프레임과 텍스트를 Figma에서 직접 편집할 수 있다.
- 이미지가 Figma Image Fill로 들어간다.
- 이미지 하나가 실패해도 나머지 섹션은 생성된다.
- JSON fallback이 같은 renderer를 사용해 동일한 구조를 만든다.
- MCP bridge가 꺼져 있어도 플러그인과 PNG export가 정상 동작한다.
- 실제 Figma 수동 검수 스크린샷과 테스트 로그가 남는다.

## 13. 후속 방향

Figma MCP 클라이언트 승인은 별도로 신청할 수 있다. 승인을 받으면 Plugin 방식은
안정적인 fallback으로 유지하고, 원클릭 MCP 자동 생성은 선택 기능으로 다시 추가한다.

