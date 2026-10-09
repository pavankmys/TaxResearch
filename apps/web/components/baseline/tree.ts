import type { ProvisionRow } from "@/components/baseline/types";

/** Flags for a provision row, indicating problems to highlight. */
export function provisionFlags(row: ProvisionRow): string[] {
  const flags: string[] = [];

  if (!row.has_baseline) {
    flags.push("No baseline text");
  } else if (row.text_chars === 0 && row.level !== "chapter") {
    flags.push("Empty text");
  }

  return flags;
}

/** Human-readable label for a provision row, e.g. "Section 16" or "(a)". */
export function rowLabel(row: ProvisionRow): string {
  const level = row.level.toLowerCase();
  const num = row.number_label;

  if (!num) {
    return level.charAt(0).toUpperCase() + level.slice(1);
  }

  // Map levels to their display format
  if (level === "chapter") {
    return `Chapter ${num}`;
  }
  if (level === "section") {
    return `Section ${num}`;
  }
  if (level === "rule") {
    return `Rule ${num}`;
  }
  if (level === "subsection") {
    return `(${num})`;
  }
  if (level === "clause") {
    return `(${num})`;
  }
  if (level === "subclause") {
    return `(${num})`;
  }
  if (level === "proviso") {
    return `Proviso ${num}`;
  }
  if (level === "explanation") {
    return `Explanation ${num}`;
  }

  return `${level.charAt(0).toUpperCase() + level.slice(1)} ${num}`;
}
