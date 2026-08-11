import { expect, test } from "@playwright/test";

const projectId = "lg4-review-project";
const runId = "lg4-review-run";

const reviewState = () => ({
  run_id: runId,
  thread_id: runId,
  status: "awaiting_review",
  current_stage: "evidence_review",
  checkpoint_id: "checkpoint-review",
  values: {
    review: {
      pending: {
        schema_version: "lg4-v1",
        review_stage: "evidence_review",
        title: "근거 사실 확인",
        description: "확정 사실과 자료 수집 결과를 확인한 뒤 판매 전략을 만듭니다.",
        allowed_decisions: ["approve", "reject"],
      },
    },
    execution: { recoverable: false, last_error: null, errors: [] },
  },
  next_nodes: [],
});

const failedState = () => ({
  run_id: runId,
  thread_id: runId,
  status: "failed",
  current_stage: "visual_planning",
  checkpoint_id: "checkpoint-failed",
  values: {
    review: { pending: null },
    execution: {
      recoverable: true,
      last_error: {
        stage: "visual_planning",
        code: "SAFE_REFERENCE_ASSET_REQUIRED",
        user_message: "AI 비주얼 기획에 사용할 안전한 권리 보유 사진이 없습니다.",
        recovery_action: "upload_safe_reference_asset_and_retry",
        recoverable: true,
      },
    },
  },
  next_nodes: ["visual_planning"],
});

test("LG-4 approval failure is visible and the same run can be retried without a no-op or duplicate click", async ({ page }) => {
  let currentState: ReturnType<typeof reviewState> | ReturnType<typeof failedState> = reviewState();
  let resumeCalls = 0;
  const resumeBodies: Array<unknown> = [];

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, async (route) => {
    const request = route.request();
    if (request.url().endsWith("/resume")) {
      resumeCalls += 1;
      resumeBodies.push(request.postDataJSON());
      if (resumeCalls === 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        currentState = failedState();
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "LangGraph execution failed. Resume the same run after resolving the cause." }),
        });
        return;
      }
      currentState = reviewState();
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentState) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentState) });
  });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  const approve = page.getByRole("button", { name: "확인·다음 단계" });
  await expect(approve).toBeVisible();
  await approve.dblclick();

  const recoveryAlert = page.locator('section[role="alert"]');
  await expect(recoveryAlert).toContainText("다음 단계로 진행하지 못했습니다");
  await expect(recoveryAlert).toContainText("SAFE_REFERENCE_ASSET_REQUIRED");
  await expect(page.getByText("LangGraph 판매자 승인을 기다리고 있습니다.")).toBeHidden();
  await expect.poll(() => resumeCalls).toBe(1);
  expect(resumeBodies[0]).toMatchObject({
    thread_id: runId,
    response: { schema_version: "lg4-v1", review_stage: "evidence_review", decision: "approve" },
  });

  await page.getByRole("button", { name: "원인 해결 후 같은 실행 재시도" }).click();
  await expect(page.getByText("LangGraph 승인 대기 · evidence_review")).toBeVisible();
  await expect.poll(() => resumeCalls).toBe(2);
  expect(resumeBodies[1]).toBeNull();
});

test("generation pending shows an approved state and does not offer duplicate storyboard approval", async ({ page }) => {
  const generationPendingState = {
    run_id: runId,
    thread_id: runId,
    status: "awaiting_review",
    current_stage: "generation_pending",
    checkpoint_id: "checkpoint-generation-pending",
    values: {
      review: {
        pending: {
          schema_version: "lg4-v1",
          review_stage: "generation_pending",
          title: "이미지 생성 준비 대기",
          description: "LG-5 이미지 생성 연결 전입니다.",
          allowed_decisions: ["defer"],
        },
      },
      execution: { recoverable: false, last_error: null, errors: [] },
    },
    next_nodes: [],
  };
  const draft = {
    storyboard_version: 1,
    status: "approved",
    revision: 1,
    estimated_cost: 0,
    selected_candidate_key: "balanced",
    revision_history: [{ revision: 1, action: "approved", selected_candidate_key: "balanced" }],
    recommendations: [],
    cards: [{
      id: "card-1",
      type: "hero",
      label: "대표 상품 소개",
      title: "판매자 확인 정보 기준으로 안내합니다.",
      bullets: ["승인된 상품 정보를 한눈에 정리했습니다."],
      source_fact_ids: [],
      visual_strategy: "image_overlay",
      is_enabled: true,
      sort_order: 0,
      image_requirement: "asset_ready",
    }],
  };

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(draft) }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(generationPendingState) }));

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByText("LangGraph 승인 대기 · generation_pending")).toBeVisible();
  await expect(page.getByText("스토리보드 승인 완료 · 이미지 생성 대기")).toBeVisible();
  await expect(page.getByRole("button", { name: "스토리보드 승인", exact: true })).toHaveCount(0);
  await expect(page.getByText("현재 실행은 스토리보드 승인 대기 상태가 아닙니다.")).toHaveCount(0);
});

test("a stale run URL recovers the project's current review run and restores the approval action", async ({ page }) => {
  const staleRunId = "stale-review-run";

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${staleRunId}`, (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "AgentRun not found" }) }));
  await page.route(`**/api/v1/graph-runs/projects/${projectId}/review`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reviewState()) }));

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${staleRunId}`);

  await expect(page.getByRole("button", { name: "확인·다음 단계" })).toBeVisible();
  await expect(page.getByText("만료된 실행 주소를 이 프로젝트의 현재 승인 대기 실행으로 복구했습니다.")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`runId=${runId}`));
});

test("a stale run URL with no recoverable run shows an explicit recovery error instead of a false waiting banner", async ({ page }) => {
  const staleRunId = "missing-review-run";

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${staleRunId}`, (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "AgentRun not found" }) }));
  await page.route(`**/api/v1/graph-runs/projects/${projectId}/review`, (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "No pending or recoverable graph run" }) }));

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${staleRunId}`);

  await expect(page.getByText("승인할 실행을 찾지 못했습니다")).toBeVisible();
  await expect(page.getByRole("button", { name: "현재 실행 다시 찾기" })).toBeVisible();
  await expect(page.getByText("LangGraph 판매자 승인을 기다리고 있습니다.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "확인·다음 단계" })).toHaveCount(0);
});
