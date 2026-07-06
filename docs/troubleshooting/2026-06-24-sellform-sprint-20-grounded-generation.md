# Grounded Page Generation Validation Troubleshooting Log

## 1. 팩트 카드 매핑 정밀도 이슈 (False Positive)

### 문제 상황
* 기획상의 `map_section_to_facts` 최소 구현 코드에서 각 확인된 사실 카드의 토큰 중 하나라도 섹션 본문에 포함되면 (`any()`) 매핑되는 단순 비교 방식을 사용했습니다.
* 이로 인해, `"휴대용 무선 냉각 선풍기"`와 같이 여러 단어로 이루어진 사실 카드가 있을 때, 섹션 본문에 단순 `"무선"`이라는 단어 하나만 출현해도 정합성 여부와 무관하게 해당 사실 카드가 매핑되는 오탐(False Positive) 현상이 테스트 중 감지되었습니다.
* 테스트 실패 메시지:
  ```text
  AssertionError: assert ['4,800mAh 배터...대용 무선 냉각 선풍기'] == ['4,800mAh 배터...대 18시간 무선 사용']
  Left contains one more item: '휴대용 무선 냉각 선풍기'
  ```

### 원인 분석
* 사실 카드의 공통적인 기능 용어(예: "무선", "배터리")가 일치할 때, 카드의 지배적인 핵심 주장(예: "휴대용 냉각 선풍기")이 누락되어 있음에도 매핑으로 처리되었습니다.

### 해결 방안
* 단순히 `any()` 매칭을 적용하는 대신, **키워드 오버랩 비율 임계치(Keyword Overlap Ratio Threshold)** 기법을 도입했습니다.
* 사실 카드에서 의미 있는 단어(길이 2 이상인 토큰)를 추출한 뒤, 해당 키워드들 중 **최소 50% 이상**이 섹션 텍스트 내에 실제로 등장하는 경우에만 올바르게 근거 카드로 인정되도록 로직을 고도화했습니다.
* 적용 코드:
  ```python
  matching_count = sum(1 for keyword in keywords if keyword.replace(" ", "").lower() in normalized_text)
  if matching_count / len(keywords) >= 0.5:
      matched.append(fact)
  ```
* 결과적으로 `"4,800mAh 배터리"`(100%), `"최대 18시간 무선 사용"`(100%)은 정확히 매핑되고, 단어 매칭률이 25%에 불과한 `"휴대용 무선 냉각 선풍기"`는 정상 차단되어 오탐을 완벽히 방어하였습니다.

---

## 2. 윈도우 PowerShell 실행 정책 차단 이슈

### 문제 상황
* 프론트엔드 빌드 유효성 검증 시 `npm run build` 명령을 실행했을 때 execution policy 차단 에러 발생.
  ```text
  npm : 이 시스템에서 스크립트 실행이 비활성화되어 있으므로...
  ```

### 해결 방안
* PowerShell 별칭 경로가 아닌 Command Shell 래퍼 명령어인 `npm.cmd run build` 형식으로 Cwd 환경에서 직접 구동하여 에러를 우회하고 프론트엔드 Next.js 정적 타입 검사 빌드를 성공적으로 검증했습니다.
# 섹션 부분 재생성 결과가 저장되지 않는 이슈

## 문제 상황

Sprint 20 검증 후 전체 백엔드 회귀 테스트를 실행했을 때 다음 테스트가 실패했다.

```text
FAILED tests/test_pages_sprint4_remediation.py::test_regenerate_page_section_applies_user_instruction
```

섹션 부분 재생성 API는 `new_copy`를 정상적으로 만들었지만, 응답의 `body_copy`가 기존 문구와 동일하게 유지되었다.

## 원인 분석

`backend/src/api/pages.py`의 `regenerate_page_section` 함수에서 `new_copy`를 생성한 뒤 실제 SQLAlchemy 모델 인스턴스인 `section.body_copy`에 대입하지 않고 `db.commit()`을 호출했다.

즉, 생성 결과가 메모리 변수에만 있고 DB 객체에는 반영되지 않았다.

## 해결 방법

`db.commit()` 직전에 다음 대입을 추가했다.

```python
section.body_copy = new_copy
db.commit()
```

수정 중 동일한 `db.commit()` 패턴이 여러 함수에 존재해 잘못된 함수에 삽입될 수 있으므로, 최종적으로 `add_page_section`, `create_page_draft`, `regenerate_page_section` 주변 라인을 재확인했다.

## 검증

```powershell
uv run pytest tests/test_pages_sprint4_remediation.py::test_regenerate_page_section_applies_user_instruction -q
```

- 결과: `1 passed`

```powershell
uv run pytest -q
```

- 결과: `90 passed`

```powershell
cd frontend
npm.cmd run build
```

- 결과: `Compiled successfully`

## 교훈

API 핸들러에서 생성된 임시 변수와 ORM 모델 필드 반영은 별개다. `new_copy`, `result`, `payload`처럼 새 값을 만든 뒤에는 반드시 실제 저장 대상 필드에 대입되었는지 확인해야 한다.
