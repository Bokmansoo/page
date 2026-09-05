# Sellform V2 Sprint 2 코드리뷰 — 자산 이해·OCR·번역

검토 기준 문서: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-2-asset-understanding.md`

## 결론

Sprint 2의 코드 완료 기준과 로컬 OCR 실행 기준을 충족한다. 분석 결과는 원본 자산과 분리된 불변 버전으로 저장되고, 공급처 원본은 참고 전용으로 유지된다. 역할·권리·OCR·번역·정체성이 불완전하면 Sprint 3 진입과 최종 출력을 차단한다.

Windows용 Tesseract 5.4.0과 `chi_sim`, `kor`, `eng` 언어팩을 설치했다. 관리자 권한 없이 재현할 수 있도록 추가 언어팩은 Git에서 제외되는 `backend/.runtime/tesseract/tessdata`에 보관하며, 서비스가 Windows 실행 파일과 프로젝트 언어팩을 자동 탐색한다.

## 기획 대조

| 기획 항목 | 구현 및 검증 결과 | 판정 |
| --- | --- | --- |
| 분석 결과 저장·버전 관리 | 원본 파일과 분리된 `asset_inspections` 불변 버전 및 재시도 이력 저장 | 완료 |
| 공급처 원본 최종 출력 제외 | `reference_only`는 분석 참고용이며 최종 출력 후보에서 제외 | 완료 |
| 판매자 역할 수정 보존 | 수동 역할·대표 상품·번역 확인을 새 버전과 감사 이력으로 보존 | 완료 |
| 기본 수치 보존과 오류 격리 | OCR 숫자·단위를 근거로 저장하고 자산 하나의 실패를 프로젝트 전체 실패로 전파하지 않음 | 완료 |
| 실이미지 역할 분석 | 실제 YL-T02 6장 분석: 기능, 스펙, 기능, 사용 장면, 소재, 온열 기능으로 분류 | 완료 |
| OCR 원문·좌표 | 실제 이미지의 중국어 원문을 `word_line` 픽셀 bbox와 신뢰도로 저장 | 완료 |
| 일반 번역 | 공백이 삽입된 중국어도 로컬 용어집으로 번역하고 미번역 문구는 `needs_review`로 명시 | 완료 |
| 자산 보드 | 역할·권리·품질·OCR·번역·좌표·중복·최종 사용 가능 여부·재시도 표시 | 완료 |
| Sprint 3 차단 | 잠긴 입력 번들의 자산 분석이 불완전하면 mock/real 실행 모두 HTTP 409 차단 | 완료 |

## 실제 YL-T02 OCR 증거

프로젝트: `75b89fa7-11ad-4128-a019-fad23b5f79f6`

| 파일 | OCR 블록 | 분류 | 대표 추출 원문 |
| --- | ---: | --- | --- |
| `1.jpg` | 3 | feature | `智能 3 键 设计` |
| `2.jpg` | 17 | spec_reference | `功能 描述`, 전압·출력·배터리·시간 표 |
| `3.jpg` | 4 | feature | `可 灵活 调节 头 枕` |
| `4.jpg` | 3 | usage_scene | `随时 随地 享受 按摩` |
| `5.jpg` | 3 | material_detail | `阳离子 空气 层面 料` |
| `6.jpg` | 3 | feature | `42°C 恒 温 加 热` |

모든 최신 분석은 `status=completed`이며 첫 좌표의 정밀도는 `word_line`이다. 로컬 OCR 재시도 결과를 원본 OCR 필드에 덮어써 좌표가 `asset_scope`로 퇴화하던 문제도 수정하고 회귀 테스트를 추가했다.

Tesseract는 글자가 작거나 효과가 많이 들어간 이미지에서 일부 문자를 잘못 읽을 수 있다. 예를 들어 모델명 `YL-T02`가 `YL-TOP`로 읽힐 수 있으므로, 확정 스펙은 판매자가 확인한 구조화 데이터가 우선하며 불확실한 OCR 번역은 계속 검수 대상으로 남긴다.

## 주요 API

- `POST /api/v1/projects/{project_id}/asset-inspections`
- `GET /api/v1/projects/{project_id}/asset-inspections`
- `GET /api/v1/projects/{project_id}/asset-inspections?include_history=true`
- `POST /api/v1/projects/{project_id}/assets/{asset_id}/asset-inspections/retry`
- `PATCH /api/v1/projects/{project_id}/assets/{asset_id}/asset-inspections/{inspection_id}/review`
- `GET /api/v1/projects/{project_id}/asset-understanding-readiness`

## 운영 설정

- OCR 엔진: Tesseract 5.4.0
- Python 래퍼: `pytesseract>=0.3.13`
- 기본 언어: `chi_sim+kor+eng`
- 로컬 언어팩: `backend/.runtime/tesseract/tessdata` (Git 제외)
- 선택적 AI 일반 번역: `SELLFORM_OCR_AI_TRANSLATION_ENABLED=true`
- 선택적 AI 픽셀 비전: `SELLFORM_ASSET_AI_VISION_ENABLED=true`

API 키가 없을 때도 Tesseract OCR·좌표·로컬 용어 번역·역할 분류는 동작한다. 일반 문장 전체의 AI 번역과 픽셀 비전만 `needs_review`로 안전하게 남는다.

## 회귀 검증

```powershell
Set-Location C:\page\backend
.\.venv\Scripts\python.exe -B -m pytest `
  tests\test_v2_sprint2_asset_understanding.py `
  tests\test_sprint2_asset_classification.py `
  tests\test_image_asset_mapper.py `
  tests\test_v2_sprint1_product_input_bundle.py `
  tests\test_v2_sprint0_baseline_policy.py -q
```

결과: `60 passed`

## 최종 판정

- Sprint 2 코드 구현: 완료
- 네이티브 중국어 OCR 설치: 완료
- 실제 YL-T02 이미지 OCR·좌표 검증: 완료
- 재시도 좌표 보존 회귀 검증: 완료
- API 키 없이 가능한 Sprint 2 범위: 완료
- 외부 AI 번역·비전 통합: API 키 확보 후 선택 검증
