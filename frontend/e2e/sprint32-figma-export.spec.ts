import { expect, test } from '@playwright/test';

const projectId = 'figma-project';

test('page editor prepares a Figma design payload without requiring an active MCP connection', async ({ page }) => {
  let figmaExportRequested = false;

  await page.route(`**/api/v1/projects/${projectId}**`, async route => {
    const request = route.request();
    const url = request.url();

    if (url.endsWith('/page/figma/export') && request.method() === 'POST') {
      figmaExportRequested = true;
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ready',
          mcp_status: 'disabled',
          payload: { project: { id: projectId }, cuts: [] },
          message: 'Figma 연동은 비활성 상태이며 디자인 payload만 생성되었습니다.',
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
          font_family: 'sans-serif',
          sections: [
            {
              id: 'section-1',
              section_type: 'header',
              title: '시원한 휴대용 냉각',
              body_copy: '확인된 상품 사실을 바탕으로 작성한 문구입니다.',
              associated_fact_ids: ['fact-1'],
              image_asset_id: null,
              sort_order: 0,
              is_visible: true,
              warnings: [],
              grounding_warnings: [],
              matched_facts: [],
            },
          ],
        }),
      });
      return;
    }

    if (url.endsWith('/facts')) {
      await route.fulfill({ contentType: 'application/json', body: '[]' });
      return;
    }

    if (url.endsWith('/assets') || url.endsWith('/style-candidates')) {
      await route.fulfill({
        contentType: 'application/json',
        body: url.endsWith('/assets') ? '[]' : JSON.stringify({ candidates: [], selected_key: null }),
      });
      return;
    }

    if (url.endsWith('/visual-backgrounds/generate')) {
      await route.fulfill({ contentType: 'application/json', body: '[]' });
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
        created_at: '2026-06-27T00:00:00Z',
        updated_at: '2026-06-27T00:00:00Z',
      }),
    });
  });

  await page.goto(`/workspace/projects/${projectId}/page-editor`);
  await page.getByRole('button', { name: 'Figma로 내보내기' }).click();

  await expect.poll(() => figmaExportRequested).toBe(true);
  await expect(page.getByText('Figma 연동은 비활성 상태이며 디자인 payload만 생성되었습니다.')).toBeVisible();
});
