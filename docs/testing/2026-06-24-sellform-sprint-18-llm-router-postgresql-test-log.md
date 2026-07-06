# Sellform Sprint 18 LLM Router & PostgreSQL Test Log

본 문서는 Sprint 18 (LLM Router 및 PostgreSQL Runtime Setup) 구현 기능의 유효성 검증을 위해 백엔드 Pytest 자동화 테스트 및 프론트엔드 Next.js 프로덕션 빌드를 수행한 결과 기록 로그입니다.

---

## 1. 백엔드 Pytest 자동화 테스트 결과

### 1.1 SQLite 환경 하의 전체 회귀 테스트

단위 테스트 `test_llm_router.py` (3 Passed)를 포함한 전체 백엔드 회귀 테스트를 SQLite 기본 개발 데이터베이스 환경에서 수행했습니다.

```powershell
uv run --project backend pytest -q
```

**테스트 출력 로그:**
```text
............................................................................. [100%]
77 passed, 502 warnings in 10.93s
```

### 1.2 PostgreSQL 런타임 호환성 테스트 (Docker)

Docker Compose로 기동한 PostgreSQL 개발/운영 컨테이너에 DDL 및 트랜잭션이 완벽하게 이관 작동하는지 검증하기 위해 임시 환경변수를 구성하여 Facts API 통합 테스트를 기동했습니다.

```powershell
# 1. PostgreSQL DB 구동 (충돌 방지를 위해 호스트 포트를 5434로 매핑)
docker compose up -d db

# 2. 임시 DATABASE_URL 주입 후 pytest 수행
$env:DATABASE_URL="postgresql://sellform:sellformpassword@localhost:5434/sellform_dev"
uv run --project backend pytest backend/tests/test_facts.py -q
```

**테스트 출력 로그:**
```text
....................                                                     [100%]
20 passed, 182 warnings in 2.24s
```

---

## 2. 프론트엔드 Next.js 프로덕션 빌드 결과

Pydantic Schema 스펙 갱신(`provider` 및 `model_name` 메타데이터 필드 추가)에 맞춰 프론트엔드의 컴파일 무결성이 확보되었는지 Next.js 프로덕션 빌드를 구동하여 검증했습니다.

```powershell
cd c:\page\frontend
npm.cmd run build
```

**빌드 출력 로그:**
```text
▲ Next.js 14.2.35

Creating an optimized production build ...
✓ Compiled successfully
Linting and checking validity of types ...
Collecting page data ...
Generating static pages (0/9) ...
Generating static pages (2/9) 
Generating static pages (4/9) 
Generating static pages (6/9) 
✓ Generating static pages (9/9)
Finalizing page optimization ...
Collecting build traces ...

Route (app)                               Size     First Load JS
┌ ○ /                                     138 B          87.4 kB
├ ○ /_not-found                           873 B          88.1 kB
├ ƒ /p/[id]                               3.28 kB        90.5 kB
├ ○ /workspace                            2.56 kB        98.6 kB
├ ○ /workspace/operations                 3.48 kB        90.7 kB
├ ƒ /workspace/projects/[id]/export       3.73 kB          91 kB
├ ƒ /workspace/projects/[id]/facts        8.89 kB         105 kB
├ ƒ /workspace/projects/[id]/page-editor  5.82 kB        93.1 kB
├ ƒ /workspace/projects/[id]/publish      3.84 kB        91.1 kB
├ ○ /workspace/projects/new               3.94 kB        91.2 kB
└ ○ /workspace/settings                   4.73 kB          92 kB
+ First Load JS shared by all             87.3 kB

Compiled successfully
```

---

## 3. 종합 검증 결론

- **라우터 폴백 신뢰도:** OpenAI 실패 시 Gemini로, Gemini 실패 시 로컬 룰 기반 분석으로 오류 없이 순차 폴백이 작동함을 검증했습니다.
- **이기종 DB 무결성:** SQLAlchemy 모델의 타입 정의가 SQLite 및 PostgreSQL 런타임 환경 모두에서 호환성 충돌 없이 완전히 동일하게 수행됨을 실환경 테스트를 통해 확보했습니다.
- **프론트엔드 빌드 무결성:** 타입 무결성이 확보되어 프로덕션 컴파일이 성공적으로 완수되었습니다.

---

## 4. 후속 검증 - 설정 네이밍 정리 (2026-06-25)

Sprint 18 후속 정리로 `FACTORY_LLM_*` 공개 예시를 제거하고 `SELLFORM_LLM_*` 기준으로 통일한 뒤 회귀 검증을 수행했습니다.

### 4.1 설정 로드 확인

```powershell
uv run python -c "from src.config import settings; print(settings.SELLFORM_LLM_DEFAULT_PROVIDER); print(settings.SELLFORM_LLM_DEFAULT_MODEL); print(settings.SELLFORM_LLM_FALLBACK1_PROVIDER); print(settings.SELLFORM_LLM_FALLBACK1_MODEL); print(settings.effective_openai_model)"
```

결과:

```text
openai
gpt-5.4-nano
google
gemini-2.5-flash
gpt-5.4-nano
```

### 4.2 백엔드 회귀 테스트

```powershell
uv run pytest tests/test_llm_router.py tests/test_ai_adapter.py tests/test_facts.py -q
```

결과:

```text
28 passed, 182 warnings in 2.75s
```

### 4.3 프론트엔드 빌드

```powershell
cd frontend
npm.cmd run build
```

결과:

```text
✓ Compiled successfully
✓ Generating static pages (9/9)
```
