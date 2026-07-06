# Figma MCP 연동 런북 (Integration Runbook)

본 문서는 Sellform 백엔드와 Figma MCP(Model Context Protocol) 어댑터 간의 연동 설정 및 트러블슈팅 가이드를 제공합니다.

## 1. 연동 구성 요소 및 흐름
1. **Sellform Backend API**: 상세페이지 초안 정보 및 광고 컷 조립 데이터를 가공하여 Figma 규격 Payload JSON 빌드.
2. **Figma MCP Adapter**: 백엔드 내부에 위치하며, 환경 변수 유효성 검사 및 외부 MCP 서버 통신을 담당.
3. **Figma MCP Server / Daemon**: 페이로드를 전달받아 실제 Figma API를 호출하고 노드 레이아웃을 피그마 캔버스에 드로잉.

## 2. 설정 방법 (Configuration)

### 환경 변수 설정
`.env` 파일에 아래 설정을 적용합니다:

```env
# Figma MCP 연동 활성화 여부 (True / False)
SELLFORM_FIGMA_MCP_ENABLED=True

# Figma MCP 엔드포인트 또는 데몬 API URL
SELLFORM_FIGMA_MCP_ENDPOINT=http://localhost:8500/mcp/figma
```

> [!NOTE]
> `SELLFORM_FIGMA_MCP_ENABLED`가 `False` 또는 누락된 경우, 연동은 비활성화되며 Fallback 프로세스로 진입하여 백그라운드 JSON 페이로드만 로컬 반환합니다.

## 3. 트러블슈팅 가이드 (Troubleshooting)

### Q1. Figma 내보내기 버튼 클릭 시 "Figma 연결 전 단계입니다" 라는 메시지가 발생합니다.
- **원인**: `SELLFORM_FIGMA_MCP_ENABLED`가 `False`로 지정되어 있거나, 내부 어댑터가 로컬 데몬 서버와 통신할 수 없을 때 Fallback 상태가 감지된 경우입니다.
- **해결책**:
  1. `.env` 파일의 `SELLFORM_FIGMA_MCP_ENABLED` 값이 `True`로 선언되어 있는지 확인하십시오.
  2. 로컬 Figma MCP 데몬 프로세스가 실행 중이며 `8500` 포트가 열려 있는지 확인하십시오.

### Q2. 409 Conflict 에러가 반환됩니다.
- **원인**: 현재 프로젝트에 생성된 상세페이지 초안(Draft)이 없는 상태에서 Figma 내보내기를 시도한 경우 발생합니다.
- **해결책**: 에디터 화면으로 이동하여 상세페이지 초안 및 컷 리스트 생성을 먼저 완료한 뒤 내보내기를 다시 시도하십시오.
