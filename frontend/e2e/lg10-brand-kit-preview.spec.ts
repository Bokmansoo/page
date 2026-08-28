import { expect, test } from "@playwright/test";

const projectId = "lg10-brand-preview-project";
const versionId = "lg10-frozen-brand-version";
const logoId = "lg10-brand-logo";
const logoHash = "a".repeat(64);

test("LG-10 frozen preview renders the hash-addressed Brand Kit logo and watermark", async ({ page }) => {
  const assetRequests: string[] = [];
  const snapshot = {
    id: versionId,
    sections_json: {
      schema_version: "lg10-detail-page-version-v1",
      commerce_renderer: {
        theme_color: "#ffffff",
        font_family: "system-ui, sans-serif",
        brand_assets: {
          logo: { asset_id: logoId, asset_content_hash: logoHash },
          watermark: { asset_id: logoId, asset_content_hash: logoHash },
        },
        sections: [{
          id: "hero", section_type: "hero", title: "고정 한국어 카피", body_copy: "고정 설명",
          sort_order: 0, is_visible: true,
        }],
      },
    },
  };
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL5XwAAAABJRU5ErkJggg==",
    "base64",
  );

  await page.route(`**/api/v1/projects/${projectId}/page/final?version_id=${versionId}`, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(snapshot),
  }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify([{ id: logoId, filename: "brand-logo.png", mime_type: "image/png", source_type: "uploaded" }]),
  }));
  await page.route(`**/api/v1/files/assets/${logoId}**`, async (route) => {
    assetRequests.push(route.request().url());
    await route.fulfill({ status: 200, contentType: "image/png", body: png });
  });

  await page.goto(`/export-render/projects/${projectId}?version_id=${versionId}`);
  await expect(page.locator('[data-detail-page-brand-logo="true"] img')).toHaveAttribute(
    "data-asset-content-hash", logoHash,
  );
  await expect(page.locator('[data-detail-page-brand-watermark="true"] img')).toHaveAttribute(
    "data-asset-content-hash", logoHash,
  );
  await expect(page.locator('[data-detail-page-brand-logo="true"] img')).toHaveJSProperty("complete", true);
  await expect(page.locator('[data-detail-page-brand-watermark="true"] img')).toHaveJSProperty("complete", true);
  // Logo and watermark intentionally share one frozen identity; Chromium may
  // satisfy the second placement from its image cache instead of requesting it.
  expect(assetRequests).toHaveLength(1);
  expect(assetRequests.every((url) => url.includes(`expected_content_hash=${logoHash}`))).toBe(true);
});
