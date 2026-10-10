import { NextResponse, type NextRequest } from "next/server";
import { apiClient } from "@/lib/server/api";

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get("q") ?? "";
  if (!q.trim()) {
    return NextResponse.json({ matched: false });
  }

  const client = await apiClient();
  const { data, response } = await client.GET("/v1/resolve", {
    params: {
      query: { q },
    },
  });

  if (!data) {
    return new NextResponse(null, { status: response.status });
  }

  return NextResponse.json(data);
}
