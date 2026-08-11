# Sellform V2 Sprint UX-2E-2 코드리뷰 — 정체성 보존 이미지 생성

검토일: 2026-08-06  
대상 기획: `docs/superpowers/plans/2026-08-06-sellform-v2-sprint-ux-2e2-identity-preserving-image-generation.md`  
최종 판정: **기획 범위 구현 완료 · 자동 회귀 검증 통과 · 실제 유료 API 품질 검증만 운영 확인 필요**

## 최종 결론

초기 구현은 기본 생성·승인 흐름은 동작했지만 UX-2E-2 기획과 대조했을 때 공급처 캡처가 제공자 입력에 포함될 수 있고, 충전 장면의 확정 사실 게이트가 없으며, 승인 입력 스냅샷·취소·중복 디스패치 방지·가격/마켓 OCR 차단·원본 비교 UI가 부족했다.

이번 리뷰에서 위 결함을 수정했다. 현재는 승인된 스토리보드에서 생성 대상 장면만 준비하고, 판매자 보유 안전 사진 2~3장과 확정 사실·승인 카피를 작업 입력에 고정한다. 공급처 캡처와 OCR 위험 사진은 생성 참고용으로도 제외하며, 충전·전원 장면은 확인된 전원/충전/배터리 사실이 없으면 정보형 HTML을 유지하고 이미지 생성은 차단한다.

생성 요청은 브라우저가 아닌 서버의 공통 제공자 어댑터를 통해 실행된다. 생성 결과는 이미지 품질·제품 정체성·OCR·가격·전화번호·QR 문구·마켓/경쟁사 문구·권리 근거 상태를 검사하고, 판매자 검수 전에는 최종 상세페이지 자산으로 승격하지 않는다.

## 기획 대비 구현 확인

| 기획 항목 | 구현 근거 | 판정 |
| --- | --- | --- |
| 승인 장면 계획·확정 입력 고정 | 승인된 storyboard revision, ScenePlan, 확정 사실, 판매자 승인 카피, 기준 사진, 고정 요소를 `input_snapshot`에 저장 | 완료 |
| 생성 장면 제한 | HERO/사용/기능·소재 클로즈업/근거 있는 충전·전원 장면만 생성 대상으로 사용. spec/notice/CTA는 생성 목록에서 제외 | 완료 |
| 충전·전원 사실 게이트 | 확인된 충전·전원·배터리·정격 입력 사실이 없으면 `POWER_FACT_REQUIRED`로 차단하고 정보형 페이지 유지 | 완료 |
| 안전한 기준 사진 | `uploaded`/`self_shot` + `seller_owned` + 이미지 + 품질 통과 + OCR/가격/QR/마켓 위험 없음 조건 적용 | 완료 |
| 공급처 캡처 입력 제외 | `sourced`, `reference_only`, 가격표, OCR 위험 사진은 제공자 입력에서 기본 제외 | 완료 |
| 제품 정체성 보존 | 전체 제품 + 조작부/측면/사용 장면 2장 이상 요구, 형태·색상·버튼·포트·구성품 고정 프롬프트 및 결과 검사 | 완료 |
| 서버 제공자 어댑터 | `GenerationProviderAdapter`의 이미지 경계에서 OpenAI allow-list 제공자를 해석하고 서버 파일로 image edit 호출 | 완료 |
| 제공자 데이터 정책 | 학습 미사용, 기본 악용 모니터링 최대 30일, 승인 조직의 ZDR 가능 여부를 작업 스냅샷에 명시 | 완료 |
| 비용·상태·재시도 | 장면 수·1024×1024·예상 합계·재생성 비용 안내, 실제 보고 비용, 시도 번호/실패 코드/기준 사진/revision 이력 저장 | 완료 |
| 중복 실행 방지 | 같은 queued 작업 재호출은 새 이력을 만들지 않고 `dispatch_required=false`; worker도 queued 작업만 실행 | 완료 |
| 판매자 취소 | 제공자 전송 전 작업을 `cancelled`로 보존하고 감사 이력과 재시작 경로 제공 | 완료 |
| 결과 안전 검사 | 디코딩·해상도·빈 이미지·정체성 편차·OCR·외국어·가격·전화번호·QR 문구·마켓/경쟁사/공급처 문구 검사 | 완료 |
| 위험 결과 승인 차단 | 위험 결과를 `blocked` 및 rejected asset으로 보존. 일반 텍스트/정체성 경고는 판매자 명시 확인 전 승인 불가 | 완료 |
| 검수 UI | 생성 결과에 `판매자 검수 전` 배지, 생성본/기준 사진 나란히 비교, 실패 사유·재시도·취소·비용 표시 | 완료 |
| 승인 후에만 상세페이지 반영 | `needs_review` 결과를 명시 승인한 경우에만 storyboard와 현재 페이지 섹션 갱신 | 완료 |
| API 실패 안전 폴백 | 키/예산/타임아웃/한도 실패 시 기존 안전 사진·HTML 페이지를 유지하고 모의 이미지를 최종 저장하지 않음 | 완료 |
| 생성 대기 상세페이지 | `allow_pending_images=true`이면 legacy 이미지 카드까지 포함해 제공자 호출을 전혀 하지 않고 즉시 HTML 정보형 페이지로 조립 | 완료 |

## 이번 리뷰에서 수정한 결함

1. 공급처·참고 전용 사진이 실제 이미지 제공자 입력으로 전달될 수 있던 문제를 차단했다.
2. `specification_graphic`, `cta`가 이미지 생성 작업으로 준비될 수 있던 범위를 제거했다.
3. 충전 장면이 확정된 전원 사실 없이 생성될 수 있던 문제를 막았다.
4. 확정 사실, 승인 카피, ScenePlan, 데이터 정책이 작업 입력에 고정되지 않던 문제를 수정했다.
5. OpenAI 구현을 서비스에서 직접 생성하던 구조를 제공자 어댑터 경계로 이동했다.
6. 중국어만 차단하던 결과 OCR 검사를 가격·전화번호·QR·마켓/경쟁사·공급처 문구까지 확장했다.
7. queued 상태 중복 호출이 백그라운드 작업을 다시 등록할 수 있던 문제를 `dispatch_required`로 막았다.
8. 판매자 취소 상태와 API/UI를 추가했다.
9. 장면 전체 예상 비용·해상도·재생성 비용 안내와 원본/생성본 비교 UI를 추가했다.
10. 기준 사진 1장 저장 제한을 2~3장 정체성 팩으로 수정하고 불필요한 중복 검증 분기를 제거했다.
11. 생성 대기 상세페이지 승인 중 일부 legacy 이미지 카드가 실제 제공자를 동기 호출해 화면이 멈추던 문제를 수정하고, 프런트 요청에도 30초 타임아웃을 추가했다.
12. 생성 대기 조립본이 동일 사실 문구를 HERO·기능에 반복하고, 짧은 사실이 종합 사양표에 포함된 것을 중복으로 오인해 최종본을 막던 문제를 수정했다.

## OpenAI 데이터 정책 확인

OpenAI 공식 문서에 따르면 API 데이터는 명시적으로 공유에 동의하지 않는 한 모델 학습에 사용되지 않는다. 다만 기본 악용 모니터링 로그는 최대 30일 보관될 수 있으며, `/v1/images/generations`와 `/v1/images/edits`는 승인된 조직에서 Zero Data Retention 적용 대상이다. 따라서 구현은 “학습 미사용”을 보장 조건으로 기록하되 “기본 무보관”이라고 잘못 표시하지 않는다.

공식 근거: https://developers.openai.com/api/docs/guides/your-data

## 변경 파일

- `backend/src/services/api_ready_generation_service.py`
- `backend/src/services/generation_provider_adapter.py`
- `backend/src/services/storyboard_image_generation_service.py`
- `backend/src/services/image_generation_service.py`
- `backend/src/api/storyboard_image_jobs.py`
- `frontend/src/components/planning/StoryboardImageGenerationPanel.tsx`
- `backend/tests/test_v2_sprint5_ai_redesign.py`
- `backend/tests/test_image_generation_service.py`
- `backend/tests/test_image_generation_api.py`

## 검증 결과

```powershell
Set-Location C:\page
.\backend\.venv\Scripts\python.exe -m pytest `
  backend/tests/test_v2_sprint5_ai_redesign.py `
  backend/tests/test_image_generation_service.py `
  backend/tests/test_image_generation_provider.py `
  backend/tests/test_image_generation_api.py `
  backend/tests/test_ux2e0_api_ready_generation.py `
  backend/tests/test_planning_draft_approve_api.py `
  backend/tests/test_v2_sprint5_prepare_asset_ready_scene.py -q
```

결과: **59 passed**

```powershell
Set-Location C:\page\frontend
npm.cmd run lint -- --file src/components/planning/StoryboardImageGenerationPanel.tsx
```

결과: **오류 0건**, 기존 `<img>` 최적화 경고 4건.

전체 `npx tsc --noEmit`에서는 이번 컴포넌트 오류가 없음을 확인했다. 다만 이번 범위 밖의 기존 파일 `e2e/upload-ready-golden-path.spec.ts`, `e2e/ux2c-uploaded-photo-composition.spec.ts`, `src/app/account/page.tsx`, `src/app/workspace/operations/page.tsx`에 타입 오류가 남아 전체 명령은 실패한다.

## 운영 확인만 남은 항목

코드 구현 누락은 발견되지 않았다. 다만 실제 OpenAI 계정의 잔액/사용 한도가 활성화된 뒤 다음은 운영 환경에서 1회 확인해야 한다.

1. 실제 YL-T02 기준 사진 2~3장으로 HERO·사용·충전 장면을 생성한다.
2. 제공자 응답 시간, 실제 과금 보고값, 결과 이미지 품질을 확인한다.
3. 생성본과 기준 사진을 나란히 보고 버튼·포트·색상·구성품을 판매자가 최종 승인한다.

이 확인은 외부 계정 상태와 생성 결과에 의존하는 운영 검수이며, 현재 코드 구현 완료 판정과는 별개다.
