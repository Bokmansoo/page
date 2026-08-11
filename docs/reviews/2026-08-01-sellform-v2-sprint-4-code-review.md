# Sellform V2 Sprint 4 코드리뷰 — 구매 흐름 스토리보드

검토일: 2026-08-03  
대상 기획: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-4-storyboard.md`

## 최종 결론

Sprint 4는 기획 범위대로 구현되었다. 승인된 사실과 자산 상태를 사용해 3개 스토리 후보를 만들고, 7~12개 섹션의 순서·문구·표시 여부·이미지 요구사항을 이미지 생성 전에 검수할 수 있다. 최종 제품 스펙은 항상 마지막이며, 공급처 참고 자산의 직접 사용과 동일 자산 자동 반복, 미확정 사실 연결은 승인 단계에서 거부된다.

실제 AI 이미지 생성, 자유 캔버스, PNG/JPG 최종 렌더링은 기획서의 제외 범위이므로 Sprint 4 완료 판정에 포함하지 않는다. 현재 API 키가 없어도 Sprint 4의 스토리보드 생성·수정·승인은 정상 동작한다.

## 기획 항목별 검토

| 기획 요구 | 상태 | 구현 근거 |
| --- | --- | --- |
| 승인 사실 기반 7~12개 판매 섹션 | 완료 | `storyboard_service.generate_storyboard()`, 기준 상품 3종 테스트 |
| 최종 제품 스펙을 마지막에 유지 | 완료 | `_normalize_order()`, `validate_storyboard()` |
| `reference_only` 최종 배치 금지 | 완료 | 자산 정책 필터와 승인 검증 |
| 최종 사용 가능 자산만 후보 지정 | 완료 | `is_asset_final_output_eligible()` 사용 |
| 동일 자산 자동 반복 금지 | 완료 | 사용 자산 집합 추적, 중복 승인 거부 |
| 승인된 사실 ID만 문구에 연결 | 완료 | 섹션별 `source_fact_ids`와 confirmed fact 검증 |
| 이미지 부족 시 AI 장면·업로드 요청 | 완료 | `image_requirement`, `scene_request`, `missing_reasons` |
| 스토리 후보 2~3개 | 완료 | 안전 정보형, 이미지 중심형, 균형 판매형 3개 |
| 후보 선택 이유·누락·위험 표시 | 완료 | recommendation reason, missing images, warning, 정보성 비용 |
| 자료 부족 시 안전 후보 기본 선택 | 완료 | 최종 사용 가능 자산이 없으면 `safe_information` 선택 |
| 순서 변경·숨김·복원 | 완료 | planning UI의 이동/숨김, 스토리보드 revision 복원 API/UI |
| 제목·본문 수정 | 완료 | planning 카드 편집과 PATCH 저장 |
| 사실·자산·장면·렌더 템플릿 저장 | 완료 | 확장된 `PlanningDraftCardSchema` |
| 채널 길이·반복 자산 경고 | 완료 | planning UI의 7~12개 길이와 반복 자산 요약 |
| 사실·자산 변경 시 stale | 완료 | `mark_fact_dependents_stale()`, `mark_storyboard_assets_stale()` |
| 추천 생성·선택·수정·승인 API | 완료 | `/storyboard/recommendations`, `/select`, `/restore`, `/approve`, planning PATCH |
| 사실 스냅샷·해시 연결 | 완료 | 생성·승인 시 `approved_fact_snapshot()` |

## 재검토 과정에서 보완한 부분

- 라우트 삽입 위치의 들여쓰기 오류를 수정하고 전체 백엔드 모듈 컴파일을 통과시켰다.
- 단순 카드 목록이던 planning 화면을 스토리 후보 3개 선택·상태·장면 요청·예상 비용을 확인하는 스토리보드 화면으로 확장했다.
- 기존 초안 PATCH가 새 메타데이터를 잃지 않도록 현재 초안과 병합하도록 수정했다.
- 사실 변경이 선택 카드뿐 아니라 추천 후보에도 stale로 전파되게 했다.
- 자산 사용 상태가 바뀌면 해당 자산을 참조하는 승인 스토리보드를 stale로 표시하게 했다.
- 스토리보드 revision 기록과 최근 버전 복원 API/UI를 추가했다.
- 기준 상품 3종(생활가전·뷰티·생활용품)이 모두 7개 이상 섹션과 구체적 장면 요청을 만드는 테스트를 추가했다.

## API 계약

- `POST /api/v1/projects/{project_id}/storyboard/recommendations`: 사실·자산 상태로 후보 3개 생성
- `POST /api/v1/projects/{project_id}/storyboard/select`: 후보 선택
- `PATCH /api/v1/projects/{project_id}/planning-draft`: 순서·문구·숨김 상태 저장 및 새 revision 생성
- `POST /api/v1/projects/{project_id}/storyboard/restore`: 이전 revision 복원
- `POST /api/v1/projects/{project_id}/storyboard/approve`: 사실 스냅샷을 고정하고 스토리보드 승인

## 검증 결과

```powershell
Set-Location C:\page\backend
uv run pytest tests\test_v2_sprint4_storyboard.py -q
# 6 passed

uv run pytest tests\test_v2_sprint4_storyboard.py tests\test_planning_draft_service.py tests\test_planning_draft_api.py tests\test_planning_draft_approve_api.py tests\test_v2_sprint3_evidence_board.py -q
# 25 passed

Set-Location C:\page\frontend
npm.cmd run build
# compiled successfully, type checking passed
```

Sprint 4 전용 테스트는 다음을 검증한다.

- 기준 상품 3종에서 7~12개 스토리보드 생성
- 공급처 참고 자산은 후보 참고로만 연결하고 최종 이미지로 배치하지 않음
- 이미지 부족 시 섹션별 구체적인 AI 리디자인 장면 요청 생성
- 최종 스펙이 마지막이 아니면 저장·승인 거부
- 동일 최종 자산 반복 거부
- 존재하지 않거나 미확정인 사실 ID 연결 거부
- 후보 선택, revision 증가, 과거 revision 복원
- 승인 사실 스냅샷 생성
- 사실·자산 변경 이후 stale 처리

## 서버에서 확인할 내용

1. 백엔드와 프런트엔드를 다시 시작한다.
2. 프로젝트 결과 화면에서 `이전 단계` 또는 planning 주소로 이동한다.
3. 기존 Sprint 3 초안이면 화면이 자동으로 Sprint 4 후보 3개를 다시 만든다.
4. 안전 정보형·이미지 중심형·균형 판매형을 차례로 선택해 섹션 수와 장면 요청이 달라지는지 확인한다.
5. 카드 제목·본문을 수정하고 순서 변경·숨김 후 `임시 저장`을 누른다.
6. `스토리보드 버전`에서 이전 revision을 복원해 본다.
7. 최종 스펙을 마지막이 아닌 위치로 옮기면 저장이 거부되는지 확인한다.
8. 정상 순서로 돌린 뒤 `스토리보드 승인`을 누른다.

## Sprint 5 진입 조건과 현재 상태

Sprint 4 데이터에는 HERO·기능·사용·디테일 장면마다 `scene_request`, `image_requirement`, 참고 자산 후보가 저장된다. 따라서 Sprint 5가 사용할 장면 계약은 준비되었다.

API 키가 없는 현재 환경에서는 `AI 리디자인 필요`가 정상 표시된다. 이는 Sprint 4 미완료가 아니라 Sprint 5가 처리할 대기 상태다. 공급처 이미지를 결과 페이지에 그대로 넣지 않는 정책도 유지된다.

## 남은 경고

빌드와 테스트의 `google.generativeai` 종료 예고, Pydantic class config, `datetime.utcnow()`, 기존 `<img>` 최적화 경고는 이전부터 존재한 기술 부채다. Sprint 4 기능 실패나 미완료 항목은 아니다.
