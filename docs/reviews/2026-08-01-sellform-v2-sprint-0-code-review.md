# Sellform V2 Sprint 0 코드리뷰

- 검토 기준: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-0-baseline-and-policy.md`
- 재검토일: 2026-08-01
- 결론: **Sprint 0 구현 계약 충족**

## 1. 재검토에서 발견하고 보완한 사항

| 발견 사항 | 위험 | 보완 결과 |
| --- | --- | --- |
| 일부 조회 경로가 과거 `confirmed` 값만 인정 | `source_confirmed`, `seller_confirmed` 사실이 상세페이지 구성에서 누락될 수 있음 | 모든 ProductFact 조회·구성 경로가 V2 승인 상태 집합을 사용하도록 통일 |
| Facts API가 과거 상태값 입력을 허용 | 코드·DB·API 계약 불일치 | API 쓰기는 V2 6개 상태만 허용하고, 과거 값은 DB 시작 마이그레이션과 읽기 호환에서만 처리 |
| 미확인 수치·충돌 사실이 경고로만 남음 | JPG/PNG 내보내기에 근거 없는 성능·수치가 노출될 수 있음 | readiness blocker로 승격하고 연결 사실 상태까지 검사 |
| 최종 스펙 섹션이 없는 페이지가 통과 가능 | 상세 스펙을 맨 마지막에 둔다는 정책 미보장 | 최종 스펙/고지 섹션 부재와 마지막 순서 위반을 모두 차단 |
| 공급처 중국어 배너 OCR이 최종 이미지에 남을 수 있음 | 공급처 원본 디자인·카피 재사용 위험 | 중국어 OCR이 남은 최종 이미지 후보를 차단 |
| 자산 상태가 `unknown`으로 남을 수 있음 | 필수 5개 상태 계약 불일치 | 생성 출처별 안전 기본값과 기존 데이터 마이그레이션 추가 |
| 기준 상품 API에서 실제 준비 상태를 알 수 없음 | 기준 캡처·JPG·평가표 누락을 완료로 오인 | workspace별 프로젝트, 캡처 자산, JPG 자산, 평가 결과와 `ready` 반환 |
| YL-T02의 마사지 헤드 수 충돌이 문자열 메모에만 존재 | 충돌 상태를 자동 검증하기 어려움 | `massage_head_count`의 `4개` 대 `6개 이상`을 구조화하고 `conflicted`로 고정 |

## 2. 기획 항목별 최종 판정

| 기획 항목 | 판정 | 구현 근거 |
| --- | --- | --- |
| 기준 상품 3종 | 충족 | YL-T02 마사지 베개, 라운드랩 자작나무 수분크림, 락앤락 비스프리 용기 세트 고정 카탈로그 |
| 기준 자료 묶음 | 충족 | 상품, 필수 이미지 역할, 참고 구조, 사실 충돌, 기준 캡처, 기준 JPG, 평가 결과를 등록·조회 |
| 자산 상태 5종 | 충족 | `reference_only`, `seller_owned`, `ai_generated`, `derived_graphic`, `blocked` |
| 사실 상태 6종 | 충족 | `extracted`, `source_confirmed`, `seller_confirmed`, `needs_review`, `conflicted`, `rejected` |
| 공급처 원본의 최종 출력 금지 | 충족 | URL 수집 자산은 기본 `reference_only`; 페이지 후보·readiness에서 제외 |
| 근거 없는 수치·성능 문구 금지 | 충족 | 일반 단위 수치와 위험 표현을 탐지하고 미승인·충돌 사실 연결 시 내보내기 차단 |
| 최종 스펙/고지 마지막 배치 | 충족 | 부재, 중간 배치, 뒤 섹션 추가 및 버전 복원 모두 검증 |
| 평가표 | 충족 | HERO 식별성, 서로 다른 시각물, 반복, 공급처 배너, 근거, 흐름, 빈 섹션, JPG 연결을 저장·판정 |
| API 준비 상태 | 충족 | 기준 상품 목록에 workspace별 등록 상태와 누락 필드를 함께 반환 |
| JPG/PNG 보호 | 충족 | readiness blocker가 있으면 내보내기 API가 거절하도록 연결 |

## 3. 핵심 구현 위치

- 정책 계약: `backend/src/services/commerce_policy.py`
- 기준 상품·평가 계약: `backend/src/services/commerce_story_baseline.py`
- 내보내기 준비도: `backend/src/services/page_readiness_service.py`
- 수치·표현 근거 검사: `backend/src/services/grounding_validator.py`
- 기준 상품 API와 페이지 순서 보호: `backend/src/api/pages.py`
- 사실 API: `backend/src/api/facts.py`
- 자산 API: `backend/src/api/files.py`, `backend/src/api/projects.py`
- 상태 마이그레이션: `backend/src/db/database.py`, `backend/src/db/models.py`
- 핵심 회귀 테스트: `backend/tests/test_v2_sprint0_baseline_policy.py`

## 4. 자동 검증 결과

실행 명령:

```powershell
Set-Location C:\page\backend
.\.venv\Scripts\python.exe -m pytest `
  tests/test_v2_sprint0_baseline_policy.py `
  tests/test_coupang_style_baseline.py `
  tests/test_page_readiness_service.py `
  tests/test_seller_fact_ingestion_service.py `
  tests/test_grounding_validator.py -q
```

결과: **28 passed**

검증된 핵심 시나리오:

- 기준 상품 3종과 YL-T02 구조화 충돌
- `reference_only` 자산의 최종 페이지 후보·내보내기 거절
- V2 자산/사실 상태 API 계약과 과거 상태 입력 거절
- 최종 스펙 섹션 부재·중간 배치 거절
- 근거 없는 수치, 충돌 사실, 공급처 중국어 배너 거절
- 기준 캡처·JPG·평가표 등록 및 API `ready` 판정
- 평가 미완료 또는 기준 JPG 누락 상태의 완료 판정 차단
- 판매자 직접 입력 사실의 `seller_confirmed` 저장

확장 회귀 검증은 **50 passed, 6 failed**였습니다. 실패 6개는 Sprint 0 변경으로 생긴 회귀가 아니라 현재 코드와 이미 계약이 달라진 과거 테스트입니다.

- 폐기되어 410을 반환하는 AI 편집 API를 200/404로 기대하는 테스트 4개
- 개발 모드에서 작업 레코드가 없는 `ai_generated` 자산을 허용하는 현재 정책과 충돌하는 테스트 1개
- 과거 HTML 비주얼 백필 결과 형식을 기대하는 테스트 1개

이 항목들은 Sprint 0 완료 조건과 분리해 후속 기술부채로 관리합니다.

## 5. 운영 확인 사항

코드는 기준 상품 세 개를 고정하고 준비 상태를 정직하게 반환합니다. 다만 실제 workspace에서 `ready: true`가 되려면 각 상품에 프로젝트, 참고 캡처 자산, 기준 JPG 자산, 모든 평가 항목을 실제로 등록해야 합니다. 누락된 상태를 완료로 가장하지 않고 API의 `missing_fields`로 표시합니다.

백엔드를 다시 시작하면 기존 `unknown`/과거 사실 상태를 V2 상태로 정규화하는 시작 마이그레이션이 적용됩니다.

## 6. 최종 결론

Sprint 0 기획에서 요구한 기준 상품, 권리 상태, 사실 상태, 평가표, 최종 출력 차단 규칙과 자동 보호 테스트가 구현되었습니다. Sprint 1 진입을 막는 Sprint 0 코드 결함은 현재 확인되지 않았습니다.
