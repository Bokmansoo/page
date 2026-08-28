import { expect, test } from "@playwright/test";

const projectId = "lg11-canvas-project";
const runId = "lg11-canvas-run";

test("LG-11 Canvas sends visibility and height draft commands through the production resume API", async ({ page }) => {
  const resumePayloads: Array<Record<string, unknown>> = [];
  const canvasView = {
    run_id: runId,
    thread_id: runId,
    status: "awaiting_review",
    current_stage: "canvas_edit",
    values: {
      review: {
        pending: {
          schema_version: "lg11-review-response-v1",
          review_stage: "canvas_edit",
          title: "Canvas section draft",
          description: "Draft only",
        },
      },
      canvas: {
        revision: 1,
        canonical_page_assembly_input: {
          sections: [
            { section_id: "hero", canvas: { is_visible: true, height_px: 240 } },
            { section_id: "specs", canvas: { is_visible: true, height_px: null } },
          ],
        },
      },
      generation: { jobs: [] },
      execution: { recoverable: false, errors: [] },
    },
    next_nodes: [],
  };

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}/resume`, async (route) => {
    resumePayloads.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(canvasView) });
  });
  await page.route(`**/api/v1/graph-runs/${runId}`, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(canvasView),
  }));

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByTestId("lg11-canvas-draft")).toBeVisible();

  await page.getByRole("button", { name: "숨김" }).first().click();
  await expect.poll(() => resumePayloads.length).toBe(1);
  expect(resumePayloads[0]).toMatchObject({
    response: {
      decision: "apply",
      canvas_operation: { kind: "set_visibility", section_id: "hero", is_visible: false },
    },
  });

  await page.getByLabel("hero 높이").fill("480");
  await page.getByRole("button", { name: "높이 적용" }).first().click();
  await expect.poll(() => resumePayloads.length).toBe(2);
  expect(resumePayloads[1]).toMatchObject({
    response: {
      decision: "apply",
      canvas_operation: { kind: "set_height", section_id: "hero", height_px: 480 },
    },
  });
});

test("LG-11 frozen Canvas preview omits hidden sections and preserves frozen height for export rendering", async ({ page }) => {
  const versionId = "lg11-canvas-child-version";
  await page.route(`**/api/v1/projects/${projectId}/page/final?version_id=${versionId}`, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      id: versionId,
      sections_json: {
        schema_version: "lg10-detail-page-version-v1",
        commerce_renderer: {
          theme_color: "#ffffff",
          font_family: "system-ui, sans-serif",
          sections: [
            {
              id: "hero", section_type: "hero", title: "Frozen Canvas", body_copy: "PNG and JPG read this frozen state.",
              sort_order: 0, is_visible: true, height_px: 480, visual_payload: { canvas_height_px: 480, canvas_is_visible: true },
            },
            {
              id: "hidden-copy", section_type: "product_information", title: "Hidden Canvas Section", body_copy: "Must not render.",
              sort_order: 1, is_visible: false, height_px: 360, visual_payload: { canvas_height_px: 360, canvas_is_visible: false },
            },
          ],
        },
      },
    }),
  }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));

  await page.goto(`/export-render/projects/${projectId}?version_id=${versionId}`);
  const sections = page.locator("[data-detail-page-section='true']");
  await expect(sections).toHaveCount(1);
  await expect(page.locator("#section-hero")).toHaveCSS("min-height", "480px");
  await expect(page.getByText("Hidden Canvas Section")).toHaveCount(0);
  await expect(page.locator("html")).toHaveAttribute("data-export-ready", "true");
});

test("LG-11 channel preview exposes frozen unsafe Canvas element identity", async ({ page }) => {
  const versionId = "lg11-unsafe-version";
  await page.route(`**/api/v1/projects/${projectId}/page/final?version_id=${versionId}&channel=coupang`, (route) => route.fulfill({
    status: 409,
    contentType: "application/json",
    body: JSON.stringify({ detail: { canvas_safety: { issues: [{ section_id: "hero", element_id: "hero:asset", reason: "Element exceeds the channel safe area." }] } } }),
  }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto(`/export-render/projects/${projectId}?version_id=${versionId}&channel=coupang`);
  await expect(page.getByText("hero · hero:asset · Element exceeds the channel safe area.")).toBeVisible();
});

test("LG-11 Canvas sends production element, layer, lock, group, and asset replacement commands", async ({ page }) => {
  const resumePayloads: Array<Record<string, unknown>> = [];
  const canvasView = {
    run_id: runId, thread_id: runId, status: "awaiting_review", current_stage: "canvas_edit",
    values: {
      review: { pending: { schema_version: "lg11-v1", review_stage: "canvas_edit", title: "Canvas", description: "Draft" } },
      canvas: { revision: 1, element_groups: [], canonical_page_assembly_input: { sections: [{ section_id: "hero", canvas: { is_visible: true, height_px: null }, canvas_elements: [
        { element_id: "hero:background", kind: "background", x: 0, y: 0, width: 760, height: 160, z_index: 0, locked: false },
        { element_id: "hero:text", kind: "text", x: 0, y: 0, width: 712, height: 120, z_index: 2, locked: false },
        { element_id: "hero:asset", kind: "asset", x: 0, y: 0, width: 712, height: 320, z_index: 1, locked: false },
      ] }, { section_id: "specs", canvas: { is_visible: true, height_px: null }, canvas_elements: [{ element_id: "specs:text", kind: "text", x: 0, y: 0, width: 712, height: 120, z_index: 1, locked: false }] }] } },
      generation: { jobs: [] }, execution: { recoverable: false, errors: [] },
    }, next_nodes: [],
  };
  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: "seller-asset", filename: "seller.png", source_type: "uploaded", usage_status: "seller_owned", mime_type: "image/png", content_hash: "a".repeat(64) },
    { id: "confirmed-asset", filename: "confirmed.png", source_type: "self_shot", usage_status: "rights_confirmed", mime_type: "image/png", content_hash: "b".repeat(64) },
    { id: "reference-asset", filename: "reference.png", source_type: "uploaded", usage_status: "reference_only", mime_type: "image/png", content_hash: "c".repeat(64) },
    { id: "supplier-asset", filename: "supplier.png", source_type: "supplier", usage_status: "seller_owned", mime_type: "image/png", content_hash: "d".repeat(64) },
    { id: "blocked-asset", filename: "blocked.png", source_type: "uploaded", usage_status: "blocked", mime_type: "image/png", content_hash: "e".repeat(64) },
  ]) }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}/resume`, async (route) => { resumePayloads.push(route.request().postDataJSON() as Record<string, unknown>); await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(canvasView) }); });
  await page.route(`**/api/v1/graph-runs/${runId}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(canvasView) }));
  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByTestId("lg11-canvas-elements")).toBeVisible();
  const replacementAssetValues = await page.getByLabel("hero:asset 교체 자산").locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value));
  expect(replacementAssetValues).toEqual(["", "seller-asset", "confirmed-asset"]);
  await page.getByTestId("lg11-canvas-move-hero:asset").click();
  await expect.poll(() => resumePayloads.length).toBe(1);
  expect(resumePayloads[0]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "move_element", section_id: "hero", element_id: "hero:asset", dx: 10, dy: 0 } } });
  await page.getByTestId("lg11-canvas-z-hero:asset").click();
  await expect.poll(() => resumePayloads.length).toBe(2);
  expect(resumePayloads[1]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "set_z_order", element_id: "hero:asset", z_index: 2 } } });
  await page.getByTestId("lg11-canvas-lock-hero:asset").click();
  await expect.poll(() => resumePayloads.length).toBe(3);
  expect(resumePayloads[2]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "set_lock", element_id: "hero:asset", locked: true } } });
  await page.getByLabel("hero:asset 선택").check();
  await page.getByLabel("hero:text 선택").check();
  await page.getByTestId("lg11-canvas-group-selected").click();
  await expect.poll(() => resumePayloads.length).toBe(4);
  expect(resumePayloads[3]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "group", element_ids: ["hero:asset", "hero:text"] } } });
  await page.getByTestId("lg11-canvas-add-mask-hero").click();
  await expect.poll(() => resumePayloads.length).toBe(5);
  expect(resumePayloads[4]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "create_element", section_id: "hero", element_kind: "mask", token: "rounded" } } });
  await page.getByTestId("lg11-canvas-duplicate-hero:asset").click();
  await expect.poll(() => resumePayloads.length).toBe(6);
  expect(resumePayloads[5]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "duplicate_element", element_id: "hero:asset" } } });
  await page.getByLabel("hero:asset 교체 자산").selectOption("confirmed-asset");
  await page.getByTestId("lg11-canvas-replace-hero:asset").click();
  await expect.poll(() => resumePayloads.length).toBe(7);
  expect(resumePayloads[6]).toMatchObject({ response: { decision: "apply", canvas_operation: { kind: "replace_element", element_id: "hero:asset", asset_id: "confirmed-asset", asset_content_hash: "b".repeat(64) } } });
});

test("LG-11 selected conversational Canvas edit pins the frozen section and element context", async ({ page }) => {
  const versionId = "lg11-frozen-version";
  const editRunId = "lg11-selected-edit-run";
  const startPayloads: Array<Record<string, unknown>> = [];
  const previewPayloads: Array<Record<string, unknown>> = [];
  const completedView = {
    run_id: runId, thread_id: runId, status: "completed", current_stage: "completed",
    values: { generation: { jobs: [] }, rendering: { detail_page_version: { id: versionId } }, execution: { recoverable: false, errors: [] } }, next_nodes: [],
  };
  const editView = {
    run_id: editRunId, thread_id: editRunId, status: "awaiting_review", current_stage: "edit_confirmation",
    values: { review: { pending: { schema_version: "lg11-v1", review_stage: "edit_confirmation", title: "Confirm", description: "Frozen target" } }, generation: { jobs: [] }, execution: { recoverable: false, errors: [] } }, next_nodes: [],
  };
  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/page/versions/${versionId}`, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({
      id: versionId,
      sections_json: { lg10: { canonical_page_assembly_input: { sections: [{ section_id: "hero", canvas_elements: [{ element_id: "hero:asset", kind: "asset" }, { element_id: "hero:text", kind: "text" }] }] } } },
    }),
  }));
  await page.route(`**/api/v1/projects/${projectId}/page/versions/${versionId}/edit-runs`, async (route) => {
    startPayloads.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ run_id: editRunId }) });
  });
  await page.route(`**/api/v1/projects/${projectId}/page/versions/${versionId}/edit-intents/preview`, async (route) => {
    previewPayloads.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      edit_intent: { intent_hash: "a".repeat(64) },
      impact_preview: { affected_artifacts: { section_ids: ["hero"], scene_ids: [], assets: [], copy_artifacts: [], facts: [], style_layout_tokens: [], brand_kit: {} }, expected_provider_cost: { status: "not_required" } },
    }) });
  });
  await page.route(`**/api/v1/graph-runs/${editRunId}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(editView) }));
  await page.route(`**/api/v1/graph-runs/${runId}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(completedView) }));

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByTestId("lg11-selected-conversation-editor")).toBeVisible();
  await page.getByTestId("lg11-edit-section").selectOption("hero");
  await page.getByTestId("lg11-edit-element").selectOption("hero:asset");
  await page.getByTestId("lg11-edit-instruction").fill("선택한 이미지를 오른쪽으로 옮겨 주세요");
  await page.getByTestId("lg11-edit-start").click();
  await expect.poll(() => previewPayloads.length).toBe(1);
  expect(startPayloads).toHaveLength(0);
  await expect(page.getByTestId("lg11-edit-impact-preview")).toBeVisible();
  await page.getByTestId("lg11-edit-confirm").click();
  await expect.poll(() => startPayloads.length).toBe(1);
  expect(startPayloads[0]).toMatchObject({
    scope: "page",
    operation: "canvas_draft",
    target_ids: [versionId],
    selected_section_id: "hero",
    selected_element_id: "hero:asset",
  });
});

test("LG-11 conversational routes preview before confirmation and keep frozen targets", async ({ page }) => {
  const versionId = "lg11-current-version";
  const historicalVersionId = "lg11-historical-version";
  const previewPayloads: Array<Record<string, unknown>> = [];
  const startPayloads: Array<{ url: string; payload: Record<string, unknown> }> = [];
  const completedView = {
    run_id: runId, thread_id: runId, status: "completed", current_stage: "completed",
    values: { generation: { jobs: [] }, rendering: { detail_page_version: { id: versionId } }, execution: { recoverable: false, errors: [] } }, next_nodes: [],
  };
  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, (route) => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: "replacement", filename: "owned.png", source_type: "uploaded", usage_status: "rights_confirmed", mime_type: "image/png", content_hash: "b".repeat(64) },
  ]) }));
  await page.route(`**/api/v1/projects/${projectId}/page/versions`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: versionId, name: "current", is_final: true, lg11_frozen: true },
    { id: historicalVersionId, name: "historical", is_final: false, lg11_frozen: true },
  ]) }));
  await page.route(`**/api/v1/brand-kits`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ versions: [{ id: "brand-v2", version: 2 }] }) }));
  await page.route(`**/api/v1/projects/${projectId}/page/versions/**`, async (route) => {
    const url = route.request().url();
    if (url.endsWith("/edit-intents/preview")) {
      previewPayloads.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        edit_intent: { intent_hash: "a".repeat(64) },
        impact_preview: { affected_artifacts: { section_ids: ["hero"], scene_ids: ["hero-scene"], assets: [{ asset_id: "product", asset_content_hash: "c".repeat(64) }], copy_artifacts: [{ artifact_key: "copy", artifact_hash: "d".repeat(64) }], facts: [{ fact_id: "fact-1", evidence_ids: ["evidence-1"] }], style_layout_tokens: [{ section_id: "hero", layout_token: "image_text" }], brand_kit: { id: "brand-v2" } }, expected_provider_cost: { status: "not_required" } },
      }) });
      return;
    }
    if (url.endsWith("/edit-runs")) {
      startPayloads.push({ url, payload: route.request().postDataJSON() as Record<string, unknown> });
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ run_id: `edit-${startPayloads.length}` }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      id: versionId,
      sections_json: { lg10: { canonical_page_assembly_input: { sections: [{ section_id: "hero", copy_ref: { fields: ["hero_title"], fact_ids: ["fact-1"] }, approved_assets: [{ scene_id: "hero-scene", asset_id: "product", asset_content_hash: "c".repeat(64) }], canvas_elements: [{ element_id: "hero:asset", kind: "asset" }] }] } } },
    }) });
  });
  await page.route(`**/api/v1/graph-runs/${runId}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(completedView) }));

  const exercise = async (mode: string, expected: Record<string, unknown>, setup?: () => Promise<void>) => {
    await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
    await expect(page.getByTestId("lg11-selected-conversation-editor")).toBeVisible();
    await page.getByTestId("lg11-edit-mode").selectOption(mode);
    await page.getByTestId("lg11-edit-section").selectOption("hero");
    if (setup) await setup();
    await page.getByTestId("lg11-edit-instruction").fill(`apply ${mode}`);
    if (mode === "copy") await page.getByTestId("lg11-edit-copy").fill("Updated frozen copy");
    const previewsBefore = previewPayloads.length;
    const startsBefore = startPayloads.length;
    await page.getByTestId("lg11-edit-start").click();
    await expect.poll(() => previewPayloads.length).toBe(previewsBefore + 1);
    expect(startPayloads).toHaveLength(startsBefore);
    await page.getByTestId("lg11-edit-confirm").click();
    await expect.poll(() => startPayloads.length).toBe(startsBefore + 1);
    expect(startPayloads.at(-1)?.payload).toMatchObject(expected);
  };

  await exercise("copy", { scope: "copy", target_ids: ["hero"], selected_section_id: "hero" });
  await exercise("fact", { scope: "fact", target_ids: ["fact-1"], selected_section_id: "hero" });
  await exercise("style", { scope: "style", operation: "restyle" });
  await exercise("scene_regenerate", { scope: "scene", target_ids: ["hero-scene"], operation: "regenerate" }, async () => {
    await page.getByTestId("lg11-edit-scene").selectOption("hero-scene");
  });
  await exercise("asset_replace", { scope: "scene", target_ids: ["hero-scene"], operation: "replace", replacement_asset_id: "replacement" }, async () => {
    await page.getByTestId("lg11-edit-scene").selectOption("hero-scene");
    await page.getByTestId("lg11-edit-replacement-asset").selectOption("replacement");
  });
  await exercise("restore", { scope: "page", target_ids: [historicalVersionId], operation: "restore" }, async () => {
    await page.getByTestId("lg11-restore-version").selectOption(historicalVersionId);
  });
  expect(startPayloads.at(-1)?.url).toContain(`/page/versions/${historicalVersionId}/edit-runs`);
  expect(startPayloads.every((entry) => !entry.url.endsWith("/restore"))).toBeTruthy();
});
