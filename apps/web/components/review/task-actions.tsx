"use client";

import { useEffect, useId, useRef, useState, useTransition, type FormEvent, type KeyboardEvent } from "react";

import { assignTask, decideTask, type ActionResult, type DecisionAction } from "@/app/(console)/queue/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { formatDateTimeUtc, isClosedStatus, statusLabel } from "./format";
import {
  AMENDMENT_FIELDS,
  METADATA_FIELDS,
  buildEditPatch,
  editableAmendmentFields,
  editableFields,
  LIST_FIELDS,
  label,
} from "./edit-fields";
import { DECISION_LABELS, type Decision, type JsonRecord } from "./proposal";

type Intent = "assign_me" | "unassign" | DecisionAction;

interface TaskActionsProps {
  taskId: string;
  kind: string;
  status: string;
  assigneeId: string | null;
  assigneeName: string | null;
  currentUserId: string;
  proposalFields: JsonRecord;
  amendmentFields?: JsonRecord | null;
  decision: Decision | null;
}

type Message = { tone: "success" | "error"; text: string };

/**
 * Assign, approve, edit then approve, reject and needs-info. Submits through a server action and
 * keeps what the reviewer typed when a request fails. Errors and results go in a region that is
 * focused after each submit.
 */
export function TaskActions({
  taskId,
  kind,
  status,
  assigneeId,
  assigneeName,
  currentUserId,
  proposalFields,
  amendmentFields,
  decision,
}: TaskActionsProps) {
  const ids = useId();
  const noteId = `${ids}-note`;
  const noteHintId = `${ids}-note-hint`;
  const alertRef = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [pending, startTransition] = useTransition();

  const closed = isClosedStatus(status);
  const isMetadata = kind === "metadata";
  const isAmendment = kind === "amendment";
  const canEdit = isMetadata || isAmendment;
  const assignedToMe = assigneeId !== null && assigneeId === currentUserId;
  const fields = isMetadata
    ? editableFields(proposalFields)
    : isAmendment
      ? editableAmendmentFields(amendmentFields ?? {})
      : [];

  useEffect(() => {
    if (message) {
      alertRef.current?.focus();
    }
  }, [message]);

  function run(request: () => Promise<ActionResult | undefined>) {
    setMessage(null);
    startTransition(async () => {
      const result = await request();
      // A successful decision redirects to the queue, so there is no result to show here.
      if (!result) {
        return;
      }
      setMessage(
        result.ok
          ? { tone: "success", text: result.message }
          : { tone: "error", text: result.error },
      );
    });
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const intent = submitter?.value as Intent | undefined;
    if (!intent) {
      return;
    }

    if (intent === "assign_me" || intent === "unassign") {
      run(() => assignTask(taskId, intent === "assign_me" ? "me" : null));
      return;
    }

    const data = new FormData(event.currentTarget);
    const note = String(data.get("note") ?? "").trim();
    let patch: JsonRecord | undefined;
    if (intent === "edit_approve") {
      const edited: Record<string, string> = {};
      for (const field of fields) {
        edited[field.name] = String(data.get(`field:${field.name}`) ?? "");
      }
      const allowed = isMetadata ? METADATA_FIELDS : AMENDMENT_FIELDS;
      const original = isMetadata ? proposalFields : (amendmentFields ?? {});
      const result = buildEditPatch(original, edited, allowed);
      if (result.errors.length > 0) {
        setMessage({ tone: "error", text: result.errors.join(". ") });
        return;
      }
      if (Object.keys(result.patch).length === 0) {
        setMessage({ tone: "error", text: "Change at least one field, or use Approve." });
        return;
      }
      patch = result.patch;
    }

    run(() => decideTask(taskId, { action: intent, note: note || undefined, fields: patch }));
  }

  function blockEnterInInputs(event: KeyboardEvent<HTMLFormElement>) {
    // Enter in a field should not trigger whichever button comes first.
    if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
      event.preventDefault();
    }
  }

  const disabled = closed || pending;

  return (
    <section aria-labelledby={`${ids}-heading`} className="space-y-4 rounded-lg border p-4">
      <h2 id={`${ids}-heading`} className="text-lg font-semibold">
        Actions
      </h2>

      <div className="space-y-1 text-sm">
        <p>
          Status: <strong>{statusLabel(status)}</strong>
        </p>
        <p>Assigned to: {assigneeName ?? "nobody"}</p>
        {decision ? (
          <p>
            Last decision: {DECISION_LABELS[decision.action] ?? decision.action}
            {decision.decided_at ? ` on ${formatDateTimeUtc(decision.decided_at)}` : ""}
            {decision.decided_by === currentUserId ? " by you" : ""}
            {decision.note ? `. Note: ${decision.note}` : ""}
          </p>
        ) : null}
        {closed ? <p className="text-muted-foreground">This task is closed.</p> : null}
      </div>

      <div
        ref={alertRef}
        role="alert"
        tabIndex={-1}
        className={cn(
          "rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          message === null && "sr-only",
          message?.tone === "error" && "border border-red-700 bg-red-50 px-3 py-2 text-red-950",
          message?.tone === "success" &&
            "border border-emerald-700 bg-emerald-50 px-3 py-2 text-emerald-950",
        )}
      >
        {message?.text}
      </div>

      <form onSubmit={onSubmit} onKeyDown={blockEnterInInputs} className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {assignedToMe ? (
            <Button type="submit" variant="outline" value="unassign" disabled={disabled}>
              Unassign
            </Button>
          ) : (
            <Button type="submit" variant="outline" value="assign_me" disabled={disabled}>
              Assign to me
            </Button>
          )}
        </div>

        {canEdit ? (
          <details className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm font-medium">Edit fields</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {fields.map((field) => {
                const inputId = `${ids}-field-${field.name}`;
                const hintId = `${inputId}-hint`;
                const isList = LIST_FIELDS.has(field.name);
                return (
                  <div key={field.name} className="space-y-1">
                    <Label htmlFor={inputId}>{label(field.name)}</Label>
                    <Input
                      id={inputId}
                      name={`field:${field.name}`}
                      defaultValue={field.initial}
                      disabled={disabled}
                      aria-describedby={isList ? hintId : undefined}
                    />
                    {isList ? (
                      <p id={hintId} className="text-xs text-muted-foreground">
                        Separate values with commas.
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              {isMetadata
                ? "Only changed fields are saved. Parties and other object fields are not editable here."
                : "Only changed fields are saved. Overrides the proposal on approval."}
            </p>
          </details>
        ) : null}

        <div className="space-y-2">
          <Label htmlFor={noteId}>Note</Label>
          <Textarea id={noteId} name="note" rows={3} disabled={disabled} aria-describedby={noteHintId} />
          <p id={noteHintId} className="text-xs text-muted-foreground">
            Required for Reject and Needs info, at least 3 characters. Optional otherwise.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button type="submit" value="approve" disabled={disabled}>
            Approve
          </Button>
          {canEdit ? (
            <Button type="submit" value="edit_approve" disabled={disabled}>
              Edit then approve
            </Button>
          ) : null}
          <Button type="submit" variant="outline" value="needs_info" disabled={disabled}>
            Needs info
          </Button>
          <Button type="submit" variant="destructive" value="reject" disabled={disabled}>
            Reject
          </Button>
        </div>
      </form>
    </section>
  );
}
