import { test, expect } from "@playwright/test";

test("seller can see and select image candidates", async ({ page }) => {
  // 1. Mock the agent runs API
  await page.route("**/api/agent-runs**", async (route) => {
    const url = route.request().url();

    if (url.endsWith("/run") || url.includes("/run-mock")) {
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
            product_name: "삼성 삼탠바이미 32인치 스마트모니터",
            asset_ids: [],
            reference_urls: [],
          },
          outputs: {
            image_generation: {
              candidates: {
                hero: [
                  {
                    candidate_id: "candidate-hero-default",
                    slot_id: "hero",
                    asset_id: "asset-default",
                    source_type: "mock-generated",
                    label: "목업 이미지",
                    is_recommended: true,
                    needs_identity_review: false,
                  },
                  {
                    candidate_id: "candidate-hero-uploaded",
                    slot_id: "hero",
                    asset_id: "asset-selected",
                    source_type: "uploaded",
                    label: "업로드 이미지",
                    is_recommended: false,
                    needs_identity_review: false,
                  }
                ]
              }
            },
            page_assembly: {
              sections: [
                {
                  id: "hero",
                  section_type: "hero",
                  title: "공간을 바꾸는 스마트 모니터",
                  body: "삼성 삼탠바이미 32인치 스마트모니터",
                  image_id: "asset-default",
                  visual_slot: {
                    asset_id: "asset-default",
                    source_type: "mock-generated",
                    status: "completed",
                    label: "목업 이미지"
                  }
                }
              ]
            }
          }
        }),
      });
      return;
    }

    // Default POST /api/agent-runs
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
          product_name: "삼성 삼탠바이미 32인치 스마트모니터",
          asset_ids: [],
          reference_urls: [],
        },
        outputs: {},
      }),
    });
  });

  // 2. Mock project page GET and PATCH APIs
  await page.route("**/v1/projects/*/page**", async (route) => {
    const method = route.request().method();
    
    if (method === "PATCH") {
      const payload = JSON.parse(route.request().postData() || "{}");
      const updatedAssetId = payload.sections?.[0]?.image_asset_id || "asset-default";
      
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "page-1",
          project_id: "project-1",
          theme_color: "#10B981",
          font_family: "sans-serif",
          sections: [
            {
              id: "hero",
              section_type: "hero",
              title: "공간을 바꾸는 스마트 모니터",
              body_copy: "삼성 삼탠바이미 32인치 스마트모니터",
              image_asset_id: updatedAssetId,
              sort_order: 0,
              is_visible: true,
            }
          ]
        })
      });
      return;
    }

    // Default GET
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-1",
        project_id: "project-1",
        theme_color: "#10B981",
        font_family: "sans-serif",
        sections: [
          {
            id: "hero",
            section_type: "hero",
            title: "공간을 바꾸는 스마트 모니터",
            body_copy: "삼성 삼탠바이미 32인치 스마트모니터",
            image_asset_id: "asset-default",
            sort_order: 0,
            is_visible: true,
            image_candidates: [
              {
                candidate_id: "candidate-hero-default",
                slot_id: "hero",
                asset_id: "asset-default",
                source_type: "mock-generated",
                label: "목업 이미지",
                is_recommended: true,
                needs_identity_review: false,
              },
              {
                candidate_id: "candidate-hero-uploaded",
                slot_id: "hero",
                asset_id: "asset-selected",
                source_type: "uploaded",
                label: "업로드 이미지",
                is_recommended: false,
                needs_identity_review: false,
              }
            ]
          }
        ]
      }),
    });
  });

  // 3. Mock project metadata and assets APIs for specific project IDs (using glob)
  await page.route("**/v1/projects/*", async (route) => {
    const url = route.request().url();
    // Exclude /page and /assets sub-routes to let their respective mocks handle them
    if (url.endsWith("/page") || url.endsWith("/assets")) {
      return route.fallback();
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "project-1",
        name: "삼성 삼탠바이미 32인치 스마트모니터",
        status: "completed"
      })
    });
  });

  await page.route("**/v1/projects/*/assets", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([])
    });
  });

  // Start E2E validation steps
  await page.goto("/workspace");
  await page.getByPlaceholder("상품명").fill("삼성 삼탠바이미 32인치 스마트모니터");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();
  
  // Wait for the "생성된 상세페이지 보기" button and click it
  const viewButton = page.getByRole("button", { name: "생성된 상세페이지 보기" }).first();
  await viewButton.waitFor({ state: "visible", timeout: 15000 });
  await viewButton.click();

  // Wait for result UI transition
  await expect(page.getByText("생성된 상세페이지 초안")).toBeVisible({ timeout: 15000 });

  // Validate image candidates UI components
  await expect(page.getByText("이미지 후보")).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("업로드 이미지").or(page.getByText("목업 이미지")).first()).toBeVisible();
});
