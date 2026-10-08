export interface Proposal {
  fields: Record<string, unknown>;
  confidence: Record<string, number>;
  issues: string[];
}

export interface Decision {
  action: string;
  note: string | null;
  decided_by: string | null;
  decided_at: string | null;
  fields: Record<string, unknown> | null;
}

export type JsonRecord = Record<string, unknown>;

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The metadata proposal stored in a task's resolution (or a spot-check's proposal), read
 * defensively because the resolution is JSON. Null when the task holds no proposal.
 */
export function readProposal(resolution: JsonRecord | null | undefined): Proposal | null {
  const raw = resolution?.proposal;
  if (!isRecord(raw)) {
    return null;
  }
  const fields = isRecord(raw.fields) ? raw.fields : {};
  const confidence: Record<string, number> = {};
  if (isRecord(raw.confidence)) {
    for (const [name, value] of Object.entries(raw.confidence)) {
      if (typeof value === "number" && Number.isFinite(value)) {
        confidence[name] = value;
      }
    }
  }
  const issues = Array.isArray(raw.issues)
    ? raw.issues.filter((issue): issue is string => typeof issue === "string")
    : [];
  return { fields, confidence, issues };
}

/** The reviewer decision stored in a resolution, or null when none was recorded. */
export function readDecision(resolution: JsonRecord | null | undefined): Decision | null {
  const raw = resolution?.decision;
  if (!isRecord(raw) || typeof raw.action !== "string") {
    return null;
  }
  return {
    action: raw.action,
    note: typeof raw.note === "string" ? raw.note : null,
    decided_by: typeof raw.decided_by === "string" ? raw.decided_by : null,
    decided_at: typeof raw.decided_at === "string" ? raw.decided_at : null,
    fields: isRecord(raw.fields) ? raw.fields : null,
  };
}

export const DECISION_LABELS: Record<string, string> = {
  approve: "Approved",
  edit_approve: "Edited and approved",
  reject: "Rejected",
  needs_info: "Marked as needs info",
};
