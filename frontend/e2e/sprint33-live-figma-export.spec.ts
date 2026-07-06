import { expect, test } from '@playwright/test';

const projectId = 'figma-live-project';
const jobId = 'job-live-123';

test.beforeEach(async ({ page }) => {
  // Common router mocks for project context
  await page.route(`**/api/v1/projects/${projectId}**`, async route => {
    const request = route.request();
    const url = request.url();

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
              body_copy: '사실 기반 문구',
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

    // Default project detail
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
});

test('Figma Live canvas export - success flow', async ({ page }) => {
  let exportInitiated = false;
  let pollCount = 0;

  // Intercept live-export POST and GET polling APIs
  await page.route(`**/api/v1/projects/${projectId}/page/figma/**`, async route => {
    const request = route.request();
    const url = request.url();

    if (url.endsWith('/live-export') && request.method() === 'POST') {
      const body = JSON.parse(request.postData() || '{}');
      expect(body.target_file_url).toBe('https://www.figma.com/design/ABC123XYZ/Test');
      exportInitiated = true;
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: jobId,
          status: 'queued',
          message: 'Figma 내보내기 작업을 시작했습니다.'
        }),
      });
      return;
    }

    if (url.endsWith(`/exports/${jobId}`) && request.method() === 'GET') {
      pollCount++;
      // Transition states: queued -> rendering -> completed
      let status = 'queued';
      let result_node_url = null;
      if (pollCount === 2) {
        status = 'rendering';
      } else if (pollCount >= 3) {
        status = 'completed';
        result_node_url = 'https://www.figma.com/design/ABC123XYZ/Test?node-id=99-88';
      }

      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: jobId,
          status: status,
          result_file_url: 'https://www.figma.com/design/ABC123XYZ/Test',
          result_node_url: result_node_url,
          error_code: null,
          error_message: null
        }),
      });
      return;
    }

    await route.continue();
  });

  // 1. Go to page editor
  await page.goto(`/workspace/projects/${projectId}/page-editor`);
  
  // 2. Click figma export button
  const exportBtn = page.getByRole('button', { name: 'Figma로 내보내기' });
  await expect(exportBtn).toBeVisible();
  await exportBtn.click();

  // 3. Verify modal elements are visible
  await expect(page.getByText('Figma Live 내보내기')).toBeVisible();
  
  // 4. Reject invalid URLs without calling the live-export API.
  await page.locator('#figma-url-input').fill('http://example.com/not-a-figma-file');
  await page.locator('#figma-start-export-btn').click();
  await expect(page.getByText(/figma\.com\/design/)).toBeVisible();
  await expect(exportInitiated).toBe(false);

  // 5. Fill a valid URL and trigger export.
  await page.locator('#figma-url-input').fill('https://www.figma.com/design/ABC123XYZ/Test');
  await page.locator('#figma-start-export-btn').click();

  // 6. Verify queued transition state
  await expect(exportInitiated).toBe(true);
  await expect(page.locator('#status-queued')).toBeVisible();

  // 7. Verify completed state with figma view link
  await expect(page.locator('#status-completed')).toBeVisible({ timeout: 5000 });
  const viewLink = page.locator('#figma-view-link');
  await expect(viewLink).toBeVisible();
  await expect(viewLink).toHaveAttribute('href', 'https://www.figma.com/design/ABC123XYZ/Test?node-id=99-88');
});

test('Figma Live canvas export - authentication required and retry flow', async ({ page }) => {
  let authRequiredPolled = false;
  let retryRequested = false;
  let retryPollCount = 0;

  await page.route(`**/api/v1/projects/${projectId}/page/figma/**`, async route => {
    const request = route.request();
    const url = request.url();

    if (url.endsWith('/live-export') && request.method() === 'POST') {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: jobId,
          status: 'queued',
        }),
      });
      return;
    }

    if (url.endsWith(`/exports/${jobId}`) && request.method() === 'GET') {
      if (!retryRequested) {
        // Return AUTH_REQUIRED failure
        authRequiredPolled = true;
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({
            job_id: jobId,
            status: 'failed',
            error_code: 'AUTH_REQUIRED',
            error_message: 'Figma OAuth authorization required.',
            auth_url: 'https://www.figma.com/oauth?test=1'
          }),
        });
      } else {
        retryPollCount++;
        // Transition after retry
        const status = retryPollCount >= 2 ? 'completed' : 'rendering';
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({
            job_id: jobId,
            status: status,
            result_node_url: 'https://www.figma.com/design/ABC123XYZ/Test?node-id=11-22'
          }),
        });
      }
      return;
    }

    if (url.endsWith(`/exports/${jobId}/retry`) && request.method() === 'POST') {
      retryRequested = true;
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: jobId,
          status: 'queued'
        }),
      });
      return;
    }

    await route.continue();
  });

  await page.goto(`/workspace/projects/${projectId}/page-editor`);
  await page.getByRole('button', { name: 'Figma로 내보내기' }).click();

  await page.locator('#figma-url-input').fill('https://www.figma.com/design/ABC123XYZ/Test');
  await page.locator('#figma-start-export-btn').click();

  // 1. Check auth cards
  await expect(page.locator('#status-failed')).toBeVisible({ timeout: 5000 });
  await expect(authRequiredPolled).toBe(true);
  
  const authLink = page.locator('#figma-auth-link');
  await expect(authLink).toBeVisible();
  await expect(authLink).toHaveAttribute('href', 'https://www.figma.com/oauth?test=1');

  // 2. Click retry button
  const retryBtn = page.locator('#figma-retry-auth-btn');
  await expect(retryBtn).toBeVisible();
  await retryBtn.click();

  // 3. Confirm transition to completed
  await expect(retryRequested).toBe(true);
  await expect(page.locator('#status-completed')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('#figma-view-link')).toBeVisible();
});
