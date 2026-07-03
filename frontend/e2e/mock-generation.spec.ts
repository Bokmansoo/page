import { test, expect } from "@playwright/test";

test("mock mode creates a complete detail page draft", async ({ page }) => {
  await page.goto("/workspace");
  await page.getByPlaceholder("상품명").fill("유아 자전거");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await expect(page.getByText("상세페이지 조립")).toBeVisible();
  await expect(page.getByRole("button", { name: "생성된 상세페이지 보기" })).toBeVisible({ timeout: 10000 });
});
