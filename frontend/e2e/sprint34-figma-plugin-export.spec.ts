import { expect, test } from '@playwright/test';

const projectId = 'figma-plugin-project';

test.beforeEach(async ({ page }) => {
  await page.route(`**/api/v1/projects/${projectId}**`, async route => {
    const request = route.request();
    const url = request.url();

    if (url.endsWith('/page/figma-plugin/tickets') && request.method() === 'POST') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          ticket_id: 'ticket-1',
          code: 'SF-8K4P-2M7Q',
          expires_at: '2026-06-28T12:10:00Z',
          status: 'issued',
        }),
      });
      return;
    }

    if (url.endsWith('/page/figma-plugin/package.json')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: '1.0',
          payload: { project: {}, brand: {}, page: {}, cuts: [] },
          embedded_assets: [],
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
          theme_color: '#5B7CFA',
          font_family: 'Inter',
          sections: [],
        }),
      });
      return;
    }
    if (url.endsWith('/facts') || url.endsWith('/assets')) {
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

    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'workspace-1',
        brand_id: 'brand-1',
        name: '루메나 선풍기',
        status: 'checking',
        current_step: 'page_editor',
        category: 'Living',
        category_confirmed: true,
      }),
    });
  });
});

test('plugin export is the default flow and issues a copyable ticket', async ({ page }) => {
  await page.goto(`/workspace/projects/${projectId}/page-editor`);
  await page.getByRole('button', { name: 'Figma로 내보내기' }).click();

  await expect(page.getByRole('heading', { name: 'Figma 플러그인으로 내보내기' })).toBeVisible();
  await expect(page.getByText('Figma Live 자동 내보내기')).toHaveCount(0);

  await page.getByRole('button', { name: '인증 코드 생성' }).click();
  await expect(page.getByText('SF-8K4P-2M7Q')).toBeVisible();
  await expect(page.getByRole('button', { name: '복사' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'JSON 패키지 다운로드' })).toBeVisible();
});
