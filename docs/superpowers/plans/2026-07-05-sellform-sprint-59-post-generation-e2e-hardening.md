# Sellform Sprint 59 Post-generation E2E and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging for any discovered failure and superpowers:verification-before-completion before declaring the sprint complete.

**Goal:** 상품 입력부터 생성, 이미지 선택, 편집, 최종화, 보관함 재진입, PNG/JPG 출력까지를 하나의 신뢰 가능한 제품 흐름으로 검증하고 실패 복구를 완성한다.

**Architecture:** 외부 LLM/이미지 provider는 contract mock transport로 대체하되 실제 API, DB, storage, frontend route를 통과한다. 각 단계의 상태 전이를 기록하고 재시도는 실패한 작업부터 이어서 수행한다.

**Tech Stack:** FastAPI, PostgreSQL test database, Next.js 14, Playwright, pytest, provider mock transport.

---

## File Structure

- Create: `backend/tests/test_post_generation_lifecycle.py`
- Create: `backend/tests/test_export_failure_recovery.py`
- Modify: `backend/src/services/agent_run_service.py`
- Modify: `backend/src/services/export_service.py`
- Modify: `backend/src/api/agent_runs.py`
- Modify: `frontend/src/components/GenerationProgressShell.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/components/DetailPageLibrary.tsx`
- Create: `frontend/e2e/sellform-complete-lifecycle.spec.ts`
- Create: `docs/testing/2026-07-05-sellform-sprint-59-release-checklist.md`

## Tasks

### Task 1: Golden-path 통합 fixture

- [ ] 한 상품, 여러 섹션 이미지, 한국어 카피를 반환하는 결정론적 provider fixture를 만든다.
- [ ] 업로드 asset이 `input_snapshot.asset_ids`부터 최종본까지 유지되는지 검증한다.
- [ ] 실제 provider 호출이나 크레딧 사용이 발생하면 테스트가 실패하게 한다.

### Task 2: 전체 lifecycle 백엔드 테스트

- [ ] 프로젝트 및 run 생성
- [ ] 11-Agent 결과와 이미지 후보 생성
- [ ] 후보 선택과 카피 수정
- [ ] 최종본 확정
- [ ] library 조회
- [ ] PNG/JPG export
- [ ] artifact와 final version 연결 검증

### Task 3: 실패 지점별 복구

- [ ] 이미지 생성 일부 실패 시 성공 후보를 보존하고 실패 슬롯만 재생성한다.
- [ ] QA 재작업 시 진행 표시가 실제 노드 이동과 일치한다.
- [ ] export route timeout, 이미지 404, 폰트 실패를 각각 재현한다.
- [ ] 재시도 후 같은 프로젝트와 최종본에서 성공하도록 한다.
- [ ] 실패 때문에 사용자를 새 프로젝트 입력 화면으로 강제 이동시키지 않는다.

### Task 4: 진행 화면의 진실성

- [ ] 단순 0.5초 타이머로 단계를 완료 처리하지 않는다.
- [ ] backend event의 `started`, `completed`, `failed`, `retrying`을 그대로 표시한다.
- [ ] QA가 이전 노드로 되돌리면 `재검토 중`과 대상 단계를 함께 표시한다.
- [ ] 장시간 이미지 생성과 export에는 경과 시간과 취소/재시도 안내를 제공한다.

### Task 5: 브라우저 전체 E2E

- [ ] 상품 이미지 업로드 후 생성한다.
- [ ] 서로 다른 섹션 이미지 후보를 확인하고 하나를 교체한다.
- [ ] 카피를 직접 수정하고 AI 수정 명령을 한 번 실행한다.
- [ ] 최종본을 확정한다.
- [ ] 보관함에서 같은 프로젝트를 다시 연다.
- [ ] PNG와 JPG를 다운로드한다.
- [ ] 파일 헤더, 크기, 세로 길이, 핵심 텍스트와 이미지 존재를 검증한다.

### Task 6: 출시 전 체크리스트

- [ ] mock/real 모드 표시가 실제 서버 설정과 일치한다.
- [ ] API 키와 비용 정보가 로그, 응답, export에 노출되지 않는다.
- [ ] 한국어 오류 문구와 재시도 동작을 수동 확인한다.
- [ ] desktop과 좁은 viewport에서 겹침과 잘림이 없다.
- [ ] 기존 Sprint 54~58 계약 테스트와 frontend build가 통과한다.

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_post_generation_lifecycle.py tests\test_export_failure_recovery.py -v

cd /d C:\page\frontend
npm.cmd run build
npm.cmd run test:e2e -- sellform-complete-lifecycle.spec.ts
```

## Acceptance Criteria

- 생성부터 재다운로드까지 한 브라우저 E2E가 통과한다.
- 진행 화면은 실제 backend 단계와 재시도 상태를 반영한다.
- 실패 후 프로젝트 데이터와 마지막 성공 결과가 보존된다.
- 화면과 PNG/JPG의 최종본 ID 및 콘텐츠가 일치한다.
- 테스트 과정에서 유료 LLM/이미지 API 호출이 발생하지 않는다.
