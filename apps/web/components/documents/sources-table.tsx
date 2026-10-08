import { formatDateTime } from "@/components/dashboard/format";
import type { components } from "@/lib/api-client/schema";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type SourceLink = components["schemas"]["SourceLinkOut"];

export function SourcesTable({ links }: { links: readonly SourceLink[] }) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Where this document was seen
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Source</TableHead>
          <TableHead scope="col">URL</TableHead>
          <TableHead scope="col">First seen</TableHead>
          <TableHead scope="col">Last seen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {links.length === 0 ? (
          <TableRow>
            <TableCell colSpan={4} className="text-muted-foreground">
              No sources recorded.
            </TableCell>
          </TableRow>
        ) : null}
        {links.map((link) => (
          <TableRow key={`${link.source_code}-${link.url}`}>
            <TableCell className="font-mono text-xs">{link.source_code}</TableCell>
            <TableCell className="break-all font-mono text-xs">{link.url}</TableCell>
            <TableCell>{formatDateTime(link.first_seen_at)}</TableCell>
            <TableCell>{formatDateTime(link.last_seen_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
