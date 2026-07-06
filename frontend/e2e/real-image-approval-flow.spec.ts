import { expect, test } from '@playwright/test';

const projectId = 'real-image-approval-flow-project';

test('real image approval flow displays correct labels and buttons', async ({ page }) => {
  // Mock project data
  await page.route(`**/api/v1/projects/${projectId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'ws-1',
        brand_id: 'b-1',
        name: '유아 자전거',
        category: 'Living',
        status: 'images_ready_for_review',
        category_confirmed: true,
      }),
    });
  });

  // Mock page data
  await page.route(`**/api/v1/projects/${projectId}/page`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'page-1',
        project_id: projectId,
        theme_color: '#3B82F6',
        font_family: 'sans-serif',
        sections: [
          {
            id: 'sec-1',
            section_type: 'hero',
            title: '안전하고 즐거운 우리 아이 유아 자전거',
            body_copy: '안심 안전 보호 장치가 장착되어 처음 배우는 아이도 안전하게 라이딩을 즐길 수 있습니다.',
            image_asset_id: null,
            sort_order: 0,
            is_visible: true,
            warnings: [],
          }
        ],
        grounding_summary: {
          warning_count: 0,
          grounded_section_count: 1,
          used_fact_count: 1,
        }
      }),
    });
  });

  // Mock style candidates
  await page.route(`**/api/v1/projects/${projectId}/style-candidates`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        candidates: [],
        selected_key: 'problem_solution',
      }),
    });
  });

  // Mock facts
  await page.route(`**/api/v1/projects/${projectId}/facts`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  // Mock assets
  await page.route(`**/api/v1/projects/${projectId}/assets`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  // Mock backgrounds
  await page.route(`**/api/v1/projects/${projectId}/visual-backgrounds/generate`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  // Mock visual package jobs with the distinct statuses:
  // - awaiting_cost_approval
  // - generating
  // - needs_review
  // - approved
  // - failed
  const mockJobs = [
    {
      job_id: 'job-1',
      section_id: 'sec-1',
      role: 'representative_product',
      source_asset_ids: [],
      prompt: 'A beautiful baby bicycle product shot.',
      negative_prompt: '',
      preserve_product_identity: true,
      output_size: '1024x1024',
      cost_tier: 'premium',
      status: 'awaiting_cost_approval',
    },
    {
      job_id: 'job-2',
      section_id: 'sec-2',
      role: 'lifestyle_scene',
      source_asset_ids: [],
      prompt: 'A child riding bicycle in a sunny park.',
      negative_prompt: '',
      preserve_product_identity: true,
      output_size: '1024x1024',
      cost_tier: 'premium',
      status: 'generating',
    },
    {
      job_id: 'job-3',
      section_id: 'sec-3',
      role: 'cutout_product',
      source_asset_ids: [],
      prompt: 'A clean cutout of the baby bicycle.',
      negative_prompt: '',
      preserve_product_identity: true,
      output_size: '1024x1024',
      cost_tier: 'premium',
      status: 'needs_review',
      output_asset_id: 'asset-out-3',
    },
    {
      job_id: 'job-4',
      section_id: 'sec-4',
      role: 'detail_closeup',
      source_asset_ids: [],
      prompt: 'A close up of the safety brake handle.',
      negative_prompt: '',
      preserve_product_identity: true,
      output_size: '1024x1024',
      cost_tier: 'premium',
      status: 'approved',
      output_asset_id: 'asset-out-4',
    },
    {
      job_id: 'job-5',
      section_id: 'sec-5',
      role: 'cta_visual',
      source_asset_ids: [],
      prompt: 'Call to action banner for the bicycle.',
      negative_prompt: '',
      preserve_product_identity: false,
      output_size: '1024x1024',
      cost_tier: 'premium',
      status: 'failed',
      error_code: 'QUALITY_GATE_FAILED',
    },
  ];

  await page.route(`**/api/v1/projects/${projectId}/visual-package`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(mockJobs),
    });
  });

  // Navigate to page editor
  await page.goto(`/workspace/projects/${projectId}/page-editor`);

  // Switch to Visual tab
  await page.getByRole('button', { name: '🖼️ 비주얼 패키지' }).click();

  // Assert status badges
  await expect(page.getByText('비용 승인 필요')).toBeVisible();
  await expect(page.getByText('생성 중')).toBeVisible();
  await expect(page.getByText('검수 필요')).toBeVisible();
  await expect(page.getByText('선택됨').first()).toBeVisible();

  // Assert action buttons
  await expect(page.getByRole('button', { name: '⚡ AI 이미지 생성' })).toBeVisible();
  await expect(page.getByRole('button', { name: '✓ 이 이미지 사용' })).toBeVisible();
  await expect(page.getByRole('button', { name: '재생성' })).toBeVisible();
});
