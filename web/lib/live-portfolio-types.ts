export type LivePosition = {
  symbol: string;
  name: string;
  weight_pct: number;
  entry_price: number;
  price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  return_pct: number | null;
  pnl: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  quality: string;
  thesis: string;
  hint: string;
  status: string;
};

export type LiveBook = {
  id: "idx" | "us" | "crypto";
  label: string;
  currency: "IDR" | "USD";
  portfolio_id: string;
  entry_date: string;
  review_at?: string;
  capital: number;
  cash_pct?: number;
  portfolio_return_pct: number | null;
  portfolio_pnl: number | null;
  winners: number;
  losers: number;
  positions: LivePosition[];
};

export type LivePortfolioPayload = {
  asOf: string;
  mode: string;
  fxUsdIdr: number | null;
  books: LiveBook[];
  totalPnlIdr: number | null;
  source: string;
  error?: string;
};
