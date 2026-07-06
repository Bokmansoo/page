# Sellform Sprint 10 AI 사실 카드 자동 추출 실행계획

> 이 문서는 Sprint 9 이후 선택할 수 있는 Sprint 10 후보 중 “AI 사실 카드 자동 추출 고도화”를 구현할 때의 실행 기준이다. 실제 구현 전에는 Sprint 9 실사용 검증 결과와 이 계획을 다시 확인한다.

## 1. 목표

사용자가 상품 URL, 복사한 상세 설명 텍스트, 업로드 이미지를 제공하면 Sellform이 먼저 상품 사실 카드 후보를 자동 생성한다.

사용자는 모든 사실을 처음부터 수기로 입력하는 대신, AI가 만든 후보를 검수·수정·삭제·확정한다. 최종 상세페이지에는 사용자가 `confirmed`로 승인한 사실만 사용한다.

## 2. 왜 필요한가

현재 사실 확인 보드는 수동 검수 구조가 안전하지만, 소싱 상품이 늘어나면 사용자가 사실 카드를 직접 작성하는 부담이 커진다.

Sellform의 핵심 가치는 “상품 자료를 상세페이지로 바꾸는 시간”을 줄이는 것이다. 따라서 사실 카드 단계도 다음 구조가 되어야 한다.

```text
상품 링크/텍스트/이미지 입력
→ AI가 사실 후보 자동 추출
→ 사용자가 근거와 표현 확인
→ 확인된 사실만 상세페이지 생성에 사용
```

## 3. 범위

### 3.1 입력 소스

- 공급처 URL
- 사용자가 복사해 붙여넣은 상품 설명 텍스트
- 업로드한 상품 이미지
- 기존 프로젝트 메타데이터
  - 상품명
  - 카테고리
  - 브랜드
  - 판매처 대상

### 3.2 자동 추출 결과

AI는 다음 형태의 사실 후보를 반환한다.

```json
{
  "fact_text": "이 상품은 USB-C 충전을 지원합니다.",
  "source_text": "USB-C charging supported",
  "source_asset_id": null,
  "confidence": 0.82,
  "extraction_source": "manual_text",
  "needs_review": true,
  "risk_flags": []
}
```

필수 필드:

- `fact_text`: 한국어 상품 사실 문장
- `source_text`: 근거가 된 원문 또는 이미지 설명
- `source_asset_id`: 이미지 근거가 있을 때 연결할 자산 ID
- `confidence`: 0~1 사이 신뢰도
- `extraction_source`: `url`, `manual_text`, `image`, `metadata` 중 하나
- `needs_review`: 자동 생성 후보는 기본적으로 `true`
- `risk_flags`: 과장, 효능, 인증, 원산지, 수치 오기재 위험 표시

### 3.3 저장 규칙

- 자동 생성된 사실은 기본 `unknown` 또는 `needs_revision` 상태로 저장한다.
- 사용자가 직접 확인한 사실만 `confirmed`로 변경할 수 있다.
- 상세페이지 생성, 카피 생성, 이미지 export에는 `confirmed` 사실만 사용한다.
- 동일하거나 매우 유사한 후보는 중복으로 저장하지 않는다.

### 3.4 URL 수집 규칙

URL 자동 수집은 편의 기능이며 필수 성공 조건이 아니다.

다음 상황에서는 실패로 처리하고 수동 입력 fallback을 안내한다.

- 캡차
- 로그인 필요
- 봇 차단
- 공급처 정책상 크롤링 제한
- 응답 timeout
- 비정상 Content-Type
- 내부망/로컬 주소 접근 위험

보안 원칙:

- localhost, 사설 IP, metadata endpoint 등 SSRF 위험 URL은 차단한다.
- 외부 URL 요청은 timeout을 둔다.
- 수집 실패 사유는 사용자에게 짧게 표시하고 트러블슈팅 로그에 남긴다.

## 4. 구현 작업

### Task 1: 데이터 모델과 API 계약 확정

확인할 파일:

- `backend/src/models.py`
- `backend/src/schemas.py`
- `backend/src/api/facts.py`
- `frontend/src/lib/api.ts`

작업:

- 사실 후보 자동 추출 요청/응답 스키마를 추가한다.
- 기존 `ProductFact` 모델에 필요한 필드가 부족하면 최소 필드만 추가한다.
- 자동 추출 결과와 사용자 확정 상태를 분리한다.

권장 API:

```http
POST /api/v1/projects/{project_id}/facts/auto-extract
```

응답 예:

```json
{
  "project_id": "uuid",
  "created_count": 6,
  "skipped_duplicates": 2,
  "failed_sources": [
    {
      "source": "url",
      "reason": "captcha_or_login_required"
    }
  ],
  "facts": []
}
```

### Task 2: 입력 수집 서비스 구현

권장 파일:

- `backend/src/services/source_collector.py`

작업:

- 프로젝트의 URL, 수동 텍스트, 이미지 메타데이터를 분석 입력으로 묶는다.
- URL 수집 실패 시 예외로 전체 흐름을 중단하지 않는다.
- 실패 사유를 구조화해서 반환한다.

### Task 3: AI 사실 추출 서비스 구현

권장 파일:

- `backend/src/services/fact_extractor.py`

작업:

- 입력 소스별로 AI 프롬프트를 구성한다.
- AI 응답을 구조화 JSON으로 파싱한다.
- 응답 검증에 실패하면 사용자에게 재시도 가능한 오류를 반환한다.
- AI provider가 비활성화된 개발 환경에서는 deterministic mock extractor를 제공한다.

### Task 4: 사실 후보 저장과 중복 제거

작업:

- 동일 문장 또는 유사 문장은 중복 저장하지 않는다.
- 위험 플래그가 있는 항목은 `needs_revision` 상태로 둔다.
- 근거 텍스트와 이미지 자산 연결을 보존한다.

### Task 5: 사실 확인 보드 UI 개선

권장 파일:

- `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

작업:

- `AI로 사실 카드 자동 생성` 버튼을 추가한다.
- 분석 중/loading 상태를 표시한다.
- 생성된 후보 개수, 중복 제외 개수, 실패한 입력 소스를 보여준다.
- 후보별 근거, 신뢰도, 위험 플래그를 확인할 수 있게 한다.
- 사용자가 `확인됨`, `수정 필요`, `제외`로 빠르게 검수할 수 있게 한다.

### Task 6: 테스트 추가

백엔드 테스트:

- 수동 텍스트에서 사실 후보가 생성된다.
- URL 수집 실패가 전체 API 실패로 번지지 않는다.
- 중복 후보가 중복 저장되지 않는다.
- `confirmed`가 아닌 사실은 상세페이지 생성에 사용되지 않는다.
- mock AI provider에서도 deterministic 결과가 나온다.

프론트 테스트/빌드:

- 사실 보드에서 자동 생성 버튼이 보인다.
- API 성공 시 후보 개수와 경고가 표시된다.
- API 실패 시 수동 입력 fallback 안내가 표시된다.
- 프론트 빌드가 통과한다.

## 5. 완료 기준

- 수동 텍스트만 있는 상품에서 5개 이상 사실 후보를 자동 생성할 수 있다.
- 이미지가 있는 상품에서 이미지 근거가 연결된 사실 후보를 만들 수 있다.
- URL 수집 실패 시에도 사용자는 다음 단계로 진행할 수 있다.
- 자동 생성 후보는 사용자 확인 전까지 상세페이지에 사용되지 않는다.
- 테스트 로그, 코드리뷰, 트러블슈팅 문서가 남는다.

## 6. 산출물

- `docs/testing/2026-06-24-sellform-sprint-10-ai-fact-extraction-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-10-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-10-ai-fact-extraction.md`
- 필요 시 `docs/decisions/2026-06-24-sellform-ai-fact-extraction-direction.md`

## 7. 제외 범위

- 쿠팡/스마트스토어 자동 업로드
- 공급처 약관을 우회하는 크롤링
- 캡차 우회
- 로그인 세션 자동 탈취 또는 비공식 자동화
- AI가 확인되지 않은 효능·인증·원산지·수치를 확정 사실처럼 사용하는 동작

