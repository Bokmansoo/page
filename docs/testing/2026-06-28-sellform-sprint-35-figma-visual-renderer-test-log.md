# Sprint 35 테스트 로그 - Figma Visual Commerce Renderer

| 항목 | 내용 |
| --- | --- |
| 스프린트 | Sprint 35 |
| 테스트 일자 | 2026-06-29 |
| 범위 | Figma 플러그인 비주얼 커머스 렌더러, visual_layout payload, 플러그인 패키지 검증 |
| 목적 | Figma로 내보낸 상세페이지가 글 중심 프레임이 아니라 이미지 슬롯과 짧은 카피가 결합된 커머스형 860px 상세페이지 구조로 생성되는지 확인 |

## 1. 실행한 테스트

### Backend visual layout / Figma package payload

```powershell
uv run --project backend --group dev pytest backend/tests/test_figma_visual_layout_builder.py backend/tests/test_figma_plugin_visual_payload.py backend/tests/test_figma_plugin_api.py -q
```

결과:

```text
10 passed, 47 warnings in 1.22s
```

확인 내용:

- Figma payload에 `visual_layout` 확장 필드가 포함된다.
- `visual_layout.layout_version`은 `commerce_visual_v1`이다.
- 860px 기준 7개 커머스 컷이 생성된다.
- 이미지 asset 참조와 image URL 매핑이 visual cut까지 전달된다.
- 기존 Figma plugin ticket/import API 흐름은 깨지지 않는다.

### Figma plugin unit tests

```powershell
npm.cmd test
```

작업 디렉터리:

```text
C:\page\integrations\figma-plugin
```

결과:

```text
Test Suites: 5 passed, 5 total
Tests:       16 passed, 16 total
```

확인 내용:

- `visual_layout`이 있는 패키지는 전용 visual commerce renderer로 렌더링된다.
- Figma root frame은 860px 폭으로 생성된다.
- 7개 섹션이 `01_problem_statement` 같은 순번 기반 이름으로 생성된다.
- 이미지가 있으면 `visual_image`, 없으면 `visual_placeholder`가 생성된다.
- headline/body/badge 텍스트는 Figma에서 편집 가능한 text node로 생성된다.
- 기존 legacy renderer 테스트는 그대로 통과한다.
- plugin UI client와 manifest configure 테스트가 현재 `http://localhost:8000` 정책에 맞게 통과한다.

### Figma plugin build

```powershell
npm.cmd run build
```

작업 디렉터리:

```text
C:\page\integrations\figma-plugin
```

결과:

```text
Figma Plugin build succeeded.
```

### Frontend build

```powershell
npm.cmd run build
```

작업 디렉터리:

```text
C:\page\frontend
```

결과:

```text
✓ Compiled successfully
✓ Generating static pages (9/9)
```

참고 경고:

```text
src/app/workspace/projects/[id]/page-editor/page.tsx
Warning: Using <img> could result in slower LCP...
```

해당 경고는 기존 이미지 렌더링 방식에 대한 Next.js 권고이며 Sprint 35 기능 실패는 아니다.

## 2. 테스트 결론

Sprint 35의 핵심 완료 기준은 충족했다.

- Backend는 Figma plugin package에 visual commerce layout 정보를 제공한다.
- Figma plugin은 해당 layout을 이용해 860px 상세페이지 프레임과 7개 비주얼 섹션을 생성한다.
- 이미지가 없는 경우에도 회색/파란색 빈 박스가 아니라 명시적인 visual placeholder와 warning을 남긴다.
- 기존 ticket code import, JSON fallback, legacy renderer 흐름은 유지된다.

## 3. 남은 확인 사항

- 실제 Figma Desktop에서 플러그인을 다시 실행해 ticket code import 결과를 눈으로 확인해야 한다.
- Sprint 36에서 상품 이미지 자동 매핑 품질이 올라가야 placeholder 비중이 줄어든다.
- Sprint 37에서 스타일 후보 선택이 들어가면 visual layout tone과 section composition을 더 다양화할 수 있다.
