# Sprint 28 보완 테스트 로그

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-27 |
| 범위 | AI 배경 후보 생성, 배경 선택 API, 선택 배경 export 반영 회귀 테스트 |

## 1. 보완 배경

Sprint 28 코드리뷰 확인 결과, 기능 뼈대는 구현되어 있었지만 전용 자동 테스트가 부족했다. 특히 다음 항목은 회귀 테스트로 고정할 필요가 있었다.

- 배경 후보가 안전한 한글 후보로 생성되는지
- 배경 후보 API가 프로젝트 스코프에서 동작하는지
- 선택한 배경이 프로젝트에 저장되는지
- 잘못된 배경 후보 ID가 거부되는지
- export가 선택된 배경 팔레트를 실제 이미지에 반영하는지

## 2. 추가 테스트

- `backend/tests/test_visual_background_service.py`
  - 생활/리빙 배경 후보 3종과 안전 문구 검증
- `backend/tests/test_visual_background_api.py`
  - 후보 생성 API, 후보 선택 API, 잘못된 후보 ID 거부 검증
- `backend/tests/test_export_visual_background.py`
  - 선택한 `cooling-blue` 배경이 export 이미지 상단 팔레트에 반영되는지 검증

## 3. 실행 결과

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_background_service.py backend\tests\test_visual_background_api.py backend\tests\test_export_visual_background.py -q
```

결과:

```text
5 passed
```

## 4. 비고

- PowerShell 출력에서는 일부 한글이 깨져 보일 수 있으나, UTF-8 파일 내부 문자열은 정상 한글로 확인했다.
- 실제 브라우저 QA에서는 page-editor의 “AI 배경 비주얼” 패널과 export 결과 이미지를 다시 확인해야 한다.

