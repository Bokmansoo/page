# 코드 리뷰: Sellform Sprint 32 보완

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-28 |
| 리뷰 범위 | Figma export workspace 권한, 보안 정책 문서, Playwright 실행 격리, 전체 회귀 |
| 결론 | 승인 |

## 1. 변경 요약

- 다른 workspace의 프로젝트를 Figma payload로 내보낼 수 없는 회귀 테스트를 추가했다.
- 실제 payload 계약에 맞게 Figma 보안 결정 문서를 수정했다.
- 개발 서버 3000번과 Playwright의 포트 충돌을 제거하기 위해 E2E 기본 포트를 3100번으로 분리했다.
- 기존 Sprint 32 테스트·리뷰·트러블슈팅 문서를 최신 증적으로 갱신했다.

## 2. 이슈와 조치

### 🟠 M1. workspace 경계의 전용 회귀 테스트 부재

- 위치: `backend/tests/test_figma_export_api.py`
- 영향: API 구현이 변경될 때 다른 workspace의 Figma payload 접근 차단이 회귀할 수 있었다.
- 조치: 다른 workspace 컨텍스트에서 요청할 때 `404 Project not found`를 검증하는 테스트를 추가했다.
- 상태: 조치 완료.

### 🟡 M2. 보안 문서가 실제 payload보다 강하게 표현됨

- 위치: `docs/decisions/2026-06-27-sellform-figma-mcp-integration-strategy.md`
- 영향: 문서는 모든 내부 UUID를 제외한다고 했지만 실제 payload에는 원본 매핑용 `project.id`, `section_id`가 포함되어 정책과 구현이 불일치했다.
- 조치: 사용자·workspace·API key·결제·추적 정보는 제외하고, 매핑에 필요한 프로젝트·섹션 식별자는 포함한다고 명확히 했다.
- 상태: 조치 완료.

### 🟡 M3. Playwright와 개발 서버의 3000번 포트 충돌

- 위치: `frontend/playwright.config.ts`
- 영향: 개발 서버가 실행 중이면 E2E webServer가 시작되지 못하고 120초 후 타임아웃됐다.
- 조치: E2E 기본 포트를 3100번으로 분리하고 `SELLFORM_E2E_PORT` 환경변수 재정의를 지원했다.
- 상태: 조치 완료.

## 3. 테스트 증적

```text
workspace 권한 테스트: 3 passed
백엔드 전체: 138 passed
프론트 프로덕션 빌드: 성공
Sprint 32 Playwright: 1 passed
```

## 4. 남은 위험

- Sprint 32는 계획대로 payload 생성과 선택형 adapter까지만 제공한다. 실제 Figma 캔버스 쓰기는 Sprint 33 범위다.
- 운영 이미지가 Figma에서 보이려면 `SELLFORM_PUBLIC_ASSET_BASE_URL`이 외부 접근 가능한 HTTPS 주소여야 한다.
- Next.js `<img>` 성능 경고 1건은 기능을 막지 않지만 후속 최적화가 필요하다.

