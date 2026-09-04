import { NextResponse } from "next/server";
import { buildLivePicks } from "@/lib/live-picks";
import type { LivePicksRequest } from "@/lib/live-picks-types";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function POST(req: Request) {
  try {
    const body = (await req.json()) as LivePicksRequest;
    if (!body?.markets?.length) {
      return NextResponse.json(
        {
          asOf: new Date().toISOString(),
          markets: [],
          source: "error",
          error: "markets wajib diisi",
        },
        { status: 400, headers: { "Cache-Control": "no-store" } }
      );
    }
    const payload = await buildLivePicks(body);
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "live picks failed";
    return NextResponse.json(
      {
        asOf: new Date().toISOString(),
        markets: [],
        source: "error",
        error: message,
      },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
}
