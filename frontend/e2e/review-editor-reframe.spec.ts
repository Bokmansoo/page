import { test, expect } from "@playwright/test";

test("generated detail page CTA opens white-first result screen", async ({ page }) => {
  // Mock agent-runs endpoints for generation flow
  await page.route("**/api/agent-runs**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/run")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "run-53",
          project_id: "project-53",
          workspace_id: "workspace-1",
          mode: "mock",
          current_stage: "review_editor",
          product_input: {
            product_name: "삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
            asset_ids: [],
            reference_urls: [],
          },
          outputs: {
            sales_strategy: {
              hook_headline: "삼탠바이미로 즐기는 나만의 스마트 라이프",
              tone_and_manner: "세련되고 실용적인 문구",
            },
            visual_plan: {
              color_palette: ["#10B981", "#14B8A6", "#FFFFFF", "#F3F4F6"],
            },
            generated_assets: {
              images: [
                { id: "hero", url: "/mock-hero.jpg", source_type: "uploaded" },
              ],
            },
            page_assembly: {
              sections: [
                {
                  id: "section-1",
                  title: "삼성 삼탠바이미 스마트모니터",
                  body: "스탠드형으로 이동이 편리합니다.",
                  visual_role: "대표",
                  image_id: "hero",
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
        id: "run-53",
        project_id: "project-53",
        workspace_id: "workspace-1",
        mode: "mock",
        current_stage: "intake",
        product_input: {
          product_name: "삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
          asset_ids: [],
          reference_urls: [],
        },
        outputs: {},
      }),
    });
  });

  // Mock project detail endpoint
  await page.route("**/api/v1/projects/project-53", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "project-53",
        name: "삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
        status: "package_ready",
      }),
    });
  });

  // Mock project page endpoint
  await page.route("**/api/v1/projects/project-53/page", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-53",
        project_id: "project-53",
        theme_color: "#3B82F6",
        font_family: "sans-serif",
        sections: [
          {
            id: "sec-1",
            section_type: "hero",
            title: "삼성 삼탠바이미 스마트모니터",
            body_copy: "스탠드형으로 이동이 편리합니다.",
            image_asset_id: "hero",
            sort_order: 0,
            is_visible: true,
          },
        ],
      }),
    });
  });

  // Mock project assets endpoint
  await page.route("**/api/v1/projects/project-53/assets", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "hero",
          filename: "mock-hero.jpg",
          file_path: "mock-hero.jpg",
          mime_type: "image/jpeg",
          source_type: "uploaded",
        },
      ]),
    });
  });

  await page.goto("/workspace");

  await page.getByPlaceholder("상품명").fill("삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  await page.getByRole("button", { name: "생성된 상세페이지 보기" }).first().click();

  await expect(page).toHaveURL(/\/workspace\/projects\/.+\/result$/);
  await expect(page.getByText("생성된 상세페이지 초안")).toBeVisible();
  await expect(page.getByText("삼탠바이미").first()).toBeVisible();
  await expect(page.getByText("셀폼 상세페이지 가이드 에디터 1.0")).not.toBeVisible();
});

test("page editor redirects or explains when no generated page exists", async ({ page }) => {
  // Mock project detail endpoint with status 'intake_received' or 'intake'
  await page.route("**/api/v1/projects/mock-project-without-assembly", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "mock-project-without-assembly",
        name: "삼성 삼탠바이미 32인치 스마트모니터",
        status: "intake_received",
      }),
    });
  });

  // Mock page endpoint to return 404 to simulate no generated page
  await page.route("**/api/v1/projects/mock-project-without-assembly/page", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Page not found" }),
    });
  });

  await page.goto("/workspace/projects/mock-project-without-assembly/page-editor");
  await expect(page.getByText("아직 생성된 상세페이지가 없습니다")).toBeVisible();
  await expect(page.getByRole("link", { name: "AI 상세페이지 만들기" })).toBeVisible();
});

test("review editor layout, elements, and mock AI edits", async ({ page }) => {
  // Mock project detail endpoint
  await page.route("**/api/v1/projects/project-53", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "project-53",
        name: "삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
        status: "package_ready",
      }),
    });
  });

  // Mock project page endpoint
  await page.route("**/api/v1/projects/project-53/page", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-53",
        project_id: "project-53",
        theme_color: "#3B82F6",
        font_family: "sans-serif",
        sections: [
          {
            id: "sec-1",
            section_type: "hero",
            title: "삼성 삼탠바이미 스마트모니터",
            body_copy: "스탠드형으로 이동이 편리합니다.",
            image_asset_id: "hero",
            sort_order: 0,
            is_visible: true,
          },
        ],
      }),
    });
  });

  // Mock project assets endpoint
  await page.route("**/api/v1/projects/project-53/assets", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "hero",
          filename: "mock-hero.jpg",
          file_path: "mock-hero.jpg",
          mime_type: "image/jpeg",
          source_type: "uploaded",
        },
      ]),
    });
  });

  // Mock AI edit command endpoint
  await page.route("**/api/v1/projects/project-53/pages/ai-edit", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        version_id: "ver-53-edited",
        status: "mock_applied",
      }),
    });
  });

  await page.goto("/workspace/projects/project-53/page-editor?mode=review");

  // Verify elements on ReviewEditorLayout
  await expect(page.getByText("생성된 상세페이지 검수")).toBeVisible();
  await expect(page.getByText("상세페이지 아웃라인")).toBeVisible();
  
  // Verify command panel elements
  await expect(page.getByRole("button", { name: "더 자연스럽게" })).toBeVisible();
  await expect(page.getByPlaceholder("AI에게 수정 요청하기")).toBeVisible();

  // First select a section
  await page.getByText("삼성 삼탠바이미 스마트모니터").first().click();

  // Trigger AI edit command
  await page.getByPlaceholder("AI에게 수정 요청하기").fill("제목을 더 매력적으로");
  await page.getByRole("button", { name: "전송" }).click();

  // Verify feedback message
  await expect(page.getByText("AI 수정이 성공적으로 반영되었습니다.")).toBeVisible();
});
