import { expect, test } from "@playwright/test";

const worklistPayload = {
  items: [
    {
      project_id: "project-1",
      project_name: "루메나 휴대용 무선 냉각선풍기",
      status: "completed",
      thumbnail_url: null,
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
});

test("user can view generated detail page worklist", async ({ page }) => {
  await page.goto("/workspace/projects");

  await expect(page.getByRole("heading", { name: "작업 목록" })).toBeVisible();
  await expect(page.getByText("루메나 휴대용 무선 냉각선풍기")).toBeVisible();
  await expect(page.getByText("검수 필요한 상세페이지")).toBeVisible();
  await expect(page.getByText("완료", { exact: true })).toBeVisible();
  await expect(page.getByText("검수 필요", { exact: true })).toBeVisible();

  const firstCard = page.locator("article").filter({ hasText: "루메나 휴대용 무선 냉각선풍기" });
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

test("user can open worklist from workspace top nav", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByRole("link", { name: "작업 목록" }).first().click();

  await expect(page).toHaveURL(/\/workspace\/projects/);
  await expect(page.getByRole("heading", { name: "작업 목록" })).toBeVisible();
});
