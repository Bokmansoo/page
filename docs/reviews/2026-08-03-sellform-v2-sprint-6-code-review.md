# Sellform V2 Sprint 6 코드리뷰 — 커머스 렌더러·블록 편집기

검토일: 2026-08-03  
대상 기획: `docs/superpowers/plans/2026-08-01-sellform-v2-sprint-6-commerce-renderer-editor.md`

## 결론

Sprint 6의 핵심 서버·편집기 범위는 보완 구현 완료다. 페이지는 `commerce-renderer-v1`이라는 불변 렌더링 계약으로 정규화되고, 최종 버전을 만들 때 해당 계약도 함께 고정된다. 내보내기 전용 화면은 이 고정 계약을 우선 사용하므로, 최종화 후 DB의 초안이 바뀌어도 이미 확정한 출력의 섹션 순서·문구·스타일 입력이 바뀌지 않는다.

이미지 생성 API가 없는 환경에서는 AI 리디자인 결과가 생기지 않는 것이 정상이며, 이는 Sprint 5의 외부 제공자 설정 조건이다. Sprint 6은 그 상태를 빈/공급처 원본 이미지로 대체하지 않고 안전하게 차단한다.

## 기획 대비 확인

| 기획 항목 | 구현 | 결과 |
| --- | --- | --- |
| `commerce_story` 기본 렌더 계약 | `commerce_renderer_service.py`의 `commerce-renderer-v1` | 완료 |
| 스타일 전용 후보 | 세 템플릿 키마다 간격·타이틀 강도·표면 토큰을 별도로 반환 | 완료 |
| 블록 순서 변경·숨김·복원 | 편집기 위/아래/숨기기·복원 버튼, 최종 사양 마지막 위치 검증 | 완료 |
| 직접 문구 수정 및 AI 문구 수정 | 직접 수정은 `seller`, AI 적용은 `ai` 출처를 섹션 스냅샷에 기록 | 완료 |
| 이미지 교체·크롭 위치 | 편집기의 자산 선택과 상단/가운데/하단 크롭이 스냅샷에 저장되고 미리보기에 반영 | 완료 |
| 색상·폰트·간격·정렬 | 페이지 색상/글꼴, 섹션 간격/정렬을 편집기에서 저장 | 완료 |
| 최종 사양 마지막 위치 | 저장·복원·렌더 계약 모두에서 검증 | 완료 |
| 숫자/기능 문구의 사실 연결 | 연결 없는 수치, 오래된 사실 문구를 렌더 차단 사유로 반환 | 완료 |
| 공급처 원본의 최종 출력 금지 | `sourced`/URL 추출/`reference_only` 자산을 렌더 차단 | 완료 |
| 반복 이미지·빈 이미지 감지 | 같은 자산 반복, 이미지 블록의 자산 누락을 차단 사유로 반환 | 완료 |
| 편집 충돌 처리 | 저장 요청에 최신 버전 ID를 보내고, 뒤늦은 저장은 HTTP 409으로 거절 | 완료 |
| 버전 복원 | 시각 종류·페이로드·사실 최신성까지 복원하고 복원 자체도 새 버전으로 저장 | 완료 |
| 변경 전후 비교 | 저장된 버전의 섹션 수·색상·글꼴을 비교하고 편집기에서 복원 가능 | 완료 |
| 미리보기/최종 출력 동일 스냅샷 | 최종 버전에 `commerce_renderer` 스냅샷을 저장하고 export render가 우선 사용 | 완료 |
| 출력에서 앱 UI 제외·이미지/폰트 대기 | 기존 export-render 전용 경로와 `waitForExportAssets` 계약을 계속 사용 | 완료 |

## 변경 파일

- `backend/src/services/commerce_renderer_service.py`
- `backend/src/api/pages.py`
- `backend/src/services/page_finalization_service.py`
- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- `frontend/src/app/workspace/projects/[id]/render/DetailPageRenderClient.tsx`
- `backend/tests/test_v2_sprint6_commerce_renderer.py`

## 검증 결과

```powershell
Set-Location C:\page\backend
& .\.venv\Scripts\python.exe -m pytest tests\test_v2_sprint6_commerce_renderer.py tests\test_v2_sprint5_ai_redesign.py -q
```

결과: `24 passed`

```powershell
Set-Location C:\page\frontend
npx.cmd eslint "src/app/workspace/projects/[id]/page-editor/page.tsx" "src/app/workspace/projects/[id]/render/DetailPageRenderClient.tsx"
```

결과: 오류 없음. 기존 `loadData` 의존성 관련 React Hook 경고 1개만 남아 있다.

`npx.cmd tsc --noEmit`도 실행했다. Sprint 6 파일과 무관한 기존 E2E 시나리오
`e2e/upload-ready-golden-path.spec.ts`의 `image_asset_id` 타입 및 `downlevelIteration`
설정 오류 2건 때문에 전체 TypeScript 검사는 실패한다. 이번 변경 파일의 ESLint 검사는 통과했다.

## 수동 확인 방법

1. 상세페이지 편집기에서 섹션을 위/아래로 이동하거나 숨김/복원한다.
2. 최종 사양·고지 섹션을 마지막보다 앞에 두려고 하면 저장이 거절되는지 확인한다.
3. 두 탭에서 같은 페이지를 연 뒤, 한 탭에서 저장하고 다른 탭에서 저장한다. 두 번째 저장은 최신 버전을 다시 불러오라는 충돌 안내가 나와야 한다.
4. 최종화한 뒤 PNG/JPG 내보내기를 실행한다. 내보내기에는 버튼·경고·편집 UI가 포함되지 않아야 한다.
5. 공급처 캡처나 반복 자산을 최종 이미지로 연결하면 렌더 준비 상태가 차단되어야 한다.

## 범위 밖 항목

- 자유 배치 캔버스
- 결제/과금
- 마켓 자동 등록
- 공급처 원본 캡처를 그대로 최종 결과로 쓰는 기능

실제 AI 이미지 생성은 별도 이미지 제공자 API 키가 설정된 경우에만 실행된다. API 키가 없는 현재 환경에서 후보 이미지가 비어 있는 것은 정상이며, 승인 대기 상태로 남는다.
