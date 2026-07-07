# Sellform API 없는 상세페이지 미리보기 테스트 페이지 가이드

이 문서는 실제 OpenAI, 이미지 생성 API, 백엔드 DB 흐름을 쓰지 않고 상세페이지 화면 구성을 빠르게 확인하는 개발용 테스트 페이지 실행 방법을 정리합니다.

## 목적

`/dev/detail-page-preview` 페이지는 로컬 fixture 데이터만 사용해서 상세페이지 결과 화면을 렌더링합니다.

이 페이지로 확인할 수 있는 것:

- 상세페이지 섹션 레이아웃
- HTML/CSS 그래픽 카드 표시
- 고객 노출용 카피 구조
- 상품군별 상세페이지 흐름
- Sprint 75, 76 이후 문구/이미지 후보 UI 방향성

이 페이지로 확인할 수 없는 것:

- 실제 OpenAI 문구 생성 품질
- 실제 이미지 생성 API 품질
- 백엔드 저장/조회
- PNG/JPG 다운로드
- 출력 이력 저장
- 작업 목록 조회

즉, 이 페이지는 “API 비용 없이 화면과 구조를 먼저 보는 샌드박스”입니다.

## 관련 파일

| 역할 | 파일 |
|---|---|
| 라우트 | `frontend/src/app/dev/detail-page-preview/page.tsx` |
| 화면 컴포넌트 | `frontend/src/components/dev/DetailPagePreviewSandbox.tsx` |
| 테스트 fixture | `frontend/src/fixtures/detailPagePreview.ts` |
| 실제 상세페이지 렌더러 | `frontend/src/components/DetailPageDocument.tsx` |

## 실행 방법

프론트엔드만 실행하면 됩니다. 백엔드는 필요 없습니다.

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

터미널에 표시되는 주소를 확인합니다.

3000번 포트로 실행되면:

```txt
http://localhost:3000/dev/detail-page-preview
```

3000번 포트가 이미 사용 중이라 3001번으로 실행되면:

```txt
http://localhost:3001/dev/detail-page-preview
```

Next.js는 3000번 포트가 사용 중이면 자동으로 3001번 같은 다음 포트를 사용합니다. 그래서 로컬에서 어떤 때는 3000, 어떤 때는 3001로 보일 수 있습니다.

## 확인 순서

1. `/dev/detail-page-preview`에 접속합니다.
2. 상단 fixture 버튼으로 상품 예시를 바꿔 봅니다.
3. 왼쪽 상세페이지 본문에서 섹션 순서와 문구 흐름을 확인합니다.
4. 오른쪽 체크리스트에서 현재 fixture가 API 없는 샌드박스임을 확인합니다.
5. HTML/CSS 그래픽 섹션이 이미지 생성 없이도 자연스럽게 보이는지 확인합니다.

## 실제 전체 기능 테스트와의 차이

테스트 페이지는 프론트 단독 확인용입니다. 실제 생성, 저장, 출력 이력까지 보려면 백엔드와 DB를 함께 실행해야 합니다.

전체 플로우 테스트는 아래처럼 실행합니다.

```cmd
cd /d C:\page
docker compose up -d db
run_backend.cmd
```

다른 터미널에서:

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

그다음 접속:

```txt
http://localhost:3000/workspace/projects
```

또는 프론트가 3001번으로 실행됐다면:

```txt
http://localhost:3001/workspace/projects
```

## mock 모드에서 비용이 나가는지 확인

`.env`가 아래처럼 되어 있으면 실제 LLM/이미지 생성 API를 쓰지 않는 mock 테스트 상태입니다.

```env
SELLFORM_RAG_RUNTIME_MOCK=true
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
```

이 상태에서는 상세페이지 문구와 이미지는 실제 AI 품질이 아니라 mock fixture 또는 mock 생성 로직 기준으로 나옵니다.

## 커밋 전 추천 검증

테스트 페이지를 눈으로 확인한 뒤, 최소한 아래 자동 검증을 실행합니다.

백엔드 Sprint 76 관련 테스트:

```cmd
cd /d C:\page\backend
uv run pytest tests/test_product_cutout_service.py tests/test_planning_draft_approve_api.py -q
```

프론트 lint:

```cmd
cd /d C:\page\frontend
npm.cmd run lint
```

`npm.cmd run build`가 Windows 로컬에서 오래 멈추면 억지로 기다리지 말고 `Ctrl + C`로 중단합니다. 이 경우 Sprint 76 검증은 백엔드 테스트와 프론트 lint 기준으로 우선 판단하고, Next build hang은 별도 이슈로 분리합니다.

## 테스트 체크리스트

- [ ] `/dev/detail-page-preview` 접속 가능
- [ ] 상품 예시 fixture 전환 가능
- [ ] 상세페이지 섹션이 깨지지 않고 렌더링됨
- [ ] 고객 노출 문구와 내부 지시문이 구분됨
- [ ] HTML/CSS 그래픽 섹션이 이미지 없이 표시됨
- [ ] mock 모드에서 실제 API 호출 없이 테스트 가능
- [ ] 실제 전체 플로우는 `/workspace/projects`에서 별도로 검증

## 자주 헷갈리는 점

### 3000과 3001 중 어디로 접속해야 하나요?

프론트 터미널에 표시된 주소를 따라가면 됩니다. 3000이 이미 사용 중이면 Next.js가 3001로 자동 실행할 수 있습니다.

### 테스트 페이지에서 PNG/JPG 다운로드도 확인할 수 있나요?

아니요. `/dev/detail-page-preview`는 화면 구조 확인용입니다. 다운로드는 실제 결과 페이지인 `/workspace/projects/{projectId}/result`에서 확인해야 합니다.

### 테스트 페이지 결과가 실제 AI 결과와 같나요?

아니요. 테스트 페이지는 fixture 기반입니다. 실제 API 모드의 결과 품질은 `.env`에서 mock을 끄고 실제 생성 플로우를 실행해야 확인할 수 있습니다.

