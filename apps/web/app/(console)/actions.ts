"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiClient, getSessionToken } from "@/lib/server/api";
import { SESSION_COOKIE } from "@/lib/session-cookie";

/** Record the logout with the API (best effort), clear the cookie and go to the login page. */
export async function logout(): Promise<void> {
  const token = await getSessionToken();
  if (token) {
    try {
      const client = await apiClient();
      await client.POST("/v1/auth/logout");
    } catch {
      // The cookie is cleared below either way.
    }
  }
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  redirect("/login");
}
