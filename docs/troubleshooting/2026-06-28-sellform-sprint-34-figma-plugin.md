# Sprint 34 Figma Plugin 보완 트러블슈팅

## 1. 코드 입력 즉시 `UNSUPPORTED_SCHEMA_VERSION`

### 원인

백엔드는 `payload.schema_version`만 반환했지만 플러그인은 응답 최상위
`schema_version`을 검증했다. 단위 테스트 mock에는 실제 응답에 없는
최상위 필드가 있어 결함을 놓쳤다.

### 조치

- 교환 API가 최상위 `schema_version`과 `embedded_assets`를 반환한다.
- UI client는 이전 응답도 `payload.schema_version`으로 정규화한다.
- 실제 백엔드 응답 계약을 API 테스트에 고정했다.

## 2. 비밀키가 없어도 티켓이 생성됨

### 원인

빈 설정을 공용 문자열 `default_secret_key`로 대체했다.

### 조치

32자 미만 비밀키는 티켓 발급·교환을 거절한다. 로컬 `.env`와
`.env.example`에 Sprint 34 설정을 추가했다.

## 3. 플러그인이 2개 또는 빈 프레임을 생성함

### 원인

validator와 API가 cut 개수를 검사하지 않았고 테스트도 2개 cut만 사용했다.

### 조치

발급 API와 플러그인 validator 모두 정확히 7개 cut을 요구한다.

## 4. Figma 여백과 폰트가 설계와 다름

### 원인

renderer가 모든 여백을 24px로 사용했고 요청 폰트 로드 실패 후에도 같은
폰트 이름을 TextNode에 지정했다.

### 조치

좌우 56px·상하 64px로 맞췄고, 요청 폰트 실패 시 Inter Regular/Bold를
명시적으로 로드한다.

## 5. 20MB보다 큰 JSON이 내려감

### 원인

Base64 인코딩 전 파일 크기만 합산했다.

### 조치

최종 JSON UTF-8 직렬화 크기를 다시 계산해 제한을 적용한다.

## 6. 기존 Remote MCP 화면이 먼저 표시됨

### 원인

Sprint 33 Live 탭이 기본값으로 남아 있었다.

### 조치

Sprint 34 플러그인 탭을 기본 흐름으로 전환하고 기본 화면에서 Live 탭을
제거했다.
