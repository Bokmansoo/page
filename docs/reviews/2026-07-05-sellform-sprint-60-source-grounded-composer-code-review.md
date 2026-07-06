# Sellform Sprint 60 코드리뷰

대상 기획: `docs/superpowers/plans/2026-07-05-sellform-sprint-60-source-grounded-composer.md`

## 구현 요약

- 자유 입력 구조화 서비스/API 추가
  - `backend/src/services/intake_structuring_service.py`
  - `POST /api/agent-runs/structure-intake`
  - 상품명, 핵심 특징, 가격, 배송, 분위기, URL/참고 URL을 구조화된 draft로 반환

- source collection 계약 확장
  - `ProductInput.freeform_input` 추가
  - `source_collection` output에 `freeform_input`, `reference_urls`, `has_freeform_input`, `has_reference_url` 보존

- 섹션별 scene planner 추가
  - `backend/src/services/detail_page_scene_planner.py`
  - `cutout_composite`, `generated_scene`, `html_graphic` 전략 구분
  - 이미지 prompt에 no-text 정책 적용

- visual/image generation 계약 확장
  - visual planning image job에 `text_free_required`, `visual_strategy`, `source_asset_ids` 추가
  - image generation job report와 generated image metadata에 동일 필드 보존

- 프론트 one-box intake/review UI 추가
  - `AIDetailPageIntake`에 `상품 자료` textarea와 `자료 확인하기` 버튼 추가
  - `StructuredIntakeReview` 확인 화면 추가
  - `frontend/src/lib/api.ts`에 `structureIntake` helper와 타입 추가
  - `frontend/e2e/source-grounded-composer.spec.ts` 추가

## 리뷰 결과

### High

- E2E는 sandbox/사용량 제한으로 실행하지 못했다.
  - 첫 시도는 `test-results/.last-run.json` 삭제 권한 문제로 실패했다.
  - 임시 output 지정 후에는 Playwright dev server/browser spawn이 sandbox `EPERM`으로 막혔다.
  - 권한 상승 재실행은 사용량 제한으로 거절되었다.
  - 프론트 `next build`는 통과했지만, 실제 브라우저 플로우는 다음 세션에서 E2E로 확인해야 한다.

### Medium

- 구조화 서비스는 deterministic heuristic 기반이다.
  - 현재는 토큰 비용 없이 기본 필드를 뽑는 안전한 MVP다.
  - URL OCR/상품 상세페이지 scraping, LLM 기반 보정은 아직 연결하지 않았다.

- 프론트 확인 화면의 input 값은 아직 최종 생성 payload로 세밀하게 역반영하지 않는다.
  - 현재 생성 시 구조화 draft의 상품명과 자유 입력은 반영된다.
  - 사용자가 확인 화면에서 수정한 가격/배송/특징까지 payload에 반영하려면 controlled form으로 확장해야 한다.

### Low

- 기존 파일의 한글 mojibake가 여전히 많다.
  - 이번 변경에서 새로 만든 파일은 정상 한글을 사용했다.
  - 기존 문구 전면 정리는 별도 작업으로 분리하는 편이 안전하다.

## 검증

- `uv run --project backend pytest backend/tests/test_agent_run_api.py backend/tests/test_intake_structuring_service.py backend/tests/test_detail_page_scene_planner.py backend/tests/test_source_collection_agent.py backend/tests/test_real_multimodal_image_generation_contract.py backend/tests/test_wysiwyg_export_contract.py -q`
  - 결과: 24 passed

- `npm.cmd run build`
  - 결과: 성공
  - 기존/신규 `<img>` 관련 Next lint warning은 존재

- `npm.cmd run test:e2e -- source-grounded-composer.spec.ts`
  - 결과: 미완료
  - 사유: sandbox 권한 및 사용량 제한으로 Playwright 실행 불가

## 다음 작업 제안

1. Sprint 57 잔여 작업: 백엔드 export가 Next render route를 Playwright로 캡처하도록 연결
2. Sprint 60 E2E 재실행: `source-grounded-composer.spec.ts`를 실제 브라우저에서 통과시키기
3. 구조화 확인 화면 고도화: 사용자가 수정한 상품명/특징/가격/배송/분위기를 최종 agent run payload에 반영
4. URL/OCR 수집 연결: 상품 URL과 참고 상세페이지 URL에서 이미지/텍스트를 수집해 `structure_intake` draft에 source evidence로 붙이기
5. scene plan을 page assembly에 연결: `detail_page_scene_planner` 결과를 실제 `PageSection` 및 image job 생성에 반영
