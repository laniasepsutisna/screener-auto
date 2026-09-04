import {
  coingeckoIdsBySymbol,
  coingeckoPrices,
  yahooQuotes,
} from "./market-prices";
import type {
  LivePickQuote,
  LivePicksPayload,
  LivePicksRequest,
} from "./live-picks-types";
import { calcUndervaluedPct, toYahooSymbol } from "./pick-symbols";

function changePct(price: number | null, prev: number | null): number | null {
  if (price == null || prev == null || prev <= 0) return null;
  return ((price / prev) - 1) * 100;
}

export async function buildLivePicks(
  req: LivePicksRequest
): Promise<LivePicksPayload> {
  const yahooSyms: string[] = [];
  const cryptoTickers: string[] = [];

  for (const m of req.markets) {
    for (const sym of m.symbols) {
      const ticker = sym.toUpperCase();
      if (m.id === "crypto") {
        cryptoTickers.push(ticker);
      } else {
        const y = toYahooSymbol(m.id, ticker);
        yahooSyms.push(y);
      }
    }
  }

  const cgIdMap = await coingeckoIdsBySymbol(cryptoTickers);
  const cgIds = [...new Set(cgIdMap.values())];

  const [yQuotes, cgPrices] = await Promise.all([
    yahooQuotes(yahooSyms),
    coingeckoPrices(cgIds),
  ]);

  const cgPriceBySymbol = new Map<string, number>();
  for (const [sym, id] of cgIdMap) {
    const p = cgPrices.get(id);
    if (typeof p === "number") cgPriceBySymbol.set(sym, p);
  }

  const markets = req.markets.map((m) => {
    const quotes: LivePickQuote[] = m.symbols.map((sym) => {
      const ticker = sym.toUpperCase();
      let price: number | null = null;
      let prev: number | null = null;

      if (m.id === "crypto") {
        price = cgPriceBySymbol.get(ticker) ?? null;
        const yahoo = toYahooSymbol("crypto", ticker);
        const yq = yQuotes.get(yahoo);
        if (price == null && yq?.price != null) price = yq.price;
        if (yq?.prev != null) prev = yq.prev;
      } else {
        const yahoo = toYahooSymbol(m.id, ticker);
        const q = yQuotes.get(yahoo);
        price = q?.price ?? null;
        prev = q?.prev ?? null;
      }

      const fairMid = m.fairMids?.[ticker] ?? m.fairMids?.[sym] ?? null;
      const undervalued_pct =
        price != null && fairMid != null && fairMid > 0
          ? calcUndervaluedPct(price, fairMid)
          : null;

      return {
        symbol: ticker,
        price,
        prev_close: prev,
        change_pct: changePct(price, prev),
        undervalued_pct,
      };
    });

    return { id: m.id, quotes };
  });

  return {
    asOf: new Date().toISOString(),
    markets,
    source: "Yahoo Finance + CoinGecko",
  };
}
