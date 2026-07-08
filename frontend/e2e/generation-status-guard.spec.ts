import { expect, test } from "@playwright/test";

const dashboardFixture = {
  summary: {
    running: 1,
    waiting_for_cost_approval: 0,
    needs_review: 0,
    completed: 1,
    failed: 0,
    estimated_cost: 0.12,
    actual_cost: 0.08,
  },
  projects: [
    {
      project_id: "project-running",
      project_name: "루메나 휴대용 무선 냉각선풍기",
      state: "running",
      current_stage: "image_generation",
      progress_percent: 76,
      can_start_new_run: false,
      recommended_action: "view_status",
      result_url: null,
      review_url: null,
      active_run: {
        id: "run-running-id",
        status: "running",
        current_stage: "image_generation",
        estimated_cost: 0.12,
        actual_cost: 0.08,
        created_at: "2026-07-06T12:03:00",
        updated_at: "2026-07-06T12:03:00",
      },
      cost: {
        estimated: 0.12,
        actual: 0.08,
        token_input: 1200,
        token_output: 500,
      },
      last_error: null,
      updated_at: "2026-07-06T12:03:00",
    },
    {
      project_id: "project-completed",
      project_name: "루메나 휴대용 무선 냉각선풍기 완성본",
      state: "completed",
      current_stage: "review_editor",
      progress_percent: 100,
      can_start_new_run: true,
      recommended_action: "view_result",
      result_url: "/workspace/projects/project-completed/result",
      review_url: "/workspace/projects/project-completed/page-editor?mode=review",
      cost: {
        estimated: 0.12,
        actual: 0.08,
        token_input: 1200,
        token_output: 500,
      },
      last_error: null,
      updated_at: "2026-07-06T12:13:00",
    },
  ],
};

test("operations page shows user friendly duplicate generation status", async ({ page }) => {
  await page.route("**/api/v1/operations/generation-status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(dashboardFixture),
    });
  });

  await page.goto("/workspace/operations?projectId=project-running");

  await expect(page.getByRole("heading", { name: "이미 작업 중인 상세페이지를 확인하세요" })).toBeVisible();
  await expect(page.getByText("이미 진행 중인 상세페이지가 있습니다")).toBeVisible();
  await expect(page.getByText("중복 생성으로 토큰과 시간이 다시 쓰이지 않도록")).toBeVisible();
  await expect(page.getByText("루메나 휴대용 무선 냉각선풍기").first()).toBeVisible();
  await expect(page.getByText("이미지 생성").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "이어서 진행" }).first()).toHaveAttribute(
    "href",
    "/workspace?runId=run-running-id",
  );
});

test("operations page translates completed action to result link", async ({ page }) => {
  await page.route("**/api/v1/operations/generation-status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(dashboardFixture),
    });
  });

  await page.goto("/workspace/operations?projectId=project-completed");

  await expect(page.getByText("같은 상품으로 이미 완성된 상세페이지가 있어요")).toBeVisible();
  await expect(page.getByRole("link", { name: "결과 보기" }).first()).toHaveAttribute(
    "href",
    "/workspace/projects/project-completed/result",
  );
});
