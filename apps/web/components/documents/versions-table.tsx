import Link from "next/link";

import { formatDateTime } from "@/components/dashboard/format";
import type { VersionOut } from "@/components/documents/types";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface VersionsTableProps {
  documentId: string;
  versions: readonly VersionOut[];
  currentVersionId: string | null;
}

export function VersionsTable({ documentId, versions, currentVersionId }: VersionsTableProps) {
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Versions of this document, oldest first
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Version</TableHead>
          <TableHead scope="col">Format</TableHead>
          <TableHead scope="col" className="text-right">Pages</TableHead>
          <TableHead scope="col">Parsed</TableHead>
          <TableHead scope="col">Parser</TableHead>
          <TableHead scope="col">Segmenter</TableHead>
          <TableHead scope="col">Extractor</TableHead>
          <TableHead scope="col">OCR</TableHead>
          <TableHead scope="col">Files</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {versions.length === 0 ? (
          <TableRow>
            <TableCell colSpan={9} className="text-muted-foreground">
              No versions yet.
            </TableCell>
          </TableRow>
        ) : null}
        {versions.map((version) => {
          const isPdf = version.mime === "application/pdf";
          return (
            <TableRow key={version.id}>
              <TableCell>
                {version.version_no}
                {version.id === currentVersionId ? <span className="ml-2 text-xs text-muted-foreground">(current)</span> : null}
              </TableCell>
              <TableCell className="font-mono text-xs">{version.mime}</TableCell>
              <TableCell className="text-right tabular-nums">{version.page_count ?? "—"}</TableCell>
              <TableCell>{formatDateTime(version.parsed_at)}</TableCell>
              <TableCell className="font-mono text-xs">{version.parser_version ?? "—"}</TableCell>
              <TableCell className="font-mono text-xs">{version.segmenter_version ?? "—"}</TableCell>
              <TableCell className="font-mono text-xs">{version.extractor_version ?? "—"}</TableCell>
              <TableCell>{version.ocr_used ? "Yes" : "No"}</TableCell>
              <TableCell>
                <div className="flex flex-col gap-1">
                  <a
                    href={`/api/files/raw/${documentId}/${version.id}`}
                    className="text-sm underline underline-offset-4 hover:no-underline"
                  >
                    Open original
                  </a>
                  {isPdf ? (
                    <Link
                      href={`/documents/${documentId}?tab=pages&version=${version.id}`}
                      className="text-sm underline underline-offset-4 hover:no-underline"
                    >
                      Pages
                    </Link>
                  ) : (
                    <span className="text-xs text-muted-foreground">No page images</span>
                  )}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
