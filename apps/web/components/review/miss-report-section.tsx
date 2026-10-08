import { formatDateTimeUtc } from "./format";
import { isRecord, type JsonRecord } from "./proposal";

interface MissReportSectionProps {
  resolution: JsonRecord | null;
  currentUserId: string;
  createdAt: string;
}

/** A miss report: what the user searched for, the filters, the as-on date and the expected result. */
export function MissReportSection({ resolution, currentUserId, createdAt }: MissReportSectionProps) {
  const report = isRecord(resolution) && isRecord(resolution.report) ? resolution.report : null;
  if (report === null) {
    return <p className="text-sm text-muted-foreground">No report details are recorded.</p>;
  }

  const query = typeof report.query === "string" ? report.query : "";
  const asOn = typeof report.as_on === "string" ? report.as_on : null;
  const expected = typeof report.expected === "string" ? report.expected : null;
  const reportedBy = typeof report.reported_by === "string" ? report.reported_by : null;
  const filters = isRecord(report.filters) ? report.filters : {};
  const hasFilters = Object.keys(filters).length > 0;

  return (
    <section aria-labelledby="report-heading" className="space-y-4">
      <h2 id="report-heading" className="text-lg font-semibold">
        Search that missed
      </h2>
      <dl className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1 sm:col-span-2">
          <dt className="text-sm font-medium text-muted-foreground">Query</dt>
          <dd className="break-words text-base">{query || "—"}</dd>
        </div>
        <div className="space-y-1">
          <dt className="text-sm font-medium text-muted-foreground">As on date</dt>
          <dd>{asOn ?? "Not given"}</dd>
        </div>
        <div className="space-y-1">
          <dt className="text-sm font-medium text-muted-foreground">Reported by</dt>
          <dd>
            {reportedBy === null ? "Unknown" : reportedBy === currentUserId ? "You" : "Another user"}
          </dd>
        </div>
        <div className="space-y-1">
          <dt className="text-sm font-medium text-muted-foreground">Reported on</dt>
          <dd>{formatDateTimeUtc(createdAt)}</dd>
        </div>
        <div className="space-y-1 sm:col-span-2">
          <dt className="text-sm font-medium text-muted-foreground">Expected result</dt>
          <dd className="whitespace-pre-wrap break-words">{expected ?? "Not given"}</dd>
        </div>
        <div className="space-y-1 sm:col-span-2">
          <dt className="text-sm font-medium text-muted-foreground">Filters</dt>
          <dd>
            {hasFilters ? (
              <pre className="overflow-auto rounded-md border bg-muted/40 p-3 text-xs">
                {JSON.stringify(filters, null, 2)}
              </pre>
            ) : (
              "No filters"
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}
