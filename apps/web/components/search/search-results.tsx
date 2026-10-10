"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type { components } from "@/lib/api-client/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/components/dashboard/format";

type SearchResponse = components["schemas"]["SearchResponse"];
type SearchItemModel = components["schemas"]["SearchItemModel"];

interface SearchResultsProps {
  response: SearchResponse;
  limit?: number;
  offset?: number;
}

const AUTHORITY_LABELS: Record<number, { label: string; variant: "default" | "secondary" | "outline" }> = {
  1: { label: "Statute / Primary", variant: "default" },
  2: { label: "Rules / Subordinate", variant: "secondary" },
  3: { label: "Notification", variant: "secondary" },
  4: { label: "Circular", variant: "outline" },
  5: { label: "Judicial Ruling", variant: "outline" },
};

function safeSnippetHtml(snippet: string): { __html: string } {
  // Escape all HTML characters first to ensure safe rendering, then restore <mark> highlights
  const escaped = snippet
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const restored = escaped
    .replace(/&lt;mark&gt;/g, "<mark class='bg-yellow-200 dark:bg-yellow-800 text-yellow-900 dark:text-yellow-100 px-1 py-0.5 rounded font-medium'>")
    .replace(/&lt;\/mark&gt;/g, "</mark>");
  return { __html: restored };
}

function getItemLink(item: SearchItemModel): string {
  if (item.chunk_kind === "provision" || item.heading_path) {
    const parts = item.doc_canonical_id.split(":");
    const instCode = parts[1] || "CGST_ACT";
    if (item.provision_version_id) {
      return `/baseline/${instCode}?p=${item.provision_version_id}`;
    }
    return `/baseline/${instCode}`;
  }
  return `/documents/${item.document_id}`;
}

export function SearchResults({ response, limit = 20, offset = 0 }: SearchResultsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const total = response.total_count ?? 0;
  const items = response.items ?? [];
  const startIdx = total === 0 ? 0 : offset + 1;
  const endIdx = Math.min(offset + limit, total);

  const goToOffset = (newOffset: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("offset", newOffset.toString());
    router.push(`/search?${params.toString()}`);
  };

  return (
    <div className="space-y-4" data-testid="search-results">
      {/* Header and Expansion info */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <div>
            Showing <span className="font-medium text-foreground">{startIdx}-{endIdx}</span> of{" "}
            <span className="font-medium text-foreground">{total}</span> results for &ldquo;
            <span className="font-semibold text-foreground">{response.query}</span>&rdquo; as of{" "}
            <span className="font-medium text-foreground">{formatDate(response.as_on)}</span>
          </div>
        </div>

        {/* Query expansion banner */}
        {response.expanded_terms && response.expanded_terms.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground bg-muted/60 px-3 py-1.5 rounded-md">
            <span>Also expanded to:</span>
            {response.expanded_terms.map((term) => (
              <Badge key={term} variant="outline" className="text-[11px] font-normal">
                {term}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Empty State */}
      {items.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center space-y-2">
          <p className="font-medium text-foreground">No documents found matching your search</p>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Try broadening your search query, using legal citations directly (e.g. s.16(2)(c)),
            removing filters, or adjusting the as-on date.
          </p>
        </div>
      )}

      {/* Results List */}
      <div className="space-y-3">
        {items.map((item) => {
          const authority = AUTHORITY_LABELS[item.authority_rank] || {
            label: `Authority ${item.authority_rank}`,
            variant: "outline",
          };
          const link = getItemLink(item);

          return (
            <div
              key={item.chunk_id}
              className="flex flex-col gap-2 rounded-lg border bg-card p-4 transition-colors hover:border-foreground/30 shadow-sm"
              data-testid="search-result-card"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="space-y-0.5">
                  <Link
                    href={link}
                    className="text-base font-semibold text-foreground hover:underline"
                  >
                    {item.doc_title}
                  </Link>
                  {item.heading_path && (
                    <div className="text-xs font-mono text-muted-foreground">
                      {item.heading_path}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <Badge variant={authority.variant} className="text-[10px]">
                    {authority.label}
                  </Badge>
                  <Badge variant="outline" className="font-mono uppercase text-[10px]">
                    {item.doc_type}
                  </Badge>
                  {item.court_level && (
                    <Badge variant="secondary" className="text-[10px]">
                      {item.court_level}
                    </Badge>
                  )}
                </div>
              </div>

              {/* Snippet */}
              <div
                className="text-sm text-foreground/90 leading-relaxed font-normal"
                dangerouslySetInnerHTML={safeSnippetHtml(item.snippet)}
              />

              {/* Card Footer */}
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground pt-1 border-t">
                <span className="font-mono text-[11px]">{item.doc_canonical_id}</span>
                <div className="flex items-center gap-3">
                  {item.passage_count > 1 && (
                    <span className="text-primary font-medium">
                      +{item.passage_count - 1} other matching {item.passage_count - 1 === 1 ? "passage" : "passages"}
                    </span>
                  )}
                  <span className="text-muted-foreground/70">
                    Score: {item.score.toFixed(3)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Pagination Controls */}
      {total > limit && (
        <div className="flex items-center justify-between border-t pt-4">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={offset <= 0}
            onClick={() => goToOffset(Math.max(0, offset - limit))}
          >
            &larr; Previous
          </Button>
          <span className="text-xs text-muted-foreground">
            Page {Math.floor(offset / limit) + 1} of {Math.ceil(total / limit)}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={offset + limit >= total}
            onClick={() => goToOffset(offset + limit)}
          >
            Next &rarr;
          </Button>
        </div>
      )}
    </div>
  );
}
