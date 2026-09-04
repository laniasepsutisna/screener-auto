import type { MarketId } from "./parse-md";

/** Parse "**BUKA** Bukalapak…" or "SOL" → ticker. */
export function extractTicker(symbolCell: string): string {
  const bold = symbolCell.match(/\*\*([A-Za-z0-9.-]+)\*\*/);
  if (bold) return bold[1].toUpperCase();
  const first = symbolCell.trim().split(/\s+/)[0] ?? "";
  return first.replace(/\*\*/g, "").toUpperCase();
}

export function priceColumnKey(headers: string[]): string | null {
  return (
    headers.find((h) => /^harga$/i.test(h.trim())) ??
    headers.find((h) => /^(price|harga sekarang)$/i.test(h.trim())) ??
    null
  );
}

export function fairValueColumnKey(headers: string[]): string | null {
  return headers.find((h) => /harga wajar/i.test(h)) ?? null;
}

export function parseFairMid(fair: string): number | null {
  const cleaned = fair.replace(/,/g, "").trim();
  const parts = cleaned.split(/\s*[-–]\s*/);
  if (parts.length < 2) return null;
  const low = Number(parts[0]);
  const high = Number(parts[1]);
  if (!Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || high <= 0) {
    return null;
  }
  return (low + high) / 2;
}

/** Selaras formula screener: (1 - price/fairMid) * 100 */
export function calcUndervaluedPct(price: number, fairMid: number): number {
  return (1 - price / fairMid) * 100;
}

export function toYahooSymbol(market: MarketId, ticker: string): string {
  const t = ticker.toUpperCase().replace(/\.JK$/, "");
  if (market === "idx") return `${t}.JK`;
  if (market === "crypto") return `${t}-USD`;
  return t.replace(/\./g, "-");
}

export function formatLivePrice(
  price: number,
  market: MarketId
): string {
  if (market === "idx") return Math.round(price).toLocaleString("id-ID");
  if (market === "crypto") {
    if (price >= 100) return price.toFixed(2);
    if (price >= 1) return price.toFixed(4);
    return price.toFixed(6);
  }
  if (price >= 100) return price.toFixed(2);
  return price.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
