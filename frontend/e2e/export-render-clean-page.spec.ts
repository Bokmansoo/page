import { expect, test } from "@playwright/test";

test("export render route does not include workspace chrome", async ({ page }) => {
  // Mock the API responses for a specific project
  const projectId = "test-project-export-clean";

  await page.route(`**/api/v1/projects/${projectId}/page/final**`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sections_json: {
          theme_color: "#3B82F6",
          font_family: "sans-serif",
          sections: [
            {
              id: "sec-1",
              section_type: "hero",
              title: "테스트 상품",
              body_copy: "테스트 상세페이지 본문입니다.",
              sort_order: 0,
              is_visible: true,
            },
          ],
        },
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.goto(`/export-render/projects/${projectId}?version_id=test-v1`);

  // The detail page document should be visible
  await expect(page.locator("[data-detail-page-document='true']")).toBeVisible();

  // Workspace chrome should NOT be present
  await expect(page.getByText("Sellform")).toHaveCount(0);
  await expect(page.getByText("AI 상세페이지 생성")).toHaveCount(0);

  // The export render shell should be present
  await expect(page.locator("[data-export-render-shell='true']")).toBeVisible();
});

test("LG-10 preview reads one immutable DetailPageVersion snapshot", async ({ page }) => {
  const projectId = "lg10-version-preview";
  const versionId = "lg10-final-v1";
  const assetHash = "a".repeat(64);
  const onePixelPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64",
  );

  await page.route(`**/api/v1/projects/${projectId}/page/final**`, async (route) => {
    expect(new URL(route.request().url()).searchParams.get("version_id")).toBe(versionId);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: versionId,
        sections_json: {
          schema_version: "lg10-detail-page-version-v1",
          commerce_renderer: {
            theme_color: "#ffffff",
            font_family: "system-ui, sans-serif",
            sections: [
              {
                id: "hero", section_type: "hero", title: "한국어 고정 카피", body_copy: "승인된 이미지와 같은 버전입니다.",
                image_asset_id: "approved-asset", image_asset_content_hash: assetHash, sort_order: 0, is_visible: true,
              },
              {
                id: "product_information", section_type: "product_information", title: "제품 사양", body_copy: "정격 입력: DC 5V 2A",
                image_asset_id: null, sort_order: 1, is_visible: true,
              },
            ],
          },
        },
      }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{ id: "approved-asset", filename: "approved.png", mime_type: "image/png", source_type: "ai_generated" }]),
    });
  });
  await page.route(/\/api\/v1\/files\/assets\/approved-asset\?expected_content_hash=/, async (route) => {
    expect(new URL(route.request().url()).searchParams.get("expected_content_hash")).toBe(assetHash);
    await route.fulfill({ contentType: "image/png", body: onePixelPng });
  });

  await page.goto(`/export-render/projects/${projectId}?version_id=${versionId}`);

  await expect(page.locator("[data-detail-page-document='true']")).toBeVisible();
  await expect(page.locator("[data-detail-page-document='true'] h3", { hasText: "한국어 고정 카피" })).toBeVisible();
  await expect(page.locator("[data-detail-page-document='true']", { hasText: "정격 입력: DC 5V 2A" })).toBeVisible();
  await expect(page.locator("[data-detail-page-section='true']")).toHaveCount(2);
  await expect(page.locator("img[src*='approved-asset']")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-export-ready", "true");
});

test("LG-10 preview blocks an asset whose bytes no longer match its frozen hash", async ({ page }) => {
  const projectId = "lg10-version-hash-mismatch";
  const versionId = "lg10-final-v1";
  const assetHash = "b".repeat(64);

  await page.route(`**/api/v1/projects/${projectId}/page/final**`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: versionId,
        sections_json: {
          schema_version: "lg10-detail-page-version-v1",
          commerce_renderer: {
            sections: [{
              id: "hero", section_type: "hero", title: "고정된 상세페이지", body_copy: "변조를 허용하지 않습니다.",
              image_asset_id: "approved-asset", image_asset_content_hash: assetHash, sort_order: 0, is_visible: true,
            }],
          },
        },
      }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([{ id: "approved-asset", filename: "approved.png", mime_type: "image/png", source_type: "ai_generated" }]),
    });
  });
  await page.route(/\/api\/v1\/files\/assets\/approved-asset\?expected_content_hash=/, async (route) => {
    expect(new URL(route.request().url()).searchParams.get("expected_content_hash")).toBe(assetHash);
    await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { code: "asset_snapshot_hash_mismatch" } }) });
  });

  await page.goto(`/export-render/projects/${projectId}?version_id=${versionId}`);

  await expect(page.locator("html")).toHaveAttribute("data-export-ready", "error");
  await expect(page.locator("[data-detail-page-document='true'] [role='alert']")).toBeVisible();
});
