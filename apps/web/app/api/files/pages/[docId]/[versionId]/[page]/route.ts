import { isUuid, streamFromApi } from "@/lib/server/file-proxy";

export const dynamic = "force-dynamic";

/** Page image proxy. The last segment is a page number, optionally with ".png". */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ docId: string; versionId: string; page: string }> },
): Promise<Response> {
  const { docId, versionId, page } = await params;
  const match = /^([1-9][0-9]{0,8})(?:\.png)?$/.exec(page);
  if (!isUuid(docId) || !isUuid(versionId) || !match) {
    return new Response("Bad request", { status: 400 });
  }

  return streamFromApi(
    `/v1/platform/documents/${docId}/versions/${versionId}/pages/${match[1]}.png`,
    { cacheControl: "private, max-age=3600", passDisposition: false },
  );
}
