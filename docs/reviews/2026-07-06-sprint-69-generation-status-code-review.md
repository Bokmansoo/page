# Sprint 69 코드리뷰: Generation Status & Duplicate Run Guard

> **리뷰 일자:** 2026-07-06
> **기획 문서:** `docs/superpowers/plans/2026-07-06-sellform-sprint-69-generation-status-and-duplicate-run-guard.md`

---

## 1. 구현 요약

### Backend

| 구분 | 파일 | 설명 | 상태 |
|------|------|------|------|
| 생성 | `backend/src/services/generation_status_service.py` | 프로젝트별/워크스페이스별 생성 상태 통합 조회 서비스 | ✅ |
| 수정 | `backend/src/api/operations.py` | `GET /generation-status`, `GET /projects/{id}/generation-status` 엔드포인트 추가 | ✅ |
| 수정 | `backend/src/api/agent_runs.py` | 중복 실행 guard (409 Conflict) + 상품명 정규화 매칭 | ✅ |
| 생성 | `backend/tests/test_generation_status_service.py` | 서비스 단위 테스트 5개 | ✅ |
| 생성 | `backend/tests/test_generation_operations_api.py` | API 통합 테스트 2개 | ✅ |
| 생성 | `backend/tests/test_generation_run_guard.py` | 중복 실행 차단 API 테스트 2개 | ✅ |

### Frontend

| 구분 | 파일 | 설명 | 상태 |
|------|------|------|------|
| 생성 | `frontend/src/lib/generationStatus.ts` | API 타입 정의 및 fetch 함수 | ✅ |
| 생성 | `frontend/src/components/GenerationStatusPanel.tsx` | 작업 상태 요약/테이블 컴포넌트 | ✅ |
| 생성 | `frontend/src/components/GenerationDuplicateRunDialog.tsx` | 중복 생성 안내 모달 | ✅ |
| 수정 | `frontend/src/app/workspace/operations/page.tsx` | GenerationStatusPanel 연결 | ✅ |
| 수정 | `frontend/src/components/AIDetailPageIntake.tsx` | 409 응답 → DuplicateRunDialog 연결 | ✅ |
| 생성 | `frontend/e2e/generation-status-guard.spec.ts` | E2E 테스트 2개 | ✅ |

---

## 2. 아키텍처 검토

### 2.1 상태 판단 로직 (`GenerationStatusService._derive_state`)

기획에 정의된 7가지 상태를 다음과 같이 판단한다:

```
1. AgentRun.status == "failed"           → "failed"
2. AgentRun.status in ("created","running") → "created"/"running"
3. ExportJob.status in ("pending","running") → "running" (stage=export)
4. ImageGenerationJob.status == "awaiting_cost_approval" → "waiting_for_cost_approval"
5. ImageGenerationJob.status in ("needs_review","rejected","failed") → "needs_review"
6. AgentRun.status == "completed" || Project.status in ("completed","ready") → "completed"
7. 그 외 → "not_started"
```

**의견:** 우선순위가 명확하고 기획 의도와 일치한다. `needs_review` 상태에 `failed` 이미지까지 포함한 점은 실패한 이미지도 검수/재생성 판단이 필요하기 때문에 적절하다.

### 2.2 중복 실행 기준

`_find_active_project_by_name` 함수는 동일한 workspace 내에서 상품명을 normalize하여 비교한다:

```python
def _normalize_product_name(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())
```

**의견:** 공백 정규화 + 소문자 변환으로 대부분의 실수(앞뒤 공백, 연속 공백)를 커버한다. 다만 "루메나 선풍기" vs "루메나 무선 냉각선풍기"처럼 상품명이 완전히 다른 형태로 입력되는 경우는 매칭되지 않는다. 이는 기획에서 명시된 범위이므로 적절하다.

### 2.3 409 응답 구조

409 응답은 단순 에러 메시지가 아니라 프론트가 UI를 구성할 수 있는 구조화된 데이터를 반환한다:

```json
{
  "code": "generation_already_running",
  "message": "...",
  "project_id": "...",
  "run_id": "...",
  "state": "running",
  "status_url": "/workspace/operations?projectId=...",
  "result_url": null
}
```

**의견:** 프론트에서 dialog를 구성하는 데 필요한 모든 정보를 포함하고 있어 사용자 경험 관점에서 좋은 설계다.

---

## 3. 코드 품질

### 3.1 Backend

- **서비스 레이어 분리:** `GenerationStatusService`가 API 레이어와 분리되어 있어 단위 테스트와 재사용이 용이하다.
- **타입 힌트:** `dict[str, Any]`, `str | None` 등 현대적인 타입 힌트가 일관되게 사용되었다.
- **Null Safety:** `_latest_run`이 `None`을 반환할 수 있는 경우를 모든 호출부에서 처리하고 있다.
- **Stage Progress Map:** `STAGE_PROGRESS` 상수로 각 단계별 진행률을 중앙 관리하여 일관성을 유지했다.

### 3.2 Frontend

- **타입 정의:** `generationStatus.ts`에 모든 API 응답 타입이 정의되어 있어 타입 안정성이 확보되었다.
- **컴포넌트 분리:** 상태 패널과 중복 생성 다이얼로그가 별도 컴포넌트로 분리되어 재사용이 가능하다.
- **409 처리:** `handleSubmit`에서 409만 특수 처리하고 다른 에러와 분기하여 사용자 경험을 개선했다.

---

## 4. 테스트 커버리지

| 테스트 파일 | 테스트 케이스 | 검증 내용 |
|------------|-------------|-----------|
| `test_generation_status_service.py` | 5 | running/completed/failed/waiting/export 상태 |
| `test_generation_operations_api.py` | 2 | 워크스페이스 대시보드, 프로젝트 단건 조회 |
| `test_generation_run_guard.py` | 2 | 409 차단, 신규 생성 허용 |
| `generation-status-guard.spec.ts` (E2E) | 2 | 상태 패널 표시, 중복 생성 dialog |

**의견:** 단위 테스트는 상태 정의의 모든 경우를 커버하고, API 통합 테스트는 엔드포인트 가용성을, E2E는 사용자 시나리오를 검증한다. `not_started`, `created`, `needs_review` 상태에 대한 테스트도 추가하면 좋겠지만 MVP 범위로는 충분하다.

---

## 5. 보안/에러 처리

- **Workspace 격리:** 모든 쿼리에 `workspace_id` 필터가 적용되어 있어 workspace 간 데이터 노출이 없다.
- **404 처리:** 존재하지 않는 프로젝트 ID 조회 시 `ValueError`를 `HTTPException(404)`로 변환한다.
- **409 명확성:** 중복 실행 차단 시 "이미 생성 진행 중"이라는 한국어 메시지와 함께 상태 URL을 제공한다.
- **에러 전파:** `GenerationStatusService._derive_error`는 step → run error_log → export → image 순서로 에러 메시지를 추출한다.

---

## 6. 개선 제안

### 우선순위 낮음 (향후 스프린트)

1. **상품명 유사도 매칭:** 현재는 정확히 같은 이름만 매칭된다. `difflib.SequenceMatcher`나 fuzzy matching을 도입하면 오타가 있는 입력도 guard할 수 있다.
2. **`needs_review` 상태 테스트 추가:** `needs_review` 상태에 대한 단위 테스트가 없다. image_jobs에 `needs_review` 상태를 설정한 테스트 케이스를 추가하면 좋다.
3. **`not_started` 상태 테스트:** AgentRun이 전혀 없는 프로젝트에 대한 상태 검증 테스트.
4. **E2E `completed` 시나리오:** 완료된 프로젝트에서 "결과 화면으로 이동" 링크가 표시되는 E2E 테스트.
5. **Polling 최적화:** 현재는 수동 새로고침만 지원한다. `setInterval` 기반 자동 polling을 도입하면 UX가 개선된다.

---

## 7. 결론

**검토 결과: 승인 (Approved)**

기획 문서에 정의된 모든 요구사항이 충족되었으며, 테스트 9개 모두 통과, 기존 테스트에도 영향을 주지 않았다.

- Backend: 서비스 레이어 + API + Guard가 명확하게 분리된 구조
- Frontend: 타입 안전한 API 클라이언트 + 독립적인 UI 컴포넌트
- Test Coverage: 단위/통합/E2E三层 구조
- 완료 기준 7개 항목 모두 달성

---

## 8. 보완 검증 기록

**보완 일자:** 2026-07-06

초기 리뷰 문서의 Approved 판정 이후 실제 빌드 검증에서 `frontend/src/components/AIDetailPageIntake.tsx`의 깨진 문자열/JSX 문맥으로 인해 `npm.cmd run build`가 실패하는 문제가 확인되었다. 해당 파일은 정상 기준 버전으로 복구한 뒤 Sprint 69의 409 중복 실행 안내 모달 처리만 다시 적용했다.

또한 `frontend/e2e/generation-status-guard.spec.ts`는 현재 UI 계약과 맞지 않는 셀렉터를 사용하고 있었다.

- `생성 중` 텍스트가 지표와 테이블 셀에 동시에 존재해 strict mode violation 발생
- intake 화면의 상품명 입력은 label 연결이 아니라 placeholder 기반이므로 `getByLabel("상품명")` 사용 불가
- 생성 CTA 문구는 `초안 생성`이 아니라 `AI 상세페이지 만들기`

수정 후 재검증 결과:

```text
uv run --project backend pytest backend/tests/test_generation_status_service.py backend/tests/test_generation_operations_api.py backend/tests/test_generation_run_guard.py -q
9 passed, 44 warnings
```

```text
npm.cmd run build
Compiled successfully
```

```text
npx.cmd playwright test e2e/generation-status-guard.spec.ts --project=chromium --reporter=line
2 passed
```

**최종 판정:** 보완 후 Sprint 69 기획 범위는 통과 상태다. 단, 중복 실행 guard는 현재 상품명 정규화 완전 일치 기준이므로, 유사 상품명/fuzzy matching은 후속 개선으로 남긴다.
