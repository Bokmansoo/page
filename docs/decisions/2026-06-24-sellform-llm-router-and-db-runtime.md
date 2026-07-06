# Sellform LLM Router & Database Runtime Architecture Decision Record (Sprint 18)

본 문서는 AI 사실 추출 서비스의 안정성 증대를 위한 LLM 라우터 도입과, 상용 서비스로의 도약을 대비한 PostgreSQL 공존 정책 수립에 관한 아키텍처 결정 레코드(ADR)입니다.

## 1. 배경 및 목적

현재 Sellform은 단일 OpenAI API 연동(또는 Mock Fallback)을 사용하여 사실 추출을 수행합니다. 
그러나 OpenAI API의 지연(Timeout), Rate Limit 도달, 또는 API Key 누락과 같은 네트워크 환경 장애 발생 시, 프로젝트 분석 파이프라인 전체가 즉시 실패하여 사용자 경험이 현저히 저해될 수 있습니다. 
이를 예방하기 위해, 여러 AI Provider들(OpenAI -> Google Gemini)을 순차적으로 시도하고, 최종 실패 시 로컬 룰 기반(Deterministic)으로 우아하게 떨어지는 **폴백(Fallback) 라우팅 체인**이 요구되었습니다.

또한, 로컬 개발/테스트 시에는 SQLite가 가볍고 유리하지만, 멀티테넌트 및 트랜잭션 빈도가 높은 상용/구독형 서비스를 지탱하려면 PostgreSQL로의 마이그레이션이 필수적입니다. 개발의 편리함을 해치지 않으면서 PostgreSQL 운영 준비를 마치는 공존 전략을 수립해야 합니다.

## 2. 결정 사항 (Decisions)

### 2.1 LLM 라우터 아키텍처 도입
1. **순차적 폴백 체인 (Sequential Fallback Chain)**:
   - 복잡한 LangGraph나 LangChain 프레임워크를 도입하지 않고, 가벼운 단일 서비스 수준의 `LLMRouter` 클래스를 구현합니다.
   - 라우터 체인 순서: **OpenAI (`gpt-5.4-nano`) -> Google Gemini (`gemini-2.5-flash`) -> Deterministic (`local-rule-based`)**
   - 앞선 Provider의 호출이 30초 타임아웃 초과, API 키 누락, 또는 API 에러를 반환하면 이를 삼켜 `failed_sources`에 누적하고, 다음 Provider를 순서대로 즉각 호출합니다.
2. **하위 호환성 및 설정 유연성**:
   - 공개 설정 변수는 `SELLFORM_LLM_DEFAULT_PROVIDER` 등 `SELLFORM_LLM_*` 설정을 기본으로 사용합니다.
   - 기존 Sprint-era 환경의 `FACTORY_LLM_*` 값은 Pydantic alias로 계속 읽되, 새 문서와 예시는 `SELLFORM_*` 네이밍만 노출합니다.
   - 기존에 사용되던 `OPENAI_FACT_MODEL`은 `SELLFORM_LLM_DEFAULT_MODEL`이 비어 있을 때만 fallback으로 참조합니다.
3. **메타데이터 저장**:
   - 추출 성공 시, 최종 응답을 준 provider 및 model명을 `ProductFact` 레코드의 `provider` 및 `model_name` 컬럼에 명시적으로 기록하여 향후 분석 및 비용 추적을 용이하게 합니다.

### 2.2 PostgreSQL 공존 런타임 수립
1. **SQLAlchemy DB 어댑터 호환성 확보**:
   - SQLite와 PostgreSQL 모두에서 정상 컴파일 및 실행이 가능하도록 표준 SQLAlchemy DDL 스키마 설정을 고수합니다.
2. **DATABASE_URL 스위칭**:
   - `.env` 파일의 `DATABASE_URL` 값에 따라 런타임 DB 어댑터가 동적으로 결정되도록 하여 기존 개발용 SQLite 기본값을 유지하되, PostgreSQL 연결 시 테이블 자동 생성(Metadata create_all)이 무결하게 이행되도록 처리합니다.
3. **도커 컨테이너화**:
   - 로컬에서도 실제 PostgreSQL 운영 테스트를 신속히 수행할 수 있도록 `docker-compose.yml` 상에 `postgres:16-alpine` 정의를 탑재하고 실행법을 문서화(런북)합니다.

## 3. 호환성 및 검증 요약

- **라우터 독립성**: `LLMRouter` 단위 테스트 작성을 통해 순차 폴백이 온전히 작동함을 입증했습니다.
- **이기종 DB 호환성**: 로컬 SQLite 및 Docker PostgreSQL 컨테이너 환경 양측에서 전체 통합 테스트 패키지(`test_facts.py` 18 passed)를 통과시켜 DDL 호환성을 보증했습니다.
