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
