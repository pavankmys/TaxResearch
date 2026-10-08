"use client";

import { useActionState } from "react";

import { submitUrl } from "@/app/(console)/ingest/actions";
import { IdentifyingFields } from "@/components/ingest/metadata-fields";
import { DOC_TYPES, DOC_TYPE_LABELS } from "@/components/ingest/payload";
import { INITIAL_INGEST_STATE } from "@/components/ingest/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export interface SourceChoice {
  code: string;
  description: string | null;
}

export function UrlForm({ sources }: { sources: readonly SourceChoice[] }) {
  const [state, formAction, pending] = useActionState(submitUrl, INITIAL_INGEST_STATE);

  return (
    <form action={formAction} className="space-y-4" aria-labelledby="url-heading">
      <h2 id="url-heading" className="text-lg font-semibold">
        By URL
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="url-source">Source</Label>
          <Select name="source" required>
            <SelectTrigger id="url-source" aria-label="Source" disabled={sources.length === 0}>
              <SelectValue placeholder="Choose a source" />
            </SelectTrigger>
            <SelectContent>
              {sources.map((source) => (
                <SelectItem key={source.code} value={source.code}>
                  {source.code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="url-doc-type">Document type</Label>
          <Select name="doc_type" required>
            <SelectTrigger id="url-doc-type" aria-label="Document type">
              <SelectValue placeholder="Choose a type" />
            </SelectTrigger>
            <SelectContent>
              {DOC_TYPES.map((docType) => (
                <SelectItem key={docType} value={docType}>
                  {DOC_TYPE_LABELS[docType]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="url-url">Document URL</Label>
        <Input id="url-url" name="url" type="url" required placeholder="https://" maxLength={2048} />
      </div>

      <IdentifyingFields idPrefix="url" />

      <div role="alert" className="min-h-5 text-sm text-destructive">
        {state.error}
      </div>

      <Button type="submit" disabled={pending || sources.length === 0}>
        {pending ? "Submitting..." : "Submit URL"}
      </Button>
      {sources.length === 0 ? (
        <p className="text-sm text-muted-foreground">No source is enabled, so a URL cannot be submitted.</p>
      ) : null}
    </form>
  );
}
