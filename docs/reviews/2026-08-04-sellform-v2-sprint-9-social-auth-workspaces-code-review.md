# Sellform v2 Sprint 9 코드리뷰 — 소셜 로그인과 워크스페이스

검토일: 2026-08-04  
기획: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-9-social-auth-workspaces.md`

## 결론

Sprint 9 범위는 구현 완료입니다. 브라우저의 임시 사용자 ID가 아니라 서버 세션을 기준으로 사용자와 워크스페이스를 식별합니다. 로컬 개발 환경에서는 소셜 앱 키가 없어도 별도 개발용 로그인으로 검증할 수 있고, 운영 모드에서는 이 경로와 테스트용 헤더가 모두 차단됩니다.

## 기획 대비 확인

| 항목 | 결과 | 구현 내용 |
| --- | --- | --- |
| 서버 세션 | 완료 | DB 세션, httpOnly 세션 쿠키, CSRF 쿠키, 만료·폐기 처리가 있습니다. |
| 소셜 로그인 | 완료 | Google·카카오·네이버 시작/콜백 API와 `/login` 화면을 제공합니다. 미설정 공급자는 비활성으로 명확히 표시합니다. |
| OAuth 보안 | 완료 | state 일회성·만료, PKCE, nonce를 사용합니다. Google은 서명된 ID 토큰의 issuer·audience·nonce를 검증합니다. |
| 콜백 주소 분리 | 완료 | `SELLFORM_PUBLIC_API_URL`을 OAuth 콜백 주소로, `SELLFORM_PUBLIC_APP_URL`을 로그인 후 화면 이동 주소로 사용합니다. |
| 계정 식별 | 완료 | 이메일 자동 병합 없이 `provider + provider_account_id`를 안정된 계정 키로 사용합니다. |
| 개인 워크스페이스 | 완료 | 최초 계정 생성 시 개인 워크스페이스와 기본 브랜드를 만들고 세션의 활성 워크스페이스에 기록합니다. |
| 권한 | 완료 | owner/admin/editor 권한을 서버에서 검사하며 다른 워크스페이스의 프로젝트 접근을 거부합니다. |
| 로그아웃·기기 관리 | 완료 | 현재 세션 로그아웃, 전체 기기 로그아웃, 세션 조회 및 특정 기기 해제를 제공합니다. |
| 테스트/개발 경계 | 완료 | `X-Mock-*` 헤더는 명시적으로 허용된 테스트 설정에서만 동작하고 운영 모드에서는 무시됩니다. |
| 확장 프로그램 연계 | 완료 | 캡처 API도 같은 서버 인증 컨텍스트를 사용합니다. |

## 변경 파일

- `backend/src/services/auth_service.py` — 세션, CSRF, OAuth 시도, 계정·워크스페이스 해석
- `backend/src/api/auth_routes.py` — 로그인, 콜백, 로그아웃, 기기·워크스페이스 관리 API
- `backend/src/api/auth.py` — 기존 API의 공통 서버 인증·권한 검사
- `backend/src/db/models.py` — `OAuthAccount`, `UserSession`, `OAuthLoginAttempt`
- `backend/src/config.py` — 인증 모드, 세션, 앱 URL/API URL, OAuth 환경 변수
- `frontend/src/app/login/page.tsx` — Google·카카오·네이버 로그인 시작 화면 및 개발용 로그인
- `frontend/src/app/workspace/layout.tsx`, `frontend/src/lib/api.ts` — 쿠키 기반 세션 호출과 로그인/로그아웃 UI
- `backend/tests/test_v2_sprint9_auth_sessions.py` — 보안·격리·콜백 URL 회귀 테스트

## 검증 결과

```text
backend/tests/test_v2_sprint9_auth_sessions.py
backend/tests/test_v2_sprint8_browser_extension_capture.py
12 passed
```

`npm.cmd run lint`도 오류 없이 통과했습니다. 기존 이미지 최적화 및 React Hook 관련 경고만 남아 있으며 Sprint 9 변경으로 새 오류는 추가되지 않았습니다.

## 운영 전 설정

1. `SELLFORM_AUTH_MODE=production`으로 바꿉니다.
2. 충분히 긴 `SELLFORM_SESSION_SECRET`과 HTTPS 환경의 `SELLFORM_SESSION_COOKIE_SECURE=true`를 설정합니다.
3. `SELLFORM_PUBLIC_APP_URL`에는 프런트엔드 주소를, `SELLFORM_PUBLIC_API_URL`에는 백엔드 공개 주소를 넣습니다.
4. 각 OAuth 공급자에 `https://백엔드도메인/api/v1/auth/callback/{provider}`를 콜백 URI로 등록합니다.
5. Google·카카오·네이버 client ID/secret은 서버 환경 변수로만 주입하고 저장소에 넣지 않습니다.
