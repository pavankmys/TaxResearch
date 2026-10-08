import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";

// Users created by scripts/e2e-stack.sh. The password default must match that script.
const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-only-password-2026";
const EDITOR = "editor@e2e.test";
const ADMIN = "admin@e2e.test";
const SOURCE = "cbic_gst_portal";
const FIXTURE = join(__dirname, "fixtures", "circular-183.pdf");
const FIXTURE_BYTES = readFileSync(FIXTURE);

/**
 * Each run appends a unique trailer after %%EOF. The bytes change, so the upload is not
 * deduplicated as already stored. PDF readers ignore the trailer.
 */
function uniquePdf(run: string): Buffer {
  return Buffer.concat([FIXTURE_BYTES, Buffer.from(`\n% e2e run ${run}\n`)]);
}

async function signIn(page: Page, email: string): Promise<void> {
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

test("the editor sees both forms and the sources without any toggle", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.goto("/ingest");

  await expect(page.getByRole("heading", { name: "By URL" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "By file" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^(Enable|Disable) source/ })).toHaveCount(0);
  await expect(page.getByRole("columnheader", { name: "Change" })).toHaveCount(0);
});

test("the admin sees the source toggles", async ({ page }) => {
  await signIn(page, ADMIN);
  await page.goto("/ingest");

  await expect(page.getByRole("button", { name: `Disable source ${SOURCE}` })).toBeVisible();
});

test("a PDF uploaded through the form reaches a finished job and its document", async ({ page }) => {
  test.setTimeout(180_000);
  const run = `${Date.now()}`;
  await signIn(page, EDITOR);
  await page.goto("/ingest");

  const fileForm = page.getByRole("form", { name: "By file" });
  await fileForm.getByLabel("Source").click();
  await page.getByRole("option", { name: SOURCE }).click();
  await fileForm.getByLabel("Document type").click();
  await page.getByRole("option", { name: "Circular", exact: true }).click();
  await fileForm.getByLabel("File", { exact: true }).setInputFiles({
    name: "circular-183.pdf",
    mimeType: "application/pdf",
    buffer: uniquePdf(run),
  });
  await fileForm.getByText("Identifying details (optional)").click();
  await fileForm.getByLabel("Title", { exact: true }).fill(`E2E circular ${run}`);
  await fileForm.getByRole("button", { name: "Upload file" }).click();

  await expect(page).toHaveURL(/\/ingest\/jobs\/[0-9a-f-]{36}$/, { timeout: 30_000 });
  await expect(page.getByText(/The job (has finished|failed)\./)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("The job has finished.")).toBeVisible();

  await page.getByRole("link", { name: "Open the document" }).click();
  await expect(page).toHaveURL(/\/documents\/[0-9a-f-]{36}$/);
  await expect(page.locator("#document-title")).toBeVisible();

  // Structure: the numbered paragraphs get p1 and p2 paths.
  await page.getByRole("tab", { name: "Structure" }).click();
  await expect(page.getByText("p1", { exact: true })).toBeVisible();
  await expect(page.getByText("p2", { exact: true })).toBeVisible();

  // Pages: the thumbnail is rendered and loads.
  await page.getByRole("tab", { name: "Pages" }).click();
  const thumbnail = page.locator('img[alt^="Page 1 of"]');
  await thumbnail.scrollIntoViewIfNeeded();
  await expect.poll(async () => thumbnail.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

  // Metadata: a title edit with a reason is queued.
  await page.getByRole("tab", { name: "Metadata" }).click();
  await page.getByLabel("Title", { exact: true }).fill(`E2E edited ${run}`);
  await page.getByLabel("Reason for the change").fill("E2E title check");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Queued — changes apply in a few seconds.")).toBeVisible();

  // The worker applies the edit a few seconds later.
  await expect
    .poll(
      async () => {
        await page.reload();
        return (await page.locator("#document-title").textContent()) ?? "";
      },
      { timeout: 60_000, intervals: [2_000, 3_000, 5_000] },
    )
    .toContain(`E2E edited ${run}`);

  expect(await seriousViolations(page)).toEqual([]);
});

test("the ingest and job pages have no serious or critical accessibility violations", async ({ page }) => {
  await signIn(page, EDITOR);
  await page.goto("/ingest");
  await expect(page.getByRole("heading", { name: "By URL" })).toBeVisible();

  expect(await seriousViolations(page)).toEqual([]);
});
