# Sellform API-free Visual Sprint 0 코드리뷰

작성일: 2026-07-31  
검토 대상: Sprint 0 기준선 확보 및 JPG 출력 복구  
판정: 승인 — Sprint 0 완료, Sprint 1 착수 가능

## 1. 결론

Sprint 0 계획의 export 안정화와 기준선 확보 목표를 충족했다. Playwright Chromium 누락은
사용자에게 실행 명령으로 안내되고, 실패 작업은 출력 자산 없이 `failed` 상태로 남는다.
실제 로컬 서버에서 기준 상품 3종을 생성해 PNG/JPG로 내려받는 통합 경로도 확인했다.

증거: [Sprint 0 통합 검증 증거](../testing/2026-07-31-sellform-api-free-visual-sprint-0-integration-evidence.md)

## 2. 구현 확인

| 계획 항목 | 상태 | 확인 근거 |
| --- | --- | --- |
| Chromium 누락 실패 테스트 | 완료 | `test_export_service.py` |
| export 전 설치 상태 확인 | 완료 | `ensure_playwright_chromium_available()` |
| 해결 명령 표시 | 완료 | backend 단위 테스트와 frontend E2E |
| PNG/JPG 다운로드 | 완료 | 단위 테스트, E2E, 로컬 통합 3종 |
| 이미지·폰트 준비 대기 | 완료 | `waitForExportAssets()`와 export-ready 계약 |
| 실패 작업 성공 오기록 방지 | 완료 | API 회귀 테스트와 오류 처리 |
| 기준 상품 3종 결과 | 완료 | 프로젝트·작업 ID와 artifact 기록 |

## 3. 검증 결과

### 자동 검증

```text
backend: 15 passed
frontend export E2E: 1 passed
backend Playwright Chromium launch: OK
git diff --check: passed
```

### 로컬 통합 검증

- 미니 마사지건, 수분 크림, 밀폐용기 세트 각각 5개 섹션 생성
- 3개 프로젝트 모두 readiness `true`
- PNG 3건, JPG 3건 모두 export `completed`
- 다운로드 응답은 각 포맷의 올바른 MIME type을 반환
- JPG는 모두 760×1265이며 한글 상품명 렌더링을 직접 확인

## 4. 코드리뷰 발견 사항

### Blocker

없음.

### Important

없음.

### 후속 개선 항목

- PNG와 JPG를 각각 요청할 때마다 새 최종본 버전이 생긴다. 동일한 변경 내용으로 반복
  다운로드하면 버전 이력이 불필요하게 늘어날 수 있다.
- 일반 export 오류는 문자열로만 저장된다. 오류 코드를 분리하면 UI 분기와 운영 집계가
  쉬워진다.
- 외부 Google Fonts는 제한된 네트워크에서 E2E 시작을 지연시킬 수 있다. Sprint 6에서
  로컬 번들 폰트 전환을 검토한다.

## 5. 범위상 남아 있는 사항

다음은 Sprint 0 결함이 아니라 Sprint 1 이후의 범위다.

- 빨간 Mock 이미지 제거
- 실제 상품 사진 우선 연결
- 상품별 이미지 역할·품질 분류
- 자동 HERO 조합과 상세 비주얼 품질 개선

현재 통합 검증은 Mock 모드이므로, 생성·내보내기 안정성을 증명하지만 실제 상품 사진 품질을
증명하지는 않는다. Sprint 1은 이 기준 결과를 이용해 실제 이미지 우선 경로를 구현해야 한다.

## 6. 최종 의견

사용자가 겪은 `BrowserType.launch: Executable doesn't exist` 오류는 코드와 실행 가이드에서
해결됐다. Sprint 0은 완료로 판정하며, 다음 작업은 Sprint 1의 실제 상품 이미지 우선 연결이다.
