import { expect, test } from "@playwright/test";

const projectId = "sprint4-html-graphics-project";

test("renders fact-grounded HTML graphics without mobile clipping", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });

  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: projectId, name: "HTML 그래픽 상품", status: "completed" }) });
  });
  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([]) });
  });
  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "page-sprint4",
        project_id: projectId,
        theme_color: "#2F6B4F",
        font_family: "sans-serif",
        sections: [
          {
            id: "benefit", section_type: "detail_1", title: "긴 제목도 안전하게 표시되는 장점 카드", body_copy: "", image_asset_id: null, visual_kind: "html_graphic", sort_order: 0, is_visible: true,
            visual_payload: { layout_variant: "benefit_cards", cards: [{ title: "가볍고 긴 제품 장점 제목도 카드 밖으로 넘치지 않습니다", body: "판매자가 확인한 정보만 사용합니다.", verification_status: "confirmed", source_fact_ids: ["fact-benefit"] }] },
          },
          {
            id: "numeric", section_type: "benefits_summary", title: "핵심 수치", body_copy: "", image_asset_id: null, visual_kind: "html_graphic", sort_order: 1, is_visible: true,
            visual_payload: { layout_variant: "numeric_highlights", highlights: [{ label: "연속 사용 시간", value: "40분", body: "확인된 사용 시간입니다.", verification_status: "confirmed", source_fact_ids: ["fact-time"] }] },
          },
          {
            id: "spec", section_type: "product_info", title: "상품 정보", body_copy: "", image_asset_id: null, visual_kind: "html_graphic", sort_order: 2, is_visible: true,
            visual_payload: { layout_variant: "spec_table", table_rows: [{ label: "긴 스펙 항목 이름", value: "긴 수치와 설명도 모바일에서 가로 스크롤로 읽을 수 있습니다.", verification_status: "confirmed", source_fact_ids: ["fact-spec"] }] },
          },
          {
            id: "seller", section_type: "pre_purchase", title: "판매자 확인 체크리스트", body_copy: "", image_asset_id: null, visual_kind: "html_graphic", sort_order: 3, is_visible: true,
            visual_payload: { layout_variant: "checklist", items: [{ kind: "seller_action", text: "추가 상세 사진을 등록해 주세요.", verification_status: "action_required", source_fact_ids: [] }] },
          },
        ],
      }),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.getByText("40분", { exact: true })).toBeVisible();
  await expect(page.getByText("확인된 상품 정보").first()).toBeVisible();
  await expect(page.getByText("추가 상세 사진을 등록해 주세요.")).toBeVisible();

  const documentBox = await page.locator("[data-detail-page-document='true']").boundingBox();
  expect(documentBox).not.toBeNull();
  for (const visual of await page.locator("[data-section-visual='html_graphic']").all()) {
    const box = await visual.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeLessThanOrEqual(documentBox!.width);
  }
});
