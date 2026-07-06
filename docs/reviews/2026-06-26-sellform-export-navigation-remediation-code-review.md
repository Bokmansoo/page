# 코드 리뷰: Sellform export/navigation 보완

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-26 |
| 리뷰 범위 | `export_service.py`, page-editor/publish 단계별 뒤로가기, Sprint 28 AI 배경 비주얼 계획 |
| 리뷰어 | Codex |

## 1. 변경 요약

- Pillow 기본 폰트로 인해 export PNG에서 한글이 깨지거나 작게 보이는 문제를 보완했다.
- `load_export_font`를 추가해 Windows/Noto/Nanum 계열 한글 폰트를 우선 로드한다.
- export 이미지 폭을 860px로 확대하고 제목/본문 줄바꿈 렌더링을 적용했다.
- page-editor 상단 버튼을 대시보드 이동이 아닌 “사실 확인으로 돌아가기”로 변경했다.
- publish 상단 버튼을 “저장/내보내기로 돌아가기”로 변경했다.
- 상품에 맞는 AI 배경 비주얼 생성은 Sprint 28 실행계획으로 분리했다.

## 2. 발견 및 조치된 이슈

### 🟠 M1. export 결과물의 한글 가독성 부족

- 위치: `backend/src/services/export_service.py`
- 내용: Pillow 기본 bitmap font와 480px 폭으로 인해 한국어 상세페이지 이미지가 읽기 어렵게 생성되었다.
- 조치: 한글 폰트 로더, 860px 출력 폭, 줄바꿈 렌더링, 큰 제목/본문 폰트를 적용했다.

### 🟡 M2. page-editor에서 뒤로가기가 대시보드로 이동

- 위치: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- 내용: 사용자가 단계 흐름 중 한 단계 뒤로 가고 싶어도 대시보드로 빠졌다.
- 조치: 사실 확인 화면(`/facts`)으로 돌아가도록 변경했다.

### 🟡 M3. publish에서 뒤로가기가 편집기로 이동

- 위치: `frontend/src/app/workspace/projects/[id]/publish/page.tsx`
- 내용: 최종 발행 단계에서 직전 단계는 export인데 편집기로 이동했다.
- 조치: 저장/내보내기 화면(`/export`)으로 돌아가도록 변경했다.

## 3. 검증

- `backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q`
  - 결과: `5 passed`
- `cd frontend && npm.cmd run build`
  - 결과: 성공

## 4. 남은 위험

- 실제 상품별 배경 이미지 생성은 아직 구현되지 않았다.
- export 결과물의 시각 품질은 브라우저에서 새 export를 생성해 육안 QA가 필요하다.
- AI 배경 생성은 Sprint 28에서 안전 규칙과 fallback을 포함해 구현해야 한다.

