# Sellform V2.1 LG-8R 브라우저 검증 가이드

작성일: 2026-08-09

## 1. 실행 환경

`C:\page\backend\.env`에서 다음처럼 무료 mock 경로를 사용한다.

```env
SELLFORM_GRAPH_RUNTIME=langgraph
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
```

백엔드는 `http://localhost:8001`, 프런트엔드는 `http://localhost:3000`을 사용한다. 실제 유료 이미지 API 키는 필요하지 않다.

## 2. 정상 전환 확인

1. `http://localhost:3000/workspace`에서 새 제품을 만든다.
2. 권리 보유 제품 사진을 올리고 역할을 지정한다.
3. `상품 입력 확인`, `근거 사실 확인`, `스토리보드 승인`을 순서대로 진행한다.
4. `비용 승인 후 이미지 생성`을 누른다.
5. 화면이 `provider_wait`로 바뀌면 브라우저를 새로고침한다.
6. 잠시 뒤 같은 URL에서 `생성 이미지 검수 · image_review`가 표시되는지 확인한다.

기대 결과:

- 완료된 각 장면이 한 번씩만 나타난다.
- 이미 끝난 장면이 새 작업으로 중복 생성되지 않는다.
- 새로고침해도 같은 run/thread의 검수 상태가 유지된다.
- 일부 장면만 승인하면 전체 실행이 완료되지 않는다.
- 모든 필수 장면을 승인한 뒤에만 다음 단계로 진행한다.

## 3. 서버 재시작 복구 확인

1. 이미지 생성 직후 `provider_wait`가 보일 때 백엔드 프로세스를 종료한다.
2. `C:\page\run_backend.ps1`로 백엔드를 다시 실행한다.
3. 기존 planning URL을 새로고침한다.
4. `작업 상태 새로고침`이 보이면 한 번 누른다.

기대 결과:

- 새 run을 만들라는 안내가 나오지 않는다.
- 기존 성공 장면과 작업 상태가 보존된다.
- 남은 fake-provider 작업이 처리되고 같은 실행이 `image_review`로 이동한다.
- 동일 장면의 비용이나 작업 수가 증가하지 않는다.

## 4. 자동 반복 검증

PowerShell에서 다음을 실행한다.

```powershell
Set-Location C:\page\frontend
$env:SELLFORM_E2E_REAL_BACKEND='1'
$env:SELLFORM_E2E_EXTERNAL_SERVER='1'
$env:SELLFORM_E2E_REAL_APP_URL='http://localhost:3000'
$env:SELLFORM_E2E_REAL_API_URL='http://localhost:8001'
npx.cmd playwright test e2e/lg8-real-backend-state.spec.ts --reporter=line --repeat-each=3 --workers=1
```

기대 결과: `3 passed`. 이 검증은 실제 백엔드·DB·LangGraph를 사용하며 유료 provider 대신 durable fake provider를 사용한다.

## 5. 실패로 판단할 화면

- 모든 작업이 완료됐는데도 계속 `provider_wait`인 경우
- 새로고침 뒤 run ID가 바뀌거나 검수 결과가 사라지는 경우
- 같은 장면이 두 번 생성되거나 비용이 늘어나는 경우
- 승인한 장면이 다시 `needs_review`로 돌아가는 경우

이 중 하나라도 발생하면 LG-9로 넘어가지 말고 planning URL과 run ID를 함께 기록한다.

