import type { components } from "@/lib/api-client/schema";
import { Badge } from "@/components/ui/badge";

import { isRecord, type JsonRecord } from "./proposal";

type ProblemPage = components["schemas"]["ProblemPage"];
type BlockItem = components["schemas"]["BlockItem"];

const SNIPPET_LENGTH = 160;
const REASON_LABELS: Record<string, string> = {
  unreadable_pdf: "The PDF could not be read.",
};

export interface BlockSelection {
  page: number;
  seq: number;
}

interface ParseFailureSectionProps {
  resolution: JsonRecord | null;
  problemPages: ProblemPage[];
  selected: BlockSelection | null;
  onSelectBlock: (block: BlockItem) => void;
}

function snippet(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact.length > SNIPPET_LENGTH ? `${compact.slice(0, SNIPPET_LENGTH)}…` : compact;
}

function pageReasons(page: ProblemPage): string[] {
  const reasons: string[] = [];
  if (page.status === "failed") {
    reasons.push("Extraction failed on this page.");
  }
  if (page.flagged) {
    reasons.push("The text checks flagged this page, so the text may be garbled.");
  }
  return reasons;
}

/** Parse problems: unreadable file, failed or flagged pages with their blocks, and numbering gaps. */
export function ParseFailureSection({
  resolution,
  problemPages,
  selected,
  onSelectBlock,
}: ParseFailureSectionProps) {
  const reason = typeof resolution?.reason === "string" ? resolution.reason : null;
  const error = typeof resolution?.error === "string" ? resolution.error : null;
  const rawNumbering = resolution?.numbering;
  const numbering = Array.isArray(rawNumbering) ? rawNumbering.filter(isRecord) : [];

  return (
    <div className="space-y-6">
      {reason || error ? (
        <section aria-labelledby="reason-heading" className="space-y-1">
          <h2 id="reason-heading" className="text-lg font-semibold">
            What went wrong
          </h2>
          {reason ? <p>{REASON_LABELS[reason] ?? reason}</p> : null}
          {error ? <p className="font-mono text-xs break-words">{error}</p> : null}
        </section>
      ) : null}

      {problemPages.length === 0 && reason === null ? (
        <p className="text-sm text-muted-foreground">No page-level problems are recorded.</p>
      ) : null}

      {problemPages.map((page) => (
        <section
          key={page.page_no}
          aria-labelledby={`problem-page-${page.page_no}`}
          className="space-y-3 rounded-lg border p-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`problem-page-${page.page_no}`} className="text-lg font-semibold">
              Page {page.page_no}
            </h2>
            <Badge variant="outline">Status: {page.status}</Badge>
            {page.flagged ? <Badge variant="secondary">Flagged</Badge> : null}
            <span className="text-sm text-muted-foreground">Method: {page.method}</span>
          </div>

          {pageReasons(page).map((line) => (
            <p key={line} className="text-sm">
              {line}
            </p>
          ))}

          <details className="rounded-md border bg-muted/40 p-3">
            <summary className="cursor-pointer text-sm font-medium">Page text</summary>
            {page.page_text === null ? (
              <p className="mt-2 text-sm text-muted-foreground">No page text is stored.</p>
            ) : (
              <>
                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">
                  {page.page_text}
                </pre>
                {page.page_text_truncated ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Showing the first part of the page text.
                  </p>
                ) : null}
              </>
            )}
          </details>

          <div className="space-y-2">
            <h3 className="text-sm font-medium">Blocks on this page</h3>
            {page.blocks.length === 0 ? (
              <p className="text-sm text-muted-foreground">No blocks are stored for this page.</p>
            ) : (
              <ul className="space-y-1">
                {page.blocks.map((block) => {
                  const isSelected = selected?.page === page.page_no && selected.seq === block.seq;
                  return (
                    <li key={block.seq}>
                      <button
                        type="button"
                        aria-pressed={isSelected}
                        onClick={() => onSelectBlock(block)}
                        className={
                          "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
                          (isSelected ? "border-amber-700 bg-amber-50" : "hover:bg-accent")
                        }
                      >
                        <span className="font-mono text-xs text-muted-foreground">
                          #{block.seq} {block.structure_path ?? "no path"}
                        </span>
                        <span className="block">{snippet(block.text)}</span>
                        {block.bbox === null ? (
                          <span className="block text-xs text-muted-foreground">
                            No position on the page
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>
      ))}

      {numbering.length > 0 ? (
        <section aria-labelledby="numbering-heading" className="space-y-2">
          <h2 id="numbering-heading" className="text-lg font-semibold">
            Numbering problems
          </h2>
          <ul className="list-inside list-disc space-y-1 text-sm">
            {numbering.map((item, index) => (
              <li key={`${String(item.path)}-${index}`}>
                <span className="font-mono text-xs">{String(item.path ?? "")}</span>{" "}
                {String(item.detail ?? item.problem ?? "")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
