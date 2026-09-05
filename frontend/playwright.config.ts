import { defineConfig, devices } from '@playwright/test';

const port = process.env.SELLFORM_E2E_PORT ?? '3100';
const baseURL = `http://127.0.0.1:${port}`;
// Real-backend suites deliberately exercise the already-running application,
// API, database and LangGraph worker together. Starting a second Next dev
// server for those suites makes both processes write to the same `.next`
// directory, which can temporarily remove dynamic route artifacts and turn a
// valid planning URL into a 404 after refresh.
const manageWebServer = process.env.SELLFORM_E2E_EXTERNAL_SERVER !== '1'
  && process.env.SELLFORM_E2E_REAL_BACKEND !== '1';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  webServer: manageWebServer ? {
    command: `npm.cmd run dev -- --hostname 127.0.0.1 --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  } : undefined,
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
