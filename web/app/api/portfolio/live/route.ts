import { NextResponse } from "next/server";
import { buildLivePortfolio } from "@/lib/live-portfolio";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  try {
    const payload = await buildLivePortfolio();
    return NextResponse.json(payload, {
      headers: {
        "Cache-Control": "no-store, max-age=0",
      },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "live portfolio failed";
    return NextResponse.json(
      {
        asOf: new Date().toISOString(),
        mode: "Paper",
        fxUsdIdr: null,
        books: [],
        totalPnlIdr: null,
        source: "error",
        error: message,
      },
      { status: 500, headers: { "Cache-Control": "no-store" } }
    );
  }
}
