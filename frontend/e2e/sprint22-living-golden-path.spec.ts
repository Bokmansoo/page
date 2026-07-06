import { Page, expect, test } from '@playwright/test';

const projectId = 'project-living-golden-path';

const corsHeaders = {
  'access-control-allow-origin': '*',
  'content-type': 'application/json',
};

async function mockSprint22Api(page: Page) {
  await page.route('http://localhost:8001/api/v1/projects', async (route) => {
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      json: [
        {
          id: projectId,
          name: '루메나 휴대용 무선 냉각선풍기',
          status: 'checking',
          current_step: 'facts_verification',
          category: 'Living',
          category_confirmed: false,
          assets: [],
          created_at: '2026-06-24T00:00:00Z',
          updated_at: '2026-06-24T00:00:00Z',
        },
      ],
    });
  });

  await page.route(`http://localhost:8001/api/v1/projects/${projectId}`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      json: {
        id: projectId,
        workspace_id: 'workspace-1',
        brand_id: 'brand-1',
        name: '루메나 휴대용 무선 냉각선풍기',
        product_url: '',
        image_url: null,
        status: 'checking',
        current_step: 'facts_verification',
        category: 'Living',
        category_confirmed: false,
        category_confirmed_at: null,
        assets: [],
        selected_style: 'problem_solution',
        created_at: '2026-06-24T00:00:00Z',
        updated_at: '2026-06-24T00:00:00Z',
      },
    });
  });

  await page.route(`http://localhost:8001/api/v1/projects/${projectId}/facts`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      json: [
        {
          id: 'fact-1',
          project_id: projectId,
          fact_text: '4,800mAh 배터리',
          source_text: '상세 스펙 4,800mAh',
          source_asset_id: null,
          verification_status: 'confirmed',
          extraction_source: 'manual_text',
          confidence: 0.98,
          needs_review: false,
          risk_flags: [],
          created_at: '2026-06-24T00:00:00Z',
          updated_at: '2026-06-24T00:00:00Z',
        },
        {
          id: 'fact-2',
          project_id: projectId,
          fact_text: '최대 18시간 무선 사용 가능',
          source_text: '최대 18시간',
          source_asset_id: null,
          verification_status: 'confirmed',
          extraction_source: 'manual_text',
          confidence: 0.95,
          needs_review: false,
          risk_flags: [],
          created_at: '2026-06-24T00:00:00Z',
          updated_at: '2026-06-24T00:00:00Z',
        },
      ],
    });
  });

  await page.route(`http://localhost:8001/api/v1/projects/${projectId}/page`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      json: {
        id: 'page-1',
        project_id: projectId,
        theme_color: '#2563EB',
        font_family: 'sans-serif',
        grounding_summary: {
          warning_count: 0,
          grounded_section_count: 1,
          used_fact_count: 1,
        },
        sections: [
          {
            id: 'section-1',
            section_type: 'header',
            title: '시원한 휴대용 냉각',
            body_copy: '짧음',
            associated_fact_ids: ['fact-1'],
            image_asset_id: null,
            sort_order: 0,
            is_visible: true,
            warnings: [],
            grounding_warnings: [],
            matched_facts: ['4,800mAh 배터리'],
          },
        ],
      },
    });
  });

  await page.route(`http://localhost:8001/api/v1/projects/${projectId}/page/versions`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      json: [
        {
          id: 'version-1',
          project_id: projectId,
          name: 'AI 초안 생성',
          style_key: 'problem_solution',
          is_final: false,
          created_at: '2026-06-24T00:00:00Z',
        },
      ],
    });
  });

  await page.route(`http://localhost:8001/api/v1/projects/${projectId}/page/compliance`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: corsHeaders,
      json: { can_export: true, issues: [] },
    });
  });

  await page.route(`http://localhost:8001/api/v1/projects/${projectId}/page/export/jobs`, async (route) => {
    await route.fulfill({ status: 200, headers: corsHeaders, json: [] });
  });
}

test('facts step blocks progress until enough confirmed facts and category confirmation exist', async ({ page }) => {
  await mockSprint22Api(page);

  await page.goto(`/workspace/projects/${projectId}/facts`);

  await expect(page.getByText('2 사실 확인')).toBeVisible();
  await expect(page.getByText('확인된 사실 카드가 3개 이상 필요합니다.')).toBeVisible();
  await expect(page.getByText('카테고리를 확정해야 상세페이지 구조를 안정적으로 만들 수 있습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: /검증 완료 및 다음 단계/ })).toBeDisabled();
});

test('page editor shows short copy warning and export readiness status', async ({ page }) => {
  await mockSprint22Api(page);

  await page.goto(`/workspace/projects/${projectId}/page-editor`);

  await expect(page.getByText('4 상세페이지 편집')).toBeVisible();
  await expect(page.getByText('이 섹션은 문구가 짧습니다. 핵심 사실과 사용 장면을 한 문장 더 추가해 보세요.').first()).toBeVisible();
  await expect(page.getByText('자동 저장됨')).toBeVisible();
  await expect(page.getByText('최종본 미지정')).toBeVisible();
  await expect(page.getByText('export 준비 전')).toBeVisible();
});

test('export step requires a final version before package generation', async ({ page }) => {
  await mockSprint22Api(page);

  await page.goto(`/workspace/projects/${projectId}/export`);

  await expect(page.getByText('5 저장/내보내기')).toBeVisible();
  await expect(page.getByText('최종본으로 지정된 상세페이지 버전이 없습니다. 에디터에서 최종본으로 지정해 주세요.')).toBeVisible();
  await expect(page.getByRole('button', { name: '판매처 이미지 패키지 생성' })).toBeDisabled();
});
