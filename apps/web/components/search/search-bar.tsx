"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export interface CitationMatch {
  matched: boolean;
  kind?: string | null;
  canonical_id?: string | null;
  entity_id?: string | null;
  title?: string | null;
  confidence?: number;
}

interface SearchBarProps {
  initialQuery?: string;
  initialAsOn?: string;
  initialExpand?: boolean;
  initialCitationMatch?: CitationMatch | null;
}

export function SearchBar({
  initialQuery = "",
  initialAsOn = "",
  initialExpand = true,
  initialCitationMatch = null,
}: SearchBarProps) {
  const router = useRouter();
  const [query, setQuery] = useState(initialQuery);
  const [asOn, setAsOn] = useState(initialAsOn);
  const [expand, setExpand] = useState(initialExpand);
  const [citation, setCitation] = useState<CitationMatch | null>(initialCitationMatch);
  const [resolving, setResolving] = useState(false);

  // Debounced citation detection for client-side typing
  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed || trimmed.length < 3) {
      setCitation(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        setResolving(true);
        const res = await fetch(`/api/resolve?q=${encodeURIComponent(trimmed)}`);
        if (res.ok) {
          const data: CitationMatch = await res.json();
          if (data && data.matched) {
            setCitation(data);
          } else {
            setCitation(null);
          }
        }
      } catch {
        // Ignore background resolution errors
      } finally {
        setResolving(false);
      }
    }, 400);

    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="space-y-3" data-testid="search-bar">
      <form
        method="GET"
        action="/search"
        className="flex flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm"
      >
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Input
              type="text"
              name="q"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search legal provisions, notifications, circulars, or enter citations (e.g. s.16(2)(c), Notf 11/2017)..."
              className="w-full text-base"
              aria-label="Search query"
              autoComplete="off"
            />
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <label htmlFor="as_on_input" className="text-xs font-medium text-muted-foreground whitespace-nowrap">
                As-on:
              </label>
              <Input
                id="as_on_input"
                type="date"
                name="as_on"
                value={asOn}
                onChange={(e) => setAsOn(e.target.value)}
                className="w-36 text-xs"
                aria-label="As-on date"
              />
            </div>
            <Button type="submit" className="px-5">
              Search
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground pt-1 border-t">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              name="expand"
              value="true"
              checked={expand}
              onChange={(e) => setExpand(e.target.checked)}
              className="rounded border-gray-300 text-primary focus:ring-primary"
            />
            <span>Enable synonym & acronym expansion (e.g. ITC → Input Tax Credit)</span>
          </label>
          {resolving && <span className="italic">Detecting citation...</span>}
        </div>
      </form>

      {/* Real-time Citation Match Suggestion Banner */}
      {citation && citation.matched && (
        <div
          data-testid="citation-banner"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm text-foreground"
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-primary">Citation Detected:</span>
            <span className="font-medium">{citation.title || citation.canonical_id}</span>
            {citation.canonical_id && (
              <Badge variant="outline" className="font-mono text-xs">
                {citation.canonical_id}
              </Badge>
            )}
            {citation.confidence && (
              <span className="text-xs text-muted-foreground">
                ({Math.round(citation.confidence * 100)}% match)
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {citation.kind === "provision" && citation.canonical_id ? (
              <Button
                type="button"
                size="sm"
                variant="default"
                onClick={() => {
                  const parts = citation.canonical_id?.split(":") || [];
                  const inst = parts[1] || "CGST_ACT";
                  const provId = citation.entity_id;
                  if (provId) {
                    router.push(`/baseline/${inst}?p=${provId}`);
                  } else {
                    router.push(`/baseline/${inst}`);
                  }
                }}
              >
                Jump to Provision &rarr;
              </Button>
            ) : citation.entity_id ? (
              <Button
                type="button"
                size="sm"
                variant="default"
                onClick={() => router.push(`/documents/${citation.entity_id}`)}
              >
                View Document &rarr;
              </Button>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
