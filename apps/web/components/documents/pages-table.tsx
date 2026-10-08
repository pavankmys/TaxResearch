import { formatCount } from "@/components/dashboard/format";
import type { PageOut } from "@/components/documents/types";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface PagesTableProps {
  documentId: string;
  versionId: string;
  title: string;
  pages: readonly PageOut[];
  isPdf: boolean;
}

function score(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

function imageUrl(documentId: string, versionId: string, page: number): string {
  return `/api/files/pages/${documentId}/${versionId}/${page}`;
}

/**
 * Page accounting for one version, with a thumbnail per PDF page. The thumbnail loads lazily and
 * links to the full image.
 */
export function PagesTable({ documentId, versionId, title, pages, isPdf }: PagesTableProps) {
  if (pages.length === 0) {
    return <p className="text-sm text-muted-foreground">No page records for this version.</p>;
  }
  return (
    <Table>
      <caption className="mb-2 text-left text-sm text-muted-foreground">
        Extraction outcome for each page
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">Page</TableHead>
          <TableHead scope="col">Image</TableHead>
          <TableHead scope="col">Method</TableHead>
          <TableHead scope="col">Status</TableHead>
          <TableHead scope="col">Flagged</TableHead>
          <TableHead scope="col" className="text-right">Garble</TableHead>
          <TableHead scope="col" className="text-right">OCR conf.</TableHead>
          <TableHead scope="col" className="text-right">Chars A</TableHead>
          <TableHead scope="col" className="text-right">Chars B</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {pages.map((page) => {
          const url = imageUrl(documentId, versionId, page.page_no);
          return (
            <TableRow key={page.page_no}>
              <TableCell className="tabular-nums">{page.page_no}</TableCell>
              <TableCell>
                {isPdf ? (
                  <a href={url} className="inline-block">
                    {/* A plain img with loading="lazy": the source is a same-origin proxy route, not a
                        static asset, so next/image would only add an optimiser in front of it. */}
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={url}
                      loading="lazy"
                      alt={`Page ${page.page_no} of ${title}`}
                      width={88}
                      className="h-auto w-[88px] border"
                    />
                  </a>
                ) : (
                  <span className="text-xs text-muted-foreground">Not an image page</span>
                )}
              </TableCell>
              <TableCell className="font-mono text-xs">{page.method}</TableCell>
              <TableCell>{page.status}</TableCell>
              <TableCell>
                {page.flagged ? <Badge variant="secondary">Flagged</Badge> : "No"}
              </TableCell>
              <TableCell className="text-right tabular-nums">{score(page.garble_score)}</TableCell>
              <TableCell className="text-right tabular-nums">{score(page.ocr_conf)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatCount(page.chars_engine_a)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatCount(page.chars_engine_b)}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
