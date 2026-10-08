import "server-only";

import { apiBaseUrl, getSessionToken } from "@/lib/server/api";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

function errorResponse(status: number, message: string): Response {
  return new Response(message, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

/**
 * Fetch a binary resource from the API with the session token and stream it back.
 * Only the status, content type and (when asked) content disposition are passed on.
 */
export async function streamFromApi(
  apiPath: string,
  options: { cacheControl: string; passDisposition: boolean },
): Promise<Response> {
  const token = await getSessionToken();
  if (!token) {
    return errorResponse(401, "Not signed in");
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl()}${apiPath}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return errorResponse(502, "The API is unavailable");
  }

  if (!upstream.ok || !upstream.body) {
    return errorResponse(upstream.status, "Not available");
  }

  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  if (options.passDisposition) {
    const disposition = upstream.headers.get("content-disposition");
    if (disposition) {
      headers.set("Content-Disposition", disposition);
    }
  }
  headers.set("Cache-Control", options.cacheControl);

  return new Response(upstream.body, { status: upstream.status, headers });
}
