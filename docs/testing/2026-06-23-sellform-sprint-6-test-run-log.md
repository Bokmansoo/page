# 테스트 로그: Sellform Sprint 6

| 항목 | 내용 |
| --- | --- |
| 일자 | 2026-06-23 |
| 범위 | 웹형 공개 페이지 발행, 공개 조회, 이미지 갤러리, 재발행, 프론트 빌드 |

## 1. Sprint 6 단위 테스트

```bash
cd backend
uv run --project . pytest tests/test_publications.py -q
```

결과:

```text
2 passed, 26 warnings
```

검증 내용:

- 공개 페이지 발행
- 비인증 공개 조회
- slug 기반 조회
- 비공개 전환 시 403 차단
- `external_store_url`, `show_faq`, `video_url` 응답 포함
- Before/After 이미지 자산 포함
- 갤러리용 프로젝트 이미지 자산 포함
- 재발행 시 기존 발행 레코드 갱신 및 공개 상태 복구

## 2. 백엔드 전체 회귀 테스트

```bash
cd backend
uv run --project . pytest -q
```

결과:

```text
44 passed, 159 warnings
```

주의:

- 병렬 pytest 실행 시 `test_temp.db` 공유 충돌 가능성이 있으므로 현재 공식 검증은 순차 실행 기준이다.

## 3. 프론트엔드 빌드

```bash
cd frontend
npm.cmd run build
```

결과:

```text
Compiled successfully
```

검증 내용:

- `/p/[id]` 공개 페이지 빌드
- `/workspace/projects/[id]/publish` 발행 관리 화면 빌드
- TypeScript/lint 검증 통과

## 4. 수동 QA 체크리스트

- [x] 공개 페이지가 모바일 최대 폭 480px 기준으로 표시되도록 구성됨
- [x] 이미지 갤러리 dot indicator 제공
- [x] 이미지가 없을 때 텍스트 fallback 제공
- [x] FAQ 버튼에 `aria-expanded` 적용
- [x] Before/After 슬라이더에 접근성 label 적용
- [x] 구매 링크가 없을 때 버튼 비활성 상태 제공
- [x] 구매 링크가 있을 때 새 창으로 이동하도록 구현
