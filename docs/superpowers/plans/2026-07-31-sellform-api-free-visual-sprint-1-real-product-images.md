# Sellform Sprint 1 실제 상품 이미지 우선 연결 실행계획

**상위 기획:** [이미지 API 없는 상품 비주얼 자동 조합 기획](../specs/2026-07-31-sellform-api-free-product-visual-composition-design.md)  
**목표:** 업로드·URL 수집 이미지를 상세페이지에 우선 연결하고 최종 결과에서 빨간 Mock 이미지를 제거한다.  
**기간:** 1주  
**의존성:** Sprint 0 완료

## 범위

- 실제 이미지 우선 선택 정책
- HERO와 상품 소개 섹션 이미지 연결
- Mock 빨간 이미지의 사용자 결과 노출 차단
- 원본 파일과 파생 사용 관계 보존
- 내부 `ai_generated` 배지 제거

## 예상 수정 파일

- `backend/src/agents/nodes/image_generation/agent.py`
- `backend/src/agents/mock_outputs.py`
- `backend/src/services/image_asset_mapper.py`
- `backend/src/services/page_asset_policy.py`
- `backend/src/api/pages.py`
- `frontend/src/components/GeneratedDetailPageResult.tsx`
- `frontend/src/components/detail-page/DetailPageDocument.tsx`
- 관련 backend 및 frontend 테스트

## 작업

### Task 1: 실제 이미지 우선 정책

- [ ] 업로드 이미지와 URL 수집 이미지가 있을 때 Mock 생성 자산을 만들지 않는 테스트를 작성한다.
- [ ] `upload > approved URL image > placeholder` 우선순위를 명시한다.
- [ ] HERO는 상품 전체가 보이는 이미지를 우선 사용한다.
- [ ] 실제 이미지가 전혀 없으면 빨간 이미지를 만들지 않고 구조화된 누락 상태를 반환한다.

### Task 2: 섹션 연결

- [ ] 대표 이미지가 HERO의 `image_asset_id`에 저장되는지 검증한다.
- [ ] 상품 소개 섹션에 사용 가능한 두 번째 이미지를 연결한다.
- [ ] 동일 이미지 재사용 시 원본 ID를 유지한다.
- [ ] 로컬 업로드 URL이 미리보기와 export 양쪽에서 접근 가능한지 확인한다.

### Task 3: 사용자 화면 정리

- [ ] 빨간 Mock 이미지와 `ai_generated` 내부 배지를 최종 결과에서 제거한다.
- [ ] 이미지가 없을 때 “사진을 추가해 주세요” 상태를 표시한다.
- [ ] 이미지 후보 패널이 실제 이미지의 출처를 구분해 보여준다.
- [ ] 편집용 상태가 JPG/PNG에 포함되지 않도록 한다.

## 테스트 시나리오

1. 업로드 이미지 1장: HERO에 해당 이미지가 표시된다.
2. URL 이미지 여러 장: 대표 후보가 HERO에 연결된다.
3. 업로드와 URL 이미지 동시 존재: 업로드 이미지가 우선한다.
4. 이미지 없음: 빨간 사각형 없이 입력 요청을 표시한다.
5. 다운로드: 실제 상품 사진이 JPG에 포함된다.

## 완료 기준

- [ ] 기준 상품 1종에서 실제 상품 사진이 HERO에 표시된다.
- [ ] 최종 미리보기와 다운로드에 빨간 Mock 이미지가 없다.
- [ ] 상품 사진의 비율, 색상과 로고가 변하지 않는다.
- [ ] 이미지가 없는 상태를 성공한 AI 이미지로 표시하지 않는다.

## 다음 스프린트 인계

Sprint 2는 연결된 실제 이미지에 역할, 해상도, 품질과 사용 위치 메타데이터를 추가한다.

