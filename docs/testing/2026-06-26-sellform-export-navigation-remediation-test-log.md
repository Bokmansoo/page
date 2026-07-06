# Sellform export/navigation 보완 테스트 로그

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-26 |
| 범위 | 상세페이지 export 한글 렌더링, 단계별 뒤로가기, Sprint 28 AI 배경 비주얼 기획 |
| 환경 | Windows, PowerShell, PostgreSQL-only 로컬 개발 환경 |

## 1. 테스트 목적

- export 결과물에서 한글이 깨지거나 너무 작게 출력되는 문제를 재현하고 수정한다.
- page-editor/publish 화면의 상단 이동 버튼이 대시보드가 아니라 직전 단계로 돌아가도록 검증한다.
- AI 배경 비주얼 생성은 별도 Sprint 28 계획으로 분리되었는지 확인한다.

## 2. 실행 결과

| 테스트 | 명령 | 결과 |
| --- | --- | --- |
| export 서비스 단위 테스트 | `backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q` | PASS, 5 passed |
| 프론트 빌드 | `cd frontend && npm.cmd run build` | PASS |

## 3. 확인된 개선

- `load_export_font`가 한글 지원 폰트를 로드한다.
- export 이미지 폭이 480px에서 860px로 확대되었다.
- 제목/본문이 지정 폰트와 줄바꿈으로 렌더링된다.
- page-editor 상단 버튼은 사실 확인 화면으로 돌아간다.
- publish 상단 버튼은 저장/내보내기 화면으로 돌아간다.

## 4. 남은 항목

- 실제 브라우저에서 export를 다시 생성해 결과 PNG 가독성을 육안 확인한다.
- 상품별 AI 배경 생성은 Sprint 28에서 구현한다.

