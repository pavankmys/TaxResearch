import Link from "next/link";
import { notFound } from "next/navigation";

import { formatAge, kindLabel } from "@/components/review/format";
import { type ViewerConfig, TaskView } from "@/components/review/task-view";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api-client/schema";
import { apiClient, requireSession } from "@/lib/server/api";
import { isUuid } from "@/lib/server/file-proxy";

type Client = Awaited<ReturnType<typeof apiClient>>;
type ReviewTaskDetail = components["schemas"]["ReviewTaskDetail"];

export const metadata = {
  title: "Review task | TaxResearch Console",
};

/** The page image to show: the task's version, or the current version of its document. */
async function viewerFor(client: Client, task: ReviewTaskDetail): Promise<ViewerConfig | null> {
  const docId = task.document?.id ?? task.version?.document_id ?? null;
  if (docId === null) {
    return null;
  }
  const title = task.document?.title ?? "document";

  let versionId: string | null = null;
  let pageCount: number | null = null;
  if (task.version) {
    versionId = task.version.id;
    pageCount = task.version.page_count;
  } else if (task.document?.current_version_id) {
    versionId = task.document.current_version_id;
    const { data } = await client.GET("/v1/platform/documents/{document_id}", {
      params: { path: { document_id: docId } },
    });
    pageCount = data?.versions.find((version) => version.id === versionId)?.page_count ?? null;
  }
  if (versionId === null) {
    return null;
  }

  const firstProblemPage = task.problem_pages?.[0]?.page_no ?? 1;
  return { docId, versionId, title, pageCount, initialPage: firstProblemPage };
}

export default async function TaskPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;
  if (!isUuid(taskId)) {
    notFound();
  }
  const user = await requireSession();
  const client = await apiClient();
  const { data: task, response } = await client.GET("/v1/platform/review-tasks/{task_id}", {
    params: { path: { task_id: taskId } },
  });

  if (!task) {
    if (response.status === 404) {
      notFound();
    }
    return (
      <div className="space-y-6">
        <BackLink />
        <Alert variant="destructive">
          <AlertDescription>
            The task could not be loaded (HTTP {response.status}). Reload the page to try again.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const viewer = await viewerFor(client, task);

  return (
    <div className="space-y-6">
      <BackLink />
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight break-words">
          {task.title ?? "Untitled task"}
        </h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Badge variant="secondary">{kindLabel(task.kind)}</Badge>
          <Badge variant="outline">P{task.priority}</Badge>
          <span>Open for {formatAge(task.opened_at)}</span>
        </p>
      </header>
      <TaskView task={task} currentUserId={user.id} viewer={viewer} />
    </div>
  );
}

function BackLink() {
  return (
    <nav aria-label="Breadcrumb">
      <Link href="/queue" className="text-sm font-medium underline underline-offset-4">
        Back to queue
      </Link>
    </nav>
  );
}
