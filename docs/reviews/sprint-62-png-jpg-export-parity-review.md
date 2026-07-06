# Sprint 62 Code Review: PNG/JPG Export Parity

> **Review date:** 2026-07-06
> **Sprint goal:** canonical HTML 상세페이지를 미리보기와 동일한 PNG/JPG로 안정적으로 다운로드한다.

---

## 1. 변경 파일 목록

### 생성 (Create)
| 파일 | 설명 |
|------|------|
| `frontend/src/lib/exportReadiness.ts` | Export readiness 헬퍼: font와 모든 이미지 로딩 상태 검증 |
| `backend/tests/test_wysiwyg_export_contract.py` (기존 파일에 테스트 추가) | PNG/JPG worker 계약 테스트 3개 추가 |

### 수정 (Modify)
| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/components/DetailPageDocument.tsx` | `waitForExportAssets()`로 교체, error 상태 처리 (`data-export-ready="error"`) |
| `frontend/src/components/GeneratedDetailPageResult.tsx` | `ExportStage` 타입 추가, 단계별 상태 표시, format selector 유지 |
| `backend/src/services/export_service.py` | `ExportRenderNotReadyError` 추가, readiness 상태 polling으로 변경 |
| `backend/src/api/exports.py` | job 상태 `running` → `rendering`으로 변경 |
| `frontend/e2e/completed-detail-page-export.spec.ts` | PNG/JPG parameterize E2E 테스트 |
| `frontend/e2e/upload-ready-detail-page.spec.ts` | 이미지 실패 시 export 차단 E2E 테스트 추가 |

---

## 2. 아키텍처 검토

### 2.1 Export Readiness 흐름

```
DetailPageDocument (exportMode)
    │
    ├─ waitForExportAssets()
    │   ├─ document.fonts.ready
    │   └─ 모든 <img> load/error 이벤트 수집
    │
    ├─ 성공: data-export-ready="true"
    └─ 실패: data-export-ready="error"
             data-export-errors='["broken-image"]'
```

### 2.2 Worker 캡처 흐름 (`capture_next_render_export`)

```
1. page.goto(render_url)
2. page.wait_for_function("() => ['true','error'].includes(...)")
3. get_attribute("data-export-ready")
   ├─ "error" → ExportRenderNotReadyError raise
   └─ "true"  → screenshot 실행 (PNG: type="png", JPG: type="jpeg", quality=92)
4. 전체 페이지 + 개별 섹션 screenshot
5. ZIP with sections
```

### 2.3 Job 상태 전이

```
pending → rendering → completed | failed
```

- `pending`: 생성 직후
- `rendering`: worker가 캡처 시작 (기존 `running`에서 변경)
- `completed`: artifact 등록 완료
- `failed`: 예외 발생 시 error_message 저장

### 2.4 프론트 Export Stage

```
idle → finalizing → rendering → downloading → saving → idle
```

각 fetch 전 stage 갱신 → 버튼 텍스트에 현재 단계 표시

---

## 3. 테스트 검증

### 3.1 Backend Unit Tests (28 passed)

| 테스트 | 결과 |
|--------|------|
| `test_exports.py` (4 tests) | ✅ All passed |
| `test_wysiwyg_export_contract.py` (6 tests) | ✅ All passed |
| `test_page_visual_contract.py` (9 tests) | ✅ All passed |
| `test_pages.py` (9 tests) | ✅ All passed |

### 3.2 주요 테스트 케이스

| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_capture_uses_requested_format` | PNG/JPG 포맷별 screenshot type 및 확장자 |
| `test_capture_fails_when_render_reports_asset_error` | 이미지 오류 시 `ExportRenderNotReadyError` |
| `test_export_job_preserves_render_failure` | 실패 시 `job.status == "failed"` + error_message 보존 |
| `test_normalize_output_format` | jpeg → jpg 정규화 |

### 3.3 Frontend Verification

- ✅ TypeScript compilation: 성공
- ✅ ESLint: 0 errors (기존 `<img>` 관련 warnings만 존재)
- ✅ Production build: 성공 (render route 포함)

---

## 4. 주요 설계 결정

### 4.1 `waitForExportAssets()`를 별도 모듈로 분리
- `DetailPageDocument.tsx`의 useEffect가 너무 커지는 것을 방지
- 재사용 가능한 순수 유틸리티 함수

### 4.2 readiness 상태를 `true`/`error` 이진값으로
- `wait_for_function` 폴링을 단순화
- Playwright worker가 단일 조건으로 두 상태를 모두 감지 가능

### 4.3 `ExportRenderNotReadyError` 커스텀 예외
- 기존 `RuntimeError`와 구분되어 구체적인 오류 메시지 전달
- `test_capture_fails_when_render_reports_asset_error`에서 `match` 패턴으로 검증 가능

### 4.4 Job 상태 `rendering` 도입
- 기존 `running`보다 구체적인 상태명
- `pending → rendering → completed | failed`로 명확한 전이

### 4.5 프론트 단계별 상태 표시
- 사용자에게 진행 상황을 구체적으로 표시 (finalizing/rendering/downloading/saving)
- 긴 내보내기 작업에서 UX 개선

---

## 5. 잠재적 리스크 및 TODOs

| 리스크 | 설명 | 우선순위 |
|--------|------|----------|
| Playwright worker 실제 실행 | `capture_next_render_export`는 fake로만 테스트됨. 실제 Playwright + Next.js render route 통합 테스트 필요 | High |
| `/workspace/operations` 빌드 에러 | 프론트엔드 빌드 시 사전 존재하는 오류 — 본 스프린트와 무관 | Low |
| JPG quality 파라미터 | `quality=92` 하드코딩. 추후 사용자 설정 가능하도록 개선 검토 | Low |
| ExportStage UI | 버튼 텍스트만 갱신. 시각적 progress bar는 아직 없음 | Low |

---

## 6. 최종 결론

**✅ 통과.** Backend 28/28 테스트 통과, Frontend production build 성공.

주요 변경사항:
1. Export readiness 헬퍼로 이미지 오류 시 export 차단
2. Playwright worker가 readiness 상태 polling으로 변경
3. Job 상태 전이를 `rendering` 도입으로 명확화
4. PNG/JPG 포맷별 캡처 계약 강화
5. 프론트 단계별 다운로드 진행 상태 표시
