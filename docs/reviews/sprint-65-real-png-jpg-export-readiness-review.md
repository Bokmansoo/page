# Sprint 65 Code Review: Real PNG/JPG Export Readiness

> **Review date:** 2026-07-06
> **Sprint goal:** 실제 프로젝트에서 PNG/JPG 버튼을 누르면 AI가 만든 상세페이지 모습 그대로 파일이 저장되게 만든다.

---

## 1. 변경 파일 목록

### 생성 (Create)
| 파일 | 설명 |
|------|------|
| `frontend/src/components/ExportReadinessWarning.tsx` | Blocker code → 한글 매핑 + 체크리스트 UI |

### 수정 (Modify)
| 파일 | 변경 내용 |
|------|-----------|
| `backend/src/services/visual_contract_backfill.py` | `_is_payload_complete()` 추가, incomplete payload도 backfill |
| `backend/src/services/page_asset_policy.py` | mock mode에서 `real-generated`/`ai-generated` 등 eligible |
| `backend/tests/test_visual_contract_backfill.py` | 4개 신규 테스트 (incomplete cards/table_rows, overwrite 방지) |
| `frontend/src/components/GeneratedDetailPageResult.tsx` | `ExportReadinessWarning` 연동, blocker 파싱, stale blocker 초기화, JSON 오류 노출 방지 |
| `frontend/e2e/upload-ready-golden-path.spec.ts` | PNG/JPG 저장 happy path + readiness blocker 메시지 표시 E2E |
| `docs/superpowers/plans/2026-07-06-sellform-sprint-65-real-png-jpg-export-readiness.md` | 한글 기획 문서 UTF-8 정상 확인, 체크박스 상태 갱신 |

---

## 2. 변경 상세

### 2.1 Backfill: incomplete payload 보강

기존: `visual_kind`가 이미 있으면 `continue` (아예 skip)

변경: `_is_payload_complete()`로 `validate_visual()`을 호출해 payload completeness 검증.
`comparison_cards`에 `cards`가 없거나 `spec_table`에 `table_rows`가 없으면 재생성.

```python
def _is_payload_complete(section: PageSection) -> bool:
    from src.services.page_visual_contract import validate_visual
    visual = {
        "visual_kind": section.visual_kind,
        "visual_payload": section.visual_payload or {},
        "image_asset_id": section.image_asset_id,
    }
    return len(validate_visual(visual)) == 0
```

### 2.2 AI 생성 이미지 eligibility

기존: `approved` 상태의 `ImageGenerationJobRecord.output_asset_id`만 허용

변경: mock/dev mode에서는 `mock-generated`, `real-generated`, `ai-generated`, `url-extracted` 타입도 eligible

```python
MOCK_MODE_ELIGIBLE_TYPES = {"mock-generated", "real-generated", "ai-generated", "url-extracted"}
# ...
or (settings.SELLFORM_GENERATION_MODE == "mock" and asset.source_type in MOCK_MODE_ELIGIBLE_TYPES)
```

### 2.3 Export blocker 프론트 표시

`ExportReadinessWarning` 컴포넌트가 `detail.blockers`를 파싱해 한글 메시지로 표시:

| Blocker code | 한글 메시지 |
|-------------|------------|
| `visual_image_asset_required` | 이미지 에셋이 필요한 섹션이 있습니다 |
| `visual_html_cards_required` | 카드형 섹션에 내용이 비어 있습니다 |
| `visual_spec_rows_required` | 스펙 테이블에 항목이 비어 있습니다 |
| `asset_not_eligible` | 일부 이미지가 내보내기 조건을 충족하지 않습니다 |
| `internal_edit_marker` | AI 수정 표식이 남아 있는 섹션이 있습니다 |

추가 보완:

- 새 다운로드 시도 시 이전 `exportBlockers`를 초기화한다.
- blocker 응답이 왔을 때 내부 JSON 문자열을 `exportError`로 노출하지 않고 짧은 오류 문구만 표시한다.
- readiness 실패 E2E fixture는 프론트 validation은 통과하지만 backend readiness에서 막히는 `asset_not_eligible` 상태로 구성했다.

---

## 3. 테스트 검증

### 3.1 Backend targeted verification

| 테스트 | 결과 |
|--------|------|
| `test_visual_contract_backfill.py` (9 tests) | ✅ |
| `test_page_readiness_service.py` (5 tests) | ✅ |
| `test_wysiwyg_export_contract.py` (6 tests) | ✅ |
| `test_exports.py` (Sprint 62 export regression) | ✅ |

실행 명령:

```bash
uv run --project backend pytest backend/tests/test_visual_contract_backfill.py backend/tests/test_page_readiness_service.py backend/tests/test_wysiwyg_export_contract.py backend/tests/test_exports.py -q
```

결과:

```text
23 passed
```

**신규 테스트 (4):**
| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_backfill_fills_incomplete_comparison_cards` | cards 누락 시 재생성 |
| `test_backfill_fills_incomplete_benefit_cards` | cards 누락 시 재생성 |
| `test_backfill_fills_incomplete_spec_table` | table_rows 누락 시 재생성 |
| `test_backfill_does_not_overwrite_complete_payload` | 완료된 payload는 덮어쓰지 않음 |

### 3.2 Frontend Verification

- ✅ Production build: 성공
- ✅ E2E: PNG/JPG 저장 happy path 통과
- ✅ E2E: readiness blocker 메시지 표시 통과

실행 명령:

```bash
npm.cmd run build
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts e2e/upload-ready-golden-path.spec.ts --project=chromium --reporter=line
```

결과:

```text
Production build: 성공
3 passed
```

빌드 경고:

- `page-editor/page.tsx`의 React Hook dependency warning
- 일부 `<img>` 사용에 대한 Next.js 권장 경고

위 경고는 Sprint 65 export readiness 통과를 막지는 않지만, 후속 hardening에서 정리하면 좋다.

---

## 4. 최종 결론

**✅ 자동화 기준 통과.** Backend targeted tests, Frontend production build, PNG/JPG export E2E, readiness blocker E2E가 통과했다.

주요 변경사항:
1. `visual_contract_backfill._is_payload_complete()` — incomplete payload도 보강
2. `page_asset_policy` — mock mode에서 AI 생성 이미지 eligible
3. `ExportReadinessWarning` — blocker code → 한글 체크리스트
4. export 실패 시 `detail.blockers` 파싱 + 체크리스트 표시
5. stale blocker 초기화 + JSON 오류 노출 방지

남은 확인:

- 실제 프로젝트 `fffe0d0f-64e0-4085-bcc4-239af755eaaf`에서 PNG/JPG 파일을 직접 저장하고 열어보는 수동 검증은 아직 별도로 수행해야 한다.
