# V2 Sprint 8 코드리뷰 — 브라우저 확장 프로그램 기반 상품 자료 수집

검토 기준: [Sprint 8 기획](../superpowers/plans/2026-08-01-sellform-v2-sprint-8-browser-extension-capture.md)

## 결론

Sprint 8의 범위인 **권한 최소화, 판매자 클릭 기반 현재 탭 수집, 일회용 연결 코드, 워크스페이스 경계, 실제 참고 파일 저장 및 감사 기록**을 구현했습니다. 이 기능은 사이트 접근 제한을 해제하거나 공급처 원본을 최종 상세페이지에 쓰는 기능이 아닙니다.

## 구현 확인

| 기획 항목 | 상태 | 구현 위치 |
| --- | --- | --- |
| 현재 탭·사용자 선택 자료만 수집 | 완료 | `browser-extension/manifest.json`, `popup.js` |
| 최소 권한(`activeTab`, `scripting`, `storage`) 및 선택 이미지 도메인의 런타임 권한 | 완료 | `browser-extension/manifest.json` |
| 1688·타오바오·샤오홍슈·쿠팡·스마트스토어 선택자 어댑터 + 공통 폴백 | 완료 | `browser-extension/popup.js` |
| 실패 시 클릭으로 DOM 영역 선택 + 현재 화면 스크린샷 | 완료 | `browser-extension/popup.js` |
| 사이트 제한/CAPTCHA/로그인 우회 금지 | 완료 | 확장 프로그램 UI, API 정책·가이드 |
| 연결 코드 발급·교환·만료·재사용 차단 | 완료 | `backend/src/api/browser_extension.py` |
| 프로젝트 목록을 연결 워크스페이스로 제한 | 완료 | `GET /browser-extension/projects`, 제출 시 워크스페이스 조회 |
| URL·제목·언어·선택 텍스트·선택 HTML·항목별 문서 순서 수집 | 완료 | `ExtensionCapturePayload`, `popup.js` |
| 선택 이미지 실제 바이트 및 화면 스크린샷 저장 | 완료 | `CapturedImageBlob`, `_store_capture_asset`, `popup.js` |
| MIME·실제 이미지 형식·용량·픽셀·HTML 안전성 검증 | 완료 | `_decode_image_blob`, `_sanitize_selected_html` |
| 이미지 SHA-256 중복 병합 | 완료 | `_store_capture_asset` |
| 토큰 회전·전체 기기 연결 해제 | 완료 | `POST /tokens/rotate`, `DELETE /connections` |
| 쿠키·세션·비밀번호·결제/연락처/주문 정보 차단 | 완료 | `SENSITIVE_PATTERNS`, preview 검증 |
| 공급처 자료 `reference_only` 저장 | 완료 | `BrowserExtensionCapture`, `SourceCapture`, `intake_snapshot` |
| 연결 해제와 감사 로그 | 완료 | `DELETE /connections/{id}`, `AuditLog` |
| 로컬 설치·사용 안내 | 완료 | `docs/guides/2026-08-04-sellform-v2-browser-extension-capture-guide.md` |

## 자동 검증

다음 테스트를 실행했습니다.

```powershell
Set-Location C:\page\backend
uv run pytest tests/test_v2_sprint8_browser_extension_capture.py -q
```

결과: **4 passed**

테스트는 사이트 어댑터 계약, 정상 발급→교환→실제 파일 저장→`reference_only` 저장, 이미지 해시 중복 병합, 토큰 회전·만료·전체 연결 해제, URL 단독 전송 거부, MIME 위조·대용량·악성 HTML 거부를 검증합니다.

프론트엔드 전체 `npm.cmd run build`는 이번 변경과 무관하게 기존 `next/font`의 Google Fonts 다운로드가 로컬 네트워크 정책(EACCES)으로 차단되어 완료하지 못했습니다. `npx.cmd tsc --noEmit` 역시 기존 `e2e/upload-ready-golden-path.spec.ts`의 타입 오류 두 건으로 실패했으며, Sprint 8 페이지 파일에서 발생한 타입 오류는 확인되지 않았습니다.

## 수동 확인 항목

1. `chrome://extensions`에서 `C:\page\browser-extension` 폴더를 로드합니다.
2. `/workspace/browser-capture`에서 코드를 발급하고 확장 프로그램을 연결합니다.
3. 상품 탭에서 텍스트·문서 항목·필요 이미지 후보만 체크하고, 이미지 주소가 막히면 현재 화면 스크린샷을 포함해 프로젝트로 보냅니다.
4. 프로젝트의 사실·증거 보드에서 수집 자료가 참고용으로 남는지 확인합니다.

## 의도적으로 Sprint 8에 포함하지 않은 것

- 사이트 접근 제한·CAPTCHA·로그인 벽 우회
- 쿠키/세션/계정 데이터 수집
- 공급처 원본을 최종 판매 이미지로 바로 사용
- AI가 실제 새 리디자인 이미지를 생성하는 실행(이미지 생성 API와 후속 Sprint 범위)
