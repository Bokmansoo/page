# Sellform V2 LG-5 — 이미지 생성 서브그래프

작성일: 2026-08-07  
상태: 구현 중  
상위 기획: [LangGraph 전환 Sprint 로드맵](2026-08-06-sellform-v2-langgraph-migration-roadmap.md)

## 목표

LG-4의 `generation_pending` interrupt에서 같은 LangGraph thread를 재개해, 승인된 스토리보드 장면을 이미지 작업으로 준비하고 제공자 실행·결과 수집·안전 검사·판매자 이미지 검수까지 연결한다. LG-6의 페이지 조립과 QA는 이 Sprint 범위에서 제외한다.

## 상태 흐름

```text
generation_pending
  ├─ defer → generation_pending (provider 호출 0건)
  └─ approve → prepare_image_jobs → dispatch_image_jobs
        ├─ provider 작업 진행 중 → provider_wait interrupt
        │     └─ worker 완료 → 같은 thread resume → collect_image_results
        └─ mock 동기 완료 → collect_image_results
  → validate_generated_images → image_review interrupt
        ├─ approve → finalize_run
        ├─ regenerate → prepare_image_jobs
        └─ upload → image_review (직접 업로드 후보 재검수)
```

## 구현 계약

1. `ImageGenerationJobRecord`가 장면별 provider 작업·attempt·비용·결과 자산의 기준 레코드다.
2. 작업 키는 기존 `s5-{project/section/variant hash}`를 유지하고, `usage_metadata.langgraph_run_id`로 동일 graph run에 귀속한다.
3. provider 호출은 `generation_pending`에서 판매자가 `approve`하고, provider/비용 게이트가 통과한 뒤에만 가능하다.
4. mock 실행은 실제 유료 provider를 호출하지 않고 동일한 job/검수 상태 계약만 검증한다.
5. real 실행은 queued job을 별도 worker에서 처리한다. worker 완료는 동일 graph thread의 `provider_wait`를 재개한다.
6. API 키 미설정·잔액/한도·timeout·안전 차단·정체성 불일치는 상태 코드와 복구 메시지를 분리해 보존하며 가짜 최종 이미지를 만들지 않는다.
7. `image_review`는 approve/reject/regenerate/upload를 버전 관리된 resume payload로 처리한다. 승인된 결과만 다음 Sprint의 Page Assembly 입력 후보가 된다.
8. 일부 장면 실패는 성공·승인된 다른 장면의 job/asset을 삭제하거나 초기화하지 않는다.

## 완료 조건

- 비용 승인 전 provider 실행이 0건인 테스트가 있다.
- 같은 thread에서 generation pending을 재개해 job이 한 번만 준비된다.
- 성공 장면 재개는 기존 job을 재사용하고 중복 dispatch/청구하지 않는다.
- provider worker 완료 및 결과 수집 뒤 `image_review` interrupt가 복원된다.
- 실패 코드가 provider 설정, 잔액/한도, timeout, 안전·정체성 검사로 분류된다.
- 승인되지 않은 `needs_review` 결과는 graph의 `approved_generated_asset_ids`에 포함되지 않는다.
- LG-5 코드리뷰 문서에 구현 증거와 테스트 결과가 남는다.
