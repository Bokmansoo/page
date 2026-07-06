# 코드 리뷰: Sellform Sprint 28 보완

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-27 |
| 리뷰 범위 | Sprint 28 AI 배경 비주얼 생성 전용 테스트 보강, export 배경 반영 회귀 검증 |
| 리뷰어 | Codex |

## 1. 변경 요약

- Sprint 28 전용 백엔드 테스트를 추가했다.
- 배경 후보 서비스가 생활/리빙용 안전 후보 3개를 반환하는지 검증했다.
- 배경 후보 생성 API와 배경 선택 API를 프로젝트 단위로 검증했다.
- 잘못된 배경 후보 ID가 `400`으로 거부되는지 검증했다.
- 선택된 `cooling-blue` 배경이 export 이미지에 실제로 반영되는지 픽셀 기준으로 검증했다.

## 2. 조치된 이슈

### 🟠 M1. Sprint 28 전용 회귀 테스트 부족

- 위치: `backend/tests/`
- 내용: Sprint 28 기능은 구현되어 있었지만, 후보 생성/선택/export 반영을 직접 검증하는 테스트 파일이 부족했다.
- 조치:
  - `backend/tests/test_visual_background_service.py`
  - `backend/tests/test_visual_background_api.py`
  - `backend/tests/test_export_visual_background.py`
  를 추가했다.

### 🟡 M2. export 배경 반영 검증 부재

- 위치: `backend/src/services/export_service.py`
- 내용: 선택한 배경 팔레트가 export 이미지에 반영되는지 자동 검증이 없었다.
- 조치: `test_run_export_uses_selected_project_background_palette`에서 `cooling-blue` 선택 시 export 상단 픽셀이 흰색이 아닌 쿨링 팔레트 계열인지 검증했다.

## 3. 검증

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_background_service.py backend\tests\test_visual_background_api.py backend\tests\test_export_visual_background.py -q
```

결과:

```text
5 passed
```

## 4. 남은 권고

- 브라우저에서 page-editor의 배경 후보 UI를 실제로 클릭해 수동 QA한다.
- 루메나 프로젝트에서 `cooling-blue`, `minimal-white`, `lifestyle-summer`를 각각 선택해 export 결과를 비교한다.
- 실제 이미지 생성 API 연동은 현재 범위가 아니며, 후속 고도화 Sprint에서 다룬다.

