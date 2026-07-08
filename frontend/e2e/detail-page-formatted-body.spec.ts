import { expect, test } from "@playwright/test";

const projectId = "formatted-body-project";

test("detail page renders body copy paragraphs and bullets with readable structure", async ({ page }) => {
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: projectId,
        name: "Portable fan",
        status: "ready",
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-1",
        project_id: projectId,
        theme_color: "#10B981",
        font_family: "sans-serif",
        sections: [
          {
            id: "benefit-section",
            section_type: "benefit_list",
            title: "Use it where you need it",
            body_copy:
              "Keep it on your desk or carry it outside.\n\n- Cordless use around the room\n- Compact shape for storage\n- Simple controls for daily use",
            image_asset_id: null,
            visual_kind: "html_graphic",
            visual_payload: { strategy: "benefit_cards" },
            sort_order: 0,
            is_visible: true,
            image_candidates: [],
          },
        ],
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.getByText("Keep it on your desk or carry it outside.", { exact: true }).first()).toBeVisible();
  await expect(page.locator("article li")).toHaveText([
    "Cordless use around the room",
    "Compact shape for storage",
    "Simple controls for daily use",
  ]);
});
