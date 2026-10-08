"use client";

import { useState, useTransition, type FormEvent } from "react";

import { editMetadata } from "@/app/(console)/documents/[id]/actions";
import { EDITABLE_FIELDS, MIN_REASON_LENGTH } from "@/components/documents/fields";
import type { DocumentActionState } from "@/components/documents/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const INITIAL: DocumentActionState = { outcome: "idle", message: null };

interface MetadataEditFormProps {
  documentId: string;
  current: Record<string, string>;
}

/**
 * Calls the Server Action inside a transition and keeps the result in state. The action also
 * revalidates the page, and waiting on that through a form action left the button pending.
 */
export function MetadataEditForm({ documentId, current }: MetadataEditFormProps) {
  const [state, setState] = useState<DocumentActionState>(INITIAL);
  const [pending, startTransition] = useTransition();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    startTransition(async () => {
      setState(await editMetadata(INITIAL, formData));
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" aria-describedby="edit-note">
      <input type="hidden" name="document_id" value={documentId} />
      <p id="edit-note" className="sr-only">
        Leave a field blank to keep its current value. A reason is required.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        {EDITABLE_FIELDS.map((field) => {
          const id = `edit-${field.name}`;
          return (
            <div key={field.name} className="space-y-2">
              <Label htmlFor={id}>{field.label}</Label>
              <Input
                id={id}
                name={field.name}
                type={field.kind === "date" ? "date" : "text"}
                inputMode={field.kind === "year" ? "numeric" : undefined}
                maxLength={field.kind === "year" ? 4 : 300}
                defaultValue={current[field.name] ?? ""}
                placeholder={field.kind === "date" ? "YYYY-MM-DD" : undefined}
              />
            </div>
          );
        })}
      </div>

      <div className="space-y-2">
        <Label htmlFor="edit-reason">Reason for the change</Label>
        <Textarea
          id="edit-reason"
          name="reason"
          required
          minLength={MIN_REASON_LENGTH}
          maxLength={2000}
          placeholder="For example: title corrected from the order text"
        />
      </div>

      <div role="status" aria-live="polite" className="min-h-5 text-sm">
        {state.outcome === "queued" ? <p>{state.message}</p> : null}
      </div>
      <div role="alert" className="min-h-5 text-sm text-destructive">
        {state.outcome === "error" ? state.message : null}
      </div>

      <Button type="submit" disabled={pending}>
        {pending ? "Saving..." : "Save changes"}
      </Button>
    </form>
  );
}
