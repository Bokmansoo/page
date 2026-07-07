import { expect, test } from "@playwright/test";

test("user can open export history from top nav without alert", async ({ page }) => {
  page.on("dialog", async (dialog) => {
    throw new Error(`Unexpected dialog: ${dialog.message()}`);
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
            filename: "루메나-휴대용-무선-냉각선풍기-상세페이지.png",
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

test("export history falls back to exported image assets when history endpoint is not loaded", async ({ page }) => {
  await page.route("**/api/v1/page/exports", async (route) => {
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/v1/projects", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        value: [
          {
            id: "project-1",
            name: "기존 프로젝트",
            updated_at: "2026-07-06T12:00:00",
            assets: [
              {
                id: "asset-jpg",
                source_type: "exported_image",
                filename: "기존-프로젝트-상세페이지.jpg",
                mime_type: "image/jpeg",
              },
              {
                id: "asset-uploaded",
                source_type: "uploaded",
                filename: "원본.png",
                mime_type: "image/png",
              },
            ],
          },
        ],
      }),
    });
  });

  await page.goto("/workspace/exports");

  await expect(page.getByText("출력 이력을 불러오지 못했습니다.")).toHaveCount(0);
  await expect(page.getByText("기존 프로젝트")).toBeVisible();
  await expect(page.getByText("JPG", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "다시 다운로드" })).toHaveAttribute(
    "href",
    /\/api\/v1\/projects\/project-1\/page\/export\/download\/asset-jpg$/,
  );
});
