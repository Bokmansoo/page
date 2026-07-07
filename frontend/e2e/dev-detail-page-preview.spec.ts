import { expect, test } from "@playwright/test";

test("dev detail page preview renders from local fixtures without API calls", async ({ page }) => {
  const apiCalls: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    apiCalls.push(route.request().url());
    await route.abort();
  });

  await page.goto("/dev/detail-page-preview");

  await expect(page.getByRole("heading", { name: "API 없는 상세페이지 미리보기" })).toBeVisible();
  await expect(page.locator("[data-detail-page-document='true']")).toBeVisible();
  await expect(page.getByText("콘센트 없이도 더운 순간 바로 꺼내 쓰는")).toBeVisible();
  await expect(page.getByText("fixture 데이터만 사용")).toBeVisible();

  await page.getByRole("button", { name: "화장품 예시" }).click();
  await expect(page.getByText("피부가 예민한 날에도 가볍게 시작하는 진정 루틴")).toBeVisible();

  expect(apiCalls).toEqual([]);
});
