import { NextResponse, type NextRequest } from "next/server";
import { apiClient } from "@/lib/server/api";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const searchParams = request.nextUrl.searchParams;
  const fromVersionId = searchParams.get("from_version_id") ?? undefined;
  const toVersionId = searchParams.get("to_version_id") ?? undefined;
  const fromDate = searchParams.get("from_date") ?? undefined;
  const toDate = searchParams.get("to_date") ?? undefined;

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/provisions/{provision_id}/diff", {
    params: {
      path: { provision_id: id },
      query: {
        from_version_id: fromVersionId,
        to_version_id: toVersionId,
        from_date: fromDate,
        to_date: toDate,
      },
    },
  });

  if (!data) {
    return new NextResponse(null, { status: response.status });
  }

  return NextResponse.json(data);
}
