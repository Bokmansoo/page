# Sellform 업로드 가능 상세페이지 전체 기획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 무문자 이미지와 HTML/CSS 카피를 결합한 상세페이지를 생성하고, 판매자가 문구를 실제 AI로 다듬은 뒤 PNG/JPG로 그대로 다운로드할 수 있게 한다.

**Architecture:** `PageSection`의 canonical visual contract를 DB부터 export까지 보존하고, 미리보기와 export가 `DetailPageDocument`를 공유한다. AI 문구 수정은 단일 `CopyRewriteService`가 preview를 만들고 판매자가 적용할 때만 page와 version을 갱신한다.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, PostgreSQL/SQLite compatibility DDL, Next.js 14, React, Tailwind CSS, Playwright, pytest, Playwright E2E

---

## 1. 현재 문제

1. `html_graphic`은 agent 중간 결과에만 존재하고 DB/API에서 유실된다.
2. 프론트는 `image_asset_id=null`을 모두 이미지 누락으로 판단한다.
3. 누락 수가 1 이상이면 PNG/JPG 버튼이 비활성화된다.
4. export route는 이미지 로딩 실패도 준비 완료로 처리할 수 있다.
5. AI 문구 수정 endpoint는 문구를 재작성하지 않고 사용자 명령을 본문에 붙인다.
6. visual package와 agent graph가 같은 섹션에 서로 다른 job 상태를 만들 수 있다.

## 2. 제품 완성 기준

- 결과 화면에 빈 이미지 placeholder가 없다.
- 히어로와 사용 장면은 실제 상품 또는 AI 이미지 위에 HTML 제목과 설명이 표시된다.
- 비교, 장점, 구매 전 확인은 HTML 카드 또는 표로 표시된다.
- 미리보기와 PNG/JPG의 이미지, 글씨, 카드, 색상이 동일하다.
- AI 수정 버튼은 선택한 섹션의 제목/본문을 의도에 맞게 재작성한다.
- 내부 명령, `[AI 수정됨]`, `[Revision]`은 판매 문구에 나타나지 않는다.
- 미확인 사실과 검수되지 않은 상품 이미지는 export 전에 차단된다.

## 3. Sprint 구성

| Sprint | 목표 | 사용자에게 보이는 결과 | 선행 조건 |
| --- | --- | --- | --- |
| 61 | Canonical visual contract와 HTML renderer | 빈 3개 영역이 비교/장점/확인 HTML 그래픽으로 표시 | 없음 |
| 62 | PNG/JPG WYSIWYG export 복구 | 미리보기 그대로 PNG/JPG 다운로드 | Sprint 61 |
| 63 | 실제 AI 문구 재작성과 비교 적용 | 버튼별로 제목/본문이 실제 변경 | Sprint 61 |
| 64 | 기존 데이터 보정과 통합 hardening | 기존 프로젝트도 재생성 없이 정상 표시·다운로드 | Sprint 61~63 |

## 4. Sprint 61 — Visual Contract와 HTML/CSS 렌더링

상세 계획:
[Sprint 61 계획](C:/page/docs/superpowers/plans/2026-07-06-sellform-sprint-61-html-visual-contract-and-rendering.md)

완료 조건:

- `PageSection.visual_kind`, `PageSection.visual_payload` 저장
- page/final/version API round trip
- `ImageSectionVisual`, `ComparisonGraphic`, `BenefitCardGraphic`, `SpecTableGraphic`
- HTML 그래픽을 누락 이미지로 계산하지 않음
- 현재 문제 프로젝트 형태의 2 image + 3 HTML fixture 통과

## 5. Sprint 62 — PNG/JPG Export Parity

상세 계획:
[Sprint 62 계획](C:/page/docs/superpowers/plans/2026-07-06-sellform-sprint-62-png-jpg-export-parity.md)

완료 조건:

- PNG/JPG 선택과 다운로드가 모두 동작
- HTML overlay가 최종 이미지 픽셀에 포함
- 이미지 실패 시 export ready가 되지 않음
- 미리보기와 render route가 동일 component와 visual validator 사용
- export 단계별 상태와 오류가 사용자에게 표시

## 6. Sprint 63 — AI Copy Rewrite

상세 계획:
[Sprint 63 계획](C:/page/docs/superpowers/plans/2026-07-06-sellform-sprint-63-ai-copy-rewrite.md)

완료 조건:

- 7개 명령 타입이 각각 올바른 필드를 수정
- 수정 전/후 비교 후 적용 또는 취소
- Real mode는 LLM router, Mock mode는 의미 있는 결정론적 rewrite
- 내부 수정 표식 및 사용자 명령 원문 미노출
- 적용 시 version 생성, 실패 시 원본 보존

## 7. Sprint 64 — Backfill 및 통합 Hardening

상세 계획:
[Sprint 64 계획](C:/page/docs/superpowers/plans/2026-07-06-sellform-sprint-64-integration-hardening.md)

완료 조건:

- 기존 image/null section을 canonical visual contract로 backfill
- visual package와 agent graph의 상태 통합
- identity review와 grounding blocker 연결
- 긴 한글, 이미지 오류, stale version, 포트/config 회귀 검증
- 문제 프로젝트와 동등한 end-to-end fixture에서 빈칸 없는 export

## 8. 릴리스 순서

1. Sprint 61을 feature flag 없이 local/CI에 적용하되 기존 image section fallback을 유지한다.
2. Sprint 62 완료 전에는 새 visual contract를 미리보기에서만 사용하고 production export 전환을 보류한다.
3. Sprint 62 통과 후 canonical Next render export를 기본 경로로 고정한다.
4. Sprint 63은 preview endpoint부터 배포하고 기존 mutation endpoint 호출을 제거한다.
5. Sprint 64에서 기존 프로젝트 backfill 후 fallback 계측을 확인하고 구형 경로를 제거한다.

## 9. 공통 검증 명령

```powershell
cd C:\page
uv run --project backend pytest backend/tests/test_page_visual_contract.py backend/tests/test_copy_rewrite_service.py backend/tests/test_wysiwyg_export_contract.py -v
```

예상 결과: 모든 선택 테스트 통과.

```powershell
cd C:\page\frontend
npm.cmd run lint
npm.cmd run build
npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts --project=chromium
```

예상 결과: lint error 0, production build 성공, Chromium E2E 통과.

## 10. 추가 수정 포인트

우선순위 높음:

- 이미지 `error`를 export ready로 처리하는 로직 제거
- HTML 그래픽을 누락 이미지로 계산하는 완료 조건 제거
- 검수되지 않은 AI 상품 이미지 export 차단
- AI edit endpoint 중복 제거

우선순위 중간:

- 긴 한글 제목과 카드 overflow 자동 검증
- export 진행 단계 표시
- JPG 배경색과 quality preset 명시
- 기존 프로젝트 backfill 결과 보고

후속 보안 개선:

- render query의 user/workspace ID를 서명된 단기 export token으로 교체
- backend port와 API base URL 환경 설정 통일

## 11. 범위 통제

이번 로드맵에는 자유 배치 캔버스, 임의 HTML 입력, AI 이미지 안의 문자 생성,
마켓플레이스 자동 업로드 API는 포함하지 않는다. 목표는 현재 작성·검수·다운로드 흐름을
신뢰할 수 있는 하나의 canonical pipeline으로 완성하는 것이다.
