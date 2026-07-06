# Sellform export/navigation 보완 트러블슈팅

## 증상 1. export 결과 PNG에서 한글이 깨지거나 너무 작게 보임

### 원인

- `backend/src/services/export_service.py`가 Pillow 기본 폰트를 사용했다.
- Pillow 기본 bitmap font는 한국어 글리프를 안정적으로 지원하지 않는다.
- 출력 폭이 480px이라 긴 한국어 문장과 모델명이 한 줄에 몰려 가독성이 낮았다.

### 조치

- `load_export_font`를 추가해 Windows/Noto/Nanum 계열 한글 폰트를 우선 로드했다.
- export 폭을 860px로 확대했다.
- 제목과 본문을 줄바꿈 처리하고 폰트 크기를 키웠다.

### 확인 명령

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q
```

## 증상 2. 상세페이지 편집 화면의 뒤로가기가 대시보드로 이동함

### 원인

- page-editor 상단 버튼이 `/workspace`로 고정되어 있었다.

### 조치

- page-editor 상단 버튼을 `/workspace/projects/{projectId}/facts`로 변경했다.

## 증상 3. 최종 발행 화면의 뒤로가기가 직전 단계가 아닌 편집기로 이동함

### 원인

- publish 화면 상단 버튼이 `/page-editor`로 이동했다.

### 조치

- publish 상단 버튼을 `/export`로 변경했다.

## 남은 개선

- 상품 맞춤 배경/히어로 이미지는 Sprint 28에서 별도 구현한다.
- 실제 export 파일은 브라우저에서 새로 생성해 육안으로 가독성을 확인한다.

