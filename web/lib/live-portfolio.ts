import fs from "fs";
import path from "path";
import type {
  LiveBook,
  LivePortfolioPayload,
  LivePosition,
} from "./live-portfolio-types";

export type {
  LiveBook,
  LivePortfolioPayload,
  LivePosition,
} from "./live-portfolio-types";

type RawPos = {
  symbol: string;
  yahoo?: string;
  coingecko_id?: string;
  name?: string;
  weight_pct: number;
  entry_price: number;
  stop_loss?: number | null;
  take_profit?: number | null;
  quality?: string;
  thesis?: string;
  allocation_usd?: number;
};

type RawBook = {
  id: "idx" | "us" | "crypto";
  label: string;
  currency: "IDR" | "USD";
  portfolio_id?: string;
  entry_date?: string;
  review_at?: string;
  capital: number;
  cash_pct?: number;
  positions: RawPos[];
};

type PositionsFile = {
  synced_at?: string;
  mode?: string;
  books: Record<string, RawBook>;
};

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

function loadPositionsFile(): PositionsFile {
  const candidates = [
    path.join(process.cwd(), "public", "data", "positions.json"),
    path.join(process.cwd(), "data", "positions.json"),
    path.join(process.cwd(), "..", "reports", "portfolio", "positions.json"),
    path.join(process.cwd(), "reports", "portfolio", "positions.json"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return JSON.parse(fs.readFileSync(p, "utf8")) as PositionsFile;
    }
  }
  throw new Error("positions.json tidak ditemukan — sync portfolio dulu");
}

async function yahooChart(symbol: string): Promise<{
  price: number | null;
  prev: number | null;
}> {
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

async function yahooQuotes(
  symbols: string[]
): Promise<Map<string, { price: number | null; prev: number | null }>> {
  const map = new Map<string, { price: number | null; prev: number | null }>();
  const unique = [...new Set(symbols.filter(Boolean))];
  if (!unique.length) return map;

  // Batch quote (cepat); fallback per-symbol chart jika gagal
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

async function coingeckoPrices(
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

function hintFor(
  price: number | null,
  entry: number,
  sl: number | null | undefined,
  tp: number | null | undefined,
  retPct: number | null
): string {
  if (price == null) return "—";
  if (sl != null && price <= sl) return "SL";
  if (tp != null && price >= tp) return "TP";
  if (retPct != null && retPct <= -8) return "Review";
  if (retPct != null && retPct >= 8) return "Scale?";
  return "Hold";
}

function buildBook(
  raw: RawBook,
  priceOf: (p: RawPos) => { price: number | null; prev: number | null }
): LiveBook {
  let totalEntry = 0;
  let totalCurrent = 0;
  const positions: LivePosition[] = [];

  for (const p of raw.positions) {
    const { price, prev } = priceOf(p);
    const alloc = (raw.capital * p.weight_pct) / 100;
    const entry = p.entry_price;
    let return_pct: number | null = null;
    let pnl: number | null = null;
    let change_pct: number | null = null;

    if (price != null && entry > 0) {
      const shares = alloc / entry;
      const entryVal = shares * entry;
      const curVal = shares * price;
      totalEntry += entryVal;
      totalCurrent += curVal;
      return_pct = ((price / entry) - 1) * 100;
      pnl = curVal - entryVal;
    }
    if (price != null && prev != null && prev > 0) {
      change_pct = ((price / prev) - 1) * 100;
    }

    const sl = p.stop_loss ?? null;
    const tp = p.take_profit ?? null;
    positions.push({
      symbol: p.symbol,
      name: p.name || p.symbol,
      weight_pct: p.weight_pct,
      entry_price: entry,
      price,
      prev_close: prev,
      change_pct,
      return_pct,
      pnl,
      stop_loss: sl,
      take_profit: tp,
      quality: p.quality || "",
      thesis: p.thesis || "",
      hint: hintFor(price, entry, sl, tp, return_pct),
      status: "open",
    });
  }

  positions.sort((a, b) => (b.return_pct ?? -999) - (a.return_pct ?? -999));
  const winners = positions.filter((p) => (p.return_pct ?? 0) > 0).length;
  const losers = positions.filter((p) => (p.return_pct ?? 0) < 0).length;
  const portfolio_return_pct =
    totalEntry > 0 ? ((totalCurrent / totalEntry) - 1) * 100 : null;
  const portfolio_pnl = totalEntry > 0 ? totalCurrent - totalEntry : null;

  return {
    id: raw.id,
    label: raw.label,
    currency: raw.currency,
    portfolio_id: raw.portfolio_id || "",
    entry_date: raw.entry_date || "",
    review_at: raw.review_at,
    capital: raw.capital,
    cash_pct: raw.cash_pct,
    portfolio_return_pct,
    portfolio_pnl,
    winners,
    losers,
    positions,
  };
}

export async function buildLivePortfolio(): Promise<LivePortfolioPayload> {
  const file = loadPositionsFile();
  const booksRaw = Object.values(file.books || {});

  const yahooSyms: string[] = ["IDR=X"];
  const cgIds: string[] = [];
  for (const b of booksRaw) {
    for (const p of b.positions) {
      if (b.id === "crypto" && p.coingecko_id) cgIds.push(p.coingecko_id);
      else if (p.yahoo) yahooSyms.push(p.yahoo);
    }
  }

  const [yQuotes, cgPrices] = await Promise.all([
    yahooQuotes(yahooSyms),
    coingeckoPrices(cgIds),
  ]);

  const fx = yQuotes.get("IDR=X")?.price ?? null;

  const books = booksRaw.map((raw) =>
    buildBook(raw, (p) => {
      if (raw.id === "crypto" && p.coingecko_id) {
        const price = cgPrices.get(p.coingecko_id) ?? null;
        return { price, prev: null };
      }
      const y = p.yahoo || p.symbol;
      return yQuotes.get(y) ?? { price: null, prev: null };
    })
  );

  // Sort books idx, us, crypto
  const order = { idx: 0, us: 1, crypto: 2 };
  books.sort((a, b) => order[a.id] - order[b.id]);

  let totalPnlIdr: number | null = 0;
  for (const b of books) {
    if (b.portfolio_pnl == null) {
      totalPnlIdr = null;
      break;
    }
    if (b.currency === "IDR") totalPnlIdr! += b.portfolio_pnl;
    else if (fx) totalPnlIdr! += b.portfolio_pnl * fx;
    else {
      totalPnlIdr = null;
      break;
    }
  }

  return {
    asOf: new Date().toISOString(),
    mode: file.mode || "Paper",
    fxUsdIdr: fx,
    books,
    totalPnlIdr,
    source: "Yahoo Finance + CoinGecko",
  };
}
