import { expect, test } from "@playwright/test";

const projectId = "lg5r-image-project";
const runId = "lg5r-image-run";
const costPlan = {
  cost_plan_hash: "a".repeat(64),
  provider: "fake_provider",
  model: "fake-image-lg5r-v1",
  scene_count: 2,
  scenes: [
    { scene_id: "hero", title: "대표 상품", role: "representative_product", model: "fake-image-lg5r-v1", output_size: "1024x1024", estimated_cost: 1 },
    { scene_id: "usage", title: "사용 장면", role: "lifestyle_scene", model: "fake-image-lg5r-v1", output_size: "1024x1024", estimated_cost: 1 },
  ],
  total_estimated_cost: 2,
  currency: "credit",
  status: "pending",
};

const view = (stage: "generation_pending" | "provider_wait" | "image_review", jobs: Array<Record<string, unknown>> = []) => ({
  run_id: runId,
  thread_id: runId,
  status: "awaiting_review",
  current_stage: stage,
  checkpoint_id: `checkpoint-${stage}`,
  values: {
    review: {
      pending: {
        schema_version: "lg5-v1",
        review_stage: stage,
        title: stage === "generation_pending" ? "이미지 생성 비용 확인" : stage === "provider_wait" ? "이미지 생성 진행 중" : "생성 이미지 검수",
        description: "같은 LangGraph 실행에서 상태를 복구합니다.",
        seller_guidance: {
          cause_ko: stage === "generation_pending" ? "이미지 생성 전에 비용 확인이 필요합니다." : stage === "provider_wait" ? "이미지 생성 결과를 확인하고 있습니다." : "생성 이미지를 확인해야 합니다.",
          action_ko: stage === "generation_pending" ? "예상 비용을 확인한 뒤 생성을 승인하세요." : stage === "provider_wait" ? "잠시 후 작업 상태를 새로고침하세요." : "장면별로 승인, 거절 또는 다시 생성을 선택하세요.",
          action_type: stage === "generation_pending" ? "approve_cost" : stage === "provider_wait" ? "refresh_status" : "review",
          retryable: false,
          review_required: true,
        },
        allowed_decisions: stage === "generation_pending" ? ["approve", "defer"] : stage === "provider_wait" ? ["refresh"] : ["approve", "reject", "regenerate", "upload"],
        context: { generation: { cost_plan: costPlan, jobs } },
      },
    },
    generation: {
      cost_plan: costPlan,
      jobs,
      pending_count: stage === "provider_wait" ? 2 : 0,
      review_count: jobs.filter((job) => job.status === "needs_review").length,
      required_scene_count: 2,
      approved_count: jobs.filter((job) => job.status === "approved").length,
      failed_job_ids: [],
    },
    execution: {
      recoverable: false,
      last_error: null,
      errors: [],
      delay_context: stage === "provider_wait" ? {
        current_stage: "first_usable_draft",
        current_stage_ko: "이미지 생성 결과를 확인하고 있습니다.",
        delay_cause: "provider_execution",
        delay_cause_ko: "이미지를 생성하고 있습니다.",
        eta_status: "estimated",
        eta_range_seconds: { min: 30, max: 60 },
        updated_at: "2026-08-26T00:00:00Z",
        seller_guidance: { cause_ko: "이미지를 생성하고 있습니다.", action_ko: "완료되면 다음 단계가 자동으로 진행됩니다.", action_type: "refresh_status", retryable: false, review_required: false },
      } : null,
    },
  },
  next_nodes: [],
});

const reviewJobs = [
  {
    job_id: "job-hero", scene_id: "hero", role: "representative_product", status: "needs_review", output_asset_id: "generated-hero", generation_attempt: 1, outbox_status: "completed", estimated_cost: 1,
    source_asset_ids: ["source-hero"],
    validation: { schema_version: "lg9-image-validation-v1", status: "needs_review", checks: { identity: "passed", ocr: "passed", crop: "needs_review", resolution: "needs_review", safety: "passed", rights: "passed" }, warnings: ["LOW_RESOLUTION"] },
  },
  { job_id: "job-usage", scene_id: "usage", role: "lifestyle_scene", status: "needs_review", output_asset_id: "generated-usage", generation_attempt: 1, outbox_status: "completed", estimated_cost: 1 },
];

test("LG-9 fake provider restores cost, worker wait and per-scene review across refresh without duplicate requests", async ({ page }) => {
  let state: Record<string, unknown> = view("generation_pending");
  let costApprovalSubmitted = false;
  let queuedGetCount = 0;
  let providerGetCount = 0;
  let assetRole = "unknown";
  const classificationBodies: Array<Record<string, unknown>> = [];
  const resumeBodies: Array<Record<string, unknown>> = [];

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify([{ id: "seller-upload", filename: "내상품.jpg", source_type: "uploaded", usage_status: "seller_owned", mime_type: "image/jpeg", asset_role: assetRole }]),
  }));
  await page.route(`**/api/v1/projects/${projectId}/assets/seller-upload/classification`, async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    classificationBodies.push(body);
    assetRole = String(body.asset_role || "unknown");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "seller-upload", filename: "내상품.jpg", source_type: "uploaded", usage_status: "seller_owned", mime_type: "image/jpeg", asset_role: assetRole }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/v1/files/assets/*", (route) => route.fulfill({
    status: 200,
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#94a3b8"/></svg>',
  }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, async (route) => {
    const request = route.request();
    if (request.url().endsWith("/resume")) {
      const body = request.postDataJSON() as Record<string, unknown>;
      resumeBodies.push(body);
      const response = body.response as { decision?: string; job_id?: string; asset_id?: string };
      if (response.decision === "approve" && response.job_id === "job-hero") {
        state = view("image_review", [{ ...reviewJobs[0], status: "approved" }, reviewJobs[1]]);
      } else if (response.decision === "upload" && response.job_id === "job-usage" && response.asset_id === "seller-upload") {
        const completed = view("image_review", reviewJobs.map((job) => ({ ...job, status: "approved" })));
        completed.status = "completed";
        completed.current_stage = "finalize_run";
        completed.values.review.pending = null as never;
        state = completed;
      } else if (response.decision === "approve") {
        // The approval response can arrive before the worker publishes its
        // provider-wait checkpoint. The panel must continue polling this
        // queued state without requiring a browser refresh.
        costApprovalSubmitted = true;
        state = view("generation_pending");
      }
    } else if (costApprovalSubmitted && (state as { current_stage?: string }).current_stage === "generation_pending") {
      queuedGetCount += 1;
      if (queuedGetCount >= 2) state = view("provider_wait");
    } else if ((state as { current_stage?: string }).current_stage === "provider_wait") {
      providerGetCount += 1;
      if (providerGetCount >= 2) state = view("image_review", reviewJobs);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(state) });
  });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await page.getByTestId("asset-role-seller-upload").selectOption("product_main");
  await expect(page.getByTestId("asset-role-seller-upload")).toHaveValue("product_main");
  expect(classificationBodies).toEqual([{ asset_role: "product_main" }]);
  await page.reload();
  await expect(page.getByTestId("asset-role-seller-upload")).toHaveValue("product_main");
  await expect(page.getByTestId("lg5r-cost-plan")).toContainText("2개 장면");
  await expect(page.getByTestId("lg5r-cost-plan")).toContainText("총 예상 비용 2 credit");
  await page.getByRole("button", { name: "비용 승인 후 이미지 생성" }).dblclick();
  await expect(page.getByRole("heading", { name: "이미지 생성 결과를 확인하고 있습니다." })).toBeVisible();
  await expect(page.getByTestId("seller-delay-context")).toContainText("예상 남은 시간 30~60초");
  await expect(page.getByTestId("lg5r-scene-hero")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toBeVisible();
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toHaveAttribute("src", /\/api\/v1\/files\/assets\/generated-hero$/);
  await expect(page.getByTestId("lg9-scene-comparison-hero")).toBeVisible();
  await expect(page.getByTestId("lg9-reference-hero-source-hero")).toHaveAttribute("src", /\/api\/v1\/files\/assets\/source-hero$/);
  await expect(page.getByTestId("lg9-validation-hero")).toContainText("자동 검사 보고서 · 판매자 확인 필요");
  await expect(page.getByTestId("lg9-validation-hero")).toContainText("해상도 · 확인 필요");
  expect(resumeBodies).toHaveLength(1);
  expect(resumeBodies[0]).toMatchObject({
    thread_id: runId,
    response: { schema_version: "lg5-v1", review_stage: "generation_pending", decision: "approve", cost_plan_hash: costPlan.cost_plan_hash },
  });

  await page.reload();
  await expect(page.getByTestId("lg5r-scene-hero")).toBeVisible();
  await page.getByTestId("lg5r-scene-hero").getByRole("button", { name: "이 장면 승인" }).click();
  await expect(page.getByText("1/2개 필수 장면 승인")).toBeVisible();
  await expect(page.getByTestId("lg5r-scene-usage").getByRole("button", { name: "이 장면 승인" })).toBeVisible();

  await page.getByLabel("job-usage 직접 업로드 사진").selectOption("seller-upload");
  await page.getByTestId("lg5r-scene-usage").getByRole("button", { name: "선택 사진 연결" }).click();
  expect(resumeBodies).toHaveLength(3);
  expect(resumeBodies[1]).toMatchObject({ response: { decision: "approve", job_id: "job-hero" } });
  expect(resumeBodies[2]).toMatchObject({ response: { decision: "upload", job_id: "job-usage", asset_id: "seller-upload", seller_attested: true } });
  await expect(page.getByTestId("lg5r-completed-gallery")).toBeVisible();
  await expect(page.getByTestId("lg5r-completed-gallery").getByRole("img")).toHaveCount(2);
});

test("LG-9 fake provider regenerates only the rejected scene through a new cost approval", async ({ page }) => {
  const rejectedHero = { ...reviewJobs[0], status: "rejected" };
  const regeneratedHero = {
    ...reviewJobs[0],
    job_id: "job-hero-retry",
    output_asset_id: "generated-hero-retry",
    generation_attempt: 2,
  };
  const approvedRegeneratedHero = { ...regeneratedHero, status: "approved" };
  let state: Record<string, unknown> = view("image_review", reviewJobs);
  const resumeBodies: Array<Record<string, unknown>> = [];

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, async (route) => {
    if (route.request().url().endsWith("/resume")) {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      resumeBodies.push(body);
      const response = body.response as { decision?: string; job_id?: string };
      if (response.decision === "reject" && response.job_id === "job-hero") {
        state = view("image_review", [rejectedHero, reviewJobs[1]]);
      } else if (response.decision === "regenerate" && response.job_id === "job-hero") {
        state = view("generation_pending", [rejectedHero, reviewJobs[1]]);
      } else if (response.decision === "approve" && response.job_id === "job-hero-retry") {
        state = view("image_review", [approvedRegeneratedHero, reviewJobs[1]]);
      } else if (response.decision === "approve" && response.job_id === "job-usage") {
        const completed = view("image_review", [approvedRegeneratedHero, { ...reviewJobs[1], status: "approved" }]);
        completed.status = "completed";
        completed.current_stage = "finalize_run";
        completed.values.review.pending = null as never;
        Object.assign(completed.values.generation, {
          all_required_scenes_approved: true,
          approved_asset_manifest: {
            schema_version: "lg9-approved-asset-manifest-v1",
            run_id: runId,
            project_id: projectId,
            assets: [
              { scene_id: "hero", asset_id: "generated-hero-retry", asset_content_hash: "a".repeat(64) },
              { scene_id: "usage", asset_id: "generated-usage", asset_content_hash: "b".repeat(64) },
            ],
          },
        });
        state = completed;
      } else if (response.decision === "approve") {
        state = view("provider_wait", [rejectedHero, reviewJobs[1]]);
      }
    } else if ((state as { current_stage?: string }).current_stage === "provider_wait") {
      state = view("image_review", [regeneratedHero, reviewJobs[1]]);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(state) });
  });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await page.getByTestId("lg5r-scene-hero").getByRole("button", { name: "거절" }).click();
  await expect(page.getByTestId("lg5r-scene-hero").getByRole("button", { name: "이 장면 재생성" })).toBeVisible();
  await page.getByTestId("lg5r-scene-hero").getByRole("button", { name: "이 장면 재생성" }).click();
  await expect(page.getByTestId("lg5r-cost-plan")).toBeVisible();
  await page.getByRole("button", { name: "비용 승인 후 이미지 생성" }).click();
  await expect(page.getByTestId("lg5r-scene-hero")).toContainText("생성 시도 2", { timeout: 8_000 });
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toHaveAttribute("src", /generated-hero-retry$/);
  await expect(page.getByTestId("lg5r-scene-preview-usage")).toHaveAttribute("src", /generated-usage$/);
  await page.getByTestId("lg5r-scene-hero").getByRole("button", { name: "이 장면 승인" }).click();
  await expect(page.getByTestId("lg5r-scene-usage").getByRole("button", { name: "이 장면 승인" })).toBeVisible();
  await page.getByTestId("lg5r-scene-usage").getByRole("button", { name: "이 장면 승인" }).click();
  await expect(page.getByTestId("lg5r-completed-gallery")).toBeVisible();
  expect(state).toMatchObject({
    status: "completed",
    values: { generation: { all_required_scenes_approved: true, approved_asset_manifest: {
      schema_version: "lg9-approved-asset-manifest-v1",
      assets: [
        { scene_id: "hero", asset_id: "generated-hero-retry", asset_content_hash: "a".repeat(64) },
        { scene_id: "usage", asset_id: "generated-usage", asset_content_hash: "b".repeat(64) },
      ],
    } } },
  });
  expect(resumeBodies).toHaveLength(5);
  expect(resumeBodies[0]).toMatchObject({ response: { decision: "reject", job_id: "job-hero" } });
  expect(resumeBodies[1]).toMatchObject({ response: { decision: "regenerate", job_id: "job-hero" } });
  expect(resumeBodies[2]).toMatchObject({ response: { decision: "approve", cost_plan_hash: costPlan.cost_plan_hash } });
  expect(resumeBodies[3]).toMatchObject({ response: { decision: "approve", job_id: "job-hero-retry" } });
  expect(resumeBodies[4]).toMatchObject({ response: { decision: "approve", job_id: "job-usage" } });
});

test("LG-9 provider polling keeps the current review content visible", async ({ page }) => {
  let delayBackgroundPoll = false;

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route("**/api/v1/files/assets/*", (route) => route.fulfill({
    status: 200,
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>',
  }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, async (route) => {
    if (!route.request().url().endsWith("/resume") && delayBackgroundPoll) {
      await new Promise((resolve) => setTimeout(resolve, 800));
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(view("provider_wait", reviewJobs)) });
  });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toBeVisible();
  delayBackgroundPoll = true;

  // The next 1.5s poll is intentionally held open. The preview must remain
  // mounted instead of being replaced by a full-panel loading placeholder.
  await page.waitForTimeout(1_700);
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toBeVisible();
});

test("LG-5R renders every actionable provider and quality error separately", async ({ page }) => {
  const failures = [
    ["API_KEY_MISSING", "이미지 생성 설정을 확인해야 합니다."],
    ["BALANCE_OR_LIMIT", "이미지 생성 사용 한도를 확인해야 합니다."],
    ["PROVIDER_TIMEOUT", "이미지 생성 응답이 늦어 완료하지 못했습니다."],
    ["PROVIDER_SAFETY", "이미지 요청이 안전 기준으로 처리되지 않았습니다."],
    ["IDENTITY_MISMATCH", "생성 이미지가 상품 사진과 충분히 일치하지 않습니다."],
    ["OCR_CONTAMINATION", "생성 이미지에서 확인이 필요한 문구가 감지되었습니다."],
    ["RIGHTS_BLOCKED", "사용 권한을 확인할 수 없는 이미지가 포함되었습니다."],
  ];
  const failedJobs = failures.map(([error_code, userMessage], index) => ({
    job_id: `failed-${index}`,
    scene_id: `failed-scene-${index}`,
    role: "generated_image",
    status: "failed",
    error_code,
    seller_guidance: { cause_ko: userMessage, action_ko: "안내에 따라 장면을 다시 생성하세요.", action_type: "retry", retryable: true, review_required: false },
    generation_attempt: 1,
    outbox_status: "dead_letter",
    ...(error_code === "IDENTITY_MISMATCH" ? {
      validation: { schema_version: "lg9-image-validation-v1", status: "blocked", checks: { identity: "blocked", ocr: "not_run", crop: "not_run", resolution: "not_run", safety: "not_run", rights: "not_run" } },
    } : {}),
  }));

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(view("image_review", failedJobs)),
  }));

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  for (const [, userMessage] of failures) {
    await expect(page.getByText(userMessage, { exact: false })).toBeVisible();
  }
  await expect(page.getByTestId("lg9-validation-failed-scene-4")).toContainText("자동 검사 보고서 · 차단");
  await expect(page.getByTestId("lg9-validation-failed-scene-4")).toContainText("상품 정체성 · 차단");
});

test("LG-5R refreshes rights-owned upload choices after a graph resume", async ({ page }) => {
  let assetsAvailable = false;
  const blockedJob = {
    job_id: "job-usage",
    scene_id: "usage",
    role: "lifestyle_scene",
    status: "blocked",
    error_code: "IDENTITY_REFERENCE_INSUFFICIENT",
    generation_attempt: 1,
    outbox_status: "completed",
    estimated_cost: 1,
  };
  const state = view("image_review", [blockedJob]);

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(assetsAvailable ? [{
      id: "new-seller-upload",
      filename: "new-product.png",
      source_type: "uploaded",
      usage_status: "seller_owned",
      mime_type: "image/png",
      asset_role: "product_main",
    }] : []),
  }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, async (route) => {
    if (route.request().url().endsWith("/resume")) assetsAvailable = true;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(state) });
  });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  const scene = page.getByTestId("lg5r-scene-usage");
  const selector = scene.locator("select");
  await expect(selector.locator("option")).toHaveCount(1);

  await scene.locator("button").first().click();

  await expect(selector.locator("option")).toHaveCount(2);
  await expect(selector.locator('option[value="new-seller-upload"]')).toHaveText("new-product.png");
});
