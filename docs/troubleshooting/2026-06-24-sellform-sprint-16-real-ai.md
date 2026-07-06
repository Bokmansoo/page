# Sellform Sprint 16 Real AI Fact Extraction Troubleshooting

본 문서는 Sprint 16 (Real AI Fact Extraction)의 환경 변수 및 AI 호출 API 연동과 관련해 발생할 수 있는 주요 예외 시나리오 및 해결 방식을 다룹니다.

---

## 1. 예상되는 오류 시나리오 및 대응 요령

### Scenario 1: `OPENAI_API_KEY` 설정 누락으로 인한 호출 실패

* **원인:** 로컬에 `.env` 파일이 생성되지 않았거나, `OPENAI_API_KEY` 값이 비어있는 경우.
* **증상:** 백엔드 시작 시 `OpenAI API Key가 설정되지 않았습니다...` 경고 로그 발생 및 AI 분석 시작 시 `ValueError` 유발.
* **대처 방식:** 
  * API 호출 계층에서 해당 예외를 캐치하여 즉시 **Mock/Deterministic Fallback** 모드로 자동 전환됩니다. 
  * 사용자에게 AI 호출 오류 알림을 전달하며 수집에 성공했던 기존 정보(이미지 OCR 등)나 수동 기입 텍스트만으로 후보 생성 단계를 온전히 완수하도록 방어 코드가 설계되었습니다.
  * 해결을 위해 `C:\page\.env`를 만들어 유효한 API 키를 할당하고 백엔드를 재기동해야 합니다.

### Scenario 2: 외부 API 타임아웃 발생 (TimeoutException)

* **원인:** OpenAI 서버의 응답이 극도로 느려지거나 로컬 네트워크망이 불안정하여 설정된 타임아웃(기본 30초)을 초과한 경우.
* **증상:** `httpx.TimeoutException` 또는 `openai.APITimeoutError`가 발생해 요청이 블로킹될 위험 발생.
* **대처 방식:**
  * `OpenAIAdapter.extract_facts` 메쏘드 내에 `retry_with_backoff` 데코레이터가 선언되어 있어 **최대 3회** 지수 백오프(Exponential Backoff) 기반의 재시도를 수행합니다.
  * 3회 재시도마저 타임아웃 초과로 최종 실패하면 예외를 상위 API 계층으로 전달하고, API는 이를 Fallback 흐름으로 포섭해 500 장애를 차단합니다.

### Scenario 3: AI 응답 JSON 스키마 미스매치 (Malformed Response)

* **원인:** LLM이 스키마 약속을 어기고 부정확한 형식의 JSON을 내려주어 `ExtractionResultSchema` 파싱 에러(ValidationError)를 유발하는 경우.
* **대처 방식:**
  * OpenAI의 최신 기능인 **Structured Outputs (`beta.chat.completions.parse`)**를 활용하여 API 수준에서 스키마 부합성을 강제했습니다.
  * 만약 다른 모델을 사용해 파싱 오류가 발생하더라도 `json.loads` 또는 `ValidationError` 처리 영역에서 에러를 트래핑하여 안전하게 수동 텍스트 분석 결과만 후보로 변환해 올리는 Fallback을 활성화합니다.

### Scenario 4: `.env` API 키 유출 위험

* **원인:** 실제 `OPENAI_API_KEY`를 로컬 `.env`에 넣은 뒤 실수로 Git에 포함할 위험이 있습니다.
* **대처 방식:**
  * `.gitignore`에 `.env`를 추가하여 로컬 API 키 파일이 기본적으로 추적되지 않도록 했습니다.
  * `.env.example`에는 실제 키 없이 빈 값과 설정 이름만 유지합니다.

### Scenario 5: AI adapter 실패 시 자동 생성 전체 중단

* **원인:** API 키가 있어 실제 OpenAI adapter 경로를 타더라도 timeout, rate limit, 잘못된 키, 스키마 오류 등으로 adapter가 실패할 수 있습니다.
* **대처 방식:**
  * `/facts/auto-extract`에서 adapter 예외를 `failed_sources`의 `ai_adapter_failed`로 기록하고 기존 deterministic fallback을 사용합니다.
  * 이 경우에도 API는 201 응답을 유지하며 사용자는 생성된 fallback 후보를 검수하거나 부족한 정보를 수동으로 보완할 수 있습니다.
