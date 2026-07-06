# Sellform Sprint 20 Grounded Page Generation Validation Code Review

## 1. 개요
* **작성일:** 2026-06-26
* **작성 대상:** Grounded Page Generation Validation 기능 구현 커밋
* **주요 변경 사항:** 상세페이지 문구의 근거(확인된 사실 카드) 연결 및 미검증/과장 위험 표현 실시간 검수 엔진 & UX 레이아웃 개발

---

## 2. 변경된 파일 목록 및 상세 설명

| 구분 | 파일 경로 | 설명 |
| :--- | :--- | :--- |
| **Backend** | [grounding_validator.py](file:///c:/page/backend/src/services/grounding_validator.py) | **[NEW]** 사실 카드 매핑, 수치/성능/안전/인증 위험 문구 경고 감지, 전체 리뷰 요약 집계 비즈니스 로직 구현 |
| **Backend** | [pages.py](file:///c:/page/backend/src/api/pages.py) | **[MODIFY]** Pydantic 응답 스키마 확장(근거 검수 통계 및 경고 세부 데이터 추가), 엔드포인트 수정 및 전용 검수 리뷰 반환 API (`/projects/{project_id}/page/grounding-review`) 설계 |
| **Backend** | [test_grounding_validator.py](file:///c:/page/backend/tests/test_grounding_validator.py) | **[NEW]** 위험 표현 분류, 사실 카드 오버랩 정밀도 매핑, 집계 및 통합 API 엔드포인트 동작 검증용 테스트 코드 구현 |
| **Frontend** | [GroundingReviewPanel.tsx](file:///c:/page/frontend/src/components/GroundingReviewPanel.tsx) | **[NEW]** 실시간 검수 통계(주의 필요 건수, 근거 연결 완료율, 팩트 카드 활용률) 및 위험 문구-수정 제안 상세 UI 컴포넌트 |
| **Frontend** | [page.tsx](file:///c:/page/frontend/src/app/workspace/projects/[id]/page-editor/page.tsx) | **[MODIFY]** 실시간 상단 요약 배너 추가, 우측 패널의 [에디터] / [근거 검수] 탭 내비게이션 구조 설계 및 컴포넌트 연동 |

---

## 3. 코드 상세 리뷰 및 핵심 비즈니스 로직

### 3.1. 백엔드: 위험 표현 탐지 및 사실 카드 매핑
* **위험 표현 탐지 ([grounding_validator.py](file:///c:/page/backend/src/services/grounding_validator.py))**
  * 성능, 효능, 수치, 안전, 건강, 인증, 비교 우위 관련 특정 위반 키워드 풀(`NUMERIC_PATTERNS`, `PERFORMANCE_PATTERNS` 등)을 사전에 정의.
  * 확정된 팩트 카드 텍스트의 공백/대소문자를 정규화하여 텍스트에 포함되어 있지 않은 경우 `GroundingWarning` 데이터 클래스(위험 문구, 위험 사유, 완화된 수정 제안) 형태로 즉각 경고 분류 수행.
* **사실 카드 매핑 알고리즘**
  * 단순 단어 매칭 오탐 문제를 완화하기 위해 사실 카드의 유효 토큰(길이 2 이상)이 최소 50% 이상 오버랩되는 경우만 참(True)으로 인정하는 Ratio 임계치 검증 로직 구현.

### 3.2. 백엔드: Pydantic 스키마 설계 및 API 리팩토링 ([pages.py](file:///c:/page/backend/src/api/pages.py))
* `SectionResponseSchema`에 `grounding_warnings` 및 `matched_facts` 필드 추가, `PageResponseSchema`에 전체 검수 통계를 담는 `grounding_summary` 필드 주입.
* `build_page_response` 및 `build_section_response` 공통 함수 내부에서 DB 세션을 참조하여 실시간으로 팩트 카드를 로드하고 검수를 통합 빌드하도록 수정하여 중복 코드 제거 및 안전성 확보.

### 3.3. 프론트엔드: 탭 및 실시간 요약 인터페이스 ([page.tsx](file:///c:/page/frontend/src/app/workspace/projects/[id]/page-editor/page.tsx))
* 상단 영역에 실시간 근거 검수 요약 헤더를 고정하여 에디팅 작업 중에도 `주의 필요`, `근거 연결`, `사실 카드 사용` 수치를 한눈에 모니터링 가능.
* 우측 상세 패널을 탭형(`activeTab` state) 구조로 분할하여 사용자가 `✏️ 섹션 에디터` 모드와 `🔍 근거 검수` 모드를 자유롭게 오갈 수 있도록 함.
* 요약 헤더의 '주의 필요' 혹은 '상세 검수 패널 열기' 버튼 클릭 시 자동으로 `activeTab`이 `grounding`으로 전환되어 사용자 여정이 자연스럽게 이어지도록 유도.

---

## 4. 검증 결과 및 피드백

1. **자동화 테스트 검증 완료:**
   * pytest의 4개 핵심 신규 테스트 및 7개 기존 상세페이지 시나리오 테스트가 전원 `PASSED`를 달성함.
2. **프론트엔드 빌드 검증 완료:**
   * Next.js 정적 프로덕션 컴파일을 이상 없이 완수하여 컴포넌트 간 TypeScript 타입 바인딩 안정성을 확보함.

---

## 5. 후속 보완 리뷰 - 섹션 부분 재생성 저장 누락 수정 (2026-06-26)

### 발견 이슈

- **심각도:** Major
- **위치:** `backend/src/api/pages.py` `regenerate_page_section`
- **내용:** 섹션 부분 재생성 API에서 `new_copy`를 생성했지만, 실제 `section.body_copy`에 대입하지 않은 채 `db.commit()`을 호출하고 있었다. 이로 인해 사용자가 “AI 섹션 부분 수정”을 실행해도 응답의 본문 카피가 기존 값과 동일하게 유지되었다.
- **영향:** Sprint 20의 근거 검수 패널 자체는 동작하지만, page editor의 부분 수정 UX가 회귀되어 상세페이지 편집 플로우 신뢰도를 떨어뜨릴 수 있었다.

### 조치 내용

- `regenerate_page_section`에서 `db.commit()` 직전에 `section.body_copy = new_copy`를 명시적으로 저장하도록 수정했다.
- 잘못된 위치에 삽입될 수 있는 동일 패턴(`db.commit()`)을 재확인해 `add_page_section` 및 `create_page_draft` 흐름에는 불필요한 변경이 남지 않도록 정리했다.

### 재검증 결과

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

### 최종 판정

후속 보완 후 Sprint 20은 기획서의 핵심 범위인 “확정 사실 기반 상세페이지 생성 검수, 위험 문구 경고, 섹션별 근거 확인, 프론트 검수 패널”을 충족하며, 전체 백엔드 테스트와 프론트 빌드가 통과했다.
