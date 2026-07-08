# Sellform Image Billing Limit And Retry Guide

작성일: 2026-07-09

## 증상

결과 화면의 이미지 후보 영역에 다음 오류가 보이면 OpenAI 이미지 생성 요청이 결제 한도에서 차단된 상태입니다.

```text
BILLING_HARD_LIMIT_REACHED
Billing hard limit has been reached.
billing_hard_limit_reached
```

이 경우 텍스트 상세페이지 생성은 완료될 수 있지만, AI 이미지 asset은 생성되지 않습니다.

## 원인

`.env` 설정이나 Sellform 라우팅 문제가 아니라 OpenAI Platform 계정/프로젝트의 사용 한도 또는 결제 상태 문제입니다.

확인할 항목:

- OpenAI Platform Billing 한도
- 프로젝트 budget / hard limit
- 결제수단 상태
- 크레딧 잔액
- 현재 `.env`의 `OPENAI_API_KEY`가 한도가 풀린 프로젝트의 키인지

## 처리 순서

1. OpenAI Platform에서 결제 한도 또는 budget을 조정합니다.
2. 필요하면 `.env`의 `OPENAI_API_KEY`를 정상 결제 프로젝트의 키로 교체합니다.
3. 백엔드 서버를 재시작합니다.
4. 결과 화면 우측 이미지 후보에서 `이미지 다시 생성`을 누릅니다.
5. 같은 상세페이지 텍스트는 유지되고, 실패했던 이미지 job만 다시 실행됩니다.

## 재시도 후 상태

- 성공하면 후보가 `생성 이미지`로 바뀌고 asset이 표시됩니다.
- 실패하면 동일 후보 카드에 새 오류 상세가 표시됩니다.
- 전체 작업을 새로 만들 필요는 없습니다. 이미지 job만 재시도하면 됩니다.

