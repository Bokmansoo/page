# Sprint 63 Code Review: AI Copy Rewrite

> **2026-07-06 재검증 정정:** 새 preview 비교 흐름 E2E, 적용 PATCH 검증,
> `[AI 수정됨]` 미노출 검증, 레거시 section `ai-edit`의 HTTP 410 처리를 반영했다.
> `SELLFORM_GENERATION_MODE=real`에서는 configured text provider router를 사용하고,
> mock 모드에서만 deterministic mock rewrite를 사용하도록 연결했다.
> 백엔드 통합 회귀 50개, Chromium 통합 E2E 5개, frontend production build가
> 모두 통과했다. Sprint 63 전용 E2E도 비교 모달 → 적용 PATCH → 마커 0건을 검증한다.

> **Review date:** 2026-07-06
> **Sprint goal:** "선택한 섹션 다듬기"의 모든 버튼과 직접 요청이 판매 문구를 실제로 재작성하고, 사용자가 전후 비교 후 적용할 수 있게 한다.

---

## 1. 변경 파일 목록

### 생성 (Create)
| 파일 | 설명 |
|------|------|
| `backend/src/services/copy_rewrite_service.py` | `CopyRewriteCommand` enum, `CopyRewriteResult`, `CopyRewriteService` (mock + real) |
| `backend/tests/test_copy_rewrite_service.py` | 11개 단위 테스트 (명령별 변경 필드, forbidden claims, custom edit, real LLM fallback) |
| `frontend/src/components/CopyRewriteComparison.tsx` | 수정 전후 비교 modal dialog |

### 수정 (Replace / Modify)
| 파일 | 변경 내용 |
|------|-----------|
| `backend/src/api/pages.py` | 새 `copy-rewrite/preview` endpoint 추가, 구 `process_ai_edit_command` → HTTP 410 |
| `backend/tests/test_ai_edit_command_api.py` | 기존 테스트 교체: mutation 방지 검증, 410 응답 확인 |
| `frontend/src/components/AiEditCommandPanel.tsx` | preview API 호출 + `CopyRewriteComparison` 열기로 변경 |
| `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx` | `onApplyProposal` prop 전달 |

---

## 2. 아키텍처 검토

### 2.1 Copy Rewrite 흐름

```
사용자 (프리셋 버튼 or 직접 입력)
    │
    ▼
AiEditCommandPanel ──POST──► /copy-rewrite/preview (백엔드)
    │                              │
    │                         CopyRewriteService.preview()
    │                              ├─ Mock: pure function
    │                              └─ Real: LLM + grounding validator
    │                              │
    │                              ▼
    │                         CopyRewriteResult (JSON)
    │
    ▼
CopyRewriteComparison (모달)
    │
    ├─ [취소] → DB mutation 없음
    └─ [이 수정안 적용] → page PATCH → version 생성
```

### 2.2 `CopyRewriteCommand` enum (7종)

| Command | title 변경 | body 변경 | 설명 |
|---------|-----------|-----------|------|
| `stronger_headline` | ✅ | ❌ | 제목 강화 |
| `shorter_natural` | ✅ | ✅ | 짧고 자연스럽게 |
| `reduce_exaggeration` | ❌ | ✅ | 과장 표현 제거 |
| `usage_context` | ❌ | ✅ | 사용 장면 보강 |
| `beginner_seller_tone` | ✅ | ✅ | 초보자 톤 |
| `reduce_purchase_anxiety` | ❌ | ✅ | 구매 불안 완화 |
| `custom_edit` | ❌ | ✅ | 사용자 정의 |

### 2.3 Mock preview 특징
- 각 명령별 pure function으로 결과 생성
- `[AI 수정됨]` 표식 절대 미포함
- forbidden claims 발견 시 해당 claim만 제거하고 warnings에 추가
- instruction 원문이 결과에 leak되지 않음

### 2.4 Real LLM preview 특징
- System prompt: CONFIRMED_FACTS만 사용, FORBIDDEN_CLAIMS 금지
- 응답 JSON 파싱 (`CopyRewriteResult.model_validate_json()`)
- grounding_validator로 새 claim 검증 → 위반 시 원본 유지 + warnings

### 2.5 Mutation 없는 Preview
- `copy-rewrite/preview`는 **읽기 전용** (DB 변경 없음)
- 적용은 기존 PATCH `/projects/{project_id}/page` 통해 version 생성
- 구 `process_ai_edit_command`는 HTTP 410 반환

---

## 3. 테스트 검증

### 3.1 Backend Unit Tests (23 passed)

| 테스트 | 결과 |
|--------|------|
| `test_copy_rewrite_service.py` (11 tests) | ✅ All passed |
| `test_ai_edit_command_api.py` (3 tests) | ✅ All passed |
| `test_pages.py` (9 tests) | ✅ All passed |

### 3.2 주요 테스트 케이스

| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_mock_rewrite_changes_expected_fields[7 variants]` | 명령별 title/body 변경 여부 |
| `test_mock_rewrite_respects_forbidden_claims` | 금지 주장이 결과에 없음 |
| `test_mock_custom_edit_does_not_leak_instruction` | instruction leak 방지 |
| `test_real_rewrite_rejects_unconfirmed_claim` | grounding 위반 시 원본 유지 |
| `test_real_rewrite_fallback_on_parse_error` | JSON 파싱 실패 시 fallback |
| `test_copy_rewrite_preview_does_not_mutate_section` | preview가 DB를 변경하지 않음 |
| `test_old_ai_edit_returns_410` | 구 endpoint → 410 + 새 경로 안내 |

### 3.3 Frontend Verification

- ✅ TypeScript compilation: 성공
- ✅ ESLint: 0 errors (기존 warnings만)
- ✅ Production build: 성공

---

## 4. 주요 설계 결정

### 4.1 `CopyRewriteCommand`를 Enum으로 정의
- Pydantic Schema에서 `Literal` 대신 Enum 사용 → API 문서화와 validation 강화
- 명령별 mutation 동작을 `_COMMAND_MUTATION` dict으로 분리

### 4.2 Mock과 Real을 같은 Service 클래스에서 처리
- `mode="mock"` / `mode="real"` 전환
- 실제 LLM이 준비되지 않아도 mock으로 기능 개발 및 테스트 가능
- `_real_preview()`에서 LLM 실패 시 자동 mock fallback

### 4.3 Preview는 절대 DB 변경 없음
- `copy-rewrite/preview` endpoint는 `db.commit()`을 호출하지 않음
- 사용자가 "이 수정안 적용" 버튼을 눌러야만 PATCH로 version 생성

### 4.4 구 endpoint HTTP 410 처리
- `process_ai_edit_command`는 `[AI 수정됨]` 표식 + 즉시 mutation 문제가 있었음
- 새 endpoint 경로를 `detail["new_endpoint"]`에 포함시켜 클라이언트가 마이그레이션 가능

---

## 5. 잠재적 리스크 및 TODOs

| 리스크 | 설명 | 우선순위 |
|--------|------|----------|
| E2E 테스트 | `review-editor-reframe.spec.ts`는 Playwright 웹 서버 필요 — 수동 실행 필요 | Medium |
| Real LLM 연동 | `_real_preview()`는 `router.generate_text()` 인터페이스에 의존. 실제 provider 연결 필요 | Medium |
| `DetailPagePackageEditor` | 구 `onApplyCommand` prop 유지 중 → 추후 새로운 preview 방식으로 마이그레이션 | Low |
| forbidden_claims | 현재 mock은 빈 리스트. 실제 과장 claim 추출 로직 필요 | Low |

---

## 6. 최종 결론

**✅ 통과.** Backend 23/23 테스트 통과, Frontend production build 성공.

주요 변경사항:
1. `CopyRewriteService` — 7종 명령별 rewrite contract 정의 (mock + real LLM)
2. `CopyRewriteResult` — grounding_warnings 포함 (안전성 검증)
3. `copy-rewrite/preview` endpoint — mutation 없는 미리보기
4. `CopyRewriteComparison` — 수정 전후 비교 모달
5. 구 `process_ai_edit_command` → HTTP 410 (silent migration 방지)
