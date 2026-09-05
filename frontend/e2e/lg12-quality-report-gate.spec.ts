import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const repoRoot = resolve(__dirname, "../..");
const backendDir = resolve(repoRoot, "backend");
const python = process.env.SELLFORM_E2E_PYTHON ?? resolve(backendDir, ".venv", "Scripts", "python.exe");

type Seed = {
  browser_url: string;
  auth_headers: Record<string, string>;
};

function browserPath(fixture: Seed): string {
  const url = new URL(fixture.browser_url);
  return `${url.pathname}${url.search}${url.hash}`;
}

function seed(state: "pass-ready" | "fail" | "needs-review"): Seed {
  if (process.env.SELLFORM_RUN_REAL_PROVIDER_SMOKE === "1") {
    throw new Error("LG-12 browser E2E must not run while the real-provider opt-in flag is enabled.");
  }
  const auth_headers = {
    "X-Mock-User-Id": randomUUID(),
    "X-Mock-Workspace-Id": randomUUID(),
  };
  const output = execFileSync(python, ["tests/seed_lg12_quality_promotion_e2e.py", "--state", state], {
    cwd: backendDir,
    encoding: "utf8",
    env: {
      ...process.env,
      APP_ENV: "test",
      SELLFORM_ALLOW_TEST_DATABASE: "1",
      SELLFORM_AUTH_MODE: "test",
      SELLFORM_AUTH_ALLOW_TEST_MOCK: "true",
      SELLFORM_IMAGE_GENERATION_MODE: "mock",
      SELLFORM_IMAGE_WORKER_ENABLED: "false",
      SELLFORM_E2E_SEED_USER_ID: auth_headers["X-Mock-User-Id"],
      SELLFORM_E2E_SEED_WORKSPACE_ID: auth_headers["X-Mock-Workspace-Id"],
      PYTHONPATH: [backendDir, process.env.PYTHONPATH].filter(Boolean).join(";"),
    },
  });
  return { ...(JSON.parse(output.trim().split(/\r?\n/).at(-1) ?? "") as Omit<Seed, "auth_headers">), auth_headers };
}

test.describe.serial("LG-12 quality report gate (real local persistence)", () => {
  test.skip(process.env.SELLFORM_E2E_REAL_BACKEND !== "1", "Requires local Next.js + FastAPI + Docker PostgreSQL.");

  test("PASS is promoted and remains export-ready after reload", async ({ page }) => {
    const fixture = seed("pass-ready");
    await page.setExtraHTTPHeaders(fixture.auth_headers);
    await page.goto(browserPath(fixture));
    await expect(page.getByTestId("lg12-quality-status")).toContainText("품질 검토를 통과했습니다");
    await page.getByTestId("lg12-promote-page").click();
    await expect(page.getByTestId("lg12-export-ready-smartstore")).toBeVisible();
    await page.reload();
    await expect(page.getByTestId("lg12-quality-status")).toContainText("상세페이지를 내보낼 준비가 되었습니다");
    await expect(page.getByTestId("lg12-smartstore-standalone-export")).toBeVisible();
  });

  test("FAIL shows rework and keeps promotion/export unavailable", async ({ page }) => {
    const fixture = seed("fail");
    await page.setExtraHTTPHeaders(fixture.auth_headers);
    await page.goto(browserPath(fixture));
    await expect(page.getByTestId("lg12-quality-rework")).toContainText("수정이 필요합니다");
    await expect(page.getByTestId("lg12-promote-page")).toHaveCount(0);
    await expect(page.getByTestId("lg12-export-ready-smartstore")).toHaveCount(0);
  });

  test("NEEDS_REVIEW exposes a seller action and keeps promotion/export unavailable", async ({ page }) => {
    const fixture = seed("needs-review");
    await page.setExtraHTTPHeaders(fixture.auth_headers);
    await page.goto(browserPath(fixture));
    await expect(page.getByTestId("graph-review-quality_review")).toBeVisible();
    await expect(page.getByText("판매자 확인 대기")).toBeVisible();
    await expect(page.getByTestId("lg12-promote-page")).toHaveCount(0);
    await expect(page.getByTestId("lg12-export-ready-smartstore")).toHaveCount(0);
    const body = await page.locator("body").innerText();
    for (const internalTerm of ["LangGraph", "routing_code", "checkpoint", "evaluator bundle", "QualityAssessmentReportVersion"]) {
      expect(body).not.toContain(internalTerm);
    }
  });
});