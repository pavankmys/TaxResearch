"use client";

import { useState, useTransition } from "react";

import { verifyBaseline } from "@/app/(console)/baseline/[code]/actions";
import type { VerifyState } from "@/components/baseline/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

const INITIAL: VerifyState = { outcome: "idle", message: "" };

interface VerifyFormProps {
  code: string;
}

/** Form to verify a baseline. Requires a confirmation checkbox before submit. */
export function VerifyForm({ code }: VerifyFormProps) {
  const [state, setState] = useState<VerifyState>(INITIAL);
  const [pending, startTransition] = useTransition();
  const [checked, setChecked] = useState(false);

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    startTransition(async () => {
      setState(await verifyBaseline(INITIAL, formData));
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" aria-label="Verify baseline">
      <input type="hidden" name="code" value={code} />

      <div className="flex items-center gap-3">
        <input
          id="confirmation"
          type="checkbox"
          checked={checked}
          onChange={(e) => setChecked(e.currentTarget.checked)}
          disabled={pending}
          className="h-4 w-4"
        />
        <Label htmlFor="confirmation" className="font-normal cursor-pointer">
          I have checked the provision tree against the source document
        </Label>
      </div>

      <div className="space-y-2">
        {state.outcome === "verified" && (
          <Alert variant="default">
            <AlertTitle>Verified</AlertTitle>
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        )}
        {state.outcome === "error" && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        )}
      </div>

      <Button type="submit" disabled={!checked || pending} variant="destructive">
        {pending ? "Verifying..." : "Verify baseline"}
      </Button>
    </form>
  );
}
