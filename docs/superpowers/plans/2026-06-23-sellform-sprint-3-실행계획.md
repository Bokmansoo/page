# 셀폼(Sellform) 스프린트 3 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** AI가 원본 입력 자료(텍스트 및 이미지)를 분석하여 한국어 상품 사실(Fact) 후보를 정형화된 JSON 형태로 추출하고, 지정된 카테고리(패션, 뷰티, 식품, 리빙)의 필수 정보 누락 및 표시광고 위반 리스크를 자동 검수하는 AI 어댑터 및 카테고리 규제 검수 엔진을 구축합니다. 또한, 각 작업의 메트릭(모델, 프롬프트 버전, 토큰 비용, 속도)을 정밀하게 기록합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [MODIFY] `backend/pyproject.toml`: `openai`, `anthropic`, `google-generativeai` 라이브러리 의존성 추가
- [MODIFY] `backend/src/config.py`: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` 환경 변수 구성 및 주입
- [MODIFY] `backend/src/db/models.py`: AI 작업 실행 이력 추적을 위한 `AiJobLog` 테이블 모델 추가 정의
- [NEW] `backend/src/services/ai_adapter.py`: 다중 AI 공급자를 추상화하는 `AIServiceAdapter` 및 구체 어댑터 클래스 구현
- [NEW] `backend/src/services/compliance.py`: 카테고리별 필수 정보 확인 및 광고 심의 금지 표현 검수 엔진 구현
- [NEW] `backend/src/api/ai.py`: 상품 분석 실행 및 결과 검수 엔드포인트 API 라우터 구현
- [MODIFY] `backend/src/app.py`: `ai` 라우터 등록
- [NEW] `backend/tests/test_ai_adapter.py`: Mock 환경에서의 어댑터 동작 및 재시도 로직 검증 테스트
- [NEW] `backend/tests/test_compliance.py`: 4대 카테고리별 규제 검수 및 금지어 탐지 단위 테스트

---

## 2. 데이터 모델 (PostgreSQL 스키마)

### 2.1 테이블 정의 (SQLAlchemy 명세)

#### **`ai_job_logs`**
- `id` (UUID, PK): 작업 실행 이력 고유 ID
- `project_id` (UUID, FK -> `product_projects.id`, nullable=False): 연동된 상품 프로젝트 ID
- `task_type` (String(100), nullable=False): 작업 유형 (`fact_extraction`, `compliance_check` 등)
- `provider` (String(50), nullable=False): AI 공급자명 (`openai`, `anthropic`, `google`)
- `model_name` (String(100), nullable=False): 사용된 모델명 (예: `gpt-4o`, `claude-3-5-sonnet`)
- `prompt_version` (String(50), nullable=False): 사용된 프롬프트 템플릿의 버전
- `duration_ms` (Integer, nullable=False): AI 호출 및 처리 소요 시간 (밀리초)
- `input_tokens` (Integer, nullable=True): 소비된 입력 토큰 수
- `output_tokens` (Integer, nullable=True): 소비된 출력 토큰 수
- `estimated_cost` (Float, nullable=True): 계산된 예상 API 비용 (USD)
- `status` (String(50), nullable=False, default="pending"): 작업 상태 (`success`, `failed`)
- `error_message` (Text, nullable=True): 에러 발생 시 기록될 스택트레이스 및 에러 메시지
- `created_at` (DateTime, default=utcnow)

---

## 3. API 계약 (API Contract)

### 3.1 상품 프로젝트 분석 (AI 추출 및 검수 통합 실행)
- **요청**: `POST /api/v1/projects/{project_id}/analyze`
  - Body: `{ "provider": "openai | google | anthropic (optional)", "model_name": "string (optional)" }`
- **응답 (202 Accepted)**:
  ```json
  {
    "job_id": "UUID",
    "project_id": "UUID",
    "status": "processing",
    "message": "AI analysis and compliance check has been scheduled."
  }
  ```
- **비즈니스 로직**:
  1. 프로젝트에 연동된 원본 텍스트 및 이미지 에셋 경로를 수집합니다.
  2. 선택된 AI 어댑터를 호출하여 상품 속성 및 한국어 사실 카드를 JSON 형태로 구조화하여 가져옵니다.
  3. 가져온 사실들에 대해 `compliance_engine`을 구동하여 필수 정보 누락(Major) 및 규제 위반 표현(Blocker)을 탐지합니다.
  4. 사실 카드(`product_facts`) 데이터베이스에 후보 항목들을 임시 생성하고, 검수 위반 결과가 있다면 `project_projects.status`를 `checking`으로 변경합니다.
  5. AI 실행 관련 매트릭을 측정하여 `ai_job_logs`에 적재합니다.

---

## 4. 테스트 케이스 및 실행 명령

### 4.1 백엔드 어댑터 및 규제 검수 테스트 (`backend/tests/`)
1. **`test_compliance.py`**:
   - `docs/testing/2026-06-23-product-test-pack-definition.md`에 명시된 12가지 카테고리별 정상/누락/위험 텍스트 시나리오 데이터를 검수 엔진에 넘겼을 때, 기대하는 오류 규칙과 경고 메시지 목록(`expected_issues`)이 100% 일치하여 탐지되는지 테스트.
2. **`test_ai_adapter.py`**:
   - AI 어댑터 호출 시 일시적인 네트워크 장애나 스키마 일치율 실패 등의 가상 시나리오를 구성하여, 최대 3회의 Exponential Backoff 재시도 로직이 정상 작동하고 최종 실패 시 `failed` 상태로 이력이 올바르게 기록되는지 테스트.

### 4.2 실행 명령
```bash
# 백엔드 단위 테스트 전체 실행
cd backend
uv run pytest
```

---

## 5. 완료 및 기록 기준 (Definition of Done)

### 5.1 기능 완료 기준
1. **다중 공급자 어댑터화 완료**: `AIServiceAdapter` 추상 인터페이스를 통해 OpenAI, Anthropic, Gemini API 요청 포맷이 격리되어 있어야 하며 환경변수로 자유롭게 기본 모델을 스위칭할 수 있어야 합니다.
2. **스키마 검증 및 재시도 탑재**: AI 응답 JSON 스키마 에러를 차단하기 위해 OpenAI `Structured Outputs` 설정이 적용되어야 하며, 기타 모델 호출 시 에러가 나면 3회 자동 재시도 로직이 수행되어야 합니다.
3. **카테고리별 가이드라인 검수 엔진**: 4대 프리셋 카테고리(패션, 뷰티, 식품, 리빙)의 필수 정보 누락 및 법적 금지 단어가 규칙에 의거해 명확히 필터링되어야 합니다.
4. **이력 추적 및 모니터링 로깅**: 매 분석 실행 시마다 소요 시간, 비용, 토큰, 성공 여부 등의 감사 메트릭이 `ai_job_logs` 테이블에 적재됩니다.

### 5.2 기록 산출물 기준 (유저 특별 요청)
본 스프린트의 변경 사항은 다음의 문서에 철저히 기록되어야 스프린트가 종결된 것으로 봅니다.
*   **자가 코드리뷰**: `docs/reviews/2026-06-23-sprint-3-code-review.md`에 설계와 품질 검토 기록.
*   **실측 테스트 로그**: `docs/testing/2026-06-23-sprint-3-test-run-log.md`에 12개 테스트 팩 수행 로그.
*   **의사결정 보완**: `docs/decisions/2026-06-23-sprint-3-ai-evaluation-and-model-selection.md`에 벤치마크 기반 최종 모델 선정 근거 기록.
*   **트러블슈팅 기록**: `docs/troubleshooting/2026-06-23-sprint-3-troubleshooting.md`에 개발 및 테스트 중 겪은 예외 원인 및 대처 방법 기술.
*   **최종 워크스루**: 프로젝트 루트의 `walkthrough.md` 및 `task.md`를 최신화하여 변경 이력을 투명하게 완료 처리.
