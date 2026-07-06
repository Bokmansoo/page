# 테스트 실행 로그: Sellform Sprint 9 기준선

- 날짜: 2026-06-24
- 목적: Sprint 9 실사용 검증 시작 전 현재 코드 상태의 테스트/빌드 기준선을 고정한다.

## 1. 백엔드 테스트

```text
uv run --project . pytest -q

결과:
50 passed, 356 warnings in 8.92s
```

## 2. 프론트 빌드

```text
npm.cmd run build

결과:
Compiled successfully
Generating static pages (9/9)
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
```

## 3. 기준선 판단

Sprint 9 실사용 검증은 현재 자동 테스트와 프론트 빌드가 모두 무결하게 통과한 상태에서 안전하게 시작한다.
