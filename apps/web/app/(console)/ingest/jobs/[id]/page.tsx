import Link from "next/link";
import { notFound } from "next/navigation";

import { formatDateTime } from "@/components/dashboard/format";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { isUuid } from "@/components/documents/ids";
import { JobAutoRefresh } from "@/components/ingest/job-auto-refresh";
import { isTerminalJob } from "@/components/ingest/job-state";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/server/api";

export const metadata = { title: "Ingest job" };

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 p-3 sm:grid-cols-[12rem_1fr]">
      <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm">{children}</dd>
    </div>
  );
}

export default async function IngestJobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) {
    notFound();
  }

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/platform/ingestion/jobs/{job_id}", {
    params: { path: { job_id: id } },
  });
  if (!data) {
    if (response.status === 404) {
      notFound();
    }
    return (
      <section className="space-y-6">
        <Link href="/ingest" className="text-sm underline underline-offset-4 hover:no-underline">
          Back to ingest
        </Link>
        <LoadFailed what="this job" status={response.status} />
      </section>
    );
  }

  const terminal = isTerminalJob(data.stage, data.status);
  const failed = data.status === "failed";

  return (
    <section className="space-y-6" aria-labelledby="job-title">
      <Link href="/ingest" className="text-sm underline underline-offset-4 hover:no-underline">
        Back to ingest
      </Link>

      <header className="space-y-2">
        <h1 id="job-title" className="text-2xl font-semibold tracking-tight">
          Ingest job
        </h1>
        <p className="break-all font-mono text-xs text-muted-foreground">{data.id}</p>
      </header>

      <div role="status" aria-live="polite" className="flex flex-wrap items-center gap-2 text-sm">
        {terminal ? (
          <span>{failed ? "The job failed." : "The job has finished."}</span>
        ) : (
          <span>The job is still running. This page refreshes every few seconds.</span>
        )}
        <Badge variant={failed ? "destructive" : "outline"}>{`Stage ${data.stage}, ${data.status}`}</Badge>
      </div>

      <dl className="divide-y rounded-md border">
        <Field label="Stage">{data.stage}</Field>
        <Field label="Status">{data.status}</Field>
        <Field label="Attempt">{String(data.attempt)}</Field>
        <Field label="Document">
          {data.document_id ? (
            <Link
              href={`/documents/${data.document_id}`}
              className="underline underline-offset-4 hover:no-underline"
            >
              Open the document
            </Link>
          ) : (
            "Not yet created"
          )}
        </Field>
        <Field label="Started">{formatDateTime(data.started_at)}</Field>
        <Field label="Finished">{formatDateTime(data.finished_at)}</Field>
        <Field label="URL">
          {data.url ? <span className="break-all font-mono text-xs">{data.url}</span> : "Uploaded file"}
        </Field>
        {data.error_code ? (
          <Field label="Error">
            <span className="font-mono text-xs">{data.error_code}</span>
            {data.error_detail ? <span className="mt-1 block">{data.error_detail}</span> : null}
          </Field>
        ) : null}
      </dl>

      {terminal ? null : <JobAutoRefresh />}
    </section>
  );
}
