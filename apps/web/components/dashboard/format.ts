/**
 * Formatting helpers shared by the dashboard, documents and ingest pages.
 * Every function returns a string a reader can use as is. A missing number shows as an em dash.
 */

const MISSING = "—";

const COUNT_FORMAT = new Intl.NumberFormat("en-US");
const DECIMAL_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const PERCENT_FORMAT = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 0,
});
const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});
const DATE_TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** A whole number with thousands separators, or an em dash. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return MISSING;
  }
  return COUNT_FORMAT.format(value);
}

/** A ratio in [0, 1] as a whole percentage, or an em dash. */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) {
    return MISSING;
  }
  return PERCENT_FORMAT.format(ratio);
}

/** Hours with at most one decimal, for example "3.5 h". */
export function formatHours(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return MISSING;
  }
  return `${DECIMAL_FORMAT.format(value)} h`;
}

/** Minutes as "45 min", or "2 h 5 min" from 60 minutes on. */
export function formatMinutes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return MISSING;
  }
  const total = Math.max(0, Math.round(value));
  if (total < 60) {
    return `${total} min`;
  }
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`;
}

/**
 * An age between two instants, as "under 1 h", "3 h", "2 d 4 h". Returns an em dash when the
 * start is missing or in the future.
 */
export function formatAge(from: string | null | undefined, now: Date): string {
  if (!from) {
    return MISSING;
  }
  const start = new Date(from).getTime();
  if (Number.isNaN(start)) {
    return MISSING;
  }
  const hours = (now.getTime() - start) / 3_600_000;
  if (hours < 0) {
    return MISSING;
  }
  if (hours < 1) {
    return "under 1 h";
  }
  const whole = Math.floor(hours);
  if (whole < 48) {
    return `${whole} h`;
  }
  const days = Math.floor(whole / 24);
  const rest = whole % 24;
  return rest === 0 ? `${days} d` : `${days} d ${rest} h`;
}

/** A calendar date from an ISO date (YYYY-MM-DD) or timestamp, for example "10 Oct 2022". */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return MISSING;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return MISSING;
  }
  return DATE_FORMAT.format(parsed);
}

/** A timestamp in UTC, for example "8 Oct 2026, 10:30 UTC". */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return MISSING;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return MISSING;
  }
  return `${DATE_TIME_FORMAT.format(parsed)} UTC`;
}

/** The UTC calendar day n days before `now`, as YYYY-MM-DD. */
export function utcDayOffset(now: Date, days: number): string {
  const copy = new Date(now.getTime());
  copy.setUTCHours(0, 0, 0, 0);
  copy.setUTCDate(copy.getUTCDate() - days);
  return copy.toISOString().slice(0, 10);
}
