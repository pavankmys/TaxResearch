import { isIsoDate, MIN_REASON_LENGTH } from "@/components/documents/fields";

export const DOCUMENT_STATUSES = [
  "in_force",
  "amended",
  "superseded",
  "rescinded",
  "struck_down",
  "stayed",
] as const;

export type DocumentStatusValue = (typeof DOCUMENT_STATUSES)[number];

export const STATUS_LABELS: Record<DocumentStatusValue, string> = {
  in_force: "In force",
  amended: "Amended",
  superseded: "Superseded",
  rescinded: "Rescinded",
  struck_down: "Struck down",
  stayed: "Stayed",
};

export type StatusPatchResult =
  | { ok: true; body: { status: DocumentStatusValue; status_valid_from?: string; reason: string } }
  | { ok: false; error: string };

/** The PATCH body for a status change. The valid-from date is optional; the API defaults it to today. */
export function buildStatusPatch(
  input: { status: string; validFrom: string; reason: string },
  currentStatus: string,
): StatusPatchResult {
  if (!(DOCUMENT_STATUSES as readonly string[]).includes(input.status)) {
    return { ok: false, error: "Choose a status." };
  }
  if (input.status === currentStatus) {
    return { ok: false, error: "The document already has that status." };
  }
  const validFrom = input.validFrom.trim();
  if (validFrom !== "" && !isIsoDate(validFrom)) {
    return { ok: false, error: "The valid-from date must be a date in the form YYYY-MM-DD." };
  }
  const reason = input.reason.trim();
  if (reason.length < MIN_REASON_LENGTH) {
    return { ok: false, error: `Give a reason for the change (at least ${MIN_REASON_LENGTH} characters).` };
  }
  const body: { status: DocumentStatusValue; status_valid_from?: string; reason: string } = {
    status: input.status as DocumentStatusValue,
    reason,
  };
  if (validFrom !== "") {
    body.status_valid_from = validFrom;
  }
  return { ok: true, body };
}
