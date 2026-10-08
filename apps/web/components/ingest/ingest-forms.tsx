import { FileForm } from "@/components/ingest/file-form";
import type { SourceChoice } from "@/components/ingest/url-form";
import { UrlForm } from "@/components/ingest/url-form";

/** The two ways to add a document, one above the other on a phone and side by side on a wide screen. */
export function IngestForms({ sources }: { sources: readonly SourceChoice[] }) {
  return (
    <div className="grid gap-10 xl:grid-cols-2">
      <UrlForm sources={sources} />
      <FileForm sources={sources} />
    </div>
  );
}
