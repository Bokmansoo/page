# 코드 리뷰: Sellform Sprint 32 Figma MCP 디자인 내보내기

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-27 |
| 리뷰 범위 | Figma payload builder, export API, MCP adapter, page-editor 진입점, 설정·문서 |
| 결론 | 승인. Sprint 32 계획 범위 구현 및 2026-06-28 보완 검증 완료 |

## 1. 변경 요약

- Sprint 31 커머스 컷을 Figma design payload로 변환한다.
- 실제 브랜드 관계와 공개 asset base URL을 사용한다.
- `POST /api/v1/projects/{project_id}/page/figma/export`에서 payload를 반환한다.
- MCP sender가 없을 때 전송 성공을 가장하지 않고 `ready` 상태로 안내한다.
- page-editor에 `Figma로 내보내기` 버튼과 상태별 사용자 메시지를 추가했다.
- Figma 설정, 정책, 테스트, 트러블슈팅 문서를 작성했다.

## 2. 조치된 이슈

### 🔴 B1. page-editor 진입점 누락

버튼과 API 호출을 추가하고 비활성·권한·페이지 없음·서버 오류를 구분해 표시하도록 보완했다.

### 🔴 B2. API 테스트 dependency override 오류

`patch("src.api.pages.get_db")` 대신 `app.dependency_overrides[get_db]`를 사용하도록 수정했다.

### 🔴 B3. 프론트 빌드 실패

누락된 배경 후보 로딩 상태를 선언해 `setLoadingBg` 타입 오류를 해소했다.

### 🟠 M1. 실제 전송 없는 성공 응답

adapter에 sender 주입 인터페이스를 추가하고 sender 미연결 시 `not_configured`를 반환하도록 변경했다.

### 🟠 M2. 외부 접근 불가능한 이미지 URL

`SELLFORM_PUBLIC_ASSET_BASE_URL`을 도입하고 저장된 실제 파일명을 사용해 URL을 만든다.

### 🟡 M3. workspace 권한 회귀 테스트 누락

다른 workspace 사용자가 프로젝트의 Figma payload를 요청하면 `404 Project not found`가 반환되는 테스트를 추가했다.

### 🟡 M4. 보안 결정 문서와 실제 payload 불일치

결정 문서가 모든 내부 UUID를 제외한다고 표현했지만 실제 설계는 원본 매핑을 위해 `project.id`와 `section_id`를 포함한다. 사용자 ID, workspace ID, API key, 결제·비용·추적 정보는 제외하고 매핑용 최소 식별자는 포함한다고 문서를 수정했다.

### 🟡 M5. Playwright 3000번 포트 충돌

개발 서버가 3000번을 사용 중이면 Playwright가 새 서버를 시작하지 못하고 120초 후 종료됐다. 테스트 기본 포트를 3100번으로 분리하고 `SELLFORM_E2E_PORT`로 재정의할 수 있게 했다.

## 3. 검증

- Sprint 32 백엔드 전용: `8 passed`
- 백엔드 전체: `138 passed`
- 프론트 프로덕션 빌드: 성공
- Playwright 브라우저 테스트: `1 passed`

## 4. 남은 위험

- 실제 Figma MCP sender는 아직 연결되지 않았다.
- 운영 asset URL은 외부에서 접근 가능한 HTTPS 주소로 설정해야 한다.
- `<img>` 사용에 관한 Next.js 성능 경고 1건은 후속 최적화 항목이다.
