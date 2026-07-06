# 트러블슈팅: Sellform Sprint 2 리뷰 보완

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | 사실 검증 API, 사실 검증 보드 UI, 리뷰 문서 |
| 상태 | 해결 |

---

## 1. 증상

- Sprint 2 코드 리뷰 문서가 승인 상태였지만, 실제 검증 결과와 맞지 않았다.
- `next build`가 미사용 변수 때문에 실패했다.
- API가 기획서에 정의된 검증 상태값 외 문자열을 허용했다.
- 사실 카드의 이미지 근거로 다른 프로젝트의 자산 ID를 연결할 수 있었다.
- 최종 전체 백엔드 테스트에서 Sprint 2 범위 밖의 `test_compliance.py` 실패와 전체 suite 순서의 DB 격리 실패가 관찰되었다.

---

## 2. 원인

1. `FactUpdateSchema.verification_status`가 단순 `str`로 정의되어 enum 계약을 강제하지 못했다.
2. `source_asset_id` 입력 시 `assets.project_id == project_id` 검증이 없었다.
3. 프론트 사실 검증 보드에 사용하지 않는 `activeFactId`, `idx` 변수가 남아 있었다.
4. 기존 리뷰 문서가 인코딩이 깨진 상태였고, 최신 검증 결과를 반영하지 못했다.

---

## 3. 조치

- `verification_status`를 `Literal["unknown", "confirmed", "needs_revision"]`로 제한했다.
- `verify_source_asset_belongs_to_project()`를 추가해 생성/수정 시 같은 프로젝트의 자산만 근거로 연결되게 했다.
- 실패 테스트를 먼저 추가한 뒤 API를 보완했다.
- 프론트 미사용 변수 제거, `useEffect` 의존성 안정화, 로컬 업로드 이미지 미리보기 lint 의도 주석을 추가했다.
- Sprint 2 코드 리뷰 문서를 깨지지 않는 한국어 상단 섹션으로 갱신하고 테스트 증적을 추가했다.
- 테스트 증적 문서는 Sprint 2 관련 테스트 통과와 전체 suite 참고 실패를 분리해서 기록했다.

---

## 4. 예방 메모

- API 계약에 선택지가 정해진 문자열은 `Literal` 또는 enum으로 먼저 고정한다.
- ID 참조 입력은 항상 현재 프로젝트/워크스페이스 소유 검증을 함께 넣는다.
- 리뷰 문서의 승인 판단은 `backend pytest`와 `frontend build`가 모두 끝난 뒤 작성한다.
