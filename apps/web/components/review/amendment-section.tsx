import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api-client/schema";

type AmendmentSummary = components["schemas"]["AmendmentSummary"];
type JsonRecord = Record<string, unknown>;

export interface DiffToken {
  type: "equal" | "delete" | "insert";
  text: string;
}

/**
 * Parses word diff output formatted with `[-deleted-]` and `{+inserted+}` into structured tokens.
 */
export function parseWordDiff(diff: string): DiffToken[] {
  const tokens: DiffToken[] = [];
  const regex = /(\[-[\s\S]*?-\]|\{\+[\s\S]*?\+\})/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(diff)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({
        type: "equal",
        text: diff.slice(lastIndex, match.index),
      });
    }
    const token = match[0];
    if (token.startsWith("[-") && token.endsWith("-]")) {
      tokens.push({
        type: "delete",
        text: token.slice(2, -2),
      });
    } else if (token.startsWith("{+") && token.endsWith("+}")) {
      tokens.push({
        type: "insert",
        text: token.slice(2, -2),
      });
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < diff.length) {
    tokens.push({
      type: "equal",
      text: diff.slice(lastIndex),
    });
  }

  return tokens;
}

interface AmendmentSectionProps {
  amendment: AmendmentSummary | null | undefined;
  resolution: JsonRecord | null | undefined;
}

export function AmendmentSection({ amendment, resolution }: AmendmentSectionProps) {
  if (!amendment) {
    return (
      <div className="rounded-lg border p-6 text-sm text-muted-foreground">
        No amendment proposal data is available for this task.
      </div>
    );
  }

  const locator = (amendment.target_locator ?? {}) as JsonRecord;
  const problems = Array.isArray(resolution?.problems)
    ? (resolution.problems as string[])
    : Array.isArray(locator.problems)
      ? (locator.problems as string[])
      : [];

  const instrument = typeof locator.instrument === "string" ? locator.instrument : "—";
  const targetPath =
    amendment.target_provision_path ??
    (typeof locator.target_path === "string" ? locator.target_path : "—");
  const isResolved = amendment.target_provision_id !== null;

  const diffTokens = amendment.dry_run_diff ? parseWordDiff(amendment.dry_run_diff) : [];

  return (
    <div className="space-y-6">
      {/* Target Locator Card */}
      <section aria-labelledby="locator-heading" className="space-y-3 rounded-lg border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="locator-heading" className="text-lg font-semibold">
            Amendment Proposal
          </h2>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="uppercase font-mono">
              {amendment.op}
            </Badge>
            <Badge variant={isResolved ? "default" : "destructive"}>
              {isResolved ? "Target Resolved" : "Unresolved"}
            </Badge>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
          <div>
            <span className="text-xs text-muted-foreground">Instrument</span>
            <p className="font-medium font-mono">{instrument}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">Target Path</span>
            <p className="font-medium font-mono">{targetPath}</p>
          </div>
          <div>
            <span className="text-xs text-muted-foreground">Effective From</span>
            <p className="font-medium">{amendment.effective_from ?? "Immediate / Unspecified"}</p>
          </div>
        </div>

        {problems.length > 0 && (
          <div className="mt-3 space-y-1">
            <span className="text-xs font-semibold text-destructive">Locator Problems:</span>
            <ul className="list-disc pl-5 text-xs text-destructive space-y-0.5">
              {problems.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Dry Run Diff Panel */}
      <section aria-labelledby="diff-heading" className="space-y-3 rounded-lg border p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="diff-heading" className="text-lg font-semibold">
            Consolidation Diff (Dry Run)
          </h2>
          {amendment.dry_run_ok ? (
            <Badge className="bg-emerald-600 hover:bg-emerald-700 text-white">
              Dry-run clean
            </Badge>
          ) : (
            <Badge variant="destructive">Dry-run failed</Badge>
          )}
        </div>

        {amendment.dry_run_ok ? (
          <div className="rounded-md border bg-muted/40 p-4 leading-relaxed font-mono text-sm whitespace-pre-wrap break-words">
            {diffTokens.map((token, index) => {
              if (token.type === "delete") {
                return (
                  <del
                    key={index}
                    className="bg-rose-100 text-rose-900 line-through dark:bg-rose-950/60 dark:text-rose-200 px-1 py-0.5 rounded"
                  >
                    {token.text}
                  </del>
                );
              }
              if (token.type === "insert") {
                return (
                  <ins
                    key={index}
                    className="bg-emerald-100 text-emerald-900 no-underline font-semibold dark:bg-emerald-950/60 dark:text-emerald-200 px-1 py-0.5 rounded"
                  >
                    {token.text}
                  </ins>
                );
              }
              return (
                <span key={index} className="text-foreground">
                  {token.text}
                </span>
              );
            })}
          </div>
        ) : (
          <Alert variant="destructive">
            <AlertTitle>Dry run failed to apply</AlertTitle>
            <AlertDescription className="mt-1 font-mono text-xs">
              {amendment.dry_run_diff || "Unable to determine diff."}
            </AlertDescription>
          </Alert>
        )}
      </section>

      {/* Current Provision and Operation Details */}
      {amendment.current_provision_text && (
        <section aria-labelledby="current-text-heading" className="space-y-2 rounded-lg border p-4">
          <h3 id="current-text-heading" className="text-sm font-semibold text-muted-foreground">
            Current Provision Text ({amendment.target_provision_path})
          </h3>
          <div className="max-h-48 overflow-y-auto rounded bg-muted/50 p-3 text-xs leading-normal font-mono whitespace-pre-wrap">
            {amendment.current_provision_text}
          </div>
        </section>
      )}

      {(amendment.old_text || amendment.new_text) && (
        <section aria-labelledby="text-detail-heading" className="space-y-3 rounded-lg border p-4">
          <h3 id="text-detail-heading" className="text-sm font-semibold">
            Drafting Substitution Details
          </h3>
          {amendment.old_text && (
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Original Text to Match:</span>
              <div className="rounded border border-rose-200 bg-rose-50/50 p-2 text-xs font-mono dark:border-rose-900/50 dark:bg-rose-950/20">
                {amendment.old_text}
              </div>
            </div>
          )}
          {amendment.new_text && (
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">New Text to Insert:</span>
              <div className="rounded border border-emerald-200 bg-emerald-50/50 p-2 text-xs font-mono dark:border-emerald-900/50 dark:bg-emerald-950/20">
                {amendment.new_text}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
