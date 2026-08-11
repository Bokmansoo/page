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
    execution: { recoverable: false, last_error: null, errors: [] },
  },
  next_nodes: [],
});

const reviewJobs = [
  { job_id: "job-hero", scene_id: "hero", role: "representative_product", status: "needs_review", output_asset_id: "generated-hero", generation_attempt: 1, outbox_status: "completed", estimated_cost: 1 },
  { job_id: "job-usage", scene_id: "usage", role: "lifestyle_scene", status: "needs_review", output_asset_id: "generated-usage", generation_attempt: 1, outbox_status: "completed", estimated_cost: 1 },
];

test("LG-5R restores cost, worker wait and per-scene review across refresh without duplicate requests", async ({ page }) => {
  let state: Record<string, unknown> = view("generation_pending");
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
        state = view("provider_wait");
      }
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
  await expect(page.getByText("이미지 생성 진행 중")).toBeVisible();
  await expect(page.getByTestId("lg5r-scene-hero")).toBeVisible({ timeout: 8_000 });
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toBeVisible();
  await expect(page.getByTestId("lg5r-scene-preview-hero")).toHaveAttribute("src", /\/api\/v1\/files\/assets\/generated-hero$/);
  expect(resumeBodies).toHaveLength(1);
  expect(resumeBodies[0]).toMatchObject({
    thread_id: runId,
    response: { schema_version: "lg5-v1", review_stage: "generation_pending", decision: "approve", cost_plan_hash: costPlan.cost_plan_hash },
  });

  await page.reload();
  await expect(page.getByTestId("lg5r-scene-hero")).toBeVisible();
  await page.getByTestId("lg5r-scene-hero").getByRole("button", { name: "이 장면 승인" }).click();
  await expect(page.getByText("1/2개 필수 장면 승인")).toBeVisible();
  await expect(page.getByTestId("lg5r-scene-usage")).toContainText("needs_review");

  await page.getByLabel("job-usage 직접 업로드 사진").selectOption("seller-upload");
  await page.getByTestId("lg5r-scene-usage").getByRole("button", { name: "선택 사진 연결" }).click();
  expect(resumeBodies).toHaveLength(3);
  expect(resumeBodies[1]).toMatchObject({ response: { decision: "approve", job_id: "job-hero" } });
  expect(resumeBodies[2]).toMatchObject({ response: { decision: "upload", job_id: "job-usage", asset_id: "seller-upload", seller_attested: true } });
  await expect(page.getByTestId("lg5r-completed-gallery")).toBeVisible();
  await expect(page.getByTestId("lg5r-completed-gallery").getByRole("img")).toHaveCount(2);
});

test("LG-5R renders every actionable provider and quality error separately", async ({ page }) => {
  const failures = [
    ["API_KEY_MISSING", "API 키가 없습니다"],
    ["BALANCE_OR_LIMIT", "API 잔액 또는 사용 한도"],
    ["PROVIDER_TIMEOUT", "제공자 응답 시간이 초과"],
    ["PROVIDER_SAFETY", "제공자 안전 정책"],
    ["IDENTITY_MISMATCH", "상품 외형이 기준 사진과 일치하지 않습니다"],
    ["OCR_CONTAMINATION", "글자·로고·워터마크 오염"],
    ["RIGHTS_BLOCKED", "이미지 사용 권리"],
  ];
  const failedJobs = failures.map(([error_code], index) => ({
    job_id: `failed-${index}`,
    scene_id: `failed-scene-${index}`,
    role: "generated_image",
    status: "failed",
    error_code,
    generation_attempt: 1,
    outbox_status: "dead_letter",
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
