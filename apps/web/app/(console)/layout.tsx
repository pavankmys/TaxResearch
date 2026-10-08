import type { ReactNode } from "react";

import { ConsoleHeader } from "@/components/console/console-header";
import { isReviewer } from "@/lib/roles";
import { requireSession } from "@/lib/server/api";

export default async function ConsoleLayout({ children }: { children: ReactNode }) {
  const user = await requireSession();

  if (!isReviewer(user.roles)) {
    return (
      <>
        <ConsoleHeader user={user} showNav={false} />
        <main id="main" tabIndex={-1} className="px-4 py-6 sm:px-6">
          <section className="mx-auto max-w-lg space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">No access</h1>
            <p className="text-muted-foreground">
              The TaxResearch Console is for platform staff. Ask an administrator for the platform
              content editor role to use it.
            </p>
          </section>
        </main>
      </>
    );
  }

  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow-md"
      >
        Skip to main content
      </a>
      <ConsoleHeader user={user} showNav />
      <main id="main" tabIndex={-1} className="px-4 py-6 sm:px-6">
        {children}
      </main>
    </>
  );
}
