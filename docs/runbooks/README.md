# Sellform Runbooks

Sellform 로컬 개발, 서버 실행, 테스트, 외부 도구 연동 절차를 모아둔 운영 문서 목록입니다.

각 runbook은 다음 상황에서 빠르게 참고하기 위한 문서입니다.

- 로컬 서버 실행
- PostgreSQL 실행
- LLM/mock 모드 전환
- API 없는 프론트 테스트 페이지 확인
- Figma 연동
- 장애 또는 재현 절차 정리

## 빠른 실행 / 로컬 서버

- [Sellform 서버 실행 및 LLM 모드 가이드](./2026-07-03-sellform-server-start-and-llm-mode-guide.md)
- [Sellform 현재 서버 실행 가이드](./2026-07-02-sellform-current-server-start-guide.md)
- [Sellform 로컬 서버 실행 Runbook](./2026-06-24-sellform-local-server-runbook.md)
- [Sellform CMD 기준 로컬 서버 실행 가이드](./2026-06-26-sellform-cmd-server-start-guide.md)

## PostgreSQL 실행

- [Sellform PostgreSQL Only CMD 실행 가이드](./2026-06-26-sellform-postgresql-only-cmd-start-guide.md)
- [Sellform PostgreSQL CMD 실행 가이드](./2026-06-26-sellform-postgresql-cmd-start-guide.md)

## LLM / 이미지 생성 / mock 모드

- [Sellform LLM 및 이미지 생성 모드 가이드](./2026-07-07-sellform-llm-and-image-generation-mode-guide.md)

## 테스트 페이지

- [Sellform API 없는 상세페이지 미리보기 테스트 페이지 가이드](./2026-07-07-sellform-api-free-detail-page-preview-sandbox-guide.md)

## Figma 연동

- [Sellform Figma MCP 통합 Runbook](./sellform-figma-mcp-integration-runbook.md)
- [Sellform Figma Plugin Importer Runbook](./2026-06-28-sellform-figma-plugin-runbook.md)
- [Sellform Figma MCP 실행 가이드](./2026-06-27-sellform-figma-mcp-runbook.md)
- [Sellform Figma MCP CMD 실행 가이드](./2026-06-28-sellform-figma-mcp-cmd-start-guide.md)

## 기타 운영 문서

- [Sellform 약관 및 정책](./2026-06-24-sellform-terms-and-policies.md)
- [Sellform Sprint 7 Runbook](./2026-06-23-sellform-sprint-7-runbook.md)

## 권장 사용 순서

처음 로컬에서 실행할 때는 아래 순서로 확인합니다.

1. 서버 실행 문서 확인
2. PostgreSQL 실행
3. `.env`의 mock/API 모드 확인
4. 프론트엔드 실행
5. API 없는 테스트 페이지 또는 실제 작업 목록 페이지에서 확인

API 비용 없이 화면만 확인하려면 먼저 테스트 페이지 문서를 보면 됩니다.

