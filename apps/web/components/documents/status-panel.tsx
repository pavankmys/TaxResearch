import { StatusChangeForm } from "@/components/documents/status-change-form";
import { StatusBadge } from "@/components/documents/badges";
import { formatDate, formatDateTime } from "@/components/dashboard/format";
import type { DocumentDetail } from "@/components/documents/types";
import { STATUS_LABELS } from "@/components/documents/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

/** The status tab: the current status, its history, and the change form. */
export function StatusPanel({ doc }: { doc: DocumentDetail }) {
  const history = [...doc.status_history].reverse();
  return (
    <div className="space-y-8">
      <section aria-labelledby="current-status" className="space-y-3">
        <h2 id="current-status" className="text-lg font-semibold">
          Current status
        </h2>
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span>Status:</span>
          <StatusBadge status={doc.status} />
        </p>
      </section>

      <section aria-labelledby="status-history" className="space-y-3">
        <h2 id="status-history" className="text-lg font-semibold">
          Status history
        </h2>
        <Table>
          <caption className="sr-only">Status history, newest first</caption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Status</TableHead>
              <TableHead scope="col">Valid from</TableHead>
              <TableHead scope="col">Valid to</TableHead>
              <TableHead scope="col">Recorded</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {history.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground">
                  No status history yet.
                </TableCell>
              </TableRow>
            ) : null}
            {history.map((event) => (
              <TableRow key={`${event.status}-${event.valid_from}-${event.created_at}`}>
                <TableCell>{STATUS_LABELS[event.status as keyof typeof STATUS_LABELS] ?? event.status}</TableCell>
                <TableCell>{formatDate(event.valid_from)}</TableCell>
                <TableCell>{event.valid_to ? formatDate(event.valid_to) : "Current"}</TableCell>
                <TableCell>{formatDateTime(event.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section aria-labelledby="change-status" className="space-y-3">
        <h2 id="change-status" className="text-lg font-semibold">
          Change status
        </h2>
        <StatusChangeForm documentId={doc.id} currentStatus={doc.status} />
      </section>
    </div>
  );
}
