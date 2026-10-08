import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { confidenceTone, type ConfidenceTone, formatConfidence } from "./confidence";

const TONE_CLASS: Record<ConfidenceTone, string> = {
  high: "border-emerald-700 bg-emerald-100 text-emerald-950",
  medium: "border-amber-700 bg-amber-100 text-amber-950",
  low: "border-red-700 bg-red-100 text-red-950",
};

/** Confidence as a percentage, coloured by tone (high 0.85 and up, medium 0.6 and up). */
export function ConfidenceBadge({ value }: { value: number }) {
  return (
    <Badge variant="outline" className={cn(TONE_CLASS[confidenceTone(value)])}>
      <span className="sr-only">Confidence: </span>
      <span>{formatConfidence(value)}</span>
    </Badge>
  );
}
