# Sprint 78 상세페이지 템플릿 시스템 구현 계획

> 목적: 상품군과 판매 목적에 맞는 상세페이지 구성 템플릿을 제공하고, 문제 제기부터 구매 전 확인까지 이어지는 흐름을 안정적으로 만든다.

## 1. 배경

기존 상세페이지 생성은 섹션 타입이 있어도 “어떤 판매 흐름으로 읽히는지”가 명확하지 않았다. 그래서 AI가 내부 가이드 문구를 노출하거나, 상품과 맞지 않는 섹션 구성이 만들어질 수 있었다.

Sprint 78에서는 상세페이지를 판매 흐름 단위의 템플릿으로 관리한다.

## 2. 기본 상세페이지 흐름

1. 문제 제기: 고객의 핵심 고민을 먼저 보여준다.
2. 메인 소구점 강조: 이 제품이 해결할 수 있는 핵심 메시지를 제시한다.
3. 소구점 A: 가장 강한 장점을 구체화한다.
4. 소구점 B: 추가 장점을 보완한다.
5. 소구점 A 재강조: 핵심 메시지를 다시 각인시킨다.
6. 소구점 B~D 정리: 나머지 장점을 정돈한다.
7. 전체 요약: 전체 흐름을 한 문장으로 정리한다.
8. 상품 정보: 최종 구매 판단에 필요한 정보를 제공한다.

## 3. 템플릿 종류

| 템플릿 | 목적 |
| --- | --- |
| 기본 판매형 | 대부분의 일반 상품에 사용 |
| 문제 해결형 | 불편/고민 해결이 강한 상품 |
| 라이프스타일형 | 사용 장면과 감성이 중요한 상품 |
| 스펙 비교형 | 기능, 수치, 구성품 비교가 중요한 상품 |
| 초보 셀러형 | 쉬운 문장과 안전한 표현 우선 |
| 프리미엄형 | 고급스러운 톤과 브랜드 감성 우선 |

## 4. 섹션 컴포넌트 계약

각 섹션은 아래 필드를 가진다.

```json
{
  "section_type": "problem",
  "role": "문제 제기",
  "headline": "더운 날, 휴대용 선풍기만으로 부족할 때",
  "body": "책상, 차량, 야외처럼 전원 연결이 번거로운 순간에도 바로 꺼내 쓸 수 있습니다.",
  "evidence_fact_ids": ["wireless", "portable"],
  "visual_strategy": "html_graphic",
  "editable": true
}
```

필수 원칙:

- `role`은 내부 관리용이며 고객에게 그대로 노출하지 않는다.
- `headline`, `body`만 고객 노출 문구로 사용한다.
- `evidence_fact_ids`로 어떤 상품 정보에 근거했는지 추적한다.
- `visual_strategy`로 이미지 생성, 누끼 합성, HTML 그래픽 중 무엇을 쓸지 명확히 한다.

## 5. 구현 범위

### Task 1. 템플릿 schema 정의

파일:

- `backend/src/services/detail_page_template_service.py`
- `backend/tests/test_detail_page_template_service.py`

구현:

- 템플릿 ID, 섹션 순서, 필수/선택 섹션 정의
- 상품군/판매 목적별 템플릿 선택 규칙

### Task 2. 패키지 API와 연결

파일:

- `backend/src/api/pages.py`
- `backend/src/db/models.py`
- `backend/src/services/detail_page_package_service.py`

구현:

- `role`, `headline`, `body`, `evidence_fact_ids`, `visual_strategy`, `editable` 필드 반환
- 기존 `title`, `body_copy`, `associated_fact_ids`와 호환 유지

### Task 3. 최종 렌더링 연결

파일:

- `frontend/src/components/DetailPageDocument.tsx`

구현:

- `visual_strategy`에 따라 이미지/HTML 그래픽/텍스트 섹션을 분기할 수 있는 계약 준비
- `Specs`, `Pre-purchase`, `Comparison`은 기본적으로 HTML/CSS 그래픽으로 처리할 수 있게 한다.

## 6. 검증 기준

- 템플릿 선택 규칙 테스트가 통과한다.
- 상세페이지 패키지 API가 섹션 컴포넌트 계약 필드를 반환한다.
- 고객 노출 문구와 내부 role이 분리된다.
- 기존 상세페이지 생성/검수 흐름과 하위 호환된다.
