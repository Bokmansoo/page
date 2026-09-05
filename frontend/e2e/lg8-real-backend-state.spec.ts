import { expect, test, type APIRequestContext, type APIResponse } from "@playwright/test";

const appBase = process.env.SELLFORM_E2E_REAL_APP_URL ?? "http://localhost:3000";
const apiBase = process.env.SELLFORM_E2E_REAL_API_URL ?? "http://localhost:8001";

type GraphState = {
  run_id: string;
  thread_id: string;
  current_stage: string;
  values: {
    review?: {
      pending?: {
        schema_version: string;
        review_stage: string;
        context?: Record<string, unknown>;
      };
    };
  };
};

async function responseJson<T>(response: APIResponse): Promise<T> {
  if (!response.ok()) {
    throw new Error(`HTTP ${response.status()}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

async function approvePending(request: APIRequestContext, state: GraphState, extra: Record<string, unknown> = {}) {
  const pending = state.values.review?.pending;
  expect(pending, `missing pending review at ${state.current_stage}`).toBeTruthy();
  const response = await request.post(`${apiBase}/api/v1/graph-runs/${state.run_id}/resume`, {
    data: {
      thread_id: state.thread_id,
      response: {
        schema_version: pending!.schema_version,
        review_stage: pending!.review_stage,
        decision: "approve",
        ...extra,
      },
    },
  });
  return responseJson<GraphState>(response);
}

test.describe("LG-8 real backend visual prompt compiler", () => {
  test.skip(process.env.SELLFORM_E2E_REAL_BACKEND !== "1", "Runs only against the real local API and DB.");

  test("persists prompt evidence, replaces only one scene, and resumes the real graph", async ({ page }) => {
    test.setTimeout(180_000);

    const login = await page.request.post(`${apiBase}/api/v1/auth/development-login`);
    expect(login.ok(), await login.text()).toBeTruthy();
    const created = await responseJson<{ id: string; project_id: string }>(
      await page.request.post(`${apiBase}/api/agent-runs`, {
        data: {
          product_name: `LG-8 visual compiler ${Date.now()}`,
          category: "전자제품",
          description: "USB 충전 휴대용 선풍기. 판매자가 확인한 정격 입력 DC 5V 2A.",
          ux_auto_generate: false,
        },
      }),
    );

    await page.setContent(`
      <main style="display:flex;gap:40px;background:#f8fafc;padding:80px">
        <div id="whole" style="width:640px;height:640px;display:grid;place-items:center;background:white">
          <div style="width:260px;height:440px;border-radius:130px;background:#2563eb;position:relative">
            <div style="position:absolute;width:190px;height:190px;left:35px;top:30px;border:24px solid #dbeafe;border-radius:50%"></div>
          </div>
        </div>
        <div id="detail" style="width:640px;height:640px;display:grid;place-items:center;background:#eff6ff">
          <div style="width:230px;height:460px;border-radius:115px;background:#2563eb;position:relative">
            <div style="position:absolute;width:42px;height:42px;left:94px;top:310px;border-radius:50%;background:white"></div>
          </div>
        </div>
      </main>
    `);
    const wholePng = await page.locator("#whole").screenshot();
    const detailPng = await page.locator("#detail").screenshot();

    const upload = async (name: string, buffer: Buffer) => responseJson<{ id: string }>(
      await page.request.post(`${apiBase}/api/v1/files/upload`, {
        multipart: {
          project_id: created.project_id,
          source_type: "uploaded",
          file: { name, mimeType: "image/png", buffer },
        },
      }),
    );
    const whole = await upload("lg8-whole-product.png", wholePng);
    const detail = await upload("lg8-control-detail.png", detailPng);

    await responseJson(await page.request.patch(
      `${apiBase}/api/v1/projects/${created.project_id}/assets/${whole.id}/classification`,
      { data: { asset_role: "product_main", is_representative: true } },
    ));
    await responseJson(await page.request.patch(
      `${apiBase}/api/v1/projects/${created.project_id}/assets/${detail.id}/classification`,
      { data: { asset_role: "product_detail", is_representative: false } },
    ));
    await responseJson(await page.request.patch(`${apiBase}/api/agent-runs/${created.id}/input-assets`, {
      data: { asset_ids: [whole.id, detail.id] },
    }));

    let state = await responseJson<GraphState>(
      await page.request.post(`${apiBase}/api/v1/graph-runs/${created.id}/start`),
    );
    expect(state.current_stage).toBe("input_review");
    state = await approvePending(page.request, state);
    expect(state.current_stage).toBe("evidence_review");
    state = await approvePending(page.request, state);
    expect(state.current_stage).toBe("planning_review");
    state = await approvePending(page.request, state);
    expect(state.current_stage).toBe("generation_pending");

    const initialPrompts = await responseJson<{ items: Array<{ id: string; scene_id: string; version: number; status: string; prompt_hash: string }> }>(
      await page.request.get(`${apiBase}/api/v1/projects/${created.project_id}/scene-prompts`),
    );
    expect(initialPrompts.items.length).toBeGreaterThan(0);

    const target = initialPrompts.items[0];

    await page.goto(`${appBase}/workspace/projects/${created.project_id}/planning?runId=${created.id}`);
    const promptEvidence = page.getByTestId(`scene-prompt-${target.scene_id}`);
    await expect(promptEvidence).toBeVisible({ timeout: 20_000 });
    await promptEvidence.locator("summary").click();
    await expect(promptEvidence).toContainText("Prompt hash");
    await expect(promptEvidence).toContainText("Reference hash");
    await expect(promptEvidence).toContainText("텍스트·로고");

    const adjustment = "Soft daylight studio background, product centered, no raster text.";
    await page.getByTestId(`scene-adjustment-${target.scene_id}`).fill(adjustment);
    await page.getByTestId(`scene-adjustment-save-${target.scene_id}`).click();
    await expect.poll(async () => {
      const response = await page.request.get(
        `${apiBase}/api/v1/projects/${created.project_id}/scene-prompts?include_stale=true`,
      );
      const body = await response.json() as { items: Array<{ scene_id: string; version: number; status: string; seller_adjustment?: string }> };
      return body.items.filter((item) => item.scene_id === target.scene_id);
    }).toEqual(expect.arrayContaining([
      expect.objectContaining({ version: 1, status: "stale" }),
      expect.objectContaining({ version: 2, status: "active", seller_adjustment: adjustment }),
    ]));

    const afterEdit = await responseJson<{ items: Array<{ scene_id: string; version: number; status: string }> }>(
      await page.request.get(`${apiBase}/api/v1/projects/${created.project_id}/scene-prompts?include_stale=true`),
    );
    for (const initial of initialPrompts.items.filter((item) => item.scene_id !== target.scene_id)) {
      expect(afterEdit.items).toContainEqual(expect.objectContaining({
        scene_id: initial.scene_id,
        version: initial.version,
        status: "active",
      }));
    }

    await page.reload();
    const restoredEvidence = page.getByTestId(`scene-prompt-${target.scene_id}`);
    await expect(restoredEvidence).toBeVisible({ timeout: 20_000 });
    await restoredEvidence.locator("summary").click();
    await expect(restoredEvidence).toContainText("v2");
    await expect(restoredEvidence).toContainText(adjustment);

    const refreshedState = await responseJson<GraphState>(
      await page.request.get(`${apiBase}/api/v1/graph-runs/${created.id}`),
    );
    const generation = refreshedState.values.review?.pending?.context?.generation as
      | { cost_plan?: { cost_plan_hash?: string } }
      | undefined;
    const costPlanHash = generation?.cost_plan?.cost_plan_hash;
    expect(costPlanHash).toBeTruthy();
    state = await approvePending(page.request, refreshedState, { cost_plan_hash: costPlanHash });
    expect(state.thread_id).toBe(created.id);
    expect(["provider_wait", "image_review"]).toContain(state.current_stage);

    // The durable worker may finish between the resume response and the UI
    // reload. Wait on the authoritative graph checkpoint, then prove that a
    // fresh browser load restores that exact review stage from the backend.
    await expect.poll(async () => {
      const current = await responseJson<GraphState>(
        await page.request.get(`${apiBase}/api/v1/graph-runs/${created.id}`),
      );
      return current.current_stage;
    }, { timeout: 30_000 }).toBe("image_review");
    await page.reload();
    await expect(page.getByTestId("graph-review-image_review")).toBeVisible({ timeout: 30_000 });

    const outbox = await responseJson<{ items: Array<{ run_id: string; idempotency_key: string; provider_dispatch_count: number }> }>(
      await page.request.get(`${apiBase}/api/v1/image-worker/outbox?run_id=${created.id}`),
    );
    const currentRunDeliveries = outbox.items.filter((item) => item.run_id === created.id);
    expect(currentRunDeliveries.length).toBeGreaterThan(0);
    expect(new Set(currentRunDeliveries.map((item) => item.idempotency_key)).size).toBe(currentRunDeliveries.length);
    expect(currentRunDeliveries.every((item) => item.provider_dispatch_count <= 1)).toBeTruthy();
  });
});
