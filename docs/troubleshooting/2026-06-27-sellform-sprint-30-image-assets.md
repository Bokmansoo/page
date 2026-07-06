# Sprint 30 트러블슈팅 - 이미지 자산 매핑 및 export 파일 잠금

## 1. 문제 요약

Sprint 30 구현 리뷰 중 다음 문제가 발견되었다.

1. 이미지 자동 매핑 서비스가 매칭 점수 0점 이미지도 섹션에 배정함
2. 이미지가 1장뿐일 때 여러 섹션에 반복 배치될 수 있음
3. 실제 이미지가 매칭되지 않은 섹션도 `product_image` 슬롯처럼 표시될 수 있음
4. Windows 테스트 환경에서 export 이미지 테스트가 파일 삭제 단계에서 실패함

## 2. 원인

### 2.1 0점 이미지 배정

`map_image_assets_to_sections`가 `best_asset`만 있으면 assignment를 생성하고 있었다. 이 때문에 섹션 타입과 파일명 힌트가 맞지 않아 점수가 0점이어도 이미지가 배정됐다.

### 2.2 단일 이미지 반복 배치

기존 로직은 사용 횟수 기반 tie-break만 있었고, 이미지가 1장뿐인 경우 “대표 섹션에만 사용”하는 제한이 없었다.

### 2.3 visual slot fallback 혼동

`visual_page_renderer._visual_slot_for`가 프로젝트에 이미지 자산이 하나라도 있으면 `product_image` 슬롯을 반환했다. 하지만 섹션별 `image_asset_id`가 실제로 매칭되지 않은 경우에는 `generated_background` 또는 `placeholder`가 더 정확하다.

### 2.4 Windows 파일 삭제 실패

테스트에서 `uploads` 경로에 PNG를 만들고 같은 프로세스에서 바로 삭제할 때 `PermissionError: [WinError 5]`가 발생했다. export 기능 실패라기보다는 Windows/샌드박스 파일 삭제 권한과 Pillow 파일 처리 방식이 겹친 테스트 환경 문제였다.

## 3. 조치

### 3.1 이미지 매핑 서비스 보완

- `best_score <= 0`이면 배정하지 않도록 수정
- 이미지가 1장뿐이면 `hero/problem_statement/main_claim` 섹션 중 첫 적합 섹션에만 배정
- 자산별 기본 반복 사용 횟수 제한 추가

### 3.2 visual slot fallback 보완

- 실제 `image_asset_id`와 asset이 매칭되는 경우에만 `product_image` 슬롯 사용
- 매칭 asset이 없으면 `selected_background` 또는 `placeholder` 사용

### 3.3 export 이미지 로딩 보완

- 파일 경로를 Pillow에 직접 넘기는 대신 `open(..., "rb")`로 bytes를 읽고 `BytesIO`에서 이미지를 열도록 수정
- 변환 이미지와 fitted 이미지 객체를 명시적으로 close

### 3.4 테스트 격리 보완

- export 테스트용 이미지는 고유 파일명으로 생성
- 관리형 Windows 테스트 샌드박스에서 Python 레벨 삭제가 실패할 수 있어, 테스트 간 충돌을 고유 파일명으로 회피
- `uploads/`는 `.gitignore` 대상이므로 테스트 이미지가 Git 추적 대상에 들어가지 않음

## 4. 재발 방지

- 이미지 매핑 로직 변경 시 0점 매핑 테스트를 반드시 유지한다.
- 이미지 1장 입력 시 반복 배치 제한 테스트를 유지한다.
- visual slot은 “실제 asset이 연결된 섹션”과 “배경 fallback 섹션”을 구분해야 한다.
- Windows에서 Pillow 테스트를 작성할 때는 파일 삭제를 테스트 성공 조건으로 두지 않는다.

## 5. 최종 검증

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

결과:

```text
126 passed, 598 warnings
```

```cmd
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
```
