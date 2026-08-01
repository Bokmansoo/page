# Sellform API-free Visual Sprint 0 기준선 검증 팩

작성일: 2026-07-31  
상태: 자동 테스트 및 로컬 통합 검증 완료

## 목적

Sprint 1~7의 결과를 같은 입력으로 비교하기 위한 고정 검증 기준을 정의한다. 자동 테스트는
저장 형식과 실패 처리를 검증하고, 실상품 검증은 실제 서버에서 동일 체크리스트를 사용한다.

## 기준 상품

| 분류 | 기준 입력 | 중점 확인 |
| --- | --- | --- |
| 소형 가전 | 마사지건 또는 무선청소기, 대표 사진과 확인된 스펙 | 제품 형태, 수치, HERO |
| 뷰티 | 용기와 패키지가 분명한 단일 제품 | 라벨, 색상, 성분 표현 |
| 생활용품 | 구성품이 2개 이상인 제품 | 구성품, 사용 단계, 반복 이미지 |

실제 URL과 사진은 저작권 및 사용 권한을 확인한 뒤 프로젝트별 테스트 기록에 첨부한다.

## 현재 기준선 문제

- Mock 이미지 생성기가 빨간색 사각형을 만들며 `ai_generated` 표식을 노출한다.
- 이미지가 없는 섹션은 후보 없음 또는 생성 상태 확인 메시지를 표시한다.
- Playwright Chromium이 없으면 브라우저 실행 파일의 로컬 경로가 포함된 원본 예외가 노출된다.
- 미리보기와 export의 시각 일치는 Sprint 6까지 계속 검증해야 한다.

## Sprint 0 자동 검증

- `backend/tests/test_export_service.py`
  - Chromium 실행 파일 사전 진단
  - launch 단계 누락 오류 정규화
  - PNG/JPG 파일 생성
- `backend/tests/test_exports.py`
  - PNG/JPG 다운로드 MIME과 파일명
  - 실패 export의 `failed` 상태와 출력 자산 미생성
- `frontend/e2e/completed-detail-page-export.spec.ts`
  - 브라우저 PNG/JPG 다운로드
  - Chromium 누락 해결 명령 표시

## 실상품 실행 체크리스트

- [ ] 입력 자료와 생성 모드를 기록한다.
- [ ] 결과 화면 전체를 캡처한다.
- [ ] 빨간 Mock 이미지와 내부 배지 수를 기록한다.
- [ ] 누락 이미지와 후보 없음 섹션을 기록한다.
- [ ] PNG와 JPG를 각각 다운로드한다.
- [ ] 미리보기와 파일의 제목, 상품 이미지, 섹션 순서를 비교한다.
- [ ] 실패 시 오류 문구와 export 작업 상태를 기록한다.

## 로컬 통합 검증 증거

2026-07-31에 실제 로컬 서버(`127.0.0.1:8001` FastAPI, `localhost:3000` Next.js,
PostgreSQL)로 생성·최종본 고정·Playwright export·다운로드를 수행했다. 상세한 프로젝트,
작업 ID, 파일 형식과 크기는 [통합 검증 증거](2026-07-31-sellform-api-free-visual-sprint-0-integration-evidence.md)를
참조한다.

## Sprint 0 완료 판정

자동 테스트가 모두 통과했고 기준 상품 3종에서 PNG/JPG 다운로드에 성공했다. 따라서 Sprint
0을 완료로 판정한다. 빨간 Mock 이미지는 Sprint 1의 해결 범위이므로 Sprint 0 blocker로
보지 않는다.
