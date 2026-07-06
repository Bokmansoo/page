# 코드 리뷰: Sellform Sprint 43 AI Sales Strategy & Direction Variants

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `sprint-43-ai-sales-strategy` |
| 리뷰 일자 | 2026-06-30 |
| 리뷰 범위 | AI 세일즈 전략 수립 API 및 다중 기획 방향 매핑, 가격 및 이미지 누락 예외 처리 분기, 프론트엔드 상품 이해/전략 검수 및 3대 기획 방향 선택 카드 통합 연동 |
| 관련 기획·작업 | [2026-06-30-sellform-sprint-43-ai-sales-strategy-direction-variants.md](file:///c:/page/docs/superpowers/plans/2026-06-30-sellform-sprint-43-ai-sales-strategy-direction-variants.md) |
| 리뷰어 | Antigravity |
| 상태 | 승인 |

## 1. 변경 요약

- **AI 세일즈 전략 수립 (Sales Strategy Service)**:
  - 입력된 인테이크 원본 텍스트를 기반으로 상품의 유형(키즈 상품, 홈 인테리어 상품, 테크/전자 제품, 일반 상품)을 감지하고, 그에 따른 핵심 타겟 고객, 페인 포인트(구매자 문제), 핵심 소구점, 톤앤매너, 가격/할인 전략, 리스크 주의사항 등을 결정론적으로 도출하는 백엔드 서비스를 구축했습니다.
- **누락/예외 케이스 복구 처리**:
  - 가격이나 할인 전략 정보가 누락된 경우, `"등록된 가격 전략 및 할인 정보가 없습니다. (수정 필요)"` 메시지와 함께 신뢰도 수준을 `"low"`로 설정하고, 판매자가 선택할 수 있는 대안 추천 리스트(`edit_options`)를 제공합니다.
  - 첨부 이미지 자산이 존재하지 않는 경우, `"등록된 이미지 자산이 없습니다. 이미지를 첨부해주세요."` 메시지와 함께 신뢰도를 `"low"`로 낮추어 수동 보완을 유도합니다.
- **3대 상세페이지 기획 방향 도출 (Direction Variants)**:
  - 설득형(문제 해결형), 감성형(라이프스타일형), 정보형(스펙 강조형)의 3가지 컨셉 방향 카드를 제공합니다.
  - 상품 정보 및 카테고리에 맞는 최적의 1개 컨셉을 AI가 자동 추천(`is_recommended`)해주며, 추천 사유, 타겟 고객군, 추천 디자인 분위기, 상세페이지 단락 레이아웃 흐름을 명확히 전달합니다.
- **하위 호환성 (Backward Compatibility) 유지**:
  - 프론트엔드에서 새로 제안된 3가지 세일즈 방향(`persuasion`, `emotional`, `information`) 중 하나를 선택하면, 백엔드 API에서 기존 상세페이지 생성 및 Figma 플러그인 연동 규격에 맞게 각각 기존 스타일 템플릿(`problem_solution`, `lifestyle`, `spec_focused`)으로 자동 매핑하여 저장합니다. 기존 Sprint 37의 스타일 선택 비즈니스 로직과 API 테스트 슈트가 전혀 깨지지 않도록 하였습니다.
- **UI/UX 통합 확장**:
  - Sprint 42의 "상품 이해" 카드를 별도로 독립시키지 않고 연장하여, 1단계 상품 분석 확인 완료 시 자연스럽게 2단계 AI 세일즈 전략 확인 및 상세페이지 기획 방향 선택 뷰로 내부 서브스텝 전환이 일어날 수 있도록 UI를 고도화했습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- **기획·결정 문서**: `2026-06-30-sellform-sprint-43-ai-sales-strategy-direction-variants.md`
- **코드·화면·API**:
  - 백엔드: [sales_strategy_service.py](file:///c:/page/backend/src/services/sales_strategy_service.py), [projects.py](file:///c:/page/backend/src/api/projects.py), [pages.py](file:///c:/page/backend/src/api/pages.py), [style_strategy_service.py](file:///c:/page/backend/src/services/style_strategy_service.py)
  - 프론트엔드: [page.tsx](file:///c:/page/frontend/src/app/workspace/projects/new/page.tsx), [ProductUnderstandingCard.tsx](file:///c:/page/frontend/src/components/ProductUnderstandingCard.tsx)
- **테스트 증적**:
  - [test_sales_strategy_service.py](file:///c:/page/backend/tests/test_sales_strategy_service.py)
  - [test_sales_strategy_api.py](file:///c:/page/backend/tests/test_sales_strategy_api.py)
  - [test_style_strategy_api.py](file:///c:/page/backend/tests/test_style_strategy_api.py) (기존 기능 리그레션 확인용)

### 핵심 흐름

```text
[1단계: 상품 분석 카드 (Product Type, Target, Problem)] (Sellform Light UI)
      ↓
[확인 완료 및 세일즈 전략 확인 클릭] → GET /projects/{project_id}/sales-strategy 호출
      ↓
[2단계: 세일즈 전략 수립 카드 진입]
  ├─ 5가지 핵심 항목 검수 (신뢰도 배지 노출: 높음, 보통, 확인 필요)
  │   └─ 가격/이미지 누락 시 low 상태 경고 및 대안 추천 리스트 제공
  └─ 상세페이지 기획 방향 선택 (설득형 / 감성형 / 정보형)
      ↓
[선택한 기획 방향으로 생성하기 클릭] → POST /projects/{project_id}/style-candidates/{key}/select 호출
      ↓ (backend legacy_keys 매핑: persuasion -> problem_solution 등)
[프로젝트 상태 'ready' 업데이트 및 /workspace 대시보드 진입]
```

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 발견 이슈 없음
- 모든 단위 기능 및 UI 스타일링 명세 검증이 성공하였으며, 발견된 결함이 없습니다.

## 4. 우선순위 권고
1. **머지 승인** — 모든 리그레션 테스트와 신규 API 기능 테스트가 백엔드에서 100% 통과하였고, 프론트엔드도 프로덕션 빌드 컴파일을 성공하여 에러가 없으므로 즉시 머지하는 것을 권장합니다.

## 5. 긍정적인 부분

- **하위 호환성 유지 설계**: 기획서에 명시된 새로운 3대 세일즈 방향 명칭이 기존 데이터베이스 필드나 Figma/PNG 익스포트 파이프라인의 명칭들과 불일치했으나, API 저장소 레이어에서 `legacy_keys` 매핑 테이블을 구현하여 백엔드 파이프라인의 파괴적 수정 없이 완벽히 수용했습니다.
- **점진적인 마법사 스텝 통합**: 상품 분석 카드와 세일즈 전략 수립을 완전히 별개의 화면으로 분리하지 않고, 한 컴포넌트 내의 애니메이션/단계 흐름으로 묶어 사용자의 입력과 검수 피로도를 획기적으로 줄였습니다.

## 6. AI·사실 신뢰성 검토

- **사용한 사실과 근거**: 사용자가 인풋으로 기입한 텍스트에 포함된 상품 특성 키워드("유아", "장난감", "매트", "식탁", "진공", "텀블러" 등)를 기반으로 상품군을 정밀 매핑하여 적합성 높은 세일즈 추천 문구를 동적 생성합니다.
- **미확인 사실 처리**: 가격 정보나 이미지 누락 시 경고 문구를 주입하고 신뢰도를 "확인 필요"로 낮춰, 잘못되거나 비어있는 사실이 확정 페이지에 포함되는 것을 미연에 방지합니다.

## 7. 검증 증적

### 자동 테스트
- 백엔드 테스트를 다음 명령어로 실행하여 성공적으로 완료했습니다.
  ```bash
  uv run pytest tests/test_sales_strategy_service.py tests/test_sales_strategy_api.py -v
  uv run pytest tests/test_style_strategy_api.py -v
  ```
- **테스트 결과**: 모든 신규 기능 및 기존 리그레션 테스트 9개 항목 100% 통과.

### 프론트엔드 정적 빌드
- Next.js 프로덕션 빌드 컴파일 및 타입 검사를 수행했습니다.
  ```bash
  npm run build
  ```
- **결과**: `✓ Compiled successfully` 및 타입 체크 성공.

## 8. 결론

- **결론**: 승인
- **결정 이유**: 기획서의 의도대로 상품 이해 카드를 전략 확인과 방향 선택으로 부드럽게 연장하였으며, 신뢰도 배지 제공, 예외 사항(가격/이미지 미등록) 식별 및 대안 추천 리스트 연동 등이 가이드라인에 맞게 완성도 높게 구현되었습니다.
