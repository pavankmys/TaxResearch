"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { apiClient } from "@/lib/server/api";
import { isUuid } from "@/lib/server/file-proxy";

export type ActionResult = { ok: true; message: string } | { ok: false; error: string };

export type DecisionAction = "approve" | "edit_approve" | "reject" | "needs_info";

export interface DecisionInput {
  action: DecisionAction;
  note?: string;
  fields?: Record<string, unknown>;
}

const DECISION_ACTIONS: ReadonlySet<string> = new Set([
  "approve",
  "edit_approve",
  "reject",
  "needs_info",
]);
const UNAVAILABLE = "The API is unavailable. Try again.";
const UNKNOWN_TASK = "This task could not be found.";

/** A readable message for an API error body: a string detail, or validation messages. */
function describeError(error: unknown, status: number): string {
  if (status === 401) {
    return "Your session has expired. Sign in again.";
  }
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string" && detail.length > 0) {
    return capitalize(detail);
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: unknown) => {
        const msg = (item as { msg?: unknown } | null)?.msg;
        return typeof msg === "string" ? msg.replace(/^Value error, /, "") : null;
      })
      .filter((msg): msg is string => msg !== null && msg.length > 0);
    if (messages.length > 0) {
      return capitalize(messages.join("; "));
    }
  }
  return `The request failed (HTTP ${status}).`;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Assign the task to the signed-in reviewer ("me") or unassign it (null). */
export async function assignTask(taskId: string, assignee: "me" | null): Promise<ActionResult> {
  if (!isUuid(taskId)) {
    return { ok: false, error: UNKNOWN_TASK };
  }
  try {
    const client = await apiClient();
    const { data, error, response } = await client.POST(
      "/v1/platform/review-tasks/{task_id}/assign",
      { params: { path: { task_id: taskId } }, body: { assignee_id: assignee } },
    );
    if (!data) {
      return { ok: false, error: describeError(error, response.status) };
    }
  } catch {
    return { ok: false, error: UNAVAILABLE };
  }
  revalidatePath("/queue");
  revalidatePath(`/queue/${taskId}`);
  return { ok: true, message: assignee === "me" ? "Assigned to you." : "Unassigned." };
}

/**
 * Record a decision. On success the browser goes to /queue?done=<id>, which shows the success
 * message and a link to the next task. On failure the result carries the API's message.
 */
export async function decideTask(
  taskId: string,
  input: DecisionInput,
): Promise<ActionResult | undefined> {
  if (!isUuid(taskId)) {
    return { ok: false, error: UNKNOWN_TASK };
  }
  if (!DECISION_ACTIONS.has(input.action)) {
    return { ok: false, error: "Unknown action." };
  }
  if (input.action === "edit_approve" && (!input.fields || Object.keys(input.fields).length === 0)) {
    return { ok: false, error: "Change at least one field, or approve without editing." };
  }

  const note = input.note?.trim() ? input.note.trim() : undefined;
  const body =
    input.action === "edit_approve"
      ? { action: input.action, note, fields: input.fields }
      : { action: input.action, note };

  try {
    const client = await apiClient();
    const { data, error, response } = await client.POST(
      "/v1/platform/review-tasks/{task_id}/decision",
      { params: { path: { task_id: taskId } }, body },
    );
    if (!data) {
      return { ok: false, error: describeError(error, response.status) };
    }
  } catch {
    return { ok: false, error: UNAVAILABLE };
  }

  revalidatePath("/queue");
  revalidatePath(`/queue/${taskId}`);
  // redirect() throws to end the request, so it stays outside the try block above.
  redirect(`/queue?done=${taskId}`);
}
