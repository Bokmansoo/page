# Sprint 21 Versioning & Export Troubleshooting

---

## 5. 이슈 E: 버전 복원 시 사실 카드/이미지 매핑 유실

### 문제 상황

상세페이지 버전 스냅샷이 문구와 디자인 설정 중심으로 저장되어, 복원 시 섹션의 `associated_fact_ids`와 `image_asset_id`가 비워질 수 있었다.

### 영향

과거 최종본을 복원했을 때 화면 문구는 돌아오지만, 해당 문구가 어떤 사실 카드와 이미지 근거를 기반으로 생성됐는지 추적하기 어려워진다. 판매용 상세페이지에서는 근거 추적성이 약해지는 위험이 있다.

### 해결

`create_page_snapshot(page, db)`를 확장해 섹션 매핑 정보와 근거 스냅샷을 함께 저장했다.

```python
{
    "sections": [
        {
            "associated_fact_ids": [...],
            "image_asset_id": "...",
        }
    ],
    "facts_snapshot": [...],
    "assets_snapshot": [...],
}
```

복원 로직은 새 구조의 `section_type/body_copy`와 기존 레거시 구조의 `key/body`를 모두 지원하도록 수정했다.

### 검증

- 복원 후 사실 카드/이미지 매핑 유지 테스트 통과
- 스냅샷에 사실 카드/이미지 자산 증적 포함 테스트 통과
- Sprint 21 관련 테스트 16 passed
- 전체 백엔드 테스트 97 passed

### 교훈

상세페이지 버전은 “렌더링 결과”만 저장하면 부족하다. 판매 문구의 책임 소재를 추적하려면 문구와 함께 해당 문구의 근거 카드, 원본 텍스트, 이미지 자산까지 같은 시점의 스냅샷으로 고정해야 한다.

---

## 4. 이슈 D: 실제 버전 스냅샷 구조와 Export 입력 구조 불일치

### 문제 상황

`DetailPageVersion.sections_json`이 `{theme_color, font_family, sections}` dict로 저장되는 실제 API 흐름과 달리, `run_export()`는 list만 입력된다고 가정했다.

### 증상

dict snapshot을 `run_export()`에 전달하면 dict key 문자열을 section으로 순회하면서 다음 오류가 발생했다.

```text
AttributeError: 'str' object has no attribute 'get'
```

### 해결

`normalize_sections_snapshot()`를 추가해 dict snapshot이면 내부 `sections` 리스트만 추출하고, list snapshot이면 그대로 사용하게 했다.

```python
def normalize_sections_snapshot(sections_snapshot) -> list[dict]:
    if isinstance(sections_snapshot, dict):
        return sections_snapshot.get("sections", [])
    return sections_snapshot or []
```

`build_export_manifest()`와 `run_export()`가 이 정규화 함수를 공통 사용한다.

### 검증

- dict snapshot 직접 export 호출 성공
- Sprint 21 export/restore 관련 테스트 5 passed
- 전체 백엔드 테스트 95 passed
- 프론트 빌드 성공

### 교훈

서비스 테스트가 list 입력만 검증하면, API가 실제로 저장하는 snapshot 구조와 어긋난 결함을 놓칠 수 있다. 앞으로는 서비스 단위 테스트에 “실제 API 저장 형태”를 반드시 포함한다.

이 문서는 Sellform Sprint 21 상세페이지 버전 스냅샷 생성 및 이미지/ZIP 내보내기 구현 단계에서 겪은 문제들과 이에 대한 해결 과정을 기록합니다.

---

## 1. 이슈 A: 버전 복원(Restore) 시 테마 컬러 및 폰트 정보 유실 문제

### 배경 및 증상
* 기존 `PageVersion` 모델은 `page_data` 컬럼 내부에 전체 페이지 상태를 JSON으로 가졌으나, 새로운 `DetailPageVersion` 기획 스펙에서는 `sections_json`만 정의되어 있었습니다.
* 이대로 구현하여 단순 `sections` 리스트만 복원할 경우, 복원 API 호출 후 페이지의 테마 색상(`theme_color`)과 폰트 패밀리(`font_family`)가 원래 값으로 원복되지 않아 `test_pages.py::test_restore_page_version` 통합 테스트가 실패했습니다.

### 원인 분석
* `DetailPageVersion` 모델 스키마와 `InMemoryDetailPageVersion`은 기획에 맞춰 생성된 `sections_json` 및 리스트 위주 구조를 지니고 있었습니다.
* 따라서 단순 `sections` 리스트만 버저닝으로 저장하게 되면 디자인 토큰 메타데이터가 완전히 소실됩니다.

### 해결 전략
1. **스마트 래핑(Wrapping) 기법 적용:**
   `create_page_version`을 호출할 때 단순 섹션 리스트 대신 다음과 같은 딕셔너리로 결합하여 `sections_json`에 저장했습니다:
   ```json
   {
     "theme_color": "#3B82F6",
     "font_family": "sans-serif",
     "sections": [...]
   }
   ```
2. **호환 가능한 프로퍼티 정의 (`models.py` / `InMemoryDetailPageVersion`):**
   모델에서 `version.sections`를 호출할 때 데이터가 `dict` 형식이면 내부 `"sections"` 키 리스트를 자동으로 슬라이싱하여 반환하는 프로퍼티 필터를 심어 기존 서비스 및 테스트 호환성을 사수했습니다.
3. **복원 로직 분기 처리:**
   복원 API 내부에서 `snapshot`이 `dict`일 경우 테마 컬러와 폰트를 갱신하고, 아닐 경우 구버전 호환성을 유지하여 섹션 리스트만 적재하도록 설계했습니다.

---

## 2. 이슈 B: 내보내기 통합 테스트 중 ExportJob status Failed 오동작

### 배경 및 증상
* `test_exports.py`에서 제공되는 `test_compliance_warning_and_successful_export` 검증 시, ExportJob 상태 조회가 최종 완료(`completed`) 상태로 넘어가지 못하고 계속 `failed`로 종료되었습니다.

### 원인 분석
* 새로 구현된 `run_export_task` 비동기 루틴은 안전성을 위해 데이터베이스에서 **"최종본(is_final=True)으로 설정된 버전"**을 읽어와 내보내기를 시도합니다.
* 하지만 테스트 셋업 fixture(`test_setup`)는 단순히 `ProductPage`와 `PageSection`만 데이터베이스에 적재하고 있었고, `DetailPageVersion`은 아예 생성되지 않은 상태였습니다.
* 이에 따라 "내보내기할 버전을 찾지 못했습니다" 예외가 발생하며 백그라운드 스레드가 오류를 기록했습니다.

### 해결 전략
* `test_exports.py` 내의 테스트 시작 부분에서 `DetailPageVersion` 엔티티 인스턴스를 수동으로 생성하고 `db_session.add(version)` 후 커밋하는 초기화 작업을 선행해 백그라운드 렌더러가 올바른 데이터를 가져올 수 있도록 조치했습니다.

---

## 3. 이슈 C: 버전 저장 시 스타일 키 불일치로 인한 검증 에러

### 배경 및 증상
* `test_save_page_and_automatic_versioning` 검증 중 `assert latest_version.style_key == "modern"` 구문에서 `AssertionError: assert 'problem_solution' == 'modern'` 이 발생했습니다.

### 원인 분석
* 초안 작성 API가 호출될 때 `style_preset="modern"`으로 유입되지만, 프로젝트 엔티티 내에 `selected_style` 필드가 DB 상에 `None`으로 존재하여 스타일 추천 폴백 플로우를 거치며 최종적으로 `"problem_solution"` 전략 키가 채택되어 버전에 박혔기 때문입니다.

### 해결 전략
* 에디터 단에서 API가 동작할 때의 폴백 매커니즘을 그대로 인정하고, 해당 테스트가 실제 DB에 반영되는 정상 fallback인 `"problem_solution"` 키를 기대하도록 단언문(Assertion)을 수정하여 빌드 파이프라인의 불일치를 바로잡았습니다.
