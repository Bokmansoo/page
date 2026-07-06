import { expect, test } from "@playwright/test";

const projectId = "golden-path-project";
const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64"
);

test("golden path: review, apply, verify readiness, and save PNG/JPG", async ({ page }) => {
  let patchPayload: unknown = null;
  const requestedFormats: string[] = [];
  let pageData = {
    id: "page-1",
    project_id: projectId,
    theme_color: "#2FAE73",
    font_family: "sans-serif",
    sections: [
      {
        id: "sec-hero",
        section_type: "hero",
        title: "콘센트 없어도 답답함을 식혀주는 휴대용 무선 냉각선풍기",
        body_copy: "방, 침대 옆, 차량, 야외에서 필요한 순간에 사용하세요.",
        image_asset_id: "hero",
        visual_kind: "image",
        visual_payload: { layout_variant: "hero_overlay", eyebrow: "HERO" },
        sort_order: 0,
        is_visible: true,
        associated_fact_ids: [],
        image_candidates: [],
      },
      {
        id: "sec-comparison",
        section_type: "comparison",
        title: "유선과 무선 사용 방식 비교",
        body_copy: "사용 장소에 맞는 방식을 확인하세요.",
        image_asset_id: null,
        visual_kind: "html_graphic",
        visual_payload: {
          layout_variant: "comparison_cards",
          cards: [
            { title: "유선", body: "전원 위치 확인", tone: "muted" },
            { title: "무선", body: "간편한 이동", tone: "positive" },
          ],
        },
        sort_order: 1,
        is_visible: true,
        associated_fact_ids: [],
        image_candidates: [],
      },
      {
        id: "sec-detail-1",
        section_type: "detail_1",
        title: "필요한 순간 바로 사용",
        body_copy: "충전한 뒤 원하는 장소로 옮겨 사용하세요.",
        image_asset_id: null,
        visual_kind: "html_graphic",
        visual_payload: {
          layout_variant: "benefit_cards",
          cards: [{ title: "간편한 이동", body: "필요한 곳에서 사용", tone: "positive" }],
        },
        sort_order: 2,
        is_visible: true,
        associated_fact_ids: [],
        image_candidates: [],
      },
      {
        id: "sec-detail-2",
        section_type: "detail_2",
        title: "생활 공간과 이동 중에도",
        body_copy: "방과 차량 등 다양한 장소에서 활용하세요.",
        image_asset_id: "lifestyle",
        visual_kind: "image",
        visual_payload: { layout_variant: "image_text", eyebrow: "DETAIL" },
        sort_order: 3,
        is_visible: true,
        associated_fact_ids: [],
        image_candidates: [],
      },
      {
        id: "sec-guarantee",
        section_type: "guarantee",
        title: "구매 전 확인사항",
        body_copy: "충전 방식과 구성품을 확인하세요.",
        image_asset_id: null,
        visual_kind: "html_graphic",
        visual_payload: {
          layout_variant: "spec_table",
          table_rows: [
            { label: "충전 방식", value: "USB-C", verification_status: "confirmed" },
          ],
        },
        sort_order: 4,
        is_visible: true,
        associated_fact_ids: [],
        image_candidates: [],
      },
    ],
  };

  await page.addInitScript(() => {
    const testWindow = window as typeof window & {
      __savedBlobs?: Array<{ type: string; size: number }>;
      showSaveFilePicker?: () => Promise<{
        createWritable: () => Promise<{
          write: (blob: Blob) => Promise<void>;
          close: () => Promise<void>;
        }>;
      }>;
    };
    testWindow.__savedBlobs = [];
    testWindow.showSaveFilePicker = async () => ({
      createWritable: async () => ({
        write: async (blob) => {
          testWindow.__savedBlobs?.push({ type: blob.type, size: blob.size });
        },
        close: async () => undefined,
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
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
          source_type: "real-generated",
        },
      ]),
    });
  });
  await page.route("**/api/v1/files/assets/{hero,lifestyle}", async (route) => {
    await route.fulfill({ contentType: "image/png", body: onePixelPng });
  });
  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    if (route.request().method() === "PATCH") {
      patchPayload = route.request().postDataJSON();
      const patched = patchPayload as {
        theme_color: string;
        font_family: string;
        sections: Array<{
          id: string;
          title: string;
          body_copy: string;
          image_asset_id: string | null;
          sort_order: number;
          is_visible: boolean;
        }>;
      };
      pageData = {
        ...pageData,
        theme_color: patched.theme_color,
        font_family: patched.font_family,
        sections: pageData.sections.map((section) => {
          const nextSection = patched.sections.find((candidate) => candidate.id === section.id);
          return nextSection ? { ...section, ...nextSection } : section;
        }),
      };
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(pageData),
    });
  });
  await page.route(
    `**/api/v1/projects/${projectId}/page/sections/sec-hero/copy-rewrite/preview`,
    async (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        command: "stronger_headline",
        scope: "section",
      });
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          title: "콘센트 없이 시원함을 바로 켜는 휴대용 냉각선풍기",
          body_copy: "방, 침대 옆, 차량, 야외에서 필요한 순간에 사용하세요.",
          change_summary: "제목을 더 구체적으로 강화했습니다.",
          grounding_warnings: [],
        }),
      });
    }
  );
  await page.route(`**/api/v1/projects/${projectId}/page/readiness`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ready: true, blockers: [], warnings: [] }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/page/finalize`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ id: "final-v1", is_final: true }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/page/export`, async (route) => {
    const format = route.request().postDataJSON().output_format as "png" | "jpg";
    requestedFormats.push(format);
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        id: `export-${format}`,
        project_id: projectId,
        preset_name: "smartstore",
        status: "pending",
        error_message: null,
        created_at: "2026-07-06T00:00:00",
        completed_at: null,
      }),
    });
  });
  await page.route(`**/api/v1/projects/${projectId}/page/export/jobs/**`, async (route) => {
    const format = route.request().url().endsWith("jpg") ? "jpg" : "png";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: `export-${format}`,
        project_id: projectId,
        status: "completed",
        error_message: null,
        output_images: [
          `/api/v1/projects/${projectId}/page/export/download/export-image.${format}`,
        ],
        created_at: "2026-07-06T00:00:00",
        completed_at: "2026-07-06T00:00:01",
      }),
    });
  });
  await page.route(
    `**/api/v1/projects/${projectId}/page/export/download/**`,
    async (route) => {
      const format = route.request().url().endsWith(".jpg") ? "jpg" : "png";
      await route.fulfill({
        contentType: format === "jpg" ? "image/jpeg" : "image/png",
        headers: {
          "Content-Disposition": `attachment; filename="sellform.${format}"`,
        },
        body: Buffer.from(`${format}-download`),
      });
    }
  );

  await page.goto(`/workspace/projects/${projectId}/result`);
  await expect(page.locator('[data-detail-page-document="true"]')).toBeVisible();
  await expect(page.locator('[data-section-visual="image"]')).toHaveCount(2);
  await expect(page.locator('[data-section-visual="html_graphic"]')).toHaveCount(3);
  await expect(page.getByText("이미지 확인이 필요합니다")).toHaveCount(0);

  await page.getByRole("button", { name: "검수하며 다듬기" }).first().click();
  await page.getByRole("button", { name: "제목을 더 강하게 바꿔줘" }).click();
  const dialog = page.getByRole("dialog", { name: "AI 수정안 비교" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "이 수정안 적용" }).click();
  await expect(page.getByText("[AI 수정됨]")).toHaveCount(0);
  const patchedSections = (
    patchPayload as {
      sections: Array<{ id: string; title: string; body_copy: string }>;
    }
  ).sections;
  expect(patchedSections.find((section) => section.id === "sec-hero")).toMatchObject({
    id: "sec-hero",
    title: "콘센트 없이 시원함을 바로 켜는 휴대용 냉각선풍기",
  });

  await page.getByRole("button", { name: "결과 화면으로" }).click();
  await expect(page.locator('[data-detail-page-document="true"]')).toBeVisible();

  const readiness = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/projects/${id}/page/readiness`, {
      headers: {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
      },
    });
    return response.json();
  }, projectId);
  expect(readiness).toMatchObject({ ready: true, blockers: [] });

  for (const [index, format] of (["png", "jpg"] as const).entries()) {
    await page.getByLabel("저장 형식").selectOption(format);
    await page.getByRole("button", { name: `${format.toUpperCase()}로 저장하기` }).click();
    await expect
      .poll(() =>
        page.evaluate(() => {
          const testWindow = window as typeof window & {
            __savedBlobs?: Array<{ type: string; size: number }>;
          };
          return testWindow.__savedBlobs?.length ?? 0;
        })
      )
      .toBe(index + 1);
  }

  expect(requestedFormats).toEqual(["png", "jpg"]);
  expect(
    await page.evaluate(() => {
      const testWindow = window as typeof window & {
        __savedBlobs?: Array<{ type: string; size: number }>;
      };
      return testWindow.__savedBlobs;
    })
  ).toEqual([
    { type: "image/png", size: 12 },
    { type: "image/jpeg", size: 12 },
  ]);
});

test("shows blocker message when export readiness fails", async ({ page }) => {
  const projectId = "blocker-test-project";
  let exportRequested = false;

  await page.addInitScript(() => {
    const testWindow = window as typeof window & {
      showSaveFilePicker?: () => Promise<{
        createWritable: () => Promise<{
          write: (blob: Blob) => Promise<void>;
          close: () => Promise<void>;
        }>;
      }>;
    };
    testWindow.showSaveFilePicker = async () => ({
      createWritable: async () => ({
        write: async () => undefined,
        close: async () => undefined,
      }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: projectId, name: "Blocker Test", status: "completed" }),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/assets`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "pending-hero",
          project_id: projectId,
          source_type: "pending-generated",
          storage_path: "pending-hero.png",
          mime_type: "image/png",
        },
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
              title: "Test",
              body_copy: "Test body",
              image_asset_id: "pending-hero",
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

  await page.route(`**/api/v1/projects/${projectId}/page/readiness`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ready: false,
        blockers: [
          { section_id: "sec-hero", code: "asset_not_eligible", message: "Test blocker" },
        ],
        warnings: [],
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

  await page.route(`**/api/v1/projects/${projectId}/page/export`, async (route) => {
    exportRequested = true;
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          message: "Page is not ready for export",
          blockers: [
            { section_id: "sec-hero", code: "asset_not_eligible", message: "일부 이미지가 내보내기 조건을 충족하지 않습니다" },
          ],
        },
      }),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/result`);
  await page.waitForSelector('[data-detail-page-document="true"]', { timeout: 10000 });

  // Try to export - should show blocker message
  await page.getByRole("button", { name: /PNG/i }).click();
  await expect.poll(() => exportRequested).toBe(true);
  await expect(page.getByText("다운로드 전 확인이 필요합니다")).toBeVisible();
  await expect(page.getByText("일부 이미지가 내보내기 조건을 충족하지 않습니다")).toBeVisible();
  await expect(page.getByText("검수하며 다듬기에서 해결하기")).toBeVisible();
});
