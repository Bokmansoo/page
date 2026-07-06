# Sellform KST 시간 표시 보정 기록

## 증상

- 새 상품 프로젝트를 생성한 직후 대시보드 카드 시간이 실제 한국 시간보다 9시간 빠르게 표시됨.
- 예: 한국 시간 오후 3시대에 생성했지만 화면에는 `오전 6:01`처럼 표시됨.

## 원인

- 백엔드는 `datetime.utcnow()` 기반의 timezone 없는 ISO 문자열을 내려준다.
- 브라우저의 `new Date("2026-06-27T06:01:...")`는 timezone 정보가 없으면 로컬 시간으로 해석한다.
- 실제로는 UTC 시각인데 프론트가 KST 변환 없이 그대로 로컬 시간처럼 표시해 9시간 차이가 발생했다.

## 조치

- `frontend/src/lib/datetime.ts` 공통 유틸을 추가했다.
- timezone suffix가 없는 백엔드 datetime 문자열은 UTC로 간주해 `Z`를 붙인 뒤 파싱한다.
- 대시보드, 설정, 사실 카드 이력, 에디터 버전 이력, export 이력의 시간 표시를 `Asia/Seoul` 기준으로 통일했다.

## 검증

- `frontend` 빌드 검증:

```cmd
npm.cmd run build
```

- 결과: 성공.

## 장기 개선 후보

- 백엔드 저장/응답 시간을 timezone-aware UTC로 통일한다.
- API 응답 스키마에서 `created_at`, `updated_at`이 항상 `Z` 또는 offset을 포함하도록 보장한다.
