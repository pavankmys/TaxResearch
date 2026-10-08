"use server";

import createClient from "openapi-fetch";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { paths } from "@/lib/api-client/schema";
import { safeNext } from "@/lib/safe-next";
import { apiBaseUrl } from "@/lib/server/api";
import { SESSION_COOKIE, sessionCookieSecure } from "@/lib/session-cookie";

export type LoginState = { error: string | null };

const INVALID_CREDENTIALS = "Invalid email or password";
const TOO_MANY_ATTEMPTS = "Too many attempts, try again later";
const UNAVAILABLE = "Sign-in is unavailable right now. Try again.";

/**
 * Exchange the credentials for an API token and store it in an httpOnly cookie.
 * The browser never sees the token. Used with useActionState, so it takes the previous state.
 */
export async function login(_previous: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const next = safeNext(String(formData.get("next") ?? ""));

  if (!email || !password) {
    return { error: "Enter your email and password" };
  }

  const client = createClient<paths>({ baseUrl: apiBaseUrl() });
  const result = await client
    .POST("/v1/auth/login", { body: { email, password } })
    .catch(() => null);
  if (!result) {
    return { error: UNAVAILABLE };
  }

  const { data, response } = result;
  if (!data) {
    if (response.status === 401) {
      return { error: INVALID_CREDENTIALS };
    }
    if (response.status === 429) {
      return { error: TOO_MANY_ATTEMPTS };
    }
    return { error: UNAVAILABLE };
  }

  const store = await cookies();
  store.set(SESSION_COOKIE, data.access_token, {
    httpOnly: true,
    sameSite: "strict",
    path: "/",
    maxAge: data.expires_in,
    secure: sessionCookieSecure(),
  });
  // redirect() throws to end the request, so it stays outside the try blocks above.
  redirect(next);
}
