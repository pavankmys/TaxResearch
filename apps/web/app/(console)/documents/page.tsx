import Link from "next/link";

import { FilterSelect } from "@/components/documents/filter-select";
import { DOC_TYPE_FILTER_LABELS, labelOr, REVIEW_STATE_LABELS, REVIEW_STATE_VALUES } from "@/components/documents/labels";
import { documentsHref } from "@/components/documents/list-query";
import { ReviewStateBadge } from "@/components/documents/badges";
import { isUuid } from "@/components/documents/ids";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { formatDate } from "@/components/dashboard/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiClient } from "@/lib/server/api";

export const metadata = { title: "Documents" };

const PAGE_SIZE = 50;
const MAX_SEARCH_LENGTH = 200;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

export default async function DocumentsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const q = first(params.q).trim().slice(0, MAX_SEARCH_LENGTH);
  const docType = first(params.doc_type);
  const reviewState = first(params.review_state);
  const cursorParam = first(params.cursor);
  const cursor = isUuid(cursorParam) ? cursorParam : undefined;
  const docTypeFilter = Object.keys(DOC_TYPE_FILTER_LABELS).includes(docType) ? docType : "all";
  const reviewStateFilter = REVIEW_STATE_VALUES.includes(reviewState) ? reviewState : "all";

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/platform/documents", {
    params: {
      query: {
        q: q || undefined,
        doc_type: docTypeFilter === "all" ? undefined : docTypeFilter,
        review_state: reviewStateFilter === "all" ? undefined : reviewStateFilter,
        cursor,
        limit: PAGE_SIZE,
      },
    },
  });

  const nextHref = data?.next_cursor
    ? documentsHref({
        q,
        docType: docTypeFilter,
        reviewState: reviewStateFilter,
        cursor: data.next_cursor,
      })
    : null;

  return (
    <section className="space-y-6" aria-labelledby="documents-title">
      <h1 id="documents-title" className="text-2xl font-semibold tracking-tight">
        Documents
      </h1>

      <form method="get" action="/documents" role="search" aria-label="Search documents" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_12rem_12rem_auto] lg:items-end">
        <div className="space-y-2">
          <Label htmlFor="q">Search by title or canonical ID</Label>
          <Input id="q" name="q" type="search" defaultValue={q} maxLength={MAX_SEARCH_LENGTH} />
        </div>
        <FilterSelect
          id="doc_type"
          name="doc_type"
          label="Document type"
          value={docTypeFilter}
          allLabel="All types"
          options={Object.entries(DOC_TYPE_FILTER_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <FilterSelect
          id="review_state"
          name="review_state"
          label="Review state"
          value={reviewStateFilter}
          allLabel="All states"
          options={Object.entries(REVIEW_STATE_LABELS).map(([value, label]) => ({ value, label }))}
        />
        <Button type="submit">Apply filters</Button>
      </form>

      {!data ? (
        <LoadFailed what="the document list" status={response.status} />
      ) : (
        <>
          <Table>
            <caption className="mb-2 text-left text-sm text-muted-foreground">
              Documents, newest first. {data.items.length} shown on this page.
            </caption>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Title</TableHead>
                <TableHead scope="col">Canonical ID</TableHead>
                <TableHead scope="col">Type</TableHead>
                <TableHead scope="col">Review state</TableHead>
                <TableHead scope="col">Document date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    No documents match these filters.
                  </TableCell>
                </TableRow>
              ) : null}
              {data.items.map((doc) => (
                <TableRow key={doc.id}>
                  <TableCell className="min-w-48 font-medium">
                    <Link href={`/documents/${doc.id}`} className="underline underline-offset-4 hover:no-underline">
                      {doc.title}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs break-all">{doc.canonical_id}</TableCell>
                  <TableCell>{labelOr(DOC_TYPE_FILTER_LABELS, doc.doc_type)}</TableCell>
                  <TableCell>
                    <ReviewStateBadge state={doc.review_state} />
                  </TableCell>
                  <TableCell>{formatDate(doc.doc_date)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {nextHref ? (
            <nav aria-label="Pagination">
              <Link href={nextHref} className="text-sm font-medium underline underline-offset-4 hover:no-underline">
                Next page
              </Link>
            </nav>
          ) : null}
        </>
      )}
    </section>
  );
}
