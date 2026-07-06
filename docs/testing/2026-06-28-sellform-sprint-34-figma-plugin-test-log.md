# Sprint 34 Figma Plugin 보완 테스트 로그

## 범위

- 일회용 티켓 응답과 플러그인 패키지 계약
- 비밀키 fail-closed, 40bit 이상 코드 entropy, 재사용 차단
- 잘못된 코드 5분당 10회 제한
- Base64 포함 실제 JSON 패키지 20MB 제한
- canonical 7단 검증
- 860px Figma Auto Layout, 여백, 이미지 placeholder, 폰트 fallback
- Sellform의 플러그인 우선 내보내기 UI

## TDD RED 증적

| 검증 | RED 결과 |
| --- | --- |
| 백엔드 보완 테스트 | 4 failed, 7 passed |
| 코드 entropy | 1 failed |
| canonical 7단 API | 1 failed |
| 플러그인 계약·렌더러 | 5 failed, 5 passed |
| 프론트 E2E | 1 failed |

실패 원인은 각각 최상위 schema version 누락, 고정 fallback secret,
rate limit 부재, Base64 이후 크기 미검증, 31문자 alphabet, 7단 미검증,
24px 여백, 폰트 fallback 부재, Remote MCP 기본 UI였다.

## GREEN 증적

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_figma_plugin_ticket_service.py tests/test_figma_plugin_api.py -q` | 13 passed |
| `uv run pytest tests -q` | 165 passed |
| `npm.cmd test` (`integrations/figma-plugin`) | 12 passed |
| `npm.cmd run build` (`integrations/figma-plugin`) | PASS |
| `npm.cmd run build` (`frontend`) | PASS, 기존 `<img>` LCP 경고 1건 |
| `npx.cmd playwright test e2e/sprint34-figma-plugin-export.spec.ts` | 1 passed |

마지막 E2E 재실행 요청은 실행 도구 사용 한도로 승인되지 않았다. 동일 변경
상태에서 앞선 E2E가 통과했고 이후 프론트 코드는 변경하지 않았으며 production
build를 다시 통과했다.

## 수동 검수

실제 Figma Desktop에서 코드 입력 후 생성되는 860px·7단 프레임 검수는
로컬 plugin ID 등록이 필요한 수동 단계다. 실행 후 아래를 첨부한다.

- [ ] Figma 캔버스 전체 스크린샷
- [ ] 7개 섹션 Layers 패널
- [ ] TextNode 직접 수정
- [ ] Image Fill 확인
- [ ] 동일 코드 재사용 거절
- [ ] JSON fallback 동일 구조 확인
