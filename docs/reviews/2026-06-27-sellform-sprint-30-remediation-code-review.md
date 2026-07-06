# 코드 리뷰: Sellform Sprint 30 보완 작업

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-27 |
| 기준 리뷰 | `docs/reviews/2026-06-27-sellform-sprint-30-code-review.md` |
| 보완 범위 | 이미지 매핑 점수/반복 제한, visual slot fallback, export 이미지 파일 핸들 처리, 테스트 안정화 |
| 리뷰어 | Codex |

## 1. 변경 요약

Sprint 30 1차 리뷰에서 발견된 보완 항목을 반영했다.

- 이미지 매칭 점수가 0점이면 자동 배정하지 않도록 수정
- 이미지가 1장뿐일 때 대표 섹션에만 배정하도록 제한
- 자산별 반복 사용 횟수 제한 추가
- 실제 `image_asset_id`가 매칭되지 않은 섹션은 `product_image`가 아니라 background/placeholder fallback을 사용하도록 수정
- export 렌더링에서 파일 경로 기반 `Image.open` 대신 bytes 기반 `BytesIO` 로딩으로 변경
- Windows/샌드박스 환경의 Python 파일 삭제 제한을 고려해 export 테스트 자산을 고유 파일명으로 격리

## 2. 조치 완료 항목

### 🟠 M1. 0점 이미지 자동 배정

상태: 조치 완료

- `best_score > 0`인 경우에만 assignment를 생성하도록 수정했다.
- 관련 테스트:
  - `test_map_image_assets_does_not_assign_zero_score_assets_to_unrelated_sections`

### 🟠 M2. 이미지 1장 반복 배치

상태: 조치 완료

- 단일 이미지 모드에서는 `hero/problem_statement/main_claim` 우선 섹션 중 첫 번째 적합 섹션에만 배정한다.
- 관련 테스트:
  - `test_map_image_assets_single_image_is_limited_to_priority_sections`

### 🟡 M3. visual slot fallback 혼동

상태: 조치 완료

- 매칭된 asset이 있는 경우에만 `product_image` 슬롯을 사용한다.
- 매칭 asset이 없으면 선택 배경 또는 placeholder를 사용한다.
- 관련 테스트:
  - `test_build_visual_sections_uses_background_when_section_has_no_image_mapping`

### 🟡 M4. export 이미지 테스트 파일 잠금

상태: 조치 완료

- export 렌더링에서 원본 이미지를 bytes로 읽어 메모리에서 열도록 변경했다.
- 테스트 자산은 고유 파일명으로 격리했다.
- 관련 테스트:
  - `test_run_export_draws_real_image_fit_into_slots`

### 🟡 M5. 산출 문서 부족

상태: 조치 완료

- 테스트 로그 작성
- 트러블슈팅 문서 작성
- 보완 코드리뷰 문서 작성

## 3. 테스트 증적

### Sprint 30 관련 테스트

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_image_asset_mapper.py backend\tests\test_page_image_mapping_api.py backend\tests\test_page_draft_image_mapping.py backend\tests\test_visual_page_renderer_image_slots.py backend\tests\test_export_image_asset_rendering.py -q
```

결과:

```text
9 passed, 23 warnings in 0.91s
```

### 전체 백엔드 테스트

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

결과:

```text
126 passed, 598 warnings in 20.00s
```

### 프론트엔드 빌드

```cmd
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
Generating static pages (9/9)
```

## 4. 남은 위험

- 자동 매핑은 아직 파일명 기반 휴리스틱이므로, 실제 상품 이미지가 여러 장일 때 완벽한 의미 매칭은 어렵다.
- 섹션별 이미지 썸네일은 파일명 표시 중심이므로, 다음 고도화에서 실제 썸네일 UI를 더 강화할 수 있다.
- export 결과의 시각 완성도는 아직 “이미지 삽입 가능” 단계이며, 쿠팡형 고품질 상세페이지 수준의 이미지/카피 배치까지는 Sprint 31 이후 템플릿 고도화가 필요하다.

## 5. 최종 판정

Sprint 30 보완 작업 후 기획서의 핵심 완료 기준을 만족한다.

- 이미지 자산 자동 매핑 가능
- 섹션별 이미지 연결 가능
- page-editor에서 이미지 자동 배치/수동 선택 가능
- export PNG에 실제 상품 이미지 삽입 가능
- 이미지가 없는 섹션은 background/placeholder로 fallback
- 백엔드 테스트와 프론트 빌드 통과
