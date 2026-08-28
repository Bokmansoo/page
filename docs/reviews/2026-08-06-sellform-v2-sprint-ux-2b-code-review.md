# Sellform V2 UX-2B Code Review

Date: 2026-08-06  
Scope: API 없는 승인 스펙 기반 한국어 판매 카피

## Review result

UX-2B 완료 기준을 코드와 테스트로 다시 대조했고, Mock 생성 경로에서 충족됨을 확인했다.

- 승인된 `ProductFact`만 카피·정보 카드·최종 사양표의 수치 근거로 사용한다.
- 내부 필드 키는 고객용 한국어 표시명으로 변환한다. 미등록 키도 영문 키를 노출하지 않고 `확인된 상품 정보`로 표시한다.
- `제품 크기`·`무게`는 본체, 개별 포장, 외박스 범위를 구분하고 모델 옵션을 함께 표시한다.
- 핵심 정보 3개는 표시명이 중복되지 않는 사실을 우선 선택한다.
- 충전 사실이 있을 때만 `충전·전원 정보 확인`을 사용한다. 전원 사실만 있으면 `전원·사용 정보 확인`, 관련 사실이 없으면 `사용 전 안내`를 사용한다.
- 구성품·주의사항·모델 옵션은 판매자 입력을 승인 사실로 저장한 뒤에만 출력한다.
- 핵심 정보, 전원/사용 안내, 구성품/주의사항, 마지막 사양표는 연결된 사실 ID를 저장한다. 생성 원본 버전과 복원 후에도 이 연결을 보존한다.
- 결과 화면의 실제 상세페이지 블록에서 제목·본문을 바로 수정할 수 있고, 연결된 사실 문구를 함께 표시한다.
- 인증·안전·치료·보증·A/S 관련 무근거 표현은 첫 저장에서 경고한다. 사용자가 사실 근거를 재확인한 뒤 명시적으로 다시 저장할 때만 해당 확인 기록을 섹션에 남긴다.
- 판매자 설명의 무근거 표현과 숫자 스펙은 HERO 보조 문구에 그대로 복사하지 않는다. 수치 정보는 근거가 연결된 섹션에서만 표시한다.
- 공급처·URL 이미지는 UX-2A 정책대로 최종 출력에서 제외한다.

## Verification

```text
.venv/Scripts/python.exe -m pytest tests/test_agent_run_api.py tests/test_page_readiness_service.py tests/test_ux2b_rule_based_copy.py tests/test_ux2_mock_output.py tests/test_mock_agent_generation.py -q -p no:cacheprovider
```

Result: **41 passed**.

```text
npm.cmd run lint
```

Result: passed. 기존 React Hook 의존성 및 `<img>` 관련 경고만 출력됐다.

```text
npx.cmd playwright test e2e/ux2-mock-output.spec.ts --reporter=line
```

Result: 편집·저장·다운로드 테스트 본문은 실패 없이 완료됐고 실패 산출물도 남지 않았다. 이 로컬 환경에서는 Playwright가 개발 서버 종료를 기다리며 명령이 시간 초과되는 기존 현상이 있다.

## Coverage

- 한국어 필드명, 영문 내부 키 비노출, 조사 문장 생성
- 본체/외박스·모델 옵션 구분과 중복 핵심 정보 방지
- 충전 사실 부재 시 충전 표현 미생성
- 숫자 HERO 문구 미연결 방지, 구성품·주의사항 사실 연결
- 무근거 표현 경고 → 명시적 재확인 저장 API
- 원본 버전 복원 뒤 사실 ID 보존
- 결과 화면 인라인 편집 → 저장 → PNG 다운로드 요청 E2E

## Intentional boundary

UX-2B는 규칙형 한국어 초안 생성기다. 사람 사용 장면·충전 장면 같은 이미지를 만들지 않는다. UX-2C에서 LLM·이미지 API를 연결하더라도 사실 연결, 금지 표현 검토, 마지막 사양표, 인라인 편집과 복원 정책은 그대로 유지한다.
