import { test, expect } from "@playwright/test";

test("workspace starts with AI detail page intake", async ({ page }) => {
  await page.goto("/workspace");
  await expect(page.getByText("상품 사진이나 URL을 넣으면 AI가 상세페이지를 만들어드려요.")).toBeVisible();
  await page.getByPlaceholder("상품명").fill("유아 자전거");
  await page.getByPlaceholder("간단한 설명").fill("보조 바퀴가 있는 첫 자전거");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await expect(page.getByText("상품 이해")).toBeVisible();
});
