"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { parseWordDiff } from "@/components/review/amendment-section";
import type { components } from "@/lib/api-client/schema";

export type ProvisionTimelineItem = components["schemas"]["ProvisionTimelineItem"];
export type ProvisionDiffResponse = components["schemas"]["ProvisionDiffResponse"];

interface ProvisionTimelineProps {
  provisionId: string;
  items: ProvisionTimelineItem[];
}

export function ProvisionTimeline({ provisionId, items }: ProvisionTimelineProps) {
  const [openDiffIndex, setOpenDiffIndex] = useState<number | null>(null);
  const [diffLoading, setDiffLoading] = useState<boolean>(false);
  const [diffData, setDiffData] = useState<Record<number, ProvisionDiffResponse>>({});
  const [diffError, setDiffError] = useState<string | null>(null);

  async function toggleDiff(index: number) {
    if (openDiffIndex === index) {
      setOpenDiffIndex(null);
      return;
    }

    if (diffData[index]) {
      setOpenDiffIndex(index);
      return;
    }

    const prevItem = items[index - 1];
    const currItem = items[index];
    if (!prevItem || !currItem) return;

    setDiffLoading(true);
    setDiffError(null);
    try {
      const res = await fetch(
        `/api/provisions/${provisionId}/diff?from_version_id=${prevItem.version_id}&to_version_id=${currItem.version_id}`
      );
      if (!res.ok) {
        throw new Error(`Failed to load diff (HTTP ${res.status})`);
      }
      const data: ProvisionDiffResponse = await res.json();
      setDiffData((prev) => ({ ...prev, [index]: data }));
      setOpenDiffIndex(index);
    } catch (err) {
      setDiffError(err instanceof Error ? err.message : "Error loading diff");
      setOpenDiffIndex(index);
    } finally {
      setDiffLoading(false);
    }
  }

  if (!items || items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground p-4 border border-dashed rounded-md">
        No version history available for this provision.
      </p>
    );
  }

  return (
    <div className="space-y-4" aria-label="Provision version timeline">
      <div className="relative pl-6 after:absolute after:inset-y-0 after:left-2 after:w-0.5 after:bg-border space-y-6">
        {items.map((item, index) => {
          const isLatest = index === items.length - 1;
          const hasPrev = index > 0;
          const isOpen = openDiffIndex === index;
          const diff = diffData[index];

          return (
            <div key={item.version_id} className="relative space-y-2">
              {/* Dot on timeline */}
              <div
                className={`absolute -left-6 top-1.5 h-2.5 w-2.5 rounded-full border-2 bg-background ${
                  isLatest ? "border-primary bg-primary" : "border-muted-foreground"
                }`}
              />

              <div className="rounded-lg border bg-card p-4 text-card-foreground shadow-sm space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-sm">
                      {item.heading || `Version ${index + 1}`}
                    </span>
                    <Badge variant={item.origin === "baseline" ? "secondary" : "default"}>
                      {item.origin}
                    </Badge>
                    {isLatest && <Badge variant="outline">Current</Badge>}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    Valid: {item.valid_from} {item.valid_to ? `to ${item.valid_to}` : "onwards"}
                  </span>
                </div>

                {item.amending_document && (
                  <div className="text-xs rounded bg-muted/50 p-2 text-muted-foreground">
                    <span className="font-medium text-foreground">Introduced by: </span>
                    {item.amending_document.number || item.amending_document.title || "Notification"}
                    {item.amending_document.doc_date && ` (${item.amending_document.doc_date})`}
                  </div>
                )}

                <div className="text-xs text-muted-foreground line-clamp-3 font-mono bg-muted/30 p-2 rounded">
                  {item.text_preview}
                  {item.text_chars > 200 && "..."}
                </div>

                {hasPrev && (
                  <div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleDiff(index)}
                      disabled={diffLoading && openDiffIndex === null}
                      className="text-xs h-7 px-2"
                    >
                      {isOpen ? "Hide diff" : "Compare with previous version"}
                    </Button>
                  </div>
                )}

                {isOpen && (
                  <div className="mt-2 rounded border bg-muted/30 p-3 text-xs font-mono space-y-2">
                    <span className="font-semibold text-foreground">
                      Changes vs previous version:
                    </span>
                    {diffLoading && !diff ? (
                      <p className="text-muted-foreground">Loading diff...</p>
                    ) : diffError ? (
                      <p className="text-destructive">{diffError}</p>
                    ) : diff ? (
                      diff.identical ? (
                        <p className="text-muted-foreground italic">Versions are identical.</p>
                      ) : (
                        <div className="leading-relaxed whitespace-pre-wrap break-words">
                          {parseWordDiff(diff.diff).map((token, tIdx) => {
                            if (token.type === "delete") {
                              return (
                                <del
                                  key={tIdx}
                                  className="bg-rose-100 text-rose-900 line-through dark:bg-rose-950/60 dark:text-rose-200 px-0.5 rounded"
                                >
                                  {token.text}
                                </del>
                              );
                            }
                            if (token.type === "insert") {
                              return (
                                <ins
                                  key={tIdx}
                                  className="bg-emerald-100 text-emerald-900 no-underline font-semibold dark:bg-emerald-950/60 dark:text-emerald-200 px-0.5 rounded"
                                >
                                  {token.text}
                                </ins>
                              );
                            }
                            return (
                              <span key={tIdx} className="text-foreground">
                                {token.text}
                              </span>
                            );
                          })}
                        </div>
                      )
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
