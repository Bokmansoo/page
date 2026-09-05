# Sellform V2.1 LG-7R 세부 구현 계획

## 1. 목표와 완료 기준

LG-7의 리뷰·레퍼런스·판매자 창작 방향 입력을 실제 운영 가능한 Creative Brief 파이프라인으로 보완한다. 문서상의 완료 판정을 재사용하지 않고 DB, API, 서비스, LangGraph checkpoint/resume, Planning UI, 실제 백엔드 기반 브라우저 테스트를 서로 역검증한다.

완료 기준은 다음과 같다.

- LG-7R 대상 미구현 0건, 부분 구현 0건, 테스트 우회 0건
- 실제 유료 LLM 및 이미지 provider 호출 0건
- fake real-LLM adapter의 구조화 출력 및 제한된 repair 경로 검증
- 실제 LangGraph interrupt와 `Command(resume=...)` 경로 검증
- 실제 백엔드·DB·LangGraph를 사용하는 Playwright와 새로고침 복구 검증
- LG-6 Prompt/Brand pinning 및 LG-5R 이미지 생성 핵심 회귀 통과

## 2. 요구사항 매핑

| LG-7R 요구사항 | 최종 기획 요구사항 | 구현 작업 | 필수 테스트 |
|---|---|---|---|
| R1 fake real-LLM 구조화 출력/repair | ARC-03, PRM-06~09, OPS-09 | 제한 호출 adapter, Pydantic schema 검증, 1회 repair, 한도 초과 오류 코드 | 정상, 최초 오류 후 성공, 연속 오류 종료, 호출 수 상한 |
| R2 기존 허용 수집 자료를 리뷰로 선택 | REV-01, REV-04 | 프로젝트 자산 중 TXT/CSV/XLSX를 선택 가능한 리뷰 원본으로 노출하고 서버에서 소유권·형식 검증 | 자산 선택 저장, 타 프로젝트 차단, 비허용 MIME 차단 |
| R3 Planning 추적 정보 | PRM-07, BRAND-05, REV-09, FAST-03~07, ARC-03 | Prompt Pack/Brand Kit/Brief pin, 사실/후보, 방향, 입력 사용 여부, 섹션 provenance, 모드, 자동 승인, stale 영향 표시 | API 계약, UI 렌더링, 새로고침 유지 |
| R4 리뷰 파일 견고성/중복 | REV-01, REV-04, OPS-09 | 빈 파일, 손상 XLSX, 인코딩/형식 오류, 업로드 hash 중복의 한국어 오류/멱등 재사용 | 각 오류 코드, 동일 hash 재업로드 시 새 버전 0건 |
| R5 실제 interrupt/resume | ARC-02, HITL-01~02, FAST-03~07 | 컴파일된 실제 그래프와 checkpointer에서 interrupt 후 `Command(resume=...)` | pending review, 동일 thread resume, 다음 interrupt/완료 |
| R6 fake LLM 전체 E2E | ARC-03, PRM-06~09, REV-09 | Creative Brief compile → planning → interrupt → resume 연결 | DB 산출물과 checkpoint를 함께 검증 |
| R7 실제 Playwright | OPS-09, TEST strategy | `page.route` 없는 백엔드/DB/graph 브라우저 시나리오 | 입력 저장, 상태 전이, reload 복구, trace 확인 |
| R8 오류 객체 한국어 표시 | UX error handling, OPS-09 | 구조화 API 오류 파서와 코드별 해결 방법 UI | `[object Object]` 부재, 코드/해결 방법 표시 |

## 3. 구현 순서

1. 현재 schema/API/graph/UI/test의 실제 경로를 감사한다.
2. additive migration으로 리뷰 source asset과 content hash 조회 성능을 보완하고 migration을 두 번 실행해 안전성을 확인한다.
3. 리뷰 parser와 저장 서비스를 typed error 및 hash 멱등 처리로 강화한다.
4. fake real-LLM adapter와 제한된 structured-output repair executor를 Creative Brief compiler에 연결한다.
5. 프로젝트 creative intelligence API에 적용 버전, 사실 계층, section provenance, 모드/승인 이력, stale 범위를 추가한다.
6. Planning UI에 기존 리뷰 원본 선택, 추적 패널, 구조화 한국어 오류 안내를 추가한다.
7. 실제 LangGraph interrupt/resume와 fake LLM 전체 E2E를 작성한다.
8. `page.route` 없는 실제 백엔드 Playwright를 작성하고 새로고침 복구를 확인한다.
9. LG-7R 전체 테스트, LG-6/LG-5R 핵심 회귀, migration 재실행을 수행한다.
10. 코드리뷰 문서와 브라우저 검증 가이드를 작성한 후 요구사항 표에서 코드와 테스트를 역추적한다.

## 4. 사전 누락 검토

- fake adapter만 단위 테스트하고 실제 graph에 연결하지 않는 우회를 금지한다.
- graph node 함수를 직접 호출하는 테스트만으로 interrupt/resume를 충족 처리하지 않는다.
- Playwright에서 대상 API를 `page.route`로 대체하지 않는다.
- 중복 리뷰는 성공처럼 새 row를 만들지 않고 기존 content hash row를 재사용한다.
- 권리/소유권 검증 전 프로젝트 자산을 리뷰 원본으로 읽지 않는다.
- trace API에 ID만 내보내지 않고 version/hash와 적용/후보/영향 범위를 함께 내보낸다.
- 오류 응답의 dict/list가 문자열 보간되어 `[object Object]`로 보이지 않도록 공통 파서를 사용한다.
- 실제 유료 provider는 환경과 테스트 양쪽에서 호출하지 않는다.

## 5. 증거 기록 방식

최종 LG-7R 코드리뷰에는 각 행별로 다음을 기록한다.

- 실제 코드 파일과 심볼
- migration revision 및 재실행 결과
- 테스트 파일과 테스트 이름
- 실행 명령과 통과 수
- 실제 브라우저 검증 주소, 입력값, 버튼 순서, 기대 상태

