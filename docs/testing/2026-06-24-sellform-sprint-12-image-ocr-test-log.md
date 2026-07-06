# 테스트 실행 로그: Sellform Sprint 12 Image OCR

- 날짜: 2026-06-24
- 목적: 이미지 OCR/mock 분석 결과가 사실 카드 후보로 연결되는지 검증한다.

## 1. OCR provider 단위 테스트

```text
uv run --project backend pytest tests/test_image_text_extractor.py -q
결과:
..                                                                       [100%]
2 passed, 10 warnings in 0.03s
```

## 2. facts API 회귀 및 통합 테스트

```text
uv run --project backend pytest tests/test_facts.py -q
결과:
...........                                                              [100%]
11 passed, 106 warnings in 1.08s
```

## 3. 전체 테스트

```text
uv run --project backend pytest -q
결과:
57 passed, 430 warnings in 3.36s
```

## 4. 프론트 빌드

```text
npm.cmd run build
결과:
▲ Next.js 14.2.35
   Creating an optimized production build ...
 ✓ Compiled successfully
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (9/9)
   Finalizing page optimization ...
   Collecting build traces ...
Route (app)                               Size     First Load JS
├ ƒ /workspace/projects/[id]/facts        7.34 kB         103 kB
```

## 5. 판단
Mock OCR 및 이미지 기반 사실 카드 자동 추출 API 로직이 전체 단위/통합 테스트 환경과 프로덕션 Next.js 빌드 환경에서 완전히 그린(GREEN) 상태로 검증되었습니다.
