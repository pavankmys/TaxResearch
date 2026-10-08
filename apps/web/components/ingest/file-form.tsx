"use client";

import { useActionState, useState, type ChangeEvent } from "react";

import { submitFile } from "@/app/(console)/ingest/actions";
import { IdentifyingFields } from "@/components/ingest/metadata-fields";
import { checkUploadSize, DOC_TYPES, DOC_TYPE_LABELS } from "@/components/ingest/payload";
import type { SourceChoice } from "@/components/ingest/url-form";
import { INITIAL_INGEST_STATE } from "@/components/ingest/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function FileForm({ sources }: { sources: readonly SourceChoice[] }) {
  const [state, formAction, pending] = useActionState(submitFile, INITIAL_INGEST_STATE);
  const [sizeError, setSizeError] = useState<string | null>(null);

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    setSizeError(file ? checkUploadSize(file.size) : null);
  }

  const message = sizeError ?? state.error;

  return (
    <form action={formAction} className="space-y-4" aria-labelledby="file-heading">
      <h2 id="file-heading" className="text-lg font-semibold">
        By file
      </h2>
      <p className="text-sm text-muted-foreground">PDF or HTML, up to 50 MB.</p>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="file-source">Source</Label>
          <Select name="source" required>
            <SelectTrigger id="file-source" aria-label="Source" disabled={sources.length === 0}>
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
          <Label htmlFor="file-doc-type">Document type</Label>
          <Select name="doc_type" required>
            <SelectTrigger id="file-doc-type" aria-label="Document type">
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
        <Label htmlFor="file-file">File</Label>
        <Input
          id="file-file"
          name="file"
          type="file"
          accept=".pdf,.html,application/pdf,text/html"
          required
          onChange={onFileChange}
          aria-describedby="file-help"
          className="file:mr-4 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1 file:text-sm"
        />
        <p id="file-help" className="text-xs text-muted-foreground">
          The file must be a PDF or an HTML page. Its type is checked when it is received.
        </p>
      </div>

      <IdentifyingFields idPrefix="file" />

      <div role="alert" className="min-h-5 text-sm text-destructive">
        {message}
      </div>

      <Button type="submit" disabled={pending || sizeError !== null || sources.length === 0}>
        {pending ? "Uploading..." : "Upload file"}
      </Button>
    </form>
  );
}
