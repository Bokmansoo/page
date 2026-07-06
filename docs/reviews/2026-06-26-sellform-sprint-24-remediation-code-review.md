# 코드 리뷰: Sellform Sprint 24 보완 작업

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-26 |
| 리뷰 범위 | 브라우저 보조 수집 파서 일관화, 후보 품질 필터, 근거 저장 보강, UI 안내 강화 |
| 관련 스프린트 | Sprint 24 - Browser Assisted URL Collection |
| 리뷰어 | Codex |

## 1. 변경 요약

- 프론트엔드의 임시 줄 단위 파싱을 백엔드 `/api/v1/projects/{project_id}/facts/bulk/parse` API 기반 파싱으로 변경했다.
- `bulk_fact_parser.py`에서 숫자 불릿 제거 정규식을 보정하고, 배송/리뷰/광고성 문장 등 일반 커머스 노이즈를 제외하도록 보강했다.
- 파싱 API 응답에 `candidate_count`, `excluded_count`, 후보별 `source_text`를 포함해 후보 품질과 근거 추적성을 높였다.
- 후보별 `source_text`에는 전체 붙여넣기 원문과 추출 후보 라인을 함께 저장하도록 했다.
- `BrowserAssistedSourcePanel`에 복사하면 좋은 정보 예시와 제외될 수 있는 문장 안내를 추가했다.

## 2. 확인 결과

### ✅ R1. 프론트/백엔드 파싱 기준 통일

- 위치:
  - `backend/src/api/facts.py`
  - `backend/src/services/bulk_fact_parser.py`
  - `frontend/src/components/BrowserAssistedSourcePanel.tsx`
- 결과: 프론트는 더 이상 자체 줄 단위 파싱만 사용하지 않고, 백엔드 파싱 API를 호출해 후보를 생성한다.

### ✅ R2. 후보 품질 필터 보강

- 위치: `backend/src/services/bulk_fact_parser.py`
- 결과: `무료배송`, `구매후기`, `리뷰`, `쿠팡 추천`, `광고` 등 상세페이지 사실 카드로 쓰기 약한 문장을 제외한다.

### ✅ R3. 근거 추적성 보강

- 위치: `backend/src/api/facts.py`
- 결과: 후보별 근거에 전체 붙여넣기 원문과 추출 후보 라인이 함께 저장된다.

### ✅ R4. 사용자 안내 강화

- 위치: `frontend/src/components/BrowserAssistedSourcePanel.tsx`
- 결과: 사용자는 어떤 정보를 복사해야 하는지, 어떤 줄이 제외될 수 있는지 더 명확히 알 수 있다.

## 3. 테스트 증적

```text
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_bulk_fact_parser.py backend\tests\test_facts.py -q
24 passed
```

```text
cd frontend
npm.cmd run build
Compiled successfully
```

## 4. 남은 리스크

- 현재 노이즈 필터는 deterministic keyword 기반이므로, 실제 쇼핑몰 문구가 다양해질수록 필터 단어를 보강해야 한다.
- 후보 품질 판단은 아직 의미 기반 LLM 분류가 아니라 규칙 기반이다. 다만 Sprint 24의 안전하고 빠른 보조 수집 목적에는 적합하다.

## 5. 결론

Sprint 24는 기존 완료 기준을 충족한 상태에서, 보완 작업을 통해 파싱 일관성, 후보 품질, 근거 추적성, 사용자 안내가 모두 개선되었다. 다음 단계인 Sprint 25로 넘어가도 된다.
