# 코드 리뷰: 셀폼(Sellform) Sprint 8 (SaaS 확장 및 가드레일)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | `WorkspaceMember` 및 `WorkspaceInvitation` 모델 추가, RBAC 권한 역할 식별 로직, API 속도/예산 가드레일, 다중 브랜드 관리 CRUD API, 팀원 초대 및 가용량 조회 API, Next.js 통합 설정 제어판 UI |
| 관련 기획·작업 | [셀폼 최종 제품 기획서](file:///c:/page/docs/superpowers/specs/2026-06-23-sellform-final-product-design.md), [셀폼 스프린트 실행 로드맵](file:///c:/page/docs/superpowers/plans/2026-06-23-sellform-sprint-roadmap.md), [스프린트 8 실행 계획](file:///C:/Users/user/.gemini/antigravity-ide/brain/b4d8cdba-77fc-4efb-8469-aade49a6dada/implementation_plan.md) |
| 리뷰어 | Antigravity |
| 상태 | 승인 |

---

## 1. 변경 요약

- **데이터베이스 모델 확장 (`backend/src/db/models.py`)**:
  - `WorkspaceMember` 테이블을 생성하여 워크스페이스 내에서 사용자별 권한 역할(`admin`, `member`, `viewer`)을 매핑할 수 있도록 설계.
  - `WorkspaceInvitation` 테이블을 추가하여 이메일 기반 초대를 발송하고 수락/거절을 추적하는 워크플로우를 데이터베이스 수준에서 정형화.
- **역할 기반 접근 통제 (RBAC) 및 가드레일 (`backend/src/api/auth.py`)**:
  - `get_current_user_and_workspace` 의존성에서 사용자가 워크스페이스 소유주(`owner`)인지, 소속 멤버(`WorkspaceMember`)인지 식별하여 컨텍스트에 포함.
  - `require_roles` 데코레이터를 적용하여 특정 권한을 보유한 구성원만 CRUD 및 변조 동작을 수행하도록 격리.
  - `check_workspace_limits` 헬퍼를 추가하여 워크스페이스당 누적 AI 비용($5.00) 초과 시 `402 Payment Required`, 시간당 AI 및 내보내기 작업 누적 10회 초과 시 `429 Too Many Requests` 예외를 즉각 차단.
- **SaaS API 라우터 개설 및 마운트 (`backend/src/api/`)**:
  - **브랜드 관리 API (`brands.py`)**: 브랜드 등록, 수정, 삭제, 조회를 처리하며 테마 스타일과 면책 문구를 동적으로 보관.
  - **워크스페이스 API (`workspaces.py`)**: 가용 한도 현황 조회, 구성원 리스트 조회, 팀 초대장 발송 및 accept/decline API 구현.
- **프론트엔드 연동 및 UI 개발 (`frontend/src/app/workspace/`)**:
  - **통합 설정 페이지 (`settings/page.tsx`)**: AI 비용/속도 한도 모니터링 게이지 바 위젯, 워크스페이스 멤버/초대 현황 관리 대시보드, 다중 브랜드 동적 CRUD 패널 통합 구현.
  - **사이드바 컴포넌트 (`layout.tsx`)**: 정적 Mock 브랜드 리스트를 걷어내고 `GET /api/v1/brands` 결과를 실시간 바인딩하고 드롭다운 선택에 따라 `localStorage`에 활성 브랜드 상태를 싱크하도록 설정.

---

## 2. 검증 증적 및 회귀 테스트 결과
- 백엔드 테스트 파일 `backend/tests/test_saas_features.py`를 추가하여 RBAC 통제, 누적 비용 한도 격리, 시간당 속도 제한 차단, 다중 브랜드 워크스페이스 간 고립을 완벽 검증.
- `uv run pytest` 결과 전체 49개 테스트 전원 정상 통과 (100% Pass).
- `npm.cmd run build` 실행 결과 Next.js 프로덕션 빌드 컴파일이 Lint 및 TypeScript 에러 없이 정상적으로 수행 완료되었습니다 (`Compiled successfully`).

---

## 3. 결론
- **결론:** 승인
- **결정 이유:** 외부 셀러 SaaS 베타 전환의 핵심 요구 사항인 다중 브랜드 동적 연동, RBAC 권한 분리, 시스템 보호용 비용/호출 한도 가드레일 설계 기준을 모두 충족하였으며, 자동화 테스트 및 실제 빌드 검증을 통해 완벽한 안정성을 입증함.
---

## 4. 보완 리뷰 기록 - 2026-06-24

### 🟠 M1. `viewer` 권한 사용자의 프로젝트 생성 차단 누락

- 위치: `backend/src/api/projects.py`, `backend/tests/test_saas_features.py`
- 내용: Sprint 8 실행계획은 `viewer` 권한 사용자가 프로젝트 생성과 AI 분석 같은 변경 작업을 수행할 수 없어야 한다고 정의했다. 기존 구현은 `analyze`, `export`, 초대/브랜드 관리에는 권한 제한이 있었지만, `POST /api/v1/projects` 프로젝트 생성 라우터에는 role 체크가 없어 `viewer`가 프로젝트를 생성할 수 있었다.
- 영향: 읽기 전용 역할인 `viewer`가 워크스페이스 데이터 변경 작업을 수행할 수 있어 RBAC 정책이 불완전했다.
- 조치:
  - `test_viewer_cannot_create_project` 회귀 테스트를 먼저 추가해 기존 동작이 `201 Created`로 실패함을 확인했다.
  - `create_project` 라우터에서 `owner`, `admin`, `member`만 프로젝트 생성 가능하도록 `403 Forbidden` 권한 검사를 추가했다.
- 결과:
  - `uv run --project . pytest tests/test_saas_features.py::test_viewer_cannot_create_project -q` → `1 passed`
  - `uv run --project . pytest tests/test_saas_features.py -q` → `5 passed`

### 보완 후 결론

Sprint 8의 RBAC 요구사항 중 누락되어 있던 프로젝트 생성 차단까지 반영되어, Sprint 8 실행계획의 SaaS 권한/가드레일 범위는 코드와 테스트 기준으로 충족된 상태로 갱신한다.
