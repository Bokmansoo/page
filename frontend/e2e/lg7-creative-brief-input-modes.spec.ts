import { expect, test } from "@playwright/test";

test("LG-7 persists separate review/reference inputs and mode changes across refresh", async ({ page }) => {
  const projectId = "lg7-project"; const runId = "lg7-run";
  let mode: "quick" | "expert" = "quick";
  let reviews: Array<Record<string, unknown>> = [];
  let references: Array<Record<string, unknown>> = [];
  let direction: Record<string, unknown> | null = null;
  const calls: string[] = [];

  await page.route(`**/api/v1/projects/${projectId}/planning-draft`, route => route.fulfill({ status: 404, body: "{}" }));
  await page.route(`**/api/v1/projects/${projectId}/assets`, route => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/projects/${projectId}/source-captures`, route => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/v1/graph-runs/${runId}**`, route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ run_id: runId, status: "awaiting_review", current_stage: "input_review", values: { review: { pending: { schema_version: "lg4-v1", review_stage: "input_review", title: "상품 입력 확인", description: "확인", allowed_decisions: ["approve", "reject"] } } } }) }));
  await page.route(`**/api/v1/projects/${projectId}/creative-intelligence**`, route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ interaction_mode: mode, reviews, references, creative_direction: direction, briefs: [], review_asset_options: [] }) }));
  await page.route(`**/api/v1/projects/${projectId}/review-inputs`, route => { calls.push("review"); reviews = [{ id: "r1", version: 1, format: "paste", fact_promotion_status: "blocked", consent_status: "confirmed", rights_status: "seller_owned" }]; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "r1", fact_promotion_status: "blocked" }) }); });
  await page.route(`**/api/v1/projects/${projectId}/reference-inputs`, route => { calls.push("reference"); references = [{ id: "ref1", version: 1, kind: "url", rights_status: "unverified", usage_scope: "analysis_only" }]; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "ref1", usage_scope: "analysis_only" }) }); });
  await page.route(`**/api/v1/projects/${projectId}/creative-direction`, route => { calls.push("direction"); direction = { version: 1, target_audience: "출퇴근 고객", desired_mood: ["깔끔한"] }; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(direction) }); });
  await page.route(`**/api/v1/agent-runs/${runId}/interaction-mode`, route => { mode = route.request().postDataJSON().interaction_mode; calls.push(`mode:${mode}`); return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ interaction_mode: mode, artifacts_preserved: true }) }); });

  await page.goto(`/workspace/projects/${projectId}/planning?runId=${runId}`);
  await expect(page.getByText("리뷰·레퍼런스·창작 방향")).toBeVisible();
  await page.getByLabel("리뷰 붙여넣기").fill("가볍고 조용하지만 손잡이는 불편해요");
  await page.getByRole("button", { name: "분석 저장" }).click();
  await page.getByLabel("레퍼런스 내용").fill("https://example.com/reference");
  await page.getByRole("button", { name: "추상 신호 저장" }).click();
  await page.getByLabel("타깃 고객").fill("출퇴근 고객");
  await page.getByLabel("원하는 분위기").fill("깔끔한");
  await page.getByRole("button", { name: "방향 저장" }).click();
  await page.getByRole("button", { name: "전문가 검수" }).click();
  await expect(page.getByText("리뷰 1개")).toBeVisible();
  await expect(page.getByText("레퍼런스 1개")).toBeVisible();
  await expect(page.getByText(/사실 승격 차단/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "전문가 검수" })).toHaveClass(/bg-violet-600/);
  expect(calls).toEqual(expect.arrayContaining(["review", "reference", "direction", "mode:expert"]));
});
