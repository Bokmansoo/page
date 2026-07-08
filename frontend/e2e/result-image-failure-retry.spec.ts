import { expect, test } from "@playwright/test";

const projectId = "result-image-failure-retry-project";

test("result page explains billing image failures and retries failed image job", async ({ page }) => {
  let regenerateCalled = false;
  let generateCalled = false;

  const failedPage = {
    id: "page-1",
    project_id: projectId,
    theme_color: "#10B981",
    font_family: "sans-serif",
    sections: [
      {
        id: "hero-section",
        section_type: "hero",
        title: "Cool wind anywhere",
        body_copy: "Portable fan for daily comfort.",
        image_asset_id: null,
        sort_order: 0,
        is_visible: true,
        image_candidates: [
          {
            candidate_id: "planning-failed-job",
            slot_id: "hero",
            asset_id: null,
            source_type: "ai_generated",
            label: "이미지 생성 실패",
            is_recommended: false,
            needs_identity_review: false,
            status: "failed",
            error_code: "BILLING_HARD_LIMIT_REACHED",
            warnings: [
              "BILLING_HARD_LIMIT_REACHED: Billing hard limit has been reached.",
            ],
          },
        ],
      },
    ],
  };

  const regeneratedPage = {
    ...failedPage,
    sections: [
      {
        ...failedPage.sections[0],
        image_candidates: [
          {
            ...failedPage.sections[0].image_candidates[0],
            asset_id: "asset-generated",
            label: "생성 이미지",
            status: "needs_review",
            error_code: null,
            warnings: [],
          },
        ],
      },
    ],
  };

  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: projectId,
        name: "Lumena portable cooling fan",
        status: "ready",
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(generateCalled ? regeneratedPage : failedPage),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/visual-jobs/planning-failed-job/regenerate`, async (route) => {
    regenerateCalled = true;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ job_id: "planning-failed-job", status: "needs_generation" }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/visual-jobs/planning-failed-job/generate`, async (route) => {
    generateCalled = true;
    expect(route.request().postDataJSON()).toEqual({ cost_approved: true });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "planning-failed-job",
        status: "needs_review",
        output_asset_id: "asset-generated",
      }),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.getByText("이미지 생성이 결제 한도 때문에 중단됐습니다")).toBeVisible();
  await page.getByRole("button", { name: "이미지 다시 생성" }).click();

  await expect.poll(() => regenerateCalled).toBe(true);
  await expect.poll(() => generateCalled).toBe(true);
  await expect(page.getByText("생성 이미지")).toBeVisible();
});
