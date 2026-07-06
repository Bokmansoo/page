# Sellform

AI 상품 콘텐츠 스튜디오 — 판매자가 업로드 가능한 상세페이지 초안을 빠르게 만들고, 검수하며 다듬고, PNG/JPG/Figma 등 실제 운영 산출물로 내보내는 것을 목표로 하는 프로젝트입니다.

Sellform은 단순히 문구를 생성하는 도구가 아니라, 상품 정보·출처·이미지·판매 맥락을 함께 이해해서 “바로 쓸 수 있는 고품질 상세페이지 초안”을 만드는 흐름을 지향합니다.

## 프로젝트 개요

현재 Sellform은 AI 기반 상품 상세페이지 제작 워크플로우를 중심으로 개발되고 있습니다.

판매자가 상품명, 이미지, 참고 URL, 핵심 특징을 입력하면 다음 과정을 거쳐 상세페이지 초안을 생성합니다.

1. 상품 정보와 판매 포인트 이해
2. 출처 기반 근거 수집 및 검증
3. 상세페이지 섹션 구성
4. AI 이미지 또는 HTML/CSS 기반 비주얼 섹션 생성
5. 판매자 검수 화면에서 문구와 구성을 다듬기
6. 결과 화면에서 PNG/JPG/Figma 등으로 내보내기

## 핵심 기능

### 1. AI 상세페이지 생성

- 상품 정보 기반 상세페이지 섹션 자동 구성
- HERO, 비교, 상세 설명, 보증/체크포인트 등 섹션 단위 생성
- 판매 맥락에 맞는 제목/본문/CTA 초안 작성

### 2. 출처 기반 콘텐츠 구성

- 참고 URL, 상품 이미지, 입력 정보에서 근거 수집
- AI가 만든 문구와 실제 출처 간 불일치 검수
- 과장 표현, 근거 없는 표현, 누락 이미지 등을 검수 대상으로 표시

### 3. 이미지 및 비주얼 생성

- 상품 이미지 기반 AI 이미지 생성
- 섹션별 이미지 후보 관리
- 이미지가 없는 경우 HTML/CSS 비주얼 카드로 대체하는 방향 설계
- 이미지 위 텍스트 오버레이를 HTML/CSS로 렌더링해 업로드 가능한 상세페이지 이미지로 내보내는 구조를 목표로 함

### 4. 검수하며 다듬기

- 생성된 상세페이지를 실제 구매자 화면 흐름으로 미리보기
- 섹션별 제목/본문 직접 수정
- AI 문구 수정 버튼 제공
  - 제목 강화
  - 짧고 자연스럽게
  - 과장 표현 축소
  - 사용 장면 보강
  - 초보 셀러 톤
  - 구매 불안 감소
  - 직접 요청 반영

### 5. 결과 내보내기

- 상세페이지 결과 화면 제공
- PNG/JPG 다운로드 방향 설계
- Figma 플러그인 및 Figma MCP 연동 실험
- 업로드 가능한 최종 산출물과 판매자가 다듬는 고품질 초안을 동시에 지원하는 것을 목표로 함

## 기술 스택

### Backend

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- uv
- OpenAI / Anthropic / Gemini 연동 구조
- Playwright 기반 렌더링/캡처 흐름

### Frontend

- Next.js 14
- React 18
- TypeScript
- Tailwind CSS
- Playwright E2E 테스트

### Integrations

- Figma plugin
- Figma bridge
- 이미지 생성 provider abstraction
- 출처/근거 수집 서비스

## 프로젝트 구조

```text
.
├── backend/                  # FastAPI 백엔드
│   ├── src/
│   │   ├── agents/           # AI 상세페이지 생성 에이전트 노드
│   │   ├── api/              # API 라우트
│   │   └── services/         # 생성, 검수, 이미지, export 서비스
│   └── tests/                # 백엔드 테스트
│
├── frontend/                 # Next.js 프론트엔드
│   ├── src/app/              # App Router 페이지
│   ├── src/components/       # 생성/검수/결과 UI 컴포넌트
│   ├── e2e/                  # Playwright E2E 테스트
│   └── tests/                # 프론트엔드 단위/스크립트 테스트
│
├── integrations/             # Figma bridge / plugin
├── docs/                     # 기획, 실행계획, 리뷰, 런북, 테스트 기록
├── memory/                   # 프로젝트 학습/결정 기록
└── README.md
```

## 로컬 실행

### Backend

```powershell
cd backend
uv sync
uvicorn src.app:app --host 0.0.0.0 --port 8001 --reload
```

API 문서:

```text
http://localhost:8001/docs
```

### Frontend

```powershell
cd frontend
npm install
npm.cmd run dev
```

프론트엔드:

```text
http://localhost:3000
```

### Production build 확인

```powershell
cd frontend
npm.cmd run build
npm.cmd run verify:production-build
npm.cmd run start:fresh
```

## 테스트

### Backend

```powershell
cd backend
uv run pytest
```

### Frontend

```powershell
cd frontend
npm.cmd run lint
npm.cmd run test:build-guard
npm.cmd run test:e2e
```

## 현재 주요 개발 방향

최근 기획은 “업로드 가능한 상세페이지 이미지”와 “판매자가 다듬을 수 있는 고품질 초안”을 동시에 만족시키는 쪽으로 정리되어 있습니다.

주요 작업 축은 다음과 같습니다.

1. HTML/CSS 기반 비주얼 섹션 계약 정리
2. PNG/JPG 다운로드가 실제 렌더링 결과와 일치하도록 export parity 강화
3. AI 문구 수정 버튼이 `[AI 수정됨]` 같은 표시를 붙이는 대신 실제 대본을 자연스럽게 다시 쓰도록 개선
4. 누락 이미지/HTML graphic/AI 생성 이미지가 같은 상세페이지 렌더링 파이프라인에서 동작하도록 통합
5. 결과 라우트가 production build에 포함되는지 자동 검증

관련 문서:

- `docs/superpowers/specs/2026-07-06-sellform-upload-ready-html-overlay-and-ai-copy-edit-design.md`
- `docs/superpowers/plans/2026-07-06-sellform-sprint-61-html-visual-contract-and-rendering.md`
- `docs/superpowers/plans/2026-07-06-sellform-sprint-62-png-jpg-export-parity.md`
- `docs/superpowers/plans/2026-07-06-sellform-sprint-63-ai-copy-rewrite.md`
- `docs/superpowers/plans/2026-07-06-sellform-sprint-64-integration-hardening.md`

## 로드맵

- HTML/CSS 오버레이 기반 상세페이지 이미지 렌더링
- PNG/JPG 다운로드 안정화
- AI 문구 수정 품질 개선
- 섹션별 이미지 누락/대체 비주얼 처리 통합
- Figma export 품질 강화
- 판매자용 검수 UX 개선
- 생성 결과 이력/라이브러리 관리
- 마켓플레이스 업로드 흐름 확장

## 상태

이 저장소는 Sellform의 개발 진행 기록과 구현물을 함께 보관합니다. 현재는 빠른 제품 검증과 상세페이지 생성 품질 개선을 중심으로 개발 중입니다.
