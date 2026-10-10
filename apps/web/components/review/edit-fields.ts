import type { JsonRecord } from "./proposal";

/**
 * Metadata fields that a reviewer may edit. This mirrors METADATA_FIELDS in
 * apps/api/app/routers/review_tasks.py; the API rejects any other name.
 */
export const METADATA_FIELDS = [
  "doc_type",
  "title",
  "number",
  "series",
  "year",
  "doc_date",
  "in_force_date",
  "issuing_authority",
  "canonical_id",
  "sections_referred",
  "effective_date",
  "gazette_ref",
  "circular_kind",
  "subject",
  "din",
  "court_level",
  "court_name",
  "court_code",
  "bench",
  "judges",
  "decision_date",
  "parties",
  "case_numbers",
  "reporter_citations",
] as const;

/** Fields stored as a list of strings; edited as comma-separated text. */
export const LIST_FIELDS: ReadonlySet<string> = new Set([
  "sections_referred",
  "judges",
  "case_numbers",
  "reporter_citations",
]);

/** Fields stored as an object. Not editable in this form; shown read-only. */
export const OBJECT_FIELDS: ReadonlySet<string> = new Set(["parties"]);

const INTEGER_FIELDS: ReadonlySet<string> = new Set(["year"]);
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const INTEGER_PATTERN = /^-?\d+$/;

export interface EditableField {
  name: string;
  initial: string;
}

/** Text shown in an edit input for a stored value. Lists are joined with ", ". */
export function formValueFor(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function listValues(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function sameItems(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

/** Comma-separated text to a list of non-empty, trimmed values. */
export function parseListText(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

/**
 * Amendment fields that a reviewer may edit when doing edit_approve.
 */
export const AMENDMENT_FIELDS = [
  "op",
  "old_text",
  "new_text",
  "effective_from",
  "effective_condition",
  "target_provision_id",
] as const;

/** The editable fields, in METADATA_FIELDS order, with their starting text. */
export function editableFields(proposalFields: JsonRecord): EditableField[] {
  return METADATA_FIELDS.filter((name) => !OBJECT_FIELDS.has(name)).map((name) => ({
    name,
    initial: formValueFor(proposalFields[name]),
  }));
}

/** The editable fields for an amendment task, in AMENDMENT_FIELDS order. */
export function editableAmendmentFields(amendmentFields: JsonRecord): EditableField[] {
  return AMENDMENT_FIELDS.map((name) => ({
    name,
    initial: formValueFor(amendmentFields[name]),
  }));
}

export interface EditPatch {
  patch: Record<string, unknown>;
  errors: string[];
}

/**
 * The fields the reviewer changed, converted to the stored types. Unchanged fields are left out,
 * so a decision only carries what was edited. An empty input clears the field (null).
 */
export function buildEditPatch(
  original: JsonRecord,
  edited: Record<string, string>,
  allowedFields: readonly string[] = METADATA_FIELDS,
): EditPatch {
  const patch: JsonRecord = {};
  const errors: string[] = [];

  for (const [name, rawText] of Object.entries(edited)) {
    if (!allowedFields.includes(name)) {
      continue;
    }
    if (OBJECT_FIELDS.has(name)) {
      continue;
    }
    const text = rawText.trim();

    if (LIST_FIELDS.has(name)) {
      // Lists compare by their values, so spacing around the commas is not a change.
      const items = parseListText(text);
      if (sameItems(items, listValues(original[name]))) {
        continue;
      }
      patch[name] = items.length > 0 ? items : null;
      continue;
    }

    if (text === formValueFor(original[name]).trim()) {
      continue;
    }

    if (text === "") {
      patch[name] = null;
    } else if (INTEGER_FIELDS.has(name)) {
      if (INTEGER_PATTERN.test(text)) {
        patch[name] = Number(text);
      } else {
        errors.push(`${label(name)} must be a whole number`);
      }
    } else if (name.endsWith("_date") || name === "effective_from") {
      if (DATE_PATTERN.test(text)) {
        patch[name] = text;
      } else {
        errors.push(`${label(name)} must be a date as YYYY-MM-DD`);
      }
    } else {
      patch[name] = text;
    }
  }

  return { patch, errors };
}

/** A readable name for a field, for messages: "doc_date" becomes "Doc date". */
export function label(name: string): string {
  const spaced = name.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
