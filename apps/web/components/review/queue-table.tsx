import Link from "next/link";

import type { components } from "@/lib/api-client/schema";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatAge, formatDateTimeUtc, isOverdue, kindLabel } from "./format";

type ReviewTaskItem = components["schemas"]["ReviewTaskItem"];

const OPEN_STATUSES = new Set(["open", "in_review"]);

interface QueueTableProps {
  items: ReviewTaskItem[];
  now: number;
}

/** The review queue. Priority 1 is most urgent. Age and SLA are relative to `now`. */
export function QueueTable({ items, now }: QueueTableProps) {
  return (
    <Table>
      <caption className="sr-only">Review tasks, most urgent and oldest first</caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Priority</TableHead>
          <TableHead scope="col">Kind</TableHead>
          <TableHead scope="col">Title</TableHead>
          <TableHead scope="col">Assignee</TableHead>
          <TableHead scope="col">Age</TableHead>
          <TableHead scope="col">SLA</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((task) => {
          const overdue = OPEN_STATUSES.has(task.status) && isOverdue(task.sla_due_at, now);
          return (
            <TableRow key={task.id}>
              <TableCell>
                <Badge variant={task.priority <= 2 ? "destructive" : "secondary"}>
                  P{task.priority}
                  <span className="sr-only"> priority</span>
                </Badge>
              </TableCell>
              <TableCell>{kindLabel(task.kind)}</TableCell>
              <TableCell className="max-w-md">
                <Link
                  href={`/queue/${task.id}`}
                  className="font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {task.title ?? "Untitled task"}
                </Link>
              </TableCell>
              <TableCell>
                {task.assignee_name ?? <span className="text-muted-foreground">Unassigned</span>}
              </TableCell>
              <TableCell className="whitespace-nowrap">{formatAge(task.opened_at, now)}</TableCell>
              <TableCell className="whitespace-nowrap">
                {task.sla_due_at === null ? (
                  <span className="text-muted-foreground">None</span>
                ) : (
                  <span className="flex flex-wrap items-center gap-2">
                    {formatDateTimeUtc(task.sla_due_at)}
                    {overdue ? <Badge variant="destructive">Overdue</Badge> : null}
                  </span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
