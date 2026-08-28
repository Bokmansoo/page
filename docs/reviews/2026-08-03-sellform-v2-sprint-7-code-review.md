# Sellform V2 Sprint 7 코드리뷰 — 채널별 출력

검토일: 2026-08-03  
기획서: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-7-channel-export.md`

## 결론

Sprint 7의 구현 범위(쿠팡·스마트스토어 프리셋, 마스터 기반 긴 이미지/분할 묶음, 브라우저 다운로드, 동일 최종본 재다운로드)를 구현했다. 공급처 이미지는 기존 자산 정책과 준비 상태 검사를 계속 통과해야 하므로 최종 출력에 새로 허용되지 않는다.

## 구현 확인

| 기획 항목 | 구현 | 근거 |
| --- | --- | --- |
| 하나의 마스터에서 두 채널 출력 | 완료 | `channel_export_service.py`가 캡처 마스터 한 장만 리사이즈·변환한다. |
| 교체 가능한 채널 프리셋/버전 | 완료 | 환경 변수 JSON 오버라이드와 `GET /api/v1/export/channel-presets`를 제공한다. |
| 안전한 섹션 경계 자동 분할 | 완료 | Playwright 섹션 스크린샷 높이를 기록하고, 가능한 마지막 경계에서 분할한다. |
| 긴 이미지·분할 묶음·섹션 ZIP | 완료 | 패키지 ZIP은 채널 긴 이미지, 연속 분할본, `sections-by-page.zip`, manifest를 포함한다. |
| 치수/형식/해시 기록 | 완료 | manifest에 프리셋/포맷/분할 좌표/마스터 SHA-256을 기록한다. |
| 최종 페이지 버전과 출력 연결 | 완료 | `ExportArtifact`에 `version_id`와 채널/포맷 타입을 저장한다. |
| 중복 실행 방지·즉시 재다운로드 | 완료 | 동일 final version+채널+포맷의 유효 아티팩트를 완료된 ExportJob으로 즉시 돌려준다. |
| 브라우저 다운로드 완료 표시 | 완료 | 표준 Blob 다운로드로 긴 이미지와 선택한 분할 ZIP이 Chrome 다운로드 목록에 각각 기록된다. |
| 실패 단계/재시도 가능 상태 | 완료 | 기존 ExportJob 실패 상태·오류 메시지를 유지하며 새 요청으로 재시도할 수 있다. Playwright Chromium 누락은 실행 전 안내한다. |

## 검증

- `backend/tests/test_v2_sprint7_channel_export.py`: 3 passed
  - 프리셋 버전 보유
  - 섹션 경계 우선 분할, 빈틈/중복 없음
  - 긴 이미지, 자동 분할 ZIP, manifest 생성
- `python -m py_compile backend/src/api/exports.py backend/src/services/channel_export_service.py backend/src/services/export_service.py`: 통과
- `npx.cmd eslint src/components/GeneratedDetailPageResult.tsx`: 오류 없음. 기존 `<img>` 최적화 경고 5건만 있음.
- `npx.cmd tsc --noEmit`: Sprint 7 파일과 무관한 기존 E2E fixture 타입 오류 2건으로 전체 타입 검사는 실패한다.

## 수동 확인 순서

1. 최종 상세페이지에서 **채널**을 `쿠팡` 또는 `네이버 스마트스토어`로 고른다.
2. PNG/JPG와 **자동 분할 묶음 함께 저장** 여부를 고른 뒤 다운로드한다.
3. Chrome 다운로드 목록에 긴 이미지와 ZIP(선택 시)이 모두 완료로 표시되는지 확인한다.
4. ZIP의 `manifest.json`에서 프리셋 버전, 마스터 해시, 분할 좌표를 확인한다.
5. 같은 프로젝트/최종본/채널/포맷으로 다시 다운로드하면 새 렌더 대기 없이 즉시 완료되는지 확인한다.

## 주의

- 실제 Playwright 캡처에는 Chromium이 필요하다. 없으면 백엔드에서 `uv run playwright install chromium`을 한 번 실행한다.
- 채널별 공식 제한값이 바뀌면 코드 변경 대신 `SELLFORM_CHANNEL_EXPORT_PRESETS_JSON` 설정을 바꾼다.
- 채널 계정 자동 업로드와 유료 다운로드 잠금은 기획 제외 범위이며 이후 Sprint에서 다룬다.
