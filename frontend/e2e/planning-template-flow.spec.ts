import { expect, test } from "@playwright/test";

const projectId = "template-flow-project";

test("creates and manipulates general sales and problem solving templates", async ({ page }) => {
  let patchPayload: any = null;
  let approveCalled = false;

  // Mock project API
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: projectId,
        name: "스마트 무선 선풍기",
        status: "processing",
        category: "Living",
        intake_snapshot: {
          selling_purpose: "제품 스펙 비교 및 안내"
        }
      }),
    });
  });

  // Mock planning-draft API
  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, async (route) => {
    if (route.request().method() === "PATCH") {
      patchPayload = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(patchPayload),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          template_id: "general_sales",
          template_name: "기본 판매형",
          cards: [
            {
              id: "card-problem",
              type: "problem",
              label: "문제 제기",
              title: "더운 날, 손이 가는 선풍기는 따로 있죠",
              bullets: ["책상, 차량, 야외처럼 전원 연결이 번거로운 순간에도 바로 꺼내 쓸 수 있어야 합니다."],
              source_fact_ids: [],
              visual_strategy: "text_only",
              is_enabled: true,
              sort_order: 0,
            },
            {
              id: "card-hero",
              type: "hero",
              label: "메인 소구점 강조",
              title: "콘센트 없이 언제 어디서나 바로 꺼내 쓰는 시원함",
              bullets: ["가볍고 콤팩트하여 휴대가 편리한 스마트 무선 선풍기입니다."],
              source_fact_ids: [],
              visual_strategy: "image_overlay",
              is_enabled: true,
              sort_order: 1,
            }
          ]
        }),
      });
    }
  });

  // Mock planning-draft/approve API
  await page.route(`**/api/v1/projects/${projectId}/planning-draft/approve`, async (route) => {
    approveCalled = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "success" }),
    });
  });

  // 1. Visit the planning page
  await page.goto(`/workspace/projects/${projectId}/planning`);

  // Verify elements
  await expect(page.locator("h2")).toContainText("상세페이지 기획 검수");
  
  // Verify card labels (internal roles)
  await expect(page.getByText("문제 제기")).toBeVisible();
  await expect(page.getByText("메인 소구점 강조")).toBeVisible();

  // Hide the second card (disable it)
  await page.getByRole("button", { name: "숨기기" }).first().click();

  // Reorder: move the first card down
  await page.locator("button[aria-label='문제 제기 아래로 이동']").click();

  // Click temporary save
  await page.getByRole("button", { name: "임시 저장" }).first().click();
  await expect(page.getByText("기획안이 임시 저장되었습니다.")).toBeVisible();

  // Click approve to submit and wait for the API response
  const approvePromise = page.waitForResponse(resp => resp.url().includes("/planning-draft/approve") && resp.request().method() === "POST");
  await page.getByRole("button", { name: "상세페이지 조립하기 →" }).first().click();
  await approvePromise;
  expect(approveCalled).toBe(true);
});
