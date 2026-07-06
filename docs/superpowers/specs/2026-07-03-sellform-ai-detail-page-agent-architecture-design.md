# Sellform 최종 기획: AI 상세페이지 생성 에이전트

> 상태: 2026-07-03 제품 인터뷰 기반 최종 기획 초안
> 범위: Sellform을 편집기 중심 워크스페이스에서 AI 상세페이지 생성 서비스로 재정의
> 핵심 결정: 제품의 중심을 수동 편집기가 아니라 AI 생성 파이프라인으로 옮긴다.

## 1. 제품 정의

Sellform은 1인 셀러를 위한 **AI 상세페이지 생성 서비스**다.

사용자는 상품 사진, 상품 URL, 상품명, 간단한 설명 중 가지고 있는 자료만 입력하면 된다. Sellform은 그 자료를 바탕으로 상품을 이해하고, 어떤 방향으로 팔아야 하는지 판단하고, 상세페이지 문구를 작성하고, 필요한 이미지 연출을 기획하고, 이미지를 생성하거나 편집한 뒤, 긴 모바일 상세페이지로 조립한다. 이후 사용자는 결과물을 검수하고 수정한 뒤 PNG, Figma, 카피 세트, 마켓플레이스 등록 데이터로 출력할 수 있다.

Sellform의 최종 제품은 다음이 아니다.

- Figma 내보내기 도구
- 수동 템플릿 편집기
- 마켓플레이스 등록 폼
- 범용 이미지 생성기

이 기능들은 모두 보조 출력물이다. 제품의 핵심 약속은 다음이다.

**상품 자료를 넣으면 AI가 팔릴 만한 상세페이지를 기획하고 만들어준다.**

## 2. 목표 사용자

주 사용자는 상품은 있지만 어떻게 팔아야 할지 모르는 1인 셀러다.

이 사용자는 보통 이렇게 생각한다.

- "상세페이지를 어떤 순서로 구성해야 할지 모르겠다."
- "이 상품의 장점을 어떻게 써야 사람들이 사고 싶어질지 모르겠다."
- "사진은 있는데 배경이나 연출을 어떻게 해야 할지 모르겠다."
- "스마트스토어에 올리고 싶은데 상품명, 태그, 상세페이지, 이미지가 막막하다."
- "디자이너나 마케터 없이 혼자서 판매 가능한 수준까지 만들고 싶다."

Sellform은 빈 디자인 툴이 아니라, 판매 결정을 도와주는 AI MD처럼 느껴져야 한다.

## 3. 최종 사용자 경험

최종 경험은 사용자가 참고로 올렸던 19장의 상세페이지 생성 서비스 흐름과 가까워야 한다.

1. 사용자는 단순한 AI 상세페이지 생성 화면에서 시작한다.
2. 상품 사진을 업로드하거나 상품 URL/상품명을 입력한다.
3. AI가 상품을 분석하고, 무엇을 이해했는지 보여준다.
4. AI가 판매 방향을 추천하고, 사용자는 이를 확인하거나 조정한다.
5. AI가 셀링 포인트, 상세페이지 섹션 흐름, 이미지 연출 방향을 제안한다.
6. 비용 승인을 거친 뒤 필요한 이미지를 생성하거나 준비한다.
7. 사용자는 생성되거나 선택된 이미지를 검수한다.
8. Sellform이 긴 모바일 상세페이지를 자동 조립한다.
9. 사용자는 AI 명령으로 문구, 이미지, 섹션을 수정한다.
10. 사용자는 PNG, Figma, 카피 세트, 마켓플레이스 등록 데이터를 출력한다.

첫 성공 경험은 "편집기를 열었다"가 아니어야 한다.

첫 성공 경험은 다음이어야 한다.

**"AI가 내 상품을 이해했고, 판매 방향과 상세페이지 초안을 만들어줬다."**

## 4. 현재 구조의 문제

현재 구현에는 유용한 기능이 많다. 하지만 제품의 중심이 잘못 놓여 있다.

현재 중심:

```text
workspace -> project -> facts/style/page editor -> visual package -> export
```

이 구조는 사용자에게 너무 빨리 후반 작업 도구를 보여준다. 사용자는 AI가 상품을 이해하고 판매 전략을 만들어주는 경험을 하기 전에, 이미지가 비어 있는 편집기를 먼저 보게 된다.

목표 중심:

```text
product input -> AI generation pipeline -> complete detail page draft -> review editor -> export/register
```

기존 편집기는 처음 화면이 아니라, 상세페이지 생성 이후의 검수/수정 단계가 되어야 한다.

## 5. 권장 아키텍처

명확한 상태 전이를 가진 에이전트형 파이프라인을 사용한다.

이 제품에는 LangGraph 또는 LangGraph와 유사한 상태 그래프 구조가 잘 맞는다. 상세페이지 생성은 단일 LLM 호출이 아니라, 분기, 재시도, 사용자 확인, 비용 승인, mock/real 실행 모드, 품질 검수 게이트가 필요한 작업이기 때문이다.

권장 생성 상태:

```text
intake
  -> product_understanding
  -> missing_info_check
  -> sales_strategy
  -> user_strategy_confirmation
  -> page_planning
  -> copy_generation
  -> visual_planning
  -> image_cost_approval
  -> image_generation
  -> image_review
  -> page_assembly
  -> qa_review
  -> review_editor
  -> export_package
```

각 상태는 프로젝트에 저장되어야 한다. 사용자는 중간에 나갔다가 돌아올 수 있어야 하고, 실패한 단계를 다시 실행할 수 있어야 하며, 로컬 개발에서는 mock mode로 계속 진행할 수 있어야 한다.

## 6. 에이전트 역할

Sellform은 "상세페이지 만들어줘"라는 하나의 거대한 프롬프트로 동작하면 안 된다. 역할을 분리해야 품질과 제어가 좋아진다.

### 6.1 상품 이해 에이전트

입력:

- 업로드된 상품 사진
- URL에서 수집한 상품 정보
- 사용자가 입력한 상품명 또는 설명
- 선택 입력된 경쟁 상품/참고 링크

출력:

- 상품 유형
- 목표 고객
- 구매자가 겪는 문제
- 구매자가 망설이는 이유
- 검증된 사실
- 추정한 정보
- 금지되거나 위험한 표현
- 대표 이미지 후보

이 에이전트는 **확인된 사실**과 **추정**을 반드시 분리해야 한다.

### 6.2 판매 전략 에이전트

입력:

- 상품 이해 결과
- 셀러의 판매 목표
- 마켓플레이스 맥락
- 카테고리 힌트

출력:

- AI 추천 판매 방향 1개
- 대안 판매 방향 2개
- 메인 소구점
- 보조 소구점
- 감성 톤
- 근거 제시 방식
- 추천 이유

예시 방향:

- 문제 해결형
- 감성/라이프스타일형
- 스펙/신뢰 강조형

### 6.3 상세페이지 설계 에이전트

입력:

- 선택된 판매 방향
- 상품 사실
- 목표 고객

출력:

- 상세페이지 섹션 순서
- 섹션별 목적
- 섹션별 문구 의도
- 섹션별 이미지 역할
- 섹션별 필요한 사실 ID

기본 설득 구조:

1. 문제 제기
2. 메인 소구점
3. 보조 장점
4. 근거, 사용 장면, 비교 등을 통한 메인 메시지 보강
5. 나머지 장점 정리
6. 한 문장 요약
7. 상품 정보와 구매 판단 정보

단, 이 구조는 카테고리에 따라 달라져야 한다. 유아용품, 생활가전, 식품, 패션, 디지털 액세서리가 모두 같은 흐름이어서는 안 된다.

### 6.4 카피라이팅 에이전트

입력:

- 상세페이지 설계 결과
- 검증된 사실
- 선택된 톤

출력:

- 히어로 제목
- 히어로 서브카피
- 섹션 제목
- 본문 카피
- 이미지 캡션
- 배지 문구
- FAQ 문구
- 상품 정보 문구
- CTA
- 스마트스토어 상품명
- 검색 태그
- SEO 제목과 설명

사실성 있는 문구는 검증되었거나 사용자가 승인한 정보에 근거해야 한다. 확인되지 않은 주장은 피하거나 검토 대상으로 표시한다.

### 6.5 이미지 기획 에이전트

입력:

- 상세페이지 설계 결과
- 카피 세트
- 상품 정체성 정보
- 선택된 상품 이미지

출력:

- 이미지 역할
- 이미지 생성 프롬프트
- 참고 이미지 요구사항
- 상품 정체성 보존 규칙
- 배경/스타일 방향
- 이미지별 예상 비용

이미지 역할 예시:

- 대표 상품 컷
- 배경 제거 상품 컷
- 라이프스타일 사용 장면
- 문제 제기 장면
- 장점 강조 이미지
- 디테일 클로즈업
- 비교표
- 전/후 또는 before/after 시각화
- 아이콘/배지 세트
- 중간 CTA 이미지

### 6.6 이미지 생성 에이전트

입력:

- 이미지 기획 결과
- 승인된 이미지 생성 작업
- 상품 참고 이미지

출력:

- 생성된 이미지 자산
- 편집된 이미지 자산
- 실패한 작업과 이유
- 대체 자산 추천

규칙:

- 상품이 포함된 이미지는 상품 정체성을 보존해야 한다.
- 실제 상품이 등장하는 장면은 가능한 한 참고 이미지 기반 편집을 사용한다.
- 마케팅 문구, 가격, 인증마크, 로고는 이미지 안에 직접 구워 넣지 않고 편집 가능한 페이지 레이어로 둔다.
- 유료 생성 요청은 반드시 명시적 비용 승인을 거친다.
- mock mode에서는 크레딧을 쓰지 않는 결정적 placeholder 이미지를 만든다.

### 6.7 조립 에이전트

입력:

- 상세페이지 설계 결과
- 카피 세트
- 승인된 이미지 자산
- 선택된 템플릿/레이아웃 규칙

출력:

- 완성된 긴 모바일 상세페이지 초안
- 섹션과 이미지 자산 매핑
- 페이지 버전
- 출력 준비 체크리스트

페이지에는 빈 placeholder가 아니라 실제 문구와 실제 이미지 섹션이 보여야 한다.

### 6.8 QA 에이전트

입력:

- 조립된 상세페이지
- 카피 세트
- 이미지 자산
- 컴플라이언스 규칙

출력:

- 누락 이미지 경고
- 검증되지 않은 주장 경고
- 과장 표현 경고
- 마켓플레이스 준비 미비 항목
- 출력 차단 사유
- 수정 제안

QA는 최종 출력 전에 반드시 실행되어야 한다.

## 7. 프롬프트 시스템 설계

프롬프트는 버전 관리되고, 구조화된 출력 계약을 가져야 한다.

권장 프롬프트 구성:

```text
prompts/
  system/
    sellform_agent_base.md
    commerce_claim_safety.md
    product_identity_safety.md
  agents/
    product_understanding.md
    sales_strategy.md
    page_planning.md
    copywriting.md
    visual_planning.md
    qa_review.md
  schemas/
    product_understanding.schema.json
    sales_strategy.schema.json
    page_plan.schema.json
    copy_set.schema.json
    visual_plan.schema.json
    qa_report.schema.json
```

시스템 프롬프트는 다음을 정의해야 한다.

- Sellform의 역할: 1인 셀러를 돕는 AI MD
- 사실 기반 작성 규칙
- 마켓플레이스 안전 문구 규칙
- 이미지 생성 안전 규칙
- JSON 출력 형식
- 한국어 커머스 카피 톤
- 정보가 부족할 때의 질문/대체 처리 방식

사용자 UI는 원본 프롬프트를 보여주면 안 된다. 대신 다음처럼 이해하기 쉬운 단계명으로 보여준다.

- 상품 분석 중
- 판매 방향 생성 중
- 상세페이지 구조 설계 중
- 문구 생성 중
- 이미지 연출 기획 중
- 상세페이지 조립 중

### 7.1 LLM Provider 전략

1차 구현은 OpenAI GPT 계열을 기본 provider로 사용한다. 다만 에이전트 코드가 특정 provider에 직접 묶이면 안 된다. 모든 LLM 호출은 `llm_router` 또는 provider adapter를 통해 실행하고, provider별 응답은 공통 출력 스키마로 검증한다.

권장 provider 구성:

```text
Text LLM
  Primary: OpenAI GPT 계열
  Fallback 1: Gemini 2.5 Flash
  Fallback 2: Claude 계열

Vision/Product Understanding
  Primary: OpenAI vision-capable model
  Fallback: Gemini 2.5 Flash

Image Generation/Edit
  Primary: OpenAI image generation/editing model
  Fallback: 추후 provider adapter로 확장
```

역할 분담:

- OpenAI GPT 계열: 상품 이해, 판매 전략, 상세페이지 구조 설계, 카피 생성, 이미지 프롬프트 생성의 1차 모델
- Gemini 2.5 Flash: 빠른 재시도, 비용 절감형 fallback, URL/상품 설명 기반 텍스트 분석 보조
- Claude 계열: 긴 문맥 카피라이팅, 문구 다듬기, 안전한 표현 검토 fallback
- OpenAI 이미지 모델: 상품 참고 이미지 기반 이미지 생성/편집의 1차 provider

운영 원칙:

- mock mode에서는 어떤 provider도 호출하지 않는다.
- real mode에서만 API 키, 비용 승인, provider 설정을 확인한 뒤 호출한다.
- provider 실패 시 fallback 순서에 따라 재시도하되, 각 실패 사유와 비용 사용 여부를 기록한다.
- JSON 구조화 출력이 깨진 경우 provider fallback 이전에 schema validation과 repair 시도를 먼저 수행한다.
- 이미지 생성 provider는 텍스트 LLM provider와 분리해서 관리한다.
- 상품 정체성이 중요한 이미지는 텍스트-only 이미지 생성보다 reference-image editing을 우선한다.

## 8. 데이터 계약

파이프라인은 프론트엔드가 렌더링하고 편집기가 수정할 수 있는 구조화 데이터를 만들어야 한다.

핵심 엔티티:

- `AgentRun`
- `ProductInput`
- `ProductUnderstanding`
- `SalesDirection`
- `SalesStrategySet`
- `DetailPagePlan`
- `CopySet`
- `VisualPlan`
- `ImageGenerationJob`
- `GeneratedAsset`
- `PageAssembly`
- `QAReport`
- `ExportPackage`

생성된 각 섹션은 다음 참조를 유지해야 한다.

- `section_id`
- `section_role`
- `copy_ids`
- `fact_ids`
- `visual_role`
- `image_asset_id`
- `claim_risk_level`

이 구조가 있어야 상세페이지를 편집, 검수, 재생성, 출력할 수 있다.

### 8.1 AgentRun 저장 계약

Sellform은 "프로젝트"와 "AI 생성 실행"을 분리해서 저장해야 한다. 하나의 상품 프로젝트에서 여러 번 AI 생성, 재생성, 실패 후 재시도, 다른 판매 방향 생성을 실행할 수 있기 때문이다.

권장 저장 단위:

```text
Workspace
  -> ProductProject
    -> AgentRun
      -> AgentRunStep
      -> ProductInput snapshot
      -> ProductUnderstanding output
      -> SalesStrategy output
      -> DetailPagePlan output
      -> CopySet output
      -> VisualPlan output
      -> QAReport output
      -> generated DetailPageVersion
      -> generated Assets
```

`AgentRun`은 다음 정보를 반드시 가진다.

- `id`
- `workspace_id`
- `project_id`
- `mode`: `mock` 또는 `real`
- `status`: `created`, `running`, `waiting_for_user`, `waiting_for_cost_approval`, `completed`, `failed`, `cancelled`
- `current_stage`
- `input_snapshot`
- `outputs_json`
- `cost_approval_status`
- `estimated_cost`
- `actual_cost`
- `provider_trace`
- `error_log`
- `created_by`
- `created_at`
- `updated_at`
- `completed_at`

`AgentRunStep`은 각 단계별 진행 이력이다.

- `run_id`
- `stage`
- `status`
- `input_json`
- `output_json`
- `provider`
- `model`
- `prompt_version`
- `token_usage`
- `estimated_cost`
- `started_at`
- `completed_at`
- `error_message`

이 구조가 있어야 "AI가 지금 어디까지 했는지", "어느 단계에서 실패했는지", "비용이 어디서 발생했는지", "이전 결과로 되돌릴 수 있는지"를 관리할 수 있다.

### 8.2 데이터 저장 위치와 생애주기

데이터 저장은 다음 원칙을 따른다.

- 구조화 데이터는 PostgreSQL에 저장한다.
- 업로드 이미지, 생성 이미지, PNG export, zip export는 파일 스토리지에 저장하고 DB에는 `Asset` 또는 `ExportArtifact`로 경로와 메타데이터를 저장한다.
- 원본 상품 URL에서 수집한 정보는 `ProductInput` 또는 `ProductFact`에 출처와 함께 저장한다.
- AI가 추정한 정보와 사용자가 확인한 정보는 분리한다.
- 사용자가 최종 지정한 상세페이지는 `DetailPageVersion.is_final = true`로 관리한다.
- AI 호출 로그와 비용 로그는 `AiJobLog`와 `AgentRunStep`에 남긴다.

삭제 정책:

- 프로젝트 삭제 시 해당 프로젝트의 `Asset`, `ProductFact`, `AgentRun`, `DetailPageVersion`, `ExportArtifact`, `ImageGenerationJob`도 함께 삭제 대상이 된다.
- 워크스페이스 삭제 시 모든 프로젝트와 자산이 삭제 대상이 된다.
- 사용자가 특정 업로드 이미지를 삭제하면 해당 이미지를 참조하는 섹션은 `image_asset_id = null` 또는 대체 이미지 필요 상태로 바뀐다.
- 최종본으로 지정된 상세페이지를 삭제하려면 먼저 최종본 해제 또는 다른 버전 지정이 필요하다.
- 실제 서비스에서는 물리 삭제 전 일정 기간 soft delete를 둘 수 있지만, 로컬/개발 구현에서는 우선 관계형 cascade와 명시적 파일 삭제 작업으로 시작한다.

보안/관리 원칙:

- 모든 데이터 조회는 `workspace_id` 기준으로 격리한다.
- API 키는 DB에 저장하지 않고 환경 변수 또는 secret manager에서만 읽는다.
- 프롬프트 원문과 provider 응답은 디버깅에 필요한 범위만 저장하고, 상품 이미지 원본을 외부 provider에 보낸 경우 provider와 전송 목적을 로그에 남긴다.
- mock mode에서는 외부 provider 호출 기록이 생기면 안 된다.

## 9. Mock Mode와 Real Mode

Sellform은 두 가지 실행 모드를 지원해야 한다.

### Mock Mode

개발, 데모, 크레딧 없는 테스트에 사용한다.

- 결정적인 상품 이해 샘플
- 결정적인 판매 전략 샘플
- placeholder 이미지 자산
- 외부 LLM/API 호출 없음
- 개발자용 mock mode 표시

Mock mode도 제품 경험의 신뢰를 깨면 안 된다. 사용자가 `삼탠바이미`를 입력했는데 자전거, 마사지, 의류 같은 무관한 샘플 상품이 결과에 섞이면 안 된다. Mock 결과는 실제 API를 쓰지 않더라도 다음 원칙을 따른다.

- 상품명, 설명, URL, 업로드 이미지 파일명을 결과 문구와 섹션 제목에 반영한다.
- 업로드 이미지가 있으면 상세페이지 preview의 대표 이미지와 섹션 이미지 후보에 우선 사용한다.
- 업로드 이미지가 없을 때만 neutral commerce placeholder를 사용한다.
- mock-generated 이미지는 `mock-generated`, 업로드 이미지는 `uploaded`, URL 추출 이미지는 `url-extracted`로 출처를 표시한다.
- mock preview에는 다른 상품 카테고리의 fixture 이미지를 섞지 않는다.
- mock mode에서도 결과 화면은 실제 상세페이지 초안처럼 보여야 하며, "테스트용 더미 데이터"처럼 느껴지면 안 된다.

### Real Mode

API 키와 비용 승인이 있을 때만 사용한다.

- 실제 LLM 호출
- 실제 비전/이미지 분석
- 실제 이미지 생성 또는 편집
- 비용 추적
- 재시도와 provider fallback
- 오류 보고

로컬 개발 기본값은 반드시 mock mode여야 한다. 사용자가 명시적으로 real mode를 켜지 않는 한 API 크레딧이 사용되면 안 된다.

## 10. 프론트엔드 UX 방향

UI는 어두운 기술 편집기에서 밝고 쉬운 AI 생성 플로우로 이동해야 한다. Sellform의 첫 화면은 관리자 콘솔이나 디자인 툴처럼 보이면 안 된다. 사용자가 들어오자마자 "상품 자료를 넣으면 AI가 상세페이지를 만들어준다"는 목적을 이해해야 한다.

기본 시각 방향:

- 전체 배경은 흰색 또는 아주 옅은 회색을 사용한다.
- 브랜드 포인트는 소프트 민트/그린을 중심으로 하고, 블루는 보조 액션이나 진행 상태에만 제한적으로 사용한다.
- 남색/다크 네이비 면적은 첫 생성 화면에서 사용하지 않는다. 짙은 색은 본문 텍스트, 얇은 구분선, 작은 보조 라벨 정도로만 사용한다.
- 첫 생성 화면은 `화이트 90% 이상 + 민트/그린 포인트 + 약한 블루 보조`의 인상을 가져야 한다.
- 첫 화면의 중심은 큰 입력 카드 하나다.
- 보조 기능, 브랜드 설정, 출력 이력은 첫 화면에서 시각적 우선순위를 낮춘다.
- CTA는 하나만 강하게 보인다.
- 생성 전에는 편집 패널, 섹션 목록, Figma 내보내기 버튼을 먼저 보여주지 않는다.
- 1인 셀러가 느끼는 "어떻게 팔아야 할지 모르겠다"는 막막함을 줄이는 문구를 사용한다.
- 화면은 SaaS 관리자 도구보다 AI 제작 서비스에 가깝게 느껴져야 한다.

피해야 할 시각 방향:

- 좌측 고정 다크 사이드바가 첫 화면을 지배하는 구성
- 남색 배경과 흰 카드가 강하게 대비되는 관리자 대시보드형 구성
- 편집기, 운영 리포트, 프로젝트 관리 화면처럼 보이는 진입 경험
- 보라/남색 그라디언트가 브랜드 전체를 지배하는 구성

허용되는 다크 톤 사용처:

- 결과 생성 이후의 고급 편집기 보조 패널
- 설정, 운영 리포트, 출력 이력 같은 관리형 화면
- 텍스트 가독성을 위한 잉크 컬러
- 작은 상태 배지나 경고 라벨의 보조 색

최종 UX 원칙:

```text
입력은 쉽고,
AI 진행은 믿을 수 있게 보이고,
결과는 상세페이지처럼 바로 보여야 하며,
편집기는 결과 이후에만 등장한다.
```

### 10.1 시작 화면

대표 메시지:

**상품 사진이나 URL을 넣으면 AI가 상세페이지를 만들어드려요.**

보조 메시지:

**상품을 어떻게 설명해야 할지 몰라도 괜찮아요. AI가 판매 포인트, 상세페이지 문구, 이미지 연출 방향까지 먼저 제안합니다.**

입력 옵션:

- 상품 사진 업로드
- 상품 URL
- 상품명
- 간단한 설명
- 선택 입력: 참고 링크/참고 이미지
- 선택 입력: 원하는 분위기 또는 피하고 싶은 표현

화면 구성:

- 상단: 흰색 헤더, Sellform 로고, AI 상세페이지 탭, 간단한 크레딧/설정 진입
- 중앙 상단: 짧은 가치 제안과 `AI 자동 생성` 배지
- 중앙: 흰색 입력 카드
  - 사진 업로드 영역
  - 상품 URL 입력
  - 상품명/설명 입력
  - 템플릿 또는 분위기 프리셋
  - 언어 선택
- 중앙 하단: 생성 단계 미리보기
  - 상품 분석
  - 판매 전략
  - 문구 작성
  - 이미지 기획
  - 상세페이지 조립
- 하단: 최근 생성물 또는 예시 상세페이지 미리보기 1~3개

주 CTA:

**AI 상세페이지 만들기**

이 화면은 기존 `/workspace`의 기본 진입점이 되어야 한다. 사용자가 프로젝트 목록이나 편집기를 먼저 보는 구조는 최종 UX와 맞지 않는다. 시작 화면에서는 사이드바를 제거하거나 숨김 처리하고, 사용자가 생성에 집중할 수 있는 단일 컬럼 또는 중앙 집중형 레이아웃을 우선한다.

### 10.2 생성 진행 화면

다음 단계를 명확히 보여준다.

- 상품 이해
- 판매 방향 추천
- 상세페이지 구조 설계
- 문구 생성
- 이미지 연출 기획
- 이미지 생성
- 상세페이지 조립
- 검수

이 화면은 빈 편집기가 아니라, 사용자가 올렸던 19장 참고 이미지처럼 진행 상황을 보여주는 느낌이어야 한다.

### 10.3 확인 화면

이미지 생성 비용을 쓰거나 최종 페이지를 조립하기 전에 다음을 보여준다.

- AI 상품 이해 카드
- 추천 판매 방향
- 선택된 상품 이미지
- 예정된 이미지 생성 작업
- 예상 비용

액션:

- 이 방향으로 생성
- 다른 방향 보기
- 조금 수정하기

### 10.4 생성된 상세페이지 검수 화면

생성 이후에는 다음 구성을 사용한다.

- 중앙: 긴 모바일 상세페이지 미리보기
- 왼쪽: 판매 전략과 섹션 아웃라인
- 오른쪽: AI 편집 명령과 선택 섹션 속성

편집기는 시작점이 아니라 검수/보완 도구다. 검수 화면에서도 남색은 넓은 배경색이 아니라 보조 패널, 텍스트, 경계선에 제한적으로 사용한다. 상세페이지 미리보기와 AI 수정 명령은 밝은 캔버스 위에서 보여야 하며, 사용자가 "관리자 화면에 들어왔다"가 아니라 "AI가 만든 결과를 다듬고 있다"고 느껴야 한다.

### 10.5 출력 화면

출력 패키지:

- 긴 PNG
- 웹 기반 편집 페이지
- Figma export
- 카피 세트
- 이미지 자산
- 마켓플레이스 데이터

## 11. 백엔드 서비스 방향

권장 백엔드 모듈:

```text
backend/src/agents/
  graph.py
  state.py
  nodes/
    intake.py
    product_understanding.py
    sales_strategy.py
    page_planning.py
    copywriting.py
    visual_planning.py
    image_generation.py
    assembly.py
    qa.py

backend/src/services/
  prompt_registry.py
  generation_mode.py
  agent_run_service.py
  detail_page_assembly_service.py
```

기존 서비스는 가능한 한 재사용한다.

- `product_intake_service.py`
- `product_understanding_service.py`
- `sales_strategy_service.py`
- `visual_package_planner.py`
- `image_generation_service.py`
- `detail_page_package_service.py`
- `detail_page_orchestrator.py`
- `visual_page_renderer.py`
- `export_service.py`

핵심 변경점은 오케스트레이션이다. 기존 서비스들은 하나의 생성 파이프라인 안에서 노드 역할을 하도록 재배치한다.

## 12. 기존 Sprint 재배치

기존 Sprint 42~47 작업은 버리는 것이 아니다. 새 구조 안에서 다음처럼 재배치한다.

| 기존 Sprint | 새 역할 |
| --- | --- |
| Sprint 42 Flexible intake/product understanding | 시작 화면과 상품 이해 에이전트 |
| Sprint 43 Sales strategy variants | 판매 전략 에이전트와 확인 카드 |
| Sprint 44 Visual package contract | 이미지 기획 에이전트와 provider-neutral 이미지 작업 계약 |
| Sprint 44.5 AI image provider generation | mock/real mode를 가진 이미지 생성 에이전트 |
| Sprint 45 Detail page package editor | 생성 이후 검수 편집기 |
| Sprint 46 Figma/marketplace alignment | 출력 패키지 단계 |
| Sprint 47 Orchestration/cost/QA | LangGraph 스타일 생성 파이프라인, 비용 승인, QA 게이트 |

수정 방향은 "기존 작업 삭제"가 아니다.

수정 방향은 **AI 생성 파이프라인을 제품의 중심으로 만드는 것**이다.

## 13. 새 구현 Sprint 계획

### Sprint 48: 에이전트 아키텍처와 프롬프트 계약

목표:

- 그래프 상태 정의
- `AgentRun`/`AgentRunStep` 저장 계약 정의
- 에이전트 노드 계약 정의
- 프롬프트 레지스트리 추가
- `llm_router`/provider adapter 계약 추가
- mock/real mode 스위치 추가
- 에이전트별 구조화 출력 스키마 추가
- 프로젝트 삭제/자산 삭제/최종본 지정에 필요한 데이터 생애주기 규칙 추가

사용자 가시 결과:

- 최소한의 개발자용 실행 미리보기

### Sprint 49: AI 생성 시작 플로우

목표:

- `/workspace` 첫 경험을 AI 상세페이지 입력 화면으로 교체
- 어두운 편집기 중심 UI를 흰 바탕 AI 생성 홈페이지 UX로 전환
- 남색 사이드바가 지배하는 하이브리드가 아니라, 화이트 기반에 민트/그린 포인트를 쓰는 밝은 생성기 UX로 전환
- 사진/URL/상품명/설명 입력 지원
- 1인 셀러가 이해하기 쉬운 큰 입력 카드, 단일 CTA, 생성 단계 미리보기 제공
- 프로젝트를 `intake` 상태로 생성
- 생성 진행 화면 shell 표시

사용자 가시 결과:

- 사용자가 편집기보다 먼저 밝고 쉬운 "AI 상세페이지 만들기" 화면에서 시작한다.

### Sprint 50: Mock End-to-End 생성

목표:

- 전체 파이프라인을 mock mode로 실행
- 상품 이해, 판매 전략, 페이지 설계, 카피, 이미지 기획, placeholder 이미지, 조립된 페이지 생성
- API 크레딧 사용 없음

사용자 가시 결과:

- 클릭 한 번으로 완성형 mock 상세페이지 초안이 생성된다.

### Sprint 51: 실제 LLM 텍스트 파이프라인

목표:

- 상품 이해, 판매 전략, 페이지 설계, 카피라이팅에 실제 LLM 연결
- 기본 provider는 OpenAI GPT 계열로 두고, fallback 후보로 Gemini 2.5 Flash와 Claude 계열을 준비
- 이미지 생성은 별도 승인 전까지 mock 유지
- provider/cost 로그 추가

사용자 가시 결과:

- 상품 입력을 바탕으로 실제 AI 문구와 상세페이지 구조가 생성된다.

### Sprint 52: 실제 이미지 파이프라인

목표:

- Sprint 51까지의 mock 생성 결과가 입력 상품명/설명/업로드 이미지와 일관되게 보이도록 보완
- mock mode에서 업로드 이미지를 상세페이지 대표 이미지와 섹션 이미지 후보로 우선 사용
- mock 결과에서 무관한 샘플 상품 이미지와 카피가 섞이지 않도록 fixture 의존 제거
- 이미지 생성/편집 provider 연결
- 1차 provider는 OpenAI 이미지 생성/편집 모델로 두고, 추후 adapter 방식으로 확장
- 명시적 이미지 비용 승인 추가
- 상품 정체성 QA 추가
- 사용자가 생성 이미지를 선택할 수 있게 한다.

사용자 가시 결과:

- AI가 생성하거나 편집한 이미지를 상세페이지 섹션에 사용할 수 있다.

### Sprint 53: 검수 편집기 재정의

목표:

- 생성 완료 후 `생성된 상세페이지 보기`가 기존 dark page-editor로 바로 이동하지 않도록 변경
- white-first 상세페이지 결과 화면을 기본 결과 보기 화면으로 연결
- 기존 dark editor는 고급 편집/관리 도구로 격리하고 기본 AI 생성 흐름에서는 노출하지 않음
- 기존 편집기는 페이지 조립 이후에만 열리도록 변경
- 문구/이미지/섹션 변경을 위한 AI 명령 추가
- 누락 이미지와 주장 위험 경고를 명확히 표시
- 검수 편집기는 밝은 상세페이지 캔버스를 중심으로 두고, 다크/남색 패널은 보조 영역으로만 제한

사용자 가시 결과:

- 생성된 상세페이지를 빈 디자인 툴이 아니라 AI 보완 도구로 수정할 수 있다.

### Sprint 57~59: 생성 이후 최종화, 보관, 출력

기존의 포괄적인 출력·마켓플레이스 패키지 범위는 아래 3개 Sprint로 구체화한다.

- Sprint 57: 화면과 PNG/JPG 출력이 같은 최종본을 사용하도록 최종화·출력 계약 통합
- Sprint 58: 사용자가 만든 상세페이지를 다시 열고 관리하는 `내 상세페이지` 보관함
- Sprint 59: 생성부터 최종화, 보관, 재편집, 다운로드까지의 실제 E2E 및 실패 복구

Figma, 카피 세트, 마켓플레이스 패키지는 최종본 스냅샷을 공통 입력으로 사용하며 기존 출력 기능을 폐기하지 않는다.

## 14. 성공 기준

최종 제품은 1인 셀러가 다음을 할 수 있을 때 성공이다.

1. Sellform을 열자마자 AI 상세페이지를 만들어주는 서비스라는 것을 이해한다.
2. 상품 사진, URL, 상품명, 짧은 설명 중 하나 이상을 입력한다.
3. AI가 상품을 어떻게 이해했는지 확인한다.
4. 추천 판매 방향을 확인하거나 조정한다.
5. 완성형 긴 모바일 상세페이지 초안을 생성한다.
6. 빈 placeholder가 아니라 실제 문구와 이미지 섹션을 본다.
7. 명시적 비용 통제 아래 상품 비주얼을 생성하거나 승인한다.
8. 간단한 AI 명령으로 상세페이지를 수정한다.
9. PNG, Figma, 카피 세트, 마켓플레이스 데이터를 출력한다.
10. "막막함"에서 "판매 가능한 상세페이지 초안이 생겼다"는 상태로 이동한다.

## 15. 하지 않을 것

이번 최종 생성 아키텍처에서는 다음을 우선하지 않는다.

- Figma를 첫 사용자 경험으로 만들기
- Photoshop 같은 복잡한 편집기 만들기
- AI 시작 전에 긴 수동 입력 폼을 요구하기
- 원본 사진이 더 좋은 경우에도 모든 이미지를 억지로 생성하기
- 비용 사용을 사용자에게 숨기기
- 로컬 mock 테스트 중 실제 API 호출하기

## 16. 핵심 제품 결정

Sellform은 다음 순서의 제품이 되어야 한다.

```text
AI 상세페이지 생성 에이전트가 첫 번째,
검수 편집기가 두 번째,
출력과 마켓플레이스 보조가 세 번째.
```

이 방향이 사용자가 19장 참고 이미지에서 원했던 제품, 즉 **사진/URL을 넣으면 AI가 상세페이지를 만들어주는 서비스**에 가장 가깝다.
## 17. 11-Agent 최종 LangGraph 구조

기존 8개 에이전트 구상은 Sellform의 핵심 흐름을 설명하기에는 충분했지만, 사용자가 원하는 최종 제품인 "상품 사진 또는 URL을 넣으면 판매 가능한 상세페이지가 만들어지는 서비스"를 안정적으로 구현하려면 11개 역할로 분리한다.

이 구조는 MVP용 임시 구조가 아니다. 최종 제품의 역할 경계를 먼저 고정하고, 각 노드의 실제 능력을 sprint별로 채워 넣는 방식이다.

### 17.1 에이전트 폴더 구조

백엔드 에이전트는 다음 폴더 구조를 기준으로 한다.

```text
backend/src/agents/
  graph.py
  state.py
  schemas.py

  nodes/
    input_router/
      agent.py
      prompt.md
      schema.py

    source_collection/
      agent.py
      prompt.md
      schema.py

    product_understanding/
      agent.py
      prompt.md
      schema.py

    reference_analysis/
      agent.py
      prompt.md
      schema.py

    sales_strategy/
      agent.py
      prompt.md
      schema.py

    page_planning/
      agent.py
      prompt.md
      schema.py

    copywriting/
      agent.py
      prompt.md
      schema.py

    visual_planning/
      agent.py
      prompt.md
      schema.py

    image_generation/
      agent.py
      prompt.md
      schema.py

    page_assembly/
      agent.py
      prompt.md
      schema.py

    qa_review/
      agent.py
      prompt.md
      schema.py
```

각 폴더는 하나의 명확한 책임을 가진다. 공통 실행 인터페이스는 `run(state) -> state` 형태로 맞추고, 각 노드는 자신의 출력만 `AgentState.outputs`에 추가한다.

### 17.2 11개 에이전트 역할

1. **Input Router Agent**
   - 사진 업로드, URL, 상품명, 설명 중 어떤 입력이 들어왔는지 판단한다.
   - 부족한 입력을 `missing_inputs`로 표시한다.
   - 외부 API를 호출하지 않는다.

2. **Source Collection Agent**
   - 업로드 이미지, URL 이미지, URL 메타데이터, 상품 설명 원문을 수집한다.
   - URL 입력이 있으면 원문 출처와 수집 시각을 남긴다.
   - 똑같이 복사할 텍스트가 아니라 참고 가능한 구조화 소스로 저장한다.

3. **Product Understanding Agent**
   - 상품 유형, 주요 사용 장면, 구매자, 구매 망설임, 확인된 사실과 추정을 분리한다.
   - 업로드 이미지가 있으면 상품 정체성 보존 기준을 만든다.

4. **Reference Analysis Agent**
   - URL 상세페이지가 있을 때만 실행한다.
   - 기존 상세페이지의 구조, 이미지 흐름, 소구점, 톤을 분석하되 그대로 복제하지 않는다.
   - `copy_risk_notes`와 `reference_takeaways`를 분리한다.

5. **Sales Strategy Agent**
   - 문제 해결형, 감성형, 스펙 강조형, 프리미엄형 등 판매 방향 후보를 만든다.
   - 최종 추천 방향과 대안 방향을 함께 제공한다.

6. **Page Planning Agent**
   - 상세페이지 섹션 순서와 각 섹션의 역할을 설계한다.
   - 문제 제기, 메인 소구, 보조 장점, 근거, 요약, 상품 정보 흐름을 상품 카테고리에 맞게 조정한다.

7. **Copywriting Agent**
   - 섹션별 제목, 본문, 캡션, FAQ, CTA, 상품명 후보, 검색 태그를 생성한다.
   - 검증되지 않은 사실은 확정 문구로 쓰지 않는다.

8. **Visual Planning Agent**
   - 상세페이지에 필요한 이미지 컷을 정의한다.
   - 각 컷의 목적, 참고 이미지 필요 여부, 배경 방향, 상품 정체성 보존 규칙, 예상 비용을 만든다.

9. **Image Generation Agent**
   - 업로드 이미지나 URL 추출 이미지를 기반으로 상세페이지용 이미지 후보를 생성하거나 편집한다.
   - 비용 승인이 없으면 실제 이미지 API를 호출하지 않는다.
   - 후보별로 `uploaded`, `url-extracted`, `mock-generated`, `real-generated` 출처를 남긴다.

10. **Page Assembly Agent**
    - 구조, 카피, 이미지 후보를 조합해 긴 모바일 상세페이지 초안을 만든다.
    - 사용자가 선택한 이미지 후보가 있으면 우선 사용하고, 없으면 추천 후보를 자동 배치한다.

11. **QA Review Agent**
    - 상품 불일치, 이미지 누락, 과장 표현, URL 레퍼런스 복제 위험, 마켓플레이스 준비 부족을 검수한다.
    - 문제가 심하면 출력 전 단계로 되돌릴 수 있는 routing hint를 만든다.

### 17.3 LangGraph 흐름

초기 구현은 자유 토론형 멀티에이전트가 아니라 제작 공정형 그래프로 간다. 사용자는 에이전트들이 토론하는 모습을 보는 것이 아니라, 상품 하나를 넣었을 때 판매 가능한 상세페이지 초안이 나오는 경험을 원하기 때문이다.

```text
START
  -> input_router
  -> source_collection
  -> product_understanding
  -> reference_analysis        # URL이 없으면 skip
  -> sales_strategy
  -> page_planning
  -> copywriting
  -> visual_planning
  -> image_generation          # 비용 승인 없으면 mock/uploaded/url-extracted 후보만 사용
  -> page_assembly
  -> qa_review
  -> END
```

조건부 라우팅:

- URL이 없으면 `reference_analysis`를 건너뛴다.
- 필수 입력이 부족하면 `input_router`가 `waiting_for_user` 상태를 만든다.
- 이미지 생성 비용 승인이 없으면 `image_generation`은 실제 provider를 호출하지 않고 mock 또는 기존 이미지 후보만 반환한다.
- QA에서 복제 위험이 높으면 `copywriting` 또는 `page_planning`으로 되돌린다.
- QA에서 상품 이미지 불일치가 높으면 `image_generation` 또는 `visual_planning`으로 되돌린다.

### 17.4 Sprint 재정렬

Sprint 48~53은 폐기하지 않는다. 지금까지 만든 시작 화면, mock/real 텍스트 파이프라인, 이미지 파이프라인, 결과/검수 화면은 11-Agent 구조 안에 흡수한다.

새로운 후속 sprint는 다음 순서로 진행한다.

| Sprint | 목표 |
| --- | --- |
| Sprint 54 | 11-Agent 폴더 구조와 LangGraph형 노드 인터페이스로 리팩터링 |
| Sprint 55 | URL/업로드 소스 수집, 레퍼런스 분석, 이미지 후보 선택 계약 강화 |
| Sprint 56 | 실제 멀티모달 이미지 생성/편집과 상세페이지 조립 품질 강화 |
| Sprint 57 | 화면·PNG/JPG 출력 일치, 최종본 스냅샷 고정, 재현 가능한 내보내기 |
| Sprint 58 | `내 상세페이지` 보관함, 다시 열기·편집·다운로드·삭제 |
| Sprint 59 | 생성 이후 전체 E2E, 오류 복구, 회귀 방지와 운영 준비 |

이 순서가 끝나면 Sellform은 11개 에이전트가 상세페이지를 생성하는 데서 끝나지 않고, 사용자가 완성본을 보관하고 다시 편집하며 화면에서 본 그대로 출력할 수 있는 제품이 된다.

## 18. 생성 이후 최종화·보관·출력 라이프사이클

### 18.1 현재 문제 정의

생성 결과 화면이 정상이어도 PNG/JPG가 빈 placeholder 중심으로 저장되거나 서로 다른 내용으로 출력될 수 있다. 원인은 결과 화면과 출력 서비스가 서로 다른 데이터 시점과 렌더러를 사용하는 데 있다.

또한 생성한 프로젝트 목록을 다시 찾는 사용자용 보관함이 없어 브라우저 주소를 잃으면 이전 상세페이지에 접근하기 어렵다. 따라서 생성 성공만으로는 제품이 완성된 것이 아니다.

### 18.2 단일 최종본 계약

최종 흐름은 다음 계약을 따른다.

```text
현재 편집본(ProductPage)
  -> 최종본 확정(Final Detail Page Snapshot)
  -> 동일한 canonical detail-page renderer
       -> 결과 화면
       -> PNG/JPG export
       -> Figma/카피/마켓플레이스 출력
  -> 내 상세페이지 보관함
```

핵심 원칙:

1. 사용자가 `최종본 확정`을 누르면 현재 섹션 순서, 카피, 선택 이미지, 스타일을 하나의 불변 스냅샷으로 저장한다.
2. 프로젝트마다 활성 최종본은 한 개만 존재하며 새 최종본을 확정하면 이전 버전은 이력으로 보존한다.
3. 결과 화면과 PNG/JPG는 같은 스냅샷과 같은 HTML/CSS 렌더 컴포넌트를 사용한다.
4. 별도의 Pillow 레이아웃으로 상세페이지 디자인을 다시 조립하지 않는다.
5. PNG/JPG 출력은 canonical HTML을 Playwright로 캡처해 화면과의 차이를 제거한다.
6. 최종본이 변경되면 기존 출력물을 자동 재사용하지 않고 새 export artifact를 생성한다.
7. 이미지 누락, 접근 불가, 폰트 로딩 실패가 있으면 성공 파일을 만들지 않고 복구 가능한 오류를 반환한다.

### 18.3 상태와 사용자 동작

상세페이지는 다음 상태를 가진다.

- `draft`: 생성 또는 편집 중
- `reviewing`: 후보 이미지와 문구를 검수 중
- `final`: 사용자가 현재 버전을 최종본으로 확정
- `exported`: 해당 최종본 기준 출력물이 하나 이상 생성됨
- `failed`: 생성 또는 출력 실패이며 원인과 재시도 동작을 제공

결과 화면에서 제공할 동작:

- 최종본 확정
- 고급 편집기로 열기
- PNG 또는 JPG로 저장
- Figma/카피/마켓플레이스 출력
- 내 상세페이지에서 보기

### 18.4 내 상세페이지 보관함

`/workspace/library`는 개발용 운영 화면이 아니라 1인 셀러를 위한 사용자 보관함이다.

각 항목은 다음 정보를 보여준다.

- 대표 이미지
- 상품명
- 생성·수정 시각
- 현재 상태
- 최종본 버전
- 마지막 출력 형식과 시각

지원 동작:

- 결과 화면 다시 열기
- 편집 계속하기
- PNG/JPG 다시 다운로드
- 새 최종본 만들기
- 프로젝트 삭제

목록은 현재 워크스페이스 범위로 격리하며 빈 상태, 로딩, 오류, 삭제 확인 상태를 모두 제공한다.

### 18.5 출력 정확성 기준

다음 조건을 모두 만족해야 출력 성공으로 본다.

- 결과 화면과 출력물의 섹션 수와 순서가 같다.
- 각 섹션의 제목, 본문, 선택 이미지가 같다.
- placeholder나 `촬영 컷 배치가 필요합니다` 문구가 최종 출력에 남지 않는다.
- PNG와 JPG 모두 실제 이미지 파일로 열리며 확장자와 MIME type이 일치한다.
- 출력 폭은 마켓플레이스용 고정 폭을 사용하고 전체 세로 길이는 콘텐츠에 따라 계산한다.
- 긴 페이지가 잘리거나 브라우저 UI, 후보 선택 패널이 함께 캡처되지 않는다.

### 18.6 검증 및 실패 복구

실제 API 크레딧을 사용하지 않는 provider mock으로 다음 전체 흐름을 자동 검증한다.

```text
상품 입력
  -> 에이전트 생성
  -> 이미지 후보 선택
  -> 문구 편집
  -> 최종본 확정
  -> 내 상세페이지 노출
  -> 다시 열기
  -> PNG/JPG 출력
  -> 파일 픽셀·크기·콘텐츠 확인
```

실패 시 사용자는 입력 화면으로 강제 이동되지 않는다. 마지막 성공 단계와 프로젝트를 유지하고, 해당 작업만 재시도할 수 있어야 한다.

## DESIGN.md Source of Truth

UI/UX implementation for this final architecture must follow the repo-root `DESIGN.md`.

Sellform must not look like an AI technology product. It must feel like a bright, easy detail page creation service where a solo seller adds a product photo or URL and receives a sales-ready detail page draft.

Required visual direction:

- White-first
- Soft commerce
- Calm green accent
- Editorial product preview
- Minimal AI decoration

Avoid:

- dark dashboard frame
- purple/blue AI gradients
- excessive sparkle icons
- generic SaaS hero
- editor-first layout

When implementation details conflict, `DESIGN.md` is the source of truth for visual tone, layout priority, copy voice, and UI QA criteria.
