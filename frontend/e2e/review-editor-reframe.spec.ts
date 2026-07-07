import { expect, test } from "@playwright/test";

const projectId = "copy-rewrite-project";

test("previews, retries, and applies copy rewrite presets with manual edit support", async ({ page }) => {
  let patchPayload: unknown = null;
  let previewCallCount = 0;
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
      previewCallCount++;
      const requestData = route.request().postDataJSON();
      
      // Verify manual edits (or current input fields) are sent as preview source
      expect(requestData).toMatchObject({
        command: "stronger_persuasion",
        title: "사용자 수동 변경 제목",
        body_copy: "사용자 수동 변경 본문 내용",
        scope: "section",
      });

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "책상·차량·야외까지, 더운 순간 바로 꺼내 쓰는 무선 냉각 선풍기",
          body_copy: "무더운 여름철 야외 활동이나 사무실 책상에서도 콘센트 없이 시원한 바람을 제공합니다.",
          change_summary: "문제와 해결을 더 선명하게 연결하여 구매 설득력을 높였습니다.",
          grounding_warnings: [],
          before: {
            title: "사용자 수동 변경 제목",
            body_copy: "사용자 수동 변경 본문 내용"
          },
          after: {
            title: "책상·차량·야외까지, 더운 순간 바로 꺼내 쓰는 무선 냉각 선풍기",
            body_copy: "무더운 여름철 야외 활동이나 사무실 책상에서도 콘센트 없이 시원한 바람을 제공합니다."
          },
          rationale: "문제와 해결을 더 선명하게 연결하여 구매 설득력을 높였습니다.",
          safety_notes: []
        }),
      });
    }
  );

  await page.goto(`/workspace/projects/${projectId}/page-editor?mode=review`);

  // 1. Fill manual edits and wait for PATCH response to resolve race condition
  const titleInput = page.locator("#section-title-edit");
  await titleInput.fill("사용자 수동 변경 제목");
  await titleInput.blur();
  await page.waitForResponse(res => res.url().includes("/page") && res.request().method() === "PATCH");

  const bodyInput = page.locator("#section-body-edit");
  await bodyInput.fill("사용자 수동 변경 본문 내용");
  await bodyInput.blur();
  await page.waitForResponse(res => res.url().includes("/page") && res.request().method() === "PATCH");

  // 2. Click preset button to preview
  await page.getByRole("button", { name: "강한 구매 설득 버전" }).click();

  // 3. Verify modal elements
  const dialog = page.getByRole("dialog", { name: "AI 수정안 비교" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("수정 전")).toBeVisible();
  await expect(dialog.getByText("수정 후")).toBeVisible();
  await expect(dialog.getByText("사용자 수동 변경 제목")).toBeVisible();
  await expect(dialog.getByText("책상·차량·야외까지, 더운 순간 바로 꺼내 쓰는 무선 냉각 선풍기")).toBeVisible();

  // 4. Test "다시 생성" (Retry) button
  await dialog.getByRole("button", { name: "다시 생성" }).click();
  expect(previewCallCount).toBe(2);

  // 5. Test "이 수정안 적용" (Apply)
  await dialog.getByRole("button", { name: "이 수정안 적용" }).click();

  // 6. Assert changes applied and PATCH triggered
  await expect(page.getByText("[AI 수정됨]")).toHaveCount(0);
  await expect(titleInput).toHaveValue("책상·차량·야외까지, 더운 순간 바로 꺼내 쓰는 무선 냉각 선풍기");
  
  expect(patchPayload).toMatchObject({
    sections: [
      expect.objectContaining({
        id: "hero-section",
        title: "책상·차량·야외까지, 더운 순간 바로 꺼내 쓰는 무선 냉각 선풍기",
        body_copy: "무더운 여름철 야외 활동이나 사무실 책상에서도 콘센트 없이 시원한 바람을 제공합니다.",
      }),
    ],
  });
});
