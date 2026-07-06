# Sprint 35 트러블슈팅 - Figma Visual Commerce Renderer

## 1. 문제: visual renderer 테스트가 모듈 없음으로 실패

### 증상

```text
Cannot find module '../src/visual-renderer'
Object literal may only specify known properties, and 'visual_layout' does not exist in type 'FigmaDesignPayload'
```

### 원인

Sprint 35 기획은 `visual_layout` 기반의 별도 Figma renderer를 요구했지만, 기존 플러그인 구조는 `cuts`만 받는 legacy renderer만 갖고 있었다.

### 조치

- `contracts.ts`에 `VisualLayout`, `VisualCommerceCut`, `VisualSlot` 타입 추가.
- `FigmaDesignPayload.visual_layout` optional 필드 추가.
- `visual-renderer.ts` 신규 추가.
- `renderer.ts`에서 `payload.visual_layout.layout_version === 'commerce_visual_v1'`인 경우 전용 renderer로 분기.

## 2. 문제: 테스트 파일 문자열 인코딩 깨짐

### 증상

테스트 파일 안에 깨진 문자열과 닫히지 않은 따옴표가 포함되어 TypeScript 테스트가 정상 파싱되지 않았다.

### 원인

이전 작업 중 한글 문자열이 콘솔/파일 인코딩 경계에서 깨진 것으로 추정된다.

### 조치

`visual-renderer.test.ts`를 정상 한글 문자열 기준으로 정리했다.

## 3. 문제: 전체 플러그인 테스트에서 localhost 기대값 불일치

### 증상

```text
Expected: "http://127.0.0.1:8000/..."
Received: "http://localhost:8000/..."
```

또는 manifest 테스트에서:

```text
Expected value: "http://127.0.0.1:8000"
Received array: ["http://localhost:8000"]
```

### 원인

Figma Desktop plugin manifest에서 `127.0.0.1` 도메인이 유효 URL로 거부되는 문제가 있어, 현재 구현은 `http://localhost:8000`을 사용하도록 조정되어 있었다. 테스트 기대값만 이전 주소에 머물러 있었다.

### 조치

- `ui-client.test.ts` 기대 URL을 `http://localhost:8000/api/v1/figma-plugin/import`로 수정.
- `configure-manifest.test.mjs`의 `devAllowedDomains` 기대값을 `http://localhost:8000`으로 수정.

## 4. 운영 메모

Figma Desktop에서 플러그인 코드를 다시 테스트할 때는 다음 순서를 따른다.

1. 백엔드 실행: `run_backend.cmd`
2. 프론트 실행: `npm.cmd run dev`
3. Figma plugin 빌드: `npm.cmd run build`
4. Figma Desktop에서 Sellform Detail Page Importer 실행
5. Sellform 화면의 ticket code를 플러그인에 입력

플러그인이 여전히 예전 UI 또는 예전 렌더링을 보이면 Figma Desktop에서 플러그인을 닫고 다시 실행한다.
