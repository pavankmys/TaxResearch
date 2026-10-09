import Link from "next/link";
import { notFound } from "next/navigation";

import { ProvisionTree } from "@/components/baseline/provision-tree";
import { StatusBadge } from "@/components/baseline/status-badge";
import { VerifyForm } from "@/components/baseline/verify-form";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { formatDate, formatCount } from "@/components/dashboard/format";
import { isUuid } from "@/components/documents/ids";
import { apiClient } from "@/lib/server/api";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

export default async function BaselineDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ code: string }>;
  searchParams: SearchParams;
}) {
  const { code } = await params;
  const query = await searchParams;
  const pParam = first(query.p);
  const selectedId = isUuid(pParam) ? pParam : undefined;

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/baseline/instruments/{code}/provisions", {
    params: { path: { code } },
  });

  if (!data) {
    if (response.status === 404) {
      notFound();
    }
    return (
      <section className="space-y-6">
        <LoadFailed what="the baseline provisions" status={response.status} />
      </section>
    );
  }

  const instrument = data.instrument;
  let detail = null;

  if (selectedId) {
    const detailResponse = await client.GET("/v1/baseline/instruments/{code}/provisions/{provision_id}", {
      params: { path: { code, provision_id: selectedId } },
    });
    detail = detailResponse.data;
    if (!detail && detailResponse.response.status !== 404) {
      return (
        <section className="space-y-6">
          <LoadFailed what="the provision detail" status={detailResponse.response.status} />
        </section>
      );
    }
  }

  const showNoteWhenEmpty = !selectedId;

  return (
    <section className="space-y-6" aria-labelledby="baseline-title">
      <Link href="/baseline" className="text-sm underline underline-offset-4 hover:no-underline">
        Back to baseline list
      </Link>

      <header className="space-y-3">
        <h1 id="baseline-title" className="text-2xl font-semibold tracking-tight">
          {instrument.short_name}
        </h1>
        <p className="font-mono text-sm text-muted-foreground">{instrument.code}</p>
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={instrument.baseline_status} />
          <span className="text-sm text-muted-foreground">
            As of {formatDate(instrument.baseline_as_on)}
          </span>
          <span className="text-sm text-muted-foreground">
            {formatCount(instrument.provision_count)} provisions, {formatCount(instrument.section_count)} sections/rules
          </span>
        </div>
      </header>

      {data.numbering_gaps.length > 0 ? (
        <Alert variant="destructive">
          <AlertTitle>Numbering gaps detected</AlertTitle>
          <AlertDescription>
            Section numbers missing from the loaded text: {data.numbering_gaps.join(", ")}. Some may be genuinely
            omitted in the law; check each against the source.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <AlertTitle>No numbering gaps</AlertTitle>
          <AlertDescription>All section numbers are sequential.</AlertDescription>
        </Alert>
      )}

      {instrument.baseline_status === "verified" && instrument.baseline_verified_by_name && (
        <Alert variant="default">
          <AlertTitle>Verified</AlertTitle>
          <AlertDescription>
            Verified by {instrument.baseline_verified_by_name} on{" "}
            {formatDate(instrument.baseline_verified_at)}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <ProvisionTree items={data.items} instrumentCode={code} selectedId={selectedId} />

        <div className="space-y-4">
          {showNoteWhenEmpty ? (
            <div className="rounded border border-dashed p-4">
              <p className="text-sm text-muted-foreground">Select a provision from the tree to view its details.</p>
            </div>
          ) : selectedId && !detail ? (
            <div className="rounded border border-dashed p-4">
              <p className="text-sm text-destructive">Provision not found.</p>
            </div>
          ) : detail ? (
            <>
              <div>
                <h2 className="font-semibold text-lg">{detail.heading || "—"}</h2>
                <p className="font-mono text-xs text-muted-foreground break-all">{detail.path}</p>
              </div>

              <div className="grid gap-2 text-sm">
                <div>
                  <span className="text-muted-foreground">Valid from:</span>
                  <p>{formatDate(detail.valid_from)}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Blocks:</span>
                  <p>{detail.block_count}</p>
                </div>
              </div>

              <div className="space-y-2">
                <span className="text-sm font-medium">Text:</span>
                <div className="max-h-96 overflow-auto rounded bg-muted p-3 text-sm whitespace-pre-wrap break-words">
                  {detail.text}
                </div>
              </div>

              {detail.source_document_id && (
                <div className="text-sm">
                  <span className="text-muted-foreground">Source:</span>
                  <p>
                    <Link
                      href={`/documents/${detail.source_document_id}`}
                      className="underline underline-offset-4 hover:no-underline"
                    >
                      {detail.source_page ? `page ${detail.source_page}` : "document"}
                    </Link>
                  </p>
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>

      {instrument.baseline_status === "loaded" && (
        <div className="border-t pt-6">
          <h2 className="font-semibold text-lg mb-4">Verify baseline</h2>
          <VerifyForm code={code} />
        </div>
      )}
    </section>
  );
}
