# 코드 리뷰: 셀폼(Sellform) Sprint 1 (제품 기반과 안전한 프로젝트 작업대)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-23 |
| 리뷰 범위 | FastAPI 프로젝트 구조화, PostgreSQL(SQLAlchemy) 데이터 모델, SSRF 방지 URL 검증기, 안전한 파일 업로드 및 자산 저장 모듈, 프로젝트 CRUD & 자동저장 API, Next.js 대시보드 UI, 새 상품 초안 마법사 및 수동 대체 흐름 UI |
| 관련 기획·작업 | [셀폼 최종 제품 기획서](file:///c:/page/docs/superpowers/specs/2026-06-23-sellform-final-product-design.md), [셀폼 스프린트 실행 로드맵](file:///c:/page/docs/superpowers/plans/2026-06-23-sellform-sprint-roadmap.md), [스프린트 1 세부 실행 계획](file:///c:/page/docs/superpowers/plans/2026-06-23-sellform-sprint-1-실행계획.md) |
| 리뷰어 | Antigravity |
| 상태 | 승인 |

## 1. 변경 요약

- **백엔드 구조 확립 및 DB 모델링 (`backend/`)**:
  - PostgreSQL 세션 설정 및 `User`, `Workspace`, `Brand`, `ProductProject`, `Asset`, `AuditLog`, `JobStatus` 테이블 구성 완료.
  - Pydantic Settings 기반의 세련된 환경 변수 설정 구성.
- **SSRF 보안 제어 및 안전 업로드 (`src/services/validation.py`)**:
  - 외부 주소 입력 시 사설망 IP 대역(RFC 1918 등)으로의 DNS 해석 우회 차단 검증기 적용.
  - 파일 확장자(JPG, PNG) 및 10MB 크기 초과 차단 보안 가드 탑재.
- **Mock 테넌트 격리 및 자가 치유 인증 (`src/api/auth.py`)**:
  - `X-Mock-User-Id` 및 `X-Mock-Workspace-Id` 헤더 전달 시 해당하는 테넌트 정보(사용자, 워크스페이스, 브랜드)가 없을 경우 자동으로 기본값을 생성(Bootstrap)해 주는 이지 온보딩 로직 도입.
- **프로젝트 CRUD 및 자동 저장 (`src/api/projects.py`, `src/api/files.py`)**:
  - 프로젝트 자동 저장(Patch API) 및 동작 흐름 기록(Audit Log) 완비.
- **프론트엔드 작업대 UI (`frontend/`)**:
  - Next.js 14 App Router, TypeScript, Tailwind CSS 기반의 글라스모피즘 스타일 및 HSL 커스텀 틴트 컬러 디자인 시스템 적용.
  - **새 상품 마법사**: 링크 자동수집 실패 시, 데이터를 잃지 않고 상세 문구 수동 기입 및 이미지 드래그 앤 드롭 업로드 폼으로 즉각적이고 매끄럽게 흐름이 전환되는 `SOURCE_EXTRACTION_UNAVAILABLE` 대응 화면 구현.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료
- 코드 파일:
  - 백엔드 핵심: `backend/src/app.py`, `backend/src/main.py`, `backend/src/config.py`, `backend/src/db/database.py`, `backend/src/db/models.py`
  - 보안 및 API: `backend/src/services/validation.py`, `backend/src/api/auth.py`, `backend/src/api/projects.py`, `backend/src/api/files.py`
  - 프론트엔드: `frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`, `frontend/src/app/workspace/layout.tsx`, `frontend/src/app/workspace/page.tsx`, `frontend/src/app/workspace/projects/new/page.tsx`
- 테스트 코드: `backend/tests/test_validation.py`, `backend/tests/test_projects.py`

### 핵심 흐름

```text
[사용자 행동: 새 상품 프로젝트 생성]
       ↓
[프로젝트 이름 및 브랜드 매핑 (Step 1)]
       ↓
[소싱 링크 주소 입력 분석 시도 (Step 2)]
       ├─ [정상 URL 및 공인 IP 해결] → [백엔드 API 호출] → [분석 상태(processing)로 초안 적재 완료] → [대시보드 리다이렉트]
       └─ [SSRF 사설 IP 차단 혹은 분석 실패]
               ↓ (자동 상태 전이)
          [SOURCE_EXTRACTION_UNAVAILABLE 수동 복구 폼 활성화]
               ↓
          [상세 설명 직접 입력 / 10MB 이하 JPG/PNG 이미지 파일 수동 드래그 앤 드롭 업로드]
               ↓
          [수동 데이터 최종 제출] → [Asset 메타데이터 DB 등록 및 이미지 디스크 저장] → [초안(draft) 상태로 대시보드 적재]
```

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 발견 이슈 없음
- SQLite 테스트용 메모리 세션의 커넥션 풀 초기화 문제(no such table) 및 모의 사용자 중복 이메일 유니크 제약 충돌이 발견되었으나, 임시 파일 데이터베이스(`test_temp.db`) 적용 및 `seller-{x_mock_user_id}@sellform.local` 형식의 동적 이메일 생성 로직 반영으로 완벽하게 해결 및 정상 검증되었습니다.
- 모든 기능이 설계 계획 범위 내에서 온전히 부합하여 동작함을 확인하였습니다.

## 4. 우선순위 권고
- Sprint 1의 완료 기준인 권한 경계 격리, 안전한 수동/자동 전환 업로드, 대시보드가 정상적으로 충족되었습니다. 따라서 후속 단계인 **Sprint 2 (자료 입력 및 사실·근거 확인)** 설계를 시작할 것을 권장합니다.

## 5. 긍정적인 부분
- **회복 탄력성 높은 API**: Mock 인증에 `X-Mock-User-Id`가 처음 전달되어도 DB 외래키 제약에 막히지 않고 사용자/워크스페이스/브랜드를 자동으로 점검해 생성해주는 Bootstrapping 로직은 로컬 개발 생산성을 혁신적으로 높였습니다.
- **SSRF 필터링 완성도**: 단순 주소 문자열 검사뿐만 아니라 직접 소켓 DNS 해석(getaddrinfo)을 거쳐 실제 최종 IP 대역까지 차단하는 철저한 다단계 SSRF 가드 설계가 강점입니다.
- **풍부한 UI 심미성**: 기본 템플릿의 단조로운 색상 대신 심도 있는 다크모드 배경 광원 효과(radial-gradient), 글라스모피즘 컴포넌트, 상태 변화에 따른 맥박(pulse) 스타일 애니메이션을 탑재하여 프리미엄한 인상을 줍니다.

## 6. AI·사실 신뢰성 검토
- **사용한 사실과 근거**: 업로드된 이미지 정보와 텍스트의 분류를 위해 `source_type`('sourced', 'self_shot', 'ai_corrected') 필드를 모델에 반영하여, 사실 정보 보존 기준(CEO 리뷰 의결사항 5, 8번)을 온전히 준수하였습니다.

## 7. 검증 증적
- **자동 테스트**: `pytest` 실행 결과 6개 테스트 케이스 100% 통과 완료.
- **빌드 테스트**: Next.js 프론트엔드 TypeScript 정적 분석 및 프로덕션 빌드 절차 통과.
- **수동 QA 테스트**:
  - `http://127.0.0.1/admin` 입력 시 사설망 접근 경고와 함께 수동 대체 폼으로 정상 화면 전환됨 확인.
  - 10MB 이상 용량의 파일 업로드 시 업로드 차단 경고 메시지 표출 확인.
  - 생성된 모든 상품 데이터 및 자산이 PostgreSQL 호환 테이블에 정상 영속화되고 대시보드 목록에 연동되어 자동 저장(Patch API)이 주기적으로 호출됨을 네트워크 탭으로 교차 검토 성공.

## 8. 결론
- **결론:** 승인
- **결정 이유:** 안전성, 격리성, 수동 복구, 대시보드 컴포넌트가 로드맵 요구사항에 완벽하게 부합하며, 버그에 대한 디버깅 조치가 완료되었고 프론트/백엔드 전체 빌드 결과가 견고함.
- **남은 위험과 다음 작업:** 실제 S3 스토리지 연동 및 파일 업로드 경로는 Sprint 7 배포 안정화 단계 전까지 로컬 환경 디스크 업로드(`uploads/` 디렉터리) 방식으로 격리 운영합니다.
