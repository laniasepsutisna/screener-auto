const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

export type Quote = { price: number | null; prev: number | null };

export async function yahooChart(symbol: string): Promise<Quote> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
    symbol
  )}?interval=1m&range=1d`;
  try {
    const res = await fetch(url, {
      headers: { "User-Agent": UA, Accept: "application/json" },
      next: { revalidate: 0 },
      cache: "no-store",
    });
    if (!res.ok) return { price: null, prev: null };
    const json = (await res.json()) as {
      chart?: {
        result?: Array<{
          meta?: {
            regularMarketPrice?: number;
            previousClose?: number;
            chartPreviousClose?: number;
          };
        }>;
      };
    };
    const meta = json.chart?.result?.[0]?.meta;
    if (!meta) return { price: null, prev: null };
    const price =
      typeof meta.regularMarketPrice === "number"
        ? meta.regularMarketPrice
        : null;
    const prev =
      typeof meta.chartPreviousClose === "number"
        ? meta.chartPreviousClose
        : typeof meta.previousClose === "number"
          ? meta.previousClose
          : null;
    return { price, prev };
  } catch {
    return { price: null, prev: null };
  }
}

export async function yahooQuotes(symbols: string[]): Promise<Map<string, Quote>> {
  const map = new Map<string, Quote>();
  const unique = [...new Set(symbols.filter(Boolean))];
  if (!unique.length) return map;

  try {
    const url = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${encodeURIComponent(
      unique.join(",")
    )}`;
    const res = await fetch(url, {
      headers: { "User-Agent": UA, Accept: "application/json" },
      cache: "no-store",
    });
    if (res.ok) {
      const json = (await res.json()) as {
        quoteResponse?: {
          result?: Array<{
            symbol?: string;
            regularMarketPrice?: number;
            regularMarketPreviousClose?: number;
          }>;
        };
      };
      for (const q of json.quoteResponse?.result ?? []) {
        if (!q.symbol) continue;
        map.set(q.symbol, {
          price:
            typeof q.regularMarketPrice === "number"
              ? q.regularMarketPrice
              : null,
          prev:
            typeof q.regularMarketPreviousClose === "number"
              ? q.regularMarketPreviousClose
              : null,
        });
      }
    }
  } catch {
    /* fall through */
  }

  const missing = unique.filter((s) => !map.has(s) || map.get(s)?.price == null);
  if (missing.length) {
    await Promise.all(
      missing.map(async (sym) => {
        map.set(sym, await yahooChart(sym));
      })
    );
  }
  return map;
}

export async function coingeckoPrices(
  ids: string[]
): Promise<Map<string, number>> {
  const map = new Map<string, number>();
  const unique = [...new Set(ids.filter(Boolean))];
  if (!unique.length) return map;
  const url = `https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(
    unique.join(",")
  )}&vs_currencies=usd`;
  try {
    const res = await fetch(url, {
      headers: { Accept: "application/json", "User-Agent": UA },
      cache: "no-store",
    });
    if (!res.ok) return map;
    const json = (await res.json()) as Record<string, { usd?: number }>;
    for (const id of unique) {
      const p = json[id]?.usd;
      if (typeof p === "number") map.set(id, p);
    }
  } catch {
    /* ignore */
  }
  return map;
}

/** Resolve ticker → CoinGecko id (exact symbol match, market cap rank). */
export async function coingeckoIdsBySymbol(
  symbols: string[]
): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  const unique = [...new Set(symbols.map((s) => s.toUpperCase()).filter(Boolean))];
  await Promise.all(
    unique.map(async (sym) => {
      try {
        const res = await fetch(
          `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(sym)}`,
          {
            headers: { Accept: "application/json", "User-Agent": UA },
            cache: "no-store",
          }
        );
        if (!res.ok) return;
        const json = (await res.json()) as {
          coins?: Array<{ id?: string; symbol?: string; market_cap_rank?: number | null }>;
        };
        const hits = (json.coins ?? []).filter(
          (c) => c.symbol?.toUpperCase() === sym && c.id
        );
        hits.sort(
          (a, b) =>
            (a.market_cap_rank ?? 9999) - (b.market_cap_rank ?? 9999)
        );
        if (hits[0]?.id) map.set(sym, hits[0].id);
      } catch {
        /* ignore */
      }
    })
  );
  return map;
}
