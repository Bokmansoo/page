import { expect, test } from "@playwright/test";

const projectId = "lg10-export-project";
const runId = "lg10-completed-run";
const frozenVersionId = "lg10-frozen-version";
const otherVersionId = "mutable-current-page-version";

test("LG-10 completion exports only the frozen version and exposes both downloads", async ({ page }) => {
  const standaloneRequests: Array<Record<string, unknown>> = [];
  const downloadRequests: string[] = [];
  const completedView = {
    run_id: runId,
    thread_id: runId,
    status: "completed",
    current_stage: "finalize_run",
    checkpoint_id: "checkpoint-completed",
    values: {
      review: { pending: null },
      generation: {
        jobs: [],
        image_generation_required: false,
        completion_basis: "no_required_image_scenes",
        required_scene_count: 0,
        approved_count: 0,
      },
      rendering: { detail_page_version: { id: frozenVersionId } },
      execution: { recoverable: false, last_error: null, errors: [] },
    },
    next_nodes: [],
  };
  const htmlDownloadUrl = `/api/v1/projects/${projectId}/page/export/download/${frozenVersionId}-html`;
  const zipDownloadUrl = `/api/v1/projects/${projectId}/page/export/download/${frozenVersionId}-zip`;
  const copyableHtml = `<div data-sellform-detail-page-version-id="${frozenVersionId}"><style>.sf-page{max-width:760px}</style><main class="sf-page"><table class="sf-spec-table"><tbody><tr><th>규격</th><td>고정 사양</td></tr></tbody></table><img src="data:image/png;base64,AAAA" alt="승인 이미지"></main></div>`;

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}`, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(completedView),
  }));
  await page.route(`**/api/v1/projects/${projectId}/page/export/standalone`, async (route) => {
    standaloneRequests.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        detail_page_version_id: frozenVersionId,
        approved_asset_manifest_hash: "a".repeat(64),
        copyable_html: copyableHtml,
        html_download_url: htmlDownloadUrl,
        zip_download_url: zipDownloadUrl,
        warnings: [],
      }),
    });
  });
  await page.route(`**${htmlDownloadUrl}`, async (route) => {
    downloadRequests.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      headers: { "Content-Disposition": 'attachment; filename="detail-page.html"' },
      body: "<main>frozen export</main>",
    });
  });
  await page.route(`**${zipDownloadUrl}`, async (route) => {
    downloadRequests.push(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/zip",
      headers: { "Content-Disposition": 'attachment; filename="detail-page.zip"' },
      body: "zip-bytes",
    });
  });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByTestId("lg5r-completed-gallery")).toBeVisible();
  await page.getByTestId("lg10-standalone-export").click();

  await expect(page.getByTestId("lg10-copyable-html-download")).toHaveAttribute("href", new RegExp(`${frozenVersionId}-html$`));
  await expect(page.getByTestId("lg10-standalone-zip-download")).toHaveAttribute("href", new RegExp(`${frozenVersionId}-zip$`));
  await expect(page.getByTestId("lg10-copyable-html-code")).toHaveValue(copyableHtml);
  expect(standaloneRequests).toEqual([{ final_version_id: frozenVersionId }]);
  expect(JSON.stringify(standaloneRequests)).not.toContain(otherVersionId);

  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByTestId("lg10-copyable-html-copy").click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(copyableHtml);
  await expect(page.getByRole("status")).toContainText("복사했습니다");

  await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("lg10-copyable-html-download").click(),
  ]);
  await Promise.all([
    page.waitForEvent("download"),
    page.getByTestId("lg10-standalone-zip-download").click(),
  ]);
  expect(downloadRequests).toHaveLength(2);
  expect(downloadRequests.every((url) => url.includes(frozenVersionId) && !url.includes(otherVersionId))).toBe(true);
});
