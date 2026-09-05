# Sellform V2 Sprint 5 코드리뷰 — AI 리디자인 이미지

검토일: 2026-08-03  
대상 기획: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-5-ai-redesign.md`

## 결론

Sprint 5의 로컬 구현 범위는 완료되었습니다. 공급처 이미지는 **참조 입력**으로만 쓰고, 실제 AI 생성 결과를 판매자가 검토·승인한 경우에만 상세페이지 카드에 연결됩니다.

다만 실제 이미지 공급자 호출은 API 키가 없는 현재 개발 환경에서 실행할 수 없으므로, 외부 공급자 품질·요금의 실환경 검증은 별도로 남아 있습니다. API 키가 없을 때에는 빈 이미지나 모의 이미지를 저장하지 않고 `IMAGE_PROVIDER_NOT_CONFIGURED`로 안전하게 차단합니다.

## 기획 대비 확인

| 기획 항목 | 구현 | 확인 |
| --- | --- | --- |
| 승인된 스토리보드에서 장면별 작업 준비 | `prepare_storyboard_jobs`가 `ai_redesign_required` 카드별 2개 후보 작업 생성 | 완료 |
| 장면 역할 분리 | HERO, 사용, 소재, 충전/보관, 기능 시각화, 구성품, CTA 역할 매핑 | 완료 |
| 상품 정체성 보존 | 전체 제품 사진 + 조작/디테일/사용 사진이 2장 이상 없으면 차단 | 완료 |
| 공급처 원본 최종 출력 금지 | `reference_only` 자산은 생성 입력으로만 허용, 승인 결과로 선택 불가 | 완료 |
| 허위 기능·인증·구성품 요청 차단 | 판매자 보정 문장에서 미확인 버튼·포트·인증·의료 표현을 검출해 거절 | 완료 |
| 비동기 작업 상태 | `queued → running → needs_review` 상태를 저장하고, 프론트가 2초 간격으로 조회 | 완료 |
| 생성 후보 비교 | 후보별 결과 이미지 썸네일, 참조 사진, 보존 항목, 프롬프트, 비용 정보를 표시 | 완료 |
| 검토 후 승인 | 위험 신호가 있으면 외형 확인을 명시적으로 눌러야 승인 가능 | 완료 |
| 결과 안전 검사 | 원본과 과도하게 유사한 결과 및 생성 결과 내 중국어 공급처 문구를 차단 | 완료 |
| 생성 이력 | 입력 스냅샷, 참조 자산, 검증 결과, 예상/실제 비용 필드, 사용량, 시드 저장 | 완료 |
| API 키 미설정 안전 동작 | 모의 최종 이미지를 만들지 않고 차단 상태 반환 | 완료 |

## 구현 파일

- `backend/src/services/storyboard_image_generation_service.py`
- `backend/src/services/image_generation_service.py`
- `backend/src/services/product_identity_validator.py`
- `backend/src/api/storyboard_image_jobs.py`
- `backend/src/db/models.py`
- `backend/src/db/database.py`
- `frontend/src/components/planning/StoryboardImageGenerationPanel.tsx`
- `backend/tests/test_v2_sprint5_ai_redesign.py`

## 검증 결과

```powershell
Set-Location C:\page\backend
C:\page\backend\.venv\Scripts\python.exe -m pytest tests\test_v2_sprint5_ai_redesign.py -q
```

결과: `16 passed`

```powershell
Set-Location C:\page\frontend
npm.cmd run build
```

결과: 성공. 기존 `<img>` 최적화 및 React Hook 의존성 경고만 있으며 Sprint 5 컴파일 오류는 없습니다.

## 수동 확인 방법

1. 사실·증거를 확인한 뒤 스토리보드를 승인합니다.
2. `/planning` 화면에서 **AI 리디자인 이미지 준비**를 누릅니다.
3. 각 후보에서 참조 사진이 2장 이상이고, 보존 항목이 제품 외형·색상·버튼·포트·구성품으로 표시되는지 확인합니다.
4. API 키가 없는 현재 환경에서는 실행 시 차단 안내가 표시되는지 확인합니다. 이것은 정상 동작입니다.
5. 이후 실제 API를 설정하면 실행 후 후보가 `검토 필요` 상태가 되고, 생성 이미지와 참조 사진을 비교해 **외형 확인 후 사용**을 눌러야 카드에 연결됩니다.

## 외부 설정이 필요한 항목

실제 이미지 생성은 다음 설정 후에만 실행됩니다.

```env
SELLFORM_IMAGE_GENERATION_MODE=real
OPENAI_API_KEY=...
```

요금 청구·크레딧 차감은 Sprint 5 범위가 아닙니다. 현재는 예상 비용과 사용량 이력만 남기며, 실제 결제 연동은 후속 스프린트에서 구현해야 합니다.
