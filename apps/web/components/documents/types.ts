import type { components } from "@/lib/api-client/schema";

export type DocumentDetail = components["schemas"]["DocumentDetail"];
export type VersionOut = components["schemas"]["VersionOut"];
export type PageOut = components["schemas"]["PageOut"];
export type BlockOut = components["schemas"]["BlockOut"];
export type BlockPage = components["schemas"]["BlockPage"];

/** Result of a Server Action that loads more blocks. Errors are returned, never thrown to the page. */
export type BlocksResult = { ok: true; page: BlockPage } | { ok: false; error: string };

/** Result of a Server Action that changes a document. */
export interface DocumentActionState {
  outcome: "idle" | "queued" | "changed" | "error";
  message: string | null;
}
