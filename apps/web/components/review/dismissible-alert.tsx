"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** A success message that the reviewer can dismiss. */
export function DismissibleAlert({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(true);
  if (!open) {
    return null;
  }
  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-700 bg-emerald-50 px-4 py-3 text-sm text-emerald-950"
    >
      <div className="space-y-1">{children}</div>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)}>
        Dismiss
      </Button>
    </div>
  );
}
