export const dynamic = "force-dynamic";

/** Liveness for compose healthchecks and the e2e stack. Public (no session needed). */
export function GET(): Response {
  return Response.json({ ok: true });
}
