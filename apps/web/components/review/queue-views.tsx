import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { QUEUE_KINDS, QUEUE_TABS, queueHref, type QueueKind, type QueueTab } from "./queue-links";
import { kindLabel } from "./format";

interface QueueViewsProps {
  tab: QueueTab;
  kind?: QueueKind;
}

const SELECT_CLASS =
  "flex h-10 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/** Tabs for the queue views, and a kind filter. The filter is a plain GET form that keeps the tab. */
export function QueueViews({ tab, kind }: QueueViewsProps) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <nav aria-label="Queue views">
        <ul className="flex flex-wrap gap-1">
          {QUEUE_TABS.map((item) => {
            const active = item.id === tab;
            return (
              <li key={item.id}>
                <Link
                  href={queueHref({ tab: item.id, kind })}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-block rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "bg-accent text-accent-foreground" : "text-muted-foreground",
                  )}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <form method="get" action="/queue" className="flex flex-wrap items-end gap-2">
        <input type="hidden" name="tab" value={tab} />
        <div className="space-y-1">
          <Label htmlFor="kind-filter">Kind</Label>
          <select id="kind-filter" name="kind" defaultValue={kind ?? ""} className={SELECT_CLASS}>
            <option value="">All kinds</option>
            {QUEUE_KINDS.map((option) => (
              <option key={option} value={option}>
                {kindLabel(option)}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" variant="outline">
          Apply filter
        </Button>
      </form>
    </div>
  );
}
