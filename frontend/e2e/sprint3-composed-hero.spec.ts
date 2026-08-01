import { expect, Page, test } from "@playwright/test";

const projectId = "sprint3-composed-hero";
const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64"
);

const heroSection = {
  id: "hero-section",
  section_type: "hero",
  title: "작지만 확실한 휴식",
  body_copy: "필요한 순간 바로 사용하는 미니 마사지건",
  image_asset_id: "hero-asset",
  visual_kind: "composed_product",
  visual_payload: {
    layout_variant: "hero_product_right",
    product_fit: "contain",
    text_safe_area: "left",
    background_token: "surface_mint",
    decoration_tokens: ["soft_circle", "accent_line"],
    badges: ["대표 상품"],
  },
  sort_order: 0,
  is_visible: true,
  image_candidates: [],
};

async function mockSprint3Apis(page: Page) {
  await page.route(`**/api/v1/projects/${projectId}/page/final**`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        sections_json: {
          project_id: projectId,
          theme_color: "#059669",
          font_family: "sans-serif",
          sections: [heroSection],
        },
      }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-1",
        project_id: projectId,
        theme_color: "#059669",
        font_family: "sans-serif",
        sections: [heroSection],
      }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "hero-asset",
          filename: "hero.png",
          file_path: "",
          mime_type: "image/png",
          source_type: "uploaded",
          asset_role: "product_main",
          is_representative: true,
        },
      ]),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: projectId, name: "미니 마사지건", status: "completed" }),
    });
  });
  await page.route("**/api/v1/files/assets/hero-asset", async (route) => {
    await route.fulfill({ contentType: "image/png", body: onePixelPng });
  });
}

test("result and fixed export use the same non-overlapping composed HERO", async ({ page }) => {
  await mockSprint3Apis(page);

  await page.goto(`/workspace/projects/${projectId}/result`);
  await expect(page.locator('[data-section-visual="composed_product"]')).toBeVisible();

  await page.goto(`/export-render/projects/${projectId}?version_id=final-v1`);
  const hero = page.locator('[data-section-visual="composed_product"]');
  const title = hero.getByRole("heading", { name: heroSection.title });
  const image = hero.locator('[data-composed-product-image="true"]');
  await expect(hero).toBeVisible();
  await expect(title).toBeVisible();
  await expect(image).toBeVisible();
  await expect(image).toHaveCSS("object-fit", "contain");
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.exportReady)).toBe("true");

  const documentBox = await page.locator('[data-detail-page-document="true"]').boundingBox();
  const titleBox = await title.boundingBox();
  const imageBox = await image.boundingBox();
  expect(documentBox).not.toBeNull();
  expect(documentBox!.width).toBeLessThanOrEqual(762);
  expect(documentBox!.width).toBeGreaterThanOrEqual(750);
  expect(titleBox).not.toBeNull();
  expect(imageBox).not.toBeNull();
  expect(titleBox!.x + titleBox!.width).toBeLessThanOrEqual(imageBox!.x + 2);
  await expect(page.getByText("직접 업로드")).toHaveCount(0);

  // The production exporter captures this exact route with Playwright.  A
  // buffer capture verifies the composed DOM survives real JPEG rasterizing.
  const jpeg = await page.screenshot({ type: "jpeg", quality: 85, fullPage: true });
  expect(jpeg[0]).toBe(0xff);
  expect(jpeg[1]).toBe(0xd8);
  expect(jpeg.length).toBeGreaterThan(1_000);
});

test("mobile composed HERO stacks copy and product without overlap", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockSprint3Apis(page);
  await page.goto(`/export-render/projects/${projectId}?version_id=final-v1`);

  const hero = page.locator('[data-section-visual="composed_product"]');
  const title = hero.getByRole("heading", { name: heroSection.title });
  const image = hero.locator('[data-composed-product-image="true"]');
  await expect(title).toBeVisible();
  await expect(image).toBeVisible();

  const titleBox = await title.boundingBox();
  const imageBox = await image.boundingBox();
  expect(titleBox).not.toBeNull();
  expect(imageBox).not.toBeNull();
  expect(titleBox!.y + titleBox!.height).toBeLessThanOrEqual(imageBox!.y);
  await expect(image).toHaveCSS("object-fit", "contain");
});
