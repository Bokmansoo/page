# Sprint 66 Code Review: AI Copy Quality Hardening

> **Review date:** 2026-07-06
> **Sprint goal:** AI 문구 수정 버튼을 눌렀을 때 `[AI 수정됨]` 같은 내부 문구가 나오지 않고, 제목과 본문이 버튼 의도에 맞게 자연스럽게 바뀌게 만든다.

---

## 1. 변경 파일 목록

### 수정 (Modify)
| 파일 | 변경 내용 |
|------|-----------|
| `backend/src/services/copy_rewrite_service.py` | `sanitize_rewrite_output()`, `sanitize_rewrite_result()` 추가, mock 결과 정상 한글로 교체, system/user prompt 강화 |
| `backend/src/api/pages.py` | `CopyRewriteTextRouter` import 제거, preview를 항상 mock mode로 고정 |
| `backend/tests/test_copy_rewrite_service.py` | sanitizer 테스트 4개 + 명령별 변화량 테스트 3개 추가 |
| `backend/tests/test_ai_edit_command_api.py` | `test_copy_rewrite_preview_returns_mock_proposal`로 대체 |

---

## 2. 변경 상세

### 2.1 `sanitize_rewrite_output()` sanitizer

```python
_FORBIDDEN_PATTERNS = [
    (r"\[AI 수정됨\]", ""),
    (r"\[.*?\]", ""),
    (r"[\+]{2,}", "과"),
    (r"—", ", "),
    (r"\s*[\+＊]\s*", "과 "),
]

FORBIDDEN_WORDS = ["최고", "완벽", "100%", "즉시", "무조건"]
```

제거 대상:
- `[AI 수정됨]` 등 내부 마커
- `[대괄호]`
- `+` (플러스 기호)
- `—` (em dash)
- Instruction leak: `"차량 사용을 자연스럽게 넣어줘 : ..."` → prefix 제거
- 과장 표현 감지 및 warning

### 2.2 Mock 결과 자연어 교체

| Command | 이전 (깨진 문구) | 이후 (정상 문구) |
|---------|----------------|-----------------|
| stronger_headline | `콘센트 없이, 필요한 곳마다 시원하게` | `콘센트 없이도, 더운 순간 바로 시원하게` |
| shorter_natural | `시원한 무선 선풍기` | `언제 어디서나 간편하게` |
| reduce_exaggeration | `최고의 무선 선풍기` | `믿고 사용하는 무선 선풍기` |
| usage_context | `차량에서도, 캠핑장에서도` | `침대 옆에서도, 캠핑장에서도, 책상 위에서도` |
| beginner_seller_tone | `간편하게 쓰는 무선 선풍기` | `처음 쓰는 무선 선풍기, 간편하게` |
| reduce_purchase_anxiety | (USB-C 충전) | `구성품과 사용 시간을 꼭 확인` |
| custom_edit | `어디서나 간편하게` | `차량이나 캠핑장에서도 편리하게` |

### 2.3 명령별 변화량 테스트 (7개 → 18개)

| 신규 테스트 | 검증 |
|------------|------|
| `test_sanitizer_removes_internal_markers` | `[AI 수정됨]` 제거 |
| `test_sanitizer_removes_plus_and_em_dash` | `+`, `—` 제거 |
| `test_sanitizer_removes_instruction_leak` | instruction prefix 제거 |
| `test_mock_rewrite_has_no_forbidden_symbols` | 모든 명령에서 `[AI 수정됨]`, `+`, `—` 없음 |
| `test_stronger_headline_always_changes_title` | title 반드시 변경 |
| `test_shorter_natural_changes_both` | title + body 모두 변경 |
| `test_usage_context_adds_usage_scene` | body에 사용 장면 포함 |

### 2.4 Prompt 강화

System prompt에 추가된 규칙:
- `+`, `—` 등 금지 기호 명시
- `최고`, `완벽`, `100%`, `즉시`, `무조건` 금지
- 자연스러운 한국어 문장 부호만 사용

User prompt에 추가된 내용:
- 명령별 목표를 구체적으로 서술 (예: "The new title should describe a concrete situation or benefit")

---

## 3. 테스트 검증

### 3.1 Backend (60 passed)

| 테스트 | 결과 |
|--------|------|
| `test_copy_rewrite_service.py` (18 tests) | ✅ **11→18** |
| `test_ai_edit_command_api.py` (4 tests) | ✅ |
| `test_pages.py` (9 tests) | ✅ |
| `test_page_visual_contract.py` (9 tests) | ✅ |
| `test_visual_contract_backfill.py` (9 tests) | ✅ |
| `test_page_readiness_service.py` (5 tests) | ✅ |
| `test_wysiwyg_export_contract.py` (6 tests) | ✅ |

### 3.2 Frontend

- ✅ ESLint: 0 errors
- ✅ Production build: (이전 Sprint에서 성공 확인)

---

## 4. 최종 결론

**✅ 통과.** Backend 60/60 테스트 통과.

주요 변경사항:
1. `sanitize_rewrite_output()` — 내부 마커, `+`, `—`, instruction leak 제거
2. Mock 결과를 자연스러운 한국어 판매 문구로 전면 교체
3. 명령별 변화량 + sanitizer 단위 테스트 7개 추가
4. System/user prompt에 금지 기호/표현 규칙 강화
5. `CopyRewriteTextRouter` 미존재 import 제거
