import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import createClient from "openapi-fetch";

import type { components, paths } from "@/lib/api-client/schema";
import { SESSION_COOKIE } from "@/lib/session-cookie";

export type SessionUser = components["schemas"]["MeResponse"];

export function apiBaseUrl(): string {
  return process.env.API_URL ?? "http://localhost:8000";
}

export async function getSessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value;
}

/** Typed API client that forwards the session token as a bearer header. Server side only. */
export async function apiClient() {
  const token = await getSessionToken();
  return createClient<paths>({
    baseUrl: apiBaseUrl(),
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

async function expireSessionCookie(): Promise<void> {
  try {
    // Cookies can only be changed in Server Actions and Route Handlers. During a render
    // this throws, so the stale cookie stays until the next login or logout replaces it.
    const store = await cookies();
    store.delete(SESSION_COOKIE);
  } catch {
    // Read-only context: nothing to clear here.
  }
}

/**
 * Return the signed-in user. With no session, or when the API rejects the token,
 * send the browser to the login page. Other API failures throw.
 */
export async function requireSession(): Promise<SessionUser> {
  const token = await getSessionToken();
  if (!token) {
    redirect("/login");
  }
  const client = await apiClient();
  const { data, response } = await client.GET("/v1/me");
  if (response.status === 401) {
    await expireSessionCookie();
    redirect("/login");
  }
  if (!data) {
    throw new Error(`GET /v1/me failed with HTTP ${response.status}`);
  }
  return data;
}
