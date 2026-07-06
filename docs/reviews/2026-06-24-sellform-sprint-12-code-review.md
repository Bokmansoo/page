# 코드 리뷰: Sellform Sprint 12 (Image OCR & Multimodal Fact Extraction)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-24 |
| 리뷰 범위 | image text extractor, source collector image OCR integration, fact extractor image candidates, UI fallback |
| 리뷰어 | Antigravity (AI Coding Assistant) |
| 상태 | **승인 완료 (Approved)** |

## 1. 변경 요약
- **Mock OCR Engine 개발**: 이미지 파일명을 기반으로 스펙 정보(USB-C, 4000mAh 등)를 모킹하여 텍스트 및 신뢰도 점수를 산출하는 단위 모듈 `MockImageTextExtractor`를 구현했습니다.
- **Source Collector의 OCR 연동**: `collect_project_sources`에서 이미지 에셋의 OCR 모듈을 수행하고, 텍스트가 있을 때 `"image"` 타입 소스로 투입하게 조치했습니다.
- **Fallback 호환성 유지**: 텍스트 분석에 실패한 일반 이미지의 경우, 기존 테스트와의 역방향 호환을 위해 `"Uploaded image asset: {filename}"` 텍스트로 대체 수집하여 `failed_sources`에 분석 실패(`image_text_unavailable`) 사유를 추가하도록 안전한 이중 처리 구조를 구현했습니다.
- **Fact Extractor의 이미지 파싱 및 신뢰도 제한**: 이미지 소스 텍스트로부터 스펙 속성을 분석해 사실 카드를 제안하되, 신뢰도 상한선(0.72)을 설정하고 강제적으로 `needs_review: True` 설정을 적용하여 무검증 반영 리스크를 원천 차단했습니다.
- **UI 번역 및 경고 알림 연동**: `page.tsx`에 `image_text_unavailable` 에러 발생 시 한국어 알림 및 전체 안내 문구 배너가 나타나도록 UI를 정비했습니다.

## 2. 계획 대비 충족 여부

| 기준 | 상태 | 근거 |
| --- | --- | --- |
| 이미지 OCR/mock provider | **충족** | `backend/tests/test_image_text_extractor.py` (2 passed) |
| 이미지 텍스트 기반 사실 후보 | **충족** | `backend/tests/test_facts.py` (11 passed) |
| source_asset_id 연결 | **충족** | API 응답 및 데이터 저장 로직 검증 완료 |
| 낮은 신뢰도 자동 확정 방지 | **충족** | `needs_review=True` 적용 및 자동 `confirmed` 차단 확인 |
| 이미지 분석 실패 fallback | **충족** | `failed_sources` 수집 및 UI 한글 매핑 렌더링 확인 |
| 테스트/빌드 | **충족** | pytest (57 passed) 및 Next.js build (Compiled successfully) |

## 3. 이슈 목록
- 없음. 기존 통합/회귀 테스트 케이스들과도 하위 호환성을 완벽하게 만족합니다.

## 4. 테스트 증적
- **단위/통합 테스트**: `uv run pytest -q` -> `57 passed`.
- **프론트 빌드**: `npm.cmd run build` -> `Compiled successfully`.

## 5. 결론
1.0 상세페이지 제작 프로세스 중 두 번째 큰 유저 리스크였던 "이미지 기반 사양 수동 기재 피로도"를 mock OCR 구조의 안정적 연동을 통해 해결했습니다. 추후 API adapter 교체만으로 Google Cloud Vision 또는 GPT-4o 멀티모달 서비스로 쉽게 승격할 수 있는 확장 가능한 시스템 기반이 완료되었습니다.
