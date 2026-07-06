# Sellform Sprint 19 Style Strategy Selection Troubleshooting

본 문서는 Sprint 19 (Style Strategy Selection) 개발 및 테스트, 빌드 과정에서 마주친 트러블슈팅과 대책을 기록합니다.

---

## 1. 직면한 오류 및 해결 조치

### Issue 1: Pydantic 엔드포인트 응답 검증 에러 (`ValidationError`)

* **증상:** `GET /projects/{project_id}/style-candidates` API 호출 시 다음과 같은 validation error 발생:
  ```text
  pydantic_core._pydantic_core.ValidationError: 3 validation errors for StyleCandidatesResponse
  candidates.0
    Input should be a valid dictionary or instance of StyleCandidateResponse [type=model_type, input_value=StyleCandidate(...)]
  ```
* **원인 분석:**
  - `generate_style_candidates` 서비스에서 리턴하는 객체 타입은 Python `@dataclass`인 반면, FastAPI router의 `response_model`은 Pydantic `StyleCandidatesResponse`였습니다.
  - Pydantic v2는 `@dataclass`를 자동으로 Pydantic schema 객체 리스트로 매핑할 때, `from_attributes=True` 설정이 없거나 native mapping이 실패하면 해당 개체를 딕셔너리로 해석하지 못해 type error를 뱉어냅니다.
* **해결 조치:**
  - API 라우터(`pages.py`)에서 candidates 리턴 데이터를 직렬화하기 전에 명시적인 List Comprehension을 사용해 `StyleCandidateResponse` Pydantic 모델 인스턴스 배열로 매핑한 후 리턴하도록 수정했습니다.
  ```python
  candidates_res = [
      StyleCandidateResponse(
          key=c.key,
          name=c.name,
          ...
      )
      for c in candidates
  ]
  ```

### Issue 2: Next.js Production Build 실패 (ESLint `react/no-unescaped-entities`)

* **증상:** `npm run build` 빌드 검증 수행 중 아래와 같이 컴파일 에러 발생:
  ```text
  ./src/components/StyleCandidateSelector.tsx
  134:21  Error: `"` can be escaped with `&quot;`, `&ldquo;`, `&#34;`, `&rdquo;`.  react/no-unescaped-entities
  ```
* **원인 분석:**
  - `StyleCandidateSelector.tsx` 파일 내에서 리터럴 큰따옴표(`"`)를 이스케이프 처리하지 않은 상태로 JSX 태그 안에 직접 렌더링하도록 배치하여 Next.js의 strict eslint parser가 에러를 검출했습니다.
* **해결 조치:**
  - `"{c.preview_summary}"` 형태를 HTML 엔티티 코드로 변환하여 `&quot;{c.preview_summary}&quot;`로 갱신하여 해결했습니다.

---

## 2. 향후 운영 팁 (Operational Tips)

1. **하위 호환성 유지 (API Fallback):**
   - 레거시 API 연동이나 테스트 스위트에서는 스타일 선택 과정을 생략하고 바로 `/page` 초안 생성을 호출하므로, `selected_style` 값이 DB 상에 NULL인 경우에 대비하여 기본값인 `"problem_solution"` 스타일을 자동으로 백엔드가 지정하도록 구성하여 regression 우려를 원천 봉쇄하였습니다.
2. **ESLint 사전 검사 권장:**
   - JSX 내에 인용구나 괄호, 따옴표 등을 표기할 경우, 가급적 문자열 식(`{"\""}`)이나 표준 HTML entity를 사용하여 타입 안전성을 극대화하십시오.

---

## 3. 후속 보완 - 잘못된 스타일 키 저장 방지

### 증상

스타일 선택 API가 `candidate_key`를 그대로 저장하면 `problem_solution`, `spec_focused`, `lifestyle` 외의 잘못된 값도 `ProductProject.selected_style`에 들어갈 수 있습니다.

### 원인

초기 구현은 프론트엔드 선택 UI를 신뢰했고, 백엔드 선택 API에서 후보 키의 유효성을 별도로 검증하지 않았습니다.

### 조치

- `STYLE_CANDIDATE_KEYS = {"problem_solution", "spec_focused", "lifestyle"}`를 정의했습니다.
- `is_valid_style_candidate_key(candidate_key)` helper를 추가했습니다.
- 선택 API에서 유효하지 않은 키를 `400 Bad Request`로 거부하도록 수정했습니다.
- 통합 테스트로 잘못된 키가 DB에 저장되지 않는지 확인했습니다.
