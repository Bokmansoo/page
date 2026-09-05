import { expect, test } from "@playwright/test";

const projectId = "ux2c-photo-project";

test("UX-2C preserves auto placement, edits photos, confirms rights, and downloads page plus ZIP", async ({ page }) => {
  const main = {
    id: "owned-main", filename: "pillow-main.jpg", file_path: "/tmp/pillow-main.jpg",
    mime_type: "image/jpeg", source_type: "uploaded", usage_status: "seller_owned",
    asset_role: "product_main", is_representative: true,
  };
  const detail = {
    id: "owned-detail", filename: "pillow-heat-detail.jpg", file_path: "/tmp/pillow-heat-detail.jpg",
    mime_type: "image/jpeg", source_type: "uploaded", usage_status: "seller_owned",
    asset_role: "feature", is_representative: false,
    quality_warnings: ["SAFE_CROP_REVIEW_REQUIRED"],
  };
  const reference = {
    id: "reference-photo", filename: "supplier-reference.jpg", file_path: "/tmp/supplier-reference.jpg",
    mime_type: "image/jpeg", source_type: "sourced", usage_status: "reference_only",
    asset_role: "product_detail", is_representative: false,
  };
  let referenceApproved = false;
  let exportPayload: Record<string, unknown> | null = null;
  const candidate = (asset: typeof main, eligible: boolean) => ({
    candidate_id: `asset:${asset.id}`, slot_id: "hero", asset_id: asset.id,
    source_type: asset.source_type, usage_status: asset.usage_status,
    label: asset.filename, eligible, block_reason: eligible ? null : "Confirm rights before this photo can be used.",
    asset_role: asset.asset_role, is_recommended: asset.id === main.id,
    recommendation_reason: asset.id === main.id ? "Representative product photo" : null,
    needs_identity_review: false, status: eligible ? "available" : "blocked",
  });
  let currentSections = [
    {
      id: "hero", section_type: "hero", title: "Neck massage pillow", body_copy: "Verified product information.",
      image_asset_id: main.id, visual_kind: "image", visual_payload: { image_fit: "contain", ux2c_selection_state: "automatic" },
      sort_order: 0, is_visible: true, associated_fact_ids: ["fact-model"], associated_fact_texts: ["Model YL-T02"],
    },
    {
      id: "spec", section_type: "product_information", title: "Product information", body_copy: "Please check before purchase.",
      image_asset_id: null, visual_kind: "html_graphic", visual_payload: {
        layout_variant: "spec_table",
        table_rows: [{ label: "Model", value: "YL-T02", verification_status: "confirmed", source_fact_ids: ["fact-model"] }],
      },
      sort_order: 1, is_visible: true, associated_fact_ids: ["fact-model"], associated_fact_texts: ["Model YL-T02"],
    },
  ];
  let confirmedLowQualityHero: boolean | undefined;

  const responsePage = () => ({
    id: "page-1", project_id: projectId, theme_color: "#10B981", font_family: "sans-serif",
    sections: currentSections.map((section) => ({
      ...section,
      image_candidates: [
        candidate(main, true),
        candidate(detail, true),
        candidate({ ...reference, usage_status: referenceApproved ? "seller_owned" : "reference_only" }, referenceApproved),
      ],
    })),
  });

  await page.route(`**/api/v1/projects/${projectId}`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: projectId, name: "Neck massage pillow", status: "completed" }) }));
  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    if (route.request().method() === "PATCH") {
      const patchPayload = route.request().postDataJSON() as {
        sections: typeof currentSections;
        confirm_low_quality_hero?: boolean;
      };
      confirmedLowQualityHero = patchPayload.confirm_low_quality_hero;
      const updates = patchPayload.sections;
      currentSections = currentSections.map((section) => ({ ...section, ...(updates.find((item: { id: string }) => item.id === section.id) || {}) }));
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(responsePage()) });
  });
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify([main, detail, reference]) }));
  await page.route(`**/api/v1/projects/${projectId}/asset-inspections`, (route) => route.fulfill({ contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/asset-understanding-readiness`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ready: true, blockers: [] }) }));
  await page.route(`**/api/v1/files/assets/**`, (route) => route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64") }));
  await page.route(`**/api/v1/files/assets/${reference.id}/usage-status`, (route) => {
    referenceApproved = true;
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...reference, usage_status: "seller_owned" }) });
  });
  await page.route(`**/api/v1/projects/${projectId}/page/finalize`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "final-ux2c" }) }));
  await page.route(`**/api/v1/projects/${projectId}/page/export`, (route) => {
    exportPayload = route.request().postDataJSON();
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "job-ux2c", status: "completed", output_images: ["/downloads/page.png", "/downloads/page.zip"] }) });
  });
  await page.route("**/downloads/page.png", (route) => route.fulfill({ contentType: "image/png", headers: { "content-disposition": "attachment; filename=page.png" }, body: "png" }));
  await page.route("**/downloads/page.zip", (route) => route.fulfill({ contentType: "application/zip", headers: { "content-disposition": "attachment; filename=page.zip" }, body: "zip" }));
  await page.route("**/api/v1/export/channel-presets", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [] }) }));

  await page.goto(`/workspace/projects/${projectId}/result`);
  await expect(page.getByTestId(`ux2c-use-hero-${main.id}`)).toBeDisabled();
  await expect(page.getByText("Model YL-T02").first()).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId(`ux2c-use-hero-${detail.id}`).click();
  await expect.poll(() => currentSections[0].image_asset_id).toBe(detail.id);
  await expect.poll(() => currentSections[0].visual_kind).toBe("image");
  expect(confirmedLowQualityHero).toBe(true);

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId(`ux2c-confirm-hero-${reference.id}`).click();
  await expect.poll(() => referenceApproved).toBe(true);

  await page.getByTestId("ux2c-visibility-hero").click();
  await expect.poll(() => currentSections[0].is_visible).toBe(false);

  const downloads: string[] = [];
  page.on("download", (download) => downloads.push(download.suggestedFilename()));
  await page.getByRole("button", { name: "PNG로 다운로드" }).click();
  await expect.poll(() => downloads.length, { timeout: 10_000 }).toBe(2);
  expect(downloads[0]).toMatch(/\.png$/);
  expect(downloads[1]).toMatch(/\.zip$/);
  expect(exportPayload?.final_version_id).toBe("final-ux2c");
  expect(exportPayload?.output_format).toBe("png");
});
