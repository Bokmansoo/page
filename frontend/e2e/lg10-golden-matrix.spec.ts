import { expect, test } from "@playwright/test";

const projectId = "lg10-golden-preview";
const assetHash = "c".repeat(64);
const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

test("LG-10 golden preview keeps all directions, Korean copy, tables, and assets usable at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify([{ id: "approved-hero", filename: "approved.png", mime_type: "image/png", source_type: "ai_generated" }]),
  }));
  await page.route(/\/api\/v1\/files\/assets\/approved-hero\?expected_content_hash=/, (route) => route.fulfill({
    contentType: "image/png",
    body: onePixelPng,
  }));
  await page.route(`**/api/v1/projects/${projectId}/page/final**`, (route) => {
    const versionId = new URL(route.request().url()).searchParams.get("version_id") || "lg10-safe_information";
    const direction = versionId.replace("lg10-", "");
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: versionId,
        sections_json: {
          schema_version: "lg10-detail-page-version-v1",
          lg10: { canonical_rendering: { design_direction: direction } },
          commerce_renderer: {
            theme_color: "#ffffff",
            font_family: "system-ui, sans-serif",
            sections: [
              {
                id: "hero", section_type: "hero", sort_order: 0, is_visible: true,
                title: "손안에 편안하게 들어오는 휴대용 제품의 핵심 기능을 자세히 확인하세요",
                body_copy: "판매자가 확인한 제품 정보와 승인된 이미지만 사용합니다.",
                image_asset_id: "approved-hero", image_asset_content_hash: assetHash,
              },
              {
                id: "product_information", section_type: "product_information", sort_order: 1, is_visible: true,
                title: "제품 사양과 사용 전 확인 사항", body_copy: "",
                image_asset_id: null, visual_kind: "html_graphic",
                visual_payload: {
                  layout_variant: "spec_table",
                  table_rows: [{
                    label: "정격 입력", value: "DC 5V 2A로 확인된 사양입니다.",
                    verification_status: "confirmed", source_fact_ids: ["fact-rated-input"],
                  }],
                },
              },
            ],
          },
        },
      }),
    });
  });

  for (const direction of ["safe_information", "image_centric", "balanced_sale"]) {
    await page.goto(`/export-render/projects/${projectId}?version_id=lg10-${direction}`);
    await expect(page.locator("[data-detail-page-document='true']")).toBeVisible();
    await expect(page.locator("[data-detail-page-document='true'] h3").first()).toContainText("휴대용 제품");
    await expect(page.locator("img[src*='approved-hero']")).toBeVisible();
    await expect(page.locator("[data-section-visual='html_graphic'] table")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-export-ready", "true");

    const mobileLayout = await page.locator("[data-detail-page-document='true']").evaluate((document) => ({
      clientWidth: document.clientWidth,
      scrollWidth: document.scrollWidth,
      koreanCopyFits: Array.from(document.querySelectorAll("h3, p, th, td"))
        .every((element) => element.scrollWidth <= element.clientWidth),
    }));
    expect(mobileLayout.scrollWidth).toBeLessThanOrEqual(mobileLayout.clientWidth);
    expect(mobileLayout.koreanCopyFits).toBe(true);
  }
});
