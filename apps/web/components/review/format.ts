const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

const DUE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** Relative age of a task: "12 min", "3 h" or "2 d". Future or invalid times give "0 min" or "unknown". */
export function formatAge(openedAt: string, now: number = Date.now()): string {
  const opened = Date.parse(openedAt);
  if (Number.isNaN(opened)) {
    return "unknown";
  }
  const elapsed = Math.max(0, now - opened);
  if (elapsed < HOUR_MS) {
    return `${Math.floor(elapsed / MINUTE_MS)} min`;
  }
  if (elapsed < DAY_MS) {
    return `${Math.floor(elapsed / HOUR_MS)} h`;
  }
  return `${Math.floor(elapsed / DAY_MS)} d`;
}

/** A timestamp shown in UTC, for example "8 Oct 2026, 18:00 UTC". */
export function formatDateTimeUtc(value: string): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) {
    return value;
  }
  return `${DUE_FORMAT.format(time)} UTC`;
}

/** True when a task has an SLA due time that has passed. */
export function isOverdue(slaDueAt: string | null, now: number = Date.now()): boolean {
  if (slaDueAt === null) {
    return false;
  }
  const due = Date.parse(slaDueAt);
  return !Number.isNaN(due) && due < now;
}

const KIND_LABELS: Record<string, string> = {
  metadata: "Metadata",
  parse_failure: "Parse failure",
  miss_report: "Miss report",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_review: "In review",
  done: "Done",
  rejected: "Rejected",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function isClosedStatus(status: string): boolean {
  return status === "done" || status === "rejected";
}
