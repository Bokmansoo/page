import { expect, test } from "@playwright/test";

const projectId = "result-editor-entrypoints-project";
const invalidProjectId = "result-editor-invalid-visual-project";

function pagePayload(id: string, missingImage = false) {
  return {
    id: `${id}-page`,
    project_id: id,
    theme_color: "#2F6B4F",
    font_family: "sans-serif",
    sections: [
      {
        id: "hero-section",
        section_type: "hero",
        title: "콘센트 없이 시원하게, 휴대용 무선 냉각선풍기",
        body_copy: "캠핑·차량·실내 어디서든 바로 사용할 수 있습니다.",
        image_asset_id: missingImage ? null : "hero-asset",
        visual_kind: "image",
        visual_payload: null,
        sort_order: 0,
        is_visible: true,
        image_candidates: [],
      },
      {
        id: "detail-section",
        section_type: "detail_1",
        title: "무선이라 더 편한 사용",
        body_copy: "책상, 차량, 야외에서도 전원 걱정을 줄입니다.",
        image_asset_id: "detail-asset",
        visual_kind: "image",
        visual_payload: null,
        sort_order: 1,
        is_visible: true,
        image_candidates: [],
      },
    ],
  };
}

async function mockProjectApis(page: import("@playwright/test").Page, id: string, missingImage = false) {
  await page.route(`**/api/v1/projects/${id}`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id, name: "루메나 휴대용 무선 냉각선풍기", status: "completed" }),
    });
  });
  await page.route(`**/api/v1/projects/${id}/page`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(pagePayload(id, missingImage)),
    });
  });
  await page.route(`**/api/v1/projects/${id}/assets`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        { id: "hero-asset", filename: "hero.png", file_path: "", mime_type: "image/png", source_type: "real-generated" },
        { id: "detail-asset", filename: "detail.png", file_path: "", mime_type: "image/png", source_type: "real-generated" },
      ]),
    });
  });
  await page.route("**/api/v1/files/assets/**", async (route) => {
    await route.fulfill({ contentType: "image/png", body: Buffer.from("image") });
  });
  await page.route(`**/api/v1/projects/${id}/page/compliance`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ can_export: true, issues: [] }),
    });
  });
}

test("result page shows distinct review, advanced, worklist and export history actions", async ({ page }) => {
  await mockProjectApis(page, projectId);

  await page.goto(`/workspace/projects/${projectId}/result`);

  await expect(page.getByRole("link", { name: "검수하며 다듬기" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "고급 편집기로 열기" }).first()).toBeVisible();
  await expect(page.getByText("문구와 이미지를 빠르게 확인하고 누락·오류를 줄입니다.")).toBeVisible();
  await expect(page.getByText("레이아웃과 섹션을 더 세밀하게 수정합니다.")).toBeVisible();
  const nextActions = page.getByLabel("다음 작업");
  await expect(nextActions.getByRole("link", { name: "작업 목록" })).toBeVisible();
  await expect(nextActions.getByRole("link", { name: "출력 이력" })).toBeVisible();
});

test("page editor separates review and advanced mode headers", async ({ page }) => {
  await mockProjectApis(page, projectId);

  await page.goto(`/workspace/projects/${projectId}/page-editor?mode=review`);
  await expect(page.getByRole("heading", { name: "검수하며 다듬기" })).toBeVisible();
  await expect(page.getByText("문구와 이미지 후보를 빠르게 확인하고 업로드 전 오류를 줄입니다.")).toBeVisible();

  await page.goto(`/workspace/projects/${projectId}/page-editor?mode=advanced`);
  await expect(page.getByRole("heading", { name: "고급 편집기" })).toBeVisible();
  await expect(page.getByText("섹션 순서와 레이아웃을 더 세밀하게 조정합니다.")).toBeVisible();
});

test("download blocker explains image remediation action", async ({ page }) => {
  await mockProjectApis(page, invalidProjectId, true);

  await page.goto(`/workspace/projects/${invalidProjectId}/result`);

  await expect(page.getByText("시각 요소 1개 확인 필요")).toBeVisible();
  await page.getByRole("button", { name: "PNG로 다운로드" }).click();
  const alert = page.getByRole("alert");
  await expect(alert.getByText("다운로드 전에 이미지 후보를 확인해 주세요.")).toBeVisible();
  await expect(alert.getByRole("button", { name: "검수하며 이미지 보완" })).toBeVisible();
});
