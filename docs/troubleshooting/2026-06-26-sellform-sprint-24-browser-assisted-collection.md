# Sellform Sprint 24 Browser Assisted Collection Troubleshooting

## 1. Issue: Character Class Escape Validation in Bulk Fact Parser Regex
- **발생 증상**: 백엔드 파서 정규식 `re.sub(r"^[\\-\\*\\•\\d\\.\\)\\s]+", "", line)` 개발 중 이스케이프 문자 표기법에 따른 매칭 예외 우려 및 이중 백슬래시(`\\`) 해석 복잡성 발생.
- **원인 분석**: 
  - 정규식 character class(`[]`) 내에서는 대부분의 특수 문자(`*`, `.`, `)` 등)가 특수한 의미를 잃고 리터럴 문자로 다루어집니다.
  - `-` 문자의 경우 클래스 범위(range)를 나타내는 특수문자로 쓰일 수 있으나, 클래스 대괄호의 맨 처음에 오게 하면 이스케이프 처리 없이도 순수 대시(`-`) 문자로 매칭됩니다.
- **해결 조치**:
  - `re.sub` 내 정규식 패턴을 간소화하고 테스트 코드(`test_bulk_fact_parser.py`)를 가동하여, 숫자 불릿(`1.`), 대시 불릿(`-`), 도트 불릿(`•`) 및 연속 공백이 있는 문장이 깨끗하게 잘 쪼개져 팩트 텍스트만 추출되는지 입증하여 이슈를 예방하였습니다.

## 2. Issue: Redundancy Concerns Between Modal Input and On-board Sourcing Panel
- **발생 증상**: 기존의 `BulkFactModal`과 새로이 추가된 `BrowserAssistedSourcePanel`이 모두 벌크 인서트를 위한 텍스트 붙여넣기를 제공하고 있어 사용자가 두 인터페이스의 용도 차이를 혼동할 가능성이 존재함.
- **원인 분석**: 
  - `BulkFactModal`은 줄 단위 입력과 더불어 `| 근거:` 라는 디테일한 근거 문자열 수동 매핑 문법을 준수해야 하는 파워 유저용 인터페이스입니다.
  - 반면 `BrowserAssistedSourcePanel`은 외부 상품 상세페이지 복사본을 마구잡이로 붙여넣었을 때, 순수 상품 스펙이나 한글 문장 단위로 자동 쪼개서 `unknown` 후보 리스트를 신속하게 벌크로 만들어주는 임시 스태이징 가이드 성격의 온보드(On-board) 패널입니다.
- **해결 조치**:
  - `facts/page.tsx` 화면에서 URL 수집 실패 안내 박스 내의 버튼("상세 정보 복사본 일괄 붙여넣기 📋")을 통해 Modal을 띄울 수 있는 루트를 온전히 보존했습니다.
  - 동시에 그 하단에 `BrowserAssistedSourcePanel`을 정적으로 고정 렌더링함으로써, 복잡한 파이프라인 문법(`| 근거:`)을 모르는 일반 소싱 사용자들도 직관적으로 드래그 복사 후 온보드에서 AI 후보 카드를 만들어낼 수 있도록 두 입력을 역할에 따라 유기적으로 안착시켰습니다.
