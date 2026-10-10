"use client";

import Link from "next/link";
import { useState } from "react";
import type { components } from "@/lib/api-client/schema";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/components/dashboard/format";

type LinkedDocumentItem = components["schemas"]["LinkedDocumentItem"];
type ProvisionLinkedResponse = components["schemas"]["ProvisionLinkedResponse"];

interface ProvisionLinkedProps {
  linked: ProvisionLinkedResponse;
}

const CATEGORY_LABELS: Record<string, string> = {
  amending_instruments: "Amending Instruments",
  issued_under: "Issued Under",
  circulars: "Clarifying Circulars",
  judgements: "Interpreting Judgements",
  mentions: "Mentions & Citations",
  other: "Other Linked Documents",
};

export function ProvisionLinked({ linked }: ProvisionLinkedProps) {
  const [activeTab, setActiveTab] = useState<string>("all");

  const groups = linked.groups ?? {};
  const totalCount = linked.total_count ?? 0;

  // Gather all items across groups
  const allItems: { item: LinkedDocumentItem; groupKey: string }[] = [];
  for (const [groupKey, items] of Object.entries(groups)) {
    for (const item of items) {
      allItems.push({ item, groupKey });
    }
  }

  const groupKeys = Object.keys(groups).filter(
    (key) => (groups[key]?.length ?? 0) > 0
  );

  const displayedItems =
    activeTab === "all"
      ? allItems
      : (groups[activeTab] ?? []).map((item) => ({ item, groupKey: activeTab }));

  if (totalCount === 0) {
    return (
      <div className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
        No linked instruments or citations recorded for this provision.
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="provision-linked-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">Linked Resources</h3>
          <Badge variant="secondary" className="text-xs">
            {totalCount}
          </Badge>
        </div>
      </div>

      {/* Category filter tabs */}
      <div className="flex flex-wrap gap-1.5 border-b pb-2 text-xs">
        <button
          type="button"
          onClick={() => setActiveTab("all")}
          className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
            activeTab === "all"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
          }`}
        >
          All ({totalCount})
        </button>
        {groupKeys.map((key) => {
          const count = groups[key]?.length ?? 0;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                activeTab === key
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
            >
              {CATEGORY_LABELS[key] || key} ({count})
            </button>
          );
        })}
      </div>

      {/* List of linked documents */}
      <div className="space-y-2">
        {displayedItems.map(({ item }) => (
          <div
            key={item.link_id}
            className="flex flex-col gap-1.5 rounded-md border p-3 text-sm hover:border-foreground/30 transition-colors"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Link
                href={`/documents/${item.document_id}`}
                className="font-medium text-foreground hover:underline"
              >
                {item.title}
              </Link>
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <Badge variant="outline" className="font-mono uppercase text-[10px]">
                  {item.doc_type}
                </Badge>
                <Badge variant="secondary" className="capitalize text-[10px]">
                  {item.link_type}
                </Badge>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span className="font-mono">{item.canonical_id}</span>
              {item.doc_date && <span>Doc Date: {formatDate(item.doc_date)}</span>}
              {item.in_force_date && <span>In Force: {formatDate(item.in_force_date)}</span>}
              {item.confidence < 1.0 && (
                <span>Confidence: {Math.round(item.confidence * 100)}%</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
