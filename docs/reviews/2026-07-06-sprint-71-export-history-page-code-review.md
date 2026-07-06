# Sprint 71 코드리뷰: 출력 이력 페이지 연결

> **리뷰 일자:** 2026-07-06
> **기획 문서:** `docs/superpowers/plans/2026-07-06-sellform-sprint-71-export-history-page.md`

---

## 1. 구현 요약

### Backend

| 구분 | 파일 | 설명 | 상태 |
|------|------|------|------|
| 생성 | `backend/src/schemas/export_history.py` | `ExportHistoryItem`, `ExportHistoryResponse` Pydantic schema | ✅ |
| 수정 | `backend/src/api/exports.py` | `GET /api/v1/page/exports` 워크스페이스 단위 export list endpoint + `_to_export_history_item()` 변환 함수 | ✅ |
| 생성 | `backend/tests/test_export_history_api.py` | list/empty/completed download_url 검증 3개 테스트 | ✅ |

### Frontend

| 구분 | 파일 | 설명 | 상태 |
|------|------|------|------|
| 생성 | `frontend/src/lib/exportHistory.ts` | API 타입 정의 및 fetch 함수 | ✅ |
| 생성 | `frontend/src/components/ExportHistoryTable.tsx` | 출력 이력 테이블 (완료/실패/대기 상태별 UI) | ✅ |
| 생성 | `frontend/src/app/workspace/exports/page.tsx` | 출력 이력 페이지 (로딩/에러/빈 상태 처리) | ✅ |
| 수정 | `frontend/src/app/workspace/layout.tsx` | 상단바 + 사이드바 "출력 이력" alert 3곳 → `Link`로 변경 | ✅ |
| 생성 | `frontend/e2e/export-history.spec.ts` | 메뉴 이동, 목록 표시, 다시 다운로드 버튼 E2E | ✅ |

---

## 2. 아키텍처 검토

### 2.1 API 계층

```
GET /api/v1/page/exports
  → ExportJob + ProductProject JOIN
  → workspace_id 필터 (workspace 격리)
  → 최신순 100개
  → _to_export_history_item() 변환
  → ExportHistoryResponse 반환
```

**의견:** 기존 `ExportJob` 모델과 `ProductProject.name`을 `relationship`으로 참조하여 별도 테이블 없이 출력 이력을 구성했다. `workspace_id` 필터로 격리가 보장된다.

### 2.2 프론트 계층

```
layout.tsx (Link) → /workspace/exports (page)
  → fetchExportHistory() → ExportHistoryTable (client 컴포넌트)
  → 완료: download_url 링크
  → 실패: error_message 표시
  → 대기/진행: "대기 중" 표시
```

**의견:** 페이지 전체가 클라이언트 사이드에서 동작한다. 기존 프로젝트의 mock headers 방식을 재사용했다. 빈 상태, 로딩, 에러, 정상 데이터 등 모든 UI 상태를 커버했다.

### 2.3 레이아웃 변경

기존에는 3군데(상단 네비게이션 바 2개 + 사이드바 1개)에서 `alert()`으로만 동작하던 "출력 이력"이 모두 실제 Link로 변경되었다.

---

## 3. 코드 품질

### 3.1 Backend

- **Schema 분리:** `src/schemas/export_history.py`에 Pydantic model을 별도 파일로 분리하여 재사용성 확보.
- **Workspace 격리:** query에 `ProductProject.workspace_id` 필터 적용하여 다른 workspace 데이터 노출 방지.
- **relationship 활용:** `job.project.name`으로 `ExportJob`에서 `ProductProject` 이름에 접근 (lazy loading).

### 3.2 Frontend

- **타입 정의:** `exportHistory.ts`에 모든 API 응답 타입이 명확히 정의됨.
- **컴포넌트 분리:** 페이지(`page.tsx`)와 테이블(`ExportHistoryTable.tsx`)이 분리되어 재사용 가능.
- **UI 상태 커버:** 로딩 스피너, 에러 배너, 빈 상태 안내, 정상 테이블 모두 구현.
- **다운로드 링크:** 완료된 export만 `download_url`을 `<a>` 링크로 제공, 실패 시 truncate된 에러 메시지 표시.

---

## 4. 테스트 커버리지

| 테스트 | 개수 | 검증 내용 |
|--------|------|-----------|
| `test_export_history_api.py` | 3 | 기록 조회, 빈 워크스페이스, completed download_url |
| `export-history.spec.ts` (E2E) | 1 | alert 미발생, URL 이동, 목록 표시, 상태별 UI |

**의견:** 백엔드는 정상/빈/다운로드 3가지 시나리오를, E2E는 사용자 시나리오(메뉴 클릭 → 페이지 이동 → 데이터 표시)를 검증한다. `running` 상태에 대한 테스트도 추가하면 좋지만 MVP 범위로 충분하다.

---

## 5. 완료 기준 달성

- ✅ `출력 이력` 클릭 시 alert가 뜨지 않음
- ✅ `/workspace/exports`로 이동
- ✅ export 기록이 최신순으로 보임
- ✅ 완료된 PNG/JPG는 다시 다운로드 가능 (`download_url` 링크)
- ✅ 실패한 export는 실패 사유 표시
- ✅ backend 테스트 3개 통과

---

## 6. 개선 제안

### 우선순위 낮음 (향후 스프린트)

1. **running 상태 polling:** 진행 중인 export가 있으면 주기적으로 상태를 갱신하는 로직 추가.
2. **format 아이콘:** PNG/JPG/PDF/HTML 각 포맷에 맞는 시각적 아이콘 추가.
3. **페이지네이션:** export 건수가 많아질 경우 page 단위 로딩.
4. **다운로드 카운트:** 각 export의 다운로드 횟수를 기록하는 기능.

---

## 7. 결론

**검토 결과: 승인 (Approved)**

기획 문서의 모든 요구사항이 충족되었으며, 백엔드 테스트 3개 모두 통과, 기존 테스트에도 영향을 주지 않았다.

- **Backend:** schema + list API + workspace 격리
- **Frontend:** 페이지 + 테이블 컴포넌트 + layout Link 전환
- **Test Coverage:** 단위 + E2E
- **완료 기준 6개** 모두 달성
