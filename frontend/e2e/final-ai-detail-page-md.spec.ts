import { expect, test } from '@playwright/test';

const projectId = 'sprint47-e2e-project';

test.beforeEach(async ({ page }) => {
  // 1. 프로젝트 상세 정보 모킹
  await page.route(`**/api/v1/projects/${projectId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'ws-1',
        brand_id: 'b-1',
        name: 'Sprint 47 Air Cooler',
        category: 'Living',
        status: 'intake_received',
        current_step: 'raw_input'
      })
    });
  });

  // 2. 세일즈 패키지 데이터셋 모킹
  await page.route(`**/api/v1/projects/${projectId}/sales-package`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        long_png: { file_path: '/uploads/exports/long.png', url: '/uploads/exports/long.png' },
        editable_web_page: { url: `/workspace/projects/${projectId}/page-editor` },
        figma_payload: { payload: {}, asset_map: {} },
        marketplace_package: {
          title: '[핫딜] Sprint 47 Air Cooler',
          tags: ['에어컨', '여름'],
          category: 'Living',
          representative_image: '/uploads/cool_fan.png',
          detail_page_artifact: '/uploads/exports/long.png',
          price: 59000,
          delivery: '무료배송',
          returns: '7일 이내 반품 가능',
          seo_metadata: {
            title: '무풍 스마트 에어쿨러',
            description: '초절전 냉방 선풍기',
            keywords: '선풍기,에어쿨러'
          }
        },
        marketplace_readiness: {
          ready: true,
          errors: []
        },
        copy_sheet: [
          { id: 'sec-1', section_type: 'hero', title: '역대급 시원함의 시작', body_copy: '에어쿨러 10초 급속 냉각 바람' }
        ],
        visual_assets: [
          { id: 'asset-1', filename: 'cool_fan.png', file_path: 'uploads/cool_fan.png', mime_type: 'image/png', source_type: 'sourced' }
        ]
      })
    });
  });

  // 3. 에디터 디테일 패키지 조회 모킹
  await page.route(`**/api/v1/projects/${projectId}/detail-page-package`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        sales_strategy: {
          target_customer: '더위를 타는 1인 가구',
          buyer_problem: '일반 선풍기는 시원하지 않고 에어컨은 전기세가 무서움',
          main_selling_point: '에어컨 20% 전력으로 영하 5도 급속 바람 구현',
          supporting_points: [],
          tone: 'modern'
        },
        copy_sections: [
          { id: 'sec-1', section_type: 'hero', title: '역대급 시원함의 시작', body_copy: '에어쿨러 10초 급속 냉각 바람', associated_fact_ids: [], image_asset_id: null, sort_order: 0, is_visible: true }
        ],
        visual_plan: { selected_style: 'problem_solution', selected_background: 'cooling-blue', jobs_count: 1 },
        page_sections: [
          { key: 'hero', layout: 'hero', eyebrow: '여름 쿨러', headline: '역대급 시원함의 시작', subcopy: '에어쿨러 10초 급속 냉각 바람', visual_slot: { kind: 'product_image', role: 'hero', filename: 'cool_fan.png', fallback_label: 'image needed' } }
        ],
        marketplace_copy: { title: '[핫딜] 에어쿨러', description: '초절전 냉방 선풍기', bullet_points: ['역대급 시원함의 시작'] },
        export_targets: ['figma', 'png', 'html']
      })
    });
  });
});

test('Orchestration E2E Flow: cost approval, review, and final preview verification', async ({ page }) => {
  // 1. 페이지 접속 (E2E 검증용 mock 페이지 구축 없이, page-editor 화면 내 탭의 연동 상태를 타깃)
  // page-editor에 패키지 탭이 활성화되어 있을 때 progress-panel과 export-panel이 다 보입니다.
  await page.goto(`/workspace/projects/${projectId}/page-editor`);

  // 2. 패키지 탭 진입
  const packageTab = page.getByRole('button', { name: 'AI 패키지 편집기' });
  await expect(packageTab).toBeVisible();
  await packageTab.click();

  // 3. E2E: 비용 승인 대기 상태 렌더링 확인 (Mock API 상 status = 'image_cost_approval_required'로 가정)
  await page.route(`**/api/v1/projects/${projectId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'ws-1',
        brand_id: 'b-1',
        name: 'Sprint 47 Air Cooler',
        category: 'Living',
        status: 'image_cost_approval_required',
        current_step: 'image_planning'
      })
    });
  });
  
  // 강제 리로드하여 새 상태 렌더링 시킴
  await page.reload();
  const packageTabAfter = page.getByRole('button', { name: 'AI 패키지 편집기' });
  await packageTabAfter.click();

  // "이미지 생성 승인 대기" 텍스트와 승인 버튼 검증
  const progressDesc = page.locator('text=이미지 생성 승인 대기');
  await expect(progressDesc).toBeVisible();

  // 4. 비용 승인 진행 모킹 및 클릭
  await page.route(`**/api/v1/projects/${projectId}/images/approve-cost`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', message: '비용 승인 완료' })
    });
  });

  // 상태를 'images_ready_for_review'로 변경 모킹
  await page.route(`**/api/v1/projects/${projectId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'ws-1',
        brand_id: 'b-1',
        name: 'Sprint 47 Air Cooler',
        category: 'Living',
        status: 'images_ready_for_review',
        current_step: 'images_generating'
      })
    });
  });

  const approveButton = page.getByRole('button', { name: '비용 승인 및 AI 이미지 생성 시작' });
  await expect(approveButton).toBeVisible();
  await approveButton.click();

  // 5. 생성 완료 및 검수 팝업(반려/재생성/최종 완성) 확인
  const reviewText = page.locator('text=생성 이미지 확인 필요');
  await expect(reviewText).toBeVisible();

  const skipButton = page.getByRole('button', { name: '⏭️ 검토 통과 및 최종 완성' });
  await expect(skipButton).toBeVisible();
  await expect(page.getByRole('button', { name: 'reject and revise' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'continue with original photo' })).toBeVisible();

  // 6. E2E: 최종 세일즈 패키지 완성 상태로 전환 모킹
  await page.route(`**/api/v1/projects/${projectId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: projectId,
        workspace_id: 'ws-1',
        brand_id: 'b-1',
        name: 'Sprint 47 Air Cooler',
        category: 'Living',
        status: 'package_ready',
        current_step: 'package_ready'
      })
    });
  });
  await skipButton.click();

  // 7. Visual Copy Assertions: 프리뷰가 렌더링되고 비어있지 않음 확인
  const visualPreviewTitle = page.locator('text=역대급 시원함의 시작').first();
  await expect(visualPreviewTitle).toBeVisible();

  // 8. 수출 및 아웃풋 패키지 버튼 검증
  const pngBtn = page.getByRole('button', { name: 'PNG 저장' });
  const figmaBtn = page.getByRole('button', { name: 'Figma로 편집' });
  await expect(pngBtn).toBeVisible();
  await expect(figmaBtn).toBeVisible();
});
