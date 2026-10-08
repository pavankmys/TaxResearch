import { formatDateTime, formatHours } from "@/components/dashboard/format";
import { SourceToggle } from "@/components/ingest/source-toggle";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export interface SourceRow {
  code: string;
  enabled: boolean;
  expected_cadence_hours: number | null;
  last_success_at: string | null;
  in_config: boolean;
}

/**
 * Sources with their enable flag and last success. Only platform admins get the toggle column;
 * for everyone else the table is read-only and has no controls.
 */
export function SourcesTable({ rows, isAdmin }: { rows: readonly SourceRow[]; isAdmin: boolean }) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">Sources</caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Source</TableHead>
          <TableHead scope="col">Enabled</TableHead>
          <TableHead scope="col">Cadence</TableHead>
          <TableHead scope="col">Last success</TableHead>
          {isAdmin ? <TableHead scope="col">Change</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 ? (
          <TableRow>
            <TableCell colSpan={isAdmin ? 5 : 4} className="text-muted-foreground">
              No sources configured.
            </TableCell>
          </TableRow>
        ) : null}
        {rows.map((row) => (
          <TableRow key={row.code}>
            <TableCell className="font-mono text-xs">
              {row.code}
              {row.in_config ? null : <Badge variant="outline" className="ml-2">Not in config</Badge>}
            </TableCell>
            <TableCell>{row.enabled ? "Enabled" : "Disabled"}</TableCell>
            <TableCell className="tabular-nums">
              {row.expected_cadence_hours === null ? "Not set" : formatHours(row.expected_cadence_hours)}
            </TableCell>
            <TableCell>{formatDateTime(row.last_success_at)}</TableCell>
            {isAdmin ? (
              <TableCell>
                <SourceToggle code={row.code} enabled={row.enabled} />
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
