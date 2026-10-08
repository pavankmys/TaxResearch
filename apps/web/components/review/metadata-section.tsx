import type { components } from "@/lib/api-client/schema";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { ConfidenceBadge } from "./confidence-badge";
import { DocumentCard } from "./document-card";
import type { Proposal } from "./proposal";

type DocumentSummary = components["schemas"]["app__routers__review_tasks__DocumentSummary"];

/** A proposed value as text. Lists are comma-separated and null is a dash. */
export function formatProposedValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((item) => String(item)).join(", ") : "—";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

interface MetadataSectionProps {
  proposal: Proposal | null;
  metaConfidence: number | null;
  spotCheck: boolean;
  document: DocumentSummary | null | undefined;
  nearDuplicate: DocumentSummary | null | undefined;
}

/** The metadata proposal: per-field values and confidence, issues, and any near-duplicate. */
export function MetadataSection({
  proposal,
  metaConfidence,
  spotCheck,
  document,
  nearDuplicate,
}: MetadataSectionProps) {
  return (
    <div className="space-y-6">
      {spotCheck ? (
        <Alert>
          <AlertDescription>
            <strong>Spot check.</strong> This document was sampled for a routine check of its stored
            metadata. Confirm the fields or correct them.
          </AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="proposal-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="proposal-heading" className="text-lg font-semibold">
            Proposed metadata
          </h2>
          {metaConfidence !== null ? (
            <p className="flex items-center gap-2 text-sm">
              Overall <ConfidenceBadge value={metaConfidence} />
            </p>
          ) : null}
        </div>

        {proposal === null ? (
          <p className="text-sm text-muted-foreground">No proposal is recorded for this task.</p>
        ) : (
          <>
            <Table>
              <caption className="sr-only">Proposed metadata fields</caption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Field</TableHead>
                  <TableHead scope="col">Proposed value</TableHead>
                  <TableHead scope="col">Confidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(proposal.fields).map(([name, value]) => {
                  const confidence = proposal.confidence[name];
                  return (
                    <TableRow key={name}>
                      <TableCell className="font-mono text-xs">{name}</TableCell>
                      <TableCell className="break-words">{formatProposedValue(value)}</TableCell>
                      <TableCell>
                        {confidence === undefined ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <ConfidenceBadge value={confidence} />
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            <div className="space-y-1">
              <h3 className="text-sm font-medium">Issues</h3>
              {proposal.issues.length > 0 ? (
                <ul className="list-inside list-disc space-y-1 text-sm">
                  {proposal.issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No issues recorded.</p>
              )}
            </div>
          </>
        )}
      </section>

      {nearDuplicate ? (
        <section aria-labelledby="duplicate-heading" className="space-y-3">
          <h2 id="duplicate-heading" className="text-lg font-semibold">
            Possible near-duplicate
          </h2>
          <p className="text-sm text-muted-foreground">
            The proposal names a near-duplicate document. No merge was made; merge it manually.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            {document ? <DocumentCard heading="This document" doc={document} /> : null}
            <DocumentCard heading="Near duplicate" doc={nearDuplicate} />
          </div>
        </section>
      ) : null}
    </div>
  );
}
