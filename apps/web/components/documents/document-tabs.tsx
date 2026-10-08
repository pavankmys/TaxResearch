"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface DocumentTab {
  value: string;
  label: string;
  content: ReactNode;
}

function tabFromParams(params: URLSearchParams, tabs: readonly DocumentTab[]): string {
  const requested = params.get("tab");
  return tabs.some((tab) => tab.value === requested) ? (requested as string) : tabs[0].value;
}

/**
 * The document's tabs. A click changes the tab at once. The ?tab= query string sets the tab on
 * load and when a link changes it (for example the "Pages" link in the versions table).
 */
export function DocumentTabs({ tabs }: { tabs: readonly DocumentTab[] }) {
  const params = useSearchParams();
  const fromUrl = tabFromParams(new URLSearchParams(params.toString()), tabs);
  const [active, setActive] = useState<string>(fromUrl);

  // A navigation that changes ?tab= (for example the Pages link) moves the tabs with it.
  useEffect(() => {
    setActive(fromUrl);
  }, [fromUrl]);

  // Clicking a tab only changes local state. Rewriting the URL here made a later Server Action
  // (revalidatePath) hang on the client, so the URL is read on load and on links only.
  function select(value: string) {
    setActive(value);
  }

  return (
    <Tabs value={active} onValueChange={select} className="w-full">
      <TabsList className="h-auto w-full flex-wrap justify-start">
        {tabs.map((tab) => (
          <TabsTrigger key={tab.value} value={tab.value}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent key={tab.value} value={tab.value} className="pt-4">
          {tab.content}
        </TabsContent>
      ))}
    </Tabs>
  );
}
