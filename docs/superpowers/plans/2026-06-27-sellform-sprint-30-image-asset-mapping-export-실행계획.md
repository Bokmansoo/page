# Sprint 30 - 상품 이미지 자산 매핑 및 상세페이지 삽입 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task.

## 1. 목표

Sprint 29에서 상세페이지 출력물이 “글 중심 카드”에서 “시각 섹션 중심”으로 한 단계 개선되었다. 하지만 아직 실제 상품 이미지가 상세페이지 본문에 충분히 들어가지 않아, 쿠팡/스마트스토어 상세페이지처럼 이미지가 중심이 되는 결과물과는 거리가 있다.

Sprint 30의 목표는 업로드되었거나 수집된 상품 이미지 자산을 상세페이지 섹션에 자동 매핑하고, page-editor 미리보기와 export PNG에 실제 이미지를 삽입하는 것이다.

최종 사용자는 다음 흐름을 기대한다.

1. 상품 링크 또는 상품 이미지 입력
2. AI 사실 카드 생성 및 확인
3. 상세페이지 초안 생성
4. 상품 이미지가 섹션별로 자동 배치된 상세페이지 확인
5. 필요하면 섹션별 이미지를 직접 교체
6. 쿠팡/스마트스토어용 긴 세로 이미지로 내보내기

## 2. 이번 스프린트에서 해결할 문제

현재 상태의 핵심 문제는 다음과 같다.

- `Asset` 모델과 `PageSection.image_asset_id`는 이미 존재하지만, 자동 매핑 흐름이 약하다.
- export 렌더러가 섹션별 실제 이미지 자산을 적극적으로 사용하지 않는다.
- page-editor에서 “이 섹션에 어떤 상품 이미지를 넣을지” 확인하거나 바꾸는 UX가 부족하다.
- 결과물이 여전히 텍스트 카드처럼 보이며, 실제 상세페이지 특유의 이미지 중심 흐름이 약하다.

Sprint 30에서는 새로운 복잡한 DB 구조를 만들기보다, 이미 존재하는 `Asset`과 `PageSection.image_asset_id`를 제대로 연결하는 데 집중한다.

## 3. 범위

### 포함

- 상품 이미지 자산 자동 매핑 서비스 추가
- 섹션별 이미지 자산 연결 API 추가
- 상세페이지 생성 후 이미지 자동 매핑 흐름 보강
- page-editor에서 섹션별 이미지 미리보기 및 수동 교체 UX 추가
- export PNG에 실제 상품 이미지 삽입
- 스냅샷 기반 export에서도 이미지 연결이 깨지지 않도록 보강
- 테스트 로그, 코드 리뷰 문서, 트러블슈팅 문서 작성

### 제외

- 이미지 생성 AI로 새 배경 이미지를 만드는 기능
  - 이는 Sprint 28 / 이후 비주얼 고도화 범위로 유지한다.
- 쿠팡/스마트스토어 자동 업로드
- Figma MCP 연동
- 소셜 영상 프레임 추출
  - 이는 Sprint 25~27 범위로 유지한다.
- 완전한 디자이너 수준의 템플릿 엔진
  - 이번 스프린트는 “실제 이미지가 상세페이지에 들어가는 최소 완성 흐름”에 집중한다.

## 4. 현재 구조 기준

### 기존 데이터 모델

이미 다음 구조가 존재한다.

- `Asset`
  - `id`
  - `project_id`
  - `source_type`
  - `filename`
  - `file_path`
  - `mime_type`
  - `file_size`
  - `created_at`

- `PageSection`
  - `id`
  - `page_id`
  - `section_type`
  - `title`
  - `body`
  - `image_asset_id`

따라서 Sprint 30에서는 원칙적으로 새 테이블을 만들지 않는다.

### 기존 파일 흐름

- 업로드 API: `backend/src/api/files.py`
- 페이지 API: `backend/src/api/pages.py`
- 시각 렌더링: `backend/src/services/visual_page_renderer.py`
- export 생성: `backend/src/services/export_service.py`
- page-editor: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- facts 화면: `frontend/src/app/workspace/projects/[id]/facts/page.tsx`

## 5. 설계 방향

### 5.1 이미지 자산 매핑 원칙

섹션별 이미지는 다음 우선순위로 연결한다.

1. 사용자가 직접 선택한 `image_asset_id`
2. 자동 매핑 결과
3. 프로젝트 대표 이미지
4. 이미지 없음 fallback

자동 매핑은 처음부터 완벽할 필요는 없다. 대신 예측 가능하고 사용자가 쉽게 수정할 수 있어야 한다.

### 5.2 섹션별 매핑 휴리스틱

| 섹션 타입 | 우선 이미지 |
| --- | --- |
| `hero`, `problem_statement`, `main_claim` | 대표 상품 이미지 |
| `secondary_benefit`, `main_claim_support` | 사용 장면, 라이프스타일 이미지 |
| `benefit_list`, `features` | 디테일 컷, 기능 설명 이미지 |
| `product_information`, `specifications` | 스펙표, 인증, KC, 구성품 이미지 |
| `summary_claim` | 대표 상품 이미지 또는 깔끔한 보조 이미지 |

파일명 기반 힌트는 다음처럼 사용한다.

- 대표 이미지: `main`, `hero`, `product`, `대표`, `상품`
- 사용 장면: `life`, `lifestyle`, `use`, `scene`, `사용`, `활용`
- 디테일: `detail`, `feature`, `기능`, `디테일`
- 스펙/인증: `spec`, `kc`, `cert`, `certificate`, `인증`, `스펙`, `상세`

### 5.3 스냅샷 원칙

export는 “현재 DB 상태”만 바라보면 나중에 섹션이나 이미지가 바뀌었을 때 과거 결과물이 재현되지 않을 수 있다.

따라서 다음 원칙을 둔다.

- page snapshot에는 `assets_snapshot`을 포함한다.
- section snapshot에는 `image_asset_id`를 포함한다.
- export는 가능하면 snapshot의 `image_asset_id`와 `assets_snapshot`을 우선 사용한다.
- snapshot에 없는 경우에만 현재 DB의 Asset을 fallback으로 사용한다.

## 6. 구현 작업

### 6.1 백엔드 - 이미지 자산 매핑 서비스 추가

파일:

- `backend/src/services/image_asset_mapper.py`
- `backend/tests/test_image_asset_mapper.py`

작업:

- [ ] 이미지 MIME 타입만 필터링한다.
- [ ] 파일명, source_type, section_type 기반 점수 계산 함수를 만든다.
- [ ] `map_image_assets_to_sections(sections, assets)` 함수를 만든다.
- [ ] 한 이미지를 모든 섹션에 반복 배치하지 않도록 기본 중복 제어를 넣는다.
- [ ] 이미지가 1장뿐이면 hero/main_claim 중심으로 사용하고 나머지는 비워둔다.
- [ ] 스펙/인증 이미지가 있으면 `product_information` 또는 `specifications`에 우선 배치한다.

테스트 예시:

- [ ] 대표 이미지가 `problem_statement` 또는 `main_claim`에 매핑된다.
- [ ] `kc/spec/cert` 파일명이 있는 이미지는 `product_information`에 매핑된다.
- [ ] 이미지가 없는 경우 빈 매핑을 반환한다.
- [ ] PDF나 텍스트 파일 자산은 이미지 매핑에서 제외된다.

### 6.2 백엔드 - 섹션 이미지 자동 매핑 API 추가

파일:

- `backend/src/api/pages.py`
- `backend/tests/test_page_image_mapping_api.py`

엔드포인트:

```http
POST /api/v1/projects/{project_id}/page/auto-map-images
```

요청 옵션:

```json
{
  "overwrite": false
}
```

응답 예시:

```json
{
  "project_id": "...",
  "assigned_count": 3,
  "skipped_count": 2,
  "assignments": [
    {
      "section_id": "...",
      "section_type": "main_claim",
      "asset_id": "...",
      "filename": "lumena-main-product.jpg",
      "reason": "대표 상품 이미지 후보"
    }
  ]
}
```

작업:

- [ ] 프로젝트와 페이지 접근 범위를 workspace 기준으로 검증한다.
- [ ] page가 없으면 명확한 404 또는 409 응답을 준다.
- [ ] `overwrite=false`일 때 기존 `image_asset_id`는 유지한다.
- [ ] `overwrite=true`일 때 기존 매핑을 재계산한다.
- [ ] 매핑 후 page snapshot 또는 autosave 흐름과 충돌하지 않도록 한다.

### 6.3 백엔드 - 상세페이지 초안 생성 후 자동 매핑 연결

파일:

- `backend/src/api/pages.py`
- `backend/tests/test_page_draft_image_mapping.py`

작업:

- [ ] `create_page_draft` 이후 프로젝트에 이미지 자산이 있으면 자동 매핑을 수행한다.
- [ ] 이미지 자산이 없으면 기존 동작을 유지한다.
- [ ] 자동 매핑 실패는 페이지 생성 자체를 실패시키지 않는다.
- [ ] 실패 시 응답 또는 로그에 fallback 상태를 남긴다.

원칙:

상세페이지 생성은 핵심 작업이므로, 이미지 매핑 실패 때문에 전체 생성이 실패하면 안 된다.

### 6.4 백엔드 - visual renderer에서 섹션별 이미지 슬롯 반영

파일:

- `backend/src/services/visual_page_renderer.py`
- `backend/tests/test_visual_page_renderer_image_slots.py`

작업:

- [ ] visual section 생성 시 `section.image_asset_id`를 읽는다.
- [ ] 섹션별로 이미지가 있으면 `visual_slot.kind = "product_image"`를 설정한다.
- [ ] `visual_slot`에 `asset_id`, `filename`, `file_path` 정보를 포함한다.
- [ ] 이미지가 없는 섹션은 기존 배경/카드형 fallback을 유지한다.
- [ ] 모든 섹션에 동일 이미지가 반복되는 문제를 막는다.

### 6.5 백엔드 - export PNG에 실제 이미지 삽입

파일:

- `backend/src/services/export_service.py`
- `backend/tests/test_export_image_asset_rendering.py`

작업:

- [ ] export 시 섹션별 `image_asset_id`에 해당하는 파일을 찾는다.
- [ ] Pillow로 이미지를 열고 섹션 비주얼 영역에 resize/crop한다.
- [ ] 이미지 비율이 깨지지 않도록 `ImageOps.fit` 또는 동등한 처리를 사용한다.
- [ ] 파일이 없거나 열 수 없으면 placeholder로 fallback한다.
- [ ] 투명 PNG, 큰 이미지, 작은 이미지에 대해 안전하게 처리한다.
- [ ] export 결과에 실제 이미지 색상이 반영되는지 테스트한다.

품질 기준:

- 상품 이미지가 텍스트보다 먼저 눈에 들어와야 한다.
- 텍스트는 이미지 위에 과하게 겹치지 않아야 한다.
- 긴 세로 상세페이지에서 섹션별 이미지와 카피가 번갈아 배치되어야 한다.

### 6.6 프론트엔드 - page-editor 이미지 매핑 UX

파일:

- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

작업:

- [ ] 상단 또는 우측 패널에 `이미지 자동 매핑` 버튼을 추가한다.
- [ ] 섹션 편집 패널에 이미지 자산 선택 드롭다운을 추가한다.
- [ ] 현재 연결된 이미지 썸네일을 보여준다.
- [ ] 이미지가 없는 경우 “이미지 없음” 상태를 명확히 표시한다.
- [ ] 선택 변경 시 autosave 또는 명시 저장 흐름에 반영한다.
- [ ] 자동 매핑 후 섹션 리스트와 미리보기를 갱신한다.

UX 문구 예시:

- “상품 이미지 자동 배치”
- “이 섹션에 사용할 이미지”
- “이미지 없음”
- “자동 매핑 결과 3개 섹션에 이미지가 연결되었습니다.”

### 6.7 프론트엔드 - export 전 확인 UX

파일:

- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

작업:

- [ ] export 전에 이미지가 하나도 없는 경우 경고를 표시한다.
- [ ] 이미지가 1장 이상 연결된 경우 연결 개수를 표시한다.
- [ ] 이미지 없는 섹션은 경고가 아니라 보조 안내로 표시한다.

예시:

```text
이미지 연결 3개 / 전체 섹션 7개
상품 이미지가 적으면 결과물이 텍스트 중심으로 보일 수 있습니다.
```

## 7. 테스트 계획

### 백엔드 테스트

실행:

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

검증:

- [ ] 이미지 매핑 서비스 단위 테스트 통과
- [ ] 자동 매핑 API 테스트 통과
- [ ] page draft 이후 이미지 매핑 테스트 통과
- [ ] export PNG 이미지 삽입 테스트 통과
- [ ] 기존 export/page/facts 테스트 회귀 없음

### 프론트엔드 테스트

실행:

```cmd
cd frontend
npm.cmd run build
```

검증:

- [ ] page-editor 빌드 성공
- [ ] 이미지 자산 선택 UI 타입 오류 없음
- [ ] 자동 매핑 버튼 API 호출 타입 오류 없음

### 수동 QA

시나리오:

1. PostgreSQL-only 모드로 서버 실행
2. 새 상품 프로젝트 생성
3. 상품 이미지 2~3장 업로드
4. 사실 카드 3개 이상 확인
5. 상세페이지 초안 생성
6. page-editor에서 이미지 자동 매핑 실행
7. 섹션별 이미지 표시 확인
8. export PNG 생성
9. 결과물에서 이미지와 텍스트가 섞여 보이는지 확인

완료 기준:

- [ ] 업로드한 상품 이미지가 page-editor 미리보기에 보인다.
- [ ] export PNG에도 실제 상품 이미지가 들어간다.
- [ ] 이미지가 없는 프로젝트는 기존처럼 fallback 렌더링된다.
- [ ] 자동 매핑 결과를 사용자가 직접 바꿀 수 있다.

## 8. 문서 산출물

구현 완료 후 다음 문서를 작성한다.

- `docs/testing/2026-06-27-sellform-sprint-30-image-asset-mapping-test-log.md`
- `docs/reviews/2026-06-27-sellform-sprint-30-code-review.md`
- `docs/troubleshooting/2026-06-27-sellform-sprint-30-image-assets.md`

리뷰 문서에는 반드시 다음을 남긴다.

- 변경 요약
- 기획 대비 구현 여부
- 발견 이슈
- 조치 완료 항목
- 테스트 증적
- 남은 위험

## 9. 리스크와 대응

### R1. 이미지 파일 경로가 깨질 수 있음

대응:

- DB에는 상대 경로를 유지한다.
- export 시 `settings.UPLOAD_DIR` 기준으로 절대 경로를 안전하게 복원한다.
- 파일 없음 fallback을 둔다.

### R2. 자동 매핑 품질이 낮을 수 있음

대응:

- 자동 매핑은 “초안”으로 취급한다.
- 사용자가 섹션별 이미지를 직접 바꿀 수 있게 한다.
- 매핑 reason을 응답에 포함해 디버깅 가능하게 한다.

### R3. 이미지가 텍스트 가독성을 해칠 수 있음

대응:

- 텍스트를 이미지 위에 직접 올리는 방식은 최소화한다.
- 기본은 이미지 영역과 텍스트 영역을 분리한다.
- 이후 고도화에서 오버레이 카드, 그라데이션 마스크를 추가한다.

### R4. export 성능 저하

대응:

- export 시 이미지를 필요한 크기로만 리사이즈한다.
- 큰 이미지는 Pillow 처리 단계에서 제한한다.
- 실패한 이미지는 즉시 fallback한다.

## 10. 완료 정의

Sprint 30은 다음 조건을 만족하면 완료로 본다.

- [ ] 이미지 자산 자동 매핑 서비스가 있다.
- [ ] page-editor에서 섹션별 이미지를 확인하고 바꿀 수 있다.
- [ ] export PNG에 실제 상품 이미지가 들어간다.
- [ ] 이미지가 없는 경우에도 기존 fallback이 유지된다.
- [ ] 백엔드 전체 테스트가 통과한다.
- [ ] 프론트엔드 빌드가 통과한다.
- [ ] 테스트 로그, 코드 리뷰, 트러블슈팅 문서가 작성된다.

## 11. 다음 스프린트 후보

Sprint 30 완료 후 다음 고도화 후보는 다음과 같다.

1. Sprint 31 - 이미지 중심 상세페이지 템플릿 고도화
   - hero 이미지, 상세 컷, 사용 장면, 스펙 이미지가 섞인 진짜 상세페이지형 레이아웃

2. Sprint 32 - AI 이미지/배경 생성과 실제 상품 이미지 합성
   - 상품 분위기에 맞는 배경 생성
   - 실제 상품 이미지와 배경 합성

3. Sprint 25~27 - 소셜 영상 기반 상세페이지 생성
   - 인스타그램/릴스/쇼츠 링크에서 장면과 카피 후보 추출

추천 순서는 Sprint 30을 먼저 완료한 뒤 Sprint 31 또는 Sprint 25로 넘어가는 것이다. 현재 가장 큰 병목은 “AI가 글은 만들지만 상세페이지처럼 보이지 않는 문제”이므로, 실제 상품 이미지 삽입을 먼저 해결하는 편이 좋다.
