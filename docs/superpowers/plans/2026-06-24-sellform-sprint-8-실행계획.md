# 셀폼(Sellform) 스프린트 8 세부 실행 계획

- **일자:** 2026-06-24
- **목표:** 내부용으로 검증된 상세페이지 엔진을 외부 셀러용 SaaS 베타 서비스로 안전하게 확장하기 위해, 다중 브랜드 관리, 워크스페이스 팀원 초대/역할(RBAC), 사용량/속도/비용 제한 가드레일, 개인정보 및 이용 약관을 완비합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [MODIFY] [models.py](file:///c:/page/backend/src/db/models.py): `WorkspaceMember` 및 `WorkspaceInvitation` 모델 추가
- [MODIFY] [auth.py](file:///c:/page/backend/src/api/auth.py): 역할 기반 권한 정보(`role`) 추가 바인딩 및 예외 처리, AI 사용량/비용 제한 검사 로직 보완
- [NEW] [brands.py](file:///c:/page/backend/src/api/brands.py): 다중 브랜드 생성, 조회, 갱신, 삭제 API 라우터 구현
- [NEW] [workspaces.py](file:///c:/page/backend/src/api/workspaces.py): 워크스페이스 사용량 조회, 팀원 초대 생성/조회, 초대 수락/거절 API 라우터 구현
- [MODIFY] [app.py](file:///c:/page/backend/src/app.py): 신규 라우터 등록
- [NEW] [test_saas_features.py](file:///c:/page/backend/tests/test_saas_features.py): 권한 격리(RBAC), 비용 한도 초과 차단, 속도 제한, 브랜드 다중 관리 검증 테스트 코드 추가

### 1.2 프론트엔드 구조 (`frontend/`)
- [NEW] [page.tsx (settings)](file:///c:/page/frontend/src/app/workspace/settings/page.tsx): 워크스페이스 멤버 관리, 초대 폼, 사용량(AI 비용 게이지) 및 다중 브랜드 설정 제어판 추가
- [MODIFY] [layout.tsx (workspace)](file:///c:/page/frontend/src/app/workspace/layout.tsx): "워크스페이스 설정" 메뉴 신규 활성화(설정 페이지로 이동), 사이드바 브랜드 목록 선택 드롭다운에 실제 백엔드 API 데이터 바인딩 및 선택값 동적 연동

### 1.3 문서화 및 규정 설계
- [NEW] [2026-06-24-sellform-terms-and-policies.md](file:///c:/page/docs/runbooks/2026-06-24-sellform-terms-and-policies.md): SaaS 이용 약관, 개인정보처리방침, AI 생성물 책임 한계 고지문 수립
- [NEW] [2026-06-24-sellform-beta-onboarding-design.md](file:///c:/page/docs/research/2026-06-24-sellform-beta-onboarding-design.md): 외부 베타 테스터 3~5명 대상 온보딩 가이드, 피드백 수집 및 기술 지원 운영 설계
- [NEW] [2026-06-24-sellform-subscription-decision.md](file:///c:/page/docs/decisions/2026-06-24-sellform-subscription-decision.md): 실제 베타 사용량과 AI 비용 청구 내역을 바탕으로 한 구독 등급제 도입 타당성 분석 및 의사결정 기록

---

## 2. 데이터 모델 (PostgreSQL/SQLite 스키마)

### 2.1 워크스페이스 회원 매핑 테이블 (`workspace_members`)
- `workspace_id` (String(36), FK, PK)
- `user_id` (String(36), FK, PK)
- `role` (String(50), default="member") - `owner`, `admin`, `member`, `viewer`
- `joined_at` (DateTime, default=utcnow)

### 2.2 워크스페이스 팀원 초대장 테이블 (`workspace_invitations`)
- `id` (String(36), PK)
- `workspace_id` (String(36), FK)
- `email` (String(255))
- `role` (String(50), default="member")
- `status` (String(50), default="pending") - `pending`, `accepted`, `declined`
- `invited_by` (String(36), FK)
- `created_at` (DateTime, default=utcnow)
- `expires_at` (DateTime, default=utcnow + 7 days)

---

## 3. API 계약 (API Contract)

### 3.1 워크스페이스 가드레일 및 사용량
- **요청**: `GET /api/v1/workspaces/usage`
- **응답 (200 OK)**:
  ```json
  {
    "total_ai_cost": 0.43,
    "ai_budget_limit": 5.0,
    "recent_jobs_count_1h": 2,
    "jobs_limit_1h": 10,
    "is_blocked": false
  }
  ```

### 3.2 워크스페이스 멤버 및 초대
- **멤버 목록 조회**: `GET /api/v1/workspaces/members`
- **초대장 발송**: `POST /api/v1/workspaces/invitations`
  - Body: `{ "email": "seller@test.com", "role": "member" }` (🚨 *owner/admin 권한 필요*)
- **초대 수락**: `POST /api/v1/workspaces/invitations/{invite_id}/accept`
- **초대 거절**: `POST /api/v1/workspaces/invitations/{invite_id}/decline`

### 3.3 다중 브랜드 관리
- **브랜드 목록 조회**: `GET /api/v1/brands`
- **브랜드 등록**: `POST /api/v1/brands`
  - Body: `{ "name": "New Premium Brand", "brand_colors": {"primary": "#000"}, "font_tone": "classic", "default_disclaimer": "..." }`
- **브랜드 수정**: `PATCH /api/v1/brands/{brand_id}`

---

## 4. 테스트 케이스 및 검증 계획

### 4.1 백엔드 단위 테스트 명세 (`backend/tests/test_saas_features.py`)
1. **역할(RBAC) 검증**:
   - `viewer` 권한으로 프로젝트 생성(`POST /projects`)이나 분석 요청 시 `403 Forbidden` 차단 여부 단언.
2. **AI 비용 한도 차단 검증**:
   - 누적 AI 비용이 `$5.00` 한도를 초과할 때 `POST /projects/{id}/analyze` 호출 시 즉각 `402 Payment Required` 예외 발생 검증.
3. **시간당 속도 제한(Rate Limit) 검증**:
   - 1시간 이내에 10회 이상의 작업을 수행하면 `429 Too Many Requests` 상태 코드가 반환되는지 확인.
4. **브랜드 다중 CRUD 검증**:
   - 다중 브랜드 생성 시 활성 브랜드 목록에 정상 노출되며, 다른 워크스페이스 소속 사용자에게 브랜드 정보가 유출되지 않음을 격리 검사.

---

## 5. 완료 기준 (Definition of Done)

1. **테넌트 및 파일 데이터 격리**
   - 멤버가 아닌 사용자는 대상 워크스페이스 브랜드, 프로젝트 및 파일에 절대 접근할 수 없습니다.
2. **RBAC 권한 제어 안착**
   - viewer/member/admin 역할에 의거하여 API 호출 및 화면 렌더링 수정/조회 제한이 적용됩니다.
3. **가드레일 제한 작동**
   - 비용 예산 임계점 도달 혹은 작업 스로틀링 작동 시 안전 가드 경고를 노출하고 핵심 연동 호출을 차단합니다.
4. **Next.js 브랜드 및 워크스페이스 세팅 완료**
   - 동적 브랜드 리스트 및 실시간 초대/권한 멤버 관리가 통합 제어판 화면을 통해 매끄럽게 동작합니다.
5. **CI 및 회귀 보증**
   - 기존 통계 보고서와 Sprint 7 결과가 흐트러짐 없이 유지되며 전체 린트/빌드/테스트가 통과됩니다.
