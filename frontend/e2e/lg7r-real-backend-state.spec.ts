import { expect, test } from "@playwright/test";

const appBase = process.env.SELLFORM_E2E_REAL_APP_URL ?? "http://localhost:3000";
const apiBase = process.env.SELLFORM_E2E_REAL_API_URL ?? "http://localhost:8001";

test.describe("LG-7R real backend state", () => {
  test.skip(process.env.SELLFORM_E2E_REAL_BACKEND !== "1", "실제 백엔드 E2E에서만 실행합니다.");

  test("collected review asset, LangGraph interrupt/resume, and refresh recovery use the real API and DB", async ({ page }) => {
    const login = await page.request.post(`${apiBase}/api/v1/auth/development-login`);
    expect(login.ok(), await login.text()).toBeTruthy();

    const created = await page.request.post(`${apiBase}/api/agent-runs`, {
      data: {
        product_name: `LG-7R 실제 브라우저 검증 ${Date.now()}`,
        category: "전자제품",
        description: "USB 충전 휴대용 선풍기. 판매자가 확인한 정격 입력 DC 5V 2A.",
        ux_auto_generate: false,
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const run = await created.json() as { id: string; project_id: string };

    await page.setContent('<main id="product" style="width:1024px;height:1024px;display:grid;place-items:center;background:#f8fafc"><div style="width:420px;height:620px;border-radius:210px;background:#2563eb;position:relative"><div style="position:absolute;width:300px;height:300px;left:60px;top:70px;border:30px solid white;border-radius:50%"></div></div></main>');
    const productPng = await page.locator("#product").screenshot();
    const uploadedImage = await page.request.post(`${apiBase}/api/v1/files/upload`, {
      multipart: {
        project_id: run.project_id,
        source_type: "uploaded",
        file: { name: "lg7r-product.png", mimeType: "image/png", buffer: productPng },
      },
    });
    expect(uploadedImage.status(), await uploadedImage.text()).toBe(201);
    const imageAsset = await uploadedImage.json() as { id: string };

    const reviewText = "가볍고 충전이 간편해 출퇴근에 편리하지만 강풍 단계의 소음은 확인이 필요합니다.";
    const uploadedReview = await page.request.post(`${apiBase}/api/v1/files/upload`, {
      multipart: {
        project_id: run.project_id,
        source_type: "sourced",
        file: { name: "lg7r-collected-reviews.txt", mimeType: "text/plain", buffer: Buffer.from(reviewText, "utf8") },
      },
    });
    expect(uploadedReview.status(), await uploadedReview.text()).toBe(201);
    const reviewAsset = await uploadedReview.json() as { id: string };

    const bundle = await page.request.patch(`${apiBase}/api/agent-runs/${run.id}/input-assets`, {
      data: { asset_ids: [imageAsset.id] },
    });
    expect(bundle.ok(), await bundle.text()).toBeTruthy();

    const started = await page.request.post(`${apiBase}/api/v1/graph-runs/${run.id}/start`);
    expect(started.ok(), await started.text()).toBeTruthy();
    expect((await started.json()).current_stage).toBe("input_review");

    await page.goto(`${appBase}/workspace/projects/${run.project_id}/planning?runId=${run.id}`);
    await expect(page.getByText("LangGraph 승인 대기 · input_review")).toBeVisible();

    const reviewFileInput = page.locator('input[type="file"][accept=".csv,.xlsx,.txt"]');
    await reviewFileInput.setInputFiles({
      name: "broken-reviews.xlsx",
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("not-an-openxml-package", "utf8"),
    });
    const structuredError = page.getByRole("status").filter({ hasText: "REVIEW_XLSX_CORRUPT" });
    await expect(structuredError).toContainText("XLSX 파일이 손상되어 읽을 수 없습니다.");
    await expect(structuredError).toContainText("해결 방법:");
    await expect(structuredError).not.toContainText("[object Object]");

    const collectedAssetSelect = page.getByLabel("기존 수집 리뷰 자료");
    await expect(collectedAssetSelect.locator(`option[value="${reviewAsset.id}"]`)).toContainText("lg7r-collected-reviews.txt");
    await collectedAssetSelect.selectOption(reviewAsset.id);
    await page.getByRole("button", { name: "자료 연결" }).click();
    await expect(page.getByText("리뷰 1개")).toBeVisible();
    await expect(page.getByText("기존 수집 자료를 리뷰 분석에 연결했습니다.")).toBeVisible();

    await page.getByRole("button", { name: "확인·다음 단계" }).click();
    await expect(page.getByText("LangGraph 승인 대기 · evidence_review")).toBeVisible();
    await page.reload();
    await expect(page.getByText("LangGraph 승인 대기 · evidence_review")).toBeVisible();
    await expect(page.getByText("입력 사용 여부")).toBeVisible();

    const intelligence = await page.request.get(`${apiBase}/api/v1/projects/${run.project_id}/creative-intelligence?run_id=${run.id}`);
    expect(intelligence.ok(), await intelligence.text()).toBeTruthy();
    const intelligenceBody = await intelligence.json();
    expect(intelligenceBody.reviews).toEqual(expect.arrayContaining([
      expect.objectContaining({ source_asset_id: reviewAsset.id }),
    ]));
    expect(intelligenceBody.trace).toEqual(expect.objectContaining({ interaction_mode: "expert" }));
  });
});
