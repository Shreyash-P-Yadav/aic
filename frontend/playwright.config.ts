import { defineConfig, devices } from '@playwright/test';

/**
 * E2E against the built app, served by Vite preview and proxied to a live backend.
 *
 * `webServer` starts both, so `npm run e2e` is one command and the CI path and the
 * developer path are the same path. Screenshots are captured at two widths in both
 * themes, which is what the gate asks for and also the only way to find the label
 * collisions that only appear at 768px.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'off',
    screenshot: 'off',
  },
  projects: [
    {
      name: 'desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        // The environment ships a Chromium whose build number differs from the one
        // this Playwright version pins, so point at it rather than downloading a
        // second copy. `PLAYWRIGHT_BROWSERS_PATH` alone is not enough when the
        // revisions disagree.
        launchOptions: { executablePath: process.env.CHROMIUM_PATH ?? '/opt/pw-browsers/chromium' },
      },
    },
  ],
  webServer: {
    command: 'npm run preview -- --port 4173 --strictPort',
    port: 4173,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
