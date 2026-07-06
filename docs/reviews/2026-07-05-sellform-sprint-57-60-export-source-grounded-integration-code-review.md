# Sprint 57/60 Export 및 Source-Grounded 통합 코드리뷰

## 리뷰 범위

- Sprint 57 canonical Next.js 렌더 캡처 기반 PNG/JPEG export
- Sprint 60 구조화 확인값의 생성 payload 반영
- 상품 URL 및 참고 상세페이지 URL의 이미지·스펙·OCR 수집
- 장면 계획의 이미지 생성 job 및 페이지 섹션 조립 연결
- Sprint 60 Chromium E2E 재검증

## 구현 결과

### 1. Canonical export

- export worker가 Pillow 재조립 대신 `/workspace/projects/{id}/render`를 Playwright로 연다.
- 요청한 `final_version_id`를 render URL에 고정하고 `data-export-ready=true` 이후 캡처한다.
- 전체 상세페이지와 섹션별 이미지를 같은 DOM에서 생성한다.
- PNG/JPEG MIME, 확장자, JPEG quality를 분리 처리한다.
- 캡처 실패 시 부분 이미지와 ZIP을 제거하고 성공 artifact를 만들지 않는다.
- export 대기 중 새 최종본이 생겨도 큐에 고정된 버전 ID를 계속 사용한다.

### 2. 구조화 확인값

- 상품명, 판매 포인트, 가격, 배송, 분위기를 controlled input으로 편집한다.
- 판매 포인트 체크 해제 결과도 반영한다.
- 확인 버튼이 반환한 최신 draft를 생성 요청 본문에 직접 전달한다.
- 값은 `AgentRun.input_snapshot`과 `ProductInput`에 보존된다.

### 3. URL 근거 수집

- HTML title, Open Graph 이미지, JSON-LD Product, 표 스펙, 본문 텍스트를 수집한다.
- 상대 이미지 URL을 절대 URL로 정규화하고 중복을 제거한다.
- 상품 URL과 참고 URL의 출처 역할을 구분해 snapshot에 저장한다.
- HTTP(S) 외 스킴, localhost, 사설·예약 IP를 차단하고 리다이렉트를 따르지 않는다.
- 참고 URL은 최대 3개로 제한한다.
- `SELLFORM_URL_OCR_ENABLED=true`일 때 기존 멀티모달 추출기로 URL 이미지 최대 3장을 OCR한다.

### 4. 장면 계획 연결

- `scene_plan`이 visual planning output에 포함된다.
- hero와 lifestyle 장면만 이미지 생성 job으로 보내 비용을 줄인다.
- pain point, benefit, spec은 `html_graphic`으로 조립한다.
- `scene_section_id`, `visual_strategy`, `identity_risk`, `text_free_required`를 최종 섹션까지 보존한다.
- HTML 그래픽은 이미지 생성 없이 추적 가능한 후보 메타데이터를 제공한다.

## 리뷰 중 발견 및 수정

1. **중요, 수정 완료:** export 큐 처리 중 최신 최종본이 바뀌면 기존 버전 캡처가 실패하는 경쟁 조건.
2. **중요, 수정 완료:** 최종본 검증 코드가 compliance endpoint에 잘못 삽입된 문제.
3. **중요, 수정 완료:** HTML 그래픽 도입 후 기존 결과 화면의 이미지 후보 계약이 비는 문제.
4. **보통, 수정 완료:** Playwright context 종료 API를 잘못 호출해 원래 캡처 오류를 덮는 문제.
5. **보통, 수정 완료:** 구조화 확인 화면의 입력값이 uncontrolled 상태라 수정값이 payload에 반영되지 않는 문제.

## 남은 위험

- URL 이미지 자체를 로컬 Asset으로 내려받아 상품 동일성 검증에 사용하는 단계는 아직 없다. 현재는 URL과 OCR/텍스트 근거를 수집한다.
- 운영 export에는 Next.js 서버가 `SELLFORM_EXPORT_RENDER_BASE_URL`에서 접근 가능해야 한다.
- 기존 코드의 Pydantic V2 및 `datetime.utcnow()` deprecation warning은 별도 정리 대상이다.

## 검증

- 백엔드 전체 테스트: `356 passed`
- 프론트 production build: 성공
- Sprint 60 Chromium E2E: `2 passed`
- 기존 lint warning은 남아 있으나 신규 blocking error는 없다.

## 판정

요청 범위는 통합 가능한 상태다. 다음 우선순위는 URL 이미지를 안전하게 Asset으로 가져오고 동일성 검증에 연결하는 작업이다.
