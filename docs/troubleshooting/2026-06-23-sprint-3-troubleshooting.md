# 트러블슈팅 로그: Sprint 3 (AI 자료 정리와 카테고리 엔진)

- **작성일:** 2026-06-23
- **작성자:** AI (Antigravity)

---

## Issue 1. Anthropic API의 네이티브 JSON 스키마 강제 미지원 및 에러 처리

### 1. 현상 (Symptom)
*   Anthropic Claude 3.5 Sonnet 모델을 통해 원본 데이터를 한국어 사실로 정리할 때, 간혹 마크다운 코드블록(` ```json `)이 응답 텍스트에 포함되거나 누락된 필드가 반환되어 Pydantic Schema Parsing 에러(`ValidationError`)가 발생할 위험이 감지됨.

### 2. 원본 원인 (Root Cause)
*   Anthropic API는 OpenAI의 `Structured Outputs`처럼 런타임 JSON 스키마 일치율을 100% 보장하는 네이티브 제약 기능을 직접 제공하지 않음.

### 3. 해결책 (Resolution)
*   **Anthropic Tools & Forced Tool Call 적용**: 
    *   `extract_product_info`라는 이름의 도구(Tool)를 정의하고, 도구의 입력 스키마(`input_schema`)로 우리가 원하는 Pydantic schema 명세를 주입했습니다.
    *   동시에 `tool_choice={"type": "tool", "name": "extract_product_info"}`를 지정하여 클로드가 대화 응답 대신 항상 이 도구를 사용하도록 강제했습니다. 이로 인해 마크다운 포장지 없이 깔끔하게 스키마를 따르는 JSON 인풋을 얻어냈습니다.

---

## Issue 2. SQLAlchemy 신규 테이블 생성 누락 문제

### 1. 현상 (Symptom)
*   `AiJobLog` 모델 추가 후 로컬 SQLite DB에 테이블(`ai_job_logs`)이 자동으로 생성되지 않아, 작업 기록 적재 시 `OperationalError: no such table: ai_job_logs` 에러가 발생함.

### 2. 원본 원인 (Root Cause)
*   FastAPI의 `lifespan`이나 테스트 conftest에서 `Base.metadata.create_all(bind=engine)`을 구동할 때, `models.py` 파일이 선언되거나 임포트되어 있지 않아 SQLAlchemy의 `Base.metadata` 맵에 테이블 정의가 등록되지 않은 채로 생성 로직이 끝났음.

### 3. 해결책 (Resolution)
*   `app.py` 및 테스트의 `conftest.py` 등 데이터베이스 테이블 생성이 진행되는 시작점 부근에 `src.db.models`를 확실하게 임포트하도록 의존 순서를 맞춰주었습니다. (FastAPI 엔드포인트 임포트 과정에서 `api/ai.py` -> `models` 임포트가 자연스럽게 연쇄되며 해결됨 확인)
