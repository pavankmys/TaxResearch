"use client";

import { useActionState } from "react";

import { login, type LoginState } from "@/app/login/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const INITIAL_STATE: LoginState = { error: null };

export function LoginForm({ next }: { next: string }) {
  const [state, formAction, pending] = useActionState(login, INITIAL_STATE);
  const hasError = state.error !== null;

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="next" value={next} />

      <div className="space-y-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          aria-invalid={hasError || undefined}
          aria-describedby="login-error"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={hasError || undefined}
          aria-describedby="login-error"
        />
      </div>

      {/* The region is always present so that screen readers announce errors when they appear. */}
      <div id="login-error" role="alert" className="min-h-5 text-sm text-destructive">
        {state.error}
      </div>

      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? "Signing in..." : "Sign in"}
      </Button>
    </form>
  );
}
