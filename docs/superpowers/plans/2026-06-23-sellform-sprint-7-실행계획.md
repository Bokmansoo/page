# 셀폼(Sellform) 스프린트 7 세부 실행 계획

- **일자:** 2026-06-23
- **목표:** 실제 및 현실적인 소싱 상품 10~20개를 통해 셀폼의 전 과정을 검출 및 검증하고, 운영 안정성 확보를 위한 리포트/대시보드와 장애 대응 런북을 마련합니다.

---

## 1. 파일 경로 및 아키텍처

### 1.1 백엔드 구조 (`backend/`)
- [NEW] [operations.py](file:///c:/page/backend/src/api/operations.py): 운영 통계 조회 API (`GET /operations/stats`) 및 대량의 현실적 상품 데이터 적재 API (`POST /operations/seed`) 구현
- [MODIFY] [app.py](file:///c:/page/backend/src/app.py): `operations` 라우터 마운트
- [NEW] [test_operations.py](file:///c:/page/backend/tests/test_operations.py): 통계 산출 및 데이터 시딩 기능 동작 검증 테스트 코드 추가

### 1.2 프론트엔드 구조 (`frontend/`)
- [MODIFY] [layout.tsx (workspace)](file:///c:/page/frontend/src/app/workspace/layout.tsx): 사이드바 내 "운영 리포트" 메뉴 아이템 활성화 및 링크 추가
- [NEW] [page.tsx (operations)](file:///c:/page/frontend/src/app/workspace/operations/page.tsx): 운영 대시보드 UI (통계 위젯, 카테고리별 검수 비율, 프로젝트 작업 목록, Mock 시드 데이터 생성 버튼 구성)

### 1.3 문서 및 CI 통합
- [NEW] [ci.yml](file:///c:/page/.github/workflows/ci.yml): GitHub Actions CI 워크플로우 정의 (pytest 실행 및 Next.js 빌드 회귀 방지)
- [NEW] [run_ci.ps1](file:///c:/page/run_ci.ps1): 로컬 PowerShell CI 모의 스크립트 제공
- [NEW] [2026-06-23-sellform-sprint-7-runbook.md](file:///c:/page/docs/runbooks/2026-06-23-sellform-sprint-7-runbook.md): AI 장애, 렌더링 에러, 스토리지 파일 유실 복구 절차 런북
- [NEW] [2026-06-23-sellform-sprint-7.md](file:///c:/page/docs/releases/2026-06-23-sellform-sprint-7.md): 성능 지표, 비용, 한계사항이 명시된 릴리스 노트

---

## 2. API 계약 (API Contract)

### 2.1 운영 지표 및 통계 조회
- **요청**: `GET /api/v1/operations/stats`
- **인증 필요**: `X-Mock-User-Id` & `X-Mock-Workspace-Id` 기반
- **응답 (200 OK)**:
  ```json
  {
    "summary": {
      "total_projects": 12,
      "total_ai_jobs": 15,
      "ai_job_success_rate": 93.3,
      "ai_job_failure_rate": 6.7,
      "average_ai_duration_seconds": 12.4,
      "total_ai_cost": 0.45,
      "total_export_jobs": 10,
      "export_job_success_rate": 90.0,
      "export_job_failure_rate": 10.0,
      "average_export_duration_seconds": 8.5
    },
    "category_stats": {
      "Fashion": {
        "project_count": 3,
        "total_issues": 2,
        "average_issues_per_project": 0.67,
        "blocker_count": 0,
        "major_count": 2,
        "warning_count": 0
      },
      "Beauty": {
        "project_count": 3,
        "total_issues": 5,
        "average_issues_per_project": 1.67,
        "blocker_count": 3,
        "major_count": 0,
        "warning_count": 2
      },
      "Food": {
        "project_count": 3,
        "total_issues": 3,
        "average_issues_per_project": 1.0,
        "blocker_count": 1,
        "major_count": 2,
        "warning_count": 0
      },
      "Living": {
        "project_count": 3,
        "total_issues": 2,
        "average_issues_per_project": 0.67,
        "blocker_count": 1,
        "major_count": 1,
        "warning_count": 0
      }
    },
    "projects": [
      {
        "id": "UUID",
        "name": "천연 소가죽 클래식 로퍼",
        "category": "Fashion",
        "status": "ready",
        "created_at": "2026-06-23T22:00:00",
        "ai_jobs": {
          "count": 1,
          "total_cost": 0.05,
          "total_duration_ms": 11000,
          "last_status": "success"
        },
        "export_jobs": {
          "count": 1,
          "last_status": "completed"
        },
        "issues": {
          "blocker": 0,
          "major": 0,
          "warning": 0
        }
      }
    ]
  }
  ```

### 2.2 운영 안정성 검증용 데이터 시딩 (Seed Data Generation)
- **요청**: `POST /api/v1/operations/seed`
- **인증 필요**: `X-Mock-User-Id` & `X-Mock-Workspace-Id` 기반
- **응답 (201 Created)**:
  ```json
  {
    "status": "seeded",
    "message": "Successfully seeded 12 realistic projects with job logs, compliance states, page drafts, and exports."
  }
  ```
- **비즈니스 로직**:
  - 기존 시드된 데이터가 있을 경우 중복 생성을 막기 위해 이전 데이터를 정리하거나, 고유한 이름으로 신규 생성합니다.
  - Fashion, Beauty, Food, Living 총 4개 카테고리별로 3개씩, 총 12개의 현실감 있는 프로젝트를 자동 인스턴스화합니다.
  - 각 프로젝트마다 백그라운드 AI 분석 로그(`AiJobLog`), 사실 카드(`ProductFact`), 규정 준수 검사 이슈들, 모바일 상세페이지 안(`ProductPage` + `PageSection`), 내보내기 작업(`ExportJob`), 공개 발행 정보(`PublishedPage`)를 인위적(Simulated)으로 모델 매핑하여 일괄 적재합니다.
  - 이를 통해 실제 AI 요금을 청구하지 않고도 대시보드와 QA를 실시간으로 테스트해볼 수 있도록 환경을 조성합니다.

---

## 3. 테스트 케이스 및 실행 명령

### 3.1 백엔드 단위 테스트 명세 (`backend/tests/test_operations.py`)
1. **시드 데이터 자동 적재 동작 검증**:
   - `POST /api/v1/operations/seed`를 실행하여 12개의 테스트 프로젝트가 올바르게 데이터베이스에 적재되고, 각각의 연관 레코드(AI 로그, 팩트, 페이지, 내보내기 내역 등)가 생성되는지 확인합니다.
2. **통계 수치 계산 검증**:
   - 데이터 적재 완료 후 `GET /api/v1/operations/stats`를 호출하여 전체 프로젝트 수, AI 작업 및 내보내기 실패율, 평균 소요 시간, 카테고리별 경고 이슈들의 개수가 정확하게 일치하는지 단언(Assert)합니다.
3. **권한 격리 검증**:
   - 서로 다른 Workspace ID 헤더를 전달했을 때 통계 집계 및 프로젝트 데이터 노출이 완벽히 격리되는지 확인합니다.

### 3.2 CI 파이프라인 구성 검증
- PowerShell 모의 스크립트 실행으로 CI 정상 작동 확인:
  ```powershell
  ./run_ci.ps1
  ```

---

## 4. 완료 기준 (Definition of Done)

1. **소싱 상품 10~20개 구비**
   - Seed API를 실행하여 최소 12개 이상의 카테고리별 사실과 상태를 지닌 현실적 프로젝트를 완성할 수 있습니다.
2. **운영 지표 분석 및 리포트 제공**
   - 작업 소요 시간, 비용, 실패 비율, 카테고리별 규정 위반(경고/블로커) 비율을 시각적으로 모니터링할 수 있는 운영 대시보드를 제공합니다.
3. **장애 가이드 및 런북 마련**
   - 주요 장애 유형(AI 어댑터 실패, Puppeteer 렌더링 에러, 스토리지 유실) 발생 시 조치 가능한 런북 문서를 완비합니다.
4. **품질 및 성능 기준 릴리스 기재**
   - 소요 시간, 평균 단가 비용, 처리량 한계사항에 대한 계측 수치를 릴리스 문서로 명문화합니다.
5. **테스트 및 CI 검증**
   - 로컬/원격 CI 스크립트를 완비하여 전체 코드와 Next.js 빌드가 회귀 없이 통과함을 증명합니다.
