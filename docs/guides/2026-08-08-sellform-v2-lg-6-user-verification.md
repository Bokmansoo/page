# Sellform V2.1 LG-6 브라우저 검증 가이드

## 1. 실행 준비

`backend/.env`에서 아래 값을 확인한다.

```env
SELLFORM_GRAPH_RUNTIME=langgraph
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
```

백엔드와 프런트엔드를 재시작한 뒤 다음 주소를 연다.

- 백엔드 문서: http://localhost:8001/docs
- 프런트: http://localhost:3000
- LG-6 설정 화면: http://localhost:3000/workspace/settings/intelligence

이 검증에서는 유료 이미지 API가 호출되지 않는다.

## 2. 기본 Prompt Pack 확인

1. LG-6 설정 화면에서 **기본 팩 준비**를 누른다.
2. 활성 팩이 총 8개인지 확인한다.
   - 카테고리 6개: 생활용품, 뷰티, 식품, 패션, 전자제품, other
   - 채널 2개: coupang, naver_smartstore
3. 각 행에 version, 상태 `active`, content hash가 표시되는지 확인한다.

기대 결과: 새로고침해도 같은 version과 hash가 유지되고 중복 팩이 생기지 않는다.

## 3. 카테고리 분류와 Golden Dataset 확인

분류 미리보기에 다음 문장을 넣고 실행한다.

```text
휴대용 무선 선풍기 USB 충전 배터리
```

기대 결과:

- category: `전자제품`
- confidence: 높은 값
- rationale: 선풍기·USB·충전 등의 분류 근거
- fallback: 사용 안 함

다음 문장도 실행한다.

```text
분류 근거 없는 신규 상품
```

기대 결과:

- category: `other`
- fallback: 사용
- 낮은 confidence와 안전 fallback 사유 표시

그다음 **Golden Dataset 평가**를 누른다. 기대 결과는 정확도 95% 이상이며 현재 고정 dataset 기준 100%다. dataset version, classifier version, input/output hash와 confusion matrix가 표시돼야 한다.

## 4. Prompt Pack lifecycle 확인

1. pack type `category`, key `other`를 선택하고 **초안 제안**을 누른다.
2. 새 버전 상태가 `draft_generated`이고 기존 active 버전은 그대로인지 확인한다.
3. 새 초안에서 **검증 요청 → 승인 → 활성화** 순서로 누른다.
4. 중간 단계를 건너뛰어 바로 활성화하려 할 때는 거부돼야 한다.
5. 활성화 후 새 버전만 `active`, 이전 버전은 `deprecated`인지 확인한다.
6. 새로고침 후에도 상태와 hash가 그대로인지 확인한다.

기대 결과: 초안 생성만으로 운영 팩이 자동 교체되지 않으며, 각 단계가 감사 로그가 남는 독립 동작이다.

## 5. Brand Kit 확인

Brand Kit의 로고와 폰트는 먼저 프로젝트에서 `권리 보유 이미지` 또는 권리 확인 완료 자산으로 업로드해야 한다. 공급처 참고 전용 사진은 picker에 나타나면 안 된다.

1. 설정 화면의 Brand Kit 영역에서 **새 Kit 만들기**를 누른다.
2. 이름을 입력하고 로고 자산과 폰트 자산을 각각 picker에서 선택한다.
3. 색상, typography, tone of voice, 금칙어, CTA 규칙, 이미지 스타일, layout, background, watermark 정책을 입력한다.
4. **버전 만들기** 후 **workspace 기본으로 활성화**한다.
5. 새 프로젝트를 하나 만든다.
6. 설정 화면에서 그 프로젝트의 resolved Brand Kit가 방금 활성화한 version인지 확인한다.
7. workspace 기본 Kit의 새 버전을 활성화한다.
8. 앞서 만든 프로젝트는 이전 snapshot version을 계속 가리키는지 확인한다.
9. 프로젝트 override를 만들고 활성화한 뒤 해당 프로젝트에만 override가 적용되는지 확인한다.
10. 새로고침해도 모든 상태가 유지되는지 확인한다.

기대 결과: workspace 기본 변경이 기존 프로젝트를 소급 변경하지 않고, override도 workspace 기본값을 수정하지 않는다.

## 6. 실제 LangGraph 경로 확인

1. 새 프로젝트를 만들고 mock 생성 흐름을 시작한다.
2. 상품 입력 확인과 근거 사실 확인을 승인한다.
3. 백엔드 문서에서 `GET /api/v1/graph-runs/{run_id}` 또는 history API를 실행한다.
4. 이벤트 순서에서 다음을 확인한다.

```text
evidence_review
category_classifier
prompt_pack_resolver
sales_strategy
```

5. 응답의 `prompt_intelligence`에서 다음 값이 있는지 확인한다.
   - classification과 confidence/fallback
   - category/channel pack version ID와 hash
   - Brand Kit version ID/hash 또는 Kit가 없을 때 null
   - compiled artifact ID/hash
6. API key, Authorization, signed URL, 원문 고객 payload가 graph checkpoint에 들어 있지 않은지 확인한다.

기대 결과: 같은 run을 새로고침·재개해도 동일한 version/hash가 유지된다. 설정에서 새 팩을 활성화해도 이미 진행 중인 run의 snapshot은 바뀌지 않는다.

## 7. LG-6의 결과 범위

LG-6은 최종 상세페이지를 직접 완성하는 단계가 아니라, 후속 카피·이미지·조립 에이전트가 사용할 **분류 결과, 검증된 Prompt Pack, Brand Kit와 불변 compile snapshot**을 제공하는 단계다. 최종 상세페이지 렌더링·편집·내보내기는 후속 LG-7 이후 단계에서 이어진다.

