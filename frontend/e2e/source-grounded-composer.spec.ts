import { test, expect } from "@playwright/test";

test("one-box intake lets seller start with freeform product material", async ({ page }) => {
  await page.route("**/api/agent-runs/structure-intake", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product_name: { value: "아이 LED 자전거", source: "freeform_input", confidence: "needs_review" },
        reference_urls: [],
        selling_points: [
          { text: "LED 조명", source: "freeform_input", confidence: "needs_review" },
          { text: "보조바퀴 탈착 가능", source: "freeform_input", confidence: "needs_review" },
        ],
        price: { value: "39,900원", source: "freeform_input", confidence: "needs_review" },
        shipping: { value: "무료배송", source: "freeform_input", confidence: "needs_review" },
        desired_mood: ["안전한", "감성적인"],
        warnings: [],
      }),
    });
  });

  await page.goto("/workspace");
  await page.getByLabel("상품 자료").fill(
    "아이 첫 자전거입니다. LED 조명이 있고 보조바퀴 탈착 가능해요. 가격은 39,900원이고 무료배송입니다."
  );
  await page.getByRole("button", { name: "자료 확인하기" }).click();

  await expect(page.getByText("AI가 이렇게 이해했어요")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "확인 상품명" })).toHaveValue("아이 LED 자전거");
  await expect(page.getByRole("textbox", { name: "핵심 특징 1", exact: true })).toHaveValue("LED 조명");
  await expect(page.getByRole("textbox", { name: "핵심 특징 2", exact: true })).toHaveValue("보조바퀴 탈착 가능");
});

test("review edits are sent in the generation payload", async ({ page }) => {
  let generationPayload: Record<string, unknown> | null = null;

  await page.route("**/api/agent-runs/structure-intake", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product_name: { value: "초기 상품명", source: "freeform_input", confidence: "needs_review" },
        description: { value: "초기 설명", source: "freeform_input", confidence: "needs_review" },
        reference_urls: ["https://reference.example.com/detail"],
        selling_points: [
          { text: "LED 조명", source: "freeform_input", confidence: "needs_review" },
          { text: "보조 바퀴", source: "freeform_input", confidence: "needs_review" },
        ],
        price: { value: "39,900원", source: "freeform_input", confidence: "needs_review" },
        shipping: { value: "무료배송", source: "freeform_input", confidence: "needs_review" },
        desired_mood: ["안전한"],
        warnings: [],
      }),
    });
  });
  await page.route("**/api/agent-runs", async (route) => {
    generationPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: "run-1", project_id: "project-1" }),
    });
  });

  await page.goto("/workspace");
  await page.locator("#freeform-input").fill("어린이 자전거");
  await page.locator("button[type='button']").filter({ hasText: "확인" }).first().click();
  await page.getByLabel("확인 상품명").fill("수정된 상품명");
  await page.getByLabel("핵심 특징 1", { exact: true }).fill("수정된 LED 조명");
  await page.getByLabel("핵심 특징 2 사용").uncheck();
  await page.getByLabel("확인 가격").fill("42,000원");
  await page.getByLabel("확인 배송").fill("조건부 무료배송");
  await page.getByLabel("확인 분위기").fill("안전한, 따뜻한");
  await page.getByRole("button", { name: "이 정보로 상세페이지 만들기" }).click();

  await expect.poll(() => generationPayload).not.toBeNull();
  expect(generationPayload).toMatchObject({
    product_name: "수정된 상품명",
    selling_points: ["수정된 LED 조명"],
    price: "42,000원",
    shipping: "조건부 무료배송",
    desired_mood: ["안전한", "따뜻한"],
    reference_urls: ["https://reference.example.com/detail"],
  });
});
