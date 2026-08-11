# Sellform V2 Sprint UX-2E-1 코드리뷰

검토·보완일: 2026-08-06  
상태: 구현 완료 · 유료 OCR/LLM 제공자 활성화 대기

## 결론

UX-2E-1의 안전한 작업 흐름을 구현했다.

```text
참고/OCR 사진 → 검토 전용 사실 후보 → 판매자 확정·충돌 해결
→ 확정 사실만 포함한 GenerationJob 카피 요청 → 근거·금지 표현 검사
→ 판매자 승인 → UX-2E-2/3에 전달 가능한 승인 카피 계약
```

기본 실행기는 비용이 발생하지 않는 결정론적 제공자다. 이는 API 키·예산 승인이 없는 현재 환경에서 실제 LLM 결과인 척하지 않기 위한 선택이다. 다만 OCR과 카피 모두 제공자 중립 `GenerationJob` 계약, 입력 스냅샷 해시, 제공자/모델, 비용, 재시도 가능 여부와 오류 분류를 영속 기록하므로 유료 제공자를 연결할 준비가 돼 있다.

## 기획 대비 구현

| 기획 항목 | 상태 | 구현 근거 |
| --- | --- | --- |
| OCR 후보·번역·정규화 | 완료 | 원문/번역/언어/신뢰도/bbox/검사 ID/제공자/모델/처리 시각을 증거에 보존하고 모델·전원·소비전력·배터리·크기·시간을 정규화 |
| OCR 실패 처리 | 완료 | `provider_error`, `safety_blocked`, `low_confidence`와 재시도 가능 여부·직접 입력 안내를 자산별로 반환 |
| 판매자 확정 사실 보호 | 완료 | OCR 충돌은 신규 후보만 `conflicted`로 만들며 기존 `seller_confirmed` 사실은 유지 |
| 근거 기반 카피 | 완료 | 확정·근거 보유 사실만 입력에 넣고 장면 목적/채널/문체/길이/금지 표현을 입력 스냅샷에 고정 |
| GenerationJob·비용 감사 | 완료 | `generation_jobs`에 워크스페이스/프로젝트 범위의 입력 해시, 출력, 제공자·모델, 추정/실제 비용, 사용량, 오류·재시도 기록 |
| 금지 표현·근거 검사 | 완료 | 금지 표현, 미근거 수치, 건강·인증·성능 주장 검사를 통과한 결과만 `needs_seller_review`로 저장 |
| 승인 무효화 | 완료 | 사실·브리프·장면 목적·근거 변경 시 기존 카피를 `stale`로 바꾸고 재생성 전 승인 불가 |
| 권한·후속 전달 | 완료 | 편집 권한만 생성/승인 가능하며 렌더 계약에는 `seller_approved` 카피만 포함 |
| UI | 완료 | 참고 사진 후보 추출, 근거 이미지/bbox 검토, 작업 수·예상 비용, 카피 승인·반려·재생성 흐름 제공 |

## 변경 파일

- `backend/src/services/ocr_copy_generation_service.py`: OCR/카피 제공자 계약, 영속 작업 감사, 실패 분류, grounding·승인 검증
- `backend/src/db/models.py`, `backend/src/db/database.py`: `generation_jobs`와 OCR 증거 추적 컬럼, 기존 DB 호환 스키마 보완
- `backend/src/services/fact_evidence_service.py`: 모델명 정규화, OCR 충돌의 확정 사실 보호, 사실 변경 시 카피 stale 처리
- `backend/src/services/api_ready_generation_service.py`: 브리프·장면 변경 시 카피 무효화 및 승인 카피만 렌더 계약에 전달
- `backend/src/api/facts.py`, `backend/src/api/pages.py`, `backend/src/schemas/api_ready_generation.py`: OCR/카피/비용 견적 API와 권한·타입 계약
- `frontend/src/components/FactEvidenceBoard.tsx`, `frontend/src/components/planning/ApiReadyGenerationPlanPanel.tsx`: OCR·카피 검토 UX
- `backend/tests/test_ux2e1_ocr_llm_product_understanding.py`: 모델 후보, 증거 추적, GenerationJob, 충돌 보호, stale, 승인 handoff, viewer 차단 회귀 테스트

## 검증 결과

```text
backend: 22 passed
  - test_v2_sprint3_evidence_board.py
  - test_ux2e1_ocr_llm_product_understanding.py
  - test_ux2e0_api_ready_generation.py

frontend: npm.cmd run lint 통과 (기존 경고만 존재)
```

`tsc --noEmit`은 이번 변경과 무관한 기존 e2e fixture, account, operations 타입 오류 때문에 전체 통과하지 않는다.

## 수동 확인 시나리오

1. 공급처 사양 사진을 선택해 한국어 정보 후보를 추출한다.
2. 원문·번역·OCR 영역·언어·신뢰도를 확인하고 후보를 확정하거나 충돌을 해결한다.
3. 카피 작업 수와 예상 비용을 확인한 뒤 장면별 초안을 만든다.
4. 근거·금지 표현 검사와 사실 ID를 확인해 승인한다.
5. 확정 사실 또는 브리프를 수정해 카피가 `재생성 필요`가 되고, 후속 렌더 계약에서 제외되는지 확인한다.
