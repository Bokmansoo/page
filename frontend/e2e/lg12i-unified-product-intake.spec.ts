import { expect, Page, test } from "@playwright/test";

type Mode = "manual" | "owned_product_url" | "photo_only";
type Channel = "smartstore" | "coupang";

const projectId = "lg12i-ui-project";
const runId = "lg12i-ui-run";
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLz6QAAAABJRU5ErkJggg==", "base64");

function state(mode: Mode, channels: Channel[], stage = "seller_confirmation_required", generationMode: "quick" | "expert" = "quick", cycle = 1) {
  const plan = {
    confirmation_required: stage !== "master_ready",
    confirmation_cycle: cycle,
    resume_request_hash: "a".repeat(64),
    clarifications: stage === "master_ready" ? [] : [{
      clarification_id: "clarification-material",
      field_id: "material",
      label: "소재를 확인해 주세요",
      observations: [{ id: "observation-steel", value: "steel" }],
    }],
  };
  return {
    run_id: runId, thread_id: runId, status: stage === "master_ready" ? "completed" : "awaiting_review",
    current_stage: stage,
    values: {
      intake: {
        envelope: { input_mode: mode, requested_generation_mode: generationMode, target_channels: channels },
        seller_confirmation: plan,
        ...(stage === "master_ready" ? {
          creative_brief: { brief_version: { id: "brief-1", version: 1, hash: "b".repeat(64) } },
          commerce_creative_master: { master_version: { id: "master-1", version: 1, canonical_hash: "c".repeat(64) } },
        } : {}),
      },
      review: { pending: stage === "master_ready" ? null : { schema_version: "lg12i-v1", review_stage: "seller_confirmation", context: { seller_confirmation: plan } } },
    },
    next_nodes: [],
  };
}

async function installApi(page: Page, mode: Mode, channels: Channel[], options: { generationMode?: "quick" | "expert"; twoCycles?: boolean } = {}) {
  const generationMode = options.generationMode || "quick";
  let current = state(mode, channels, "seller_confirmation_required", generationMode);
  const calls: Array<{ path: string; body: unknown }> = [];
  await page.route("**/api/v1/brands", (route) => route.fulfill({ json: [{ id: "brand-1", name: "테스트 브랜드" }] }));
  await page.route("**/api/v1/projects", async (route) => {
    calls.push({ path: "/projects", body: route.request().postDataJSON() });
    await route.fulfill({ status: 201, json: { id: projectId } });
  });
  await page.route("**/api/v1/projects/" + projectId + "/reference-inputs", async (route) => {
    calls.push({ path: "/reference-inputs", body: route.request().postDataJSON() });
    await route.fulfill({ status: 200, json: { id: "reference-1", version: 1, content_hash: "b".repeat(64) } });
  });
  await page.route("**/api/v1/files/upload", async (route) => {
    calls.push({ path: "/files/upload", body: route.request().postData() });
    await route.fulfill({ status: 201, json: { id: "asset-1", filename: "product.png", source_type: "uploaded", usage_status: "seller_owned", mime_type: "image/png", content_hash: "c".repeat(64) } });
  });
  await page.route("**/api/v1/graph-runs/projects/" + projectId + "/unified-intake", async (route) => {
    calls.push({ path: "/unified-intake", body: route.request().postDataJSON() });
    await route.fulfill({ status: 201, json: current });
  });
  await page.route("**/api/v1/graph-runs/" + runId + "/resume", async (route) => {
    calls.push({ path: "/resume", body: route.request().postDataJSON() });
    current = options.twoCycles && calls.filter((call) => call.path === "/resume").length === 1
      ? state(mode, channels, "seller_confirmation_required", generationMode, 2)
      : state(mode, channels, "master_ready", generationMode);
    await route.fulfill({ json: current });
  });
  await page.route("**/api/v1/graph-runs/" + runId, (route) => route.fulfill({ json: current }));
  return calls;
}

async function prepareMode(page: Page, mode: Mode, channel: Channel) {
  await page.locator('input[name="input-mode"][value="' + mode + '"]').check();
  if (mode === "manual") {
    await page.getByLabel("판매자 입력 사실 후보").fill("무게 150g");
    await page.getByLabel("창작 방향 (선택)").fill("깔끔한 분위기");
  } else if (mode === "owned_product_url") {
    await page.getByLabel("내 상품 URL").fill("https://shop.example.test/products/fan");
  } else {
    await page.getByLabel("상품 사진 1~2장").setInputFiles({ name: "product.png", mimeType: "image/png", buffer: png });
  }
  const smartstore = page.getByLabel("SmartStore");
  const coupang = page.getByLabel("Coupang");
  if (channel === "coupang") {
    await smartstore.uncheck();
    await coupang.check();
  }
}

async function openIntake(page: Page) {
  await page.goto("/workspace/projects/new");
  // Wait for the hydrated, production API-backed brand control before
  // driving client-side mode state. This avoids treating server HTML as a
  // ready interactive intake form.
  await expect(page.getByLabel("브랜드")).toHaveValue("brand-1");
}

for (const mode of ["manual", "owned_product_url", "photo_only"] as const) {
  for (const channel of ["smartstore", "coupang"] as const) {
    test("LG-12I " + mode + " x " + channel + " uses the production unified-intake and public resume contracts", async ({ page }) => {
      const calls = await installApi(page, mode, [channel]);
      const pageErrors: string[] = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await openIntake(page);
      await page.getByLabel("프로젝트 이름").fill("LG-12I 테스트 상품");
      await prepareMode(page, mode, channel);
      await page.getByRole("button", { name: "상품 입력 시작" }).click();
      await expect(page.getByRole("heading", { name: "상품 정보 확인" })).toBeVisible();
      const intake = calls.find((call) => call.path === "/unified-intake");
      expect(intake?.body).toMatchObject({ input_mode: mode, requested_generation_mode: "quick", target_channels: [channel] });
      expect(calls.filter((call) => call.path === "/unified-intake")).toHaveLength(1);
      await page.getByRole("button", { name: "확인 응답 제출" }).click();
      await expect(page.getByText("Commerce Creative Master가 준비되었습니다")).toBeVisible();
      const resume = calls.find((call) => call.path === "/resume");
      expect(resume?.body).toMatchObject({ thread_id: runId, response: { schema_version: "lg12i-v1", review_stage: "seller_confirmation", decision: "submit", confirmation_request_hash: "a".repeat(64) } });
      // Optional confirmation values must be omitted, not serialized as empty
      // identifiers. The live seller-confirmation validator fail-closes on an
      // explicitly supplied empty selected_observation_id.
      expect((resume?.body as { response: { confirmation_answers: Array<Record<string, string>> } }).response.confirmation_answers[0]).not.toHaveProperty("selected_observation_id");
      await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
      await expect(page.getByTestId("lg12i-master-ready")).toContainText("master-1");
      await page.reload();
      await expect(page.getByTestId("lg12i-master-ready")).toContainText("master-1");
      expect(pageErrors).toEqual([]);
    });
  }
}

test("expert manual keeps its distinct identity and both channel set through the production API", async ({ page }) => {
  const calls = await installApi(page, "manual", ["smartstore", "coupang"], { generationMode: "expert" });
  await openIntake(page);
  await page.getByLabel("프로젝트 이름").fill("Expert 수동 입력");
  await page.getByLabel("판매자 입력 사실 후보").fill("소재 스테인리스");
  await page.getByLabel("Expert").check();
  await page.getByLabel("Coupang").check();
  await page.getByRole("button", { name: "상품 입력 시작" }).click();
  await expect(page.getByRole("heading", { name: "상품 정보 확인" })).toBeVisible();
  const intake = calls.find((call) => call.path === "/unified-intake");
  expect(intake?.body).toMatchObject({
    input_mode: "manual",
    requested_generation_mode: "expert",
    target_channels: ["smartstore", "coupang"],
  });
});

test("clarification supports selected observations, corrected values, and a durable second cycle", async ({ page }) => {
  const calls = await installApi(page, "manual", ["smartstore"], { twoCycles: true });
  await openIntake(page);
  await page.getByLabel("프로젝트 이름").fill("확인 주기");
  await page.getByRole("button", { name: "상품 입력 시작" }).click();
  await page.getByLabel("기존 관찰 선택").selectOption("observation-steel");
  await page.getByLabel("수정 값").fill("스테인리스");
  await page.getByLabel("단위").fill("grade 304");
  await page.getByRole("button", { name: "확인 응답 제출" }).click();
  await expect(page.getByText("이번 확인 주기에는 최대 3개 항목만 표시됩니다.")).toBeVisible();
  await page.getByRole("button", { name: "확인 응답 제출" }).click();
  await expect(page.getByText("Commerce Creative Master가 준비되었습니다")).toBeVisible();
  const resumes = calls.filter((call) => call.path === "/resume");
  expect(resumes).toHaveLength(2);
  expect((resumes[0].body as { response: { confirmation_answers: Array<Record<string, string>> } }).response.confirmation_answers[0]).toMatchObject({
    selected_observation_id: "observation-steel", answer_value: "스테인리스", unit: "grade 304",
  });
});

test("photo input blocks zero and more than two files before any production intake request", async ({ page }) => {
  const calls = await installApi(page, "photo_only", ["smartstore"]);
  await openIntake(page);
  await page.getByLabel("프로젝트 이름").fill("사진 검증");
  await page.locator('input[name="input-mode"][value="photo_only"]').check();
  await page.getByRole("button", { name: "상품 입력 시작" }).click();
  await expect(page.getByText("상품 사진은 1~2장만 선택할 수 있습니다.")).toBeVisible();
  await page.getByLabel("상품 사진 1~2장").setInputFiles([
    { name: "one.png", mimeType: "image/png", buffer: png },
    { name: "two.png", mimeType: "image/png", buffer: png },
    { name: "three.png", mimeType: "image/png", buffer: png },
  ]);
  await expect(page.getByText("상품 사진은 1~2장만 선택할 수 있습니다.")).toBeVisible();
  expect(calls.filter((call) => call.path === "/unified-intake")).toHaveLength(0);
});

test("URL validation errors are rendered as safe recovery messages", async ({ page }) => {
  const calls = await installApi(page, "owned_product_url", ["smartstore"]);
  await page.route("**/api/v1/projects/" + projectId + "/reference-inputs", (route) => route.fulfill({ status: 422, json: { detail: { code: "unsafe_url", message: "안전하지 않은 URL입니다." } } }));
  await openIntake(page);
  await page.getByLabel("프로젝트 이름").fill("URL 검증");
  await prepareMode(page, "owned_product_url", "smartstore");
  await page.getByRole("button", { name: "상품 입력 시작" }).click();
  await expect(page.getByText("안전하지 않은 URL입니다.")).toBeVisible();
  expect(calls.filter((call) => call.path === "/unified-intake")).toHaveLength(0);
});
