# Sellform V2.1 LG-8R Provider Resume Stability Plan

## Confirmed failure

- `frontend/e2e/lg8-real-backend-state.spec.ts` times out while waiting for
  `image_review`; the observed graph stage remains `provider_wait`.
- The failing run completed all eight fake-provider jobs and outbox records.
- Each scene completion independently resumed the same LangGraph
  `provider_wait` interrupt. Those eight serial graph executions accumulated
  enough latency to exceed the real-backend transition budget.

## Requirements and implementation map

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Resume only after the generation wave is terminal | Inspect the latest required job per scene and resume only when `pending_count == 0` | Real DB/fake-provider test asserts one resume for eight jobs |
| Exactly-once graph transition | Reuse the conditional `AgentRun.awaiting_review -> running` resume lease | Duplicate reconciliation and duplicate worker assertions |
| Crash/restart recovery | Reconcile ready `provider_wait` runs at the beginning and end of every durable worker batch, including an empty batch | Simulated crash after job commit, then a new worker session resumes the same run |
| Preserve successful/approved work | Read-only readiness aggregation over latest scene attempts; do not recreate jobs | Existing regeneration/idempotency regressions plus new job/cost count assertions |
| No duplicate cost/provider dispatch | Keep outbox lease and provider idempotency behavior; record one completion-resume coordinator per generation wave | Dispatch count and outbox/job cardinality assertions |
| Real browser stability | Run the existing real backend/DB/LangGraph Playwright test repeatedly without route-level backend mocking | `--repeat-each` evidence in LG-8R review |

## Change sequence

1. Add a durable readiness/reconciliation helper to the image worker.
2. Replace per-scene unconditional resumes with readiness-based resume.
3. Reconcile before and after a batch so a crash between the last job commit
   and callback is recovered even when the queue is empty.
4. Add real DB/fake-provider tests for single resume, duplicate reconciliation,
   and restart recovery.
5. Run LG-8, LG-5R through LG-7R regressions, frontend static checks, and the
   real-backend Playwright flow repeatedly.
6. Update the LG-8 completion record and user verification guide, then perform
   a final code-to-spec reverse audit.

## Non-solutions explicitly excluded

- Increasing Playwright timeouts or adding blind polling.
- Synchronously completing provider work inside the graph.
- Replacing the backend with `page.route` fixtures.
- Calling a paid image or LLM provider.
