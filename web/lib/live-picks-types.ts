import type { MarketId } from "./parse-md";

export type LivePickQuote = {
  symbol: string;
  price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  undervalued_pct: number | null;
};

export type LivePicksMarket = {
  id: MarketId;
  quotes: LivePickQuote[];
};

export type LivePicksPayload = {
  asOf: string;
  markets: LivePicksMarket[];
  source: string;
  error?: string;
};

export type LivePicksRequest = {
  markets: Array<{
    id: MarketId;
    symbols: string[];
    fairMids?: Record<string, number | null>;
  }>;
};
