# 테스트 실행 로그: 셀폼(Sellform) Sprint 7

본 문서는 셀폼 스프린트 7 구현에 대한 자동화 테스트 및 프론트엔드 빌드 검증 실행 증적입니다.

---

## 1. 백엔드 자동화 테스트 결과

### 1.1 단위 테스트 실행 내역 (`pytest tests/test_operations.py`)
```text
tests\test_operations.py .                                               [100%]
======================= 1 passed, 171 warnings in 0.71s =======================
```

### 1.2 전체 백엔드 회귀 테스트 실행 내역 (`pytest`)
```text
collected 45 items

tests\test_ai_adapter.py .....                                           [ 11%]
tests\test_ai_api.py ....                                                [ 20%]
tests\test_compliance.py ............                                    [ 46%]
tests\test_exports.py ..                                                 [ 51%]
tests\test_facts.py ......                                               [ 64%]
tests\test_operations.py .                                               [ 66%]
tests\test_pages.py ...                                                  [ 73%]
tests\test_pages_sprint4_remediation.py ....                             [ 82%]
tests\test_projects.py ...                                               [ 88%]
tests\test_publications.py ..                                            [ 93%]
tests\test_validation.py ...                                             [100%]

====================== 45 passed, 323 warnings in 9.37s =======================
```

---

## 2. 프론트엔드 빌드 및 린트 검증 결과

### 2.1 Next.js 프로덕션 빌드 실행 내역 (`npm run build`)
```text
> frontend@0.1.0 build
> next build

  ▲ Next.js 14.2.35

   Creating an optimized production build ...
 ✓ Compiled successfully
   Linting and checking validity of types ...
   Collecting page data ...
 ✓ Generating static pages (8/8)
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
└ ○ /workspace/projects/new               3.94 kB        91.2 kB
+ First Load JS shared by all             87.3 kB

✓ Compiled and built successfully without any TypeScript or Lint errors.
```
