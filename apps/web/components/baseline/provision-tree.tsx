import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { provisionFlags, rowLabel } from "@/components/baseline/tree";
import type { ProvisionRow } from "@/components/baseline/types";

/** Map depth to padding class. Capped at depth 5. */
const DEPTH_PADDING: Record<number, string> = {
  0: "pl-0",
  1: "pl-4",
  2: "pl-8",
  3: "pl-12",
  4: "pl-16",
  5: "pl-20",
};

function getPaddingClass(depth: number): string {
  const capped = Math.min(depth, 5);
  return DEPTH_PADDING[capped] || DEPTH_PADDING[5];
}

interface ProvisionTreeProps {
  items: ProvisionRow[];
  instrumentCode: string;
  selectedId?: string;
}

/** Renders a flat tree-ordered list of provisions with indentation, selection, and flags. */
export function ProvisionTree({ items, instrumentCode, selectedId }: ProvisionTreeProps) {
  const label = `Provisions tree for ${instrumentCode}`;
  const isSelected = (id: string) => id === selectedId;

  return (
    <nav aria-label={label} className="max-h-[70vh] overflow-auto rounded border">
      <ul className="divide-y">
        {items.map((row) => {
          const flags = provisionFlags(row);
          const href = `/baseline/${instrumentCode}?p=${row.id}`;
          const selected = isSelected(row.id);

          return (
            <li key={row.id}>
              <Link
                href={href}
                className={`block p-2 text-sm hover:bg-muted ${
                  selected ? "bg-muted" : ""
                }`}
                aria-current={selected ? "page" : undefined}
              >
                <div className={getPaddingClass(row.depth)}>
                  <div className="flex items-baseline gap-2">
                    <span className="font-medium">{rowLabel(row)}</span>
                    {row.heading && (
                      <span className="truncate text-xs text-muted-foreground">
                        {row.heading}
                      </span>
                    )}
                  </div>
                  {flags.length > 0 && (
                    <div className="mt-1">
                      <Badge variant="destructive" className="text-xs">
                        {flags[0]}
                      </Badge>
                    </div>
                  )}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
