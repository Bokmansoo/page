# 코드 리뷰: Sellform Sprint 46 Output Package, Figma, and Marketplace Alignment

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `main` |
| 리뷰 일자 | 2026-07-02 |
| 리뷰 범위 | Sales Package Service 구현, 마켓플레이스 등록 API 및 UI, Figma 플러그인 제약 완화 및 다이얼로그 개정 |
| 관련 기획·작업 | [2026-06-30-sellform-sprint-46-output-package-figma-marketplace-alignment.md](file:///c:/page/docs/superpowers/plans/2026-06-30-sellform-sprint-46-output-package-figma-marketplace-alignment.md) |
| 리뷰어 | Antigravity AI |
| 상태 | 승인 |

## 1. 변경 요약

- 상세페이지의 단순 출력을 단일 이미지뿐만 아니라 종합적인 'Sales Package' 형태로 확장하여 한눈에 출력 및 연계 액션들을 활용할 수 있도록 재정의했습니다.
- **추가한 아웃풋 구성**: `long_png` (긴 모바일 세로 이미지), `editable_web_page` (에디터 내 일반 편집 탭 전환), `figma_payload` (Figma 플러그인용 설계본), `marketplace_package` (마켓 상품 등록 정보 및 SEO 메타), `copy_sheet` (텍스트 모음), `visual_assets` (이미지 자산 리스트).
- **마켓플레이스 연계**: 등록 데이터에 필요한 필수 항목(대표 이미지, 상세 아티팩트, 가격 등)에 대한 정합성 검증 API를 추가하고, 클라이언트 측에서 이를 모두 통과했을 때만 "등록 데이터 준비됨 (Ready)" 상태 배지를 노출하며 전송 트리거를 제공합니다.
- **Figma 연동 재포지셔닝**: 기존 7개 섹션 강제 검사 조건을 최소 1개 이상 존재 시 허용하도록 완화하여, 사용자 편집본의 내보내기가 차단되지 않도록 개선했으며 Figma 다이얼로그 카피를 '고급 편집'에 적합하게 개정했습니다.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료

- **기획 문서**: [2026-06-30-sellform-sprint-46-output-package-figma-marketplace-alignment.md](file:///c:/page/docs/superpowers/plans/2026-06-30-sellform-sprint-46-output-package-figma-marketplace-alignment.md)
- **코드·화면·API**:
  - [sales_package_service.py](file:///c:/page/backend/src/services/sales_package_service.py)
  - [marketplaces.py](file:///c:/page/backend/src/api/marketplaces.py)
  - [exports.py](file:///c:/page/backend/src/api/exports.py)
  - [figma_plugin.py](file:///c:/page/backend/src/api/figma_plugin.py)
  - [SalesPackageExportPanel.tsx](file:///c:/page/frontend/src/components/SalesPackageExportPanel.tsx)
  - [DetailPagePackageEditor.tsx](file:///c:/page/frontend/src/components/DetailPagePackageEditor.tsx)
  - [FigmaExportDialog.tsx](file:///c:/page/frontend/src/components/figma/FigmaExportDialog.tsx)
- **테스트 증적**:
  - [test_sales_package_service.py](file:///c:/page/backend/tests/test_sales_package_service.py)
  - [test_figma_plugin_api.py](file:///c:/page/backend/tests/test_figma_plugin_api.py)

### 핵심 흐름

```text
[상세페이지 생성/편집] → [세일즈 패키지 데이터 조합] → [필수 정보 유효성 검사] → [PNG 다운로드 / Figma 고급 편집 / 마켓 등록]
```

- **정상 흐름**: 상세페이지 초안 생성 시점 이후부터 아웃풋 패널에서 PNG 다운로드, 웹 수정, Figma 고급 편집, 마켓플레이스 등록 준비가 유기적으로 연결됩니다.
- **누락 자료 처리**: 가격, 대표 이미지, 상세 이미지 등이 누락되었을 경우, 마켓플레이스 전송 및 "준비됨" 상태 배지가 차단되며 클라이언트와 백엔드에서 모두 안전하게 400 에러 또는 미완료 안내로 대응합니다.
- **예외 복구**: `ProductProject`에 `image_url` 필드가 없는 버그가 식별되어 `intake_snapshot`을 조회하도록 복구하였고, 7개 섹션이 아닌 경우에 API 테스트가 실패하던 이슈를 테스트 케이스 리팩토링으로 안전하게 해결했습니다.

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 🔴 B1. DB 스키마 속성 불일치로 인한 AttributeError
- **위치**: `backend/src/services/sales_package_service.py:49`
- **내용**: `ProductProject` 인스턴스에 `image_url` 속성이 존재하지 않아, 세일즈 패키지 조회 시 `AttributeError`가 발생해 API 전체가 작동 불능 상태에 도달했습니다.
- **영향**: 세일즈 패키지 조회 및 프론트엔드 출력이 중단되었습니다.
- **제안**: `project.image_url` 대신 `project.intake_snapshot` 딕셔너리 내부의 `image_url` 키값을 먼저 검색하고, 없을 경우 최초의 이미지형 에셋으로 대체하도록 Null-safe 코드로 리팩토링합니다.
> **[조치 상태 - 2026-07-02]** `sales_package_service.py` 내부 로직을 수정하여 `intake.get("image_url")`을 사용하도록 교체하였으며, 이로 인해 에러가 완전히 해소되었습니다.

### 🟠 M1. Figma 플러그인 유효성 테스트 실패
- **위치**: `backend/tests/test_figma_plugin_api.py:103-136`
- **내용**: 7개 섹션 강제 규칙을 제거함에 따라 기존의 실패 검증용 API 테스트가 `AssertionError`를 발생시키며 실패했습니다.
- **영향**: CI 테스트 파이프라인의 전체 실패를 초래했습니다.
- **제안**: `test_issue_ticket_rejects_page_without_canonical_seven_sections` 테스트의 명칭을 `test_issue_ticket_rejects_page_without_sections`로 변경하고, 제약 완화 상태인 `at least 1 section`이 올바르게 검출되는지 assert 검증식을 교체합니다.
> **[조치 상태 - 2026-07-02]** 완화된 제약조건에 맞춰 테스트 코드를 정상 반영했으며, 243개 전체 테스트가 성공적으로 완료되었습니다.

### 🟡 m1. 프론트엔드 Typescript any 타입 및 ESLint Unused 변수 에러
- **위치**: `frontend/src/components/SalesPackageExportPanel.tsx:15,16,156`
- **내용**: `any` 타입 사용 금지 룰(`@typescript-eslint/no-explicit-any`) 위반 및 `catch` 절의 `err` 선언 후 미사용 경고로 빌드가 거부되었습니다.
- **영향**: 프론트엔드 Next.js 프로덕션 빌드가 실패하여 배포가 불가한 상태였습니다.
- **제안**: `any`를 `Record<string, unknown>` 등으로 재정의하고 `err` 변수는 콘솔이나 로깅에 투입해 미사용 경고를 제거했습니다.
> **[조치 상태 - 2026-07-02]** eslint 에러 및 경고를 전부 제거하고 `next build` 컴파일을 성공적으로 패스했습니다.

## 4. 우선순위 권고

1. **🔴 B1 (DB 스키마 불일치)** — 이미 조치 완료되었으며, 백엔드 서버 기동에 필수적인 Blocker였습니다.
2. **🟠 M1 (테스트 실패)** — 조치 완료되어 CI 파이프라인 통과 상태를 유지 중입니다.

## 5. 긍정적인 부분

- **유연성 극대화**: 사용자가 상세페이지를 편집하는 도중에도 7개 섹션 강제를 없앰으로써 Figma와 에디터 간의 양방향 싱크 및 유연성이 비약적으로 증가했습니다.
- **종합 데이터 허브**: PNG 다운로드뿐만 아니라, SEO, 가격, 배송, 텍스트 데이터 전체를 `sales-package` 하나의 데이터셋으로 모아 프론트엔드 컴포넌트의 통신 및 렌더링 효율을 극대화했습니다.

## 6. AI·사실 신뢰성 검토

- **사용한 사실과 근거**: 상세페이지 내에서 검증되어 확정된 `copy_sections` 및 `visual_assets`만을 세일즈 패키지 텍스트와 이미지 리스트로 묶어 활용했으므로 근거의 정합성이 유지됩니다.
- **프롬프트·모델·스키마 변경**: 변동 사항 없습니다.

## 7. 검증 증적

### 자동 테스트
- [test_sales_package_service.py](file:///c:/page/backend/tests/test_sales_package_service.py) 단위 테스트를 추가하고 `pytest`를 활용하여 243개 전체 테스트 무오류 통과를 확인했습니다:
  ```text
  tests/test_sales_package_service.py .
  ======= 243 passed, 1005 warnings in 323.81s (0:05:23) =======
  ```

### 수동 QA 및 빌드 증적
- **Next.js Build 검증**:
  ```text
  Route (app)                               Size     First Load JS
  ├ ƒ /workspace/projects/[id]/page-editor  26 kB           122 kB
  ✓ Generating static pages (9/9)
  All local CI checks passed successfully!
  ```

## 8. 결론

- **결론**: 승인
- **결정 이유**: 기획서 상의 요구사항인 4개 액션 통합, 마켓플레이스 등록 흐름 및 Figma 연동 포지셔닝 변경이 완벽히 준수되었습니다. 식별된 블로커성 버그들도 개발 및 검증 과정에서 완전 자가 해결(Resolved) 및 수리 완료했습니다.
