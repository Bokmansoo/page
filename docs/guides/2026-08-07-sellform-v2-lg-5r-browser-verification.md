# LG-5R 브라우저 사용자 검증 가이드

## 1. 안전한 로컬 설정

`C:\page\backend\.env`에 아래 값을 설정하고 백엔드를 재시작한다. 이 검증은 유료 API를
호출하지 않는다.

```env
SELLFORM_GRAPH_RUNTIME=langgraph
SELLFORM_GENERATION_MODE=mock
SELLFORM_IMAGE_GENERATION_MODE=mock
SELLFORM_IMAGE_WORKER_ENABLED=true
SELLFORM_IMAGE_WORKER_POLL_SECONDS=0.5
SELLFORM_IMAGE_WORKER_LEASE_SECONDS=60
SELLFORM_IMAGE_WORKER_BATCH_SIZE=4
```

확인 주소:

- 백엔드 상태: `http://localhost:8001/`
- API 문서: `http://localhost:8001/docs`
- Sellform: `http://localhost:3000/workspace`

## 2. 입력값

- 상품명: `LG-5R 검증용 경추 마사지 베개`
- 설명: `정격 입력 DC 5V 2A, 제품 크기 40 x 17 x 15cm, 온열·압박 마사지 기능`
- 사진: 글자·로고·워터마크가 없는 직접 촬영 또는 사용 권리가 있는 제품 사진 2장 이상

## 3. 버튼 순서와 기대 결과

1. `http://localhost:3000/workspace`에서 `AI 상세페이지 생성`으로 새 작업을 만든다.
   - planning 상단의 사진 카드가 `unknown`이면 각 카드의 역할 선택 메뉴를 사용한다.
   - 권리 보유 사진 중 제품 전체가 선명한 1장은 `대표 제품 전체`로 지정한다.
   - 다른 1장은 사진 내용에 맞게 `조작부·측면 상세`, `제품 구성품`, `제품 실사용`,
     `사용 장면` 중 하나로 지정한다.
   - 공급처 참고 사진은 기획 참고용일 뿐 AI provider의 정체성 기준 사진으로 사용할 수 없다.
   - 역할 선택 뒤 새로고침해도 선택값이 유지되는지 확인한다.
2. `상품 입력 확인`에서 사진과 설명을 확인하고 `확인·다음 단계`를 누른다.
3. `근거 사실 확인`에서 확정 사실을 확인하고 `확인·다음 단계`를 누른다.
4. `스토리보드 승인`까지 진행한다.
5. `이미지 생성 비용·제공자 확인`에서 다음을 확인한다.
   - 장면 수
   - provider와 model
   - 장면별 예상 비용
   - 총 예상 비용
6. 먼저 `대기 상태 저장`을 한 번 누른다.
   - 같은 `generation_pending` 화면이 유지되어야 한다.
   - `/docs`의 `GET /api/v1/image-worker/outbox`에는 새 dispatch가 없어야 한다.
7. `비용 승인 후 이미지 생성`을 빠르게 두 번 눌러 본다.
   - 요청은 한 번만 처리되고 `이미지 생성 작업 진행 중`이 표시되어야 한다.
8. 이 상태에서 새로고침한다.
   - 같은 runId와 provider 대기 상태가 복원되어야 한다.
    - worker가 완료하면 자동으로 `생성 이미지 검수`로 이동한다.
   - `IDENTITY_REFERENCE_INSUFFICIENT`가 보이면 위 1번의 역할 분류가 빠졌거나,
     해당 사진이 `공급처 참고 사진`인 경우다. 권리 보유 사진 2장을 역할 지정한 뒤
     실패 장면만 재생성한다.
9. 첫 장면에서 `이 장면 승인`을 누른다.
   - 승인 전에 카드 안의 `생성 결과 미리보기`를 직접 확인해야 한다.
   - mock 모드에서는 실제 AI 디자인 대신 테스트용 실루엣 PNG가 표시된다.
   - real 모드에서는 이미지 provider가 생성한 실제 결과가 같은 위치에 표시된다.
   - `1/N개 필수 장면 승인`처럼 표시되고 전체 실행은 완료되지 않아야 한다.
10. 다른 장면에서 `거절` 후 `이 장면 재생성`을 누른다.
    - 비용 화면의 장면 수가 전체가 아니라 **1개**여야 한다.
    - 다시 비용 승인하면 그 장면만 새 시도로 생성되고 이미 성공한 장면은 유지돼야 한다.
11. 다른 미승인 장면에서 `권리 보유 사진 선택` 드롭다운을 연다.
    - raw asset ID 입력칸이 없어야 한다.
    - 파일명을 선택하고 `선택 사진 연결`, 이어서 `이 장면 승인`을 누른다.
12. 이미지 검수 상태에서 다시 새로고침한다.
    - 승인·거절·재생성·업로드 상태가 그대로 복원되어야 한다.
13. 모든 필수 장면을 승인한다.
    - 마지막 장면 승인 전에는 완료되지 않고, 마지막 승인 뒤에만 다음 그래프 단계 또는 완료로 이동해야 한다.

## 4. 운영 상태 선택 확인

`http://localhost:8001/docs`에서 다음 API를 확인할 수 있다.

- `GET /api/v1/image-worker/outbox`: queued/leased/completed/dead-letter와 dispatch count
- `POST /api/v1/image-worker/recovery-sweep`: 만료 lease 복구
- `POST /api/v1/image-worker/outbox/{delivery_id}/retry`: 원인이 확정된 dead-letter 재시도

유료 provider 전송 결과가 불명확한 `PROVIDER_OUTCOME_UNKNOWN`은 중복 과금 방지를 위해
자동 또는 운영자 API로 바로 재전송되지 않는 것이 정상이다.
