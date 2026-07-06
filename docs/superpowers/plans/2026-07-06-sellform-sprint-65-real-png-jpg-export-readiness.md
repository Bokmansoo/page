# Sprint 65 실제 PNG/JPG 다운로드 통과 기획

> **작업자 참고:** 이 문서는 Sprint 65 구현 기준 문서입니다. 체크박스는 구현/검증 진행 상태를 추적하기 위한 항목입니다.

**목표:** 실제 프로젝트에서 PNG/JPG 버튼을 누르면 AI가 만든 상세페이지 모습 그대로 파일이 저장되게 만든다.

**아키텍처:** export 전에 `page_readiness_service`가 정확히 readiness를 판단하고, 불완전한 visual payload는 backfill로 보강한다. AI 생성 이미지는 `ImageGenerationJobRecord` 승인 기록 또는 dev/mock 예외 정책을 통해 export 가능 상태로 만든다. 프론트엔드는 blocker를 사람이 이해할 수 있는 체크리스트로 보여준다.

**기술 스택:** FastAPI, SQLAlchemy, PostgreSQL, Next.js, Playwright export, pytest, Playwright E2E

---

## 1. 현재 문제

실제 프로젝트 `fffe0d0f-64e0-4085-bcc4-239af755eaaf`의 readiness가 false다.

blocker:

- `asset_not_eligible` 2개
- `visual_html_cards_required` 2개
- `visual_spec_rows_required` 1개

따라서 다운로드 버튼은 눌리더라도 backend export API가 정상적으로 진행될 수 없다.

---

## 2. 구현 범위

백엔드 수정 대상:

- `backend/src/services/visual_contract_backfill.py`
- `backend/src/services/page_readiness_service.py`
- `backend/src/services/page_asset_policy.py`
- AI 이미지 생성 asset을 만드는 서비스
- `backend/src/api/exports.py`

프론트엔드 수정 대상:

- `frontend/src/components/GeneratedDetailPageResult.tsx`
- 필요 시 `frontend/src/components/ExportReadinessWarning.tsx`

테스트 대상:

- `backend/tests/test_visual_contract_backfill.py`
- `backend/tests/test_page_readiness_service.py`
- `backend/tests/test_wysiwyg_export_contract.py`
- `frontend/e2e/completed-detail-page-export.spec.ts`
- `frontend/e2e/upload-ready-golden-path.spec.ts`

---

## 3. 작업 계획

### Task 1 — incomplete visual payload backfill 테스트 추가

- [x] `backend/tests/test_visual_contract_backfill.py`에 `comparison_cards` payload가 불완전할 때 `cards`가 생성되는 테스트를 추가한다.
- [x] `benefit_cards` payload가 불완전할 때 `cards`가 생성되는 테스트를 추가한다.
- [x] `spec_table` payload가 불완전할 때 `table_rows`가 생성되는 테스트를 추가한다.

실행:

```bash
uv run --project backend pytest backend/tests/test_visual_contract_backfill.py -q
```

기대:

- 구현 전에는 새 테스트가 실패한다.

### Task 2 — payload completeness 기준 backfill 구현

- [x] `visual_kind`가 있어도 `validate_visual()` 결과가 있으면 payload를 보강한다.
- [x] 이미 완성된 `cards`와 `table_rows`는 덮어쓰지 않는다.
- [x] confirmed fact가 있으면 fact 기반으로 payload를 만들고, 없으면 section title/body 기반으로 fallback payload를 만든다.

### Task 3 — AI 생성 이미지 eligibility 정책 정리

- [x] `real-generated` 이미지가 export 가능해지는 조건을 테스트로 고정한다.
- [x] real mode에서는 승인된 `ImageGenerationJobRecord.output_asset_id`만 허용한다.
- [x] mock/dev mode에서는 생성 이미지 job을 approved로 만들거나 `real-generated`를 dev 한정 eligible로 본다.
- [ ] 실제 이미지 생성 저장 경로에서 `ImageGenerationJobRecord`가 생성되는지 실제 프로젝트로 확인한다.

실행:

```bash
uv run --project backend pytest backend/tests/test_page_readiness_service.py backend/tests/test_wysiwyg_export_contract.py -q
```

### Task 4 — export blocker 프론트 표시

- [x] `GeneratedDetailPageResult.tsx`에서 export 실패 응답의 `detail.blockers`를 파싱한다.
- [x] blocker code를 한글 문구로 매핑한다.
- [x] `다운로드 전 확인이 필요합니다` 박스를 footer 근처 또는 결과 상단에 표시한다.
- [x] `검수하며 다듬기에서 해결하기` 버튼을 제공한다.
- [x] 새 다운로드 시도 시 이전 blocker 안내를 초기화한다.
- [x] blocker 발생 시 내부 JSON 대신 짧은 한글 오류 문구만 표시한다.

### Task 5 — PNG/JPG E2E 갱신

- [x] PNG export의 content type이 `image/png`인지 확인한다.
- [x] JPG export의 content type이 `image/jpeg`인지 확인한다.
- [x] 파일명이 `.png`, `.jpg`로 분기되는지 확인한다.
- [x] readiness blocker가 있을 때 사용자 메시지가 표시되는지 확인한다.

실행:

```bash
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts e2e/upload-ready-golden-path.spec.ts --project=chromium --reporter=line
```

### Task 6 — 실제 프로젝트 수동 검증

- [ ] `fffe0d0f-64e0-4085-bcc4-239af755eaaf` result 화면을 연다.
- [ ] PNG 다운로드를 시도한다.
- [ ] JPG 다운로드를 시도한다.
- [ ] 저장된 파일을 열어 브라우저 상세페이지와 같은지 확인한다.

> 자동화 검증은 통과했다. 실제 프로젝트 수동 검증은 로컬 dev 서버와 브라우저에서 별도 확인이 필요하다.

---

## 4. 완료 기준

- readiness가 `ready: true`가 된다.
- PNG 다운로드가 실제 파일로 저장된다.
- JPG 다운로드가 실제 파일로 저장된다.
- export 실패 시 이유가 한글 체크리스트로 보인다.
- backend tests 통과.
- frontend build 통과.
- export E2E 통과.
