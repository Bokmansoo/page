import { expect, test } from "@playwright/test";

test("LG-6 manages prompt lifecycle, Golden evaluation and immutable Brand Kit via asset picker", async ({ page }) => {
  const calls: string[] = [];
  let packs: Array<Record<string, unknown>> = [];
  let kits: Array<Record<string, unknown>> = [];
  let versions: Array<Record<string, unknown>> = [];

  await page.route("**/api/v1/projects", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify([{ id: "project-1", name: "선풍기" }]),
  }));
  await page.route("**/api/v1/brand-kits**", async (route) => {
    const url = route.request().url(); const method = route.request().method(); calls.push(`${method} ${url}`);
    if (method === "GET" && url.endsWith("/brand-kits/assets")) return route.fulfill({
      status: 200, contentType: "application/json", body: JSON.stringify([
        { id: "asset-logo", filename: "logo.png", file_path: "logo.png", usage_status: "seller_owned", asset_role: "logo" },
        { id: "asset-font", filename: "brand.woff2", file_path: "brand.woff2", usage_status: "seller_owned", asset_role: "font" },
      ]),
    });
    if (method === "GET") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ kits, versions }) });
    if (url.endsWith("/api/v1/brand-kits")) kits = [{ id: "kit-1", name: "기본 브랜드 키트" }];
    else if (url.includes("/projects/project-1/overrides")) versions = [{ id: "override-1", brand_kit_id: "kit-1", version: 2, status: "active", scope: "project", project_id: "project-1", content_hash: "b".repeat(64) }, ...versions];
    else if (url.includes("/kit-1/versions")) versions = [{ id: "version-1", brand_kit_id: "kit-1", version: 1, status: "draft", scope: "workspace", content_hash: "a".repeat(64) }];
    else if (url.includes("/versions/version-1/activate")) versions[0] = { ...versions[0], status: "active" };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.route("**/api/v1/prompt-intelligence/**", async (route) => {
    const url = route.request().url(); calls.push(`${route.request().method()} ${url}`);
    if (route.request().method() === "GET" && url.endsWith("/packs")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(packs) });
    }
    if (url.endsWith("/packs/seed")) packs = [{ id: "pack-1", pack_type: "category", pack_key: "other", version: 1, status: "active", content_hash: "c".repeat(64) }];
    if (url.endsWith("/evaluate")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accuracy: 1, dataset_version: "lg6-golden-v1" }) });
    if (url.endsWith("/classify")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ category: "전자제품", confidence: 0.95, rationale: "분류 단어: 무선, 충전", fallback: false, classifier_version: "sellform-category-keyword-v1" }) });
    if (url.endsWith("/packs/propose")) packs = [{ id: "draft-2", pack_type: "category", pack_key: "other", version: 2, status: "draft_generated", content_hash: "d".repeat(64) }, ...packs];
    return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  await page.goto("/workspace/settings/intelligence");
  await expect(page.getByTestId("prompt-pack-admin")).toBeVisible();
  await page.getByRole("button", { name: "기본 팩 준비" }).click();
  await expect(page.getByText("category · other")).toBeVisible();
  await page.getByRole("button", { name: "분류 정확도 평가" }).click();
  await expect(page.getByText("정확도:")).toContainText("100.0%");
  await page.getByRole("button", { name: "분류 확인" }).click();
  await expect(page.getByTestId("classifier-preview")).toContainText("전자제품");
  await page.getByRole("button", { name: "새 draft 제안" }).click();
  await expect(page.getByText("v2 draft_generated")).toBeVisible();

  await page.getByRole("button", { name: "Kit 만들기" }).click();
  await page.getByLabel("대상 Brand Kit").selectOption("kit-1");
  await page.getByLabel("logo.png 로고로 사용").check();
  await page.getByLabel("brand.woff2 폰트로 사용").check();
  await page.getByRole("button", { name: "Workspace 버전 만들기" }).click();
  await expect(page.getByText("v1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "활성화" }).click();
  await page.getByRole("button", { name: "프로젝트 override 만들기" }).click();
  expect(calls.some((call) => call.includes("/projects/project-1/overrides"))).toBeTruthy();
  expect(calls.some((call) => call.includes("/prompt-intelligence/evaluate"))).toBeTruthy();

  await page.reload();
  await expect(page.getByText("project").first()).toBeVisible();
  await expect(page.getByText("active").first()).toBeVisible();
});
