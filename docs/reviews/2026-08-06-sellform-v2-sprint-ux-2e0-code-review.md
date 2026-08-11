# Sellform V2 Sprint UX-2E-0 코드리뷰

검토·보완일: 2026-08-06  
상태: 구현 완료 · 실제 AI API 연결 대기

## 결론

UX-2E-0은 외부 LLM·OCR·이미지 생성 API를 호출하지 않는 조건에서 완료했다. 판매자는 API 비용 없이 상품 브리프와 장면 계획을 만들고, 확정 사실·안전한 기준 사진·예상 문구·판매자 메모·승인 상태를 수정할 수 있다.

사람 사용 장면이나 새 제품 연출처럼 실제 생성이 필요한 장면은 `generation_pending`으로 남는다. 이 상태는 생성 완료로 위장되지 않으며, 미리보기와 내보내기 계약에는 안전한 원본 사진 또는 확정 사실 기반 정보형 대체 규칙이 함께 저장된다.

## 기획 대비 구현

| 기획 항목 | 상태 | 구현 근거 |
| --- | --- | --- |
| 구조화 상품 브리프 | 완료 | 제품명·카테고리·모델/옵션·색상·채널·확정 사실·금지 표현·정체성 기준·출처 상태·미확인/충돌 항목을 스냅샷에 저장 |
| 브리프 수정·저장 | 완료 | `PATCH /generation-plan`에서 브리프 필드를 수정하고 프로젝트 스냅샷에 보존 |
| 장면 계획 | 완료 | 장면 목적, 사실 ID, 기준 사진 ID, 예상 문구, 출력 유형, Mock 상태, 프롬프트/카피 청사진, 승인 상태를 저장 |
| 장면 수정·재생성 이력 | 완료 | 목적·사실·사진·문구·승인 변경마다 사유와 시각을 장면 이력에 보존 |
| 근거 기반 선택 | 완료 | 임의의 첫 사실을 붙이지 않고 장면 종류별 관련 확정 사실만 기본 연결; 판매자는 다른 확정 사실로 수정 가능 |
| 안전 기준 사진 | 완료 | UX-2D-1 위험 코드·권리 상태를 다시 검사하며, 위험/참고 전용 사진은 PATCH에서도 거부 |
| 제공자 중립 작업 계약 | 완료 | 타입이 있는 요청·출력 규격·전체 작업 상태·비용·검사 결과·실패 유형 계약과 미연결 어댑터 제공 |
| 생성 대기 안전성 | 완료 | 실제 API 호출/비용/가짜 결과 없이 `generation_pending`·정보형 대체 규칙을 명시 |
| 결과·고급 편집 UX | 완료 | 브리프 전체, 확정 사실, 누락·충돌, 장면별 사진·사실·예상 문구·메모·승인을 화면에서 확인/수정 |
| 버전·JPG/ZIP 추적 | 완료 | 일반/최종 스냅샷과 렌더 계약에 생성 계획을 동결하고, 채널 ZIP에 동일한 `generation-plan.json`을 동봉 |
| 차단된 링크의 직접 입력 계속 진행 | 완료 | URL은 `reference_only`로 기록하고 판매자 직접 입력·사진·확정 사실로 브리프/장면 계획을 계속 생성 |

## 변경 파일

- `backend/src/services/api_ready_generation_service.py`: 브리프·장면 생성, 장면별 사실 선택, 예상 문구, 이력, 렌더 대체 계약
- `backend/src/schemas/api_ready_generation.py`: 브리프/장면 PATCH 및 타입이 있는 GenerationJob 요청·결과 계약
- `backend/src/services/generation_provider_adapter.py`: 실제 제공자 연결 전 안전한 타입 경계
- `backend/src/api/pages.py`, `backend/src/services/page_finalization_service.py`: 생성 계획·안전 렌더 계약을 일반/최종 스냅샷에 동결
- `backend/src/services/channel_export_service.py`, `backend/src/api/exports.py`: ZIP에 동결된 생성 계획 JSON 동봉
- `frontend/src/components/planning/ApiReadyGenerationPlanPanel.tsx`: 브리프·사실·장면·이력 검토/수정 UI
- `backend/tests/test_ux2e0_api_ready_generation.py`, `backend/tests/test_v2_sprint7_channel_export.py`: 마사지기 전체 사실, 안전 사진 분류, 차단 링크, 타입 계약, 스냅샷, ZIP 동봉 회귀 테스트

## 검증 결과

```text
backend targeted: 6 passed
  - test_ux2e0_api_ready_generation.py
  - test_v2_sprint7_channel_export.py
frontend: npm.cmd run lint 통과 (기존 경고만 존재)
```

`npx tsc --noEmit`은 e2e fixture, account 화면, operations 화면의 기존 타입 오류로 전체 통과하지 않는다. 이번 UX-2E-0 패널에서 새 타입 오류는 보고되지 않았다. 함께 실행한 `test_exports.py`의 4개 실패는 내보내기 준비 상태에서 400을 반환한 뒤 발생했으며, UX-2E-0의 ZIP 동봉 코드까지 도달하지 못했다. 별도 export readiness 테스트 정비가 필요하다.

## 수동 확인 시나리오

1. 새 프로젝트에서 제품명, 설명, 모델/옵션, 판매 채널, 안전한 제품 사진을 입력한다.
2. 결과 또는 스토리보드에서 `상품 브리프·장면 계획 만들기`를 누른다.
3. 상품 브리프의 모델·색상·채널·금지 표현·정체성 메모와 확정 사실/미확인 항목을 확인한다.
4. 장면별로 기준 사진, 근거 사실, 예상 문구를 수정하고 `이 장면 계획을 확인했습니다`를 선택한다.
5. API 미연결 장면이 `AI 이미지 생성 대기`로 표시되고 가짜 완성 이미지가 생기지 않는지 확인한다.
6. 다운로드 ZIP을 열어 `generation-plan.json`이 포함되며, 해당 최종본과 같은 계획 버전인지 확인한다.
