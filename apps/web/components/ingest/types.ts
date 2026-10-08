/** State returned by the ingest Server Actions. A successful submit redirects instead. */
export interface IngestState {
  error: string | null;
}

export const INITIAL_INGEST_STATE: IngestState = { error: null };
