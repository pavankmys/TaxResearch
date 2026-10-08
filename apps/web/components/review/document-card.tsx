import Link from "next/link";

import type { components } from "@/lib/api-client/schema";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

type DocumentSummary = components["schemas"]["app__routers__review_tasks__DocumentSummary"];

/** A document's identity (title, canonical ID, type, review state) with a link to its page. */
export function DocumentCard({ heading, doc }: { heading: string; doc: DocumentSummary }) {
  return (
    <Card>
      <CardHeader className="space-y-1 p-4">
        <h3 className="text-sm font-medium text-muted-foreground">{heading}</h3>
        <p className="font-semibold leading-snug">{doc.title}</p>
      </CardHeader>
      <CardContent className="space-y-2 p-4 pt-0 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-muted-foreground">Canonical ID</dt>
          <dd className="break-all font-mono text-xs">{doc.canonical_id}</dd>
          <dt className="text-muted-foreground">Type</dt>
          <dd>{doc.doc_type}</dd>
          <dt className="text-muted-foreground">Review state</dt>
          <dd>{doc.review_state}</dd>
        </dl>
        <Link
          href={`/documents/${doc.id}`}
          className="inline-block font-medium underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Open document<span className="sr-only"> {doc.title}</span>
        </Link>
      </CardContent>
    </Card>
  );
}
