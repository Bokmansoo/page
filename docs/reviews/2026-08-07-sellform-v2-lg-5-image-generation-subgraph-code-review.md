# LG-5 이미지 생성 서브그래프 코드리뷰

검토일: 2026-08-07  
대상 기획: `docs/superpowers/plans/2026-08-07-sellform-v2-lg-5-image-generation-subgraph.md`

## 결론

LG-5의 완료 조건을 구현했다. LangGraph 실행은 판매자 비용 승인 전에는
`ImageGenerationJobRecord`를 만들거나 제공자 호출을 하지 않으며, 승인 후에는
동일한 `run_id`/`thread_id`에서 작업 준비, 제공자 대기, 결과 수집, 이미지 검토를
순차적으로 수행한다. 생성 후보는 명시적 이미지 승인 전까지 최종 조합 입력으로
노출되지 않는다.

## 기획 대비 확인표

| 기획 항목 | 구현 위치 | 검토 결과 |
| --- | --- | --- |
| `generation_pending → prepare → dispatch → provider_wait → collect → validate → image_review` | `backend/src/agents/langgraph_runtime.py` | 충족 |
| 비용 승인 전 제공자 호출 차단 | `langgraph_review_service.py`, `langgraph_image_generation_service.py` | 충족 |
| 승인된 스토리보드만 작업 준비 | `approve_graph_storyboard`, `prepare_storyboard_jobs` | 충족 |
| 장면/프롬프트/참조 기준 결정적 작업 ID 및 재시도 재사용 | 기존 `s5-*` 결정적 ID + `prepare_graph_image_jobs` | 충족 |
| 실제 제공자 작업 완료 후 동일 graph thread 재개 | `run_storyboard_job_worker`, `resume_provider_wait` | 충족 |
| 제공자 미설정·작업 준비·전송 실패의 복구 가능한 오류 | `ImageGenerationGateError`, `LangGraphRunService._failure_contract` | 충족 |
| 개별 장면 재생성, 거절, 직접 업로드, 승인 | `apply_image_review`, `GraphReviewPanel.tsx` | 충족 |
| 부분 실패 시 성공 작업 보존 | 작업별 상태/출력 자산을 유지하고 대상 장면만 재시작 | 충족 |
| 미승인 생성 자산의 최종 사용 차단 | `approved_generated_asset_ids`와 `review_generated_asset_ids` 분리 | 충족 |
| LG-4 승인과 LG-5 비용 승인 연결 | `_lg4_planning_review`의 영속 스토리보드 승인 | 충족 |

## 추가 보완

- LangGraph가 만든 마지막 `product_information` 카드를 표준 최종 사양 타입인
  `product_specifications`로 매핑했다. 이로써 판매자 승인 시 최종 사양 카드가
  마지막이어야 한다는 스토리보드 검증을 통과한다.
- AI 재디자인 장면에서 같은 원본 사진이 여러 카드의 최종 이미지로 오인되지 않게
  최종 할당은 비우고 후보 참조 ID는 유지한다. 원본 사진은 비공개 정체성 참조로만
  사용된다.

## 자동 검증

성공:

```text
backend: 7 passed
  tests/test_lg4_human_review_interrupts.py
  tests/test_lg5_image_generation_subgraph.py
frontend lint: GraphReviewPanel.tsx, lg5-image-generation-review.spec.ts 통과
python syntax: LG-5 변경 모듈 통과
```

LG-5 테스트는 다음을 직접 확인한다.

- 비용 승인 전 작업 수 0개
- 비용 승인 후 승인된 스토리보드에서 장면 작업을 생성
- 재준비해도 동일 `s5-*` 작업 ID만 사용
- 생성 후보는 `review_generated_asset_ids`에만 있고 승인 전에는
  `approved_generated_asset_ids`가 비어 있음
- 이미지 승인 후 실행이 완료되고 모든 장면 작업이 승인됨
- 실제 제공자 미설정 시 `IMAGE_PROVIDER_NOT_CONFIGURED`로 제공자 호출 전 차단

참고: 전체 프런트 `tsc --noEmit`은 LG-5와 무관한 기존 타입 오류
(`upload-ready-golden-path`, `ux2c-uploaded-photo-composition`, account,
operations) 때문에 실패한다. LG-5 대상 파일 ESLint는 통과했다. Playwright의
LG-5 시나리오는 요청 본문과 화면 전환까지 실행됐지만, 이 Windows 개발 환경의
Next 개발 서버 자식 프로세스가 종료되지 않아 CLI가 종료 타임아웃되었다.
