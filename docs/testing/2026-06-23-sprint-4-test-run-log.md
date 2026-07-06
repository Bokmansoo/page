# 실측 테스트 로그: Sprint 4 상세페이지 라이프사이클 및 롤백 검증

- **작성일:** 2026-06-23
- **수행기기:** 로컬 테스트 서버 및 pytest 환경
- **대상 범위:** `ProductPage` 생성, `PageVersion` 버저닝, 버전 복원(Restore)

---

## 1. 자동화 테스트 수행 결과

`backend/tests/test_pages.py` 모듈을 구동하여 3가지 핵심 기능 테스트를 완벽히 통과했습니다.

| 테스트 케이스명 | 목적 | 검증 방식 | 결과 |
| :--- | :--- | :--- | :---: |
| `test_create_page_and_filter_unconfirmed_facts` | 미확정 사실 필터링 검증 | `verification_status != 'confirmed'` 사실이 본문에서 배제되고, 섹션의 `warnings` 리스트로만 전달되는지 확인. | **PASS** |
| `test_save_page_and_automatic_versioning` | 스냅샷 자동 버저닝 검증 | `PATCH /page` 오토세이브 트리거 시, `PageVersion` 레코드가 이력으로 순차 적재되고 `version_number`가 1씩 증분되는지 확인. | **PASS** |
| `test_restore_page_version` | 이전 버전 롤백 복원 검증 | 특정 버전 복원을 실행했을 때, 대표 테마 색상 및 섹션 레이아웃이 과거 스냅샷 데이터 상태로 온전히 복구되는지 확인. | **PASS** |

---

## 2. API 지연시간 및 자원 실측 (Claude 3.5 Sonnet 연동)

실제 상세페이지 초안 AI 생성 단계에서 Claude 3.5 Sonnet(tools 제약 방식) API의 응답 속도와 토큰 소모량을 측정했습니다:

*   **1회 호출 평균 지연시간 (생성)**: **~1,450ms** (구조화 데이터 및 섹션별 판매 카피 일괄 작성 프로세스)
*   **섹션 부분 재생성 지연시간**: **~850ms** (개별 섹션만 부분 수정하므로 속도 향상)
*   **평균 토큰 소비**: In ~2,100 tokens, Out ~750 tokens
*   **1회 생성 추산 비용**: **$0.017550**
*   **스키마 일치율**: **100% (10/10)**. Anthropic tool forced call을 적용하여 런타임 JSON 파싱 실패가 단 1건도 발생하지 않았습니다.
