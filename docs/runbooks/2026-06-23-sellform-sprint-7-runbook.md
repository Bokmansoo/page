# 셀폼(Sellform) 운영 장애 복구 런북 (Sprint 7)

본 문서는 셀폼(Sellform) 시스템 운영 중 발생할 수 있는 주요 장애 유형별 진단 방법 및 긴급 조치 가이드를 제공합니다.

---

## 1. AI 어댑터 연동 실패 및 API 호출 제한 (Rate Limit)

### 1.1 증상
- 상품 분석 요청 시 상태가 계속 `failed`로 변경되며 `JobStatus` 에러 메시지에 `AuthenticationError`, `RateLimitError` 혹은 `APIConnectionError`가 노출됩니다.
- 또는 백엔드 로그에 `HTTP 429 Too Many Requests`가 기록됩니다.

### 1.2 대응 절차
1. **API Key 및 환경 변수 검증**:
   - `.env` 파일에 `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`가 올바르게 입력되어 있는지 확인합니다.
   - API Key 만료 여부를 각 플랫폼 콘솔(OpenAI, Google Cloud, Anthropic console)에서 확인합니다.
2. **속도 제한(Rate Limit) 초과 시 해결책**:
   - 단기 해결책: `AnalyzeRequest` 요청 본문에서 AI 공급자를 교체하여 우회 호출을 시도합니다 (예: OpenAI -> Google).
   - 장기 해결책: API 사용 등급(Tier)을 올리기 위해 결제 수단 한도를 증액하거나 호출량에 스로틀링(Throttling)을 적용합니다.
3. **수동 복구 (Fallback)**:
   - AI 분석이 중단되더라도 사용자는 `SOURCE_EXTRACTION_UNAVAILABLE` 인터페이스를 통해 수동으로 팩트 정보 및 상품명을 타이핑하여 프로젝트를 `facts_verification` 단계로 진행할 수 있습니다.

---

## 2. Chromium 렌더링 엔진 및 PDF/이미지 출력 실패

### 1.2 증상
- 상세페이지 내보내기(`POST /page/export`) 처리 도중 백그라운드 작업 상태가 `failed`로 빠지며 `TimeoutError: Navigation Timeout Exceeded` 혹은 `Chromium process crashed` 등의 오류 메시지가 발생합니다.

### 2.2 대응 절차
1. **Playwright 의존성 확인**:
   - 서버 내에 Headless Chromium 브라우저 바이너리가 제대로 설치되었는지 확인합니다.
   - 복구 명령어:
     ```bash
     cd backend
     uv run playwright install chromium
     ```
2. **서버 리소스(메모리) 부족 검사**:
   - Chromium이 페이지를 렌더링하고 이미지 슬라이싱을 진행하는 동안 CPU/Memory 점유율이 95% 이상으로 치솟아 프로세스가 OS에 의해 강제 종료(OOM)되었는지 확인합니다.
   - 복구 절차: 불필요한 크롬 좀비 프로세스를 수동 강제 종료(Kill) 처리합니다:
     ```powershell
     # Windows PowerShell
     Get-Process -Name chrome, headless_shell | Stop-Process -Force
     ```
3. **템플릿 HTML 검증**:
   - 렌더링 대상이 되는 HTML 스키마에 잘못된 CSS 루프나 대용량 외부 리소스 로딩(예: 외부 폰트, CDN 이미지 지연)이 포함되어 타임아웃을 유발하는지 확인합니다.

---

## 3. 로컬/오브젝트 스토리지 및 파일 저장 장애

### 3.1 증상
- 업로드한 상품 이미지나 내보내기(Export)된 Zip/이미지 파일 다운로드 시 `404 Not Found` 혹은 `File has been deleted or not ready on disk` 오류가 응답됩니다.

### 3.2 대응 절차
1. **업로드 디렉토리 권한 및 존재 여부 확인**:
   - 백엔드가 사용하는 `uploads` 디렉토리(기본값: `backend/uploads/`)가 실제로 생성되어 있고 권한이 정상 부여되었는지 검사합니다.
   - 복구 명령어:
     ```powershell
     # Windows 폴더 생성 및 권한 검사
     New-Item -ItemType Directory -Force -Path "backend/uploads"
     ```
2. **스토리지 디스크 용량 검증**:
   - 로컬 서버의 하드디스크가 100% 꽉 차서 신규 업로드나 내보내기 압축파일 저장이 불가능한지 확인합니다.
   - 디스크 정리 및 불필요한 임시 디렉토리 청소를 수행합니다.
