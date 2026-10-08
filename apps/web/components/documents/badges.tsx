import { Badge } from "@/components/ui/badge";
import { REVIEW_STATE_LABELS, labelOr } from "@/components/documents/labels";
import { STATUS_LABELS } from "@/components/documents/status";

/** Review state as a badge. The text names the state, so colour is not the only cue. */
export function ReviewStateBadge({ state }: { state: string }) {
  const variant = state === "pending_review" ? "secondary" : "outline";
  return <Badge variant={variant}>{labelOr(REVIEW_STATE_LABELS, state)}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const label = (STATUS_LABELS as Record<string, string>)[status] ?? status;
  return <Badge variant="outline">{label}</Badge>;
}

/** Extraction or metadata confidence as text, for example "Confidence 95%". */
export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) {
    return <Badge variant="outline">Confidence not set</Badge>;
  }
  const percent = Math.round(value * 100);
  const variant = value >= 0.85 ? "outline" : "secondary";
  const label = value >= 0.85 ? "High" : "Low";
  return (
    <Badge variant={variant}>
      {`${label} confidence ${percent}%`}
    </Badge>
  );
}
