import Link from "next/link";

import { DismissibleAlert } from "@/components/review/dismissible-alert";
import { QueueTable } from "@/components/review/queue-table";
import { QueueViews } from "@/components/review/queue-views";
import {
  assigneeFilter,
  parseKind,
  parseTab,
  queueHref,
  type QueueKind,
  type QueueTab,
} from "@/components/review/queue-links";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { apiClient } from "@/lib/server/api";
import { isUuid } from "@/lib/server/file-proxy";
import { cn } from "@/lib/utils";

export const metadata = {
  title: "Review queue | TaxResearch Console",
};

const PAGE_SIZE = 50;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function single(value: string | string[] | undefined): string | undefined {
  return typeof value === "string" ? value : undefined;
}

export default async function QueuePage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const tab: QueueTab = parseTab(single(params.tab));
  const kind: QueueKind | undefined = parseKind(single(params.kind));
  const cursor = single(params.cursor)?.slice(0, 512);
  const doneParam = single(params.done);
  const done = doneParam && isUuid(doneParam) ? doneParam : undefined;
  const assignee = assigneeFilter(tab);
  const now = Date.now();

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/platform/review-tasks", {
    params: {
      query: { assignee, kind, cursor: cursor || undefined, limit: PAGE_SIZE },
    },
  });

  let nextTaskLink: { id: string; label: string } | null = null;
  if (done) {
    nextTaskLink = await findNextTask(client);
  }

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Review queue</h1>
        {data ? (
          <p className="text-sm text-muted-foreground">
            {data.total === 1 ? "1 task" : `${data.total} tasks`} in this view
          </p>
        ) : null}
      </header>

      {done ? (
        <DismissibleAlert>
          <p className="font-medium">Decision recorded.</p>
          {nextTaskLink ? (
            <p>
              <Link
                href={`/queue/${nextTaskLink.id}`}
                className="font-medium underline underline-offset-4"
              >
                Next task: {nextTaskLink.label}
              </Link>
            </p>
          ) : (
            <p>No open tasks are left in your queue.</p>
          )}
        </DismissibleAlert>
      ) : null}

      <QueueViews tab={tab} kind={kind} />

      {!data ? (
        <Alert variant="destructive">
          <AlertDescription>
            The queue could not be loaded (HTTP {response.status}). Reload the page to try again.
          </AlertDescription>
        </Alert>
      ) : data.items.length === 0 ? (
        <section className="rounded-lg border border-dashed p-8 text-center">
          <h2 className="text-lg font-medium">Nothing to review here</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {tab === "mine"
              ? "You have no tasks assigned to you. Try All open to pick one up."
              : "No tasks match this view. Try another tab or kind."}
          </p>
        </section>
      ) : (
        <>
          <QueueTable items={data.items} now={now} />
          {data.next_cursor ? (
            <nav aria-label="Pagination" className="flex justify-end">
              <Link
                href={queueHref({ tab, kind, cursor: data.next_cursor })}
                className={cn(buttonVariants({ variant: "outline" }))}
              >
                Next page
              </Link>
            </nav>
          ) : null}
        </>
      )}
    </section>
  );
}

/** The first task in My tasks, else the first in All open. Null when neither has a task. */
async function findNextTask(
  client: Awaited<ReturnType<typeof apiClient>>,
): Promise<{ id: string; label: string } | null> {
  for (const filter of ["me", undefined] as const) {
    const { data } = await client.GET("/v1/platform/review-tasks", {
      params: { query: { assignee: filter, limit: 1 } },
    });
    const first = data?.items[0];
    if (first) {
      return { id: first.id, label: first.title ?? "Untitled task" };
    }
  }
  return null;
}
