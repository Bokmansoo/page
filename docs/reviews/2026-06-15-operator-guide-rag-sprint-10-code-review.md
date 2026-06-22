# 코드 리뷰: operator_guide RAG Sprint 10 (Debug Endpoint & Production Wiring)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `feature/operator-guide-rag-sprint10` |
| 리뷰 일자 | 2026-06-15 |
| 리뷰 범위 | RAG 디버그 API 라우터(`debug_router.py`), FastAPI `lifespan` 런타임 Wiring (`app.py`), RAG 검색 모니터링 로깅 (`rag_retriever.py`), 데이터베이스 세션 환경 변수 호환성 보강 (`engine.py`) |
| 관련 기획·작업 | RAG Sprint 10 설계 및 개발 계획 |
| 리뷰어 | kimkyungpyo |
| 상태 | 승인 |

## 1. 변경 요약

- RAG 검색 품질을 LLM 답변 과정 없이 단독 진단하는 디버그 엔드포인트 `POST /api/v1/debug/manual-rag/search` API 라우터 추가.
- API 진입부에서 `FACTORY_RAG_DEBUG_ENABLED` 환경변수가 `true`로 설정되지 않았을 경우 `403 Forbidden`을 리턴하는 보안 제어 구성.
- RAG 검색 시 쿼리, 매칭 수, 스코어, Confidence 정보 등을 기록하는 시스템 표준 로깅 심기 (`rag_retriever.py`).
- FastAPI `lifespan` 초기화 및 종료 주기에 맞춰 pgvector 데이터베이스 및 Embedding Provider를 빌드해 `ManualQAService`에 글로벌 주입(Wiring)하도록 설계.
- 테스트 환경 격리를 보장하기 위한 `FACTORY_RAG_RUNTIME_MOCK` 환경변수 플래그 도입 및 우회 처리 반영.
- DB 연결 호환성 개선을 위해 `engine.py`에서 `DATABASE_URL`이 없을 때 `FACTORY_DATABASE_URL`을 fallback으로 적용하도록 보강.

명시적으로 이번 범위에서 제외한 것:
- RAG 검색 결과에 따른 실시간 LLM 카피/답변 생성 및 요약 기능.
- 쿠팡 및 스마트스토어 외부 채널로의 자동 상품 등록 API 연동.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- 기획·결정 문서: RAG Sprint 10 설계 명세서 및 API 보안 설계 결정 기록
- 코드·화면·API:
  - RAG 디버그 라우터: `backend/src/api/debug_router.py`
  - FastAPI 진입 및 Wiring: `backend/src/app.py`
  - RAG 검색 및 로깅: `backend/src/rag/rag_retriever.py`
  - DB 커넥션 설정: `backend/src/db/engine.py`
- 테스트 증적: `pytest backend/tests/test_rag.py` 실행 로그 및 로컬 API 동작 테스트 결과

### 핵심 흐름

```text
[디버그 검색 요청 (POST)]
       ↓
[FACTORY_RAG_DEBUG_ENABLED 환경변수 검사]
       ├─ (False) → [403 Forbidden 반환 및 차단]
       └─ (True)  → [RAG 검색 엔진 구동]
                         ↓
                  [질문 분해기 (Decomposer) 동작]
                         ↓
                  [pgvector 다중 질문 벡터 검색 수행]
                         ↓
                  [Score 및 Confidence 메트릭 계산]
                         ↓
                  [시스템 표준 로그 기록 (rag_retriever.py)]
                         ↓
[검색 매칭 결과 및 품질 분석 데이터 응답 (200 OK)]
```

- **정상 흐름**: RAG 디버그가 활성화된 상태에서, LLM 최종 답변 생성을 생략하고 pgvector로부터 검색된 순수 청크 정보와 스코어, 신뢰도 데이터를 구조화된 형태로 응답.
- **빈 입력·누락 자료**: 검색어 입력이 비어 있거나 유효하지 않은 포맷인 경우 Pydantic 스키마 수준에서 Validation Error 발생.
- **AI·외부 서비스 실패**: pgvector 초기화나 OpenAI Embedding API 연결 실패 시 예외를 잡아 기존 CSV-only 모드로 안전하게 Graceful Fallback 수행.
- **느린 연결·중복 요청·이탈 후 재개**: FastAPI lifespan 생명주기 관리 하에 초기 커넥션 풀 빌드를 완료하고, 중복 연결을 배제하도록 설계.

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 🔴 B1. `engine.py`에서 `DATABASE_URL` 우선 적용으로 인한 SQLite pgvector 문법 에러

- **위치:** `backend/src/db/engine.py:13-22`
- **내용:** `engine.py`가 RAG 런타임 바인딩 시 `DATABASE_URL` 환경 변수만 바라보고 있어, `.env.prod`에 기재된 `FACTORY_DATABASE_URL`이 누락된 상태에서 SQLite(`sqlite:///./factory_space.db`)를 강제 로드했다. SQLite 환경에서 pgvector 전용 vector distance 정렬 연산자를 호출함에 따라 `sqlite3.OperationalError: near ">": syntax error`가 발생하며 RAG 서비스 전체가 불능이 됨.
- **영향:** 로컬 구동 및 실서버 테스트 시 RAG 검색 기능 동작 실패.
- **제안:** `DATABASE_URL`이 정의되지 않았을 때 프로젝트 전반에서 쓰는 `FACTORY_DATABASE_URL`을 fallback으로 함께 확인하도록 수정.

> **[조치 상태 - 2026-06-15]** `get_database_url` 함수에서 `os.environ.get("DATABASE_URL") or os.environ.get("FACTORY_DATABASE_URL")` 형태로 환경 변수를 병합 조회하도록 보강하여 pgvector 에러를 깔끔하게 해소했습니다.

### 🟠 M1. FastAPI lifespan 테스트 시 Mock 런타임 오버라이드 문제

- **위치:** `backend/src/app.py:33-49`
- **내용:** 유닛 테스트 실행 시 `TestClient`가 FastAPI lifespan을 시작하면서 실제 pgvector DB와 OpenAI Embedding 서비스를 엮은 실시간 런타임을 글로벌 주입했다. 이로 인해 테스트 코드 내에서 격리 검증을 위해 셋업했던 Mock RAG 런타임이 오버라이드되는 현상이 발생했다.
- **영향:** 유닛 테스트 환경 오염 및 RAG 런타임 Mocking 테스트 실패 유발.
- **제안:** 테스트 세션과 같이 RAG 런타임을 Mocking해야 하는 경우 강제로 lifespan 초기화를 우회하는 별도 환경변수 플래그 도입.

> **[조치 상태 - 2026-06-15]** `FACTORY_RAG_RUNTIME_MOCK` 환경 변수가 `true`인 경우 lifespan 내 RAG 초기화 로직을 우회하도록 예외 분기 처리를 반영했습니다.

## 4. 우선순위 권고

1. **B1** — SQLite pgvector 에러는 RAG 프로덕션 가동 자체를 불가능하게 하므로 즉각 수정되어야 함 (조치 완료).
2. **M1** — 테스트 격리 오염을 유발하므로 즉각 반영되어야 함 (조치 완료).

## 5. 긍정적인 부분

- RAG 품질만을 독립적으로 검사할 수 있는 디버그 엔드포인트를 구현하여 개발 편의성 및 품질 모니터링 능력이 대폭 향상됨.
- RAG 초기화 실패 시 예외 처리를 거쳐 기존 CSV-only 모드로 graceful fallback하는 안정적인 결함 격리 설계가 반영됨.
- 질문 분해기(Decomposer)를 거친 다중 질문 검색 구조와 confidence 산출이 자연스럽게 백엔드 런타임에 통합됨.

## 6. AI·사실 신뢰성 검토

- **사용한 사실과 근거:** RAG 디버그 API를 통해 반환되는 검색 스코어 및 매칭 근거 데이터.
- **미확인 사실 처리:** 디버그 API 레벨에서 Confidence 점수를 명시하여, 임계치 이하의 정보가 생성부에 노출되지 않도록 필터링 가능하도록 함.
- **프롬프트·모델·스키마 변경:** RAG 리트리버 성능 검증을 위한 메타데이터 구조 추가.
- **품질·비용·안전성 평가:** 디버그 검색 모니터링 로깅(`rag_retriever.py`)을 통해 호출당 검색 매칭 품질 및 소요 속도 확인 가능.

## 7. 검증 증적

- **자동 테스트:** `pytest backend/tests/test_rag.py` 실행 완료 (Mock RAG 런타임 우회 정상 동작 및 SQLite 환경 격리 테스트 패스).
- **수동 QA:** `FACTORY_RAG_DEBUG_ENABLED=true` 설정 후 `POST /api/v1/debug/manual-rag/search` API 호출 및 쿼리에 따른 pgvector 검색 반환 확인.
- **출력물·스크린샷:** RAG 디버그 API 실행 결과 JSON 데이터 수집 완료.

## 8. 결론

- **결론:** 승인
- **결정 이유:** 심각도가 높은 Blocker(B1) 및 Major(M1) 이슈에 대한 조치가 완료되었으며, 유닛 테스트 통과 및 디버그 엔드포인트를 통한 수동 동작 검증이 완료됨.
- **머지 또는 다음 스프린트 전 필수 조치:** 실서버 배포 시 `.env` 환경 변수(`FACTORY_RAG_DEBUG_ENABLED`, `FACTORY_DATABASE_URL`)의 올바른 설정값 재확인.
- **남은 위험과 다음 작업:** RAG 성능 고도화를 위해 실 데이터셋 기반의 정밀도/재현율 평가 진행 예정.

## 9. 후속 기록

- **`memory/`에 남길 교훈:** 로컬/테스트 환경의 SQLite 환경과 운영/개발 환경의 PostgreSQL(pgvector) 간 호환성을 보장하기 위해, 데이터베이스 세션 팩토리 연결부(`engine.py`) 작성 시 환경변수 fallback 및 다중 DB 드라이버 분기를 상시 신중하게 검증할 것.
