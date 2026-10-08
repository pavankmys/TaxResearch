"use client";

import { useState, useTransition } from "react";

import { structureDepth } from "@/components/documents/structure";
import type { BlockOut, BlockPage, BlocksResult } from "@/components/documents/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const ALL_PAGES = "all";

interface StructureOutlineProps {
  documentId: string;
  versionId: string;
  initial: BlockPage;
  pageNumbers: readonly number[];
  loadBlocks: (input: {
    documentId: string;
    versionId: string;
    page: number | null;
    after: number | null;
  }) => Promise<BlocksResult>;
}

/**
 * The blocks of the current version as an outline. Each dot in structure_path indents one level.
 * The page filter and "Load more" fetch through a Server Action, so the token stays on the server.
 */
export function StructureOutline({
  documentId,
  versionId,
  initial,
  pageNumbers,
  loadBlocks,
}: StructureOutlineProps) {
  const [items, setItems] = useState<BlockOut[]>(initial.items);
  const [next, setNext] = useState<number | null>(initial.next_cursor);
  const [page, setPage] = useState<string>(ALL_PAGES);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function pageArg(value: string): number | null {
    return value === ALL_PAGES ? null : Number(value);
  }

  function changePage(value: string) {
    setPage(value);
    startTransition(async () => {
      const result = await loadBlocks({ documentId, versionId, page: pageArg(value), after: null });
      if (result.ok) {
        setItems(result.page.items);
        setNext(result.page.next_cursor);
        setError(null);
      } else {
        setError(result.error);
      }
    });
  }

  function loadMore() {
    startTransition(async () => {
      const result = await loadBlocks({ documentId, versionId, page: pageArg(page), after: next });
      if (result.ok) {
        setItems((previous) => [...previous, ...result.page.items]);
        setNext(result.page.next_cursor);
        setError(null);
      } else {
        setError(result.error);
      }
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        {pageNumbers.length > 0 ? (
          <div className="space-y-2">
            <Label htmlFor="structure-page">Page</Label>
            <Select value={page} onValueChange={changePage}>
              <SelectTrigger id="structure-page" className="w-40" aria-label="Page filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectItem value={ALL_PAGES}>All pages</SelectItem>
                {pageNumbers.map((number) => (
                  <SelectItem key={number} value={String(number)}>
                    {`Page ${number}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
          {pending ? "Loading blocks..." : `${items.length} blocks shown`}
        </p>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Blocks could not be loaded</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No blocks for this version.</p>
      ) : (
        <ol className="space-y-3" aria-label="Document structure">
          {items.map((block) => (
            <li
              key={block.id}
              data-depth={structureDepth(block.structure_path)}
              style={{ paddingLeft: `${structureDepth(block.structure_path) * 1.5}rem` }}
              className="border-l-2 border-muted pl-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono">{block.structure_path ?? "no path"}</span>
                {block.para_label ? <span className="font-medium">{block.para_label}</span> : null}
                <Badge variant="outline">{block.kind}</Badge>
                {block.is_boilerplate ? <Badge variant="secondary">Boilerplate</Badge> : null}
                {block.lang ? <span>{`Language ${block.lang}`}</span> : null}
                {block.page ? <span>{`Page ${block.page}`}</span> : null}
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words text-sm">{block.text}</p>
            </li>
          ))}
        </ol>
      )}

      {next !== null ? (
        <Button type="button" variant="outline" onClick={loadMore} disabled={pending}>
          Load more blocks
        </Button>
      ) : null}
    </div>
  );
}
