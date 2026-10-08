import { IngestForms } from "@/components/ingest/ingest-forms";
import { SourcesTable, type SourceRow } from "@/components/ingest/sources-table";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { apiClient, requireSession } from "@/lib/server/api";

export const metadata = { title: "Ingest" };

export default async function IngestPage() {
  const user = await requireSession();
  const isAdmin = user.roles.includes("platform_admin");

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/platform/sources");

  const rows: SourceRow[] = (data?.items ?? []).map((source) => ({
    code: source.code,
    enabled: source.enabled,
    expected_cadence_hours: source.expected_cadence_hours,
    last_success_at: source.last_success_at,
    in_config: source.in_config,
  }));
  const choices = (data?.items ?? [])
    .filter((source) => source.enabled && source.in_config)
    .map((source) => ({ code: source.code, description: source.description }));

  return (
    <section className="space-y-10" aria-labelledby="ingest-title">
      <h1 id="ingest-title" className="text-2xl font-semibold tracking-tight">
        Ingest
      </h1>

      {data ? (
        <IngestForms sources={choices} />
      ) : (
        <LoadFailed what="the source list" status={response.status} />
      )}

      <section aria-labelledby="sources-heading" className="space-y-3">
        <h2 id="sources-heading" className="text-lg font-semibold">
          Sources
        </h2>
        {data ? (
          <SourcesTable rows={rows} isAdmin={isAdmin} />
        ) : (
          <p className="text-sm text-muted-foreground">The sources could not be listed.</p>
        )}
      </section>
    </section>
  );
}
