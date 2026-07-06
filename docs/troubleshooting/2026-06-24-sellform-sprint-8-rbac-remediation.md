# 트러블슈팅: Sellform Sprint 8 RBAC 보완

- 날짜: 2026-06-24
- 범위: Sprint 8 SaaS 권한 가드레일
- 관련 파일:
  - `backend/src/api/projects.py`
  - `backend/tests/test_saas_features.py`
  - `docs/reviews/2026-06-24-sellform-sprint-8-code-review.md`

## 1. 증상

Sprint 8 실행계획은 `viewer` 역할을 읽기 전용 권한으로 정의했다. 그러나 코드 리뷰 과정에서 `viewer`가 `POST /api/v1/projects`를 호출해 새 프로젝트를 생성할 수 있는 가능성이 확인되었다.

## 2. 원인

Sprint 8 구현에서 RBAC는 다음 영역에 적용되어 있었다.

- 브랜드 생성/수정/삭제
- 워크스페이스 초대 생성/조회
- AI 분석 실행
- Export 실행

하지만 프로젝트 생성 라우터인 `create_project`에는 `role` 기반 차단 로직이 없었다. 이 때문에 워크스페이스 멤버십만 있으면 `viewer`도 프로젝트 생성이 가능했다.

## 3. 재현 테스트

먼저 회귀 테스트를 추가해 기존 동작이 실패함을 확인했다.

```text
uv run --project . pytest tests/test_saas_features.py::test_viewer_cannot_create_project -q

FAILED tests/test_saas_features.py::test_viewer_cannot_create_project
assert 201 == 403
```

## 4. 조치

`backend/src/api/projects.py`의 `create_project` 라우터에서 다음 역할만 프로젝트를 생성할 수 있도록 제한했다.

- `owner`
- `admin`
- `member`

그 외 역할, 특히 `viewer`는 `403 Forbidden`을 반환한다.

## 5. 검증

```text
uv run --project . pytest tests/test_saas_features.py::test_viewer_cannot_create_project -q
1 passed, 11 warnings in 0.25s
```

```text
uv run --project . pytest tests/test_saas_features.py -q
5 passed, 36 warnings in 1.03s
```

```text
npm.cmd run build
Compiled successfully
Generating static pages (9/9)
```

## 6. 남은 주의사항

- 현재 Sprint 8의 RBAC는 API 단에서 우선 보강되었다.
- 향후 외부 셀러용 SaaS로 확장할 때는 실제 인증/세션 기반 사용자 권한과 연결해야 한다.
- 프로젝트 수정, 파일 업로드, 페이지 편집 등 변경성 API 전체에 대해 역할별 권한 매트릭스를 별도로 점검하는 것이 좋다.
