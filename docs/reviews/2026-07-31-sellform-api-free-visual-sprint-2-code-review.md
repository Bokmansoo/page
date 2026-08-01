# Sellform API-Free Visual Sprint 2 코드리뷰

## 결론

Sprint 2 기획서 재검토에서 발견된 미완료 항목까지 보완했다. 이제 **실상품 이미지의 역할·품질 상태 저장, 자동 점검, 대표 이미지 1개 추천·확정, 판매자 역할 수정, 낮은 품질 HERO 보호**가 구현되었다.

Sprint 1의 실상품 사진 우선 정책은 유지된다. 이 Sprint는 이미지를 새로 만들거나 변형하지 않으며, 원본 사진을 분석해 배치 판단에 사용할 메타데이터만 저장한다.

## 기획 대비 구현 확인

| 기획 항목 | 구현 | 확인 위치 |
| --- | --- | --- |
| 역할·품질 데이터 계약 | 완료 | `Asset`에 `asset_role`, `role_confidence`, `quality_status`, `identity_status`, `width`, `height`, `quality_warnings` 등을 추가했다. |
| 기존 DB 호환 및 backfill | 완료 | 런타임 schema compatibility에 컬럼 추가를 포함했고, 프로젝트 자산 목록을 열면 이전 자산을 한 번 검사한다. |
| Pillow 기반 해상도·비율·형식 검사 | 완료 | `image_asset_inspector.py`가 로컬 이미지의 크기·형식·손상 여부를 검사한다. |
| 중복 파일 검사 | 완료 | SHA-256 해시로 같은 프로젝트의 완전 동일 파일을 `DUPLICATE_FILE` 경고로 표시한다. |
| 손상 파일만 자동 거절 | 완료 | 열 수 없는 파일은 `rejected`; 낮은 해상도·비율·중복은 `warning`으로만 남긴다. |
| 역할 자동 추천과 신뢰도 | 완료 | 파일명·출처·URL·저장된 OCR 텍스트를 사용하고, 대표 후보는 역할 신호·품질·픽셀 수를 함께 비교한다. |
| 대표 이미지 1개 확정 | 완료 | 자동 추천은 하나만 지정하며, 판매자가 `대표로 선택`을 누르면 다른 대표 선택은 해제된다. |
| 판매자 역할 변경 우선 | 완료 | `PATCH /api/v1/projects/{project_id}/assets/{asset_id}/classification`으로 역할·대표 선택을 직접 정하면 자동 분류가 덮어쓰지 않는다. |
| 이미지 패널의 역할·품질 표시 | 완료 | 완료 상세페이지의 `섹션별 이미지 후보` 패널에 썸네일, 역할, 신뢰도, 해상도, 크롭 상태와 경고를 함께 표시한다. |
| 저품질 HERO 보호 | 완료 | 품질 경고 자산은 자동 HERO 매핑에서 제외한다. 판매자가 직접 고르면 확인 창과 API 확인 플래그가 필요하다. |
| 사용 위치 표시 | 완료 | 자산별로 현재 적용 중인 섹션을 `사용 섹션`으로 표시하고, 기존 섹션별 후보 패널에서 즉시 교체할 수 있다. |

## 주요 구현 내용

### 1. 자산 검사 서비스

`backend/src/services/image_asset_inspector.py`를 추가했다.

- 지원 역할: `product_main`, `product_detail`, `usage_scene`, `components`, `package`, `spec_reference`, `unknown`
- 품질 상태: `usable`, `warning`, `rejected`
- 상품 정체성 상태: 기본 `needs_review`
- 경고 코드: `LOW_RESOLUTION`, `EXTREME_ASPECT_RATIO`, `DUPLICATE_FILE`, `IMAGE_FILE_CORRUPT` 등
- URL만 있는 원격 이미지는 다운로드하지 않고 `REMOTE_IMAGE_NOT_DOWNLOADED` 경고로 검수 대상에 둔다.
- `safe_crop_status`는 원본 비율 기준으로 `safe | needs_review | not_recommended`를 기록한다. 실제 피사체 위치를 보는 비전 판정은 하지 않는다.

### 2. 기존 흐름과의 연결

- 업로드 직후 이미지 검사 결과를 저장한다.
- 기존 프로젝트는 자산 목록/비주얼 작업을 열 때 lazy backfill한다.
- 기존 Sprint 2 자산도 `classification_version`으로 한 번만 재점검해 새 OCR·안전 크롭·대표 추천 정보를 채운다.
- 기존 `image_asset_mapper`는 Sprint 2 역할을 기존 섹션 매핑 역할로 변환해 이전 자동 매핑 기능과 호환된다.
- `rejected` 자산은 페이지 렌더링 후보에서 제외된다.

### 3. 사용자 보호 장치

- 낮은 해상도·극단적 비율·중복·무결성 경고가 있는 이미지는 자동 HERO 후보가 될 수 없다.
- 사용자가 HERO를 직접 선택하면 확인 대화상자가 나타난다.
- 서버도 `confirm_low_quality_hero` 없이는 해당 저장을 `409 Conflict`로 막아 UI 우회를 방지한다.

## 검증 결과

실행 명령:

```powershell
Set-Location C:\page\backend
.\.venv\Scripts\python.exe -m pytest tests/test_sprint2_asset_classification.py tests/test_image_asset_mapper.py tests/test_sprint1_real_product_images.py tests/test_detail_page_orchestrator_remediation.py -q
```

결과: **34 passed**

확인한 회귀 범위:

- Sprint 2 역할·해상도·형식·품질 경고·중복·손상 파일 검사
- 가장 큰 상품 후보의 대표 이미지 추천, OCR 신호 반영, 대표 이미지 1개 수동 확정
- 경고 자산 자동 HERO 제외
- AgentRun과 기존 자동 매핑 모두에서 저품질 HERO 자동 추천 제외
- 서버의 저품질 HERO 확인 강제 (`409 Conflict`)
- Sprint 1 실상품 사진 우선 및 URL 이미지 수동 승인
- 기존 Mock 이미지 자동 교체 보호

프론트 검증:

```powershell
Set-Location C:\page\frontend
npm.cmd run lint
```

결과: 성공. 기존 `<img>` 사용 및 Hook dependency 관련 경고만 존재하며, 이번 변경으로 추가된 오류는 없다.

## 남은 한계와 다음 Sprint 연결

- 역할 추천은 파일명·출처·URL·OCR 텍스트와 이미지 크기를 사용하는 결정론적 규칙이다. 실제 상품이 선명하게 보이는지, 배경이 복잡한지는 사람 검수 상태로 남긴다.
- 외부 이미지 API나 비전 모델 없이 구현했으므로 피사체 위치·상품 노출 정도는 의미 기반으로 판정하지 않는다.
- Sprint 3에서는 판매자가 확정한 `product_main` 이미지를 중심으로 HERO의 크롭·contain 배치·텍스트 안전 영역을 구성한다.

## 판정

Sprint 2는 기획의 필수 완료 기준을 충족했다. Sprint 3 HERO 조합 구현으로 진행 가능하다.
