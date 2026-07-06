import { expect, test } from '@playwright/test';

const projectId = 'sprint36-image-mapping';

test.beforeEach(async ({ page }) => {
  await page.route(`**/api/v1/projects/${projectId}**`, async route => {
    const request = route.request();
    const url = request.url();

    if (url.endsWith('/page/auto-map-images') && request.method() === 'POST') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          project_id: projectId,
          assigned_count: 1,
          skipped_count: 0,
          missing_roles: ['lifestyle_scene'],
          assignments: [
            {
              section_id: 'section-1',
              section_type: 'main_claim',
              asset_id: 'asset-1',
              filename: 'fan-main-product.jpg',
              asset_role: 'product_main',
              confidence: 0.82,
              reason: 'product_main 역할과 main_claim 섹션의 적합도 90점',
            },
          ],
        }),
      });
      return;
    }

    if (url.endsWith('/page/versions')) {
      await route.fulfill({ contentType: 'application/json', body: '[]' });
      return;
    }
    if (url.endsWith('/page')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'page-1',
          project_id: projectId,
          theme_color: '#2D7DFF',
          font_family: 'Inter',
          sections: [
            {
              id: 'section-1',
              section_type: 'main_claim',
              title: '작지만 강력한 바람',
              body_copy: '휴대하기 편한 냉각 선풍기입니다.',
              associated_fact_ids: [],
              image_asset_id: null,
              sort_order: 0,
              is_visible: true,
              warnings: [],
            },
          ],
        }),
      });
      return;
    }
    if (url.endsWith('/assets')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'asset-1',
            filename: 'fan-main-product.jpg',
            file_path: 'uploads/fan-main-product.jpg',
            mime_type: 'image/jpeg',
            source_type: 'uploaded',
          },
        ]),
      });
      return;
    }
    if (url.endsWith('/facts')) {
      await route.fulfill({ contentType: 'application/json', body: '[]' });
      return;
    }
    if (url.endsWith('/style-candidates')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ candidates: [], selected_key: null }),
      });
      return;
    }
    if (url.includes('/visual-backgrounds/generate')) {
      await route.fulfill({ contentType: 'application/json', body: '[]' });
      return;
    }

    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'workspace-1',
        brand_id: 'brand-1',
        name: '루메나 휴대용 무선 냉각선풍기',
        product_url: '',
        image_url: null,
        status: 'checking',
        current_step: 'page_editor',
        category: 'Living',
        category_confirmed: true,
        created_at: '2026-06-29T00:00:00Z',
        updated_at: '2026-06-29T00:00:00Z',
      }),
    });
  });
});

test('shows image mapping status, confidence and missing-role guidance', async ({ page }) => {
  await page.goto(`/workspace/projects/${projectId}/page-editor`);

  const panel = page.getByTestId('image-mapping-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByText('fan-main-product.jpg')).toBeVisible();

  await panel.getByRole('button', { name: '이미지 자동 배치' }).click();

  await expect(panel.getByText('product_main')).toBeVisible();
  await expect(panel.getByText('82%')).toBeVisible();
  await expect(panel.getByText(/생활 사용 장면 이미지가 필요합니다/)).toBeVisible();
});
