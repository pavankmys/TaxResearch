"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

import { bboxToPercent, type Bbox, type PageSize, pageSizeFromPixels } from "./bbox";

interface PageViewerProps {
  docId: string;
  versionId: string;
  title: string;
  page: number;
  pageCount: number | null;
  onPageChange: (page: number) => void;
  /** The block to outline, in PDF points. Drawn only once the page image has its size. */
  highlight: Bbox | null;
}

/**
 * A rendered source page with an optional outline over a block. The outline is positioned in
 * percent of the page, so it stays aligned at any width.
 */
export function PageViewer({
  docId,
  versionId,
  title,
  page,
  pageCount,
  onPageChange,
  highlight,
}: PageViewerProps) {
  const src = `/api/files/pages/${docId}/${versionId}/${page}`;
  // Size and error are keyed by the image URL, so a page change needs no reset effect.
  const [loaded, setLoaded] = useState<{ src: string; size: PageSize } | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const size = loaded?.src === src ? loaded.size : null;
  const failed = failedSrc === src;
  const box = highlight && size ? bboxToPercent(highlight, size) : null;

  return (
    <div className="space-y-3">
      {pageCount !== null ? (
        <nav aria-label="Source pages" className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            Previous page
          </Button>
          <p className="text-sm" aria-live="polite">
            Page {page} of {pageCount}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page >= pageCount}
            onClick={() => onPageChange(page + 1)}
          >
            Next page
          </Button>
        </nav>
      ) : null}

      <div className="relative overflow-hidden rounded-md border bg-muted">
        {failed ? (
          <p className="p-6 text-sm">The page image could not be loaded.</p>
        ) : (
          // Page images come from an authenticated proxy, so next/image optimisation does not apply.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={src}
            src={src}
            alt={`Page ${page} of ${title}`}
            className="block h-auto w-full"
            onLoad={(event) => {
              const image = event.currentTarget;
              if (image.naturalWidth > 0 && image.naturalHeight > 0) {
                setLoaded({
                  src,
                  size: pageSizeFromPixels({
                    width: image.naturalWidth,
                    height: image.naturalHeight,
                  }),
                });
              }
            }}
            onError={() => setFailedSrc(src)}
          />
        )}
        {box ? (
          <div
            aria-hidden="true"
            data-testid="block-highlight"
            className="pointer-events-none absolute border-2 border-amber-600 bg-amber-300/30"
            style={{
              left: `${box.left}%`,
              top: `${box.top}%`,
              width: `${box.width}%`,
              height: `${box.height}%`,
            }}
          />
        ) : null}
      </div>
    </div>
  );
}
