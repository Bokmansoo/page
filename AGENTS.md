# Sellform Agent Instructions

## Project Goal

Sellform is an AI commerce detail-page generation platform.

The current production architecture is based on the LangGraph LG roadmap.

Preserve the existing product behavior while implementing the remaining LG roadmap.

---

## Source of Truth

When implementing an LG task:

1. Read the relevant LG specification or plan first.
2. Treat the relevant LG plan as the source of truth for that task.
3. Inspect only the code necessary to understand and implement the task.
4. Do not reinterpret unrelated historical Sprint documents as current requirements.

If requirements conflict, stop and report the conflict instead of inventing a solution.

The priority order is:

1. Current LG source-of-truth specification
2. Required security, authorization, persistence, and data-integrity contracts
3. Existing production architecture and public API contracts
4. These AGENTS.md instructions
5. Tool/plugin recommendations

Code Review Graph, Ponytail, or any other development tool must never override the current LG specification or required correctness and safety contracts.

---

## Context Efficiency

Minimize repository context before reading broad portions of the codebase.

Code Review Graph is installed for this repository and should be used before broad repository inspection.

Before reading large parts of the repository:

1. Use Code Review Graph first to identify the smallest relevant code surface.
2. Identify:
   - directly affected files
   - callers and dependents
   - relevant tests
   - likely blast radius
3. Read the smallest necessary code surface first.
4. Expand to additional files only when graph evidence, test failures, or the current LG source-of-truth shows they are necessary.
5. Do not scan large unrelated directories merely to gain general context.
6. Prefer incremental graph updates over rebuilding or rereading the entire repository.
7. After meaningful code changes, update the local graph incrementally before using graph results for final review.

Code Review Graph is a context-discovery aid, not an authority.

If graph information conflicts with production code or the current LG specification, verify against the actual code and specification.

Do not skip direct inspection of security-sensitive, persistence-sensitive, authorization-sensitive, or externally exposed code merely because the graph suggests a narrow dependency set.

If Code Review Graph is temporarily unavailable, fall back to direct targeted inspection rather than broad repository scanning.

---

## Minimal Implementation

Apply Ponytail-style minimal-implementation principles on every coding task, whether or not the Ponytail plugin hooks are currently active.

The AGENTS.md rules are authoritative for this behavior; Ponytail plugin hooks or skills are optional accelerators, not a prerequisite.

Before writing new code, check in this order:

1. Does this behavior actually need to be added?
2. Does Sellform already implement the required behavior?
3. Can an existing service/helper be reused or extended?
4. Can Python/TypeScript/platform standard functionality solve it?
5. Can an already-installed dependency solve it safely?
6. Only then add the smallest new implementation required by the current LG specification.

Prefer deleting unnecessary proposed complexity over introducing another abstraction.

Do not optimize for the fewest lines of code at the expense of correctness.

Never remove, weaken, bypass, or omit required:

- validation
- authorization
- workspace/project/run isolation
- immutable lineage
- provenance
- hash/integrity verification
- idempotency
- transaction safety
- retry limits
- checkpoint/recovery behavior
- cost approval
- provider boundaries
- fail-closed behavior
- security controls
- accessibility
- Acceptance Criteria
- required tests

Minimal code means the smallest correct implementation, not code golf.

---

## Implementation Rules

- Use the current production LangGraph path.
- Do not add new features to legacy execution paths.
- Do not create a compatibility layer unless it is required by the current LG specification.
- Prefer modifying an existing service over creating another service with overlapping responsibility.
- Do not create duplicate implementations of existing behavior.
- Do not perform unrelated refactoring.
- Preserve existing public API contracts unless the LG specification explicitly changes them.
- Keep changes scoped to the current task.

Before adding a new service, adapter, abstraction, dependency, provider call, or LLM call:

1. Search the relevant existing production path.
2. Check Code Review Graph first when available.
3. Check whether an existing service/helper already owns the responsibility.
4. Prefer extending the existing owner when that preserves architectural boundaries.
5. Add a new abstraction only when the current LG specification or a real architectural boundary requires it.

Do not introduce speculative abstractions for possible future tasks.

---

## Change Surface

Keep the implementation blast radius as small as practical.

Before editing:

1. Identify the production entry point.
2. Trace the relevant execution path.
3. Identify persistence and authorization boundaries.
4. Identify directly affected tests.
5. Identify downstream callers that rely on the current contract.

Use Code Review Graph to narrow this inspection before manually opening broad code areas.

After editing:

1. Re-check the affected callers/dependents.
2. Confirm that unrelated production paths were not modified.
3. Confirm that no duplicate implementation was introduced.
4. Confirm that the change did not silently expand the task scope.
5. Run `code-review-graph update` when meaningful source changes affect the graph.
6. Re-check the final blast radius before completion when practical.

A smaller diff is preferred only when it still completely satisfies the requirement.

---

## LLM Rules

- Use the existing centralized provider/router architecture for text LLM calls.
- Do not hard-code provider models inside feature services.
- Do not add an LLM call when deterministic code can reliably perform the operation.
- Avoid repeatedly passing large accumulated state when a smaller structured payload is sufficient.
- Reuse existing provider, cost, outbox, worker, and retry infrastructure.
- Do not introduce another provider abstraction when the centralized architecture already supports the requirement.

When deterministic validation is sufficient, prefer deterministic validation.

Do not use an LLM merely because it is convenient if deterministic code can provide the same correctness contract.

---

## Persistence and Database Rules

Use the database appropriate to the test level.

### Production

- Supabase PostgreSQL is the production database.
- Do not mutate production Supabase data unless explicitly authorized.

### Local Development and Integration

Use PostgreSQL for behavior that depends on real persistence semantics, including:

- LangGraph checkpoints
- migrations
- immutable persistence
- transaction behavior
- concurrency
- row locking
- unique constraints
- recovery
- promotion/export gates
- persisted E2E fixtures
- production-like regression fixtures
- PostgreSQL-specific trigger and constraint behavior

Do not silently fall back to SQLite for PostgreSQL-required integration tests.

When PostgreSQL semantics are part of the Acceptance Criteria, PostgreSQL evidence is required.

### Unit Tests

SQLite may be used for fast tests that do not depend on PostgreSQL semantics, such as:

- pure schema validation
- deterministic helpers
- canonical hashing
- rule mapping
- bounded payload validation
- isolated unit tests

A SQLite test must not be presented as evidence for a PostgreSQL-specific contract.

---

## Testing

During implementation:

- Run the smallest relevant test set first.
- Prefer tests identified from the affected production path and Code Review Graph blast radius.
- Fix relevant test failures before declaring the task complete.
- Do not run the entire backend test suite after every small change.
- Add tests only for behavior required by the current task or necessary regression protection.
- Do not create redundant tests that prove an existing contract without adding meaningful coverage.
- Prefer existing fixtures/helpers over duplicating test infrastructure.

When an LG milestone is complete:

1. Run the LG-specific backend tests.
2. Run PostgreSQL integration tests when persistence/checkpoint/concurrency behavior changed.
3. Run the frontend production build if frontend code changed.
4. Run the relevant Playwright E2E test if the user flow changed.
5. Run focused regression tests for affected existing production paths.

Do not claim completion when required tests are failing.

Do not treat a test that mocks the production executor as proof that the production executor works.

For integration acceptance, use the real production path and mock only genuine external boundaries when appropriate.

Examples of acceptable fake boundaries:

- deterministic fake image provider
- external paid provider
- external marketplace network boundary

Do not fake:

- production orchestration
- persistence
- Quality Bar
- promotion authority
- checkpoint/recovery behavior

when those are the behavior under test.

---

## Golden and Regression Tests

When a task uses Golden baselines:

- Golden updates must be explicit.
- Normal test execution must never silently rewrite Golden files.
- Normalize nondeterministic values before comparison.
- Preserve meaningful ordering where order is part of the contract.
- Prefer semantic diffs over opaque hash-only failures.
- Do not update a Golden baseline merely to make a failing test pass.
- Treat an unexpected Golden difference as a potential regression until explained.
- Prefer existing persisted fixtures over building parallel fake scenario implementations.

External-provider behavior should use deterministic fake providers for reproducible Golden tests unless a real-provider smoke is explicitly required.

Golden baselines should not contain unnecessary:

- timestamps
- random UUIDs
- temporary paths
- raw provider payloads
- image bytes
- full internal checkpoint bodies
- full QA report bodies

unless the source-of-truth explicitly requires them.

---

## Frontend

When frontend code changes:

- Preserve the existing Sellform design system.
- Do not redesign unrelated screens.
- Prefer existing components and native browser capabilities before adding dependencies.
- Do not expose internal architecture terminology to end users.
- Keep user-facing states focused on the current task, result, and next action.
- Run `npm run build`.
- Use Playwright for important user-flow verification.

Do not expose user-facing terms such as:

- LangGraph
- routing_code
- checkpoint
- evaluator bundle
- internal rule IDs
- internal canonical hashes
- internal version class names

unless explicitly required for a developer-only interface.

When design-oriented skills are available, they may improve presentation but must not alter backend contracts or expand the task scope.

Use design-specific skills only when the current task actually contains frontend/UI design work.

---

## Security and Trust Boundaries

Never reduce security or trust-boundary validation to save code, tokens, or implementation time.

For relevant changes, verify:

- authentication
- workspace isolation
- project isolation
- run ownership
- persisted current-version authority
- stale-reference rejection
- cross-scope injection
- immutable lineage
- provenance
- channel authority
- idempotency
- replay safety
- direct API bypasses

Frontend disabling is not a security boundary.

Backend authorization and persisted source-of-truth validation must enforce protected operations.

Do not accept caller-supplied state as authority when persisted server-side state exists.

Examples:

- PASS
- current version
- promotion readiness
- channel authority
- ownership
- approval state

must come from persisted trusted state when required by the current architecture.

---

## Review

After implementation, review the current Git diff against the current task.

Use Code Review Graph to identify:

- affected callers
- affected dependents
- regression-sensitive paths
- directly related tests
- unexpected blast-radius expansion

Then verify findings against the actual production code.

Focus on:

- requirement violations
- logic bugs
- regression risk
- missing tests
- architecture violations
- authorization or trust-boundary bypasses
- unnecessary abstractions or duplicate code
- stale/current-version bypasses
- persistence and recovery regressions

Apply Ponytail-style review to identify code that can be removed or replaced by existing functionality, but never recommend removing required validation, safety, or Acceptance Criteria.

Do not create code-review Markdown documents unless explicitly requested.

Do not spend time on style-only suggestions during implementation review.

Report review findings as:

- BLOCKER
- MAJOR
- MINOR
- PASS

For final task review, distinguish clearly between:

- correctness/security defects
- missing Acceptance Criteria
- non-blocking operational notes

---

## Git

- Keep each task independently reviewable when practical.
- Keep diffs as small as practical without sacrificing correctness.
- Do not modify or delete unrelated user changes.
- Do not commit generated caches, temporary files, test artifacts, secrets, or local environment files.
- Do not create commits unless explicitly requested.
- Before completion, inspect the current diff for accidental unrelated changes.
- Run `git diff --check`.
- Do not commit `.code-review-graph/` local index data.
- Do not commit local PostgreSQL data, local fixture DBs, Playwright downloads, or temporary Golden-generation files unless the task explicitly requires tracked Golden baselines.

---

## Documentation

Do not create new planning, review, verification, or test-report documents unless they are required by the current LG specification or explicitly requested.

Update documentation only when the implementation changes information that developers need to retain.

Architecture decisions that materially affect future development may be documented in `docs/decisions/`.

Do not generate documentation merely to summarize work that is already captured by tests, code, or the task report.

---

## Tool Discipline

Tools support implementation; they do not define requirements.

Use tools only when they materially improve correctness, context efficiency, or verification.

### Code Review Graph

Code Review Graph is installed and indexed for Sellform.

Use it before broad repository inspection for:

- locating relevant code
- dependency/caller analysis
- blast-radius analysis
- identifying relevant tests
- avoiding unnecessary repository-wide reads
- narrowing implementation scope
- narrowing review scope

After meaningful source changes, run an incremental graph update when practical:

`code-review-graph update`

Do not rebuild the full graph unless necessary.

Do not treat graph output as source of truth.

Verify security-sensitive, persistence-sensitive, authorization-sensitive, and externally exposed paths against the actual production code.

If CRG output is stale, incomplete, or conflicts with actual source code, trust the current source code and specification.

### Ponytail

Apply Ponytail-style principles on every implementation task even if Ponytail lifecycle hooks are not active in the current Codex session.

Use these principles to:

- avoid unnecessary code
- reuse existing services/helpers
- avoid speculative abstractions
- prefer native/platform functionality
- avoid unnecessary dependencies
- reduce duplicate implementation
- stop at the smallest correct solution that satisfies the current LG Acceptance Criteria

If the Ponytail plugin or skills are available, they may be used as an additional aid.

Do not depend on plugin activation for these rules to apply.

Never use Ponytail or code-size reduction as justification for removing or weakening required:

- validation
- authorization
- immutable lineage
- provenance
- idempotency
- transaction safety
- checkpoint/recovery
- security
- cost approval
- provider boundaries
- required tests
- Acceptance Criteria

### Context7

Use only when current external library/API behavior must be verified.

Do not query documentation unnecessarily for standard language behavior or repository-local contracts.

### Playwright

Use for actual user-flow verification when required.

Do not replace required actual E2E verification with route mocks.

When actual user flow is part of the Acceptance Criteria, prefer:

Playwright
→ actual frontend
→ actual backend
→ actual local PostgreSQL/test persistence

Mock only genuine external network/provider boundaries when appropriate.

### PostgreSQL / Supabase

Use PostgreSQL for persistence-sensitive integration behavior.

Keep production Supabase mutation separate from local/test verification unless explicitly authorized.

Local Docker PostgreSQL can be used to validate:

- migrations
- constraints
- triggers
- locks
- concurrency
- checkpoints
- promotion/export persistence

Production Supabase deployment remains a separate operational gate.

---

## Resource Efficiency

Optimize for the smallest correct use of code, context, tools, and test execution.

Before broad inspection:

1. Use Code Review Graph.
2. Read only relevant source-of-truth documents.
3. Inspect only the smallest required production path.
4. Reuse existing tests and fixtures.
5. Expand scope only when evidence requires it.

Before implementation:

1. Apply Ponytail-style reuse/minimality.
2. Search for existing ownership of the behavior.
3. Avoid new abstractions unless necessary.
4. Prefer deterministic code over new LLM calls.

Before testing:

1. Run directly affected tests first.
2. Run focused regressions next.
3. Run expensive integration/E2E only when the task requires them.
4. Do not repeatedly run identical expensive tests without a relevant code change.

Token or time reduction must never weaken correctness, security, or Acceptance Criteria.

---

## Definition of Done

A task is complete only when:

- the requested LG requirement is implemented
- the current LG source-of-truth Acceptance Criteria are satisfied
- relevant tests pass
- PostgreSQL-specific tests pass when PostgreSQL semantics are relevant
- frontend build passes when applicable
- relevant E2E passes when applicable
- current diff contains no known BLOCKER
- no unresolved MAJOR prevents the task from satisfying its contract
- no unnecessary legacy path was introduced
- no duplicate implementation was introduced
- no required validation/security/recovery behavior was weakened
- no unrelated scope was added
- required production-path evidence exists for integration-critical behavior

`PASS_WITH_NOTES` may close a task only when the remaining notes are non-blocking operational or maintenance items and the task's correctness and security contracts are satisfied.

A task must remain `FIX_REQUIRED` or `IN_PROGRESS` when required production-path evidence is missing, even if isolated unit tests pass.