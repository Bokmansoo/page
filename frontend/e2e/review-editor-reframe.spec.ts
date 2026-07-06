import { expect, test } from "@playwright/test";

const projectId = "copy-rewrite-project";

test("previews and applies stronger headline without edit markers", async ({ page }) => {
  let patchPayload: unknown = null;
  let pageData = {
    id: "page-1",
    project_id: projectId,
    theme_color: "#2FAE73",
    font_family: "sans-serif",
    sections: [
      {
        id: "hero-section",
        section_type: "hero",
        title: "콘센트 없어도 답답함을 식혀주는 휴대용 무선 냉각선풍기",
        body_copy: "방/침대 옆/차량/야외까지, 더운 순간에 바로 켜서 시원한 바람을 이어보세요.",
        associated_fact_ids: [],
        image_asset_id: "hero-asset",
        sort_order: 0,
        is_visible: true,
        visual_kind: "image",
        visual_payload: {
          layout_variant: "hero_overlay",
          eyebrow: "HERO",
          badges: ["무선", "냉풍 컨셉"],
        },
      },
    ],
  };

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
          id: "hero-asset",
          filename: "hero.png",
          file_path: "",
          mime_type: "image/png",
          source_type: "real-generated",
        },
      ]),
    });
  });

  await page.route(`**/api/v1/files/assets/hero-asset`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lJ1mVwAAAABJRU5ErkJggg==",
        "base64"
      ),
    });
  });

  await page.route(`**/api/v1/projects/${projectId}/page`, async (route) => {
    if (route.request().method() === "PATCH") {
      patchPayload = route.request().postDataJSON();
      const patched = patchPayload as {
        sections: Array<{ id: string; title: string; body_copy: string }>;
      };
      pageData = {
        ...pageData,
        sections: pageData.sections.map((section) => {
          const nextSection = patched.sections.find((candidate) => candidate.id === section.id);
          return nextSection
            ? { ...section, title: nextSection.title, body_copy: nextSection.body_copy }
            : section;
        }),
      };
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(pageData),
    });
  });

  await page.route(
    `**/api/v1/projects/${projectId}/page/sections/hero-section/copy-rewrite/preview`,
    async (route) => {
      expect(route.request().postDataJSON()).toMatchObject({
        command: "stronger_headline",
        instruction: "",
        scope: "section",
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "콘센트 없이도 시원함을 바로 켜는 휴대용 냉각선풍기",
          body_copy: "방, 침대 옆, 차량, 야외에서 더운 순간에 바로 켜서 시원한 바람을 이어보세요.",
          change_summary: "제목을 더 구체적이고 강하게 다듬었습니다.",
          grounding_warnings: [],
        }),
      });
    }
  );

  await page.goto(`/workspace/projects/${projectId}/page-editor?mode=review`);

  await expect(page.locator("#section-title-edit")).toHaveValue(
    "콘센트 없어도 답답함을 식혀주는 휴대용 무선 냉각선풍기"
  );
  await page.getByRole("button", { name: "제목을 더 강하게 바꿔줘" }).click();

  const dialog = page.getByRole("dialog", { name: "AI 수정안 비교" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("수정 전")).toBeVisible();
  await expect(dialog.getByText("수정 후")).toBeVisible();
  await expect(dialog.getByText("콘센트 없이도 시원함을 바로 켜는 휴대용 냉각선풍기")).toBeVisible();

  await dialog.getByRole("button", { name: "이 수정안 적용" }).click();

  await expect(page.getByText("[AI 수정됨]")).toHaveCount(0);
  await expect(page.locator("#section-title-edit")).toHaveValue(
    "콘센트 없이도 시원함을 바로 켜는 휴대용 냉각선풍기"
  );
  expect(patchPayload).toMatchObject({
    sections: [
      expect.objectContaining({
        id: "hero-section",
        title: "콘센트 없이도 시원함을 바로 켜는 휴대용 냉각선풍기",
        body_copy: "방, 침대 옆, 차량, 야외에서 더운 순간에 바로 켜서 시원한 바람을 이어보세요.",
      }),
    ],
  });
});
