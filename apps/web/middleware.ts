import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session-cookie";

const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "img-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  // Next.js inlines its bootstrap scripts, so 'unsafe-inline' stays. Dev also needs eval.
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/favicon") ||
    pathname === "/api/health"
  );
}

function applySecurityHeaders(response: NextResponse): void {
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "same-origin");
  response.headers.set("Content-Security-Policy", CONTENT_SECURITY_POLICY);
}

/** Send visitors without a session cookie to the login page, and add security headers. */
export function middleware(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  let response: NextResponse;

  if (!isPublicPath(pathname) && !request.cookies.has(SESSION_COOKIE)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    response = NextResponse.redirect(loginUrl);
  } else {
    response = NextResponse.next();
  }

  applySecurityHeaders(response);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
