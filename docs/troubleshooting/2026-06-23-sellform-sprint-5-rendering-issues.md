# 트러블슈팅: Sellform Sprint 5 렌더링/Export 보완

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | Sprint 5 Export 패키징, 마켓 프리셋, 프론트엔드 Export 화면 |
| 관련 리뷰 | `docs/reviews/2026-06-23-sellform-sprint-5-remediation-code-review.md` |

## 1. 증상

Sprint 5 구현 후 검증 과정에서 백엔드 Export API 단위 테스트는 개별 실행 기준으로 통과했지만, 프론트엔드 빌드가 실패했다.

주요 오류는 `frontend/src/app/workspace/projects/[id]/export/page.tsx`에서 발생했다.

- JSX 태그가 깨져 `Unexpected token div` 파싱 오류 발생
- `handleDownload` 함수 선언부가 주석 처리된 상태로 남아 버튼 이벤트에서 참조 불가
- mock 데이터 문자열의 따옴표가 escape되지 않아 TypeScript 구문 오류 발생
- `slice_{idx+1:02d}.png`처럼 Python 포맷 문법이 JSX 안에 남아 있음

## 2. 원인

Export 화면 TSX 파일에 일부 깨진 문자열과 잘못된 JSX가 섞여 있었다.

특히 한국어/특수문자 표시가 깨진 상태에서 JSX 닫는 태그와 문자열 리터럴이 손상되었고, Python 스타일 포맷 문자열이 TypeScript 코드에 남아 있었다. 이 때문에 Next.js 빌드 단계의 TypeScript/JSX 파서가 파일을 정상적으로 해석하지 못했다.

## 3. 조치

- Export 화면 파일을 정상적인 TypeScript React 컴포넌트로 재작성했다.
- mock compliance 데이터, export job 이력, preset 선택, export 시작, 상태 polling, ZIP 다운로드 흐름을 명확히 분리했다.
- 깨진 JSX 태그와 잘못된 문자열 포맷을 제거했다.
- 사용자에게 보이는 한국어 문구를 정상 문자열로 정리했다.
- Sprint 5 보완 리뷰 문서와 테스트 로그를 별도로 남겼다.

## 4. 추가 발견: 병렬 pytest 실행 시 SQLite 충돌

초기 검증에서 `tests/test_exports.py`와 전체 pytest를 동시에 실행했을 때 `test_temp.db` 공유로 인해 `no such table: assets`, `no such table: brands` 오류가 발생했다.

개별 순차 실행에서는 다음 테스트가 정상 통과했다.

- `uv run --project . pytest tests/test_exports.py -q`
- `uv run --project . pytest -q`

따라서 Sprint 5 기능 결함이라기보다는 테스트 실행 방식의 격리 문제로 판단했다. 향후 병렬 테스트를 공식 지원하려면 worker별 임시 DB 경로를 분리하는 보완이 필요하다.

## 5. 검증 결과

| 검증 | 결과 |
| --- | --- |
| Export API 테스트 | `2 passed, 18 warnings` |
| 백엔드 전체 테스트 | `42 passed, 139 warnings` |
| 프론트엔드 빌드 | `Compiled successfully` |

## 6. 남은 위험

- `RENDERER_MOCK=true` 기반 fallback 렌더링과 실제 Playwright 렌더링 결과의 시각적 차이는 추가 QA가 필요하다.
- 쿠팡/스마트스토어 이미지 규격 값은 현재 구현 기준으로 반영했지만, 운영 적용 전 공식 최신 정책 재확인이 필요하다.
- 병렬 테스트를 안정화하려면 테스트 DB 격리 전략을 별도 Sprint에서 정리하는 것이 좋다.
