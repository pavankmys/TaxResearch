export const HIGH_CONFIDENCE = 0.85;
export const MEDIUM_CONFIDENCE = 0.6;

export type ConfidenceTone = "high" | "medium" | "low";

/** Tone for a confidence score: 0.85 and above is high, 0.6 and above is medium, else low. */
export function confidenceTone(value: number): ConfidenceTone {
  if (value >= HIGH_CONFIDENCE) {
    return "high";
  }
  if (value >= MEDIUM_CONFIDENCE) {
    return "medium";
  }
  return "low";
}

/** Whole-percent label, for example 0.9 becomes "90%". */
export function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}
