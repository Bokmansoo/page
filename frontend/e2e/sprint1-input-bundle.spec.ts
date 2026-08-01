import { expect, test } from "@playwright/test";

const image = (name: string) => ({
  name,
  mimeType: "image/png",
  buffer: Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Jv5QAAAAASUVORK5CYII=",
    "base64",
  ),
});

test("accepts five product images at once and lets the seller reorder them", async ({ page }) => {
  await page.goto("/workspace");

  await page.locator("#product-images").setInputFiles([
    image("01-hero.png"),
    image("02-feature.png"),
    image("03-usage.png"),
    image("04-components.png"),
    image("05-spec.png"),
  ]);

  await expect(page.getByText("5 / 20장")).toBeVisible();
  await expect(page.getByText("상품 사진 5장 준비 완료.", { exact: false })).toBeVisible();
  await expect(page.getByText("01-hero.png")).toBeVisible();
  await expect(page.getByText("05-spec.png")).toBeVisible();

  await page.getByRole("button", { name: "1번째 사진 뒤로" }).click();

  const cards = page.locator("ol > li");
  await expect(cards.nth(0)).toContainText("02-feature.png");
  await expect(cards.nth(1)).toContainText("01-hero.png");
});

test("keeps numeric values and units unchanged on the seller review screen", async ({ page }) => {
  const exactDescription = "무게 260g, 사용 시간 10분, 배터리 용량 800mAh, 온도 42°C";

  await page.route("**/api/agent-runs/structure-intake", async (route) => {
    const request = route.request();
    const payload = request.postDataJSON() as { description?: string };
    expect(payload.description).toContain(exactDescription);

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product_name: {
          value: "미니 마사지건",
          source: "explicit_field",
          confidence: "confirmed",
        },
        description: {
          value: payload.description,
          source: "explicit_field",
          confidence: "confirmed",
        },
        product_url: { value: "", source: "explicit_field", confidence: "confirmed" },
        reference_urls: [],
        selling_points: [],
        price: { value: "", source: "explicit_field", confidence: "confirmed" },
        shipping: { value: "", source: "explicit_field", confidence: "confirmed" },
        desired_mood: ["깔끔한"],
        asset_ids: [],
        warnings: [],
      }),
    });
  });

  await page.goto("/workspace");
  await page.locator("#product-images").setInputFiles(image("representative.png"));
  await page.getByPlaceholder("상품명", { exact: true }).fill("미니 마사지건");
  await page.getByPlaceholder("간단한 설명", { exact: false }).fill(exactDescription);
  await page.getByRole("button", { name: "자료 확인하기" }).click();

  await expect(page.getByLabel("확인 상세 정보")).toHaveValue(/260g/);
  await expect(page.getByLabel("확인 상세 정보")).toHaveValue(/10분/);
  await expect(page.getByLabel("확인 상세 정보")).toHaveValue(/800mAh/);
  await expect(page.getByLabel("확인 상세 정보")).toHaveValue(/42°C/);
});

test("shows model options, image order, and rights before final confirmation", async ({ page }) => {
  await page.route("**/api/agent-runs/structure-intake", async (route) => {
    const payload = route.request().postDataJSON() as { description?: string };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        product_name: { value: "YL-T02 마사지 베개", source: "explicit_field", confidence: "confirmed" },
        description: { value: payload.description, source: "explicit_field", confidence: "confirmed" },
        reference_urls: [],
        selling_points: [],
        price: { value: "", source: "explicit_field", confidence: "confirmed" },
        shipping: { value: "", source: "explicit_field", confidence: "confirmed" },
        desired_mood: ["깔끔한"],
        asset_ids: [],
        warnings: [],
      }),
    });
  });

  await page.goto("/workspace");
  await page.locator("#product-images").setInputFiles([image("01-main.png"), image("02-supplier.png")]);
  await page.getByLabel("2번째 사진 출처와 권리").selectOption("sourced");
  await page.getByPlaceholder("상품명", { exact: true }).fill("YL-T02 마사지 베개");
  await page.getByPlaceholder("간단한 설명", { exact: false }).fill("정격 출력 8W");
  await page.getByPlaceholder("예: 쿠팡, 스마트스토어, 자사몰").fill("쿠팡");
  await page.getByPlaceholder("예: YL-T02 / 그레이, 단품").fill("YL-T02 / 그레이");
  await page.getByRole("button", { name: "자료 확인하기" }).click();

  await expect(page.getByText("쿠팡", { exact: true })).toBeVisible();
  await expect(page.getByText("YL-T02 / 그레이", { exact: true })).toBeVisible();
  await expect(page.getByText("1. 01-main.png · 직접 촬영·보유", { exact: true })).toBeVisible();
  await expect(page.getByText("2. 02-supplier.png · 공급처 참고용", { exact: true })).toBeVisible();
});
