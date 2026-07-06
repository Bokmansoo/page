# Sprint 31 보완 테스트 로그

## 백엔드 타깃 테스트

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_commerce_visual_cut_builder.py backend\tests\test_visual_page_renderer_commerce_cuts.py backend\tests\test_export_commerce_visual_cuts.py backend\tests\test_commerce_cut_quality.py -q
```

결과:

```text
4 passed, 11 warnings
```

샌드박스에서는 Windows 사용자 임시 폴더 접근이 제한되어 프로젝트 내부 임시 경로를 지정해 실행했다.

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_commerce_visual_cut_builder.py backend\tests\test_visual_page_renderer_commerce_cuts.py backend\tests\test_export_commerce_visual_cuts.py backend\tests\test_commerce_cut_quality.py -q --basetemp=.pytest-tmp-sprint31
```

## 백엔드 전체 회귀 테스트

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q --basetemp=.pytest-tmp-backend-full
```

결과:

```text
130 passed, 598 warnings
```

## 프론트 빌드

```cmd
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
Generating static pages (9/9)
```

`page-editor/page.tsx`의 `<img>` 사용에 대한 Next.js 성능 경고 1건은 남아 있지만 빌드 실패는 아니다.

## Playwright 회귀 테스트

추가 파일:

`frontend/e2e/sprint31-commerce-cut-export.spec.ts`

수정 전 실행 결과:

```text
Expected: use_commerce_cut: true
Received: preset_name only
1 failed
```

수정 후에는 도구의 브라우저 실행 권한 사용 한도로 재실행하지 못했다. 로컬 CMD에서 다음 명령으로 최종 확인한다.

```cmd
cd frontend
npm.cmd run test:e2e -- sprint31-commerce-cut-export.spec.ts
```

2026-06-27 로컬 재실행 결과, 테스트 본문 진입 전 Playwright 웹 서버 준비 단계에서 다음 오류가 발생했다.

```text
Error: Timed out waiting 120000ms from config.webServer.
```

이는 export payload assertion 실패가 아니라 `next dev` 서버가 `http://127.0.0.1:3000`에서 준비되지 못한 테스트 인프라 오류다. 프론트 서버를 별도 CMD에서 먼저 실행한 뒤 테스트를 재실행해 GREEN 여부를 확인한다.
