# Sellform Sprint 44.5 AI Image Provider Generation 코드리뷰

**검토 기준:** `docs/superpowers/plans/2026-06-30-sellform-sprint-44-5-ai-image-provider-generation.md`

**결론:** 자동화로 검증 가능한 Sprint 44.5 범위는 기획대로 구현되었으며, 병합을 막는 코드 결함은 발견되지 않았다. 실제 OpenAI 유료 호출을 사용하는 수동 스모크 테스트만 운영자 승인과 API 키가 필요해 수행하지 않았다.

## 검토 결과

### 차단 이슈

없음.

### 이번 검토에서 보완한 사항

1. OpenAI Image API 요청을 현재 계약에 맞게 정리했다.
   - 제품 원본이 있는 작업은 `images.edit`와 모든 참조 이미지를 사용한다.
   - 비제품 보조 이미지는 `images.generate`를 사용한다.
   - `quality`, `background`, `output_format`, `input_fidelity`를 역할에 맞게 전달한다.

2. 생성 실행의 실패 안전성을 강화했다.
   - 속도 제한과 타임아웃은 한 번 재시도한다.
   - API 키 누락은 `AUTHENTICATION_FAILED`로 표준화한다.
   - 존재하지 않는 원본 파일과 다른 프로젝트의 자산은 호출 전에 차단한다.
   - 중복 실행은 유료 호출과 자산 중복 생성을 막는다.

3. 품질 및 제품 정체성 게이트를 보완했다.
   - 실제 반환 MIME과 이미지 바이트 형식을 대조한다.
   - 디코딩, 최소 크기, 빈 이미지, 색상 변화, 실루엣 차이를 검사한다.
   - 부정 지시문의 `logo`, `text` 같은 단어를 잘못 위반으로 판단하지 않는다.
   - 마케팅 문구나 인증 마크를 생성하도록 요구한 제품 이미지 작업은 거절한다.

4. 승인과 거절 상태 전이를 바로잡았다.
   - `needs_review` 상태만 승인할 수 있다.
   - 거절된 생성 자산은 감사 목적으로 유지하고 원본 사진을 다시 선택한다.
   - 재생성 및 실패 후 재시도도 비용 확인을 다시 거친다.
   - UI에서 `rejected` 상태와 기존 생성 결과를 확인할 수 있다.

5. 환경 설정 예시를 추가했다.
   - `SELLFORM_IMAGE_PROVIDER`
   - `SELLFORM_IMAGE_MODEL`
   - `SELLFORM_IMAGE_PREVIEW_MODEL`
   - `SELLFORM_IMAGE_OUTPUT_FORMAT`

## 기획 충족 확인

- 공급자 중립 요청/응답 및 프로토콜: 충족
- GPT Image 생성/편집 어댑터와 오류 코드: 충족
- 영속 작업 상태, 비용 승인, 재시도, 자산 저장: 충족
- 제품 원본 보호와 품질 경고: 충족
- 워크스페이스 및 프로젝트 범위 API: 충족
- 승인 전 검토 및 원본 복원 UI: 충족
- Sprint 45가 승인된 생성 자산을 사용하는 연결: 충족

## 검증

```text
uv run --project backend pytest backend/tests/test_image_generation_provider.py backend/tests/test_image_generation_service.py backend/tests/test_image_generation_api.py -q
20 passed

uv run --project backend pytest backend/tests -q
232 passed

cd frontend
npm.cmd run build
Compiled successfully
```

기존 코드의 SQLAlchemy/Pydantic 사용 중단 예정 경고와 `<img>` 최적화 경고는 남아 있으나 Sprint 44.5 기능 오류는 아니다.

## 남은 수동 확인

운영자가 비용을 승인하고 `OPENAI_API_KEY`를 설정한 환경에서 제품 사진 한 장으로 다음 두 작업을 각각 한 번 확인해야 한다.

1. 투명 배경 제품 누끼 생성
2. 원본 제품을 참조한 라이프스타일 장면 생성

자동 품질 검사는 결정론적 휴리스틱이므로 사람 수준의 로고/OCR 및 제품 동일성 판별을 대신하지 않는다. 따라서 `needs_review`와 판매자 승인 단계는 계속 필수다.
