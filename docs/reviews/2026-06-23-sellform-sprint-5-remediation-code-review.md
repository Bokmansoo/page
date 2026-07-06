# 코드 리뷰: Sellform Sprint 5 Remediation

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-23 |
| 리뷰 범위 | Sprint 5 검수·이미지형 판매처 출력 보완, export 프론트 빌드 오류 수정, 테스트 재검증 |
| 결론 | 승인 가능 |

## 1. 보완 전 발견 이슈

### 🔴 B1. Export 프론트 페이지 JSX 문법 오류

- 위치: `frontend/src/app/workspace/projects/[id]/export/page.tsx`
- 증상: `npm.cmd run build` 실행 시 `Unexpected token div. Expected jsx identifier` 오류가 발생했다.
- 원인: 한글 인코딩이 깨진 텍스트가 JSX 태그처럼 남아 있었고, `handleDownload` 함수 선언이 주석에 붙어 파싱되지 않았다. 또한 mock 문구 안의 작은따옴표와 `slice_{idx+1:02d}` 형태의 Python식 포맷 문자열이 TSX 파서를 깨뜨렸다.
- 조치: export 페이지를 깨끗한 TSX로 재작성했다. 기존 기능인 compliance 조회, export job 생성, polling, ZIP 다운로드, export history, preset 선택은 유지했다.

### 🟡 M1. 병렬 테스트 실행 시 SQLite `test_temp.db` 충돌

- 위치: 테스트 실행 환경
- 증상: `test_exports.py`와 전체 pytest를 병렬로 실행했을 때 `no such table: assets`, `no such table: brands` 오류가 발생했다.
- 원인: 두 pytest 프로세스가 같은 SQLite 테스트 파일을 동시에 생성/삭제했다.
- 조치: 테스트 검증은 순차 실행 기준으로 확정했다. 단독 `test_exports.py`와 전체 pytest 순차 실행은 모두 통과했다.

## 2. 최종 검증 결과

```bash
cd backend
uv run --project . pytest tests/test_exports.py -q
# 2 passed, 18 warnings
```

```bash
cd backend
uv run --project . pytest -q
# 42 passed, 139 warnings
```

```bash
cd frontend
npm.cmd run build
# Compiled successfully
# Linting and checking validity of types passed
```

## 3. Sprint 5 기획서 대비 판단

| 기획 항목 | 상태 |
| --- | --- |
| `ExportJob` 모델 | 충족 |
| compliance 검사 API | 충족 |
| Blocker 존재 시 export 차단 | 충족 |
| 비동기 export job 생성 | 충족 |
| renderer 기반 이미지 슬라이싱 및 ZIP 생성 | 충족 |
| export job 상태 조회 | 충족 |
| export job 목록 조회 | 충족 |
| ZIP 다운로드 API | 충족 |
| 프론트 export 작업대 | 충족 |

## 4. 남은 위험

- 현재 테스트는 `RENDERER_MOCK=true` 기반 fallback renderer를 중심으로 검증한다. 실제 Playwright Chromium 렌더링은 배포 환경에서 별도 smoke test가 필요하다.
- 판매처별 공식 이미지 규격은 Sprint 0 문서에서 “직접 검증 필요”로 남아 있다. 현재 preset 값은 구현 가설이며, 실제 판매처 정책 원문 확인 후 확정해야 한다.
- 기존 deprecation warning은 별도 리팩터링 Sprint에서 정리한다.
