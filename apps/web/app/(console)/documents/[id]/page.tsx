import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { PagesTable } from "@/components/documents/pages-table";
import { SourcesTable } from "@/components/documents/sources-table";
import { StatusPanel } from "@/components/documents/status-panel";
import { MetadataPanel } from "@/components/documents/metadata-panel";
import { VersionsTable } from "@/components/documents/versions-table";
import { StructureOutline } from "@/components/documents/structure-outline";
import { DocumentTabs, type DocumentTab } from "@/components/documents/document-tabs";
import { ConfidenceBadge, ReviewStateBadge, StatusBadge } from "@/components/documents/badges";
import { DOC_TYPE_FILTER_LABELS, labelOr } from "@/components/documents/labels";
import { isUuid, shortId } from "@/components/documents/ids";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/server/api";
import { loadBlocks } from "@/app/(console)/documents/[id]/actions";

export const metadata = { title: "Document" };

const BLOCK_PAGE_SIZE = 200;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

export default async function DocumentPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: SearchParams;
}) {
  const { id } = await params;
  if (!isUuid(id)) {
    notFound();
  }
  const query = await searchParams;

  const client = await apiClient();
  const detail = await client.GET("/v1/platform/documents/{document_id}", {
    params: { path: { document_id: id } },
  });
  const doc = detail.data;
  if (!doc) {
    if (detail.response.status === 404) {
      notFound();
    }
    return (
      <section className="space-y-6">
        <Link href="/documents" className="text-sm underline underline-offset-4 hover:no-underline">
          Back to documents
        </Link>
        <LoadFailed what="this document" status={detail.response.status} />
      </section>
    );
  }

  const currentVersion = doc.versions.find((version) => version.id === doc.current_version_id) ?? null;
  const requestedVersion = first(query.version);
  const pagesVersion = doc.versions.find((version) => version.id === requestedVersion) ?? currentVersion;
  const pageCount = currentVersion?.mime === "application/pdf" ? (currentVersion.page_count ?? 0) : 0;
  const pageNumbers = Array.from({ length: pageCount }, (_, index) => index + 1);

  let structure: React.ReactNode = <p className="text-sm text-muted-foreground">This document has no version yet.</p>;
  if (currentVersion) {
    const blocks = await client.GET("/v1/platform/documents/{document_id}/versions/{version_id}/blocks", {
      params: {
        path: { document_id: doc.id, version_id: currentVersion.id },
        query: { limit: BLOCK_PAGE_SIZE },
      },
    });
    structure = blocks.data ? (
      <StructureOutline
        documentId={doc.id}
        versionId={currentVersion.id}
        initial={blocks.data}
        pageNumbers={pageNumbers}
        loadBlocks={loadBlocks}
      />
    ) : (
      <LoadFailed what="the structure" status={blocks.response.status} />
    );
  }

  let pages: React.ReactNode = <p className="text-sm text-muted-foreground">This document has no version yet.</p>;
  if (pagesVersion) {
    const list = await client.GET("/v1/platform/documents/{document_id}/versions/{version_id}/pages", {
      params: { path: { document_id: doc.id, version_id: pagesVersion.id } },
    });
    pages = list.data ? (
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">{`Pages of version ${pagesVersion.version_no}`}</h2>
        <PagesTable
          documentId={doc.id}
          versionId={pagesVersion.id}
          title={doc.title}
          pages={list.data.items}
          isPdf={pagesVersion.mime === "application/pdf"}
        />
      </div>
    ) : (
      <LoadFailed what="the page list" status={list.response.status} />
    );
  }

  const tabs: DocumentTab[] = [
    { value: "metadata", label: "Metadata", content: <MetadataPanel doc={doc} /> },
    { value: "status", label: "Status", content: <StatusPanel doc={doc} /> },
    {
      value: "versions",
      label: "Versions",
      content: (
        <VersionsTable documentId={doc.id} versions={doc.versions} currentVersionId={doc.current_version_id} />
      ),
    },
    { value: "structure", label: "Structure", content: structure },
    { value: "pages", label: "Pages", content: pages },
    { value: "sources", label: "Sources", content: <SourcesTable links={doc.sources} /> },
    {
      value: "tasks",
      label: "Review tasks",
      content:
        doc.open_review_task_ids.length === 0 ? (
          <p className="text-sm text-muted-foreground">No open review tasks for this document.</p>
        ) : (
          <ul className="space-y-2">
            {doc.open_review_task_ids.map((taskId) => (
              <li key={taskId}>
                <Link href={`/queue/${taskId}`} className="underline underline-offset-4 hover:no-underline">
                  {`Open review task ${shortId(taskId)}`}
                </Link>
              </li>
            ))}
          </ul>
        ),
    },
  ];

  return (
    <section className="space-y-6" aria-labelledby="document-title">
      <Link href="/documents" className="text-sm underline underline-offset-4 hover:no-underline">
        Back to documents
      </Link>

      <header className="space-y-3">
        <h1 id="document-title" className="break-words text-2xl font-semibold tracking-tight">
          {doc.title}
        </h1>
        <p className="break-all font-mono text-sm">{doc.canonical_id}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{labelOr(DOC_TYPE_FILTER_LABELS, doc.doc_type)}</Badge>
          <StatusBadge status={doc.status} />
          <ReviewStateBadge state={doc.review_state} />
          <ConfidenceBadge value={doc.meta_confidence} />
        </div>
      </header>

      <Suspense fallback={null}>
        <DocumentTabs tabs={tabs} />
      </Suspense>
    </section>
  );
}
