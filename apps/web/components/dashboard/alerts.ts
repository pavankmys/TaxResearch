/** Alert kinds from GET /v1/platform/ingestion/dashboard, with the severity each one shows. */

export type AlertSeverity = "critical" | "warning";

const SEVERITY_BY_KIND: Record<string, AlertSeverity> = {
  failure_rate: "critical",
  overdue_review: "critical",
  freshness_p95: "warning",
  stale_source: "warning",
  queue_lag: "warning",
};

/** Unknown kinds count as warnings, so a new alert kind is never shown without a severity. */
export function alertSeverity(kind: string): AlertSeverity {
  return SEVERITY_BY_KIND[kind] ?? "warning";
}

/** The severity as text. Colour is never the only signal. */
export function alertSeverityLabel(severity: AlertSeverity): string {
  return severity === "critical" ? "Critical" : "Warning";
}
