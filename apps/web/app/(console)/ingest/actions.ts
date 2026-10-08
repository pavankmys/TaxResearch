"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  buildUploadFields,
  buildUrlSubmission,
  checkUploadSize,
  messageFromDetail,
} from "@/components/ingest/payload";
import type { IngestState } from "@/components/ingest/types";
import { apiBaseUrl, apiClient, getSessionToken } from "@/lib/server/api";

/** The form fields as strings. Files are read separately. */
function textFields(formData: FormData): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const [name, value] of formData.entries()) {
    if (typeof value === "string") {
      fields[name] = value;
    }
  }
  return fields;
}

/**
 * Submit a URL. On success the job page opens; the redirect ends this action, so it stays
 * outside any try block.
 */
export async function submitUrl(_previous: IngestState, formData: FormData): Promise<IngestState> {
  const built = buildUrlSubmission(textFields(formData));
  if (!built.ok) {
    return { error: built.error };
  }

  const client = await apiClient();
  const { data, error, response } = await client.POST("/v1/platform/ingestion/url", {
    body: built.body,
  });
  if (!data) {
    return { error: messageFromDetail(error?.detail, `The URL was not accepted (HTTP ${response.status}).`) };
  }
  redirect(`/ingest/jobs/${data.ingestion_job_id}`);
}

/**
 * Upload a file. The file is forwarded to the API as multipart form data with the session's
 * bearer token. Next limits Server Action bodies to 1 MB unless next.config raises the limit.
 */
export async function submitFile(_previous: IngestState, formData: FormData): Promise<IngestState> {
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { error: "Choose a PDF or HTML file." };
  }
  const sizeError = checkUploadSize(file.size);
  if (sizeError) {
    return { error: sizeError };
  }
  const built = buildUploadFields(textFields(formData));
  if (!built.ok) {
    return { error: built.error };
  }

  const token = await getSessionToken();
  if (!token) {
    return { error: "Your session has ended. Sign in again." };
  }

  const body = new FormData();
  body.set("file", file, file.name);
  for (const [name, value] of Object.entries(built.body)) {
    body.set(name, value);
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}/v1/platform/ingestion/manual`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body,
      cache: "no-store",
    });
  } catch {
    return { error: "The API is unavailable. Try again." };
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : undefined;
    return { error: messageFromDetail(detail, `The file was not accepted (HTTP ${response.status}).`) };
  }
  const jobId =
    payload && typeof payload === "object" && "ingestion_job_id" in payload
      ? String(payload.ingestion_job_id)
      : "";
  if (!jobId) {
    return { error: "The upload finished without a job. Try again." };
  }
  redirect(`/ingest/jobs/${jobId}`);
}

/** Enable or disable a source. The API refuses this for anyone but a platform admin. */
export async function setSourceEnabled(_previous: IngestState, formData: FormData): Promise<IngestState> {
  const code = String(formData.get("code") ?? "");
  const enabled = formData.get("enabled") === "true";
  if (!/^[a-z0-9_]{1,100}$/.test(code)) {
    return { error: "The source code is not valid." };
  }

  const client = await apiClient();
  const { response, error } = await client.PATCH("/v1/platform/sources/{code}", {
    params: { path: { code } },
    body: { enabled },
  });
  if (!response.ok) {
    return { error: messageFromDetail(error?.detail, `The source was not changed (HTTP ${response.status}).`) };
  }
  revalidatePath("/ingest");
  return { error: null };
}
