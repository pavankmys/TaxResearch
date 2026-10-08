"use client";

import { useActionState } from "react";

import { setSourceEnabled } from "@/app/(console)/ingest/actions";
import { INITIAL_INGEST_STATE } from "@/components/ingest/types";
import { Button } from "@/components/ui/button";

/** Enable or disable one source. Rendered only for platform admins. */
export function SourceToggle({ code, enabled }: { code: string; enabled: boolean }) {
  const [state, formAction, pending] = useActionState(setSourceEnabled, INITIAL_INGEST_STATE);
  const verb = enabled ? "Disable" : "Enable";

  return (
    <form action={formAction} className="flex flex-wrap items-center gap-2">
      <input type="hidden" name="code" value={code} />
      <input type="hidden" name="enabled" value={enabled ? "false" : "true"} />
      <Button type="submit" size="sm" variant="outline" disabled={pending} aria-label={`${verb} source ${code}`}>
        {pending ? "Saving..." : verb}
      </Button>
      {state.error ? <span role="alert" className="text-sm text-destructive">{state.error}</span> : null}
    </form>
  );
}
