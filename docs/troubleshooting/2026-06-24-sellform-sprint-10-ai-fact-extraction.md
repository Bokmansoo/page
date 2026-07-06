# 트러블슈팅: Sellform Sprint 10 AI 사실 카드 자동 추출

## 1. 개요

Sprint 10에서는 사실 확인 보드에서 사용자가 모든 사실을 수기로 작성하지 않도록, 상품 텍스트와 이미지 자산에서 사실 카드 후보를 자동 생성하는 기능을 추가했다.

## 2. 확인된 이슈와 대응

### M1. URL 직접 수집은 구현하지 않음

- **증상**: 상품에 `raw_input_url`이 있어도 URL 내용을 직접 가져오지 않는다.
- **원인**: 공급처 URL은 캡차, 로그인, 봇 차단, 약관, SSRF, timeout 문제가 발생할 수 있다.
- **현재 처리**: API 응답의 `failed_sources`에 다음 fallback 메시지를 반환한다.

```json
{
  "source": "url",
  "reason": "url_collection_deferred",
  "message": "URL direct collection is deferred; manual text and uploaded assets were used instead."
}
```

- **복구 방법**: 사용자가 공급처 상세 설명 텍스트를 복사해 `raw_input_text`에 넣거나 이미지를 업로드한 뒤 자동 생성을 실행한다.
- **후속 과제**: 안전한 URL fetch 정책, timeout, Content-Type 제한, SSRF 차단, 실패 사유 분류를 별도 작업으로 구현한다.

### M2. 기존 로컬 SQLite DB의 컬럼 누락 가능성

- **증상**: 기존 개발 DB에 `extraction_source`, `confidence`, `needs_review`, `risk_flags` 컬럼이 없으면 facts 조회/저장 시 오류가 날 수 있다.
- **원인**: `Base.metadata.create_all()`은 기존 SQLite 테이블을 자동으로 alter하지 않는다.
- **조치**: FastAPI startup 시 `ensure_sqlite_schema_compatibility()`가 누락 컬럼을 추가하도록 보정했다.
- **주의**: 이는 로컬 SQLite용 임시 호환 레이어이며, 운영 DB로 전환할 때는 정식 migration을 작성해야 한다.

### M3. deterministic extractor의 커버리지 제한

- **증상**: 알려진 패턴이 없는 문장은 자동 사실 후보가 적거나 낮은 신뢰도 후보로 생성될 수 있다.
- **원인**: Sprint 10 1차 구현은 외부 LLM 호출 없이 테스트 가능한 deterministic rule 기반 extractor를 사용한다.
- **복구 방법**: 사용자가 수동 사실 카드를 추가하거나, 입력 텍스트에 명확한 스펙 문장을 포함한다.
- **후속 과제**: 실제 LLM/멀티모달 adapter와 JSON schema validation을 연결한다.

### N1. facts 페이지 기존 한글 문구 깨짐

- **증상**: 일부 UI 문구가 깨진 문자로 표시된다.
- **원인**: Sprint 10 이전부터 존재한 TSX 파일 내 문자열 인코딩 문제.
- **조치**: Sprint 10 신규 UI 문구는 정상 한글로 추가했다.
- **후속 과제**: 별도 보완 작업으로 facts 페이지 전체 문구를 정리한다.

## 3. 검증 명령

```powershell
uv run --project backend pytest backend/tests/test_facts.py -q
uv run --project backend pytest -q
cd frontend
npm.cmd run build
```

## 4. 결론

자동 사실 카드 생성의 1차 경로는 안정적으로 동작한다. 다만 URL 직접 수집과 이미지 내용 OCR/멀티모달 분석은 이번 범위에서 제외했으므로, 실제 상품 URL만으로 완전 자동 생성되는 경험은 후속 고도화가 필요하다.

