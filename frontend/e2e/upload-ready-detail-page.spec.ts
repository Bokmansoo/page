import { expect, test } from "@playwright/test";

test("result page renders image overlays and html graphics as export-ready visuals", async ({
  page,
}) => {
  const projectId = "project-visual-test";

  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: projectId,
        name: "루메나 휴대용 무선 냉각선풍기",
        status: "completed",
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "hero",
          filename: "hero.png",
          file_path: "",
          mime_type: "image/png",
          source_type: "uploaded",
        },
        {
          id: "lifestyle",
          filename: "lifestyle.png",
          file_path: "",
          mime_type: "image/png",
          source_type: "ai-generated",
        },
      ]),
    });
  });

  const onePixelPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64"
  );

  await page.route(`**/api/v1/files/assets/hero`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: onePixelPng,
    });
  });

  await page.route(`**/api/v1/files/assets/lifestyle`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: onePixelPng,
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({}),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-1",
        project_id: projectId,
        theme_color: "#2FAE73",
        font_family: "sans-serif",
        sections: [
          {
            id: "sec-hero",
            section_type: "hero",
            title:
              "콘센트 없어도 냉풍 컨셉으로 답답함을 식혀주는 휴대용 무선 냉각선풍기",
            body_copy:
              "방, 침대 옆, 차량, 야외까지 더운 순간에 바로 켜서 사용하세요.",
            image_asset_id: "hero",
            visual_kind: "image",
            visual_payload: {
              layout_variant: "hero_overlay",
              eyebrow: "HERO",
              badges: ["무선", "냉풍 컨셉"],
            },
            sort_order: 0,
            is_visible: true,
          },
          {
            id: "sec-comparison",
            section_type: "comparison",
            title: "더운데 선풍기만으로 답답하고, 전원 찾기도 번거로워요",
            body_copy: "콘센트가 멀거나 이동 중일 때 바로 쓰기 어렵습니다.",
            image_asset_id: null,
            visual_kind: "html_graphic",
            visual_payload: {
              layout_variant: "comparison_cards",
              cards: [
                { title: "유선", body: "전원 위치에 사용이 묶여요", tone: "muted" },
                { title: "무선", body: "간편한 이동", tone: "positive" },
              ],
            },
            sort_order: 1,
            is_visible: true,
          },
          {
            id: "sec-detail-1",
            section_type: "detail_1",
            title: "무선이라 필요한 순간에 바로 사용",
            body_copy: "충전 후 들고 다니며 켜기만 하면 됩니다.",
            image_asset_id: null,
            visual_kind: "html_graphic",
            visual_payload: {
              layout_variant: "benefit_cards",
              cards: [{ title: "필요한 시간", body: "바로 사용", tone: "positive" }],
            },
            sort_order: 2,
            is_visible: true,
          },
          {
            id: "sec-detail-2",
            section_type: "detail_2",
            title: "침대 옆과 차량에서도 이어지는 바람",
            body_copy: "실내와 이동 환경에 맞춰 사용할 수 있습니다.",
            image_asset_id: "lifestyle",
            visual_kind: "image",
            visual_payload: {
              layout_variant: "image_text",
              eyebrow: "DETAIL",
              badges: ["생활 장면"],
            },
            sort_order: 3,
            is_visible: true,
          },
          {
            id: "sec-guarantee",
            section_type: "guarantee",
            title: "구매 전 확인하세요",
            body_copy: "구매 전 확인해야 할 핵심 정보를 정리했습니다.",
            image_asset_id: null,
            visual_kind: "html_graphic",
            visual_payload: {
              layout_variant: "spec_table",
              table_rows: [
                {
                  label: "충전 방식",
                  value: "상세페이지 기준으로 확인",
                  verification_status: "needs_review",
                },
              ],
            },
            sort_order: 4,
            is_visible: true,
          },
        ],
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page/finalize`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "final-v1" }),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.locator('[data-detail-page-document="true"]')).toBeVisible();
  await expect(page.locator('[data-section-visual="html_graphic"]')).toHaveCount(3);
  await expect(page.locator('[data-section-visual="image"]')).toHaveCount(2);

  await expect(page.getByText("간편한 이동")).toBeVisible();
  await expect(page.getByText("충전 방식")).toBeVisible();
  await expect(page.getByText("이미지 확인이 필요합니다")).toHaveCount(0);

  const firstImageVisual = page.locator('[data-section-visual="image"]').first();
  await expect(firstImageVisual.getByText("HERO")).toBeVisible();
  await expect(firstImageVisual.getByText("콘센트 없어도 냉풍 컨셉")).toBeVisible();
  await expect(firstImageVisual.locator("span", { hasText: /^무선$/ })).toBeVisible();

  await expect(page.getByRole("button", { name: /PNG로 저장하기/ })).toBeEnabled();
});

test("blocks export readiness when a required image fails", async ({ page }) => {
  const projectId = "export-block-test";

  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: projectId, name: "Export Block", status: "completed" }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "broken", filename: "broken.png", file_path: "", mime_type: "image/png", source_type: "uploaded" },
      ]),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "page-1",
          project_id: projectId,
          theme_color: "#2FAE73",
          font_family: "sans-serif",
          sections: [
            {
              id: "sec-hero",
              section_type: "hero",
              title: "Broken Image Test",
              body_copy: "Testing",
              image_asset_id: "broken",
              visual_kind: "image",
              visual_payload: { layout_variant: "hero_overlay" },
              sort_order: 0,
              is_visible: true,
            },
          ],
        }),
      });
    } else {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    }
  });

  await page.route(`**/api/v1/projects/${projectId}/page/final**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "final-v1",
        sections_json: {
          theme_color: "#2FAE73",
          font_family: "sans-serif",
          sections: [
            {
              id: "sec-hero",
              section_type: "hero",
              title: "Broken Image Test",
              body_copy: "Testing",
              image_asset_id: "broken",
              visual_kind: "image",
              visual_payload: { layout_variant: "hero_overlay" },
              sort_order: 0,
              is_visible: true,
            },
          ],
        },
      }),
    });
  });

  // Abort the image request to simulate failure
  await page.route("**/api/v1/files/assets/broken", (route) => route.abort());

  // Navigate to render route
  await page.goto(`/workspace/projects/${projectId}/render?version_id=version-1`);

  // Wait for the render page to load and export readiness to be set
  await page.waitForSelector("[data-detail-page-document='true']", { timeout: 10000 });

  // After rendering, check the export readiness state
  await expect(page.locator("html")).toHaveAttribute("data-export-ready", "error");
  await expect(page.getByText("필수 이미지를 불러오지 못했습니다")).toBeVisible();
});
