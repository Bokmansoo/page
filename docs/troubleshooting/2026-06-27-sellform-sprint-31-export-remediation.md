# Sprint 31 내보내기 보완 트러블슈팅

## 증상 1. 커머스 컷 코드가 있는데 결과물이 기존 형태로 출력됨

### 원인

프론트 내보내기 요청이 `use_commerce_cut` 옵션을 전달하지 않아 백엔드 기본값 `false`가 적용됐다.

### 해결

내보내기 요청 body에 다음 값을 추가했다.

```json
{
  "preset_name": "coupang",
  "use_commerce_cut": true
}
```

## 증상 2. 렌더링 테스트가 마지막 파일 삭제 단계에서 실패함

### 오류

```text
PermissionError: [WinError 5] 액세스가 거부되었습니다.
```

### 원인

고정된 테스트 이미지 경로를 반복 사용하고 종료 직후 삭제하면서 Windows 파일 점유와 충돌할 수 있었다.

### 해결

pytest `tmp_path`로 실행마다 고유한 이미지 파일을 만들고 수동 삭제를 제거했다. 샌드박스에서 사용자 임시 폴더 접근이 제한될 때는 `--basetemp`로 프로젝트 내부 테스트 전용 경로를 지정한다.

## 증상 3. Playwright가 120초 후 웹 서버 대기 시간 초과로 종료됨

### 오류

```text
Error: Timed out waiting 120000ms from config.webServer.
```

### 의미

Sprint 31 테스트 assertion이 실패한 것이 아니다. Playwright가 테스트 시작 전에 실행하는 Next.js 개발 서버가 `http://127.0.0.1:3000`에서 준비되지 못했다.

### 확인 및 재실행

첫 번째 CMD에서 프론트 서버를 실행한다.

```cmd
cd C:\page\frontend
npm.cmd run dev
```

브라우저에서 `http://localhost:3000/workspace`가 열리는 것을 확인한다. 그 상태에서 두 번째 CMD를 열어 테스트를 실행한다.

```cmd
cd C:\page\frontend
npm.cmd run test:e2e -- sprint31-commerce-cut-export.spec.ts
```

Playwright 설정의 `reuseExistingServer`가 로컬 환경에서 활성화되어 있으므로, 이미 실행 중인 서버를 사용해 테스트 본문으로 진입한다.
