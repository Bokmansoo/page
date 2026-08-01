# 쿠팡형 상세페이지 Sprint 1 코드리뷰

작성일: 2026-08-01  
결론: **재검토 및 보완 완료. Sprint 1 기획 범위를 구현했으며, 상품 자료 묶음·숫자 단위·사진 순서·링크 수집 실패 정보가 이후 단계까지 보존된다.**

## 재검토 결과

최초 리뷰에서는 완료로 표시했지만 다음 두 가지 근거가 부족했다.

1. 직접 업로드 사진을 저장할 때 URL에서 이미 수집한 이미지 ID를 덮어쓸 수 있었다.
2. `260g`·`10분`·`800mAh`가 저장되는 백엔드 검증은 있었지만 판매자 확인 화면까지 그대로 노출되는 브라우저 검증이 없었다.

이번 재검토에서 직접 업로드 사진을 판매자 순서대로 앞에 두고 URL 수집 이미지를 뒤에 합치도록 수정했다. 숫자와 단위의 확인 화면 보존, 403 수집 실패 경고의 응답·저장도 회귀 테스트로 고정했다.

## 기획 대비 확인

| 기획 항목 | 구현 | 결과 |
| --- | --- | --- |
| 다중 이미지 드래그앤드롭/일괄 업로드 | `AIDetailPageIntake`의 `multiple` 파일 선택, drop 영역, 최대 20장 미리보기 | 완료 |
| 5장 이상 이미지 선택 및 순서 확인 | 순서 카드, 앞/뒤 이동, 삭제, 5장 준비 상태 안내 | 완료 |
| 상품명·카테고리·가격·배송·상세 설명·기능·구성품·주의사항 | 입력 화면, 확인 화면, `AgentRun.input_snapshot`·`ProductProject.intake_snapshot` 저장 | 완료 |
| 숫자+단위 보존 | 원문 묶음을 그대로 전송하고 확인 화면에서 동일 표기를 노출한 뒤 `260g`·`10분`·`800mAh`를 확정 사실로 저장 | 완료 |
| 링크 수집 실패 대안 | URL 입력 즉시 직접 업로드 안내, 수집 실패 경고 응답·저장, 기획 화면 배너 | 완료 |
| 직접 업로드와 URL 이미지 병합 | 판매자 지정 순서를 우선하고 URL 수집 이미지를 중복 없이 뒤에 보존 | 완료 |
| 외부 접근 제한 우회 | 구현하지 않음 | 기획 제외 범위 준수 |

## 핵심 변경

- `frontend/src/components/AIDetailPageIntake.tsx`
  - 다중 사진 선택/드래그앤드롭, 순서 이동, 필요 사진 유형 안내.
  - 판매자 정보 필드를 하나의 원문 증거 묶음으로 보존.
  - 생성 직후 순서대로 업로드하고 asset ID 순서를 백엔드에 저장.
  - URL 수집 이미지가 존재해도 직접 업로드 처리에서 유실되지 않도록 두 목록을 병합.
- `backend/src/api/agent_runs.py`
  - 입력 묶음 필드와 `PATCH /api/agent-runs/{id}/input-assets` 추가.
  - 동일 프로젝트의 이미지 자산만 등록하도록 검증.
- `backend/src/services/agent_run_service.py`
  - 자동 탐색보다 판매자가 정한 이미지 순서를 우선.
- `frontend/src/app/workspace/projects/[id]/planning/page.tsx`
  - 링크 수집 실패 시 직접 사진 업로드 대안을 다시 안내.

## 검증

```powershell
Set-Location C:\page\backend
uv run pytest tests/test_coupang_style_input_bundle.py tests/test_agent_run_api.py tests/test_seller_fact_ingestion_service.py -q
```

결과: `16 passed`

추가 검증 내용:

- 상품 자료 전체 필드와 숫자·단위 저장
- 구조화 요약에서 숫자·단위 원문 보존
- 5개 이미지의 판매자 지정 순서 저장 및 실행 단계 유지
- 다른 프로젝트 이미지 등록 거부
- URL 수집 403 실패 경고의 API 응답 및 실행 입력 스냅샷 저장

```powershell
Set-Location C:\page\frontend
npm.cmd run lint
```

결과: 오류 없음. 기존 및 미리보기 `<img>` 관련 경고만 존재한다.

`frontend/e2e/sprint1-input-bundle.spec.ts`에는 다음 회귀 시나리오를 추가했다.

- 5장 일괄 선택과 순서 변경
- `260g`·`10분`·`800mAh`가 판매자 확인 화면에 동일하게 표시되는지 확인

실행 결과:

```text
npx.cmd playwright test e2e/sprint1-input-bundle.spec.ts --project=chromium
2 passed
```

Windows 테스트 환경에서 두 시나리오는 각각 통과했으나 Playwright 임시 개발 서버 종료가 지연되어 상위 명령은 120초 감시 제한에 의해 종료되었다. 테스트 실패는 없었고 출력은 `2 passed`였다.

## 다음 단계

Sprint 2에서 이 입력 묶음의 각 사진을 대표컷·기능컷·사용 장면·구성품·스펙 이미지로 분류하고, 품질/OCR 정보를 보여준다.
