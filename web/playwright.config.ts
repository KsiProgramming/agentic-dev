import { defineConfig, devices } from "@playwright/test";

// Point at any running web app: `pnpm dev` (default) or docker compose.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

/** The widths the layout is designed and tested at (tech-stack.md → UI design system). */
const VIEWPORTS = {
  "mobile-375": { width: 375, height: 812 },
  "tablet-768": { width: 768, height: 1024 },
  "laptop-1024": { width: 1024, height: 768 },
  "desktop-1440": { width: 1440, height: 900 },
};

// Layout checks run at every width; a11y at the narrowest and widest. Functional specs run once.
// The journey changes the workspace's connections, so it runs alone, after every other project.
const LAYOUT = /layout\.spec\.ts/;
const A11Y = /a11y\.spec\.ts/;
const JOURNEY = /journey\.spec\.ts/;

export default defineConfig({
  testDir: "./e2e",
  // Connects the workspace to Claude and the fake GitHub App (the stack's e2e fakes).
  globalSetup: "./e2e/global-setup.ts",
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: [LAYOUT, A11Y, JOURNEY],
    },
    ...Object.entries(VIEWPORTS).map(([name, viewport]) => ({
      name,
      use: { ...devices["Desktop Chrome"], viewport },
      testMatch: name === "mobile-375" || name === "desktop-1440" ? [LAYOUT, A11Y] : [LAYOUT],
    })),
    {
      name: "journey",
      use: { ...devices["Desktop Chrome"] },
      testMatch: JOURNEY,
      dependencies: ["chromium", ...Object.keys(VIEWPORTS)],
    },
  ],
});
