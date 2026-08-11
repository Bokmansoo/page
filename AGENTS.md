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

Before adding a new service, adapter, abstraction, or LLM call, check whether the existing architecture can support the requirement.

---

## LLM Rules

- Use the existing centralized provider/router architecture for text LLM calls.
- Do not hard-code provider models inside feature services.
- Do not add an LLM call when deterministic code can reliably perform the operation.
- Avoid repeatedly passing large accumulated state when a smaller structured payload is sufficient.

---

## Testing

During implementation:

- Run the smallest relevant test set first.
- Fix relevant test failures before declaring the task complete.
- Do not run the entire backend test suite after every small change.

When an LG milestone is complete:

1. Run the LG-specific backend tests.
2. Run the frontend production build if frontend code changed.
3. Run the relevant Playwright E2E test if the user flow changed.

Do not claim completion when required tests are failing.

---

## Frontend

When frontend code changes:

- Preserve the existing Sellform design system.
- Do not redesign unrelated screens.
- Run `npm run build`.
- Use Playwright for important user-flow verification.

---

## Review

After implementation, review the current Git diff against the current task.

Focus on:

- requirement violations
- logic bugs
- regression risk
- missing tests
- architecture violations

Do not create code-review Markdown documents unless explicitly requested.

Do not spend time on style-only suggestions during implementation review.

Report review findings as:

- BLOCKER
- MAJOR
- MINOR
- PASS

---

## Git

- Keep each task independently reviewable when practical.
- Do not modify or delete unrelated user changes.
- Do not commit generated caches, temporary files, test artifacts, secrets, or local environment files.
- Do not create commits unless explicitly requested.

---

## Documentation

Do not create new planning, review, verification, or test-report documents unless they are required by the current LG specification or explicitly requested.

Update documentation only when the implementation changes information that developers need to retain.

Architecture decisions that materially affect future development may be documented in `docs/decisions/`.

---

## Definition of Done

A task is complete only when:

- the requested LG requirement is implemented
- relevant tests pass
- frontend build passes when applicable
- relevant E2E passes when applicable
- current diff contains no known BLOCKER
- no unnecessary legacy path or duplicate implementation was introduced