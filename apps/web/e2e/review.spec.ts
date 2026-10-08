import AxeBuilder from "@axe-core/playwright";
import { type APIRequestContext, expect, type Locator, type Page, test } from "@playwright/test";

// The stack (scripts/e2e-stack.sh) runs the API on 8000 and the web app on 3000.
const API = "http://localhost:8000";
// Users created by scripts/e2e-stack.sh. The password default must match that script.
const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-only-password-2026";
const ADMIN = "admin@e2e.test";
const EDITOR = "editor@e2e.test";

interface Ingested {
  token: string;
  documentId: string;
  taskId: string;
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.help}`);
}

async function apiLogin(request: APIRequestContext, email: string): Promise<string> {
  const response = await request.post(`${API}/v1/auth/login`, {
    data: { email, password: PASSWORD },
  });
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as { access_token: string };
  return body.access_token;
}

/**
 * A one-page PDF with the given lines of text (Helvetica, 12 pt, Letter size). Written by hand so
 * the test needs no PDF library. The cross-reference table is computed, so readers accept it.
 */
function makePdf(lines: string[]): Buffer {
  const escape = (text: string) => text.replace(/[\\()]/g, (char) => `\\${char}`);
  const drawing = lines
    .map((line, index) =>
      index === 0 ? `(${escape(line)}) Tj` : `0 -18 Td (${escape(line)}) Tj`,
    )
    .join("\n");
  const content = `BT\n/F1 12 Tf\n72 720 Td\n${drawing}\nET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(content, "latin1")} >>\nstream\n${content}\nendstream`,
  ];
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body, "latin1"));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(body, "latin1");
  const entries = offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`);
  body +=
    `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${entries.join("")}` +
    `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

interface ManualUpload {
  name: string;
  buffer: Buffer;
  title: string;
  docType: string;
}

/** Upload a file through the manual ingestion endpoint. Returns the job id. */
async function uploadManual(request: APIRequestContext, upload: ManualUpload): Promise<string> {
  const admin = await apiLogin(request, ADMIN);
  const response = await request.post(`${API}/v1/platform/ingestion/manual`, {
    headers: { Authorization: `Bearer ${admin}` },
    multipart: {
      file: { name: upload.name, mimeType: "application/pdf", buffer: upload.buffer },
      source: "cbic_gst_portal",
      doc_type: upload.docType,
      title: upload.title,
    },
  });
  expect(response.status()).toBe(202);
  const body = (await response.json()) as { ingestion_job_id: string };
  return body.ingestion_job_id;
}

/** Wait until the job has created its document (success or failure), then return the document id. */
async function waitForDocument(request: APIRequestContext, jobId: string): Promise<string> {
  const admin = await apiLogin(request, ADMIN);
  const headers = { Authorization: `Bearer ${admin}` };
  let documentId = "";
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/v1/platform/ingestion/jobs/${jobId}`, {
          headers,
        });
        const job = (await response.json()) as { document_id: string | null };
        documentId = job.document_id ?? "";
        return documentId;
      },
      { timeout: 60_000, message: "the ingestion job never produced a document" },
    )
    .not.toBe("");
  return documentId;
}

/** Wait until the document has an open review task of the given kind. Returns its id. */
async function waitForTask(
  request: APIRequestContext,
  documentId: string,
  kind: string,
): Promise<string> {
  const admin = await apiLogin(request, ADMIN);
  const headers = { Authorization: `Bearer ${admin}` };
  let taskId = "";
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API}/v1/platform/documents/${documentId}`, {
          headers,
        });
        const document = (await response.json()) as { open_review_task_ids: string[] };
        for (const candidate of document.open_review_task_ids) {
          const taskResponse = await request.get(`${API}/v1/platform/review-tasks/${candidate}`, {
            headers,
          });
          const task = (await taskResponse.json()) as { kind: string };
          if (task.kind === kind) {
            taskId = candidate;
          }
        }
        return taskId;
      },
      { timeout: 60_000, message: `no ${kind} review task was opened` },
    )
    .not.toBe("");
  return taskId;
}

/**
 * Upload a notification with no date, so the worker opens a metadata task for it. The notification
 * number is unique per run, so runs do not merge into one another.
 */
async function ingestNotification(request: APIRequestContext): Promise<Ingested> {
  const token = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
  const number = 10000 + Math.floor(Math.random() * 89999);
  const pdf = makePdf([
    "CENTRAL GOODS AND SERVICES TAX",
    `Notification No. ${number}/2026-Central Tax`,
    `Review test ${token}. This notification has no date.`,
    "Seeded by the Playwright review test.",
  ]);
  const jobId = await uploadManual(request, {
    name: `review-${token}.pdf`,
    buffer: pdf,
    title: `E2E review ${token}`,
    docType: "notification",
  });
  const documentId = await waitForDocument(request, jobId);
  const taskId = await waitForTask(request, documentId, "metadata");
  return { token, documentId, taskId };
}

/** Find a task's row in the open queue, following "Next page" links as needed. */
async function findQueueLink(page: Page, taskId: string, kind: string): Promise<Locator> {
  await page.goto(`/queue?tab=open&kind=${kind}`);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const link = page.locator(`a[href="/queue/${taskId}"]`);
    if ((await link.count()) > 0) {
      return link;
    }
    const next = page.getByRole("link", { name: "Next page" });
    if ((await next.count()) === 0) {
      break;
    }
    await Promise.all([page.waitForURL(/cursor=/), next.click()]);
  }
  throw new Error(`task ${taskId} is not in the open queue`);
}

function resultAlert(page: Page, text: string): Locator {
  return page.locator('[role="alert"]').filter({ hasText: text });
}

test("an editor corrects a metadata proposal and approves it", async ({ page, request }) => {
  const ingested = await ingestNotification(request);
  const newTitle = `Corrected title ${ingested.token}`;

  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);
  await (await findQueueLink(page, ingested.taskId, "metadata")).click();
  await expect(page).toHaveURL(new RegExp(`/queue/${ingested.taskId}$`));

  // The source page image is shown at its natural size.
  const image = page.getByRole("img", { name: /^Page 1 of / });
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth))
    .toBeGreaterThan(0);

  // The round robin gave the task to the editor when it opened: unassign, then take it back.
  await page.getByRole("button", { name: "Unassign" }).click();
  await expect(resultAlert(page, "Unassigned.")).toBeVisible();
  await page.getByRole("button", { name: "Assign to me" }).click();
  await expect(resultAlert(page, "Assigned to you.")).toBeVisible();

  // Edit the title, then approve with the edit.
  await page.getByText("Edit fields").click();
  await page.getByLabel("Title", { exact: true }).fill(newTitle);
  await page.getByRole("button", { name: "Edit then approve" }).click();

  await expect(page).toHaveURL(new RegExp(`/queue\\?done=${ingested.taskId}$`));
  await expect(page.getByRole("status").filter({ hasText: "Decision recorded." })).toBeVisible();

  // The task is closed, and the decision holds only the field that changed.
  const token = await apiLogin(request, EDITOR);
  const headers = { Authorization: `Bearer ${token}` };
  const task = (await (
    await request.get(`${API}/v1/platform/review-tasks/${ingested.taskId}`, { headers })
  ).json()) as { status: string; resolution: { decision: { action: string; fields: unknown } } };
  expect(task.status).toBe("done");
  expect(task.resolution.decision.action).toBe("edit_approve");
  expect(task.resolution.decision.fields).toEqual({ title: newTitle });

  // The worker applies the edit to the document.
  await expect
    .poll(
      async () => {
        const response = await request.get(
          `${API}/v1/platform/documents/${ingested.documentId}`,
          { headers },
        );
        const document = (await response.json()) as { metadata: { fields?: { title?: string } } };
        return document.metadata.fields?.title;
      },
      { timeout: 60_000 },
    )
    .toBe(newTitle);

  expect(await seriousViolations(page)).toEqual([]);

  await page.goto(`/queue/${ingested.taskId}`);
  await expect(page.getByText("This task is closed.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  expect(await seriousViolations(page)).toEqual([]);
});

test("rejecting without a note shows the validation error and keeps the task open", async ({
  page,
  request,
}) => {
  const ingested = await ingestNotification(request);

  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);
  await (await findQueueLink(page, ingested.taskId, "metadata")).click();
  await expect(page).toHaveURL(new RegExp(`/queue/${ingested.taskId}$`));

  await page.getByRole("button", { name: "Reject" }).click();

  const alert = resultAlert(page, "at least 3 characters");
  await expect(alert).toBeVisible();
  await expect(alert).toBeFocused();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeEnabled();

  const token = await apiLogin(request, EDITOR);
  const task = (await (
    await request.get(`${API}/v1/platform/review-tasks/${ingested.taskId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  ).json()) as { status: string };
  expect(["open", "in_review"]).toContain(task.status);

  expect(await seriousViolations(page)).toEqual([]);
});

test("an unreadable PDF opens a parse failure task that gives the reason", async ({
  page,
  request,
}) => {
  const token = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
  const broken = Buffer.from(`%PDF-1.4\n% not a real page ${token}\n%%EOF\n`, "latin1");
  const jobId = await uploadManual(request, {
    name: `broken-${token}.pdf`,
    buffer: broken,
    title: `E2E broken ${token}`,
    docType: "notification",
  });
  const documentId = await waitForDocument(request, jobId);
  const taskId = await waitForTask(request, documentId, "parse_failure");

  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);
  await (await findQueueLink(page, taskId, "parse_failure")).click();
  await expect(page).toHaveURL(new RegExp(`/queue/${taskId}$`));

  await expect(page.getByRole("heading", { name: "What went wrong" })).toBeVisible();
  await expect(page.getByText("The PDF could not be read.")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});

test("a miss report shows the query, filters and as-on date", async ({ page, request }) => {
  const token = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
  const query = `Input tax credit reversal ${token}`;
  const reporter = await apiLogin(request, EDITOR);
  const created = await request.post(`${API}/v1/miss-reports`, {
    headers: { Authorization: `Bearer ${reporter}` },
    data: {
      query,
      filters: { act: "CGST", section: "16" },
      as_on: "2026-09-30",
      expected: "Rule 36(4) of the CGST Rules",
    },
  });
  expect(created.status()).toBe(201);
  const { id: taskId } = (await created.json()) as { id: string };

  await signIn(page, EDITOR);
  await expect(page).toHaveURL(/\/queue$/);
  await (await findQueueLink(page, taskId, "miss_report")).click();
  await expect(page).toHaveURL(new RegExp(`/queue/${taskId}$`));

  await expect(page.getByRole("heading", { name: "Search that missed" })).toBeVisible();
  await expect(page.locator("dd", { hasText: query })).toBeVisible();
  await expect(page.getByText("2026-09-30")).toBeVisible();
  await expect(page.getByText('"section": "16"')).toBeVisible();
  await expect(page.getByText("This task has no source page image.")).toBeVisible();
  expect(await seriousViolations(page)).toEqual([]);
});
