import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:8770', viewport: { width: 1280, height: 960 }, trace: 'retain-on-failure' },
  webServer: {
    command: 'python ../tools/preview_ui.py --demo --port 8770 --no-browser',
    url: 'http://127.0.0.1:8770/?demo=1',
    reuseExistingServer: false,
    timeout: 30000
  }
});
