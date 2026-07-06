# 테스트 실행 로그: Sellform Sprint 15 Bulk Fact Input UX

- 날짜: 2026-06-24
- 목적: 일괄 사실 카드 등록 API 및 모달 UI의 완결성과 이미지 0개 프로젝트 하에서의 예외 상황 검증을 수행한다.

## 1. 백엔드 facts 테스트

```text
uv run --project backend pytest backend/tests/test_facts.py -q
결과:
............                                                             [100%]
12 passed, 134 warnings in 1.91s
```
- 추가된 일괄 중복 배제 테스트 케이스(`test_bulk_create_facts_deduplicates_existing_fact`)를 포함하여 사실 관련 12건의 테스트가 전원 통과(GREEN)하였습니다.

## 2. 전체 백엔드 회귀 테스트

```text
uv run --project backend pytest -q
결과:
62 passed, 454 warnings in 9.27s
```
- 전체 회귀 테스트 62건이 모두 정상 작동하여, 기존 기능의 영향도 없이 무결하게 스프린트 작업이 완료되었습니다.

## 3. 프론트 빌드

```text
npm.cmd run build (CWD: c:\page\frontend)
결과:
> frontend@0.1.0 build
> next build

  ▲ Next.js 14.2.35

   Creating an optimized production build ...
 ✓ Compiled successfully
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (9/9)
   Finalizing page optimization ...
   Collecting build traces ...
Route (app)                               Size     First Load JS
...
└ ○ /workspace/settings                   4.73 kB          92 kB
```
- 타입스크립트 type check 및 eslint 검사 단계를 에러 없이 무사히 완수하고 성공적으로 번들이 생성되었습니다.

## 4. 수동 QA 시나리오 검증

- **일괄 추가 모달 파서 검증**: Textarea에 `사실 | 근거: 근거` 형태로 입력 시 각 줄을 바르게 분리하여 백엔드로 전송하고, 구분자가 없는 줄은 사실 문장을 근거 텍스트로 복사하여 안정적으로 DB에 저장함을 확인했습니다.
- **중복 판단 및 결과 리포트**: 동일한 팩트가 존재할 경우 신규 생성을 제외하고 `생성 2개, 중복 1개` 등의 얼럿 메시지가 직관적으로 보고되는 것을 파악했습니다.
- **이미지 부재 시 UX**: 프로젝트 내 업로드 에셋이 0개일 때, 수동 폼 및 수정 폼 내 관련 이미지 선택 드롭다운이 `disabled` 처리되며 "업로드된 이미지가 없습니다. 상품 이미지 업로드 후 선택할 수 있습니다." 경고 플레이스홀더를 제공하는 것을 검증했습니다.
- **무임팩트 저장**: 이미지를 선택하지 않거나 없는 상태로 "사실 카드 저장"을 눌러도 HTTP 201 응답과 함께 카드 생성이 정상 작동함을 검토했습니다.

## 5. 판단
- E2E 무결성이 확보되었으며 완료 기준을 모두 충족하므로 본 테스트 로그를 통과(PASS)로 확정합니다.

## 6. 보완 검증 - 2026-06-24

Sprint 15 코드리뷰 후 완료 기준을 더 명확히 하기 위해 bulk facts API edge case 테스트를 추가로 보강했습니다.

### 추가 테스트 케이스

- `test_bulk_create_facts_rejects_empty_items`
  - 일괄 입력 항목이 0개일 때 `400 Bad Request`를 반환하는지 검증.
- `test_bulk_create_facts_rejects_more_than_fifty_items`
  - 51개 입력 시 1회 최대 50개 제한이 적용되는지 검증.
- `test_bulk_create_facts_counts_blank_fact_as_failed`
  - 공백 `fact_text`는 생성하지 않고 `failed_count`로 집계하는지 검증.
- `test_bulk_create_facts_uses_fact_text_as_source_when_source_is_blank`
  - `source_text`가 비어 있으면 `fact_text`를 근거 텍스트로 fallback하는지 검증.

### 실행 명령 및 결과

```text
uv run --project backend pytest backend/tests/test_facts.py -q
결과:
................                                                         [100%]
16 passed, 152 warnings in 1.48s
```

### 판정

- Sprint 15 핵심 기능과 edge case 검증이 모두 통과했습니다.
- 경고는 기존 FastAPI/TestClient, Pydantic v2 deprecation, `datetime.utcnow` 관련 경고이며 이번 Sprint 15 보완으로 새로 발생한 실패는 없습니다.
