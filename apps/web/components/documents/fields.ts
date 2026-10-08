/**
 * The metadata fields a reviewer may edit from the document page, and the payload builder for
 * PATCH /v1/platform/documents/{id}. Only changed fields are sent, so an untouched field is not
 * recorded as an override.
 */

export type EditableKind = "text" | "year" | "date";

export interface EditableField {
  name: string;
  label: string;
  kind: EditableKind;
}

export const EDITABLE_FIELDS: readonly EditableField[] = [
  { name: "title", label: "Title", kind: "text" },
  { name: "number", label: "Number", kind: "text" },
  { name: "series", label: "Series", kind: "text" },
  { name: "year", label: "Year", kind: "year" },
  { name: "doc_date", label: "Document date", kind: "date" },
  { name: "in_force_date", label: "In force from", kind: "date" },
  { name: "issuing_authority", label: "Issuing authority", kind: "text" },
  { name: "subject", label: "Subject", kind: "text" },
  { name: "din", label: "DIN", kind: "text" },
  { name: "court_name", label: "Court name", kind: "text" },
  { name: "bench", label: "Bench", kind: "text" },
  { name: "decision_date", label: "Decision date", kind: "date" },
];

export const EDITABLE_FIELD_NAMES: readonly string[] = EDITABLE_FIELDS.map((field) => field.name);

/** The document row, the metadata JSON and the typed row, as the detail endpoint returns them. */
export interface MetadataSource {
  title: string;
  number: string | null;
  series: string | null;
  doc_date: string | null;
  in_force_date: string | null;
  issuing_authority: string | null;
  bench: string | null;
  metadata: Record<string, unknown>;
  typed_row: Record<string, unknown> | null;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** The value a field shows now: the metadata JSON first, then the document column, then the typed row. */
export function currentFieldValue(doc: MetadataSource, name: string): string {
  const fromMetadata = doc.metadata.fields as Record<string, unknown> | undefined;
  if (fromMetadata && fromMetadata[name] !== undefined && fromMetadata[name] !== null) {
    return asText(fromMetadata[name]);
  }
  const columns: Record<string, unknown> = {
    title: doc.title,
    number: doc.number,
    series: doc.series,
    doc_date: doc.doc_date,
    in_force_date: doc.in_force_date,
    issuing_authority: doc.issuing_authority,
    bench: doc.bench,
  };
  if (name in columns) {
    return asText(columns[name]);
  }
  return asText(doc.typed_row?.[name]);
}

export function currentFieldValues(doc: MetadataSource): Record<string, string> {
  return Object.fromEntries(
    EDITABLE_FIELDS.map((field) => [field.name, currentFieldValue(doc, field.name)]),
  );
}

export const MIN_REASON_LENGTH = 3;

const YEAR_PATTERN = /^\d{4}$/;
const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/** True for a real calendar date written as YYYY-MM-DD. */
export function isIsoDate(value: string): boolean {
  const match = DATE_PATTERN.exec(value);
  if (!match) {
    return false;
  }
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

export type PatchResult =
  | { ok: true; body: { fields: Record<string, string>; reason: string } }
  | { ok: false; error: string };

/**
 * Turn the submitted form into the PATCH body. Blank fields and unchanged fields are left out.
 * A blank field keeps its value; the form cannot clear one.
 */
export function buildMetadataPatch(
  current: Record<string, string>,
  submitted: Record<string, string>,
  reason: string,
): PatchResult {
  const trimmedReason = reason.trim();
  if (trimmedReason.length < MIN_REASON_LENGTH) {
    return { ok: false, error: `Give a reason for the change (at least ${MIN_REASON_LENGTH} characters).` };
  }

  const fields: Record<string, string> = {};
  for (const field of EDITABLE_FIELDS) {
    const value = (submitted[field.name] ?? "").trim();
    if (value === "") {
      continue;
    }
    if (field.kind === "year" && !YEAR_PATTERN.test(value)) {
      return { ok: false, error: `${field.label} must be a four-digit year.` };
    }
    if (field.kind === "date" && !isIsoDate(value)) {
      return { ok: false, error: `${field.label} must be a date in the form YYYY-MM-DD.` };
    }
    if (value !== (current[field.name] ?? "").trim()) {
      fields[field.name] = value;
    }
  }

  if (Object.keys(fields).length === 0) {
    return { ok: false, error: "No changes to save." };
  }
  return { ok: true, body: { fields, reason: trimmedReason } };
}
