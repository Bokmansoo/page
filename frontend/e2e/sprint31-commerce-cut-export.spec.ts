import { expect, test } from '@playwright/test';

test('export request enables commerce cut rendering', async ({ page }) => {
  let exportRequestBody: Record<string, unknown> | null = null;

  await page.route('**/api/v1/projects/test-project/page/**', async route => {
    const request = route.request();
    const url = request.url();

    if (url.endsWith('/compliance')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ can_export: true, issues: [] }),
      });
      return;
    }

    if (url.endsWith('/versions')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'version-final',
            name: '최종본',
            style_key: 'living',
            is_final: true,
            created_at: '2026-06-27T00:00:00Z',
          },
        ]),
      });
      return;
    }

    if (url.endsWith('/export/jobs') && request.method() === 'GET') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }

    if (url.endsWith('/export') && request.method() === 'POST') {
      exportRequestBody = request.postDataJSON();
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'export-job-1',
          project_id: 'test-project',
          preset_name: 'coupang',
          status: 'pending',
          error_message: null,
          zip_asset_id: null,
          output_images: null,
          created_at: '2026-06-27T00:00:00Z',
          completed_at: null,
        }),
      });
      return;
    }

    if (url.endsWith('/export/jobs/export-job-1')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'export-job-1',
          project_id: 'test-project',
          preset_name: 'coupang',
          status: 'completed',
          error_message: null,
          zip_asset_id: 'zip-1',
          output_images: [],
          created_at: '2026-06-27T00:00:00Z',
          completed_at: '2026-06-27T00:00:01Z',
        }),
      });
      return;
    }

    await route.fulfill({ status: 404, body: '{}' });
  });

  await page.goto('/workspace/projects/test-project/export');

  const checklist = page.locator('aside input[type="checkbox"]');
  await expect(checklist).toHaveCount(4);
  for (let index = 0; index < 4; index += 1) {
    await checklist.nth(index).check();
  }

  await page.locator('aside button').last().click();

  await expect.poll(() => exportRequestBody).not.toBeNull();
  expect(exportRequestBody).toEqual({
    preset_name: 'coupang',
    use_commerce_cut: true,
  });
});
