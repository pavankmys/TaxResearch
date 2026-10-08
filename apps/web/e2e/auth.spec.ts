import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

// Users created by scripts/e2e-stack.sh. The password default must match that script.
const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-only-password-2026";
const EDITOR = "editor@e2e.test";
const PROFESSIONAL = "pro@e2e.test";

async function signIn(page: Page, email: string, password: string = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.help}`);
}

test("an unauthenticated visit to /queue goes to the login page", async ({ page }) => {
  await page.goto("/queue");

  await expect(page).toHaveURL(/\/login\?next=%2Fqueue$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("a bad password shows the error and stays on the login page", async ({ page }) => {
  await signIn(page, EDITOR, "not-the-right-password");

  // Next.js adds its own role="alert" announcer, so match on the message.
  await expect(page.getByRole("alert").filter({ hasText: "Invalid email or password" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("a good login lands on /queue with the console navigation", async ({ page }) => {
  await signIn(page, EDITOR);

  await expect(page).toHaveURL(/\/queue$/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Queue" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Documents" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Ingest" })).toBeVisible();
});

test("the login page has no serious or critical accessibility violations", async ({ page }) => {
  await page.goto("/login");

  expect(await seriousViolations(page)).toEqual([]);
});

test("the queue page has no serious or critical accessibility violations", async ({ page }) => {
  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);

  expect(await seriousViolations(page)).toEqual([]);
});

test("logout returns to the login page and the session is gone", async ({ page }) => {
  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/queue");
  await expect(page).toHaveURL(/\/login\?next=%2Fqueue$/);
});

test("a professional user sees the no-access page", async ({ page }) => {
  await signIn(page, PROFESSIONAL);

  await expect(page.getByRole("heading", { name: "No access" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
});

test("the session cookie is httpOnly and SameSite=Strict, and the token is not in the page", async ({
  page,
}) => {
  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);

  const cookies = await page.context().cookies();
  const session = cookies.find((cookie) => cookie.name === "tr_session");
  expect(session).toBeDefined();
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Strict");
  expect(session?.path).toBe("/");

  const html = await page.content();
  expect(html).not.toContain(session?.value ?? "no-cookie");
});

test("the file proxy rejects malformed ids and passes API errors through", async ({ page }) => {
  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);

  const badId = await page.request.get("/api/files/pages/not-a-uuid/also-bad/1.png");
  expect(badId.status()).toBe(400);

  const badPage = await page.request.get(
    "/api/files/pages/00000000-0000-4000-8000-000000000001/00000000-0000-4000-8000-000000000002/0",
  );
  expect(badPage.status()).toBe(400);

  const missing = await page.request.get(
    "/api/files/raw/00000000-0000-4000-8000-000000000001/00000000-0000-4000-8000-000000000002",
  );
  expect(missing.status()).toBe(404);
});
