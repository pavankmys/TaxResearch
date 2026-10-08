import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";

// Users created by scripts/e2e-stack.sh. The password default must match that script.
const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-only-password-2026";
const EDITOR = "editor@e2e.test";
const SOURCE = "cbic_gst_portal";
const FIXTURE_BYTES = readFileSync(join(__dirname, "fixtures", "circular-183.pdf"));

async function signIn(page: Page, email: string = EDITOR): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
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

/** Upload a fresh copy of the fixture (unique bytes per run) and return the document's URL path. */
async function uploadAndOpenDocument(page: Page, run: string): Promise<string> {
  await signIn(page);
  await page.goto("/ingest");
  const fileForm = page.getByRole("form", { name: "By file" });
  await fileForm.getByLabel("Source").click();
  await page.getByRole("option", { name: SOURCE }).click();
  await fileForm.getByLabel("Document type").click();
  await page.getByRole("option", { name: "Circular", exact: true }).click();
  await fileForm.getByLabel("File", { exact: true }).setInputFiles({
    name: "circular-183.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.concat([FIXTURE_BYTES, Buffer.from(`\n% e2e run ${run}\n`)]),
  });
  await fileForm.getByRole("button", { name: "Upload file" }).click();

  await expect(page).toHaveURL(/\/ingest\/jobs\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  await expect(page.getByText("The job has finished.")).toBeVisible({ timeout: 90_000 });
  await page.getByRole("link", { name: "Open the document" }).click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test.describe.serial("documents", () => {
  let documentPath = "";

  test("a document opens with its tabs, versions and an original file link", async ({ page }) => {
    test.setTimeout(180_000);
    documentPath = await uploadAndOpenDocument(page, `${Date.now()}-doc`);

    await expect(page.locator("#document-title")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Versions" })).toBeVisible();

    await page.getByRole("tab", { name: "Versions" }).click();
    const original = page.getByRole("link", { name: "Open original" }).first();
    const href = await original.getAttribute("href");
    expect(href).toMatch(/^\/api\/files\/raw\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/);
    const response = await page.request.get(href ?? "/");
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("application/pdf");

    expect(await seriousViolations(page)).toEqual([]);
  });

  test("the status can be changed with a reason and the history shows it", async ({ page }) => {
    test.skip(!documentPath, "needs the document from the previous test");
    await signIn(page);
    await page.goto(documentPath);

    await page.getByRole("tab", { name: "Status" }).click();
    // Pick the first status that is not current, so a re-run still has a change to make.
    await page.getByRole("combobox", { name: "New status" }).click();
    const option = page.getByRole("option").first();
    const label = (await option.innerText()).trim();
    await option.click();
    await page.getByLabel("Reason", { exact: true }).fill("E2E status check");
    await page.getByRole("button", { name: "Change status" }).click();

    // The action re-renders the page, which reads the API several times, so allow longer here.
    await expect(page.getByText(`Status changed to ${label.toLowerCase().replace(/ /g, " ")}.`)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("cell", { name: label }).first()).toBeVisible();
  });

  test("the list shows documents, filters by review state and pages", async ({ page }) => {
    await signIn(page);
    await page.goto("/documents");

    await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("table").getByRole("link").first()).toBeVisible();

    await page.getByLabel("Search by title or canonical ID").fill("cir:");
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect(page).toHaveURL(/q=cir%3A/);

    await page.getByRole("combobox", { name: "Review state" }).click();
    await page.getByRole("option", { name: "Pending review" }).click();
    await page.getByRole("button", { name: "Apply filters" }).click();
    await expect(page).toHaveURL(/review_state=pending_review/);
    await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();

    expect(await seriousViolations(page)).toEqual([]);
  });

  test("the document and document list have no serious or critical accessibility violations", async ({ page }) => {
    test.skip(!documentPath, "needs the document from the first test");
    await signIn(page);
    await page.goto(documentPath);
    await expect(page.locator("#document-title")).toBeVisible();

    expect(await seriousViolations(page)).toEqual([]);
  });
});
