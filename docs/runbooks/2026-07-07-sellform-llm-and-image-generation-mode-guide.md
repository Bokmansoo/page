# Sellform LLM / 이미지 생성 모드 확인 가이드

작성일: 2026-07-07

이 문서는 `.env` 설정을 보고 Sellform이 실제 API로 상세페이지를 만드는 상태인지, mock으로 테스트하는 상태인지 확인하는 기준을 정리합니다.

## 현재 확인된 상태

현재 `.env` 기준으로는 mock 테스트 모드가 아니라 실제 API를 사용하는 상태입니다.

```env
SELLFORM_RAG_RUNTIME_MOCK=false
SELLFORM_GENERATION_MODE=real
SELLFORM_IMAGE_GENERATION_MODE=real
SELLFORM_IMAGE_PROVIDER=openai
SELLFORM_IMAGE_MODEL=gpt-image-1-mini
```

API 키 값은 보안상 문서에 기록하지 않습니다. 키가 설정되어 있는지만 확인합니다.

## 설정별 의미

| 설정 | 현재 값 | 의미 |
| --- | --- | --- |
| `SELLFORM_RAG_RUNTIME_MOCK` | `false` | RAG/분석 흐름을 mock으로 강제하지 않음 |
| `SELLFORM_GENERATION_MODE` | `real` | 상세페이지 기획/문구 생성에 실제 LLM 사용 |
| `SELLFORM_IMAGE_GENERATION_MODE` | `real` | 이미지 생성에 실제 이미지 API 사용 |
| `SELLFORM_IMAGE_PROVIDER` | `openai` | 이미지 생성 provider로 OpenAI 사용 |
| `SELLFORM_IMAGE_MODEL` | `gpt-image-1-mini` | 이미지 생성 모델 |

따라서 지금 상태에서 `상세페이지 조립하기`를 누르면 텍스트 생성과 이미지 생성 모두 실제 API 호출을 시도합니다.

## 실제 API 모드

실제 텍스트 생성과 실제 이미지 생성을 모두 사용하려면 아래처럼 둡니다.

```env
SELLFORM_RAG_RUNTIME_MOCK=false
SELLFORM_GENERATION_MODE=real
SELLFORM_IMAGE_GENERATION_MODE=real
SELLFORM_IMAGE_PROVIDER=openai
SELLFORM_IMAGE_MODEL=gpt-image-1-mini
```

이 모드에서 이미지가 생성되지 않으면 먼저 아래를 확인합니다.

- `OPENAI_API_KEY`가 설정되어 있는지
- OpenAI 계정에 이미지 생성 권한/결제/한도가 있는지
- `SELLFORM_IMAGE_MODEL`이 현재 계정에서 사용 가능한 모델인지
- `.env` 변경 후 백엔드 서버를 재시작했는지

## 전체 mock 테스트 모드

비용 없이 전체 흐름만 테스트하고 싶으면 아래처럼 둡니다.

```env
SELLFORM_RAG_RUNTIME_MOCK=true
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
```

이 모드는 실제 LLM/API를 호출하지 않고, 테스트용 문구와 테스트용 이미지를 사용합니다.

## 텍스트는 실제 API, 이미지만 mock

상세페이지 기획/문구는 실제 LLM으로 만들고, 이미지 생성 비용이나 오류를 피하고 싶으면 아래처럼 둡니다.

```env
SELLFORM_RAG_RUNTIME_MOCK=false
SELLFORM_GENERATION_MODE=real
SELLFORM_IMAGE_GENERATION_MODE=mock
```

이 설정은 초안 품질은 실제 LLM으로 확인하면서, 이미지 생성은 mock으로 안정적으로 테스트할 때 유용합니다.

## 텍스트는 mock, 이미지만 실제 API

문구 생성 비용은 줄이고 이미지 API만 확인하고 싶으면 아래처럼 둘 수 있습니다.

```env
SELLFORM_RAG_RUNTIME_MOCK=true
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=real
SELLFORM_IMAGE_PROVIDER=openai
SELLFORM_IMAGE_MODEL=gpt-image-1-mini
```

다만 이 조합은 실제 운영 검증보다는 이미지 파이프라인 단독 확인용에 가깝습니다.

## 변경 후 반드시 해야 할 일

`.env`를 수정한 뒤에는 백엔드 서버를 재시작해야 합니다.

```cmd
cd /d C:\page
run_backend.cmd
```

프론트엔드는 이미 떠 있어도 되지만, 라우트나 화면 코드가 바뀐 경우에는 프론트도 재시작하는 편이 안전합니다.

```cmd
cd /d C:\page\frontend
npm.cmd run dev
```

## 3000 / 3001 포트 주의

Next.js dev 서버는 3000번 포트가 이미 사용 중이면 자동으로 3001번으로 뜰 수 있습니다.

따라서 브라우저 주소는 현재 터미널에 표시된 포트를 기준으로 맞춰야 합니다.

- `localhost:3000`으로 떴으면 3000 사용
- 3000이 이미 사용 중이라 `localhost:3001`로 떴으면 3001 사용

같은 기능을 테스트할 때는 프론트 포트를 섞어 쓰지 않는 것이 좋습니다.

## 빠른 판단 기준

| 원하는 상태 | 핵심 설정 |
| --- | --- |
| 실제 상세페이지 + 실제 이미지 | `SELLFORM_GENERATION_MODE=real`, `SELLFORM_IMAGE_GENERATION_MODE=real` |
| 실제 상세페이지 + mock 이미지 | `SELLFORM_GENERATION_MODE=real`, `SELLFORM_IMAGE_GENERATION_MODE=mock` |
| 전체 mock 테스트 | `SELLFORM_GENERATION_MODE=mock`, `SELLFORM_IMAGE_GENERATION_MODE=mock`, `SELLFORM_RAG_RUNTIME_MOCK=true` |

## 현재 프로젝트에서 발생했던 관련 이슈

이전에 이미지가 생성되지 않았던 원인 중 하나는 이미지 생성 서비스가 이미지 전용 설정인 `SELLFORM_IMAGE_GENERATION_MODE`가 아니라 텍스트 생성 설정인 `SELLFORM_GENERATION_MODE`를 보고 provider를 선택하던 문제였습니다.

수정 후에는 아래처럼 분리해서 동작합니다.

- 텍스트/기획 생성: `SELLFORM_GENERATION_MODE`
- 이미지 생성: `SELLFORM_IMAGE_GENERATION_MODE`

즉, 텍스트는 실제 API를 쓰고 이미지만 mock으로 돌리는 테스트가 가능해졌습니다.
