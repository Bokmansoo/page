# Sellform V2 Sprint UX-2C 코드리뷰

검토일: 2026-08-06  
상태: 구현 완료 · 단위/통합/Playwright 검증 통과

## 결론

UX-2C의 범위인 **업로드 사진 기반 상세페이지 조립**을 구현했다. 이미지·LLM 생성 API 없이도, 판매자가 보유하거나 최종 사용 권한을 확인한 사진을 섹션별로 배치하고 결과 화면에서 바꿀 수 있다. 공급처 참고 사진은 후보로 보이되, 권한 확인 전에는 최종 페이지와 다운로드에 사용할 수 없다.

## 구현 확인

- 프로젝트의 모든 이미지 자산을 각 섹션 후보로 제공한다. 이미지 생성 작업이 없더라도 직접 업로드 사진을 선택할 수 있다.
- `seller_owned` 상태이며 최종 출력 정책에 맞는 사진만 자동 배치·선택할 수 있다. `reference_only`/`blocked` 사진은 사유와 함께 비활성 후보로 표시한다.
- 결과 화면에서 사진 선택/교체, 권한 확인, 사진 제거 후 텍스트 레이아웃 전환, 섹션 숨김·표시, 순서 변경, `contain`/`cover` 표시 방식을 저장한다.
- 상품 사양·필수 고지 섹션은 마지막 위치를 유지하므로 숨김·순서 이동은 허용하지 않는다. 필요하면 사진 선택만 할 수 있다.
- 변경은 기존 페이지 PATCH 및 페이지 버전에 저장된다. 확정된 페이지 섹션을 사용하는 미리보기·렌더·PNG/JPG/분할 ZIP 출력에도 동일한 사진 연결이 전달된다.
- 자동 배치는 같은 보유 사진을 여러 섹션에 반복하지 않으며, 사진이 부족한 섹션은 HTML 정보 레이아웃으로 남는다.
- 사진 역할 매퍼를 UX-2C 섹션에 연결해 대표·기능·사용·구성품 사진을 역할에 맞게 서로 다른 섹션에 배치한다. 역할을 판별할 수 없는 사진은 업로드 순서로 빈 섹션에만 제안한다.
- 재생성 시 기존 섹션을 무조건 초기화하지 않고, 판매자가 고른 사진·텍스트 전환·숨김·순서·맞춤/채움 상태를 병합해 보존한다.
- 사용 불가 사진 선택 API는 기획 계약대로 `422`를 반환한다.
- 섹션별 후보 화면에서 사진의 출처·권한·역할·추천 근거와 해당 섹션에 연결된 확인 사실을 함께 표시한다.
- 영문 상품명 `massage`가 독립된 `AS` 금칙어로 잘못 인식되던 규칙도 수정했다.

## 주요 변경 파일

- `backend/src/api/pages.py`: 업로드 사진 후보와 권한 상태 제공, 사진 제거 저장 허용
- `backend/src/agents/mock_outputs.py`, `backend/src/agents/nodes/page_assembly/agent.py`, `backend/src/services/agent_run_service.py`: 권한 허용 사진만 자동 배치, 중복 배치 방지
- `frontend/src/components/GeneratedDetailPageResult.tsx`: 섹션별 사진 후보·권한 확인·레이아웃 편집 UI
- `frontend/src/components/detail-page/ImageSectionVisual.tsx`: 사진 맞춤/채움 렌더링
- `backend/tests/test_ux2c_uploaded_photo_composition.py`: 자동 배치, 권한 차단/확인, 텍스트 전환, 버전 복원 검증
- `frontend/e2e/ux2c-uploaded-photo-composition.spec.ts`: 자동 배치·사진 교체·권한 확인·숨김 저장·PNG/분할 ZIP 다운로드 브라우저 회귀 시나리오

## 검증 결과

다음 백엔드 관련 테스트를 실행했다.

```text
.venv/Scripts/python.exe -m pytest \
  tests/test_agent_run_api.py \
  tests/test_page_readiness_service.py \
  tests/test_ux2b_rule_based_copy.py \
  tests/test_ux2c_uploaded_photo_composition.py \
  tests/test_ux2_mock_output.py \
  tests/test_mock_agent_generation.py \
  tests/test_wysiwyg_export_contract.py \
  tests/test_page_image_mapping_api.py \
  tests/test_image_asset_mapper.py -q -p no:cacheprovider

56 passed
```

프런트엔드 `npm.cmd run lint`도 성공했다. 기존 `img` 최적화 및 Hook 의존성 경고는 남아 있지만 오류는 없고, 이번 기능의 타입/린트 오류는 없다.

Playwright 시나리오는 고정된 버튼 순서 대신 안정적인 테스트 식별자를 사용한다. 자동 배치 사진 확인, 다른 보유 사진으로 교체, 참고 사진 권한 확인, 섹션 숨김 저장, 확정 버전 ID를 사용한 PNG와 분할 ZIP 다운로드를 한 흐름으로 검증했고 통과했다.

```text
cd frontend
npx playwright test e2e/ux2c-uploaded-photo-composition.spec.ts
```

```text
1 passed
```

## 완료 조건 재검토

- 보유 사진 1장 이상 자동 배치: 통과
- 역할이 지정된 사진 4장을 대표·기능·사용·구성품에 중복 없이 배치: 통과
- 권한 미확인/차단 사진의 선택·출력 차단: 통과
- 사진 교체·텍스트 전환·숨김·순서·맞춤 상태 저장 및 버전 복원: 통과
- 재생성 후 판매자 편집 상태 보존: 통과
- 확정 버전을 사용한 PNG와 분할 ZIP 다운로드: 통과
- 사진이 부족할 때 개발용 자리표시자 대신 HTML 정보 섹션 사용: 통과

## 범위 밖

사람이 사용하는 장면, 충전 장면 등을 새로 만드는 이미지 생성 API와 상품별 판매 대본을 작성하는 LLM API는 UX-2D 범위다. UX-2C는 그 API가 아직 없어도 보유 사진과 안전한 정보 레이아웃으로 다운로드 가능한 상세페이지를 만드는 단계다.
