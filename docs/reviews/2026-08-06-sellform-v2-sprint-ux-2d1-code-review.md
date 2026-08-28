# Sellform V2 Sprint UX-2D-1 코드리뷰

검토일: 2026-08-06  
상태: 보완 구현 완료 · 회귀 테스트 통과

## 결론

UX-2D-1 기획의 핵심인 **위험 사진의 자동 배치 제외**와 **정보형 대체**를 구현했다. 새 Mock 프로젝트에서는 OCR에서 외국어·전화번호·가격·QR·마켓/경쟁사·공급처 위험이 감지된 판매자 사진을 기본 상세페이지 이미지로 자동 사용하지 않는다. 같은 원본(`content_hash`)의 복사본도 자동 배치에서 하나만 사용할 수 있다.

위험 사진을 직접 선택하는 기능은 제거하지 않았다. 기존 UX-2D의 판매자 확인 절차를 거쳐 사용할 수 있으며, 최종 결과 화면은 이 경우 `판매자 확인 후 사용` 상태와 확인 건수를 표시한다.

## 기획 대비 구현

| 기획 항목 | 구현 | 근거 |
| --- | --- | --- |
| OCR 위험 사진 자동 제외 | 완료 | Mock 조립 단계의 보수적 사전 필터와 DB 저장 단계의 `auto_placement_risk_codes` 이중 검사 |
| 동일 원본 중복 자동 배치 방지 | 완료 | `content_hash` 그룹을 자동 배치당 한 번만 사용 |
| 대체 사진이 없을 때 정보형 렌더링 | 완료 | `html_graphic` + `ux2d1_auto_replacement` 메타데이터로 안전한 정보형 섹션 유지 |
| 자동 대체 사유 노출 | 완료 | 콘텐츠 품질 리포트에 `auto_replaced_with_information` 권고 추가 |
| 수동 예외와 상태 구분 | 완료 | 확인된 위험 이미지가 있으면 `판매자 확인 후 사용` 배지와 건수 표시 |
| 미리보기·저장·출력 일관성 | 완료 | 저장된 `visual_payload`와 버전 스냅샷에 대체 메타데이터를 보존 |

## 변경 파일

- `backend/src/agents/mock_outputs.py`: Mock 조립 단계의 안전 필터 및 정보형 대체 사유 생성
- `backend/src/agents/nodes/page_assembly/agent.py`, `backend/src/agents/graph.py`: OCR·해시 등 안전 판단에 필요한 자산 메타데이터 전달
- `backend/src/services/agent_run_service.py`: 페이지 저장 단계에서 위험/중복 자동 선택을 HTML 정보형으로 전환
- `backend/src/services/commerce_content_quality_service.py`: 자동 대체 권고와 판매자 확인 상태 제공
- `frontend/src/components/GeneratedDetailPageResult.tsx`: 판매자 확인 후 사용 상태 표시
- `backend/tests/test_ux2c_uploaded_photo_composition.py`: OCR 위험 제외, 동일 원본 중복 제외, 7장 입력 안전 배치, 수동 선택 뒤 재생성 회귀 테스트
- `backend/tests/test_ux2d_content_quality.py`: 모든 위험 코드, 최신 OCR 검사값, 고화질 보정본의 원본 OCR 계승, 확인 이미지 건수 회귀 테스트

## 검증 결과

```text
backend: 44 passed
frontend: npm.cmd run lint 통과
```

프런트엔드 lint에는 기존 `img` 최적화 및 Hook 의존성 경고가 남아 있으나, 이번 변경으로 새 오류는 발생하지 않았다. 이미지/LLM 생성 API는 연결하지 않았으며, 이번 Sprint는 Mock·규칙 기반 안전 배치 범위만 다룬다.

## 보완 재검토

- 고화질 보정본은 `source_asset_id` 계보를 따라 원본의 파일명·OCR·최신 검사 OCR까지 합산해 위험 여부를 판단한다. 따라서 원본에 외국어·가격·전화번호 등이 있으면 보정본도 자동 배치되지 않는다.
- 중복 `content_hash`는 실제 자동 배치를 시도했을 때만 해당 섹션에 `duplicate_asset_group` 대체 사유를 남긴다. 다른 빈 섹션 전체에 사유가 붙지 않는다.
- 판매자가 수동으로 선택한 이미지의 `content_hash` 그룹은 재생성 시 자동 배치 후보에서 제외한다. 수동 선택은 유지하고, 같은 원본의 자동 복사본이 다른 섹션에 추가되지 않는다.
- `판매자 확인 후 사용` 건수는 위험 코드 개수가 아니라 확인된 이미지 수로 계산한다.
- 생성 페이지의 버전 스냅샷에도 대체 메타데이터가 보존되므로 미리보기·최종화·JPG/분할 ZIP 출력은 동일한 안전 선택을 사용한다.

## 수동 확인 시나리오

1. 새 프로젝트에서 외국어·가격·QR 등이 들어간 사진과 깨끗한 제품 사진을 함께 업로드한다.
2. 생성 후 위험 사진은 자동 선택되지 않고, 해당 섹션이 정보형으로 표시되는지 확인한다.
3. 위험 사진을 직접 선택하고 `사용 확인`을 누르면 결과 상단 상태가 `판매자 확인 후 사용`으로 바뀌는지 확인한다.
4. JPG/ZIP 다운로드에서 자동 제외된 위험 사진이 들어가지 않는지 확인한다.
