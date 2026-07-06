# 기획 의사결정 전략: Figma MCP 연동

본 문서는 Sellform Sprint 32에서 진행된 Figma MCP(Model Context Protocol) 연동 설계의 핵심 의사결정 배경 및 보안 정책을 기록합니다.

## 1. 배경 및 비즈니스적 가치
- **목적**: AI가 생성한 상세페이지 및 광고 컷 데이터를 Figma 디자인 파일로 신속하게 마이그레이션하여, 디자이너의 후속 편집 비용을 최소화합니다.
- **연동 정책**: Figma 연동은 필수가 아닌 **"선택적 고도화 플러그인"**으로 취급됩니다. 

## 2. 핵심 아키텍처 의사결정

### A. 느슨한 결합 (Loose Coupling) 및 Fallback 보장
- `SELLFORM_FIGMA_MCP_ENABLED` 환경변수를 통해 활성화 여부를 전역 제어합니다.
- MCP 데몬 또는 클라이언트 통신 실패 시(예: 서버가 응답하지 않거나 권한이 없는 경우) 시스템이 정지되지 않고, 일반 내보내기(Sprint 31 이미지 컷 다운로드) 화면으로 매끄럽게 대체(Fallback) 처리됩니다.

### B. 보안 정책 (Security & Confidentiality)
- Figma design payload builder는 아래 민감 데이터를 payload에 포함하지 않습니다:
  - 사용자 API Key 및 토큰
  - 사용자 ID 및 워크스페이스 ID
  - 결제 정보 및 비용 관련 메타데이터
  - 내부 로깅용 추적 ID
- `project.id`와 `section_id`는 Sellform 원본과 Figma 디자인 사본을 연결하는 데 필요한 최소 식별자로 payload에 포함합니다.
- 해당 식별자는 인증 수단으로 사용하지 않으며, 이름·이메일 같은 개인정보와 함께 전달하지 않습니다.

### C. Figma 요건에 부합하는 Payload Schema 설계
- 상세페이지를 구성하는 각 visual 광고 컷과 테마 정보(주색상, 폰트)를 Figma 노드 형태로 변환 가능한 JSON 규격으로 매핑합니다.
- 이미지 조립 시 Sprint 31에서 작성한 이미지 슬롯 생성 유틸리티를 호출하여 이미지 자산 메타데이터를 정합성 있게 매칭합니다.
