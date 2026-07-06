# Sprint 21 Versioning & Export Test Log

---

## 6. 후속 보완 검증 - 근거 추적 가능한 버전 스냅샷

### 보완 목적

상세페이지 버전이 문구/디자인만 저장하는 것을 넘어, 섹션이 참조한 사실 카드와 이미지 자산까지 함께 저장·복원되는지 확인한다.

### 추가 테스트

- `test_restore_page_version_preserves_fact_and_image_mappings`
  - 버전 복원 후 `associated_fact_ids`와 `image_asset_id`가 유지되는지 검증
- `test_page_snapshot_includes_fact_and_asset_evidence`
  - `create_page_snapshot(page, db)` 결과에 `facts_snapshot`, `assets_snapshot`, 카테고리, 스타일 키, 섹션 매핑 정보가 포함되는지 검증

### 재검증

```powershell
uv run pytest tests/test_pages.py::test_restore_page_version_preserves_fact_and_image_mappings tests/test_pages.py::test_page_snapshot_includes_fact_and_asset_evidence -q
```

- 결과: `2 passed`

```powershell
uv run pytest tests/test_pages.py tests/test_page_version_service.py tests/test_export_service.py tests/test_exports.py -q
```

- 결과: `16 passed`

```powershell
uv run pytest -q
```

- 결과: `97 passed, 556 warnings`

---

## 5. 후속 보완 검증 - 실제 버전 스냅샷 Export (2026-06-26)

### 실패 재현

실제 API가 저장하는 `DetailPageVersion.sections_json`은 dict snapshot이다.

```python
{
    "theme_color": "#fff",
    "font_family": "sans-serif",
    "sections": [{"key": "a", "title": "A", "body": "B"}],
}
```

기존 `run_export()`는 list만 가정해 dict key를 순회했고, 다음 오류가 발생했다.

```text
AttributeError: 'str' object has no attribute 'get'
```

### 보완 테스트

- `test_normalizes_detail_page_version_snapshot_dict`
- `test_run_export_accepts_detail_page_version_snapshot_dict`
- `test_restore_page_version`에 복원 후 섹션 개수 중복 방지 assertion 추가

### 재검증

```powershell
uv run pytest tests/test_export_service.py tests/test_pages.py::test_restore_page_version tests/test_exports.py::test_compliance_warning_and_successful_export -q
```

- 결과: `5 passed`

```powershell
uv run pytest -q
```

- 결과: `95 passed, 538 warnings`

```powershell
cd frontend
npm.cmd run build
```

- 결과: `Compiled successfully`

이 문서는 Sellform Sprint 21 상세페이지 버전 관리 및 내보내기(Export) 기능의 테스트 및 검증 로그를 기록합니다.

## 1. 테스트 환경
* **OS:** Windows Server / Local Developer Machine
* **Python Version:** 3.14.2
* **Node.js/Next.js Version:** Next.js 14.2.35
* **DB:** SQLite (with Schema Compatibility Middleware)

---

## 2. 백엔드 테스트 검증 (pytest)

백엔드에서는 `pytest`를 활용하여 신규 `DetailPageVersion` 및 `ExportArtifact` 모델, `page_version_service`, `export_service`의 동작과 API 라우터 연동을 검증했습니다.

### 테스트 실행 명령
```powershell
uv run --project backend pytest
```

### 테스트 결과 요약
* **총 테스트 개수:** 93개
* **결과:** 모두 통과 (`93 passed`)
* **수행 시간:** 약 21.63초

### 핵심 통과 테스트 목록
* [test_page_version_service.py](file:///c:/page/backend/tests/test_page_version_service.py)
  * `test_create_and_restore_page_version`: 버전 생성 및 sections_json 데이터 무결성 복원 검증.
  * `test_only_one_final_version_per_project`: 특정 프로젝트 내에서 최종본(is_final) 플래그가 단 1개만 활성화되는 독점적 토글 제어 검증.
* [test_export_service.py](file:///c:/page/backend/tests/test_export_service.py)
  * `test_build_export_manifest_for_long_image_and_section_zip`: 긴 세로 이미지 및 ZIP용 내보내기 매니페스트 빌드 동작 검증.
* [test_exports.py](file:///c:/page/backend/tests/test_exports.py)
  * `test_compliance_warning_and_successful_export`: Blocker가 없는 경고 상황에서 Pillow fallback을 활용하여 로컬 PNG/ZIP 파일이 성공적으로 빌드되고 `Asset` 및 `ExportArtifact`에 적재되는 연동 과정 전체 검증.
* [test_pages.py](file:///c:/page/backend/tests/test_pages.py)
  * `test_save_page_and_automatic_versioning`: PATCH API 호출 시 수정한 상세페이지가 `DetailPageVersion`에 스냅샷으로 자동 버저닝(사용자 수정)되는 로직 검증.
  * `test_restore_page_version`: 이전의 특정 버전으로의 상세페이지 복원(Restore) API 호출 및 실제 복원 롤백 검증.

---

## 3. 프론트엔드 최적화 빌드 검증

프론트엔드에서는 Next.js 번들링 과정에서의 타입 정합성 및 컴파일 최적화 동작을 빌드 스크립트를 통해 확인했습니다.

### 빌드 실행 명령
```powershell
npm.cmd run build
```

### 빌드 결과
```text
> frontend@0.1.0 build
> next build

  ▲ Next.js 14.2.35

   Creating an optimized production build ...
 ✓ Compiled successfully
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (0/9) ...
   Generating static pages (2/9) 
   Generating static pages (4/9) 
   Generating static pages (6/9) 
 ✓ Generating static pages (9/9)
   Finalizing page optimization ...
   Collecting build traces ...

Route (app)                               Size     First Load JS
┌ ○ /                                     138 B          87.4 kB
├ ○ /_not-found                           873 B          88.1 kB
├ ƒ /p/[id]                               3.28 kB        90.5 kB
├ ○ /workspace                            2.56 kB        98.6 kB
├ ○ /workspace/operations                 3.48 kB        90.7 kB
├ ƒ /workspace/projects/[id]/export       4.58 kB        91.8 kB
├ ƒ /workspace/projects/[id]/facts        8.89 kB         105 kB
├ ƒ /workspace/projects/[id]/page-editor  8.82 kB        96.1 kB
├ ƒ /workspace/projects/[id]/publish      3.84 kB        91.1 kB
├ ○ /workspace/projects/new               3.94 kB        91.2 kB
└ ○ /workspace/settings                   4.73 kB          92 kB
+ First Load JS shared by all             87.3 kB

✓ Compiled successfully
```

---

## 4. 검증 체크리스트
* [x] AI 초안 생성 시 버전 스냅샷 자동 적재 (`DetailPageVersion`)
* [x] 사용자 상세페이지 PATCH 저장 시 버전 스냅샷 자동 적재 (`DetailPageVersion`)
* [x] AI 부분 재생성(Regenerate Section) 시 버전 스냅샷 자동 적재 (`DetailPageVersion`)
* [x] 버전 목록 내역 UI 연동 (`name`, `style_key`, `is_final` 필드 노출)
* [x] 최종 버전 마킹 API 및 UI 연동 (한 프로젝트 당 1개만 `is_final=True` 유지)
* [x] 이전 임시/백업 스냅샷 복원(Restore) API 및 UI 연동
* [x] 내보내기 전 필수 체크리스트 4가지 항목 준수 여부에 따른 빌드 제어 기능 추가
* [x] Pillow 기반 긴 이미지 & 섹션별 ZIP 빌드 및 `Asset` & `ExportArtifact` 스키마 연동 완료
* [x] 긴 세로 이미지 다운로드 / 섹션별 이미지 ZIP 다운로드 기능 개별 제공
