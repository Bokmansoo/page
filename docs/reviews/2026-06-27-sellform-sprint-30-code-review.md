# 코드 리뷰: Sellform Sprint 30 - 상품 이미지 자산 매핑 및 상세페이지 삽입

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-27 |
| 리뷰 범위 | 이미지 자산 자동 매핑 서비스, 페이지 이미지 매핑 API, 상세페이지 초안 생성 후 이미지 매핑, visual renderer 이미지 슬롯, export PNG 이미지 삽입, page-editor 이미지 매핑 UX |
| 기준 문서 | `docs/superpowers/plans/2026-06-27-sellform-sprint-30-image-asset-mapping-export-실행계획.md` |
| 리뷰어 | Codex |

## 1. 결론

Sprint 30은 핵심 구현의 뼈대가 들어왔지만, 아직 기획서 기준으로 “완료”라고 보기에는 이른 상태다.

구현된 부분:

- `backend/src/services/image_asset_mapper.py` 이미지 자산 매핑 서비스 추가
- `POST /api/v1/projects/{project_id}/page/auto-map-images` API 추가
- 상세페이지 초안 생성 후 이미지 자산 자동 매핑 시도 추가
- `visual_page_renderer`에서 `image_asset_id` 기반 `product_image` 슬롯 생성
- `export_service`에서 실제 이미지 파일을 열어 export PNG에 삽입하는 경로 추가
- page-editor에서 이미지 자동 배치 버튼과 섹션별 이미지 선택 UI 추가
- Sprint 30 관련 백엔드 테스트 파일 추가

보완이 필요한 부분:

- 이미지 매핑 서비스가 점수 0점인 경우에도 모든 섹션에 이미지를 배정할 수 있음
- 이미지 1장만 있을 때 hero/main_claim 중심으로 쓰고 나머지는 비우라는 계획과 다르게 여러 섹션에 반복 배치될 수 있음
- 이미지가 매칭되지 않은 섹션도 `product_image` 슬롯처럼 표시될 수 있음
- export 이미지 테스트가 Windows 파일 잠금 문제로 실패함
- Sprint 30 테스트 로그와 트러블슈팅 문서가 아직 없음

## 2. 기획 대비 구현 확인

| 항목 | 상태 | 확인 내용 |
| --- | --- | --- |
| 이미지 MIME 타입 필터링 | 완료 | `map_image_assets_to_sections`에서 `mime_type.startswith("image/")` 필터 적용 |
| 파일명/섹션 기반 점수 계산 | 부분 완료 | 기본 키워드 점수는 있으나 source_type 가중치는 없음 |
| 중복 제어 | 부분 완료 | 사용 횟수 기반 tie-break는 있으나 실제 중복 제한은 약함 |
| 이미지 1장일 때 hero/main_claim 중심 사용 | 미흡 | 현재는 이미지 1장이 여러 섹션에 반복 매핑될 수 있음 |
| 스펙/인증 이미지 우선 배치 | 부분 완료 | `spec/kc/cert` 키워드 점수는 있으나 0점 매핑 방지 없음 |
| 자동 매핑 API | 완료 | `/projects/{project_id}/page/auto-map-images` 구현 |
| overwrite=false 기존 매핑 유지 | 완료 | 기존 `image_asset_id`가 있으면 skip |
| 상세페이지 초안 생성 후 자동 매핑 | 완료 | page 생성 후 asset이 있으면 매핑 시도 |
| 자동 매핑 실패 시 페이지 생성 유지 | 완료 | try/except로 warning 로그 처리 |
| 섹션별 product_image 슬롯 | 부분 완료 | 매칭된 asset은 슬롯에 포함되나 미매칭 섹션 fallback이 애매함 |
| export PNG 실제 이미지 삽입 | 부분 완료 | Pillow 렌더링 경로는 있으나 테스트 실패 |
| page-editor 자동 매핑 버튼 | 완료 | 우측 패널에 자동 배치 실행 버튼 추가 |
| page-editor 섹션별 이미지 선택 | 완료 | 섹션 편집 패널에 이미지 select 추가 |
| 이미지 썸네일 표시 | 미흡 | 현재는 파일명 표시 중심이며 실제 썸네일 미리보기는 부족 |
| export 전 이미지 연결 경고 | 미흡 | 이미지 연결 개수/경고 UX가 명확히 구현된 흔적은 약함 |
| 테스트 로그/리뷰/트러블슈팅 문서 | 부분 완료 | 리뷰 문서는 본 문서로 작성. 테스트 로그/트러블슈팅 문서는 아직 필요 |

## 3. 발견 이슈

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 🟠 M1. 이미지 매핑 서비스가 0점 후보도 섹션에 배정함

- 위치: `backend/src/services/image_asset_mapper.py`
- 내용: `_calculate_match_score` 결과가 0점이어도 `best_asset`이 선택되어 assignment에 들어간다. 이 경우 문맥과 무관한 이미지가 모든 섹션에 배치될 수 있다.
- 영향: 상세페이지가 실제 상품 이미지 중심으로 보이기보다는, 같은 이미지가 무작위 반복된 결과가 될 수 있다.
- 권고:
  - `best_score <= 0`이면 해당 섹션은 매핑하지 않는다.
  - 단, 이미지가 1장이고 섹션이 `hero/problem_statement/main_claim`이면 예외적으로 배정한다.

### 🟠 M2. 이미지 1장일 때 반복 배치 제한이 부족함

- 위치: `backend/src/services/image_asset_mapper.py`
- 내용: 기획서에는 이미지가 1장뿐이면 hero/main_claim 중심으로 사용하고 나머지는 비워두도록 되어 있다. 현재는 사용 횟수 기반 tie-break만 있고 반복 제한이 명확하지 않다.
- 영향: export 결과가 같은 이미지 반복으로 단조로워질 수 있다.
- 권고:
  - asset 수가 1개일 때는 상위 우선 섹션 1~2개에만 배치한다.
  - asset별 최대 사용 횟수 기본값을 둔다.

### 🟡 M3. 미매칭 섹션도 `product_image` fallback처럼 표시될 수 있음

- 위치: `backend/src/services/visual_page_renderer.py`
- 내용: `_visual_slot_for`는 `image_assets`가 하나라도 있으면 `kind="product_image"`를 반환한다. 실제 `image_asset_id`가 매칭되지 않은 섹션도 product image 영역처럼 취급될 수 있다.
- 영향: 섹션별 이미지 매핑 상태가 명확하지 않고, export에서 실제 이미지가 아닌 placeholder가 “업로드된 상품 이미지”로 보일 수 있다.
- 권고:
  - `matched_asset`이 없으면 `selected_background` 또는 `placeholder`를 사용한다.
  - `product_image`는 실제 `asset_id/file_path`가 있는 경우에만 사용한다.

### 🟡 M4. export 이미지 테스트가 Windows 파일 잠금으로 실패함

- 위치: `backend/tests/test_export_image_asset_rendering.py`
- 증상:

```text
FAILED backend\tests\test_export_image_asset_rendering.py::test_run_export_draws_real_image_fit_into_slots
PermissionError: [WinError 5] 액세스가 거부되었습니다: 'C:\\page\\uploads\\temp_test_product.png'
```

- 원인 추정: 테스트에서 생성한 `Image` 객체를 명시적으로 닫지 않은 상태에서 동일 파일을 삭제하려고 해 Windows 파일 잠금이 발생한 것으로 보인다.
- 권고:
  - 테스트 이미지 생성 시 `with Image.new(...) as img:` 패턴을 쓰거나 `img.close()`를 호출한다.
  - 가능하면 `tmp_path`를 사용하고 export path도 테스트 전용 위치로 격리한다.

### 🟡 M5. Sprint 30 산출 문서가 아직 부족함

- 누락:
  - `docs/testing/2026-06-27-sellform-sprint-30-image-asset-mapping-test-log.md`
  - `docs/troubleshooting/2026-06-27-sellform-sprint-30-image-assets.md`
- 영향: 이후 회귀 추적과 운영 재현성이 약해진다.
- 권고: 보완 작업 후 테스트 로그와 트러블슈팅 문서를 작성한다.

## 4. 테스트 증적

### Sprint 30 관련 백엔드 테스트

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
PermissionError: [WinError 5] 액세스가 거부되었습니다.
```

### 프론트엔드 빌드

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

## 5. 긍정적인 부분

- 새 DB 모델을 추가하지 않고 기존 `Asset`과 `PageSection.image_asset_id`를 활용한 방향은 기획과 잘 맞는다.
- 자동 매핑 API, 초안 생성 후 매핑, page-editor 수동 선택, export 렌더링까지 전체 흐름의 주요 연결점은 만들어졌다.
- export에 실제 이미지를 삽입하려는 테스트가 추가되어, “이미지 중심 상세페이지”로 가는 핵심 품질 기준이 생겼다.
- page-editor에서 사용자가 자동 매핑 결과를 직접 교체할 수 있는 방향은 좋다.

## 6. 우선순위 권고

1. **M4 테스트 실패 수정**
   - 현재 테스트가 실패하므로 Sprint 30 완료 판정 불가.

2. **M1/M2 매핑 품질 보완**
   - 점수 0점 배정 방지와 1장 이미지 반복 제한은 실제 결과물 품질에 직접 영향을 준다.

3. **M3 visual slot fallback 정리**
   - 실제 이미지가 있는 섹션과 없는 섹션을 명확히 구분해야 한다.

4. **문서 산출물 보강**
   - 테스트 로그와 트러블슈팅 문서를 추가한다.

## 7. 최종 판정

Sprint 30은 “부분 구현 완료 / 보완 필요” 상태다.

기획의 핵심 구조는 들어왔지만, 테스트 실패와 이미지 매핑 품질 이슈가 남아 있어 아직 기획서 기준 완료로 보기는 어렵다. 보완 후 Sprint 30 관련 테스트와 전체 백엔드 테스트를 다시 실행해야 한다.
