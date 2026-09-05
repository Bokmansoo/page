import { expect, test, type Page, type TestInfo } from "@playwright/test";

/**
 * LG-14 beta gate. This suite intentionally has no route/API mocks: it drives
 * the existing intake UI against the already-running local FastAPI/PostgreSQL
 * stack. Run headed (`npx playwright test ... --headed`) for release evidence.
 */
test.describe.configure({ mode: "serial" });

const paths = [
  { mode: "owned_product_url", channel: "smartstore" },
  { mode: "owned_product_url", channel: "coupang" },
  { mode: "photo_only", channel: "smartstore" },
  { mode: "photo_only", channel: "coupang" },
  { mode: "manual", channel: "smartstore" },
  { mode: "manual", channel: "coupang" },
] as const;

async function productPhotos(page: Page) {
  const buffers = await page.evaluate(() =>
    ["#1b5e4b", "#7e4a23"].map((color) => {
      const canvas = document.createElement("canvas");
      canvas.width = 1024;
      canvas.height = 1024;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#f4f7f5";
      context.fillRect(0, 0, 1024, 1024);
      context.fillStyle = color;
      context.fillRect(192, 144, 640, 736);
      context.fillStyle = "#fff";
      context.fillRect(448, 304, 128, 480);
      return canvas.toDataURL("image/png").split(",", 2)[1];
    }),
  );
  return [
    { name: "lg14-product-main.png", mimeType: "image/png", buffer: Buffer.from(buffers[0], "base64") },
    { name: "lg14-product-detail.png", mimeType: "image/png", buffer: Buffer.from(buffers[1], "base64") },
  ];
}

async function startPath(page: Page, mode: string, channel: string) {
  await page.goto("/workspace/projects/new");
  await page.getByRole("radio", { name: `입력 방식 ${mode}` }).check();
  await page.getByRole("textbox", { name: "프로젝트 이름" }).fill(`LG14 ${mode} ${channel} ${Date.now()}`);
  await page.getByRole("combobox", { name: "브랜드" }).selectOption({ index: 1 });
  if (mode === "owned_product_url") {
    const sourceUrl = process.env.SELLFORM_LG14_SOURCE_FIXTURE_URL;
    test.skip(!sourceUrl, "SELLFORM_LG14_SOURCE_FIXTURE_URL is required for the real URL capture path.");
    await page.locator('input[type="url"]').fill(sourceUrl!);
  } else if (mode === "photo_only") {
    await page.locator('input[type="file"]').setInputFiles(await productPhotos(page));
  } else {
    await page.getByRole("textbox", { name: "판매자 입력 사실 후보" }).fill("TEST_GENERATED local product facts");
    await page.getByRole("combobox", { name: "권리 상태" }).selectOption({ label: "확인됨" });
  }
  const channelBox = page.getByRole("checkbox", { name: channel === "smartstore" ? "SmartStore" : "Coupang" });
  if (!(await channelBox.isChecked())) await channelBox.check();
  const other = page.getByRole("checkbox", { name: channel === "smartstore" ? "Coupang" : "SmartStore" });
  if (await other.isChecked()) await other.uncheck();
  await page.getByRole("radio", { name: channel === "smartstore" ? "Quick" : "Expert" }).check();
  await page.getByRole("button", { name: "상품 입력 시작" }).click();
  await expect.poll(async () => (
    await page.getByRole("heading", { name: "상품 정보 확인" }).count()
    + await page.getByRole("link", { name: "기존 상세페이지 흐름으로 계속" }).count()
  ), { timeout: 90_000 }).toBeGreaterThan(0);
  for (let cycle = 0; cycle < 12; cycle += 1) {
    const submitConfirmation = page.getByRole("button", { name: "확인 응답 제출" });
    if (!(await submitConfirmation.count())) break;
    const groups = page.locator('form[aria-labelledby="confirmation-title"] fieldset');
    for (let index = 0; index < await groups.count(); index += 1) {
      const group = groups.nth(index);
      const fieldId = await group.locator("legend").innerText();
      const prohibited = ["exact_weight", "material_grade", "certification", "performance", "ingredients", "waterproof_rating", "battery_capacity", "medical_claim"];
      await group.getByRole("radio", { name: prohibited.includes(fieldId) ? "거절" : "확인" }).check();
      const value = group.getByRole("textbox").first();
      if (await value.count()) await value.fill("seller-confirmed-value");
    }
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/resume"),
    );
    await submitConfirmation.click();
    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    if (mode === "manual" && channel === "smartstore") {
      const duplicate = await page.context().request.post(response.url(), {
        data: response.request().postDataJSON(),
      });
      expect(duplicate.ok()).toBeTruthy();
    }
    const nextRun = await response.json() as { current_stage?: string };
    if (nextRun.current_stage !== "seller_confirmation") break;
    await expect.poll(async () => (
      await submitConfirmation.count()
      + await page.getByRole("link", { name: "기존 상세페이지 흐름으로 계속" }).count()
    ), { timeout: 90_000 }).toBeGreaterThan(0);
  }
  await expect(page.getByRole("link", { name: "기존 상세페이지 흐름으로 계속" })).toBeVisible({ timeout: 90_000 });
}

async function refreshCanonicalPlanning(page: Page) {
  await Promise.all([
    page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/storyboard/recommendations")),
    page.getByRole("button", { name: "후보 3개 다시 만들기" }).click(),
  ]);
  await expect(page.getByRole("button", { name: "스토리보드 승인" }).first()).toBeVisible({ timeout: 30_000 });
}

async function completeCanonicalGraph(page: Page, mode: string) {
  await page.getByRole("button", { name: "스토리보드 승인" }).first().click();
  await expect.poll(async () => (
    await page.getByTestId("graph-review-generation_pending").count()
    + await page.getByTestId("graph-review-image_review").count()
    + await page.getByTestId("lg12-quality-status").count()
    + await page.getByTestId("graph-review-quality_review").count()
  ), { timeout: 90_000 }).toBeGreaterThan(0);
  if (await page.getByTestId("graph-review-generation_pending").count()) {
    await page.getByRole("button", { name: "비용 승인 후 이미지 생성" }).click();
    await expect.poll(async () => (
      await page.getByTestId("graph-review-image_review").count()
      + await page.getByTestId("lg12-quality-status").count()
      + await page.getByTestId("graph-review-quality_review").count()
    ), { timeout: 90_000 }).toBeGreaterThan(0);
  }
  if (mode === "photo_only" && await page.getByTestId("graph-review-image_review").count()) {
    const job = page.getByTestId("graph-review-image_review").locator("article").first();
    await job.locator("select").selectOption({ index: 1 });
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/resume"),
    );
    await job.getByRole("button").last().click();
    expect((await responsePromise).ok()).toBeTruthy();
  }
  for (let approvals = 0; approvals < 12; approvals += 1) {
    const approve = page.getByRole("button", { name: "이 장면 승인" });
    await expect.poll(async () => {
      if (await page.getByTestId("lg12-quality-status").count()) return "quality";
      if (await page.getByTestId("graph-review-quality_review").count()) return "quality_review";
      return await approve.count() ? "review" : "transition";
    }, { timeout: 30_000 }).not.toBe("transition");
    const remaining = await approve.count();
    if (!remaining) break;
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/resume"),
    );
    await approve.first().click();
    expect((await responsePromise).ok()).toBeTruthy();
    await expect.poll(async () => {
      if (await page.getByTestId("lg12-quality-status").count()) return -1;
      if (await page.getByTestId("graph-review-quality_review").count()) return -1;
      const current = await approve.count();
      return current > 0 && current < remaining ? current : remaining;
    }, { timeout: 120_000 }).toBeLessThan(remaining);
  }
  const qualityReview = page.getByTestId("graph-review-quality_review");
  if (await qualityReview.count()) {
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/resume"),
    );
    await qualityReview.getByRole("button").last().click();
    expect((await responsePromise).ok()).toBeTruthy();
  }
  await expect(page.getByTestId("lg12-quality-status")).toBeVisible({ timeout: 90_000 });
}

async function verifyFinalSellerOutputs(page: Page, mode: string, channel: string, testInfo: TestInfo) {
  const planningUrl = page.url();
  const projectId = new URL(planningUrl).pathname.split("/")[3];
  await page.reload();
  await expect(page.getByTestId("lg12-quality-status")).toBeVisible({ timeout: 60_000 });
  await page.goto(planningUrl);
  await expect(page.getByTestId("lg12-quality-status")).toBeVisible({ timeout: 60_000 });

  const promotion = page.getByTestId("lg12-promote-page");
  if (await promotion.count()) {
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/page/promotion"),
    );
    await promotion.click();
    const response = await responsePromise;
    expect(response.status()).toBe(201);
    if (mode === "manual" && channel === "smartstore") {
      const duplicate = await page.context().request.post(response.url(), {
        data: response.request().postDataJSON(),
      });
      expect(duplicate.status()).toBe(201);
      expect(await duplicate.json()).toEqual(await response.json());
    }
  }
  const preview = page.getByTestId(`lg12-export-ready-${channel}`);
  await expect(preview).toBeVisible({ timeout: 60_000 });
  const previewHref = await preview.getAttribute("href");
  expect(previewHref).toContain(`channel=${channel}`);
  const versionId = new URL(previewHref!, page.url()).searchParams.get("version_id");
  expect(versionId).toBeTruthy();

  const standaloneResponsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/page/export/standalone"),
  );
  await page.getByTestId(`lg12-${channel}-standalone-export`).click();
  const standaloneResponse = await standaloneResponsePromise;
  expect(standaloneResponse.ok()).toBeTruthy();
  if (mode === "manual" && channel === "smartstore") {
    const duplicate = await page.context().request.post(standaloneResponse.url(), {
      data: standaloneResponse.request().postDataJSON(),
    });
    expect(duplicate.ok()).toBeTruthy();
    expect(await duplicate.json()).toEqual(await standaloneResponse.json());
  }
  const htmlLink = page.getByTestId(`lg12-${channel}-html-download`);
  const zipLink = page.getByTestId(`lg12-${channel}-zip-download`);
  await expect(htmlLink).toBeVisible({ timeout: 60_000 });
  const htmlDownloadPromise = page.waitForEvent("download");
  await htmlLink.click();
  const htmlDownload = await htmlDownloadPromise;
  const htmlPath = testInfo.outputPath(`${mode}-${channel}.html`);
  await htmlDownload.saveAs(htmlPath);
  const fs = await import("node:fs/promises");
  expect((await fs.stat(htmlPath)).size).toBeGreaterThan(0);
  const zipDownloadPromise = page.waitForEvent("download");
  await zipLink.click();
  const zipDownload = await zipDownloadPromise;
  const zipPath = testInfo.outputPath(`${mode}-${channel}.zip`);
  await zipDownload.saveAs(zipPath);
  const zipBytes = await fs.readFile(zipPath);
  expect(zipBytes.byteLength).toBeGreaterThan(0);
  expect(zipBytes.subarray(0, 2).toString("ascii")).toBe("PK");

  await page.goto(previewHref!);
  await expect(page.locator('[data-detail-page-section="true"]').first()).toBeVisible({ timeout: 60_000 });
  const previewUrl = page.url();
  await page.reload();
  await expect(page.locator('[data-detail-page-section="true"]').first()).toBeVisible({ timeout: 60_000 });
  await page.goto(previewUrl);
  await expect(page.locator('[data-detail-page-section="true"]').first()).toBeVisible({ timeout: 60_000 });

  await page.goto(planningUrl);
  await expect(page.getByTestId("lg12-quality-status")).toBeVisible({ timeout: 60_000 });
  for (const format of ["png", "jpg"] as const) {
    const downloadPromise = page.waitForEvent("download", { timeout: 120_000 });
    await page.getByTestId(`lg12-${channel}-${format}-download`).click();
    const download = await downloadPromise;
    const outputPath = testInfo.outputPath(`${mode}-${channel}.${format}`);
    await download.saveAs(outputPath);
    const imageBytes = await fs.readFile(outputPath);
    expect(imageBytes.byteLength).toBeGreaterThan(0);
    expect(download.suggestedFilename().toLowerCase()).toMatch(new RegExp(`\\.${format === "jpg" ? "jpe?g" : "png"}$`));
    expect(format === "png"
      ? imageBytes.subarray(1, 4).toString("ascii")
      : imageBytes.subarray(0, 2).toString("hex")).toBe(format === "png" ? "PNG" : "ffd8");
  }

  await page.goto(previewUrl);
  await expect(page.locator('[data-detail-page-section="true"]').first()).toBeVisible({ timeout: 60_000 });
  const internalTerms = [
    "LangGraph", "LG-7", "checkpoint", "routing_code", "outbox", "dead-letter",
    "needs_review", "seller_confirmed", "safe_existing_photo",
  ];
  const bodyText = await page.locator("body").innerText();
  expect(internalTerms.filter((term) => bodyText.toLowerCase().includes(term.toLowerCase()))).toEqual([]);
  const severeAccessibilityProblems = await page.evaluate(() => ({
    unnamedButtons: Array.from(document.querySelectorAll("button")).filter((element) => !(element.textContent || "").trim() && !element.getAttribute("aria-label")).length,
    imagesWithoutAlt: Array.from(document.querySelectorAll("img")).filter((element) => !element.hasAttribute("alt")).length,
    duplicateIds: Array.from(document.querySelectorAll("[id]")).map((element) => element.id).filter((id, index, ids) => ids.indexOf(id) !== index).length,
  }));
  expect(severeAccessibilityProblems).toEqual({ unnamedButtons: 0, imagesWithoutAlt: 0, duplicateIds: 0 });
  const path = await import("node:path");
  await page.addScriptTag({ path: path.join(process.cwd(), "node_modules", "axe-core", "axe.min.js") });
  const axeViolations = await page.evaluate(async () => {
    const axe = (window as unknown as {
      axe: { run: (root: Document, options: Record<string, unknown>) => Promise<{ violations: Array<{ id: string; impact: string | null }> }> };
    }).axe;
    const result = await axe.run(document, { resultTypes: ["violations"] });
    return result.violations.filter((violation) => ["critical", "serious"].includes(violation.impact || ""));
  });
  expect(axeViolations).toEqual([]);

  const viewport = mode === "photo_only" ? { width: 390, height: 844 }
    : mode === "manual" ? { width: 768, height: 1024 }
    : { width: 1440, height: 900 };
  await page.setViewportSize(viewport);
  await expect(page.locator('[data-detail-page-section="true"]').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath(`${mode}-${channel}-${viewport.width}.png`), fullPage: true });

  const qualityResponse = await page.context().request.get(
    `http://localhost:8001/api/v1/projects/${projectId}/quality-status`,
  );
  expect(qualityResponse.ok()).toBeTruthy();
  const evidence = {
    projectId, planningUrl, previewUrl, versionId, channel,
    quality: await qualityResponse.json(),
  };
  await testInfo.attach("lg14-path-evidence", {
    body: Buffer.from(JSON.stringify(evidence, null, 2)), contentType: "application/json",
  });
}

for (const path of paths) {
  test(`${path.mode} × ${path.channel} reaches frozen quality output`, async ({ page }, testInfo) => {
    test.setTimeout(480_000);
    await startPath(page, path.mode, path.channel);
    await page.getByRole("link", { name: "기존 상세페이지 흐름으로 계속" }).click();
    // PlanningDraftEditor deliberately owns the visible approval action while
    // GraphReviewPanel suppresses its duplicate planning-review controls.
    await expect(page.getByRole("button", { name: "스토리보드 승인" }).first()).toBeVisible({ timeout: 60_000 });
    await refreshCanonicalPlanning(page);
    await completeCanonicalGraph(page, path.mode);
    await verifyFinalSellerOutputs(page, path.mode, path.channel, testInfo);
  });
}
