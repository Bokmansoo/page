import { expect, test } from "@playwright/test";

const projectId = "ux2-mock-project";

test("UX-2B result edits grounded Korean copy before PNG download", async ({ page }) => {
  const fact = { verification_status: "confirmed", source_fact_ids: ["fact-1"] };
  const sections = [
    { id: "hero", section_type: "hero", title: "목과 어깨 사용을 고려한 마사지기", body_copy: "판매자가 확인한 제품 사양을 한눈에 정리했습니다.", image_asset_id: null, visual_kind: "html_graphic", visual_payload: { layout_variant: "image_text", mock_safe_hero: true, ux2_mock_output: true }, sort_order: 0, is_visible: true, associated_fact_ids: [], associated_fact_texts: [] },
    ...[["feature_1", "배터리 용량", "2000mAh"], ["feature_2", "정격 소비전력", "8W"], ["feature_3", "제품 크기", "40 × 17 × 15cm"]].map(([sectionType, title, value], index) => ({ id: sectionType, section_type: sectionType, title, body_copy: `${title}은 ${value}입니다.`, image_asset_id: null, visual_kind: "html_graphic", visual_payload: { layout_variant: "benefit_cards", cards: [{ title, body: value, ...fact }], ux2_mock_output: true }, sort_order: index + 1, is_visible: true, associated_fact_ids: [`fact-${index + 1}`], associated_fact_texts: [`${title}: ${value}`] })),
    { id: "usage", section_type: "usage_guide", title: "전원·사용 정보 확인", body_copy: "정격 소비전력은 8W입니다.", image_asset_id: null, visual_kind: "html_graphic", visual_payload: { layout_variant: "image_text", ux2_mock_output: true }, sort_order: 4, is_visible: true, associated_fact_ids: ["fact-2"], associated_fact_texts: ["정격 소비전력: 8W"] },
    { id: "spec", section_type: "product_information", title: "제품 사양·주의사항·필수 고지", body_copy: "모델과 규격을 구매 전에 확인해 주세요.", image_asset_id: null, visual_kind: "html_graphic", visual_payload: { layout_variant: "spec_table", table_rows: [{ label: "정격 소비전력", value: "8W", ...fact }], ux2_mock_output: true }, sort_order: 5, is_visible: true, associated_fact_ids: ["fact-2"], associated_fact_texts: ["정격 소비전력: 8W"] },
  ];
  let currentSections = sections;

  await page.route(`**/api/v1/projects/${projectId}`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: projectId, name: "마사지기", status: "completed" }) }));
  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    if (route.request().method() === "PATCH") {
      const updates = route.request().postDataJSON().sections;
      currentSections = currentSections.map((section) => ({
        ...section,
        ...(updates.find((update: { id: string }) => update.id === section.id) || {}),
      }));
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "page-1", project_id: projectId, theme_color: "#10B981", font_family: "sans-serif", sections: currentSections }) });
  });
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ contentType: "application/json", body: "[]" }));
  await page.route("**/api/v1/export/channel-presets", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: [] }) }));
  await page.route(`**/api/v1/projects/${projectId}/page/finalize`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "final-1", project_id: projectId, is_final: true }) }));
  await page.route(`**/api/v1/projects/${projectId}/page/export`, (route) => route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ id: "export-1", project_id: projectId, status: "pending", output_images: null }) }));
  await page.route(`**/api/v1/projects/${projectId}/page/export/jobs/export-1`, (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "export-1", project_id: projectId, status: "completed", output_images: [`/api/v1/projects/${projectId}/page/export/download/mock-png`] }) }));
  await page.route(`**/api/v1/projects/${projectId}/page/export/download/mock-png`, (route) => route.fulfill({ contentType: "image/png", headers: { "Content-Disposition": "attachment; filename*=UTF-8''ux2b-mock.png" }, body: Buffer.from("png") }));

  await page.goto(`/workspace/projects/${projectId}/result`);
  await expect(page.getByRole("heading", { name: "완성된 상세페이지" })).toBeVisible();
  await expect(page.getByText("사진 필요", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "제품 크기" }).first()).toBeVisible();
  await expect(page.getByText("8W", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "문구 수정" }).first().click();
  await page.getByLabel("제목").fill("목과 어깨 사용을 고려한 온열 마사지 베개");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("heading", { name: "목과 어깨 사용을 고려한 온열 마사지 베개" })).toBeVisible();
  expect(currentSections[0].title).toBe("목과 어깨 사용을 고려한 온열 마사지 베개");

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "PNG로 다운로드" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.png$/);
});
