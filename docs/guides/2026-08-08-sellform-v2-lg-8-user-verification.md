# 2026-08-09 LG-8R 검증 안내

provider worker 완료 후 `provider_wait -> image_review` 반복 안정성과 서버 재시작 복구 검증은 최신 가이드 `docs/guides/2026-08-09-sellform-v2-lg-8r-user-verification.md`를 사용한다.

---

# Sellform V2.1 LG-8 브라우저 사용자 검증 가이드

작성일: 2026-08-08  
목적: 유료 API를 호출하지 않고 장면별 Visual Prompt Compiler, 버전, stale 범위, 비용 승인, worker와 LangGraph 재개를 확인한다.

## 1. 실행 환경

`C:\page\backend\.env`에서 다음 값을 사용한다.

```env
SELLFORM_GRAPH_RUNTIME=langgraph
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
```

백엔드와 프런트엔드를 재시작한 뒤 아래 주소를 연다.

- 프런트: `http://localhost:3000/workspace`
- 백엔드 문서: `http://localhost:8001/docs`

## 2. 새 프로젝트 입력

1. `AI 상세페이지 생성`에서 새 상품을 만든다.
2. 상품 전체가 잘 보이는 권리 보유 사진 1장과 버튼·포트·구성품 또는 사용 장면 사진 1장 이상을 올린다.
3. 사진 역할을 `대표 제품 전체`, `조작부·측면 상세`, `제품 구성품` 또는 `사용 장면`으로 지정한다.
4. 상품명과 확인 가능한 사양만 입력한다.
5. `입력 자료 확인 후 생성하기`를 누른다.

기대 결과: `input_review`와 `evidence_review`를 거쳐 스토리보드가 표시된다. 권리 보유 대표 사진이 없으면 안전 차단 메시지가 나오는 것이 정상이다.

## 3. 장면 prompt 확인

1. 스토리보드 장면을 확인하고 승인한다.
2. `스토리보드 승인 완료 · 이미지 생성 대기` 상태에서 장면별 `생성 프롬프트 근거` 또는 prompt 상세를 연다.
3. 다음 항목을 확인한다.

- 장면 유형과 목적
- prompt version/hash
- reference hash와 기준 사진 수
- 제품 정체성 고정 요소
- 권리 snapshot
- Brand Kit version/hash
- `no_rasterized_copy`
- negative text/QR/watermark/price/CTA 정책
- 모델, 1024x1024 크기, 장면별 예상 비용

기대 결과: provider prompt에 최종 한국어 제목·본문·사양표를 이미지 안에 넣으라는 지시가 없다.

## 4. 장면 하나만 수정되는지 확인

한 장면의 판매자 시각 지시에 아래처럼 입력한다.

```text
밝은 중성 스튜디오 배경, 제품을 중앙에 배치하고 이미지 안에는 문구를 넣지 않음
```

저장 후 확인할 결과:

- 수정 장면은 v2 active가 된다.
- 그 장면의 v1만 stale로 남는다.
- 다른 장면은 기존 active version과 job을 유지한다.
- 새로고침해도 동일하다.

아래 요청은 저장이 차단돼야 한다.

```text
이미지 안에 할인 문구와 로고를 크게 넣어 주세요
```

기대 결과: 한국어 오류 코드, 원인, 해결 방법이 표시되고 `[object Object]`는 보이지 않는다.

## 5. 비용 승인과 실제 상태 복구

1. 비용 카드에서 장면 수, provider/model, 크기, 장면별 비용, 총 예상 비용을 확인한다.
2. 승인 전에는 이미지 작업이 provider로 dispatch되지 않는다.
3. `비용 승인 후 이미지 생성`을 한 번만 누른다.
4. `provider_wait`에서 `작업 상태 새로고침`을 누르거나 잠시 기다린다.
5. F5로 새로고침한다.

기대 결과: 같은 runId가 유지되고 `image_review`로 이동한다. mock 모드에서는 실제 AI 사진 대신 fake 결과가 표시되며 과금은 발생하지 않는다.

## 6. 장면별 검수

1. 한 장면만 승인한다.
2. 전체 실행이 완료되지 않고 나머지 장면은 검수 대기로 남는지 확인한다.
3. 다른 장면 하나를 거절하거나 재생성한다.
4. 승인한 장면은 보존되고 실패·거절 장면만 다시 작업되는지 확인한다.
5. 직접 업로드는 raw asset ID가 아니라 화면의 `권리 보유 사진 선택`에서 사진을 고른 뒤 연결한다.
6. 모든 필수 장면을 승인한다.

기대 결과: 필수 장면 전부가 승인된 뒤에만 다음 graph 단계로 진행한다. LG-8의 최종 확인 대상은 장면별 prompt 계약과 버전 연결이며, 실제 이미지 자동 검사와 승인 manifest 고도화는 LG-9에서 이어진다.

## 7. 선택적 API 확인

Swagger에서 다음 API를 확인할 수 있다.

- `GET /api/v1/projects/{project_id}/scene-prompts`
- `POST /api/v1/projects/{project_id}/scene-prompts/compile`
- `PATCH /api/v1/projects/{project_id}/scene-prompts/{scene_id}`

GET 결과에서 모든 active 장면에 `prompt_version`, `prompt_hash`, `reference_hash`, `identity_constraints`, `text_policy`, `brand_kit_visual_hash`, `expected_cost`가 있는지 확인한다. `include_stale=true`를 사용하면 이전 version의 `stale_reason`과 장면 하나만 포함된 `stale_impact`도 볼 수 있다.
