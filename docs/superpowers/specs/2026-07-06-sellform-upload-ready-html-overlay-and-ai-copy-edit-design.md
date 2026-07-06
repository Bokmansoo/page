# Sellform 업로드 가능 HTML 오버레이 및 AI 문구 수정 설계

작성일: 2026-07-06  
상태: 사용자 검토 대기

## 1. 배경

현재 결과 화면은 일부 섹션에서 AI 이미지를 정상 생성하지만, `html_graphic`으로 계획된
섹션은 이미지 생성을 건너뛴 뒤 실제 HTML 그래픽을 렌더링하지 않는다. 조립 단계에서
생성된 `visual_slot` 정보도 DB 저장과 API 응답 과정에서 유실된다. 프론트엔드는
`image_asset_id`가 없으면 무조건 누락 이미지로 판단하므로 비교, 장점, 구매 전 확인
섹션이 빈 박스로 표시된다.

고급 수정 화면의 AI 문구 수정도 실제 재작성이 아니다. 현재 endpoint는 기존 본문 앞에
`[AI 수정됨] 사용자 명령:`을 붙이거나 `[Revision: ...]` 표식을 추가한다. 따라서 버튼의
의도와 다른 판매 문구가 저장된다.

PNG/JPG 다운로드가 시작되지 않는 직접 원인도 같은 계약 불일치다.
`GeneratedDetailPageResult`는 `image_asset_id`가 없는 모든 섹션을 `missingVisualCount`로
계산하고, 이 값이 1 이상이면 다운로드 버튼을 비활성화한다. 정상적인
`html_graphic` 섹션 3개가 누락 이미지로 오인되어 사용자는 export 요청 자체를 보낼 수 없다.

## 2. 목표

Sellform이 만드는 기본 결과는 다음 두 성격을 동시에 만족해야 한다.

1. 빈칸이나 임시 문구 없이 곧바로 마켓플레이스에 업로드할 수 있는 완성본
2. 판매자가 제목, 본문, 이미지, HTML 그래픽을 다듬을 수 있는 고품질 초안

최종 상세페이지는 AI가 만든 무문자 이미지와 브라우저가 렌더링한 HTML/CSS 글씨를
조합한다. 미리보기와 PNG/JPG 출력은 같은 DOM을 사용해 시각적으로 동일해야 한다.

## 3. 핵심 원칙

- AI 이미지 모델에는 한글, 영문, 로고, 배지, 표를 그리게 하지 않는다.
- 제목, 본문, 배지, 비교 카드, 장점 카드, 스펙 표는 HTML/CSS로 렌더링한다.
- 판매 문구에는 `[AI 수정됨]`, `[Revision]`, 사용자 명령 원문 같은 내부 표식을 넣지 않는다.
- 확인되지 않은 상품 정보는 판매용 결과에서 제외한다.
- 미확인 항목은 결과 본문과 분리된 판매자 체크리스트에 표시한다.
- 이미지 또는 HTML 그래픽이 없는 일반 섹션은 생성 완료로 판정하지 않는다.
- 미리보기, 편집기, export renderer가 하나의 canonical section renderer를 공유한다.

## 4. 완성 상세페이지 구조

### 4.1 이미지 중심 섹션

히어로와 사용 장면은 AI 이미지 또는 업로드 이미지를 사용한다. 이미지 자체에는 글씨가
없다. 섹션 제목, 본문, 배지와 핵심 포인트는 이미지 위 또는 옆에 HTML로 배치한다.

예시:

- 히어로: 상품 이미지 + 어두운 scrim + 헤드라인 + 설명 + 핵심 배지
- 사용 장면: 라이프스타일 이미지 + 사용 맥락 설명
- 상품 디테일: 실제 상품 이미지 + 확인된 특징 라벨

### 4.2 HTML 그래픽 섹션

사진보다 구조화된 설명이 중요한 섹션은 HTML/CSS로 만든다.

- 비교: 2~3개의 비교 카드
- 장점: 아이콘, 짧은 제목, 한두 문장의 장점 카드
- 구매 전 확인: 확인된 정보 표와 미확인 항목 안내
- 보증/주의: 근거가 있는 정책과 확인 사항

HTML 그래픽은 이미지 asset이 없어도 정상적인 시각 결과다. 프론트엔드는 이를 이미지
누락으로 계산하지 않는다.

## 5. 데이터 모델

`PageSection`에 다음 canonical 시각 필드를 추가한다.

```json
{
  "visual_kind": "image | html_graphic",
  "visual_payload": {
    "layout_variant": "hero_overlay | image_text | comparison_cards | benefit_cards | spec_table",
    "eyebrow": "선택 값",
    "badges": ["선택 값"],
    "cards": [
      {
        "icon_key": "portable",
        "title": "필요한 곳으로 간편하게",
        "body": "확인된 정보에 기반한 설명",
        "tone": "positive"
      }
    ],
    "table_rows": [
      {
        "label": "충전 방식",
        "value": "확인된 값",
        "verification_status": "confirmed",
        "source_fact_ids": ["fact-id"]
      }
    ],
    "palette": {
      "surface": "#F2F7F4",
      "accent": "#16643F",
      "text": "#13231C"
    }
  }
}
```

`title`, `body_copy`, `image_asset_id`는 기존 필드를 canonical 값으로 유지한다.
`visual_payload`에는 중복되는 제목과 본문을 저장하지 않고, 카드·표·배지·레이아웃 같은
구조화 정보만 저장한다.

### 5.1 호환성

- 기존 `image_asset_id`가 있는 섹션은 `visual_kind=image`로 해석한다.
- `html-graphic` 후보가 있고 asset이 없는 기존 섹션은 `visual_kind=html_graphic`으로
  backfill한다.
- 기존 프로젝트의 HTML payload는 현재 제목, 본문, 섹션 타입과 확인된 facts를 이용해
  결정론적으로 생성한다.
- backfill할 근거가 부족하면 빈 값을 발명하지 않고 해당 항목을 판매자 체크리스트로 보낸다.

## 6. 백엔드 처리 흐름

1. `visual_planning`이 섹션별 `visual_kind`와 `layout_variant`를 결정한다.
2. 이미지 섹션만 image generation job을 생성한다.
3. HTML 그래픽 섹션은 구조화된 `visual_payload`를 생성한다.
4. `page_assembly`가 이미지와 HTML 그래픽을 동일한 완성 시각 결과로 취급한다.
5. `agent_run_service`가 `visual_kind`와 `visual_payload`를 DB에 저장한다.
6. page API와 final version snapshot이 두 필드를 그대로 반환한다.
7. QA는 이미지 섹션의 asset 존재 여부와 HTML 그래픽 payload의 완전성을 각각 검사한다.

`visual-package`와 agent graph가 서로 다른 job 상태를 만드는 현재 이중 경로는 하나의
canonical section visual contract를 사용하도록 통합한다.

## 7. 프론트엔드 렌더링

`DetailPageDocument`를 미리보기와 export의 단일 renderer로 유지한다.

섹션 렌더링 규칙:

- `visual_kind=image`: `ImageSectionVisual`
- `visual_kind=html_graphic`, `comparison_cards`: `ComparisonGraphic`
- `visual_kind=html_graphic`, `benefit_cards`: `BenefitCardGraphic`
- `visual_kind=html_graphic`, `spec_table`: `SpecTableGraphic`

이미지 섹션은 `layout_variant`에 따라 제목을 이미지 위에 overlay하거나 이미지 옆에
배치한다. 모든 텍스트는 선택·편집 가능한 실제 DOM 텍스트다.

결과 화면의 이미지 후보 패널은 HTML 그래픽을 비활성 이미지 후보로 표시하지 않는다.
대신 “HTML 그래픽”으로 표시하고 그래픽 편집 버튼을 제공한다.

## 8. 판매자 편집

판매자는 다음 값을 수정할 수 있다.

- 섹션 제목과 본문
- 이미지 후보 선택
- HTML 그래픽의 카드 제목, 설명, 순서
- 스펙 표의 확인된 값
- 배지와 강조 색상

직접 수정은 즉시 가운데 미리보기에 반영하고 blur 또는 명시적 저장 시 버전을 만든다.
HTML 그래픽의 미확인 값은 판매자가 입력하고 확인하기 전까지 판매용 출력에 포함하지 않는다.

## 9. 실제 AI 문구 수정

두 개로 갈라진 AI edit endpoint와 표식 추가 로직을 하나의 `CopyRewriteService`로 통합한다.

### 9.1 입력

- 현재 `title`, `body_copy`
- 섹션 타입과 역할
- 선택한 명령
- 사용자 자유 지시
- 확인된 상품 facts와 출처
- 금지 주장과 compliance 제약
- 목표 톤과 최대 길이

### 9.2 버튼별 동작

- `stronger_headline`: 제목만 더 구체적이고 강하게 재작성
- `natural_tone`: 제목과 본문의 중복 및 군더더기 제거
- `reduce_exaggeration`: 근거 없는 최상급, 절대 표현, 확정 표현 제거
- `usage_context`: 확인 가능한 실제 사용 맥락을 본문에 추가
- `beginner_seller_tone`: 쉬운 단어와 짧은 문장으로 변경
- `reduce_purchase_anxiety`: 확인된 정보와 구매 전 체크사항 추가
- `custom_edit`: 사용자 자유 지시를 제약 안에서 반영

### 9.3 결과

```json
{
  "title": "재작성된 제목",
  "body_copy": "재작성된 본문",
  "change_summary": "제목을 구체화하고 중복 표현을 제거했습니다.",
  "grounding_warnings": []
}
```

Real 모드는 기존 LLM router를 사용한다. Mock 모드는 사용자 명령을 본문에 붙이지 않고,
각 명령에 맞는 결정론적 재작성 결과를 만든다.

### 9.4 적용 UX

기본 동작은 수정 전/후 비교 후 적용이다.

1. 버튼 또는 직접 요청 선택
2. 원본과 제안 문구를 나란히 표시
3. 판매자가 적용 또는 취소
4. 적용 시 section 저장과 page version 생성
5. 직전 변경 되돌리기 제공

AI 호출이나 검증이 실패하면 기존 문구는 변경하지 않는다.

## 10. PNG/JPG export

PNG와 JPG는 같은 canonical render route를 Playwright로 캡처한다.

- PNG: 무손실 기본값
- JPG: 흰색 배경으로 합성하고 품질 설정 적용
- viewport와 출력 폭은 marketplace preset에 고정
- web font와 이미지 로딩 완료 후 `data-export-ready=true`
- 이미지 로딩 실패는 준비 완료로 간주하지 않고 export blocker로 반환
- 미리보기와 export가 같은 `DetailPageDocument`를 사용
- HTML 텍스트, 카드, 표, 배지가 최종 이미지에 rasterize되어 포함
- 사용자 화면에서 선택한 final version ID를 export 완료까지 고정

## 11. 완료 및 내보내기 조건

다음 조건을 모두 만족해야 “생성 완료”로 표시한다.

- 모든 일반 섹션에 유효한 이미지 또는 완전한 HTML 그래픽이 있음
- 이미지 섹션 asset이 실제로 조회 가능함
- HTML 그래픽 필수 카드/행이 비어 있지 않음
- 판매용 문구에 내부 수정 표식이 없음
- 근거 없는 주장이 없음
- 미확인 값이 판매용 본문에 노출되지 않음
- PNG/JPG 렌더 route가 준비 상태를 반환함

실패 시 어떤 섹션의 무엇이 부족한지 판매자에게 구체적으로 표시한다.

## 12. 테스트 전략

### 백엔드

- `visual_kind`와 `visual_payload` 저장/조회 round trip
- agent assembly의 HTML 그래픽 보존
- 기존 프로젝트 backfill
- HTML 그래픽을 이미지 누락으로 판정하지 않는 QA
- AI 버튼별 title/body 변경 범위
- `[AI 수정됨]`, `[Revision]`, 사용자 명령 원문 미포함
- 확인되지 않은 facts를 생성하지 않는 grounding 검증
- AI 실패 시 원본 보존

### 프론트엔드

- 이미지 overlay 렌더링
- 비교 카드, 장점 카드, 스펙 표 렌더링
- HTML 그래픽이 누락 이미지 수에 포함되지 않음
- 직접 편집과 미리보기 동기화
- AI 수정 전/후 비교와 적용/취소
- 되돌리기

### E2E 및 export

- 현재 문제 프로젝트와 같은 5개 섹션 fixture 사용
- 이미지 2개와 HTML 그래픽 3개가 빈칸 없이 표시
- PNG와 JPG 다운로드
- 미리보기와 export에서 동일한 제목, 카드, 이미지 확인
- 오래된 final version이나 미완성 섹션 export 차단

## 13. 수용 기준

1. 결과 화면에 “이미지 확인 필요” 빈 박스가 없다.
2. AI 이미지는 글씨 없이 생성되고, 한글은 HTML/CSS로 선명하게 렌더링된다.
3. 비교, 장점, 구매 전 확인 영역이 실제 HTML 그래픽으로 표시된다.
4. PNG와 JPG가 모두 저장되고 미리보기와 같은 내용을 포함한다.
5. AI 문구 수정 버튼이 목적에 맞는 문구를 제안한다.
6. 내부 수정 표식이나 사용자 명령이 판매 문구에 포함되지 않는다.
7. 판매자가 수정 전후를 비교하고 적용하거나 취소할 수 있다.
8. 적용된 변경은 버전으로 저장되고 되돌릴 수 있다.
9. 확인되지 않은 상품 정보는 판매용 결과에 포함되지 않는다.
10. 새 프로젝트와 기존 프로젝트 모두 같은 renderer와 export 경로를 사용한다.

## 14. 추가로 함께 수정할 품질 포인트

- 다운로드 버튼의 활성 조건을 `image_asset_id` 유무가 아니라 섹션별 visual contract
  유효성으로 계산한다.
- export 진행 상태를 준비, 렌더링, 다운로드 단계로 나누고 실패 원인을 화면에 보존한다.
- 이미지 `error` 이벤트가 발생하면 `data-export-ready=true`를 설정하지 않는다.
- 긴 한글 제목과 카드 문구가 760px export 폭에서 잘리지 않는지 overflow 검증을 추가한다.
- AI 생성 상품 이미지의 identity review가 끝나지 않았으면 export를 차단하고 해당 섹션으로
  바로 이동할 수 있게 한다.
- render route 인증은 장기적으로 user/workspace ID query string 대신 짧은 수명의 서명된
  export token으로 교체한다.
- 백엔드 실행 포트와 프론트엔드 API base URL을 단일 환경 변수와 runbook으로 통일한다.
- 기존 `pages/ai-edit`, `page/sections/{id}/ai-edit`, `regenerate`의 중복 수정 경로를 하나의
  copy rewrite contract로 합친다.

## 15. 구현 범위 밖

- 자유 배치형 캔버스 편집기
- 판매자가 임의 HTML/CSS 코드를 입력하는 기능
- AI가 로고나 한글을 이미지 픽셀로 직접 생성하는 기능
- 모든 마켓플레이스의 자동 업로드 API 연동
- 이번 변경과 무관한 전체 디자인 시스템 개편
