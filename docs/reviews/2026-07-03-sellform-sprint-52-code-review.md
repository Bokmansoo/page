# 코드 리뷰: Sprint 52 Real Image Pipeline

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `sprint-52-real-image-pipeline` |
| 리뷰 일자 | 2026-07-03 |
| 리뷰 범위 | 이미지 생성 및 QA 연결, Mock 일관성 보완, 프론트엔드 UI 상태 반영 및 E2E 테스트 추가 |
| 관련 기획·작업 | `2026-07-03-sellform-sprint-52-real-image-pipeline.md` 기획안 |
| 리뷰어 | Antigravity |
| 상태 | 승인 |

## 1. 변경 요약

- **Mock 입력 상품/업로드 이미지 일관성 보완**: `mock_outputs.py`의 mock 빌더가 `product_name` 및 `description` 컨텍스트를 활용하도록 동적 매핑을 지원하고, 업로드 및 URL 이미지 소스에 맞춰 `uploaded`, `url-extracted`, `mock-generated` 레이블링을 적용하도록 일관성을 확보했습니다.
- **이미지 Provider 계약 강화**: `ImageGenerationRequest`에 비용 승인 정보 및 참조 자산 ID 리스트를 포함시키고, `OpenAIImageProvider`에서 비용 미승인 시 API 호출을 즉각 차단하도록 안정 장치를 강화했습니다.
- **상품 정체성 QA 연결**: `ImageGenerationService`에 `review_generated_asset` 품질 필터 검수 단계를 연계하여 Pillow 기반의 `ProductIdentityValidator`를 통해 이미지 해상도, 빈 화면(단색), 텍스트/로고/인증마크 삽입 등의 브랜드 가이드 위반 여부를 검증하도록 구축했습니다.
- **이미지 승인 UI 연결**: 프론트엔드 `VisualPackagePanel.tsx` 및 `GenerationProgressShell.tsx`에서 신규 상태 명세인 `비용 승인 필요`, `생성 중`, `검수 필요`, `선택됨`, `재생성`, `이 이미지 사용`을 올바르게 반영하고, `url-extracted` 소스 타입을 처리하도록 구성했습니다.
- **E2E 테스트 추가**: `real-image-approval-flow.spec.ts`를 작성하여 각 상태 전환에 따른 라벨 및 버튼 노출 여부를 Playwright를 통해 성공적으로 검증 완료하였습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- 기획·결정 문서: [2026-07-03-sellform-sprint-52-real-image-pipeline.md](file:///c:/page/docs/superpowers/plans/2026-07-03-sellform-sprint-52-real-image-pipeline.md)
- 코드·화면·API:
  - 백엔드 서비스: [image_generation_service.py](file:///c:/page/backend/src/services/image_generation_service.py), [image_generation_provider.py](file:///c:/page/backend/src/services/image_generation_provider.py), [openai_image_provider.py](file:///c:/page/backend/src/services/openai_image_provider.py), [product_identity_validator.py](file:///c:/page/backend/src/services/product_identity_validator.py)
  - 프론트엔드 컴포넌트: [VisualPackagePanel.tsx](file:///c:/page/frontend/src/components/VisualPackagePanel.tsx), [GenerationProgressShell.tsx](file:///c:/page/frontend/src/components/GenerationProgressShell.tsx)
- 테스트 증적:
  - 단위/통합 테스트: [test_real_image_pipeline_contract.py](file:///c:/page/backend/tests/test_real_image_pipeline_contract.py), [test_mock_generation_product_consistency.py](file:///c:/page/backend/tests/test_mock_generation_product_consistency.py)
  - E2E 테스트: [real-image-approval-flow.spec.ts](file:///c:/page/frontend/e2e/real-image-approval-flow.spec.ts)

### 핵심 흐름

```text
[입력 데이터 & 상품 컨텍스트] → [이미지 생성 기획 / 비용 게이트] → [AI 생성 & Pillow QA 검수] → [사용자 승인 / 반려] → [상세페이지 조립 완료]
```

- **정상 흐름**:
  1. 기획 단계에서 이미지 생성 비용 산정 및 고비용 등급 여부 판정.
  2. 고비용인 경우 `awaiting_cost_approval` 상태로 비용 대기 게이트 발동.
  3. 사용자가 비용을 승인하면 `generating`으로 전이 및 AI API 호출.
  4. 생성물이 나오면 해상도/단색 여부/텍스트 삽입 규정 검수 거쳐 `needs_review` 진입.
  5. 사용자가 최종 승인하면 `approved` 처리되어 상세페이지 레이아웃에 매핑되고 패키지 빌드.
- **빈 입력·누락 자료**: 업로드된 이미지나 URL 이미지가 부족한 경우에는 AI 모의 생성 플레이스홀더(`mock-generated`)로 안전하게 매칭되어 중단 없이 진행됩니다.
- **AI·외부 서비스 실패**: AI 호출 지연/오류 시 최대 2회 재시도(Retry)하며 최종 실패 시 `failed` 상태로 이행되어 `재생성` 또는 원본 이미지 사용이 가능합니다.

## 3. 이슈 목록

발견 이슈 없음

## 4. 우선순위 권고

1. **머지 완료** — 80개 백엔드 단위/계약 테스트 및 전체 E2E 테스트가 100% 통과함을 확인했으므로 즉각적인 머지를 권장합니다.

## 5. 긍정적인 부분

- **브랜드 안전성 가드레일**: 생성된 이미지 내 텍스트나 허가되지 않은 마크가 포함되었는지 프롬프트 및 이미지를 통해 자동으로 검출하고 기각(`failed` / `IDENTITY_GATE_REJECTED`)하여 브랜딩 품질의 안전성을 크게 개선했습니다.
- **하위 호환성 유지**: 기존 단위 테스트 코드와의 하위 호환성을 유지하기 위해 신규 파라미터의 기본값을 적절하게 설정함으로써 기존의 파이프라인이나 검사 동작에 영향이 없도록 설계되었습니다.

## 6. AI·사실 신뢰성 검토

- **사용한 사실과 근거**: 상품 명 및 상세 입력 내용을 기반으로 일관성 있게 프롬프트와 사본(Copy)이 빌드되도록 검증을 거쳤습니다.
- **품질·비용·안전성 평가**: 실제 AI 호출에 필요한 비용 게이팅이 백엔드 및 Provider 수준에서 확실하게 차단됨을 확인했습니다.

## 7. 검증 증적

- **자동 테스트**:
  - 백엔드 테스트 실행:
    ```powershell
    uv run pytest -v
    ```
    결과: 290 passed 성공.
  - 프론트엔드 E2E 테스트 실행:
    ```powershell
    cmd.exe /c npx playwright test e2e/real-image-approval-flow.spec.ts
    ```
    결과: 1 passed 성공.

## 8. 결론

- **결론**: 승인
- **결정 이유**: 실 이미지 생성의 비용 게이팅, Pillow를 이용한 자동 QA 정책 연결, 프론트엔드 UI/UX 라벨 매칭 및 신규 E2E 테스트 구축까지 기획안에 명시된 요구사항을 예외 케이스 처리(Exclusion Prompt 매칭 우회 등)를 포함하여 완성도 높게 구현하였습니다.
