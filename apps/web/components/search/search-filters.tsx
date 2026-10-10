"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface SearchFiltersProps {
  selectedTypes: string[];
  selectedCourt?: string;
  selectedState?: string;
  dateFrom?: string;
  dateTo?: string;
  groups: Record<string, number>;
}

const DOC_TYPES = [
  { key: "act", label: "Primary Acts / Statutes" },
  { key: "rule", label: "Subordinate Rules" },
  { key: "notification", label: "Notifications" },
  { key: "circular", label: "Circulars & Clarifications" },
  { key: "order", label: "Orders" },
  { key: "judgement", label: "Judgements / Rulings" },
];

const COURT_LEVELS = [
  { key: "SC", label: "Supreme Court" },
  { key: "HC", label: "High Court" },
  { key: "Tribunal", label: "CESTAT / GSTAT" },
  { key: "AAR", label: "Advance Ruling (AAR)" },
  { key: "AAAR", label: "Appellate AAR" },
];

export function SearchFilters({
  selectedTypes,
  selectedCourt = "",
  selectedState = "",
  dateFrom = "",
  dateTo = "",
  groups,
}: SearchFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const updateParam = (key: string, value: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    params.delete("offset"); // reset pagination on filter change
    router.push(`/search?${params.toString()}`);
  };

  const toggleType = (typeKey: string) => {
    const params = new URLSearchParams(searchParams.toString());
    let currentTypes = params.getAll("types");
    // Handle comma-separated format if any
    if (currentTypes.length === 1 && currentTypes[0].includes(",")) {
      currentTypes = currentTypes[0].split(",");
    }

    let updated: string[];
    if (currentTypes.includes(typeKey)) {
      updated = currentTypes.filter((t) => t !== typeKey);
    } else {
      updated = [...currentTypes, typeKey];
    }

    params.delete("types");
    for (const t of updated) {
      params.append("types", t);
    }
    params.delete("offset");
    router.push(`/search?${params.toString()}`);
  };

  const clearFilters = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("types");
    params.delete("court");
    params.delete("state");
    params.delete("date_from");
    params.delete("date_to");
    params.delete("offset");
    router.push(`/search?${params.toString()}`);
  };

  const hasActiveFilters =
    selectedTypes.length > 0 ||
    Boolean(selectedCourt) ||
    Boolean(selectedState) ||
    Boolean(dateFrom) ||
    Boolean(dateTo);

  return (
    <div className="space-y-6 rounded-lg border bg-card p-4 text-sm" data-testid="search-filters">
      <div className="flex items-center justify-between border-b pb-3">
        <h3 className="font-semibold text-foreground">Filters</h3>
        {hasActiveFilters && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearFilters}
            className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
          >
            Clear all
          </Button>
        )}
      </div>

      {/* Document Types */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Document Type
        </h4>
        <div className="space-y-1.5">
          {DOC_TYPES.map(({ key, label }) => {
            const isChecked = selectedTypes.includes(key);
            const count = groups[key] ?? 0;
            return (
              <label
                key={key}
                className="flex items-center justify-between gap-2 cursor-pointer rounded px-1.5 py-1 hover:bg-muted select-none"
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggleType(key)}
                    className="rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <span>{label}</span>
                </div>
                {count > 0 && (
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
                    {count}
                  </Badge>
                )}
              </label>
            );
          })}
        </div>
      </div>

      {/* Court Level */}
      <div className="space-y-2 border-t pt-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Court / Forum
        </h4>
        <select
          value={selectedCourt}
          onChange={(e) => updateParam("court", e.target.value || null)}
          className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
          aria-label="Court level filter"
        >
          <option value="">All Courts / Levels</option>
          {COURT_LEVELS.map(({ key, label }) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {/* State Filter */}
      <div className="space-y-2 border-t pt-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          State Code
        </h4>
        <Input
          type="text"
          placeholder="e.g. MH, DL, KA"
          value={selectedState}
          onChange={(e) => updateParam("state", e.target.value ? e.target.value.toUpperCase() : null)}
          className="h-8 text-xs font-mono uppercase"
          maxLength={5}
          aria-label="State filter"
        />
      </div>

      {/* Date Range */}
      <div className="space-y-2 border-t pt-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Document Date
        </h4>
        <div className="grid gap-2">
          <div>
            <span className="text-[10px] text-muted-foreground">From:</span>
            <Input
              type="date"
              value={dateFrom}
              onChange={(e) => updateParam("date_from", e.target.value || null)}
              className="h-8 text-xs"
              aria-label="Filter from date"
            />
          </div>
          <div>
            <span className="text-[10px] text-muted-foreground">To:</span>
            <Input
              type="date"
              value={dateTo}
              onChange={(e) => updateParam("date_to", e.target.value || null)}
              className="h-8 text-xs"
              aria-label="Filter to date"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
