"use server";

import { revalidatePath } from "next/cache";

import { buildMetadataPatch, currentFieldValues, EDITABLE_FIELD_NAMES } from "@/components/documents/fields";
import { isUuid } from "@/components/documents/ids";
import { buildStatusPatch } from "@/components/documents/status";
import type { BlocksResult, DocumentActionState } from "@/components/documents/types";
import { messageFromDetail } from "@/components/ingest/payload";
import { apiClient } from "@/lib/server/api";

const BLOCK_PAGE_SIZE = 200;
const QUEUED_MESSAGE = "Queued — changes apply in a few seconds.";

function errorState(message: string): DocumentActionState {
  return { outcome: "error", message };
}

/**
 * Metadata edit. The API queues the change for the worker (202), so the page shows the queued
 * message and the new values appear after the worker has run.
 */
export async function editMetadata(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  const documentId = String(formData.get("document_id") ?? "");
  if (!isUuid(documentId)) {
    return errorState("The document ID is not valid.");
  }

  const client = await apiClient();
  const current = await client.GET("/v1/platform/documents/{document_id}", {
    params: { path: { document_id: documentId } },
  });
  if (!current.data) {
    return errorState(`The document could not be loaded (HTTP ${current.response.status}).`);
  }

  const submitted: Record<string, string> = {};
  for (const name of EDITABLE_FIELD_NAMES) {
    submitted[name] = String(formData.get(name) ?? "");
  }
  const built = buildMetadataPatch(
    currentFieldValues(current.data),
    submitted,
    String(formData.get("reason") ?? ""),
  );
  if (!built.ok) {
    return errorState(built.error);
  }

  const { response, error } = await client.PATCH("/v1/platform/documents/{document_id}", {
    params: { path: { document_id: documentId } },
    body: built.body,
  });
  if (!response.ok) {
    return errorState(messageFromDetail(error?.detail, `The change was not saved (HTTP ${response.status}).`));
  }

  revalidatePath(`/documents/${documentId}`);
  return { outcome: "queued", message: QUEUED_MESSAGE };
}

/** Status change. The API writes the status and its history row at once. */
export async function changeStatus(
  _previous: DocumentActionState,
  formData: FormData,
): Promise<DocumentActionState> {
  const documentId = String(formData.get("document_id") ?? "");
  if (!isUuid(documentId)) {
    return errorState("The document ID is not valid.");
  }

  const client = await apiClient();
  const current = await client.GET("/v1/platform/documents/{document_id}", {
    params: { path: { document_id: documentId } },
  });
  if (!current.data) {
    return errorState(`The document could not be loaded (HTTP ${current.response.status}).`);
  }

  const built = buildStatusPatch(
    {
      status: String(formData.get("status") ?? ""),
      validFrom: String(formData.get("status_valid_from") ?? ""),
      reason: String(formData.get("reason") ?? ""),
    },
    current.data.status,
  );
  if (!built.ok) {
    return errorState(built.error);
  }

  const { response, error } = await client.PATCH("/v1/platform/documents/{document_id}", {
    params: { path: { document_id: documentId } },
    body: built.body,
  });
  if (!response.ok) {
    return errorState(messageFromDetail(error?.detail, `The status was not changed (HTTP ${response.status}).`));
  }

  revalidatePath(`/documents/${documentId}`);
  return { outcome: "changed", message: `Status changed to ${built.body.status.replace(/_/g, " ")}.` };
}

/** Next page of blocks for the structure outline. The page filter is applied by the API. */
export async function loadBlocks(input: {
  documentId: string;
  versionId: string;
  page: number | null;
  after: number | null;
}): Promise<BlocksResult> {
  if (!isUuid(input.documentId) || !isUuid(input.versionId)) {
    return { ok: false, error: "The version is not valid." };
  }
  if (input.page !== null && (!Number.isInteger(input.page) || input.page < 1)) {
    return { ok: false, error: "The page is not valid." };
  }
  if (input.after !== null && (!Number.isInteger(input.after) || input.after < 0)) {
    return { ok: false, error: "The position is not valid." };
  }

  const client = await apiClient();
  const { data, response } = await client.GET(
    "/v1/platform/documents/{document_id}/versions/{version_id}/blocks",
    {
      params: {
        path: { document_id: input.documentId, version_id: input.versionId },
        query: {
          page: input.page ?? undefined,
          after: input.after ?? undefined,
          limit: BLOCK_PAGE_SIZE,
        },
      },
    },
  );
  if (!data) {
    return { ok: false, error: `The blocks could not be loaded (HTTP ${response.status}).` };
  }
  return { ok: true, page: data };
}
