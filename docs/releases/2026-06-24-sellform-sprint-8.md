# 셀폼(Sellform) 릴리스 노트 - Sprint 8 (SaaS 확장 준비)

## 1. 릴리스 정보
- **릴리스 버전:** v0.8.0 (Sellform-saas-preview)
- **배포 일자:** 2026-06-24
- **주요 내용:** 다중 테넌트 지원을 위한 브랜드 동적 관리 API 및 드롭다운 바인딩, 팀 초대 및 회원 목록(RBAC) 관리 제어판 수립, AI 예산 비용($5.00) 및 작업 제한(10회/시간) 가드레일 작동 구현.

---

## 2. 신규 기능 명세 (SaaS Features)

### 2.1 다중 브랜드 동적 관리 (Brand CRUD)
- 기존 Next.js의 정적 Mock 브랜드 리스트를 완전히 배제하고 백엔드 `Brand` 테이블과 연동하였습니다.
- 사용자는 설정 제어판에서 신규 브랜드(이름, 색상값, CS 면책조항)를 자유롭게 추가, 갱신 및 삭제할 수 있으며, 반영 결과는 사이드바 브랜드 드롭다운 메뉴에 즉각 연동됩니다.

### 2.2 역할 기반 접근 제어 (RBAC) 및 팀원 초대
- 워크스페이스 내에서 구성원 권한(`owner`, `admin`, `member`, `viewer`)에 따라 접근 통제가 정밀하게 가동됩니다.
- `viewer`(뷰어) 권한을 지닌 팀원은 프로젝트 생성, AI 분석, 페이지 내보내기 등 일체의 수정 및 처리 작업이 원천 차단되며 `403 Forbidden` 경고를 수령합니다.
- 이메일을 활용한 팀원 초대장(`WorkspaceInvitation`) 발송 기능 및 상대방 수락 시 워크스페이스 소속으로 매핑되는 accept 워크플로우를 완비하였습니다.

### 2.3 비용 및 속도 제한 가드레일 (SaaS Quota Limits)
- **AI 예산 제한**: 워크스페이스 누적 AI 비용 합계가 **$5.00**에 도달하는 즉시 추가 AI 작업을 봉쇄하고 `402 Payment Required` 예외로 안전하게 격리합니다.
- **호출 속도 제한**: 시간당 누적 작업(AI + Export) 횟수가 **10회**를 초과하면 즉각 스로틀링(Throttling)을 적용하여 `429 Too Many Requests` 상태로 돌려보냅니다.

---

## 3. SaaS 규정 및 법적 고지 문서 완비
- 서비스 이용 약관, 개인정보처리방침, AI 생성물 법적 고지문: [2026-06-24-sellform-terms-and-policies.md](file:///c:/page/docs/runbooks/2026-06-24-sellform-terms-and-policies.md)
- 외부 3~5명 베타 온보딩 채널 및 프로세스 디자인: [2026-06-24-sellform-beta-onboarding-design.md](file:///c:/page/docs/research/2026-06-24-sellform-beta-onboarding-design.md)
- 베타 사용량 계측 기반 수익화 요금제 의사결정: [2026-06-24-sellform-subscription-decision.md](file:///c:/page/docs/decisions/2026-06-24-sellform-subscription-decision.md)
