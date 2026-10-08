import { formatCount, formatDateTime, formatHours, formatMinutes } from "@/components/dashboard/format";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface DailyTableRow {
  source_code: string | null;
  day: string;
  discovered: number;
  done: number;
  failed: number;
  skipped: number;
  running: number;
  queued: number;
}

export interface SourceHealthTableRow {
  code: string;
  enabled: boolean;
  expected_cadence_hours: number | null;
  last_success_at: string | null;
  last_new_doc_at: string | null;
  hours_since_new_doc: number | null;
  stale: boolean;
}

export interface ReviewQueueTableRow {
  kind: string;
  status: string;
  count: number;
  oldest_opened_at: string | null;
  overdue_count: number;
}

export interface QueueLagTableRow {
  queue: string;
  queued: number;
  oldest_run_after: string | null;
  lag_minutes: number;
}

export function DailyCountsTable({ rows }: { rows: readonly DailyTableRow[] }) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Documents per source and day, last 7 days (UTC)
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Day</TableHead>
          <TableHead scope="col">Source</TableHead>
          <TableHead scope="col" className="text-right">Discovered</TableHead>
          <TableHead scope="col" className="text-right">Done</TableHead>
          <TableHead scope="col" className="text-right">Failed</TableHead>
          <TableHead scope="col" className="text-right">Skipped</TableHead>
          <TableHead scope="col" className="text-right">Running</TableHead>
          <TableHead scope="col" className="text-right">Queued</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={8} className="text-muted-foreground">
              No documents discovered in the last 7 days.
            </TableCell>
          </TableRow>
        ) : null}
        {rows.map((row) => (
          <TableRow key={`${row.day}-${row.source_code ?? ""}`}>
            <TableCell>{row.day.slice(0, 10)}</TableCell>
            <TableCell className="font-mono text-xs">{row.source_code ?? "All"}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.discovered)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.done)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.failed)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.skipped)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.running)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.queued)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function SourceHealthTable({ rows }: { rows: readonly SourceHealthTableRow[] }) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Source health against the expected cadence
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Source</TableHead>
          <TableHead scope="col">Enabled</TableHead>
          <TableHead scope="col" className="text-right">Cadence</TableHead>
          <TableHead scope="col">Last success</TableHead>
          <TableHead scope="col">Last new document</TableHead>
          <TableHead scope="col" className="text-right">Since new document</TableHead>
          <TableHead scope="col">Health</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.code}>
            <TableCell className="font-mono text-xs">{row.code}</TableCell>
            <TableCell>{row.enabled ? "Yes" : "No"}</TableCell>
            <TableCell className="text-right tabular-nums">
              {row.expected_cadence_hours === null ? "Not set" : formatHours(row.expected_cadence_hours)}
            </TableCell>
            <TableCell>{formatDateTime(row.last_success_at)}</TableCell>
            <TableCell>{formatDateTime(row.last_new_doc_at)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatHours(row.hours_since_new_doc)}</TableCell>
            <TableCell>
              {row.stale ? (
                <Badge variant="destructive">Stale</Badge>
              ) : (
                <Badge variant="outline">Current</Badge>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ReviewQueueTable({ rows }: { rows: readonly ReviewQueueTableRow[] }) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Review tasks by kind and status
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Kind</TableHead>
          <TableHead scope="col">Status</TableHead>
          <TableHead scope="col" className="text-right">Count</TableHead>
          <TableHead scope="col">Oldest opened</TableHead>
          <TableHead scope="col" className="text-right">Past SLA</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={5} className="text-muted-foreground">
              No review tasks.
            </TableCell>
          </TableRow>
        ) : null}
        {rows.map((row) => (
          <TableRow key={`${row.kind}-${row.status}`}>
            <TableCell className="font-mono text-xs">{row.kind}</TableCell>
            <TableCell>{row.status}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.count)}</TableCell>
            <TableCell>{formatDateTime(row.oldest_opened_at)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.overdue_count)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function QueueLagTable({ rows }: { rows: readonly QueueLagTableRow[] }) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Job queues: queued jobs and lag
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Queue</TableHead>
          <TableHead scope="col" className="text-right">Queued</TableHead>
          <TableHead scope="col">Oldest due</TableHead>
          <TableHead scope="col" className="text-right">Lag</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={4} className="text-muted-foreground">
              No queued jobs.
            </TableCell>
          </TableRow>
        ) : null}
        {rows.map((row) => (
          <TableRow key={row.queue}>
            <TableCell className="font-mono text-xs">{row.queue}</TableCell>
            <TableCell className="text-right tabular-nums">{formatCount(row.queued)}</TableCell>
            <TableCell>{formatDateTime(row.oldest_run_after)}</TableCell>
            <TableCell className="text-right tabular-nums">{formatMinutes(row.lag_minutes)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
