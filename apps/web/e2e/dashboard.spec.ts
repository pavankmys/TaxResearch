import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Users created by scripts/e2e-stack.sh. The password default must match that script.
const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-only-password-2026";
const EDITOR = "editor@e2e.test";

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EDITOR);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // A good login lands on the queue. Wait for it so the next navigation is not raced.
  await expect(page).toHaveURL(/\/queue$/);
}

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.help}`);
}

test("the dashboard shows the metric tiles and the numbering gap placeholder", async ({ page }) => {
  await signIn(page);
  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "Ingestion dashboard" })).toBeVisible();
  await expect(page.getByText("Documents discovered", { exact: true })).toBeVisible();
  await expect(page.getByText("Freshness p50", { exact: true })).toBeVisible();
  await expect(page.getByText("Freshness p95", { exact: true })).toBeVisible();
  await expect(page.getByText("Flagged pages", { exact: true })).toBeVisible();
  await expect(page.getByText("Cross-check disagreements", { exact: true })).toBeVisible();
  await expect(page.getByText("Numbering gaps", { exact: true })).toBeVisible();
  await expect(page.getByText("Not measured until M7")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Source health" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Review queue" })).toBeVisible();
});

test("an alert banner, when shown, names the severity in text", async ({ page }) => {
  await signIn(page);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Ingestion dashboard" })).toBeVisible();

  const banner = page.getByRole("alert");
  if ((await banner.count()) > 0) {
    await expect(banner.getByText(/^(Critical|Warning)$/).first()).toBeVisible();
  }
});

test("the dashboard has no serious or critical accessibility violations", async ({ page }) => {
  await signIn(page);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Ingestion dashboard" })).toBeVisible();

  expect(await seriousViolations(page)).toEqual([]);
});
