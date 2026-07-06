# 코드 리뷰: Sellform Sprint 31 보완 작업

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-27 |
| 리뷰 범위 | 커머스 컷 내보내기 요청 연결, Windows 테스트 이미지 정리 안정화 |
| 결론 | 코드 보완과 백엔드·빌드 검증 완료. Playwright GREEN은 로컬 재실행 필요 |

## 1. 변경 요약

- 실제 내보내기 요청에 `use_commerce_cut: true`를 명시적으로 전달하도록 수정했다.
- Sprint 31 커머스 컷 렌더링 기능이 백엔드에만 존재하고 사용자 내보내기 흐름에서는 비활성화되던 문제를 해결했다.
- Windows에서 고정 테스트 이미지 경로가 충돌하지 않도록 pytest 임시 경로를 사용하게 변경했다.
- 내보내기 요청 payload를 검증하는 Playwright 회귀 테스트를 추가했다.

## 2. 발견 및 조치 이슈

### 🔴 B1. 실제 내보내기에서 커머스 컷 모드가 활성화되지 않음

- 위치: `frontend/src/app/workspace/projects/[id]/export/page.tsx`
- 원인: 요청 body에 `preset_name`만 전달하고 `use_commerce_cut`를 전달하지 않았다.
- 영향: 백엔드의 Sprint 31 렌더링 코드가 구현되어 있어도 일반 사용자 내보내기에서는 기존 렌더링이 사용됐다.
- 조치: `use_commerce_cut: true`를 요청 body에 추가했다.

### 🟡 M1. Windows에서 테스트 이미지 삭제 실패

- 위치: `backend/tests/test_export_commerce_visual_cuts.py`
- 원인: 고정된 테스트 이미지 경로를 반복 사용하고 즉시 삭제하면서 Windows 파일 점유와 충돌했다.
- 영향: 렌더링 검증은 성공했지만 정리 단계에서 테스트가 실패했다.
- 조치: pytest `tmp_path`로 테스트마다 고유한 원본 이미지 경로를 사용하고 수동 삭제를 제거했다.

## 3. 검증 결과

- Sprint 31 백엔드 타깃 테스트: `4 passed`
- 백엔드 전체 회귀 테스트: `130 passed`
- 프론트 프로덕션 빌드: 성공
- Playwright 회귀 테스트:
  - 수정 전 RED 확인 완료: 요청 body에 `use_commerce_cut` 누락
  - 수정 후 브라우저 GREEN 실행은 도구 권한 사용 한도로 실행하지 못함
  - 요청 코드와 테스트 기대값의 정적 일치는 확인함

## 4. 남은 위험

- 로컬 환경에서 다음 명령으로 Playwright 회귀 테스트를 한 번 실행해야 한다.

```cmd
cd frontend
npm.cmd run test:e2e -- sprint31-commerce-cut-export.spec.ts
```
