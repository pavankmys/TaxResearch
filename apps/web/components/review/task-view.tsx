"use client";

import { useMemo, useState } from "react";

import type { components } from "@/lib/api-client/schema";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { type BlockSelection, ParseFailureSection } from "./parse-failure-section";
import { MetadataSection } from "./metadata-section";
import { MissReportSection } from "./miss-report-section";
import { PageViewer } from "./page-viewer";
import { parseBbox, type Bbox } from "./bbox";
import { TaskActions } from "./task-actions";
import { readDecision, readProposal, type JsonRecord } from "./proposal";

type ReviewTaskDetail = components["schemas"]["ReviewTaskDetail"];
type BlockItem = components["schemas"]["BlockItem"];
type ProblemPage = components["schemas"]["ProblemPage"];

/** Where the source page comes from. Null when the task has no page image. */
export interface ViewerConfig {
  docId: string;
  versionId: string;
  title: string;
  pageCount: number | null;
  initialPage: number;
}

const NO_PAGES: ProblemPage[] = [];

interface TaskViewProps {
  task: ReviewTaskDetail;
  currentUserId: string;
  viewer: ViewerConfig | null;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The task page: the source page on the left, the kind-specific details and the actions on the
 * right. Parse-failure blocks select a block, which is outlined on the page.
 */
export function TaskView({ task, currentUserId, viewer }: TaskViewProps) {
  const resolution = (task.resolution ?? null) as JsonRecord | null;
  const problemPages: ProblemPage[] = task.problem_pages ?? NO_PAGES;
  const proposal = readProposal(resolution);

  const [page, setPage] = useState(viewer?.initialPage ?? 1);
  const [selected, setSelected] = useState<BlockSelection | null>(null);

  const highlight: Bbox | null = useMemo(() => {
    if (selected === null || selected.page !== page) {
      return null;
    }
    const block = problemPages
      .find((item) => item.page_no === selected.page)
      ?.blocks.find((item) => item.seq === selected.seq);
    return block ? parseBbox(block.bbox) : null;
  }, [page, problemPages, selected]);

  function selectBlock(block: BlockItem) {
    const target = block.page ?? page;
    setSelected({ page: target, seq: block.seq });
    setPage(target);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      <section aria-labelledby="source-heading" className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="source-heading" className="text-lg font-semibold">
            Source page
          </h2>
          {viewer ? (
            <a
              href={`/api/files/raw/${viewer.docId}/${viewer.versionId}`}
              className={cn(buttonVariants({ variant: "link", size: "sm" }), "h-auto px-0")}
            >
              Open original
            </a>
          ) : null}
        </div>
        {viewer ? (
          <PageViewer
            docId={viewer.docId}
            versionId={viewer.versionId}
            title={viewer.title}
            page={page}
            pageCount={viewer.pageCount}
            onPageChange={setPage}
            highlight={highlight}
          />
        ) : (
          <p className="rounded-md border border-dashed p-6 text-sm text-muted-foreground">
            This task has no source page image.
          </p>
        )}
      </section>

      <div className="min-w-0 space-y-6">
        {task.kind === "metadata" ? (
          <MetadataSection
            proposal={proposal}
            metaConfidence={numberOrNull(resolution?.meta_confidence)}
            spotCheck={resolution?.spot_check === true}
            document={task.document}
            nearDuplicate={task.near_duplicate_of}
          />
        ) : null}
        {task.kind === "parse_failure" ? (
          <ParseFailureSection
            resolution={resolution}
            problemPages={problemPages}
            selected={selected}
            onSelectBlock={selectBlock}
          />
        ) : null}
        {task.kind === "miss_report" ? (
          <MissReportSection
            resolution={resolution}
            currentUserId={currentUserId}
            createdAt={task.opened_at}
          />
        ) : null}
        {!["metadata", "parse_failure", "miss_report"].includes(task.kind) ? (
          <p className="text-sm text-muted-foreground">This kind of task has no details view.</p>
        ) : null}

        <TaskActions
          taskId={task.id}
          kind={task.kind}
          status={task.status}
          assigneeId={task.assignee_id}
          assigneeName={task.assignee_name}
          currentUserId={currentUserId}
          proposalFields={proposal?.fields ?? {}}
          decision={readDecision(resolution)}
        />
      </div>
    </div>
  );
}
