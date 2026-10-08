"use client";

import { useState, useTransition, type FormEvent } from "react";

import { changeStatus } from "@/app/(console)/documents/[id]/actions";
import { DOCUMENT_STATUSES, STATUS_LABELS } from "@/components/documents/status";
import { MIN_REASON_LENGTH } from "@/components/documents/fields";
import type { DocumentActionState } from "@/components/documents/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const INITIAL: DocumentActionState = { outcome: "idle", message: null };

interface StatusChangeFormProps {
  documentId: string;
  currentStatus: string;
}

export function StatusChangeForm({ documentId, currentStatus }: StatusChangeFormProps) {
  const [state, setState] = useState<DocumentActionState>(INITIAL);
  const [pending, startTransition] = useTransition();
  const choices = DOCUMENT_STATUSES.filter((status) => status !== currentStatus);
  const [chosen, setChosen] = useState<string>(choices[0] ?? "");
  // After a change the current status leaves the choices, so fall back to the first choice.
  const status = choices.includes(chosen as (typeof choices)[number]) ? chosen : (choices[0] ?? "");

  // The Server Action is called inside a transition and its result kept in state. The action also
  // revalidates the page; waiting on that through a form action left the button pending.
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    startTransition(async () => {
      setState(await changeStatus(INITIAL, formData));
    });
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2" aria-label="Change document status">
      <input type="hidden" name="document_id" value={documentId} />
      <input type="hidden" name="status" value={status} />

      <div className="space-y-2">
        <Label htmlFor="status-select">New status</Label>
        <Select value={status} onValueChange={setChosen}>
          <SelectTrigger id="status-select" aria-label="New status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {choices.map((choice) => (
              <SelectItem key={choice} value={choice}>
                {STATUS_LABELS[choice]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="status-valid-from">Valid from (optional)</Label>
        <Input id="status-valid-from" name="status_valid_from" type="date" />
        <p className="text-xs text-muted-foreground">Leave blank to use today.</p>
      </div>

      <div className="space-y-2 sm:col-span-2">
        <Label htmlFor="status-reason">Reason</Label>
        <Textarea
          id="status-reason"
          name="reason"
          required
          minLength={MIN_REASON_LENGTH}
          maxLength={2000}
          placeholder="For example: stayed by the High Court on the date given in the order"
        />
      </div>

      <div className="sm:col-span-2 space-y-2">
        <div role="status" aria-live="polite" className="min-h-5 text-sm">
          {state.outcome === "changed" ? <p>{state.message}</p> : null}
        </div>
        <div role="alert" className="min-h-5 text-sm text-destructive">
          {state.outcome === "error" ? state.message : null}
        </div>
        <Button type="submit" disabled={pending || choices.length === 0}>
          {pending ? "Saving..." : "Change status"}
        </Button>
      </div>
    </form>
  );
}
