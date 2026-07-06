# 테스트 실행 로그: 셀폼(Sellform) Sprint 8

본 문서는 셀폼 스프린트 8 (SaaS 확장 및 가드레일) 구현에 대한 백엔드 자동화 테스트 및 프론트엔드 빌드 검증 실행 증적입니다.

---

## 1. 백엔드 자동화 테스트 결과

### 1.1 SaaS 신규 기능 테스트 실행 내역 (`pytest tests/test_saas_features.py`)
```text
collected 4 items

tests\test_saas_features.py ....                                         [100%]

======================= 4 passed, 35 warnings in 0.73s ========================
```

### 1.2 전체 백엔드 회귀 테스트 실행 내역 (`pytest`)
```text
collected 49 items

tests\test_ai_adapter.py .....                                           [ 10%]
tests\test_ai_api.py ......                                              [ 22%]
tests\test_compliance.py .===========                                    [ 46%]
tests\test_exports.py ....                                               [ 55%]
tests\test_facts.py ........                                             [ 71%]
tests\test_operations.py .                                               [ 73%]
tests\test_pages.py ...                                                  [ 79%]
tests\test_pages_sprint4_remediation.py ....                             [ 87%]
tests\test_projects.py ...                                               [ 93%]
tests\test_publications.py ..                                            [ 97%]
tests\test_saas_features.py ....                                         [100%]

====================== 49 passed, 355 warnings in 5.15s =======================
```

---

## 2. 프론트엔드 빌드 및 린트 검증 결과

### 2.1 Next.js 프로덕션 빌드 실행 내역 (`npm.cmd run build`)
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
├ ƒ /workspace/projects/[id]/facts        6.4 kB          102 kB
├ ƒ /workspace/projects/[id]/page-editor  5.53 kB        92.8 kB
├ ƒ /workspace/projects/[id]/publish      3.84 kB        91.1 kB
├ ○ /workspace/projects/new               3.94 kB        91.2 kB
└ ○ /workspace/settings                   4.73 kB          92 kB
+ First Load JS shared by all             87.3 kB
  ├ chunks/117-f1f0722679bdc789.js        31.7 kB
  ├ chunks/fd9d1056-253d8695cd74475a.js   53.6 kB
  └ other shared chunks (total)           1.89 kB


○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand

✓ Compiled and built successfully without any TypeScript or Lint errors.
```
# 보완 테스트 실행 로그 - 2026-06-24

## 0. RBAC 보완 회귀 테스트

### 0.1 RED 확인

```text
uv run --project . pytest tests/test_saas_features.py::test_viewer_cannot_create_project -q

FAILED tests/test_saas_features.py::test_viewer_cannot_create_project
assert 201 == 403
```

`viewer` 권한 사용자가 `POST /api/v1/projects` 호출 시 기존 구현에서 프로젝트를 생성할 수 있음을 확인했다.

### 0.2 GREEN 확인

```text
uv run --project . pytest tests/test_saas_features.py::test_viewer_cannot_create_project -q

1 passed, 11 warnings in 0.25s
```

### 0.3 Sprint 8 전체 테스트

```text
uv run --project . pytest tests/test_saas_features.py -q

5 passed, 36 warnings in 1.03s
```

### 0.4 프론트 빌드 재검증

```text
npm.cmd run build

Compiled successfully
Generating static pages (9/9)
```
