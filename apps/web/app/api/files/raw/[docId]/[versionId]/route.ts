import { isUuid, streamFromApi } from "@/lib/server/file-proxy";

export const dynamic = "force-dynamic";

/** Original file proxy, with the content type and disposition from the API. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string; versionId: string }> },
): Promise<Response> {
  const { docId, versionId } = await params;
  if (!isUuid(docId) || !isUuid(versionId)) {
    return new Response("Bad request", { status: 400 });
  }

  return streamFromApi(`/v1/platform/documents/${docId}/versions/${versionId}/raw`, {
    cacheControl: "private, no-store",
    passDisposition: true,
  });
}
