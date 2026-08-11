# Sellform V2.1 LG-7R 브라우저 검증 가이드

## 1. 사전 조건

백엔드와 프런트엔드를 재시작한 뒤 다음 주소가 열리는지 확인한다.

- 백엔드 상태: `http://localhost:8001/`
- API 문서: `http://localhost:8001/docs`
- Sellform: `http://localhost:3000/workspace`

유료 API를 호출하지 않으려면 다음 설정을 유지한다.

```env
SELLFORM_GRAPH_RUNTIME=langgraph
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
```

## 2. 기본 LG-7R 흐름

1. `http://localhost:3000/workspace`에서 새 상품을 만든다.
2. 상품을 식별할 수 있는 대표 사진 1장과 상품명을 입력한다.
3. 생성 후 Planning 화면에서 `LangGraph 승인 대기 · input_review`를 확인한다.
4. `리뷰·레퍼런스·창작 방향` 카드에서 아래 리뷰를 붙여 넣는다.

```text
가볍고 충전이 간편해 출퇴근에 편리하지만 강풍 단계의 소음은 확인이 필요합니다.
```

5. `분석 활용 동의`를 체크하고 `분석 저장`을 누른다.
6. `리뷰 1개`와 `리뷰는 사실 승격 차단` 안내를 확인한다.
7. 필요하면 레퍼런스 URL 또는 창작 방향을 저장한다. 이 입력은 선택 사항이다.
8. `생성 추적 정보`를 펼쳐 다음 항목이 보이는지 확인한다.

- 현재 생성/진행 모드
- Prompt Pack ID/version/hash
- Brand Kit ID/version/hash 또는 미적용
- Creative Brief ID/version/hash 또는 미생성
- 리뷰·레퍼런스 사용 여부
- 승인 사실과 사실 후보
- 창작 방향
- 섹션별 target/objective/fact IDs/copy classification
- 자동 승인 이력
- stale artifact와 영향 범위

9. 상단 `확인·다음 단계`를 누른다.
10. 상태가 `evidence_review`로 바뀐 뒤 브라우저를 새로고침한다.
11. 새로고침 후에도 `evidence_review`, 저장한 리뷰, 추적 정보가 유지되면 통과다.

## 3. 기존 수집 자료 선택 검증

프로젝트에 TXT/CSV/XLSX 수집 자료가 있으면 `기존 수집 리뷰 자료` 목록에 표시된다.

1. 목록에서 텍스트가 있는 자료를 선택한다.
2. `자료 연결`을 누른다.
3. `기존 수집 자료를 리뷰 분석에 연결했습니다.` 안내를 확인한다.
4. 같은 내용의 파일이나 붙여넣기를 다시 저장한다.
5. 리뷰 개수가 증가하지 않으면 content hash 중복 방지가 정상이다.

목록에 자료가 없다면 API 문서의 `POST /api/v1/files/upload`에서 현재 `project_id`, `source_type=sourced`, TXT 파일을 올린 뒤 Planning 화면을 새로고침한다. 일반 상품 사진 업로드에는 문서 파일이 허용되지 않는다.

## 4. 한국어 오류 표시 검증

1. 메모장에 `not-an-openxml-package`를 입력한다.
2. 파일명을 `broken-reviews.xlsx`로 저장한다.
3. Planning의 `CSV/XLSX/TXT`에서 이 파일을 선택한다.
4. 다음 형태의 안내가 보여야 한다.

```text
[REVIEW_XLSX_CORRUPT] XLSX 파일이 손상되어 읽을 수 없습니다. 해결 방법: 파일을 다시 내려받거나 XLSX로 다시 저장해 주세요.
```

`[object Object]`가 보이면 실패다.

## 5. fake LLM 및 graph 자동 검증

fake real-LLM의 정상 schema, schema 오류, 1회 repair, repair 한도 종료와 실제 `Command(resume=...)`는 자동 테스트로 검증한다.

```powershell
cd C:\page\backend
.\.venv\Scripts\python.exe -m pytest -q tests\test_lg7_creative_brief_input_modes.py
```

브라우저에서 직접 확인할 핵심 결과는 `input_review → evidence_review` 전이와 새로고침 복구다. 자동 테스트는 이어서 `planning_review → generation_pending`까지 같은 thread/checkpoint로 진행한다.

## 6. 통과 기준

- 리뷰 붙여넣기·파일·기존 수집 자료가 서로 분리되면서 같은 내용은 중복 저장되지 않는다.
- 리뷰 문장이 상품 확정 사실로 승격되지 않는다.
- 적용 pack/kit/brief와 사실·섹션 provenance를 Planning에서 확인할 수 있다.
- 손상 파일 오류가 한국어 코드·원인·해결 방법으로 표시된다.
- 승인 후 같은 LangGraph 실행이 다음 interrupt로 이동한다.
- 새로고침 후 상태와 입력이 복구된다.
