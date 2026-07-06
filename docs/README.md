# 셀폼 문서 운영 가이드

이 폴더는 셀폼을 만들고 운영하면서 내린 결정, 검증 결과, 장애 대응, 조사 자료를 남기는 기준점이다. 문서는 코드와 같은 수준으로 검토한다.

## 폴더 구조

| 경로 | 목적 | 새 문서를 만드는 때 |
|---|---|---|
| [decisions/](decisions/README.md) | 기술·제품 결정 기록(ADR) | 되돌리기 어렵거나 여러 작업에 영향을 주는 선택을 확정할 때 |
| [testing/](testing/README.md) | 테스트 계획과 실행 증적 | 기능 검증, 회귀 테스트, 수동 QA를 수행할 때 |
| [troubleshooting/](troubleshooting/README.md) | 문제 해결 기록 | 원인 분석이나 재발 방지 조치가 필요한 문제가 생겼을 때 |
| [runbooks/](runbooks/README.md) | 운영·복구 절차 | 장애, AI 작업 실패, 배포 실패를 반복 가능하게 대응해야 할 때 |
| [research/](research/README.md) | 판매처 정책·시장·기술 조사 | 외부 사실·규격·정책을 제품 결정에 사용할 때 |
| [releases/](releases/README.md) | 릴리스 노트 | 사용자가 체감하는 변경을 배포할 때 |
| [reviews/](reviews/README.md) | 리뷰 가이드와 리뷰 기록 | 설계·기능·코드 변경을 검토할 때 |
| [superpowers/plans/](superpowers/plans/) | 스프린트·구현 실행 계획 | 승인된 기획을 작업 순서와 완료 기준으로 나눌 때 |
| [superpowers/specs/](superpowers/specs/) | 제품 기획서와 설계 문서 | 제품 범위·흐름·아키텍처를 확정할 때 |
| [../memory/](../memory/) | 장기 교훈과 리뷰 요약 | 반복해서 참고할 가치가 있는 결론이 생겼을 때 |

## 모든 작업의 최소 기록

작업 하나를 마칠 때 다음 네 가지를 해당 문서 또는 작업 기록에 남긴다.

1. 무엇을 했는가
2. 왜 했는가
3. 어떻게 검증했는가
4. 남은 위험과 다음 작업은 무엇인가

AI가 관여한 작업에는 추가로 모델·프롬프트 또는 워크플로 버전, 비용·소요 시간, 품질 이슈를 남긴다.
## 사용자 가이드

- [Sellform 홈페이지로 상세페이지 만드는 법](guides/2026-06-24-sellform-homepage-user-guide.md)
