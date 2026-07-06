# Sprint 30 이미지 자산 매핑 보완 테스트 로그

| 항목 | 내용 |
| --- | --- |
| 테스트 일자 | 2026-06-27 |
| 범위 | 이미지 자산 자동 매핑, 섹션별 visual slot, export 실제 이미지 삽입, 프론트 빌드 |
| 상태 | 통과 |

## 1. 보완 전 실패

### Sprint 30 관련 테스트

명령:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_image_asset_mapper.py backend\tests\test_page_image_mapping_api.py backend\tests\test_page_draft_image_mapping.py backend\tests\test_visual_page_renderer_image_slots.py backend\tests\test_export_image_asset_rendering.py -q
```

결과:

```text
5 passed, 1 failed
```

실패:

```text
test_run_export_draws_real_image_fit_into_slots
PermissionError: [WinError 5]
```

추가로 보완 테스트를 작성한 뒤 다음 케이스가 기존 구현에서 실패하는 것을 확인했다.

```text
test_map_image_assets_does_not_assign_zero_score_assets_to_unrelated_sections
test_map_image_assets_single_image_is_limited_to_priority_sections
test_build_visual_sections_uses_background_when_section_has_no_image_mapping
```

## 2. 보완 내용

- 매칭 점수 0점 이미지는 섹션에 자동 배정하지 않도록 수정
- 이미지가 1장뿐일 때는 `hero/problem_statement/main_claim` 우선 섹션에만 배정하도록 제한
- 자산별 기본 반복 사용 횟수를 제한
- 실제 `image_asset_id`가 매칭되지 않은 섹션은 `product_image`가 아니라 배경/placeholder 슬롯을 사용하도록 수정
- export 렌더링 시 원본 이미지 파일을 `BytesIO`로 읽어 원본 파일 핸들 잠금 가능성을 줄임
- Windows/샌드박스 환경에서 Python 레벨 파일 삭제가 제한될 수 있어 export 테스트 자산은 고유 파일명으로 격리

## 3. Sprint 30 관련 테스트 재실행

명령:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_image_asset_mapper.py backend\tests\test_page_image_mapping_api.py backend\tests\test_page_draft_image_mapping.py backend\tests\test_visual_page_renderer_image_slots.py backend\tests\test_export_image_asset_rendering.py -q
```

결과:

```text
9 passed, 23 warnings in 0.91s
```

## 4. 전체 백엔드 테스트

명령:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

결과:

```text
126 passed, 598 warnings in 20.00s
```

주요 warning:

- Pydantic V2 class-based config deprecation
- `datetime.utcnow()` deprecation
- `google.generativeai` package deprecation
- pytest cache path warning

이번 Sprint 30 보완 작업과 직접 관련된 실패는 없다.

## 5. 프론트엔드 빌드

명령:

```cmd
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
Linting and checking validity of types ...
Generating static pages (9/9)
```

## 6. 판정

Sprint 30 보완 작업 후 자동 이미지 매핑, 섹션별 visual slot fallback, export 실제 이미지 삽입 관련 테스트가 통과했다.

현재 기준 Sprint 30은 기획서의 핵심 완료 기준을 만족한다.
