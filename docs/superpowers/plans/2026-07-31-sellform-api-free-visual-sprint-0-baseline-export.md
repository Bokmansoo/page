# Sellform Sprint 0 기준선 확보 및 JPG 출력 복구 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 현재 생성·미리보기·다운로드 흐름을 재현하고 실제 상품 1종의 JPG를 안정적으로 내려받는다.  
**기간:** 1주  
**의존성:** 없음

**구현 상태:** 완료 — 코드, 자동 검증 및 로컬 통합 검증 완료

## 범위

- Playwright Chromium 설치 여부 사전 진단
- JPG/PNG export 오류를 사용자 친화적으로 표시
- 빨간 Mock 이미지와 내부 표식 노출 위치 조사
- 기준 상품 3종과 기준 결과 보관 규칙 확정
- 현재 미리보기와 다운로드 결과 차이 기록

## 제외

- 실제 상품 사진 자동 배치
- 이미지 역할 분류
- 신규 디자인 템플릿

## 예상 수정 파일

- `backend/src/services/export_service.py`
- `backend/src/api/exports.py`
- `backend/tests/test_export_service.py`
- `frontend/src/components/GeneratedDetailPageResult.tsx`
- `frontend/e2e/completed-detail-page-export.spec.ts`
- `docs/runbooks/실행가이드.md`

## 작업

### Task 1: 기준 결과 확보

- [x] 소형 가전, 뷰티, 생활용품 기준 상품 유형과 검증 항목을 고정한다.
- [x] 기준 상품 3종의 입력, 생성 결과와 PNG/JPG 다운로드 시도를 보관한다.
- [x] 빨간 Mock 이미지, 누락 이미지, 레이아웃 깨짐과 내부 배지를 체크리스트로 기록한다.
- [x] 이후 스프린트가 동일 입력으로 재생성할 수 있도록 자동 테스트 데이터를 고정한다.

### Task 2: Playwright 사전 진단

- [x] Chromium 실행 파일이 없을 때의 실패 테스트를 작성한다.
- [x] export 시작 전에 브라우저 설치 상태를 확인한다.
- [x] 실패 응답에 `uv run playwright install chromium` 안내를 포함한다.
- [x] 실행가이드에 최초 설치 및 확인 명령을 추가한다.

### Task 3: JPG/PNG 기본 흐름 검증

- [x] 백엔드 export 단위 테스트를 실행한다.
- [x] 브라우저 E2E로 JPG와 PNG 다운로드 요청을 검증한다.
- [x] 이미지·폰트 로딩 완료 전에 캡처하지 않는지 확인한다.
- [x] 실패 작업을 성공 이력으로 저장하지 않는지 확인한다.

## 검증 명령

```powershell
cd C:\page\backend
uv run playwright install chromium
uv run pytest tests/test_export_service.py tests/test_exports.py -v

cd C:\page\frontend
npm.cmd run test:e2e -- completed-detail-page-export.spec.ts
```

## 완료 기준

- [x] 기준 상품 1종 이상이 JPG와 PNG로 다운로드된다.
- [x] Playwright가 없을 때 해결 명령이 화면에 표시된다.
- [x] 기준 상품 3종의 현재 결과와 문제 목록을 확보한다.
- [x] 실패 export가 성공으로 표시되지 않는다.

## 다음 스프린트 인계

Sprint 1은 본 문서의 기준 결과와 체크리스트를 사용해 빨간 Mock 이미지를 실제 상품 사진으로
교체한다.
