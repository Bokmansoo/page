import { test, expect } from "@playwright/test";

test("mock mode creates a complete detail page draft", async ({ page }) => {
  await page.route("**/api/agent-runs**", async (route) => {
    const url = route.request().url();

    if (url.endsWith("/run-mock")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "run-1",
          project_id: "project-1",
          workspace_id: "workspace-1",
          mode: "mock",
          current_stage: "review_editor",
          product_input: {
            product_name: "유아 자전거",
            asset_ids: [],
            reference_urls: [],
          },
          outputs: {
            sales_strategy: {
              hook_headline: "아이의 첫 페달링을 안심으로 시작하세요",
              tone_and_manner: "따뜻하고 신뢰감 있는 판매 문구",
            },
            visual_plan: {
              color_palette: ["#10B981", "#14B8A6", "#FFFFFF", "#F3F4F6"],
            },
            generated_assets: {
              images: [
                { id: "hero", url: "/mock-hero.jpg", source_type: "uploaded" },
                { id: "comparison", url: "/mock-comparison.jpg", source_type: "URL-extracted" },
                { id: "detail", url: "/mock-detail.jpg", source_type: "mock-generated" },
                { id: "pending", url: "/mock-pending.jpg", source_type: "pending real generation" },
              ],
            },
            page_assembly: {
              sections: [
                {
                  id: "section-1",
                  title: "안심하고 태우는 우리 아이 첫 유아 자전거",
                  body: "튼튼한 보조 바퀴로 첫 주행을 돕습니다.",
                  visual_role: "첫인상",
                  image_id: "hero",
                },
                {
                  id: "section-2",
                  title: "상품 비교",
                  body: "구매 전 차이를 쉽게 확인하세요.",
                  visual_role: "비교",
                  image_id: "comparison",
                },
                {
                  id: "section-3",
                  title: "안전 설계",
                  body: "아이를 위한 세부 설계를 보여드립니다.",
                  visual_role: "상세",
                  image_id: "detail",
                },
                {
                  id: "section-4",
                  title: "추가 이미지",
                  body: "실제 이미지 생성 단계에서 교체됩니다.",
                  visual_role: "생성 예정",
                  image_id: "pending",
                },
              ],
            },
          },
        }),
      });
      return;
    }

    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "run-1",
        project_id: "project-1",
        workspace_id: "workspace-1",
        mode: "mock",
        current_stage: "intake",
        product_input: {
          product_name: "유아 자전거",
          asset_ids: [],
          reference_urls: [],
        },
        outputs: {},
      }),
    });
  });

  await page.goto("/workspace");
  await page.getByPlaceholder("상품명").fill("유아 자전거");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();

  await expect(page.getByText("상세페이지 초안 미리보기")).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("안심하고 태우는 우리 아이 첫 유아 자전거")).toBeVisible();

  await expect(page.getByText("출처: AI 모의 생성").first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("출처: 직접 업로드")).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("출처: URL 추출")).toBeVisible();
  await expect(page.getByText("출처: 생성 대기 중")).toBeVisible();

  const resultCta = page.getByRole("button", { name: "생성된 상세페이지 보기" });
  await expect(resultCta).toBeVisible();
  await expect(resultCta).toHaveClass(/bg-emerald-600/);
  await expect(resultCta).not.toHaveClass(/bg-gradient-to-r/);
});
