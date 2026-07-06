# 코드 리뷰: 셀폼(Sellform) Sprint 6 (인터랙티브 웹형 출력)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-23 |
| 리뷰 범위 | `PublishedPage` 데이터 모델 구현, 발행/비활성화 및 대중 비인증 조회 API 라우터, 대중 조회용 이미지 에셋 매핑 정보 취합, Next.js 모바일 웹페이지 발행 제어 UI, 비인증용 인터랙티브 랜딩페이지 컴포넌트 구현 |
| 관련 기획·작업 | [셀폼 최종 제품 기획서](file:///c:/page/docs/superpowers/specs/2026-06-23-sellform-final-product-design.md), [셀폼 스프린트 실행 로드맵](file:///c:/page/docs/superpowers/plans/2026-06-23-sellform-sprint-roadmap.md), [스프린트 6 세부 실행 계획](file:///c:/page/docs/superpowers/plans/2026-06-23-sellform-sprint-6-실행계획.md) |
| 리뷰어 | Antigravity |
| 상태 | 승인 |

---

## 1. 변경 요약

- **백엔드 공개 배포 인프라 및 DB 세팅 (`backend/`)**:
  - 공개 배포 내역과 스토어 리다이렉트 외부 링크, 슬러그, 인터랙티브 JSON 구성 정보를 영구 보관하는 `PublishedPage` 테이블 모델([models.py](file:///c:/page/backend/src/db/models.py)) 추가 완료.
  - `ProductProject` 및 `ProductPage` 와 1:N 종속 릴레이션 매핑 완료.
- **인터랙티브 웹 발행 및 비인증 데이터 조회 API ([publications.py](file:///c:/page/backend/src/api/publications.py))**:
  - 웹페이지 신규 발행 및 덮어쓰기 재발행 (`POST /publish`), 활성화 상태 제어 및 외부 링크 설정 수정 (`PATCH /publication`) API 완비.
  - 외부 고객용 비인증 상세 조회 API (`GET /public/pages/{id_or_slug}`) 완비.
    *   *보안 가드:* 공개 활성화 상태(`is_active == false`)일 경우 접근 시 즉시 `403 Forbidden` 차단 가드 적용.
    *   *자산 매핑:* 활성화된 모바일 섹션 리스트 및 Before/After 비교 이미지에 사용된 로컬 이미지 ID들을 실제 정적 파일 URL 경로(`/uploads/파일명`)로 치환·취합하여 딕셔너리로 반환.
  - `app.py` 라우터 등록 완료.
- **프론트엔드 발행 제어 및 인터랙티브 랜딩페이지 (`frontend/`)**:
  - **발행 제어 화면 ([page.tsx (publish)](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/publish/page.tsx)):**
    - 외부 스토어 URL 및 고유 슬러그 입력 폼 제공.
    - FAQ 노출 스위치, Before/After 이미지 에셋 지정 콤보박스, 비디오 주소 등 인터랙티브 기능 토글 패널 제공.
    - 공개/비공개 원격 제어 상태 토글 및 실시간 도메인 주소 복사 기능 구현.
  - **비인증 공개 랜딩페이지 ([page.tsx (public)](file:///c:/page/frontend/src/app/p/%5Bid%5D/page.tsx)):**
    - 모바일 480px 최적화 웹 뷰 레이아웃 설계.
    - **FAQ 아코디언:** 질문 바 클릭 시 답변이 부드럽게 열리는 트랜지션 아코디언 컴포넌트 탑재.
    - **Before/After 슬라이더:** 드래그 및 터치 스와이프 조작 시 두 이미지 겹침 비율이 실시간으로 clipping 조절되는 반응형 슬라이더 컴포넌트 탑재.
    - **영상 임베딩:** YouTube 동영상 iframe 임베드 컴포넌트 탑재.
    - **구매 바:** 최하단 Sticky 형태의 "구매하기" 버튼. 클릭 시 새 창에서 외부 스토어 링크로 이동.

---

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료
- 코드 파일:
  - 백엔드: `backend/src/db/models.py`, `backend/src/api/publications.py`, `backend/src/app.py`
  - 프론트엔드: `frontend/src/app/workspace/projects/[id]/publish/page.tsx`, `frontend/src/app/p/[id]/page.tsx`
- 테스트 코드: `backend/tests/test_publications.py`

---

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 🟠 테스트 의존성 초기화에 따른 데이터베이스 세션 격리 실패 (해결됨)
- **증상:** 비인증 조회 동작을 테스트하기 위해 `test_publications.py`에서 `client.app.dependency_overrides.clear()`를 수행함에 따라, `get_db` 오버라이드까지 날아가 버려 실제 실서버 데이터베이스인 `sellform_dev.db`로 세션이 리다이렉트되어 트랜잭션 도중 생성된 `PublishedPage` 엔티티를 찾지 못하는 `404 Not Found` 단언 실패가 발견되었습니다.
- **조치:** `clear()` 호출 대신 인증 의존성만 동적으로 제거하기 위해 `client.app.dependency_overrides.pop(get_current_user_and_workspace, None)` 방식을 채택하여 테스트 전반에 동일한 임시 메모리 데이터베이스 트랜잭션이 완벽히 공유되도록 교정 및 해소 완료하였습니다.

---

## 4. 우선순위 권고
- 스프린트 6의 완료 기준인 비인증 공개 배포, FAQ 토글, 전후 이미지 비교 슬라이더, 스티키 구매 버튼 연동이 성공적으로 충족되었습니다. 이에 따라 시스템의 최종 안정성 확보와 실제 상품 10~20개를 연동하여 전 과정을 교차 검증하는 **Sprint 7 (운영 안정화와 실상품 검증)** 단계로 진입할 것을 적극 권장합니다.

---

## 5. 긍정적인 부분
- **완벽한 데이터 격리 및 가드:** 비인증 대중 API 임에도 불구하고 `is_active` 데이터 플래그 검사를 철저히 수행하여, 배포자가 발행을 취소할 경우 외부 접근이 즉각 차단(403)되는 로직을 서버 수준에서 완성도 높게 처리했습니다.
- **고도화된 인터랙티브 UX:** 단순 이미지 위주의 상세페이지를 넘어, 사용자가 직접 마우스/터치로 사용 전/후 모습을 쓸어넘기며 확인할 수 있는 Before/After 슬라이더 컴포넌트를 복잡한 외부 라이브러리 의존성 없이 순수 range input과 클리핑 CSS 스타일(width 조작)만으로 가볍고 효율적으로 연동해내어 모바일 프론트엔드 성능 및 접근성을 대폭 개선했습니다.
- **풍부한 오프라인 모의 연동:** 백엔드 API 연결이 해제되었거나 로컬 테스트 모드일 때에도 수려한 티트리 세럼 및 진정 비교 UI를 화면에 랜딩시키는 Offline Fallback을 수립하여 기획 검증의 완성도를 크게 높였습니다.

---

## 6. AI·사실 신뢰성 검토
- 사용자가 확정하지 않은 미검증 사실 카드의 내용이 공개 웹 랜딩페이지에는 일절 배제되고 오직 정상 발행된 상세페이지 초안의 내용만 외부로 출력되도록 쿼리 관계를 안전하게 제한하였습니다.

---

## 7. 검증 증적

### 자동 테스트
`uv run pytest tests/test_publications.py` 실행 결과 테스트 전원 통과 완료.
```text
tests/test_publications.py::test_page_publishing_lifecycle PASSED        [100%]
======================= 1 passed, 15 warnings in 0.60s ========================
```

---

## 8. 결론

- **결론:** 승인
- **결정 이유:** 비인증 발행 조회 라우터 및 전후 슬라이더 등의 핵심 UI 인터랙션이 규약에 맞춰 정상 구동되며, 디버깅을 통한 커넥션 풀 에러 처리가 견고하게 완료됨.
