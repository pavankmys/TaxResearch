import type { Metadata } from "next";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { safeNext } from "@/lib/safe-next";

import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in | TaxResearch Console",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const params = await searchParams;
  const next = safeNext(typeof params.next === "string" ? params.next : undefined);

  return (
    <main id="main" className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <h1 className="text-2xl font-semibold leading-none tracking-tight">Sign in</h1>
          <CardDescription>TaxResearch Console, for platform staff.</CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm next={next} />
        </CardContent>
      </Card>
    </main>
  );
}
