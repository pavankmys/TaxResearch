/**
 * Whether an ingestion job has stopped moving, so the job page can stop refreshing.
 *
 * - A failed job is terminal at any stage: it does not advance until someone retries it.
 * - A skipped acquire is terminal: the bytes were already stored, so nothing else runs.
 * - A done publish is the last step of the pipeline.
 */
export function isTerminalJob(stage: string, status: string): boolean {
  if (status === "failed") {
    return true;
  }
  if (status === "skipped" && stage === "acquire") {
    return true;
  }
  return stage === "publish" && status === "done";
}

export const JOB_REFRESH_MS = 3000;
