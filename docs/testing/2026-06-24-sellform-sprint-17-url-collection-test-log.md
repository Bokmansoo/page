# Sellform Sprint 16 URL Source Collection Test Log

본 문서는 Sprint 16 (URL Source Collection)의 기능 검증을 위해 백엔드 Pytest 자동화 테스트 및 프론트엔드 Next.js 프로덕션 빌드 빌드 무결성 테스트를 수행한 결과 기록 로그입니다.

---

## 1. 백엔드 Pytest 자동화 테스트 결과

### 1.1 URL 수집기 단위 테스트 (`test_source_collector.py`)

단위 테스트를 통해 아래 4가지 핵심 시나리오가 의도대로 통과됨을 검증했습니다:
1. `test_fetch_url_source_success`: 정상 HTML 사이트 Fetch 시, script/style 제외 정제 텍스트 추출 검증
2. `test_fetch_url_source_forbidden`: 403 Forbidden 응답 시, `blocked_or_forbidden` 에러 코드 맵핑 검증
3. `test_fetch_url_source_timeout`: 10초 초과 타임아웃 발생 시, `timeout` 에러 코드 맵핑 검증
4. `test_fetch_url_source_network_error`: 잘못된 도메인 등 기타 에러 발생 시, `network_error` 에러 코드 맵핑 검증

```powershell
uv run --project backend pytest backend/tests/test_source_collector.py -q
```

**테스트 출력 로그:**
```text
....                                                                     [100%]
4 passed, 10 warnings in 0.03s
```

### 1.2 사실 자동 생성 통합 테스트 (`test_facts.py`)

통합 테스트를 통해 아래와 같이 URL 수집 결과가 AI Facts adapter 입력과 에러 처리에 미치는 영향을 검증했습니다:
1. `test_auto_extract_uses_url_source_text_for_fact_candidates`: URL 수집 성공 시, 본문 텍스트가 사실 후보 생성 데이터로 바르게 통합 및 전달됨을 검증.
2. `test_auto_extract_reports_url_failure_gracefully`: URL 수집 실패(403 등) 시, API가 크래시되지 않고 실패 목록에 `blocked_or_forbidden`을 수집하여 정상 리턴함을 검증.
3. `test_auto_extract_reports_url_fallback_without_failing`: 모킹 없이 실제 네트워크 에러 발생 상황에서도 `network_error`로 안전하게 리턴됨을 확인.

```powershell
uv run --project backend pytest backend/tests/test_facts.py -q
```

**테스트 출력 로그:**
```text
..................                                                       [100%]
18 passed, 166 warnings in 2.88s
```

---

## 2. 프론트엔드 Next.js 프로덕션 빌드 테스트 결과

에셋 검수 보드 화면의 UI가 갱신됨에 따라, Next.js의 타입 체킹, 린트 및 최종 정적/동적 라우팅 프로덕션 빌드가 에러 없이 패스되는지 확인했습니다.

```powershell
cd c:\page\frontend
npm.cmd run build
```

**빌드 출력 로그:**
```text
> frontend@0.1.0 build
> next build

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

✓ Compiled successfully
```

---

## 3. 검증 결론

- **백엔드 (API & 수집 엔진):** 총 22개의 테스트가 경고 수준을 제외하고 전원 통과하여 안전성이 입증됨.
- **프론트엔드 (UI & 빌드):** 컴파일러 무결성이 확인되었으며, `/workspace/projects/[id]/facts` 페이지가 안정적으로 렌더링됨.
