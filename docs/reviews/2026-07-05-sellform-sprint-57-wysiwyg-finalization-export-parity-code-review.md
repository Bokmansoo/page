# Sellform Sprint 57 코드리뷰

대상 기획: `docs/superpowers/plans/2026-07-05-sellform-sprint-57-wysiwyg-finalization-export-parity.md`

## 구현 요약

- 최종본 고정 서비스 추가
  - `backend/src/services/page_finalization_service.py`
  - 현재 `ProductPage`와 섹션, 검증 사실, 렌더링 가능 asset을 `DetailPageVersion.sections_json`에 snapshot으로 저장
  - 프로젝트당 `is_final=True` 버전을 하나만 유지
  - final 조회는 최신 초안 fallback 없이 실패 처리

- 최종본 API 추가
  - `POST /api/v1/projects/{project_id}/page/finalize`
  - `GET /api/v1/projects/{project_id}/page/final`
  - final이 없으면 404로 명확히 응답

- export 계약 수정
  - `ExportRequest.final_version_id` 추가
  - background export task가 명시 final version을 검증해서 사용
  - final이 없으면 최신 draft로 fallback하지 않고 실패
  - 실패 시 rollback 후 job을 `failed`로 보존

- 프론트 공용 렌더러 추가
  - `frontend/src/components/DetailPageDocument.tsx`
  - 결과 화면과 `/workspace/projects/[id]/render` route가 같은 문서 컴포넌트를 사용
  - export mode에서는 이미지와 폰트 로딩 후 `data-export-ready="true"` 설정

- 다운로드 UX 연결
  - `GeneratedDetailPageResult`에서 다운로드 직전 `page/finalize` 호출
  - 반환된 `final_version_id`를 export 요청에 포함

## 리뷰 결과

### High

- 백엔드 `export_service.run_export`는 아직 Next render route를 Playwright로 캡처하지 않고 기존 Pillow 기반 export 경로를 사용한다.
  - Sprint 57의 "canonical renderer를 export 파일에도 사용" 요구를 완전히 만족하려면 다음 단계에서 `run_export` 또는 별도 export service가 `/workspace/projects/{id}/render?version_id=...`를 열고 `data-export-ready=true`를 기다린 뒤 캡처해야 한다.
  - 이번 변경은 final version 계약, 공용 프론트 renderer, export route 준비까지 완료한 상태다.

### Medium

- `GeneratedDetailPageResult.tsx`에는 기존 렌더러 코드 일부가 unreachable branch로 남아 있다.
  - 빌드는 통과하지만 lint warning에 `<img>` 사용 위치가 남는다.
  - 다음 정리 때 기존 inline article 렌더 코드를 완전히 제거하면 유지보수성이 좋아진다.

### Low

- 기존 코드의 한글 mojibake가 여러 파일에 남아 있어 patch와 리뷰 가독성이 낮다.
  - 기능 변경과 직접 관련 없는 문자열은 이번 범위에서 건드리지 않았다.

## 검증

- `uv run --project backend pytest backend/tests/test_page_finalization_service.py backend/tests/test_wysiwyg_export_contract.py backend/tests/test_exports.py -q`
  - 결과: 9 passed

- `npm.cmd run build`
  - 결과: 성공
  - 기존/신규 `<img>` 관련 Next lint warning은 존재

## 다음 구현 권장 순서

1. `export_service`에 Playwright 캡처 경로 추가
2. `final_version_id`를 render route query로 넘겨 특정 final snapshot만 렌더링
3. full-page screenshot 결과와 화면 DOM section 순서/텍스트 parity 테스트 추가
4. unreachable legacy renderer 코드 제거
