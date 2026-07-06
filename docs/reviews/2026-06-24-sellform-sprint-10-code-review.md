# 코드 리뷰: Sellform Sprint 10 (AI 사실 카드 자동 추출)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | 자동 사실 추출 API, deterministic fact extractor, source collector, ProductFact 메타데이터, 사실 확인 보드 UI |
| 리뷰어 | Codex |
| 상태 | **조건부 승인 (Conditionally Approved)** |

## 1. 변경 요약

- `POST /api/v1/projects/{project_id}/facts/auto-extract` API 추가.
- 프로젝트의 수동 입력 텍스트, 업로드 이미지 자산, URL 존재 여부를 분석 입력으로 묶는 source collector 추가.
- 외부 AI/URL 크롤링에 의존하지 않는 deterministic fact extractor 1차 구현.
- 자동 생성 후보에 다음 메타데이터를 저장:
  - `extraction_source`
  - `confidence`
  - `needs_review`
  - `risk_flags`
- 자동 생성된 사실은 기본 `unknown` 또는 `needs_revision` 상태로 저장.
- 동일 사실 후보 중복 저장 방지.
- 기존 SQLite 개발 DB에 새 컬럼이 없을 때 시작 시 보정하는 호환 레이어 추가.
- 사실 확인 보드에 `AI로 사실 카드 자동 생성` 버튼, 결과 요약, 출처/신뢰도/위험 플래그 배지 추가.

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| 수동 텍스트에서 5개 이상 사실 후보 자동 생성 | 충족 | `backend/tests/test_facts.py` |
| 이미지 근거가 연결된 사실 후보 생성 | 충족 | `test_auto_extract_creates_image_asset_candidate` |
| URL 수집 실패 시 흐름 중단 없음 | 충족 | URL fallback 응답 |
| 자동 후보는 확인 전 상세페이지에 사용되지 않음 | 충족 | 기존 confirmed-only 페이지 생성 규칙 유지 |
| 프론트 버튼/결과 표시 | 충족 | facts page UI 및 `npm.cmd run build` |
| 실제 URL 직접 수집 | 제외/이관 | 정책·보안 리스크로 deferred 처리 |
| 실제 멀티모달 이미지 OCR/분석 | 부분 충족 | 이미지 자산 연결은 구현, 이미지 내용 분석은 후속 |

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 🟡 M1. 현재 fact extractor는 deterministic 1차 버전

- 위치: `backend/src/services/fact_extractor.py`
- 내용: 현재 구현은 외부 LLM 호출 없이 알려진 패턴 기반으로 사실 후보를 생성한다.
- 영향: 안정적이고 테스트 가능하지만, 다양한 공급처 문장/중국어/이미지 내 문구를 완전히 커버하지 못한다.
- 판단: Sprint 10 1차 구현으로는 적절하다. 실제 LLM/멀티모달 고도화는 별도 후속 작업으로 분리한다.

### 🟡 M2. URL 직접 수집은 deferred

- 위치: `backend/src/services/source_collector.py`
- 내용: URL이 있어도 직접 크롤링하지 않고 fallback 메시지를 반환한다.
- 영향: 공급처 링크만 넣었을 때 자동 추출 품질은 제한된다.
- 판단: 캡차, 로그인, 약관, SSRF, timeout 위험을 고려하면 안전한 1차 범위다.

### ⚪ N1. 기존 facts 페이지의 일부 한글 문자열 인코딩이 깨져 있음

- 위치: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`
- 내용: Sprint 10에서 추가한 문자열은 정상이나, 기존 페이지 일부 텍스트는 깨진 상태가 남아 있다.
- 영향: 기능에는 영향 없고 빌드는 통과하지만, 사용자 경험에는 좋지 않다.
- 권고: 별도 UI 문구 정리 스프린트 또는 보완 작업에서 정리한다.

## 4. 테스트 증적

```text
uv run --project backend pytest backend/tests/test_facts.py -q
10 passed, 109 warnings in 1.16s
```

```text
uv run --project backend pytest -q
54 passed, 415 warnings in 8.34s
```

```text
cd frontend
npm.cmd run build
Compiled successfully
Generating static pages (9/9)
```

## 5. 결론

Sprint 10은 핵심 목표였던 “AI가 먼저 사실 카드 후보를 만들고, 사용자는 검수하는 흐름”을 1차 구현했다.

다만 현재 버전은 실제 URL 크롤링/멀티모달 OCR까지 들어간 완성형 AI 추출기가 아니라, 안전한 deterministic extractor와 수동 입력/이미지 자산 기반 자동 후보 생성이다. 따라서 판정은 **조건부 승인**으로 둔다.

다음 고도화 후보:

1. 공급처 URL 직접 수집을 위한 안전한 fetch/정책 게이트.
2. OCR 또는 멀티모달 모델을 통한 이미지 내 텍스트·스펙 추출.
3. 중국어/영어 공급처 문장 번역과 사실 후보 생성 품질 개선.
4. 기존 facts 페이지의 깨진 한글 UI 문구 정리.

