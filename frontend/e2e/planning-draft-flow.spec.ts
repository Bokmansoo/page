import { expect, test } from "@playwright/test";

const projectId = "project-123";

const planningCards = [
  {
    id: "card-1",
    type: "hero",
    label: "히어로 메시지",
    title: "처음 제목",
    bullets: ["처음 본문 포인트", "두 번째 포인트"],
    source_fact_ids: ["fact-1"],
    visual_strategy: "image_overlay",
    is_enabled: true,
    sort_order: 0,
  },
  {
    id: "card-2",
    type: "comparison",
    label: "비교 포인트",
    title: "비교 제목",
    bullets: ["비교 본문"],
    source_fact_ids: [],
    visual_strategy: "graphic_chart",
    is_enabled: true,
    sort_order: 1,
  },
];

test("Quality mode planning draft can be edited and approved", async ({ page }) => {
  let savedPayload: unknown = null;
  let approveCalled = false;

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, async (route) => {
    const method = route.request().method();

    if (method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ cards: planningCards }),
      });
      return;
    }

    if (method === "PATCH") {
      savedPayload = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(savedPayload),
      });
      return;
    }

    await route.fulfill({ status: 405 });
  });

  await page.route(`**/api/v1/projects/${projectId}/planning-draft/approve`, async (route) => {
    approveCalled = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "success" }),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/planning`);

  await expect(page.getByRole("heading", { name: "상세페이지 기획 검수" })).toBeVisible();
  await expect(page.getByText("히어로 메시지")).toBeVisible();

  await page.locator('input[value="처음 제목"]').fill("수정된 히어로 제목");
  await page.locator('input[value="처음 본문 포인트"]').fill("수정된 본문 포인트");
  await page.getByRole("button", { name: "상세페이지 조립하기 →" }).click();

  await expect.poll(() => approveCalled).toBe(true);
  expect(savedPayload).toMatchObject({
    cards: expect.arrayContaining([
      expect.objectContaining({
        id: "card-1",
        title: "수정된 히어로 제목",
        bullets: expect.arrayContaining(["수정된 본문 포인트"]),
      }),
    ]),
  });
  await expect(page).toHaveURL(new RegExp(`/workspace/projects/${projectId}/result`));
});
