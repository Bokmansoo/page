# Sprint 29 이미지 중심 렌더링 트러블슈팅

## 문제 1: export_service 테스트 실행 시 AttributeError `PageGenerationService` object has no attribute `_get_mock_page` 발생

### 원인
- `_short_fact_summary` 헬퍼 함수를 파일 전역 영역에 삽입하면서, 기존 클래스 내부의 `_get_mock_page` 및 `_get_problem_solution_mock_page` 메서드들의 들여쓰기가 전역 스코프로 오인되었습니다.
- 파이썬 컴파일러가 해당 메서드들을 클래스 외부 함수로 해석해 `PageGenerationService` 인스턴스에서 호출 시 `AttributeError`가 발생했습니다.

### 해결
- `_short_fact_summary`를 `PageGenerationService` 클래스 내부에 `@staticmethod` 데코레이터를 붙여 정적 메서드로 소속을 고정시켰습니다.
- 이를 통해 들여쓰기 꼬임 현상을 원천 방지하고, 클래스 내부의 다른 메서드들이 온전히 `self._short_fact_summary` 로 안정적으로 호출되도록 구조를 개선했습니다.

---

## 문제 2: export 결과 첫 화면이 1200px 미만의 불충분한 세로 높이로 검출되어 테스트 실패 (`assert 780 >= 1200`)

### 원인
- 기존의 단순 텍스트 카드 높이 계산 방식을 유지한 상태에서 export를 구동하면, 3개의 짧은 섹션일 때 총 세로 이미지 높이가 780px 정도에 그쳤습니다.
- 이미지 중심 고도화 레이아웃 요건상, 히어로는 500px, 본문은 이미지 플레이스홀더를 동반해 최소 550px을 확보해야 했습니다.

### 해결
- `run_export`에서 각 `visual_section`의 레이아웃 성격(`hero`인 경우 `max(500, ...)`, 일반 이미지 텍스트인 경우 `max(550, ...)` 등)에 따른 최소 영역 높이 가중치를 분기 적용하여 렌더링을 교체했습니다.
- 이를 통해 3개의 간단한 섹션만 내보내더라도 1400px 이상의 충분한 세로 상세페이지 비주얼 스케일을 확보하여 테스트 단언 조건(1200px 이상)을 안정적으로 패스했습니다.
