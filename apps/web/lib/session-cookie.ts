/** Name of the httpOnly cookie that holds the API bearer token. The browser never reads it. */
export const SESSION_COOKIE = "tr_session";

/** Cookies are secure unless COOKIE_SECURE=false (local http only, see README). */
export function sessionCookieSecure(): boolean {
  return process.env.COOKIE_SECURE !== "false";
}
