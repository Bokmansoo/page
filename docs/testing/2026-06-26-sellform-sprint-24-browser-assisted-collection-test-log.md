# Sellform Sprint 24 Browser Assisted Collection Test Log

## 1. Test Overview
- **테스트 일시**: 2026-06-26
- **테스트 환경**: Local 개발 환경 (Next.js FE + FastAPI BE)
- **테스트 대상**: `parse_bulk_fact_text` 파서 모듈 및 `BrowserAssistedSourcePanel` 프론트엔드 컴포넌트 연동 흐름
- **목표**: 사용자가 복사 붙여넣은 텍스트를 줄바꿈 및 불릿 필터링 처리해 팩트 카드로 잘 쪼개어 `/facts/bulk` API로 안전하게 인서트하는지 유효성 검증.

## 2. Automated Tests Results

### A. Bulk Fact Parser 단위 테스트
- **실행 명령**:
  ```powershell
  backend\.venv\Scripts\python.exe -m pytest backend\tests\test_bulk_fact_parser.py -v
  ```
- **결과**: `1 passed`
- **테스트 케이스 요약**:
  - `test_parse_bulk_fact_text_splits_lines_and_colon_specs`: 콜론 스펙 문자열, 줄바꿈, 다중 공백 및 숫자/불릿 기호가 섞인 원천 복사 텍스트가 주어졌을 때 핵심 문장들("모델명: FAN JET ULTRA", "배터리: 4,800mAh", "최대 18시간 무선 사용 가능", "USB-C 충전 지원")로 고유 파싱되는지 검증 (PASS).

## 3. Manual Verification & QA (Frontend)

### A. BrowserAssistedSourcePanel 렌더링 및 기능 검증
- **테스트 조건**: 프로젝트의 URL 분석 실패 시나리오 유도.
- **결과**:
  1. `Sourcing 근거 자료` 영역 옆에 `BrowserAssistedSourcePanel`이 경고 조건에 맞추어 정상 노출됨을 확인했습니다.
  2. 원본 링크가 설정된 경우 새 탭으로 여는 CTA 링크가 정확히 렌더링되고 연결됩니다.
  3. 좌측 텍스트 상자에 스펙 문구 다수를 붙여넣고 `여러 사실 후보로 변환하기`를 클릭하면, 줄 단위로 정제된 결과물이 우측 미리보기 영역에 카드로 조각조각 분할 렌더링됨을 검증했습니다.
  4. 우측 미리보기 카드의 개별 `✕` 버튼을 누르면 실시간으로 리스트에서 제외됩니다.
  5. `사실 검증 대기 후보로 저장하기`를 클릭하면 `/api/v1/projects/[id]/facts/bulk` API를 호출하여, 중복은 건너뛰고 새 팩트는 `unknown` 검증 대기 상태로 DB에 적재 후 성공 콜백을 받아 부모 리스트에 병합 리프레시되는 플로우를 통과하였습니다.

### B. New Project Wizard 수동 가이드 보강 검증
- **테스트 조건**: 공급처 URL 분석 검증 실패(오류 코드: SOURCE_EXTRACTION_UNAVAILABLE) 유도.
- **결과**:
  - 수동 입력 폼 상단에 새로 보강된 💡 수동 정보 입력 가이드(소비전력, 규격 등 3개 이상의 핵심 사실 수집 가이드 및 이미지 첨부 OCR 팁)가 가시성이 확보된 형태로 정상 렌더링되는지 확인했습니다 (PASS).

## 4. Conclusion
단위 테스트와 컴포넌트 바인딩 및 가이드 UI 갱신이 모두 올바르게 완료되었습니다.
