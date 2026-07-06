import { expect, test } from "@playwright/test";

test("user can open export history from top nav without alert", async ({ page }) => {
  // Fail if any dialog (alert) appears
  page.on("dialog", async () => {
    throw new Error("Unexpected dialog: alert should not appear for export history");
  });

  await page.route("**/api/v1/page/exports", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "export-1",
            project_id: "project-1",
            project_name: "루메나 휴대용 무선 냉각선풍기",
            format: "png",
            status: "completed",
            filename: "루메나_선풍기.png",
            content_type: "image/png",
            download_url: "/api/v1/projects/project-1/page/export/download/asset-1",
            error_message: null,
            created_at: "2026-07-06T12:00:00",
            completed_at: "2026-07-06T12:01:00",
          },
          {
            id: "export-2",
            project_id: "project-2",
            project_name: "실패한 상품",
            format: "jpg",
            status: "failed",
            filename: null,
            content_type: null,
            download_url: null,
            error_message: "이미지 생성 서버 타임아웃",
            created_at: "2026-07-06T11:00:00",
            completed_at: null,
          },
        ],
      }),
    });
  });

  await page.goto("/workspace");
  await page.getByRole("link", { name: "출력 이력" }).first().click();

  await expect(page).toHaveURL(/\/workspace\/exports/);
  await expect(page.getByRole("heading", { name: "출력 이력" })).toBeVisible();
  await expect(page.getByText("루메나 휴대용 무선 냉각선풍기")).toBeVisible();
  await expect(page.getByText("실패한 상품")).toBeVisible();
  await expect(page.getByText("PNG", { exact: true })).toBeVisible();
  await expect(page.getByText("JPG", { exact: true })).toBeVisible();
  await expect(page.getByText("이미지 생성 서버 타임아웃")).toBeVisible();
  await expect(page.getByRole("link", { name: "다시 다운로드" })).toBeVisible();
});
