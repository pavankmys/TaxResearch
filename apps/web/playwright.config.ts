import { defineConfig, devices } from "@playwright/test";

// The stack is started separately (scripts/e2e-stack.sh). This config does not start it.
const chromiumPath = process.env.PW_CHROMIUM_PATH;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    launchOptions: chromiumPath ? { executablePath: chromiumPath } : {},
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
