# Sellform API-free Visual Sprint 0 로컬 통합 검증 증거

작성일: 2026-07-31  
실행 환경: Windows 로컬 개발 환경, FastAPI `127.0.0.1:8001`, Next.js `localhost:3000`, PostgreSQL Docker `5544`  
생성 모드: `mock` — export 파이프라인 검증용

## 검증 흐름

각 상품에서 아래 실제 서비스 경로를 실행했다.

```text
상품 입력 → /api/agent-runs 생성 → run-mock → page readiness
→ final version 고정 → PNG export → JPG export → 다운로드 API 응답 확인
```

각 프로젝트는 readiness `true`, 5개 섹션, PNG/JPG `completed` 상태를 확인했다. 각
다운로드 응답의 Content-Type과 바이트 수를 읽고, 생성된 JPG의 760×1265 해상도를 확인했다.

## 결과

| 기준 상품 | 프로젝트 ID | Run ID | PNG 작업 ID | JPG 작업 ID | PNG / JPG 크기 |
| --- | --- | --- | --- | --- | --- |
| 바디프랜드 미니 마사지건 | `c4d5bc81-64ae-4971-9a0c-4ff853b6bda5` | `bdc067c1-59a4-44ac-9087-6d81a23de05d` | `3cc71569-4402-4297-869c-b48c5be19520` | `6df6e2d4-3cdd-43fa-89e3-09008fd6bca2` | 49,829 B / 128,368 B |
| 라운드랩 자작나무 수분 크림 | `5c5396e1-a954-4612-9084-2b51736e94a7` | `7f5ec52d-3a8d-4b86-a270-caaf9392021f` | `367ce8c0-bcaf-420c-bfb1-ddc97cb07687` | `c43428e7-0623-444e-9bb7-f883337b3302` | 50,380 B / 128,173 B |
| 락앤락 비스프리 밀폐용기 세트 | `168718e8-4da9-40b0-bd44-a23e10baad50` | `d3ac1269-e9e2-45a3-ab20-f09946a5deed` | `9b44b6f3-a137-4987-99bf-99bd6597299d` | `8b48c723-bf00-4f13-99a4-5e6f787e2d08` | 51,671 B / 130,614 B |

## 생성 파일

모든 파일은 `backend/uploads/exports/`에 생성됐다.

| 상품 | PNG | JPG |
| --- | --- | --- |
| 미니 마사지건 | `c4d5bc81-64ae-4971-9a0c-4ff853b6bda5_c3b34a3a-cc0d-4410-ae07-cfab3efeb185_long.png` | `c4d5bc81-64ae-4971-9a0c-4ff853b6bda5_084904d8-6508-4204-bb2a-712870f34162_long.jpg` |
| 수분 크림 | `5c5396e1-a954-4612-9084-2b51736e94a7_6b06d18c-a991-4039-9767-349fdde3c380_long.png` | `5c5396e1-a954-4612-9084-2b51736e94a7_e3da2df7-edd0-4aa8-9c6b-c60826504be3_long.jpg` |
| 밀폐용기 세트 | `168718e8-4da9-40b0-bd44-a23e10baad50_1748b0fd-f6e0-4b0c-8df3-ebe5c28b54ed_long.png` | `168718e8-4da9-40b0-bd44-a23e10baad50_ff9946cd-3bfe-4f19-aa72-05165e38cce5_long.jpg` |

JPG를 직접 열어 한글 상품명이 `?`로 깨지지 않고 렌더링되는 것을 확인했다.

## 확인된 범위와 한계

- Chromium 설치·기동, 백엔드 export worker, Next.js export route, 다운로드 API까지 실제로
  연결된 경로를 확인했다.
- 본 검증은 Mock 모드이며 실제 제품 사진이나 외부 AI 이미지가 포함되지 않는다.
- 따라서 빨간 Mock 이미지 제거와 실제 상품 사진 배치는 Sprint 1의 인수 범위다.
- 기준 상품명과 설명은 UTF-8 JSON으로 전송했다. PowerShell 기본 인코딩으로 보낸 초기
  시도는 한글이 `?`로 저장돼 증거에서 제외했다.
