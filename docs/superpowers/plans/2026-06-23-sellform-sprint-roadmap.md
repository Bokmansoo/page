# 셀폼(Sellform) 스프린트 실행 로드맵

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement each sprint task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 셀폼의 최종 기획을 실제 내부 판매 도구 1.0으로 구현하고, 이후 외부 셀러 SaaS로 확장 가능한 기반을 만든다.

**Architecture:** 전체 제품은 상품 프로젝트, 사실·근거 레지스트리, 카테고리 엔진, AI 콘텐츠 생성, 페이지 조합·검수·출력의 독립 모듈로 나눈다. 각 스프린트는 실행 가능한 세로 단면(vertical slice)을 완성하며, 다음 스프린트는 이전 스프린트의 검증된 데이터와 인터페이스 위에서만 진행한다.

**Tech Stack:** Next.js + TypeScript + React, Tailwind CSS, FastAPI + Python, PostgreSQL, S3 호환 오브젝트 스토리지, Redis 기반 작업 큐, HTML/CSS + Headless Chromium 렌더링, 공급자 교체 가능한 AI 어댑터.

---

## 운영 원칙

- 한 스프린트가 끝나기 전 다음 스프린트의 구현을 시작하지 않는다.
- 스프린트 시작 전에는 해당 범위만 다루는 세부 구현 계획을 `docs/superpowers/plans/`에 별도 작성한다.
- 스프린트 종료 전에는 테스트 증적, 리뷰 기록, 남은 위험을 반드시 남긴다.
- 실제 상품 또는 현실적인 테스트 상품으로 기능을 검증한다.
- 기획서에 없는 기능은 스프린트 범위에 조용히 추가하지 않는다. 필요하면 결정 기록과 리뷰를 먼저 남긴다.

## 전체 순서

```text
S0 조사·기준선
 → S1 제품 기반
 → S2 자료·사실 확인
 → S3 AI 정리·카테고리
 → S4 상세페이지 생성·편집
 → S5 이미지형 출력·검수
 → S6 웹형 출력
 → S7 운영 안정화·실상품 검증
 → S8 SaaS 확장 준비
```

## Sprint 0 — 구현 전 조사와 품질 기준

**목표:** 바뀌기 쉬운 외부 규격과 AI 선택을 조사해 구현의 전제조건을 확정한다.

### 범위

- [ ] 쿠팡·네이버 스마트스토어의 최신 상세 설명·이미지 등록 규격을 공식 출처로 조사한다.
- [ ] 중국·해외·국내 공급처 링크·자료 처리의 기술적 제한과 권리·약관 위험을 조사한다.
- [ ] 패션·뷰티·식품·리빙의 표시·광고 검수 우선 규칙을 조사한다.
- [ ] 후보 AI 모델의 이미지 이해, 한국어 카피, 구조화 출력, 비용·지연시간을 평가한다.
- [ ] 카테고리별 정상·누락·위험 입력을 가진 상품 테스트 팩을 정의한다.

### 산출물

- `docs/research/`의 조사 기록 4개 이상
- `docs/testing/`의 상품 테스트 팩 계획
- `docs/decisions/`의 AI 공급자·모델 선택 결정 기록

### 완료 기준

- 판매처 출력 규격이 출처·확인 날짜와 함께 문서화되어 있다.
- 4개 카테고리의 최소 필수 정보와 위험 표현 예시가 정리되어 있다.
- AI 선택의 품질·비용·대체 전략이 결정 기록으로 남아 있다.

### 제외 범위

- 애플리케이션 코드 구현
- 판매처 자동 등록 연동

## Sprint 1 — 제품 기반과 안전한 프로젝트 작업대

**목표:** 사용자·워크스페이스·브랜드·상품 프로젝트·파일을 안전하게 관리하는 실행 가능한 기반을 만든다.

### 범위

- [ ] Next.js 프론트엔드와 FastAPI 백엔드를 프로젝트 구조로 초기화한다.
- [ ] 개발·테스트 환경의 PostgreSQL, 파일 저장소, 작업 큐 구성을 만든다.
- [ ] 워크스페이스, 브랜드, 상품 프로젝트의 데이터 모델·권한 경계를 구현한다.
- [ ] 프로젝트 대시보드와 새 상품 초안 생성 화면을 구현한다.
- [ ] 안전한 파일 업로드와 외부 링크 사전 검사를 구현한다.
- [ ] 자동 저장, 작업 상태, 감사 이벤트의 최소 기반을 구현한다.

### 완료 기준

- 사용자 1명이 브랜드 1개와 빈 상품 프로젝트를 생성·수정·재개할 수 있다.
- 허용하지 않는 링크·파일은 명확한 이유와 대안 행동을 보여주며 차단된다.
- 새로고침 후 초안과 업로드 완료 파일이 유지된다.
- 자동·수동 테스트와 리뷰 기록이 남아 있다.

### 제외 범위

- 공급처 정보 자동 추출
- AI 생성과 상세페이지 렌더링

## Sprint 2 — 자료 입력과 사실·근거 확인

**목표:** 공급처 원본과 직접 촬영 자료를 사실 카드로 정리하고 사용자가 안전하게 확정할 수 있게 한다.

### 범위

- [x] 공급처 링크, 텍스트, 캡처, 사진을 하나의 상품 프로젝트에 연결한다.
- [x] 수동 입력을 기본 흐름으로 완성하고, 링크 처리 실패 시 `SOURCE_EXTRACTION_UNAVAILABLE` 복구 화면을 제공한다.
- [x] 상품 사실, 근거 원본, 확인 상태(`확인됨`, `수정 필요`, `모름`)와 변경 이력을 구현한다.
- [x] 사실 확인 보드에서 원본 근거와 한국어 사실을 나란히 비교·수정·확정하게 한다.
- [x] 확인되지 않은 사실이 최종 출력 후보에 쓰이지 않도록 데이터 규칙을 적용한다.

### 완료 기준

- 사진·텍스트만으로도 하나의 상품 사실 카드를 끝까지 만들 수 있다.
- 링크 추출이 실패해도 입력한 자료가 사라지지 않고 수동 입력으로 이어진다.
- 확정 사실을 수정해도 이전 사실과 근거, 변경자가 남는다.

### 제외 범위

- 실제 AI 자동 추출 품질 최적화
- 카테고리별 카피 생성

## Sprint 3 — AI 자료 정리와 카테고리 엔진

**목표:** AI가 원본 자료를 구조화·번역하고, 사용자가 확정할 카테고리와 필수 확인 항목을 추천한다.

### 범위

- [x] AI 어댑터와 JSON 스키마 검증 계층을 구현한다.
- [ ] 텍스트·이미지 기반 후보 사실 추출과 중국어·외국어 자료의 한국어 정리를 구현한다. *(텍스트 중심 구현 완료, 이미지 실분석은 공개 URL/base64 정책과 함께 후속 처리)*
- [x] AI 실패, 빈 결과, 스키마 오류에 대한 재시도·수동 입력 대체 흐름을 구현한다.
- [x] 패션·뷰티·식품·리빙 프리셋의 필수 필드, 권장 섹션, 위험 표현 규칙을 구현한다.
- [x] 카테고리 추천과 사용자의 최종 변경·확정 흐름을 구현한다.
- [x] 작업 ID, 모델·프롬프트 버전, 시간, 비용, 오류를 기록한다.

### 완료 기준

- 테스트 팩의 각 카테고리에서 후보 사실과 누락 질문이 구조화된 데이터로 생성된다.
- AI가 실패해도 사용자는 수동 편집으로 사실 확인 단계를 끝낼 수 있다.
- 카테고리별 필수 정보 누락이 사용자에게 행동 가능한 이슈로 표시된다.

### 제외 범위

- 판매 카피와 상세페이지 시각 생성

## Sprint 4 — 상세페이지 계획·생성·가이드형 편집

**목표:** 확정된 사실과 사진으로 카테고리별 상세페이지를 생성하고, 사용자가 안전하게 수정할 수 있게 한다.

### 범위

- [ ] 스타일 토큰, 템플릿, 섹션 JSON의 페이지 조합 모델을 구현한다.
- [ ] AI가 추천 스타일 1개와 대안 1개, 추천 근거, 섹션 계획을 생성하게 한다.
- [ ] 섹션별 판매 카피를 확인된 사실 ID에 연결해 생성한다.
- [ ] 가이드형 3단 편집기(섹션 목록, 모바일 미리보기, 선택 섹션 편집·AI 수정)를 구현한다.
- [ ] 문구 수정, 사진 교체, 섹션 숨김·순서 변경, 대표색·폰트 톤 변경을 구현한다.
- [ ] AI 수정은 전체 재생성보다 섹션 단위 부분 재생성을 우선한다.
- [ ] 페이지 버전 생성·비교·복원을 구현한다.

### 완료 기준

- 각 카테고리 테스트 상품이 최소 한 개의 편집 가능한 상세페이지 초안을 생성한다.
- 미확인 사실은 경고와 함께 초안에서만 보이고, 최종 사용 후보에는 자동으로 포함되지 않는다.
- 이전 페이지 버전을 열고 현재 버전으로 복원할 수 있다.

### 제외 범위

- 자유 배치형 캔버스 편집
- 판매처용 파일 다운로드

## Sprint 5 — 검수와 이미지형 판매처 출력

**목표:** 판매처에 올릴 수 있는 긴 세로형 상세페이지를 검수하고 이미지 묶음으로 출력한다.

### 범위

- [ ] 페이지 섹션을 HTML/CSS 기반으로 렌더링하고 모바일 미리보기를 구현한다.
- [ ] Headless Chromium 기반 이미지 렌더링과 긴 페이지 분할 출력을 구현한다.
- [ ] 확인 상태, 카테고리 필수 정보, 위험 표현, 이미지 해상도·잘림·빈 자산을 검사한다.
- [ ] 검수 이슈에서 대상 섹션으로 이동하고 수정·재검수할 수 있게 한다.
- [ ] 출력 작업을 비동기 작업으로 처리하고 다운로드 이력·파일을 저장한다.
- [ ] 판매처별 출력 프리셋을 설정 데이터로 관리한다.

### 완료 기준

- 4개 카테고리 테스트 팩에서 모바일 기준의 이미지형 상세페이지가 출력된다.
- 차단 이슈가 남은 페이지는 최종 판매처 출력이 막힌다.
- 렌더링 실패·파일 저장 실패에 재시도와 사용자 안내가 있다.

### 제외 범위

- 판매처 API를 통한 자동 등록
- 인터랙티브 웹 공개 페이지

## Sprint 6 — 인터랙티브 웹형 출력

**목표:** 동일한 상품 프로젝트를 모바일 랜딩페이지로 발행하고 판매처 구매 링크로 연결한다.

### 범위

- [ ] 페이지 버전에서 웹형 공개 페이지를 생성·발행한다.
- [ ] 구매 버튼, 이미지 갤러리, FAQ 펼치기 기능을 구현한다.
- [ ] 상품·카테고리에 따라 옵션 전환, 전후 비교, 영상 링크를 선택적으로 활성화한다.
- [ ] 공개 URL, 비공개 전환, 재발행, 판매처 링크 설정을 구현한다.
- [ ] 모바일 성능·접근성·링크 오류 검사를 추가한다.

### 완료 기준

- 이미지형 상세페이지와 동일한 사실·카피·자산 기반의 웹형 페이지가 생성된다.
- 구매 버튼은 설정한 쿠팡 또는 스마트스토어 상품 페이지로 이동한다.
- 공개 페이지를 비공개로 전환하면 접근이 차단된다.

### 제외 범위

- 장바구니·결제·자체 쇼핑몰 기능

## Sprint 7 — 운영 안정화와 실상품 검증

**목표:** 실제 소싱 상품으로 셀폼의 전 과정을 검증하고, 운영 가능한 품질 기준을 만든다.

### 범위

- [ ] 실제 또는 현실적인 소싱 상품 10~20개를 프로젝트로 완성한다.
- [ ] 입력부터 첫 이미지형 출력까지의 시간, 재생성 횟수, AI 비용, 검수 이슈를 측정한다.
- [ ] 프로젝트별 작업 추적, 실패율, 평균 시간, 비용, 카테고리별 경고 비율을 보는 운영 화면 또는 리포트를 구현한다.
- [ ] 오류 알림과 AI 작업·렌더링·파일 저장 장애 런북을 작성한다.
- [ ] 테스트 팩, 출력 스크린샷 비교, 회귀 테스트를 CI에 연결한다.
- [ ] 발견한 반복 문제를 결정·트러블슈팅·memory 문서로 정리한다.

### 완료 기준

- 10개 이상의 상품에서 판매처용 출력물을 실제로 만들 수 있다.
- 주요 작업 실패가 사용자·운영자 어느 쪽에도 조용히 사라지지 않는다.
- 비용·성능·품질 기준과 남은 제한이 릴리스 노트에 기록된다.

### 제외 범위

- 외부 고객 결제·팀 협업

## Sprint 8 — 외부 셀러 SaaS 준비

**목표:** 내부 도구에서 검증한 흐름을 외부 셀러 베타로 안전하게 열 준비를 한다.

### 범위

- [ ] 워크스페이스 초대, 역할·권한, 브랜드 다중 관리를 구현한다.
- [ ] 사용량 집계, AI 비용 한도, 작업 속도 제한을 구현한다.
- [ ] 데이터 보관·삭제 정책, 개인정보·AI 생성물 고지, 이용 약관 초안을 준비한다.
- [ ] 외부 셀러 3~5명 베타의 온보딩·피드백·지원 흐름을 설계한다.
- [ ] 구독·결제 도입 여부는 베타 사용량과 비용을 근거로 별도 결정 기록을 남긴다.

### 완료 기준

- 서로 다른 워크스페이스의 데이터와 파일이 격리된다.
- 외부 베타 사용자를 안전하게 초대·제한·지원할 수 있다.
- 구독 결제는 검증 전 억지로 도입하지 않고, 측정 가능한 판단 기준을 가진다.

### 제외 범위

- 쿠팡·네이버 스마트스토어 자동 상품 등록
- 성과 데이터 기반 자동 최적화

## 스프린트 종료 공통 체크리스트

- [ ] 해당 스프린트의 완료 기준을 모두 충족했다.
- [ ] 자동 테스트와 필요한 수동 QA의 실행 결과를 `docs/testing/`에 남겼다.
- [ ] [리뷰 기록 템플릿](../../reviews/TEMPLATE.md)으로 기능·설계·코드 변경을 검토했다.
- [ ] 오류·복구 절차가 필요한 경우 `docs/troubleshooting/` 또는 `docs/runbooks/`에 남겼다.
- [ ] 중요한 선택은 `docs/decisions/`에, 반복 교훈은 `memory/`에 남겼다.
- [ ] 사용자에게 보이는 변경은 `docs/releases/`에 기록했다.
- [ ] 다음 스프린트로 넘어가기 전에 범위·의존성·남은 위험을 검토했다.

## 스프린트별 세부 계획 생성 규칙

각 스프린트를 시작할 때 다음 문서를 먼저 만든다.

`docs/superpowers/plans/YYYY-MM-DD-sellform-sprint-N-실행계획.md`

세부 계획에는 정확한 파일 경로, 데이터 모델 변경, API 계약, 테스트 케이스, 실행 명령, 완료 기준, 리뷰·문서 산출물을 넣는다. 세부 구현 계획이 승인되기 전에는 해당 스프린트의 코드를 변경하지 않는다.

## Sprint 9 — 1.0 실사용 검증과 제품 안정화

**목표:** Sprint 0~8로 구현된 Sellform 내부 도구 1.0을 실제 또는 현실적인 소싱 상품 10~20개로 끝까지 검증하고, 제품화 전에 고쳐야 할 품질·UX·운영 리스크를 증거 기반으로 정리한다.

### 범위

- [ ] 실제 또는 현실적인 소싱 상품 10~20개를 검증 상품팩으로 정의한다.
- [ ] 패션/잡화, 뷰티/화장품, 식품/건강식품, 생활/리빙 4개 카테고리를 모두 포함한다.
- [ ] 각 상품마다 상품 생성, 자료 입력, 사실 확인, 카테고리 확정, 상세페이지 생성, 편집, 검수, 이미지 export, 공개 페이지 발행까지 end-to-end로 실행한다.
- [ ] 상품별 소요 시간, 사용자 수정 횟수, AI 비용, 검수 이슈, export 성공 여부, 판매처 업로드 가능 판단을 기록한다.
- [ ] Blocker/Major 결함만 Sprint 9 안에서 작게 보완하고, 나머지는 Sprint 10 후보로 분리한다.
- [ ] Sprint 10의 방향을 운영 배포 안정화, 이미지 AI 고도화, MCP 연동, 외부 셀러 베타 중 하나로 결정한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-9-실사용검증-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-9-baseline-test-log.md`
- `docs/testing/2026-06-24-sellform-sprint-9-product-validation-pack.md`
- `docs/testing/2026-06-24-sellform-sprint-9-product-run-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-9-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-9-troubleshooting.md`
- `docs/releases/2026-06-24-sellform-sprint-9.md`
- `memory/2026-06-24-sellform-sprint-9-lessons.md`
- `docs/decisions/2026-06-24-sellform-sprint-10-direction.md`

### 완료 기준

- 10개 이상 상품을 전체 흐름으로 검증한다.
- 4개 카테고리 모두 최소 2개 이상 검증한다.
- 5개 이상 상품에서 이미지형 상세페이지 export를 생성한다.
- 4개 이상 상품에서 공개 랜딩형 페이지 발행을 검증한다.
- export 또는 발행까지 가지 못한 상품은 compliance 차단, 입력 부족, AI 실패, 수동 보완 필요 등으로 원인을 분류한다.
- 실패 사례와 우회/복구 방법이 문서화된다.
- Sprint 10의 방향이 결정 기록으로 남는다.

## Sprint 10 — AI 사실 카드 자동 추출 고도화

**목표:** 사용자가 상품 URL, 복사한 상세 설명 텍스트, 업로드 이미지를 제공하면 AI가 상품 사실 카드 후보를 자동 생성하고, 사용자는 검수·수정·확정 중심으로 작업하도록 사실 확인 흐름을 고도화한다.

### 범위

- [ ] 사실 확인 보드에 `AI로 사실 카드 자동 생성` 진입점을 추가한다.
- [ ] 프로젝트의 공급처 URL, 수동 입력 텍스트, 업로드 이미지 자산을 하나의 분석 입력으로 묶는다.
- [ ] 링크 직접 수집은 실패 가능성을 전제로 timeout, 보안 차단, 로그인/캡차 실패를 명확히 표시하고 수동 입력으로 fallback한다.
- [ ] AI 응답은 `fact_text`, `source_text`, `source_asset_id`, `confidence`, `extraction_source`, `needs_review`를 포함한 구조화 JSON으로 받는다.
- [ ] 자동 생성된 사실은 기본 `unknown` 또는 `needs_revision` 상태로 저장하고, 사용자가 `confirmed`로 바꾼 항목만 상세페이지 생성에 사용한다.
- [ ] 중복 사실, 근거 없는 과장 표현, 인증·효능·원산지·수치 오기재 위험 후보를 감지해 검수 경고를 표시한다.
- [ ] 자동 추출 결과, 실패 사유, 사용자 확정 이력을 테스트 로그와 리뷰 문서에 남긴다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-10-ai-fact-extraction-실행계획.md`
- `docs/decisions/2026-06-24-sellform-ai-fact-extraction-direction.md`
- `docs/testing/2026-06-24-sellform-sprint-10-ai-fact-extraction-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-10-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-10-ai-fact-extraction.md`

### 완료 기준

- 수동 텍스트만 있는 상품에서 5개 이상 사실 후보를 자동 생성할 수 있다.
- 업로드 이미지가 있는 상품에서 이미지 근거를 연결한 사실 후보를 생성할 수 있다.
- URL 수집이 실패해도 프로젝트 흐름이 중단되지 않고 수동 입력 fallback 안내가 표시된다.
- 사용자는 사실 카드 전체를 수기로 작성하지 않고 AI 후보를 검수하는 방식으로 진행할 수 있다.
- 미확정 사실이 상세페이지 생성에 사용되지 않는 테스트가 통과한다.
- 자동 추출 성공/실패 케이스가 테스트 로그, 코드리뷰, 트러블슈팅 문서에 남는다.

## Sprint 11 — 사실 확인 보드 UX 문구 정리와 사용성 보완

**목표:** Sprint 10에서 추가한 자동 사실 카드 생성 기능을 사용자가 헷갈리지 않고 쓸 수 있도록 facts 페이지의 깨진 한글 문구, 상태 안내, 빈 상태, 자동 생성 결과 UX를 정리한다.

### 범위

- [ ] facts 페이지의 깨진 한글 문구를 정상화한다.
- [ ] `AI로 사실 카드 자동 생성`, `사실 카드 수동 추가`, `검증 완료 및 다음 단계` 등 핵심 버튼 문구를 일관되게 정리한다.
- [ ] 자동 생성 후보와 사용자가 승인한 `확인됨` 사실의 차이를 명확히 안내한다.
- [ ] URL fallback, 중복 제외, 위험 플래그, 신뢰도 안내를 사용자 친화적인 한국어로 표시한다.
- [ ] 빈 상태에서 AI 자동 생성 또는 수동 추가를 선택할 수 있게 한다.
- [ ] 데스크톱과 모바일 폭에서 사실 카드 보드를 수동 QA한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-11-facts-ux-copy-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-11-facts-ux-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-11-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-11-facts-ux.md`

### 완료 기준

- facts 페이지에서 깨진 한글 문구가 보이지 않는다.
- 사용자가 AI 자동 생성 버튼의 목적을 이해할 수 있다.
- 자동 생성 후보와 확인된 사실의 차이가 명확히 표시된다.
- URL fallback 안내가 사용자 친화적으로 표시된다.
- 데스크톱과 모바일 폭에서 주요 흐름이 읽힌다.
- 프론트 빌드와 수동 QA 결과가 문서화된다.

## Sprint 12 — 이미지 OCR·멀티모달 사실 추출 고도화

**목표:** 업로드된 상품 이미지 안의 텍스트, 옵션표, 사이즈표, 성분표, 패키지 정보를 읽어 사실 카드 후보로 생성한다.

### 범위

- [ ] 이미지 분석 provider 전략을 결정하고 문서화한다.
- [ ] deterministic mock OCR provider와 교체 가능한 image text extractor 인터페이스를 구현한다.
- [ ] 이미지 OCR/mock 결과를 `source_asset_id`와 연결해 사실 후보로 생성한다.
- [ ] 이미지 분석 실패 시 전체 API가 실패하지 않고 fallback 안내를 반환한다.
- [ ] 낮은 신뢰도 후보는 자동 확정하지 않고 `needs_revision` 또는 검수 필요 상태로 둔다.
- [ ] 프론트에서 이미지 분석 실패와 낮은 신뢰도 후보를 사용자 친화적으로 안내한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-12-image-ocr-multimodal-facts-실행계획.md`
- `docs/decisions/2026-06-24-sellform-image-ocr-provider-strategy.md`
- `docs/testing/2026-06-24-sellform-sprint-12-image-ocr-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-12-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-12-image-ocr.md`

### 완료 기준

- 이미지 파일명/mock OCR 결과에서 텍스트 후보가 생성된다.
- 이미지 텍스트에서 1개 이상 사실 카드 후보가 생성된다.
- 생성된 후보는 `source_asset_id`로 이미지 근거와 연결된다.
- 이미지 분석 실패 시 `failed_sources`에 실패 사유가 남는다.
- 낮은 신뢰도 또는 위험 후보는 자동 `confirmed` 처리되지 않는다.
- 백엔드 전체 테스트와 프론트 빌드가 통과한다.

## Sprint 13 — 문제 해결형 상세페이지 내러티브 템플릿

**목표:** 확인된 상품 사실을 “문제 제기 → 핵심 소구점 → 보조 장점 → 요약 → 상품 정보” 흐름으로 배치하는 문제 해결형 상세페이지 템플릿을 추가한다.

### 범위

- [ ] `problem_solution` narrative template을 정의한다.
- [ ] 상세페이지 생성 요청에 `narrative_template` 선택값을 추가한다.
- [ ] 문제 해결형 템플릿의 섹션 순서를 `problem_statement`, `main_claim`, `secondary_benefit`, `main_claim_support`, `benefit_list`, `summary_claim`, `product_information`으로 고정한다.
- [ ] 패션, 뷰티, 식품, 리빙 카테고리별 문제 제기/소구점 변형 규칙을 적용한다.
- [ ] mock/fallback page generator에서도 동일한 섹션 구조를 생성한다.
- [ ] page editor에서 `카테고리 기본형`과 `문제 해결형`을 선택할 수 있게 한다.
- [ ] confirmed fact만 본문 카피에 사용하고 미확정 사실은 warnings로만 남긴다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-13-problem-solution-template-실행계획.md`
- `docs/decisions/2026-06-24-sellform-narrative-template-strategy.md`
- `docs/testing/2026-06-24-sellform-sprint-13-template-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-13-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-13-template.md`

### 완료 기준

- `problem_solution` narrative template으로 page 생성 요청을 보낼 수 있다.
- 생성된 page sections가 문제 해결형 7단계 순서를 따른다.
- problem_solution 템플릿도 confirmed fact만 본문 카피에 사용한다.
- page editor에서 템플릿 선택 UI가 제공된다.
- 백엔드 page 테스트와 전체 회귀 테스트가 통과한다.
- 프론트 빌드가 통과한다.
## Sprint 14 — 실상품 템플릿 품질 검증

**목표:** Fashion, Beauty, Food, Living의 실제 또는 현실적인 소싱 상품 4개로 카테고리 기본형과 문제 해결형을 비교하고, 카테고리별 권장 템플릿과 다음 고도화 우선순위를 결정한다.

### 범위

- [ ] 카테고리별 상품 1개씩을 선택하고 자료 출처·이미지 사용 권한·광고 주의사항을 기록한다.
- [ ] confirmed 사실 카드와 이미지를 같은 조건으로 유지해 두 템플릿을 각각 생성한다.
- [ ] 사실성, 카테고리 적합성, 설득 구조, 모바일 390px 가독성, 공개 미리보기·이미지 export를 평가한다.
- [ ] 발견 이슈의 재현 절차와 심각도를 기록하고, Blocker/Major 보완은 별도 Sprint로 분리한다.
- [ ] 카테고리별 권장 템플릿과 Sprint 15 후보 하나를 결정 문서에 남긴다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-14-template-quality-validation-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-14-validation-pack.md`
- `docs/testing/2026-06-24-sellform-sprint-14-template-comparison-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-14-quality-review.md`
- `docs/decisions/2026-06-24-sellform-template-recommendation.md`
## Sprint 15 - 사실 카드 일괄 입력 UX 개선

**목표:** 사용자가 상품 사실을 하나씩 입력하지 않고, 여러 사실과 근거를 한 번에 붙여넣어 검수 가능한 사실 카드로 만들 수 있게 한다.

### 범위

- [ ] facts 페이지에 `여러 사실 한번에 추가` 진입점을 추가한다.
- [ ] 여러 줄 입력을 파싱해 사실 카드 여러 개를 생성한다.
- [ ] `사실 | 근거: ...` 형식을 지원한다.
- [ ] 같은 프로젝트 안의 동일한 사실 문장은 중복 제외한다.
- [ ] 일괄 생성 결과로 생성 수, 중복 제외 수, 실패 수를 표시한다.
- [ ] 이미지 자산이 없을 때 `업로드된 이미지가 없습니다. 상품 이미지 업로드 후 선택할 수 있습니다.` 안내를 표시한다.
- [ ] 기존 단일 사실 카드 추가 기능은 그대로 유지한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-15-bulk-fact-input-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-15-bulk-fact-input-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-15-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-15-bulk-fact-input.md`

### 완료 기준

- 한 번의 입력으로 5개 이상 사실 카드를 생성할 수 있다.
- 중복 사실은 새로 생성되지 않는다.
- 이미지가 없는 프로젝트에서도 사용자가 왜 선택지가 없는지 이해할 수 있다.
- 백엔드 facts 테스트와 프론트 빌드가 통과한다.

## Sprint 16 - 실제 AI API 기반 사실 후보 생성

**목표:** `.env`의 API 키를 사용해 입력 텍스트와 업로드 이미지 기반 사실 카드 후보를 실제 AI로 생성하고, 키가 없거나 실패할 때는 안전하게 fallback한다.

### 범위

- [ ] `.env.example`에 `OPENAI_API_KEY`, `OPENAI_FACT_MODEL`, timeout 설정을 추가한다.
- [ ] 로컬 서버 runbook에 AI 키 설정 방법을 문서화한다.
- [ ] `OPENAI_API_KEY`가 있을 때 실제 OpenAI 사실 추출 adapter를 사용한다.
- [ ] API 키가 없거나 AI 호출이 실패하면 fallback 안내를 반환한다.
- [ ] AI 후보는 자동 `confirmed` 처리하지 않고 사용자 검수 상태로 저장한다.
- [ ] provider, model, duration, 실패 사유를 테스트 로그와 리뷰 문서에 남긴다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-16-real-ai-fact-extraction-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-16-real-ai-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-16-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-16-real-ai.md`

### 완료 기준

- `.env`에 `OPENAI_API_KEY`가 있을 때 실제 AI adapter 경로가 사용된다.
- 키가 없거나 호출 실패 시 작업이 중단되지 않는다.
- AI 후보는 자동 확정되지 않는다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

## Sprint 17 - URL 기반 상품 원문 수집

**목표:** 사용자가 상품 URL을 입력하면 Sellform이 정책과 실패 가능성을 고려해 원문 정보 수집을 시도하고, 성공한 텍스트를 AI 사실 후보 생성 입력으로 연결한다.

### 범위

- [ ] 프로젝트 source URL에서 공개 HTML 텍스트 수집을 시도한다.
- [ ] 수집 성공 시 source snapshot을 사실 후보 생성 입력에 포함한다.
- [ ] 쿠팡/스마트스토어처럼 차단 가능성이 높은 사이트는 실패를 정상 경로로 처리한다.
- [ ] 차단, timeout, 동적 렌더링 실패 시 수동 복사 붙여넣기 fallback을 안내한다.
- [ ] 외부 사이트 차단 우회, 로그인 우회, CAPTCHA 우회는 구현하지 않는다.
- [ ] URL 수집 정책 결정 문서를 작성한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-17-url-source-collection-실행계획.md`
- `docs/decisions/2026-06-24-sellform-url-collection-policy.md`
- `docs/testing/2026-06-24-sellform-sprint-17-url-collection-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-17-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-17-url-collection.md`

### 완료 기준

- 일반 공개 HTML URL에서 텍스트를 수집할 수 있다.
- 차단/실패 URL에서도 API가 죽지 않고 fallback 안내를 반환한다.
- 수집 텍스트가 AI 사실 후보 생성 입력으로 연결된다.
- 외부 사이트 차단 우회가 구현되지 않는다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

## Sprint 18 - LLM Router & PostgreSQL Runtime Setup

**목표:** Sellform의 AI 사실 추출을 단일 OpenAI 호출 구조에서 LLM Router 기반 다중 Provider 구조로 확장하고, SQLite 개발 흐름을 유지하면서 PostgreSQL 운영 전환이 가능하도록 준비한다.

### 범위

- [ ] `.env.example`과 `.env`에 LLM Router 설정을 추가한다.
- [ ] 기본 Provider는 `openai`, 기본 모델은 `gpt-5.4-nano`로 설정한다.
- [ ] 1차 fallback Provider는 `google`, 모델은 `gemini-2.5-flash`로 설정한다.
- [ ] 최종 fallback은 기존 deterministic/local fallback으로 유지한다.
- [ ] `backend/src/services/llm_router.py`를 추가해 provider/model 순서, 실패 처리, fallback 결과를 통합한다.
- [ ] `/facts/auto-extract`가 direct OpenAI 호출 대신 LLM Router를 사용하도록 변경한다.
- [ ] AI 후보 사실 카드는 자동 확정하지 않고 사용자 검수 상태로 저장한다.
- [ ] provider, model, duration, 실패 사유를 테스트 로그 또는 코드리뷰 문서에 남긴다.
- [ ] SQLite 기본 개발 경로는 유지한다.
- [ ] PostgreSQL 연결 설정과 실행 방법을 runbook에 추가한다.
- [ ] PostgreSQL 연결 smoke test 절차를 문서화한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-18-llm-router-postgresql-runtime-실행계획.md`
- `docs/decisions/2026-06-24-sellform-llm-router-and-db-runtime.md`
- `docs/testing/2026-06-24-sellform-sprint-18-llm-router-postgresql-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-18-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-18-llm-router-postgresql.md`

### 완료 기준

- `.env.example`에 OpenAI 기본 Provider와 Google fallback Provider 설정이 있다.
- 실제 API 키가 없을 때도 기존 fallback 흐름이 깨지지 않는다.
- API 키가 있을 때 LLM Router가 설정된 순서대로 provider를 시도한다.
- OpenAI 실패 시 Google fallback을 시도하고, 둘 다 실패하면 deterministic fallback으로 내려간다.
- AI 후보 사실은 자동 확정되지 않는다.
- 실패 provider/model/reason이 확인 가능하다.
- SQLite 개발 환경이 계속 동작한다.
- PostgreSQL 연결 방법과 문제 해결법이 문서화되어 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

## Sprint 19 - 스타일 후보와 판매 전략 선택 UX

**목표:** 상세페이지 생성 전에 기본 7단 설득 구조와 카테고리별 변형 규칙을 적용하고, 디자인 미리보기와 판매 전략 설명이 포함된 스타일 후보 3개를 사용자가 선택할 수 있게 만든다.

### 범위

- [ ] 상세페이지 기본 구조를 7단 설득 프레임으로 고정한다.
- [ ] 생활/리빙, 패션잡화, 뷰티, 식품/건강식품 카테고리별 변형 규칙을 정의한다.
- [ ] 스타일 후보 3개를 생성한다.
- [ ] 각 후보에 디자인 미리보기, 판매 전략 설명, 추천 이유를 표시한다.
- [ ] 하나의 후보에 `AI 추천` 배지를 표시한다.
- [ ] `쿠팡 적합`, `스마트스토어 적합`, `둘 다 가능` 채널 배지를 표시한다.
- [ ] 사용자는 반드시 하나의 후보를 선택한 뒤 상세페이지를 생성한다.
- [ ] 마음에 들지 않으면 `다른 스타일 다시 추천`을 사용할 수 있다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-19-style-strategy-selection-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-19-style-strategy-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-19-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-19-style-strategy.md`

### 완료 기준

- 스타일 후보가 항상 3개 표시된다.
- 하나의 후보에는 `AI 추천` 배지가 있다.
- 모든 후보에는 판매 전략 설명과 디자인 미리보기 요약이 있다.
- 모든 후보에는 채널 적합도 배지가 있다.
- 사용자는 스타일을 선택한 뒤 상세페이지를 생성할 수 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

## Sprint 20 - 검증 기반 상세페이지 생성과 위험 문구 검수

**목표:** 확인된 사실 카드를 중심으로 상세페이지 문구를 생성하고, 근거가 필요한 표현은 경고와 수정 제안으로 검수할 수 있게 만든다.

### 범위

- [ ] 확인된 사실 카드 기반으로 주요 주장을 생성한다.
- [ ] 일반적인 사용 장면과 감성 표현은 허용한다.
- [ ] 성능, 효능, 수치, 안전, 건강, 인증, 비교 우위 표현은 근거가 없으면 위험 문구로 표시한다.
- [ ] 섹션별로 어떤 사실 카드가 근거로 쓰였는지 매핑한다.
- [ ] 상세페이지 상단에 검수 요약을 표시한다.
- [ ] 상세 검수 패널에서 위험 문구, 위험 사유, 수정 제안을 확인할 수 있게 한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-20-grounded-page-generation-validation-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-20-grounded-generation-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-20-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-20-grounded-generation.md`

### 완료 기준

- 확인된 사실 기반 문구와 일반 감성 표현이 공존할 수 있다.
- 근거 없는 위험 주장은 경고된다.
- 검수 요약과 상세 검수 패널이 표시된다.
- 위험 문구에는 수정 제안이 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

## Sprint 21 - 상세페이지 버전 관리와 Export 1차 완성

**목표:** 상세페이지 생성/재생성/큰 수정 시 버전 스냅샷을 저장하고, 최종본을 긴 세로 이미지와 섹션별 이미지 ZIP으로 내보낼 수 있게 만든다.

### 범위

- [ ] AI 초안 생성 시 버전을 저장한다.
- [ ] 스타일 재추천/재생성 시 버전을 저장한다.
- [ ] 큰 수정 시 버전을 저장한다.
- [ ] 이전 버전을 복원할 수 있다.
- [ ] 하나의 최종본을 지정할 수 있다.
- [ ] 긴 세로 이미지 1장으로 export할 수 있다.
- [ ] 섹션별 이미지 ZIP으로 export할 수 있다.
- [ ] export 전 검수 체크리스트를 표시한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-21-versioning-export-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-21-versioning-export-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-21-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-21-versioning-export.md`

### 완료 기준

- AI 생성/재생성/큰 수정 시 버전 스냅샷을 남길 수 있다.
- 이전 버전을 복원할 수 있다.
- 하나의 프로젝트에는 최종본이 하나만 존재한다.
- 최종본을 긴 세로 이미지로 export할 수 있다.
- 최종본을 섹션별 이미지 ZIP으로 export할 수 있다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

## Sprint 22 - Living 골든 패스 UX 정리

**목표:** 생활/리빙 상품 하나를 링크 입력부터 상세페이지 저장까지 진행할 때 사용자가 다음 행동을 헷갈리지 않도록 작업 흐름 UI를 정리한다.

### 범위

- [ ] `1 자료 입력 → 2 사실 확인 → 3 스타일 선택 → 4 상세페이지 편집 → 5 저장/내보내기` 단계 표시를 추가한다.
- [ ] 각 화면에 현재 사용자가 해야 할 일을 안내한다.
- [ ] 다음 단계 버튼의 활성화 조건을 명확히 한다.
- [ ] 버튼이 비활성화된 경우 이유를 표시한다.
- [ ] 링크 수집 실패, 백엔드 연결 실패, AI fallback 상태를 이해 가능한 문구로 표시한다.
- [ ] page-editor에서 초안 생성 후 다음 행동을 안내한다.
- [ ] 저장, 최종본, export 준비 상태를 명확히 표시한다.
- [ ] Living 골든 패스 QA 체크리스트 기준으로 수동 테스트를 1회 실행한다.

### 산출물

- `docs/superpowers/plans/2026-06-24-sellform-sprint-22-living-golden-path-ux-실행계획.md`
- `docs/testing/2026-06-24-sellform-sprint-22-living-golden-path-ux-test-log.md`
- `docs/reviews/2026-06-24-sellform-sprint-22-code-review.md`
- `docs/troubleshooting/2026-06-24-sellform-sprint-22-living-golden-path-ux.md`

### 완료 기준

- 사용자는 현재 몇 단계에 있는지 알 수 있다.
- 사용자는 각 화면에서 다음에 무엇을 해야 하는지 알 수 있다.
- 다음 버튼이 왜 비활성화됐는지 알 수 있다.
- 실패/대기/성공 상태가 이해 가능한 문구로 표시된다.
- page-editor에서 초안 생성 후 다음 행동이 명확하다.
- 저장/최종본/export 상태가 명확하다.
- Living 골든 패스 QA 체크리스트를 1회 이상 실행했다.
- 프론트 빌드가 통과한다.
---

## Sprint 28 - AI 배경 비주얼 생성

**목표:** 상품명·카테고리·확인된 사실 카드 기반으로 상세페이지에 어울리는 배경/히어로 비주얼 후보를 만들고, 사용자가 선택한 배경을 미리보기와 export 이미지에 반영한다.

### 범위

- page-editor에서 “AI 배경 후보 만들기”를 제공한다.
- 상품/카테고리/판매전략/확인된 사실을 바탕으로 2~3개 배경 후보를 만든다.
- 이미지 생성 API가 없어도 카테고리별 fallback 배경 후보가 동작한다.
- 선택한 배경은 상세페이지 미리보기와 export에 반영한다.
- 타사 로고, 인증마크, 실제 제품 이미지를 AI가 임의 생성하지 않도록 안전 규칙을 둔다.

### 산출물

- `docs/superpowers/plans/2026-06-26-sellform-sprint-28-ai-background-visual-generation-실행계획.md`
- `docs/testing/2026-06-26-sellform-sprint-28-ai-background-test-log.md`
- `docs/reviews/2026-06-26-sellform-sprint-28-code-review.md`
- `docs/troubleshooting/2026-06-26-sellform-sprint-28-ai-background.md`

### 완료 기준

- 배경 후보가 2개 이상 생성된다.
- 후보를 선택하면 미리보기 배경이 바뀐다.
- export 이미지에 선택한 배경이 반영된다.
- 이미지 생성 API가 없어도 fallback으로 동작한다.
- 백엔드 테스트와 프론트 빌드가 통과한다.

---

## Sprint 30 - 상품 이미지 자산 매핑 및 상세페이지 삽입

**목표:** 업로드/수집된 상품 이미지 자산을 상세페이지 섹션에 자동 매핑하고, page-editor 미리보기와 export PNG에 실제 상품 이미지를 삽입한다.

### 범위

- 기존 `Asset`과 `PageSection.image_asset_id`를 활용해 섹션별 이미지 연결 구조를 완성한다.
- 상품 이미지 자산 자동 매핑 서비스를 추가한다.
- page-editor에서 섹션별 이미지 미리보기와 수동 교체 UX를 제공한다.
- export PNG에서 실제 상품 이미지를 렌더링한다.
- 이미지가 없는 경우 기존 fallback 렌더링이 깨지지 않도록 한다.

### 산출물

- `docs/superpowers/plans/2026-06-27-sellform-sprint-30-image-asset-mapping-export-실행계획.md`
- `docs/testing/2026-06-27-sellform-sprint-30-image-asset-mapping-test-log.md`
- `docs/reviews/2026-06-27-sellform-sprint-30-code-review.md`
- `docs/troubleshooting/2026-06-27-sellform-sprint-30-image-assets.md`

### 완료 기준

- 업로드한 상품 이미지가 page-editor 미리보기에 보인다.
- export PNG에 실제 상품 이미지가 들어간다.
- 섹션별 이미지 자동 매핑과 수동 교체가 가능하다.
- 이미지가 없는 프로젝트도 기존처럼 정상 export된다.
- 백엔드 테스트와 프론트 빌드가 통과한다.
- 諛깆뿏???뚯뒪?몄? ?꾨줎??鍮뚮뱶媛 ?듦낵?쒕떎.

## Sprint 31 - 이미지 중심 커머스 컷 렌더링

**목표:** Sprint 30의 이미지 슬롯 기반 출력물을 실제 쇼핑몰 상세페이지처럼 이미지, 배경, 짧은 카피가 한 컷 안에 함께 배치되는 시각형 상세페이지로 고도화한다.

### 범위

- 상세페이지 섹션을 `CommerceVisualCut` 단위로 변환한다.
- 긴 문단형 카피를 헤드라인, 서브카피, 보조문장으로 압축한다.
- 상품 이미지, 배경 영역, 텍스트 오버레이가 함께 렌더링되는 컷 레이아웃을 추가한다.
- 이미지가 없을 때는 명확한 placeholder와 보완 안내를 표시한다.
- PNG 내보내기 결과가 텍스트 문서가 아니라 커머스 이미지 컷처럼 보이도록 개선한다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-27-sellform-sprint-31-visual-commerce-cut-rendering-실행계획.md`

## Sprint 32 - Figma MCP 디자인 내보내기

**목표:** Sellform에서 만든 상세페이지 컷 구조를 Figma에서 편집 가능한 프레임으로 내보낼 수 있게 하되, Sellform 본체의 상세페이지 생성·내보내기 기능은 Figma 없이도 독립적으로 동작하게 유지한다.

### 범위

- Sellform 상세페이지 컷 데이터를 Figma 디자인 payload로 변환한다.
- 페이지 에디터에 `Figma로 내보내기` 진입점을 추가한다.
- Figma MCP가 비활성화된 환경에서는 명확한 안내를 제공한다.
- Figma 연동은 선택형 플러그인 구조로 두고, 핵심 렌더링 엔진에는 깊게 결합하지 않는다.
- Figma 연동 방식, 토큰, 실패 대응, 보안 주의사항을 runbook과 decision 문서로 남긴다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-27-sellform-sprint-32-figma-mcp-design-export-실행계획.md`

## Sprint 33 - 실제 Figma MCP 프레임 내보내기

**목표:** Sprint 32에서 만든 design payload를 사용자가 지정한 기존 Figma Design 파일에 실제 편집 가능한 상세페이지 프레임으로 생성하고, Sellform에서 작업 상태와 결과 링크를 확인할 수 있게 한다.

### 범위

- Figma Remote MCP OAuth를 담당하는 선택형 로컬 bridge를 추가한다.
- 기존 Figma 파일 URL을 입력받아 860px 상세페이지 프레임과 커머스 컷을 생성한다.
- 제목·설명·색상·이미지를 네이티브 Figma 노드로 만들어 편집 가능하게 유지한다.
- 비동기 작업 상태, 결과 node URL, 재시도와 중복 생성 방지를 지원한다.
- 인증, 권한, 공개 이미지 URL, MCP 장애를 구분해 안내한다.
- Figma 실패와 무관하게 Sellform 기본 편집과 PNG export를 계속 제공한다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-27-sellform-sprint-33-live-figma-mcp-export-실행계획.md`

### 실사용 검증 상태

Figma Remote MCP OAuth 동적 클라이언트 등록이 `403 Forbidden`으로 차단되어
Sellform 자체 bridge의 실제 캔버스 쓰기는 완료 처리하지 않는다. canonical payload와
실패 격리 코드는 유지하되, 사용자 제공 기능은 Sprint 34 Figma Plugin 경로로 전환한다.

## Sprint 34 - Sellform Figma Plugin 상세페이지 자동 생성

**목표:** Sellform이 발급한 일회용 코드 또는 JSON 패키지를 Figma Plugin에서 불러와,
현재 열린 Figma Design 파일에 860px 편집 가능한 상세페이지를 자동 생성한다.

### 범위

- 10분 유효·1회 사용 일회용 코드
- canonical payload snapshot과 임시 asset session
- Figma Plugin UI, payload validator, native node renderer
- 기본 7단 Auto Layout, TextNode, Image Fill
- JSON + embedded image fallback
- Sellform 코드 발급·복사·만료·다운로드 UX
- MCP 실패와 무관한 Plugin 및 PNG export
- 자동 테스트와 실제 Figma 수동 QA

### 설계·실행계획

- `docs/superpowers/specs/2026-06-28-sellform-sprint-34-figma-plugin-design.md`
- `docs/superpowers/plans/2026-06-28-sellform-sprint-34-figma-plugin-실행계획.md`

### 완료 기준

- 빈 Figma Design 파일에서 코드를 입력하면 7단 상세페이지가 생성된다.
- 생성된 프레임, 텍스트, 이미지를 Figma에서 편집할 수 있다.
- 코드 재사용과 만료가 차단된다.
- JSON fallback으로 같은 구조를 생성할 수 있다.
- 리뷰·테스트·트러블슈팅·runbook과 실제 Figma QA 증적이 남는다.

## Sprint 35 - Figma 비주얼 커머스 렌더러

**목표:** Sprint 34의 Figma Plugin 결과물을 텍스트 중심 프레임에서 이미지, 배경, 짧은 카피, 카드형 정보가 섞인 커머스 상세페이지 프레임으로 고도화한다.

### 범위

- Figma payload에 `visual_layout`을 추가한다.
- 7단 섹션을 hero/problem/solution/benefit/spec/lifestyle/purchase 커머스 컷으로 변환한다.
- Figma Plugin renderer가 visual layout을 사용해 860px 상세페이지 프레임을 생성한다.
- 이미지가 없을 때도 의도적인 placeholder와 안내를 표시한다.
- 기존 ticket code import와 JSON fallback은 유지한다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-28-sellform-sprint-35-figma-visual-commerce-renderer-실행계획.md`

## Sprint 36 - 이미지 자산 자동 매핑 고도화

**목표:** 업로드·수집·생성된 상품 이미지를 상세페이지 각 섹션에 자동 배치하여 Figma와 PNG 결과물에 실제 상품 이미지가 자연스럽게 들어가도록 만든다.

### 범위

- 이미지 자산 role 분류를 추가한다.
- 섹션별 요구 이미지 role을 정의한다.
- 이미지 자동 매핑 API를 추가한다.
- page-editor에서 섹션별 이미지 매핑 상태와 수동 변경 UX를 제공한다.
- Figma Plugin과 PNG export에 선택된 이미지 매핑을 반영한다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-28-sellform-sprint-36-image-asset-auto-mapping-실행계획.md`

## Sprint 37 - 스타일 후보 선택 및 재생성 고도화

**목표:** 상품과 카테고리에 맞는 상세페이지 스타일 후보 2~3개를 제안하고, 사용자가 선택하거나 다시 생성할 수 있게 하여 디자인 방향을 명확히 제어한다.

### 범위

- style candidate 데이터 모델과 생성 서비스를 추가한다.
- Living 카테고리 기준 `problem_solution`, `spec_focused`, `lifestyle` 후보를 제공한다.
- page-editor에 디자인 미리보기와 판매 전략 설명이 포함된 후보 카드 UX를 추가한다.
- 선택된 style token을 Figma Plugin과 PNG export에 반영한다.
- “다른 스타일 다시 추천” 기능을 제공한다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-28-sellform-sprint-37-style-candidate-selection-실행계획.md`

## Sprint 38 - 마켓 등록 공통 상품 패키지

**목표:** 최종 상세페이지, 확인된 상품 사실, 이미지 산출물을 외부 API 호출 없이 재현 가능한 공통 등록 패키지로 만든다.

### 범위

- 최종 `DetailPageVersion`과 `ExportArtifact`를 불변 JSON 스냅샷으로 묶는다.
- 공통 필수값과 이미지 누락을 검증한다.
- 상품 JSON, 검증 결과, 대표·상세 이미지를 ZIP으로 내려받는다.
- 상세페이지 내보내기 화면에서 `마켓 등록 준비`로 이동한다.

### 실행계획 문서

`docs/superpowers/plans/2026-06-29-sellform-sprint-38-marketplace-product-package-실행계획.md`

## Sprint 39 - 네이버 스마트스토어 승인형 등록

**목표:** 공통 상품 패키지를 네이버 상품 등록 형식으로 변환하고 사용자가 승인한 요청만 스마트스토어로 전송한다.

### 범위

- 스마트스토어 계정 연결과 암호화된 자격 증명 저장
- 네이버 상품 필드 변환 및 필수값 검증
- 등록 미리보기와 패키지 해시 기반 승인
- live submission 기본 비활성화
- 승인 후 상품 등록과 결과 저장

### 실행계획 문서

`docs/superpowers/plans/2026-06-29-sellform-sprint-39-smartstore-registration-실행계획.md`

## Sprint 40 - 쿠팡 승인형 등록

**목표:** 공통 상품 패키지를 쿠팡 상품 생성 형식으로 변환하고 사용자 승인 후 안전하게 전송한다.

### 범위

- 쿠팡 API 자격 증명과 HMAC 서명
- 카테고리·고시·출고지·반품지·옵션 검증
- 등록 미리보기와 승인
- 멱등 키 기반 중복 요청 차단
- 상품 생성 및 상태 저장

### 실행계획 문서

`docs/superpowers/plans/2026-06-29-sellform-sprint-40-coupang-registration-실행계획.md`

## Sprint 41 - 마켓 게시 상태·재시도·운영 안정화

**목표:** 스마트스토어와 쿠팡 등록 상태를 통합하고 실패해도 중복 상품 없이 진단·수정·재시도할 수 있게 한다.

### 범위

- 공통 등록 상태 머신과 이벤트 로그
- 429·5xx·timeout에 한정된 재시도
- timeout 후 원격 상태 선조회
- 내용 변경 시 기존 승인 무효화
- 프로젝트 복구 UI와 운영 리포트
- 장애 복구 runbook

### 실행계획 문서

`docs/superpowers/plans/2026-06-29-sellform-sprint-41-marketplace-operations-stability-실행계획.md`
