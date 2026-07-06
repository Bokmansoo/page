import { expect, test } from "@playwright/test";

test("operations page shows generation status dashboard", async ({ page }) => {
  await page.route("**/api/v1/operations/stats", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        summary: {
          total_projects: 1,
          total_ai_jobs: 1,
          ai_job_success_rate: 100,
          ai_job_failure_rate: 0,
          average_ai_duration_seconds: 3,
          total_ai_cost: 0.08,
          total_export_jobs: 0,
          export_job_success_rate: 100,
          export_job_failure_rate: 0,
          average_export_duration_seconds: 0,
        },
        category_stats: {},
        projects: [],
      }),
    });
  });

  await page.route("**/api/v1/operations/generation-status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        summary: {
          running: 1,
          waiting_for_cost_approval: 0,
          needs_review: 0,
          completed: 0,
          failed: 0,
          estimated_cost: 0.12,
          actual_cost: 0.08,
        },
        projects: [
          {
            project_id: "project-1",
            project_name: "루메나 휴대용 무선 냉각선풍기",
            state: "running",
            current_stage: "image_generation",
            progress_percent: 76,
            can_start_new_run: false,
            recommended_action: "view_status",
            result_url: null,
            review_url: null,
            cost: {
              estimated: 0.12,
              actual: 0.08,
              token_input: 1200,
              token_output: 500,
            },
            last_error: null,
            updated_at: "2026-07-06T12:03:00",
          },
        ],
      }),
    });
  });

  await page.goto("/workspace/operations");

  await expect(page.getByText("현재 생성 작업 상태")).toBeVisible();
  await expect(page.getByText("루메나 휴대용 무선 냉각선풍기")).toBeVisible();
  await expect(page.getByRole("cell", { name: "생성 중" })).toBeVisible();
  await expect(page.getByText("image_generation")).toBeVisible();
  await expect(page.getByText("in 1200 / out 500")).toBeVisible();
});

test("intake shows duplicate run dialog when backend blocks repeated generation", async ({ page }) => {
  await page.route("**/api/agent-runs", async (route) => {
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "generation_already_running",
          message: "이미 이 상품의 상세페이지 생성이 진행 중입니다.",
          project_id: "project-1",
          run_id: "run-1",
          state: "running",
          status_url: "/workspace/operations?projectId=project-1",
          result_url: null,
        },
      }),
    });
  });

  await page.goto("/workspace");
  await page.getByPlaceholder("상품명").fill("루메나 휴대용 무선 냉각선풍기");
  await page.getByLabel("상품 자료").fill("무선 냉각선풍기");
  await page.getByRole("button", { name: "AI 상세페이지 만들기" }).click();

  await expect(page.getByRole("dialog", { name: "이미 진행 중인 작업" })).toBeVisible();
  await expect(page.getByText("중복 생성을 막았습니다")).toBeVisible();
  await expect(page.getByText("작업 상태 보기")).toBeVisible();
});
