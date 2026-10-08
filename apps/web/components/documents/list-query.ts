/** Query-string state of the document list. "all" and blank values mean no filter. */

export interface DocumentListQuery {
  q?: string;
  docType?: string;
  reviewState?: string;
  cursor?: string;
}

export function documentsHref(query: DocumentListQuery): string {
  const params = new URLSearchParams();
  const term = (query.q ?? "").trim();
  if (term) {
    params.set("q", term);
  }
  for (const [key, value] of [
    ["doc_type", query.docType],
    ["review_state", query.reviewState],
  ] as const) {
    if (value && value !== "all") {
      params.set(key, value);
    }
  }
  if (query.cursor) {
    params.set("cursor", query.cursor);
  }
  const text = params.toString();
  return text ? `/documents?${text}` : "/documents";
}
