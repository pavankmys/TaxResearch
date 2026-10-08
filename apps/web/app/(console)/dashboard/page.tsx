import { AlertsBanner } from "@/components/dashboard/alerts-banner";
import {
  formatAge,
  formatCount,
  formatHours,
  formatMinutes,
  utcDayOffset,
} from "@/components/dashboard/format";
import { openTasksByKind, overdueTotal, flaggedPageTotal, failedPageTotal, maxQueueLag } from "@/components/dashboard/dashboard-data";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { MetricTile } from "@/components/dashboard/metric-tile";
import {
  DailyCountsTable,
  QueueLagTable,
  ReviewQueueTable,
  SourceHealthTable,
} from "@/components/dashboard/dashboard-tables";
import { apiClient } from "@/lib/server/api";

export const metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const client = await apiClient();
  const { data, response } = await client.GET("/v1/platform/ingestion/dashboard");
  if (!data) {
    return (
      <section className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Ingestion dashboard</h1>
        <LoadFailed what="the dashboard" status={response.status} />
      </section>
    );
  }

  const now = new Date();
  // The daily view counts by calendar day, so "last 24 h" is today and yesterday (UTC).
  const sinceDay = utcDayOffset(now, 1);
  const weekStart = utcDayOffset(now, 6);
  const recent = data.daily.filter((row) => row.day.slice(0, 10) >= sinceDay);
  const week = data.daily.filter((row) => row.day.slice(0, 10) >= weekStart);
  const sum = (rows: typeof recent, key: "discovered" | "done" | "failed") =>
    rows.reduce((total, row) => total + row[key], 0);

  const overall = data.freshness.find((row) => row.source_code === null);
  const openByKind = openTasksByKind(data.review_queue);
  const lag = maxQueueLag(data.queue_lag);
  const crossCheck = data.cross_check_disagreements;

  return (
    <section className="space-y-8" aria-labelledby="dashboard-title">
      <div className="space-y-4">
        <h1 id="dashboard-title" className="text-2xl font-semibold tracking-tight">
          Ingestion dashboard
        </h1>
        <AlertsBanner alerts={data.alerts} />
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Last 24 hours</h2>
        <p className="text-sm text-muted-foreground">
          Counted by calendar day in UTC, so this covers today and yesterday.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <MetricTile label="Documents discovered" value={formatCount(sum(recent, "discovered"))} />
          <MetricTile label="Documents done" value={formatCount(sum(recent, "done"))} />
          <MetricTile label="Documents failed" value={formatCount(sum(recent, "failed"))} />
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Freshness and review</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile
            label="Freshness p50"
            value={formatHours(overall?.p50_hours)}
            detail="Discovery to publication, last 7 days"
          />
          <MetricTile
            label="Freshness p95"
            value={formatHours(overall?.p95_hours)}
            detail={`${formatCount(overall?.samples ?? 0)} published jobs`}
          />
          <MetricTile
            label="Review tasks past SLA"
            value={formatCount(overdueTotal(data.review_queue))}
          />
          <MetricTile
            label="Queue lag (longest)"
            value={lag === null ? "—" : formatMinutes(lag)}
            detail="Oldest due job across the queues"
          />
          {openByKind.length === 0 ? (
            <MetricTile label="Open review tasks" value={formatCount(0)} />
          ) : (
            openByKind.map((kind) => (
              <MetricTile
                key={kind.kind}
                label={`Open ${kind.kind.replace(/_/g, " ")} tasks`}
                value={formatCount(kind.count)}
                detail={`Oldest open ${formatAge(kind.oldestOpenedAt, now)}`}
              />
            ))
          )}
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Pages and checks</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile
            label="Flagged pages"
            value={formatCount(flaggedPageTotal(data.page_accounting))}
            detail="Pages flagged by extraction checks"
          />
          <MetricTile
            label="Failed pages"
            value={formatCount(failedPageTotal(data.page_accounting))}
          />
          <MetricTile
            label="Cross-check disagreements"
            value={formatCount(crossCheck.disagreements)}
            detail={`Of ${formatCount(crossCheck.compared_pages)} pages compared`}
          />
          <MetricTile
            label="Numbering gaps"
            value="Not measured until M7"
            detail="Gap detection arrives with milestone M7"
          />
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Per source</h2>
        <DailyCountsTable rows={week} />
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Source health</h2>
        <SourceHealthTable rows={data.source_health} />
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Review queue</h2>
        <ReviewQueueTable rows={data.review_queue} />
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Queues</h2>
        <QueueLagTable rows={data.queue_lag} />
      </div>
    </section>
  );
}
