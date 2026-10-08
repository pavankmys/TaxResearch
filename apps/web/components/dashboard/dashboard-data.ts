/** Pure selectors over the dashboard payload. The page passes the API rows straight in. */

export interface ReviewQueueInput {
  kind: string;
  status: string;
  count: number;
  oldest_opened_at: string | null;
  overdue_count: number;
}

export interface PageAccountingInput {
  method: string;
  status: string;
  pages: number;
  flagged_pages: number;
  pages_last_30d: number;
}

export interface QueueLagInput {
  queue: string;
  queued: number;
  lag_minutes: number;
}

export interface OpenTaskKindSummary {
  kind: string;
  count: number;
  oldestOpenedAt: string | null;
}

/** Statuses that count as open work. Decided tasks are not shown here. */
export const OPEN_REVIEW_STATUSES: readonly string[] = ["open", "in_review"];

/** Open review tasks per kind, with the oldest opening time among them. Sorted by kind. */
export function openTasksByKind(rows: readonly ReviewQueueInput[]): OpenTaskKindSummary[] {
  const byKind = new Map<string, OpenTaskKindSummary>();
  for (const row of rows) {
    if (!OPEN_REVIEW_STATUSES.includes(row.status)) {
      continue;
    }
    const current = byKind.get(row.kind) ?? { kind: row.kind, count: 0, oldestOpenedAt: null };
    current.count += row.count;
    if (row.oldest_opened_at && (!current.oldestOpenedAt || row.oldest_opened_at < current.oldestOpenedAt)) {
      current.oldestOpenedAt = row.oldest_opened_at;
    }
    byKind.set(row.kind, current);
  }
  return [...byKind.values()].sort((a, b) => a.kind.localeCompare(b.kind));
}

export function overdueTotal(rows: readonly ReviewQueueInput[]): number {
  return rows.reduce((sum, row) => sum + row.overdue_count, 0);
}

export function flaggedPageTotal(rows: readonly PageAccountingInput[]): number {
  return rows.reduce((sum, row) => sum + row.flagged_pages, 0);
}

export function failedPageTotal(rows: readonly PageAccountingInput[]): number {
  return rows.reduce((sum, row) => (row.status === "failed" ? sum + row.pages : sum), 0);
}

/** The longest queue lag in minutes, or null when no queue is listed. */
export function maxQueueLag(rows: readonly QueueLagInput[]): number | null {
  if (rows.length === 0) {
    return null;
  }
  return rows.reduce((max, row) => Math.max(max, row.lag_minutes), 0);
}
