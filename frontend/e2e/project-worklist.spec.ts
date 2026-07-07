import { expect, test } from "@playwright/test";

const transparentPixel = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
  "base64",
);

const worklistPayload = {
  items: [
    {
      project_id: "project-1",
      project_name: "루메나 FAN JET ULTRA PLUS 프리미엄 아웃도어 휴대용 냉각 선풍기",
      status: "completed",
      thumbnail_url: "/api/v1/export-jobs/export-1/download",
      result_url: "/workspace/projects/project-1/result",
      review_url: "/workspace/projects/project-1/page-editor?mode=review",
      export_history_url: "/workspace/exports?project_id=project-1",
      last_export_status: "completed",
      updated_at: "2026-07-06T12:00:00",
    },
    {
      project_id: "project-2",
      project_name: "검수 필요한 상세페이지",
      status: "needs_review",
      thumbnail_url: null,
      result_url: "/workspace/projects/project-2/result",
      review_url: "/workspace/projects/project-2/page-editor?mode=review",
      export_history_url: "/workspace/exports?project_id=project-2",
      last_export_status: null,
      updated_at: "2026-07-06T11:00:00",
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/projects/worklist", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(worklistPayload),
    });
  });

  await page.route("**/api/v1/export-jobs/export-1/download", async (route) => {
    await route.fulfill({
      contentType: "image/png",
      body: transparentPixel,
    });
  });
});

test("user can view generated detail page worklist", async ({ page }) => {
  await page.goto("/workspace/projects");

  await expect(page.getByRole("heading", { name: "작업 목록" })).toBeVisible();
  await expect(page.getByText("루메나 FAN JET ULTRA PLUS 프리미엄 아웃도어 휴대용 냉각 선풍기")).toBeVisible();
  await expect(page.getByText("검수 필요한 상세페이지")).toBeVisible();
  await expect(page.getByText("완료", { exact: true })).toBeVisible();
  await expect(page.getByText("검수 필요", { exact: true })).toBeVisible();

  const firstCard = page.locator("article").filter({ hasText: "루메나 FAN JET ULTRA PLUS" });
  await expect(firstCard.getByRole("img", { name: /썸네일/ })).toHaveAttribute(
    "src",
    /http:\/\/localhost:8001\/api\/v1\/export-jobs\/export-1\/download/,
  );
  await expect(firstCard.getByRole("link", { name: "결과 보기" })).toHaveAttribute(
    "href",
    "/workspace/projects/project-1/result",
  );
  await expect(firstCard.getByRole("link", { name: "검수하며 다듬기" })).toHaveAttribute(
    "href",
    "/workspace/projects/project-1/page-editor?mode=review",
  );
  await expect(firstCard.getByRole("link", { name: "출력 이력" })).toHaveAttribute(
    "href",
    "/workspace/exports?project_id=project-1",
  );
});

test("worklist falls back to legacy projects endpoint when new endpoint is not loaded", async ({ page }) => {
  await page.route("**/api/v1/projects/worklist", async (route) => {
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/v1/projects", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "legacy-project",
          name: "기존 API에서 불러온 상세페이지",
          status: "completed",
          updated_at: "2026-07-06T13:00:00",
        },
      ]),
    });
  });

  await page.goto("/workspace/projects");

  await expect(page.getByText("작업 목록을 불러오지 못했습니다.")).toHaveCount(0);
  await expect(page.getByText("기존 API에서 불러온 상세페이지")).toBeVisible();
  await expect(page.getByRole("link", { name: "결과 보기" })).toHaveAttribute(
    "href",
    "/workspace/projects/legacy-project/result",
  );
});

test("user can open worklist from workspace top nav", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByRole("link", { name: "작업 목록" }).first().click();

  await expect(page).toHaveURL(/\/workspace\/projects/);
  await expect(page.getByRole("heading", { name: "작업 목록" })).toBeVisible();
});
