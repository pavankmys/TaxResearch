/**
 * Form-to-payload helpers for the ingest forms and the job page. These run on the server (in the
 * Server Actions) and in the browser (for the size check and the job state).
 */

export const DOC_TYPES = [
  "notification",
  "circular",
  "instruction",
  "order",
  "judgement",
  "act",
  "rules",
  "other",
] as const;

export const DOC_TYPE_LABELS: Record<(typeof DOC_TYPES)[number], string> = {
  notification: "Notification",
  circular: "Circular",
  instruction: "Instruction",
  order: "Order",
  judgement: "Judgement",
  act: "Act",
  rules: "Rules",
  other: "Other",
};

export const UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024;

/** The optional identifying fields, in the order the form shows them. */
export const OPTIONAL_FIELDS = [
  "title",
  "series",
  "number",
  "year",
  "circular_a",
  "circular_b",
  "case_number",
  "court_code",
  "decision_date",
] as const;

export type OptionalField = (typeof OPTIONAL_FIELDS)[number];

export type BuildResult<T> = { ok: true; body: T } | { ok: false; error: string };

/** The JSON body of POST /v1/platform/ingestion/url. */
export type UrlSubmissionBody = {
  source: string;
  doc_type: string;
  url: string;
} & Partial<Record<OptionalField, string>>;

/** An error message for a file that cannot be uploaded, or null when the size is acceptable. */
export function checkUploadSize(size: number): string | null {
  if (size <= 0) {
    return "The file is empty. Choose a PDF or HTML file.";
  }
  if (size > UPLOAD_LIMIT_BYTES) {
    return "The file is larger than 50 MB. Choose a smaller file.";
  }
  return null;
}

/** Trimmed value, or undefined when blank. Blank optional fields are left out of the payload. */
function trimmed(raw: Record<string, string>, name: string): string | undefined {
  const value = (raw[name] ?? "").trim();
  return value === "" ? undefined : value;
}

function isDocType(value: string): value is (typeof DOC_TYPES)[number] {
  return (DOC_TYPES as readonly string[]).includes(value);
}

function requiredError(raw: Record<string, string>): string | null {
  if (!trimmed(raw, "source")) {
    return "Choose a source.";
  }
  const docType = trimmed(raw, "doc_type") ?? "";
  if (!isDocType(docType)) {
    return "Choose a document type.";
  }
  return null;
}

/** The JSON body for POST /v1/platform/ingestion/url. */
export function buildUrlSubmission(raw: Record<string, string>): BuildResult<UrlSubmissionBody> {
  const error = requiredError(raw);
  if (error) {
    return { ok: false, error };
  }
  const url = trimmed(raw, "url");
  if (!url) {
    return { ok: false, error: "Enter the document's URL." };
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, error: "The URL is not valid." };
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { ok: false, error: "The URL must start with http:// or https://." };
  }

  const body: UrlSubmissionBody = {
    source: trimmed(raw, "source") ?? "",
    doc_type: trimmed(raw, "doc_type") ?? "",
    url,
  };
  for (const field of OPTIONAL_FIELDS) {
    const value = trimmed(raw, field);
    if (value !== undefined) {
      body[field] = value;
    }
  }
  return { ok: true, body };
}

/** The text fields of the multipart upload. The file itself is added by the caller. */
export function buildUploadFields(raw: Record<string, string>): BuildResult<Record<string, string>> {
  const error = requiredError(raw);
  if (error) {
    return { ok: false, error };
  }
  const fields: Record<string, string> = {
    source: trimmed(raw, "source") ?? "",
    doc_type: trimmed(raw, "doc_type") ?? "",
  };
  for (const field of OPTIONAL_FIELDS) {
    const value = trimmed(raw, field);
    if (value !== undefined) {
      fields[field] = value;
    }
  }
  return { ok: true, body: fields };
}

/** Text for an error from the API. FastAPI sends a string, or a list of validation messages. */
export function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim() !== "") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
      .filter((message) => message !== "");
    if (messages.length > 0) {
      return messages.join(" ");
    }
  }
  return fallback;
}
