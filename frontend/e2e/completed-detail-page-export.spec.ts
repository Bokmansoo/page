import { expect, test } from "@playwright/test";

const projectId = "completed-detail-page-project";

test("shows a completed page and downloads PNG/JPG via browser download", async ({ page }) => {
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: projectId, name: "삼탠바이미", status: "completed" }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-1",
        project_id: projectId,
        theme_color: "#2F6B4F",
        font_family: "sans-serif",
        sections: [
          {
            id: "hero-section",
            section_type: "hero",
            title: "공간마다 따라오는 나만의 화면",
            body_copy: "거실과 침실을 오가며 편하게 즐겨보세요.",
            image_asset_id: "hero-generated",
            sort_order: 0,
            is_visible: true,
            image_candidates: [
              {
                candidate_id: "hero-generated-candidate",
                slot_id: "hero",
                asset_id: "hero-generated",
                source_type: "real-generated",
                label: "거실 사용 장면",
                is_recommended: true,
                needs_identity_review: false,
              },
            ],
          },
          {
            id: "detail-section",
            section_type: "detail_1",
            title: "시선에 맞춰 움직이는 스탠드",
            body_copy: "소파와 책상에서 화면 각도를 편하게 맞춥니다.",
            image_asset_id: "detail-generated",
            sort_order: 1,
            is_visible: true,
            image_candidates: [
              {
                candidate_id: "detail-generated-candidate",
                slot_id: "detail_1",
                asset_id: "detail-generated",
                source_type: "real-generated",
                label: "각도 조절 장면",
                is_recommended: true,
                needs_identity_review: false,
              },
            ],
          },
        ],
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "hero-generated",
          filename: "hero.png",
          file_path: "",
          mime_type: "image/png",
          source_type: "real-generated",
        },
        {
          id: "detail-generated",
          filename: "detail.png",
          file_path: "",
          mime_type: "image/png",
          source_type: "real-generated",
        },
      ]),
    });
  });

  await page.route("**/api/v1/files/assets/hero-generated", async (route) => {
    await route.fulfill({ contentType: "image/png", body: Buffer.from("hero-image") });
  });
  await page.route("**/api/v1/files/assets/detail-generated", async (route) => {
    await route.fulfill({ contentType: "image/png", body: Buffer.from("detail-image") });
  });

  await page.route(`**/api/v1/projects/${projectId}/page/finalize`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "final-v1",
        project_id: projectId,
        name: "Final",
        style_key: "minimal",
        sections_json: {},
        is_final: true,
        created_at: "2026-07-04T00:00:00",
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page/export`, async (route) => {
    const requestedFormat = route.request().postDataJSON().output_format as "png" | "jpg";
    expect(route.request().postDataJSON()).toMatchObject({
      preset_name: "smartstore",
      output_format: requestedFormat,
      export_target: "local_download",
    });
    expect(["png", "jpg"]).toContain(requestedFormat);
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        id: `export-${requestedFormat}`,
        project_id: projectId,
        preset_name: "smartstore",
        status: "pending",
        error_message: null,
        zip_asset_id: null,
        output_images: null,
        created_at: "2026-07-04T00:00:00",
        completed_at: null,
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page/export/jobs/**`, async (route) => {
    const jobId = route.request().url().split("/").pop() || "export-png";
    const requestedFormat = jobId.endsWith("jpg") ? "jpg" : "png";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: jobId,
        project_id: projectId,
        preset_name: "smartstore",
        status: "completed",
        error_message: null,
        zip_asset_id: "zip-1",
        output_images: [
          `/api/v1/projects/${projectId}/page/export/download/export-image-${requestedFormat}`,
        ],
        created_at: "2026-07-04T00:00:00",
        completed_at: "2026-07-04T00:00:01",
      }),
    });
  });

  await page.route(
    `**/api/v1/projects/${projectId}/page/export/download/**`,
    async (route) => {
      const requestedFormat = route.request().url().endsWith("jpg") ? "jpg" : "png";
      await route.fulfill({
        contentType: requestedFormat === "jpg" ? "image/jpeg" : "image/png",
        headers: {
          "Content-Disposition": `attachment; filename="sellform-long.${requestedFormat}"`,
        },
        body: Buffer.from(`${requestedFormat}-download`),
      });
    }
  );

  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.getByRole("heading", { name: "완성된 상세페이지" })).toBeVisible();
  await expect(page.getByAltText("공간마다 따라오는 나만의 화면")).toHaveAttribute("src", /hero-generated/);

  // Test PNG download via browser download event
  const pngDownloadPromise = page.waitForEvent("download");
  await page.getByLabel("저장 형식").selectOption("png");
  await page.getByRole("button", { name: "PNG로 다운로드" }).click();
  const pngDownload = await pngDownloadPromise;
  expect(pngDownload.suggestedFilename()).toMatch(/\.png$/);

  // Test JPG download via browser download event
  const jpgDownloadPromise = page.waitForEvent("download");
  await page.getByLabel("저장 형식").selectOption("jpg");
  await page.getByRole("button", { name: "JPG로 다운로드" }).click();
  const jpgDownload = await jpgDownloadPromise;
  expect(jpgDownload.suggestedFilename()).toMatch(/\.jpg$/);
});
