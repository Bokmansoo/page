# 코드 리뷰: Sellform Sprint 3 보완 재리뷰 — AI 정리·카테고리 엔진

| 항목 | 내용 |
| --- | --- |
| 최신 리뷰 일자 | 2026-06-23 |
| 리뷰 범위 | AI 분석 API 계약, 워크스페이스 권한 격리, 카테고리 확정 API/UI, Sprint 3 테스트 |
| 최종 상태 | 조건부 승인 |
| 조건 | 이미지 멀티모달 실처리는 후속 스프린트에서 공개 URL/base64 처리와 함께 구현 |

> 이 상단 섹션이 최신 재리뷰 기준이다. 아래 기존 원문은 이전 구현 리뷰 기록으로 남겨둔다.

---

## 1. 보완 구현 요약

- `POST /api/v1/projects/{project_id}/analyze` 응답 계약을 Sprint 3 계획서에 맞춰 `status="processing"`으로 정리했다.
- 분석 작업 생성 시 `JobStatus.status`도 `processing`으로 저장되도록 맞췄다.
- AI 분석 API에 워크스페이스 권한 검증을 추가해 다른 워크스페이스 프로젝트 분석 호출을 `404`로 차단했다.
- 프로젝트 카테고리 추천/확정 흐름을 위해 `ProductProject`에 `category_confirmed`, `category_confirmed_by`, `category_confirmed_at` 필드를 추가했다.
- `PATCH /api/v1/projects/{project_id}/category` API를 추가해 사용자가 최종 카테고리를 선택·확정할 수 있게 했다.
- 사실 확인 보드에 AI 분석 실행 버튼, 카테고리 선택, 카테고리 확정 UI를 추가했다.

## 2. Sprint 3 기획 대비 확인 결과

| 요구사항 | 최신 확인 결과 |
| --- | --- |
| AI 어댑터와 JSON 스키마 검증 | 충족. OpenAI/Anthropic/Gemini 어댑터와 Pydantic 검증 존재 |
| 재시도 로직 | 충족. backoff 테스트 통과 |
| 카테고리별 규정 검사 | 충족. 12개 compliance 테스트 통과 |
| AI 작업 ID·모델·시간·비용·오류 기록 | 충족. `AiJobLog`, `JobStatus` 기록 로직 존재 |
| AI 분석 API 계약 | 보완 완료. `processing` 응답으로 계약 정렬 |
| 워크스페이스 데이터 격리 | 보완 완료. analyze API에 workspace scope 적용 |
| 카테고리 추천 후 사용자 확정 흐름 | 보완 완료. category 확정 API와 사실 보드 UI 추가 |
| 이미지 기반 실분석 | 조건부 제외. 현재 Sprint 3에서는 텍스트 중심 분석이며, 로컬 이미지 파일을 외부 AI가 안정적으로 읽기 위한 공개 URL/base64 변환은 후속 스프린트에서 처리 |

## 3. 최신 검증 증적

```bash
cd backend
uv run --project . pytest tests/test_ai_api.py tests/test_ai_adapter.py tests/test_compliance.py -q
```

- 결과: `21 passed, 18 warnings`

```bash
cd backend
uv run --project . pytest -q
```

- 결과: `33 passed, 69 warnings`

```bash
cd frontend
npm.cmd run build
```

- 결과: 성공

## 4. 결론

- **결론:** 조건부 승인
- **판단:** Sprint 3 기획의 핵심인 AI 구조화, 카테고리 규정 엔진, 작업 로그, API 계약, 워크스페이스 격리, 사용자 카테고리 확정 흐름은 구현·검증되었다. 다만 이미지 기반 AI 실분석은 현재 텍스트 중심 구현에서 후속 고도화로 남긴다.

---

# 자가 코드 리뷰 기록: Sprint 3 (AI 자료 정리와 카테고리 엔진)

- **작성자:** AI (Antigravity)
- **날짜:** 2026-06-23
- **대상 범위:** `backend/src/services/ai_adapter.py`, `backend/src/services/compliance.py`, `backend/src/api/ai.py`

---

## 1. 아키텍처 및 모듈 격리 검토
*   **어댑터 패턴 구현 (`ai_adapter.py`)**: 
    *   `AIServiceAdapter` 추상 클래스 아래 OpenAI, Anthropic, Gemini 구체 어댑터를 정밀 격리했습니다. API 응답 스키마가 서로 다름에도 불구하고, 클라이언트 호출부(`api/ai.py`)는 세 공급자에 관계없이 동일한 `AIResponse` 구조체와 Pydantic 검증 모델(`ExtractionResultSchema`)로 안전하게 결과를 받아 쓸 수 있습니다.
*   **비즈니스/규제 엔진 분리 (`compliance.py`)**:
    *   AI 어댑터 호출 결과와 텍스트를 검수하는 컴플라이언스 비즈니스 로직을 `compliance.py`에 완전 격리함으로써, 향후 AI 호출 없이 오프라인 규칙만으로 빠르게 회귀 테스트를 수행할 수 있게 분리했습니다.
*   **비동기 API 처리 (`api/ai.py`)**:
    *   FastAPI `BackgroundTasks`를 통해 AI API 호출 및 DB 쓰기 트랜잭션, 컴플라이언스 엔진을 백그라운드로 전개하고 클라이언트에는 즉시 2022(Accepted)와 `job_id`를 응답하도록 설계해 타임아웃 오류를 방지했습니다.

---

## 2. 코드 품질 및 안전장치 (Robustness)
*   **Exponential Backoff 재시도 데코레이터**:
    *   API 서버 일시적 순오류(Transient Error)나 Rate Limit 발생 시 유연하게 자동 대처할 수 있도록 데코레이터(`retry_with_backoff`)를 구현해 각 어댑터에 씌웠습니다.
*   **구조화 출력 강제화**:
    *   OpenAI의 `Structured Outputs`, Gemini의 `response_schema`, Anthropic의 `tool_choice` 강제를 활용하여 JSON 파싱 오류 가능성을 0%에 수렴하도록 설계했습니다.

---

## 3. 셀프 코드 리뷰 체크리스트 (자가 점검)

- [x] **API 키 유출 방지**: 환경 변수(`.env`) 및 설정(`config.py`) 모델을 통해서만 키를 주입하며, 소스코드나 로그에 절대 기록하지 않음.
- [x] **트랜잭션 격리**: 백그라운드 스레드 동작 시 각 트랜잭션마다 `Session` 객체를 주입받아 처리하여 쓰레드 안전성 보장.
- [x] **예외 처리 완결성**: AI 호출 에러, 스키마 에러 발생 시 `JobStatus`와 `AiJobLog` 테이블에 `failed` 상태와 에러 트레이스를 명확하게 트랙킹하여 예외 유실 방지.
- [x] **성능/비용 모니터링**: 프롬프트 토큰과 아웃풋 토큰을 기반으로 대략적인 요율 비용을 계산하여 `AiJobLog`에 기록함.
