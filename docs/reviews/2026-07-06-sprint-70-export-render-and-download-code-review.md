# Sprint 70 코드리뷰: Browser Download & Clean Export Render

> **리뷰 일자:** 2026-07-06
> **기획 문서:** `docs/superpowers/plans/2026-07-06-sellform-sprint-70-browser-download-and-clean-export-render.md`

---

## 1. 구현 요약

### Backend

| 구분 | 파일 | 설명 | 상태 |
|------|------|------|------|
| 수정 | `backend/src/services/export_service.py` | `build_export_render_path()` 함수 분리, 기본 경로 `/export-render/projects/{project_id}`로 변경 | ✅ |
| 수정 | `backend/src/api/exports.py` | download endpoint에 `Content-Disposition: attachment` 추가 | ✅ |
| 수정 | `backend/tests/test_export_service.py` | `test_default_export_render_path_is_outside_workspace` 추가 (기존 7→8개) | ✅ |
| 생성 | `backend/tests/test_export_api.py` | download header 형식 검증 테스트 | ✅ |

### Frontend

| 구분 | 파일 | 설명 | 상태 |
|------|------|------|------|
| 생성 | `frontend/src/app/export-render/projects/[id]/page.tsx` | workspace layout을 타지 않는 export 전용 렌더 라우트 | ✅ |
| 수정 | `frontend/src/app/workspace/projects/[id]/export-render/page.tsx` | 기존 경로 → `/export-render/projects/{id}`로 redirect | ✅ |
| 수정 | `frontend/src/components/GeneratedDetailPageResult.tsx` | `showSaveFilePicker()` 제거 → `<a download>` 통일, 버튼 문구 "다운로드"로 변경 | ✅ |
| 수정 | `frontend/e2e/completed-detail-page-export.spec.ts` | download event 기반 E2E로 변경 | ✅ |
| 생성 | `frontend/e2e/export-render-clean-page.spec.ts` | export render 화면 workspace header 미포함 검증 | ✅ |

---

## 2. 아키텍처 검토

### 2.1 Export Render 라우트 분리

```
Before:  /workspace/projects/[id]/export-render  (workspace layout 적용)
After:   /export-render/projects/[id]              (독립 레이아웃, header 없음)
```

**의견:** 기존에는 `/workspace` App Router segment 아래 있어 layout.tsx의 헤더/네비게이션이 함께 캡처될 위험이 있었다. 새로운 `/export-render` 라우트는 workspace layout과 완전히 분리되어 screenshot에 앱 chrome이 포함되지 않는다.

### 2.2 다운로드 방식 변경

```
Before:  showSaveFilePicker() → createWritable() → write blob
After:   blob URL → <a download> 링크 생성 → click() → revoke
```

**의견:** `showSaveFilePicker`는 File System Access API로 Chrome 다운로드 기록에 남지 않는다. `<a download>` 방식은 브라우저 내장 다운로드 매니저를 사용하므로 다운로드 기록에 파일이 남고, 사용자가 예상하는 "다운로드" 경험과 일치한다.

### 2.3 Content-Disposition: attachment

`FileResponse`에 `Content-Disposition: attachment` 헤더를 명시적으로 추가하여 브라우저가 파일을 표시하지 않고 다운로드하도록 지정했다.

---

## 3. 코드 품질

### 3.1 Backend

- **함수 분리:** `build_export_render_path()`를 별도 함수로 분리하여 단위 테스트 가능하게 했다.
- **환경변수 기반 설정:** `SELLFORM_EXPORT_RENDER_PATH` 환경변수로 기본값 오버라이드 가능.
- **하위 호환성:** 기존 `test_export_service.py` 테스트 7개 모두 영향 없음.

### 3.2 Frontend

- **Next.js App Router:** 새 라우트에서 `params`와 `searchParams`를 `Promise`로 받는 Next.js 15 패턴 사용.
- **Suspense 경계:** `DetailPageRenderClient`가 클라이언트 컴포넌트이므로 `Suspense`로 fallback 처리.
- **redirect:** 기존 경로는 `next/navigation`의 `redirect()`로 새 경로로 안내.
- **메모리 누수 방지:** blob URL 생성 후 `setTimeout`으로 1초 후 `revokeObjectURL`.

---

## 4. 테스트 커버리지

| 테스트 | 개수 | 검증 내용 |
|--------|------|-----------|
| `test_export_service.py` | 8 (기존 7 + 신규 1) | render path가 `/workspace/` 밖인지 확인 |
| `test_export_api.py` | 1 | download header에 `Content-Disposition: attachment` 포함 |
| `completed-detail-page-export.spec.ts` (E2E) | 1 | PNG/JPG download event 발생, filename 확장자 검증 |
| `export-render-clean-page.spec.ts` (E2E) | 1 | export render에 workspace header 미포함 |

**의견:** 백엔드는 경로 변경과 header 검증, E2E는 다운로드 동작과 chrome 미포함을 각각 검증한다. 실제 브라우저 download와 workspace layout 격리를 모두 확인 가능하다.

---

## 5. 완료 기준 달성

- ✅ PNG/JPG 버튼 클릭 시 Playwright `download` event 발생
- ✅ Chrome 다운로드 기록에 남는 `<a download>` 방식
- ✅ 저장 파일명에 상품명과 확장자 포함
- ✅ 저장 이미지에 workspace header 미포함 (별도 라우트)
- ✅ export render 라우트가 `/workspace` layout을 타지 않음
- ✅ backend export 기본 경로 `/export-render/projects/{project_id}`

---

## 6. 개선 제안

### 우선순위 낮음 (향후 스프린트)

1. **다운로드 polling 중단 조건 개선:** 현재 120회(60초) polling 후 타임아웃. 백엔드 완료 시간 데이터를 기반으로 동적 timeout 계산 가능.
2. **다운로드 완료 안내:** 다운로드 완료 후 토스트 메시지로 "다운로드 완료" 표시.
3. **중복 다운로드 방지:** 같은 포맷 연속 다운로드 시 이전 blob URL 정리.
4. **오래된 export-render 라우트 제거:** `/workspace/projects/[id]/export-render`가 충분히 안정화되면 redirect 대신 404 처리.

---

## 7. 결론

**검토 결과: 승인 (Approved)**

기획 문서의 모든 요구사항이 충족되었으며, 백엔드 테스트 9개 모두 통과, 기존 테스트에도 영향을 주지 않았다.

- **핵심 변경:** export render 라우트 분리 + `<a download>` 방식 전환
- **Backend:** `build_export_render_path()` + `Content-Disposition: attachment`
- **Frontend:** 새 라우트 + `showSaveFilePicker` 제거 + 버튼 문구 정리
- **Test Coverage:** 단위/통합/E2E 3계층 검증
