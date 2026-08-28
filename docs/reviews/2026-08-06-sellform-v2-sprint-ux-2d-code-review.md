# Sellform V2 Sprint UX-2D 코드리뷰

검토일: 2026-08-06  
상태: 보완 구현 완료 · 백엔드 회귀 및 프론트 린트 통과

## 결론

UX-2D의 목표인 **API 없는 판매용 콘텐츠 품질 검수**를 구현했다. 초기 구현에서 빠졌던 반복 본문 판정, 동일 해시 사진, OCR 상업 노출 위험, 확인 시각, 최종본 품질 스냅샷과 내보내기 연결까지 보완했다. 기술적 렌더링 상태와 판매용 콘텐츠 상태는 화면에서 함께 보되 서로 다른 기준으로 관리한다.

## 구현 확인

- 상품명 정규화가 긴 스펙 문자열, 여러 `항목: 값` 나열, 비정상적으로 긴 입력을 감지한다.
- 정규화된 이름만 프로젝트 생성과 채널 출력 slug에 사용하며, 빈값 또는 붙여넣기 스펙은 `상세페이지` 안전 이름으로 대체한다. 출력 slug는 60자로 제한한다.
- `GET /api/v1/projects/{project_id}/page/content-quality`가 상품명, 제목·본문 반복, 임시 문구, 동일 asset/파일 해시, 섹션-사진 역할 불일치, OCR 위험을 반환한다.
- OCR은 Asset 원문과 최신 AssetInspection 블록에서 외국어, 공급처/마켓 문구, 전화번호, 가격, QR 표기를 검사한다. 원본 문자를 제거·번역했다고 표시하지 않는다.
- 자동 사진 배치는 같은 `asset_id`뿐 아니라 같은 `content_hash` 복사본도 한 번만 제안한다. 수동 중복 선택 시 사전 경고하고, 품질 패널에서 다른 사진·정보형 전환·안전 여백 표시·사용 확인을 제공한다.
- 확인 가능한 사진 위험만 판매자가 확인할 수 있고, 반복 카피·임시 문구는 실제 수정 전에는 확인으로 우회할 수 없다.
- 확인자·확인 시각·asset·코드는 서버 소유 `visual_payload`에 보존되며, 모든 페이지 스냅샷과 최종본 스냅샷에 콘텐츠 품질 요약을 함께 저장한다.
- 최종본 생성은 남은 판매용 품질 확인 항목이 있으면 막고, export 요청은 요청한 최종 버전에 저장된 품질 요약을 확인한다. 이미지 로드 실패·권한·마지막 사양 섹션은 기존 readiness가 계속 별도로 차단한다.

## 주요 변경 파일

- `backend/src/services/commerce_content_quality_service.py`: 이름/slug 정규화, 반복 카피·해시 중복·OCR 상업 노출 검사
- `backend/src/api/agent_runs.py`: 새 프로젝트 생성 시 상품명 정상화 및 입력 경고 보존
- `backend/src/api/exports.py`: 채널 출력 파일명 slug 길이·문자 정리
- `backend/src/api/pages.py`: 콘텐츠 품질 조회·확인 API, 확인 시각, 품질 스냅샷, 최종본 게이트
- `backend/src/services/page_finalization_service.py`, `backend/src/api/exports.py`: 최종본 및 export의 고정 품질 상태 사용
- `frontend/src/components/GeneratedDetailPageResult.tsx`: 품질 패널·섹션 이동·사진 교체·정보형 전환·안전 여백·사용 확인 UI
- `frontend/src/components/AIDetailPageIntake.tsx`: 생성 전 붙여넣기 스펙형 상품명 경고
- `frontend/src/components/DetailPageDocument.tsx`: 품질 항목에서 이동할 수 있는 섹션 anchor
- `backend/tests/test_ux2d_content_quality.py`: 이름, 반복 제목, 중복 사진, 중국어 OCR, 판매자 확인 및 버전 생성 테스트

## 검증 결과

```text
.venv/Scripts/python.exe -m pytest \
  tests/test_ux2d_content_quality.py \
  tests/test_ux2b_rule_based_copy.py \
  tests/test_image_asset_mapper.py \
  tests/test_page_finalization_service.py \
  tests/test_page_readiness_service.py -q

33 passed
```

```text
cd frontend
npm.cmd run lint
```

린트는 성공했다. 기존 Hook 의존성 및 `<img>` 최적화 경고는 남아 있으나 UX-2D의 오류는 없다.

## 완료 조건 재검토

- 긴 스펙 문자열이 출력 파일명으로 그대로 쓰이지 않음: 통과
- 임시·반복 제목 및 본문 감지: 통과
- 같은 사진·동일 해시 복사본의 자동 중복 방지와 수동 중복 확인: 통과
- OCR 외국어·공급처·전화번호·가격·QR 노출 감지 및 판매자 확인: 통과
- 사진 역할 불일치 권고: 통과
- 기술 readiness와 판매용 품질 상태 분리: 통과
- 확인 상태(확인자·시각·asset)가 상세페이지 및 최종본 버전에 보존됨: 통과
- 이미지·LLM 생성 API 비용 없이 동작: 통과

## 범위 밖

- 중국어가 들어간 원본 사진의 문자 제거 또는 자연스러운 한국어 합성
- 새 사용 장면·충전 장면 이미지 생성
- LLM 기반 자유 판매 대본 생성
- 자유 배치 캔버스

위 기능은 UX-2E에서 생성형 API를 연결할 때에도 UX-2D의 사실, 권한, 중복, 외국어 노출, 버전 고정 규칙을 통과해야 한다.
