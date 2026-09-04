"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PortfolioReport } from "@/lib/parse-portfolio";
import type {
  LiveBook,
  LivePortfolioPayload,
  LivePosition,
} from "@/lib/live-portfolio-types";
import styles from "./dashboard.module.css";

type Props = {
  portfolio: PortfolioReport;
};

type SortDir = "asc" | "desc";
type BookId = "idx" | "us" | "crypto";

const POLL_MS = 20_000;

function retTone(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return "";
  if (pct > 0.05) return styles.retPos;
  if (pct < -0.05) return styles.retNeg;
  return styles.retFlat;
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function fmtMoney(v: number | null | undefined, currency: "IDR" | "USD"): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (currency === "IDR") {
    return `Rp ${Math.round(v).toLocaleString("id-ID")}`;
  }
  const sign = v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function fmtPrice(v: number | null | undefined, currency: "IDR" | "USD"): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (currency === "IDR") return Math.round(v).toLocaleString("id-ID");
  if (v >= 100) return v.toFixed(2);
  if (v >= 1) return v.toFixed(4);
  return v.toFixed(6);
}

function actionClass(action: string): string {
  if (action === "SL") return styles.badgeWarn;
  if (action === "TP" || action === "Scale?") return styles.badgeGood;
  if (action === "Review") return styles.badgeMid;
  return styles.badgeNeutral;
}

function flashClass(changePct: number | null | undefined): string {
  if (changePct == null) return "";
  if (changePct > 0.01) return styles.flashUp;
  if (changePct < -0.01) return styles.flashDown;
  return "";
}

export default function PortfolioView({ portfolio }: Props) {
  const [live, setLive] = useState<LivePortfolioPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [bookId, setBookId] = useState<BookId>("idx");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<keyof LivePosition | "">("return_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [tick, setTick] = useState(0);
  const prevPrices = useRef<Record<string, number>>({});

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`/api/portfolio/live?t=${Date.now()}`, {
        cache: "no-store",
      });
      const data = (await res.json()) as LivePortfolioPayload;
      if (!res.ok || data.error) {
        setError(data.error || `HTTP ${res.status}`);
      } else {
        setError(null);
      }
      if (data.books?.length) {
        setLive(data);
        setTick((n) => n + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal fetch live");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [refresh]);

  const books = live?.books ?? [];
  const active: LiveBook | undefined =
    books.find((b) => b.id === bookId) ?? books[0];

  const filtered = useMemo(() => {
    if (!active) return [];
    let rows = [...active.positions];
    const q = query.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (r) =>
          r.symbol.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q) ||
          r.thesis.toLowerCase().includes(q)
      );
    }
    const key = sortKey || "return_pct";
    const mul = sortDir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (typeof av === "number" && typeof bv === "number") {
        return mul * (av - bv);
      }
      return mul * String(av ?? "").localeCompare(String(bv ?? ""), "id");
    });
    return rows;
  }, [active, query, sortKey, sortDir]);

  // Track price direction vs previous poll for flash
  const priceDelta = useMemo(() => {
    const map: Record<string, number> = {};
    if (!active) return map;
    for (const p of active.positions) {
      if (p.price == null) continue;
      const key = `${active.id}:${p.symbol}`;
      const prev = prevPrices.current[key];
      if (prev != null && prev !== p.price) {
        map[p.symbol] = p.price - prev;
      }
      prevPrices.current[key] = p.price;
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, active?.id]);

  function onSort(key: keyof LivePosition) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(
        key === "return_pct" || key === "pnl" || key === "change_pct"
          ? "desc"
          : "asc"
      );
    }
  }

  const asOfLabel = live?.asOf
    ? new Date(live.asOf).toLocaleString("id-ID", {
        timeZone: "Asia/Jakarta",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }) + " WIB"
    : "—";

  const heroRet = active?.portfolio_return_pct;
  const heroLabel = active?.label
    ? `${active.label} return (live)`
    : "Return (live)";

  if (!portfolio.available && !live?.books?.length && !loading) {
    return (
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div>
            <h2>Portfolio Review</h2>
            <p>
              Belum ada posisi. Sync <code>positions.json</code> dari skill
              portfolio-review.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <>
      <header className={styles.hero}>
        <div className={styles.brandBlock}>
          <p className={styles.eyebrow}>
            portfolio-review · mode {live?.mode || portfolio.mode}
            <span className={styles.livePill} title="Harga di-refresh otomatis">
              LIVE
            </span>
          </p>
          <h1 className={styles.brand}>Portfolio</h1>
          <p className={styles.tagline}>
            Harga &amp; fluktuasi realtime (Yahoo · CoinGecko). Entry tetap dari
            snapshot paper trade — P&amp;L dihitung ulang setiap {POLL_MS / 1000}
            d.
          </p>
          <p className={styles.metaInline}>
            Update: {asOfLabel}
            {live?.fxUsdIdr
              ? ` · USDIDR ${Math.round(live.fxUsdIdr).toLocaleString("id-ID")}`
              : ""}
            {live?.totalPnlIdr != null
              ? ` · Total P&L ${fmtMoney(live.totalPnlIdr, "IDR")}`
              : ""}
          </p>
        </div>
        <div className={styles.heroStat} aria-live="polite">
          <span className={styles.heroStatLabel}>{heroLabel}</span>
          <strong className={`${styles.heroStatValue} ${retTone(heroRet)}`}>
            {fmtPct(heroRet)}
          </strong>
          <span className={styles.heroStatMeta}>
            {loading && !live ? "Memuat…" : `refresh ${asOfLabel}`}
          </span>
        </div>
      </header>

      {error && (
        <p className={styles.liveError} role="alert">
          Live feed: {error} — menampilkan data terakhir yang berhasil.
        </p>
      )}

      <section className={styles.summaryGrid} aria-label="Ringkasan lintas pasar">
        {books.length
          ? books.map((b) => (
              <article key={b.id} className={styles.summaryCard}>
                <div className={styles.summaryTop}>
                  <strong>{b.label}</strong>
                  <span className={`${styles.badge} ${styles.badgeLive}`}>LIVE</span>
                </div>
                <p
                  className={`${styles.summaryRet} ${retTone(b.portfolio_return_pct)}`}
                >
                  {fmtPct(b.portfolio_return_pct)}
                  <small className={styles.summaryPnl}>
                    {" "}
                    · {fmtMoney(b.portfolio_pnl, b.currency)}
                  </small>
                </p>
                <small>
                  Menang {b.winners}/{b.positions.length}
                  {b.review_at ? ` · review ${b.review_at}` : ""}
                </small>
              </article>
            ))
          : ["IDX", "US", "Crypto"].map((label) => (
              <article key={label} className={styles.summaryCard}>
                <div className={styles.summaryTop}>
                  <strong>{label}</strong>
                  <span className={`${styles.badge} ${styles.badgeNeutral}`}>
                    {loading ? "…" : "—"}
                  </span>
                </div>
                <p className={styles.summaryRet}>
                  {loading ? "Mengambil harga live…" : "Belum ada data"}
                </p>
                <small>
                  {error
                    ? "Gagal fetch — coba Refresh"
                    : "Yahoo · CoinGecko · ~20s refresh"}
                </small>
              </article>
            ))}
      </section>

      {portfolio.priorityNote && (
        <p className={styles.priorityNote}>{portfolio.priorityNote}</p>
      )}

      <nav className={styles.tabs} aria-label="Pilih buku portofolio">
        {(books.length
          ? books
          : [
              { id: "idx" as const, label: "IDX", positions: [] },
              { id: "us" as const, label: "US", positions: [] },
              { id: "crypto" as const, label: "Crypto", positions: [] },
            ]
        ).map((b) => (
          <button
            key={b.id}
            type="button"
            className={b.id === bookId ? styles.tabActive : styles.tab}
            onClick={() => {
              setBookId(b.id);
              setQuery("");
            }}
          >
            <span>{b.label}</span>
            <small>
              {"positions" in b && b.positions.length
                ? `${b.positions.length} posisi`
                : "—"}
            </small>
          </button>
        ))}
      </nav>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div>
            <h2>
              {active?.label ?? "Detail"} — harga saat ini
            </h2>
            <p>
              {active
                ? `${fmtPct(active.portfolio_return_pct)} · ${fmtMoney(
                    active.portfolio_pnl,
                    active.currency
                  )} · entry ${active.entry_date || "—"}`
                : "Memuat posisi…"}
            </p>
          </div>
          <div className={styles.liveActions}>
            <button
              type="button"
              className={styles.refreshBtn}
              onClick={() => refresh()}
              disabled={loading}
            >
              Refresh
            </button>
            <p className={styles.updated}>Auto {POLL_MS / 1000}s</p>
          </div>
        </div>

        <div className={styles.filters}>
          <label className={styles.field}>
            <span>Cari</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ticker, thesis…"
            />
          </label>
        </div>

        {!active?.positions.length ? (
          <p className={styles.empty}>
            {loading ? "Mengambil harga live…" : "Belum ada posisi."}
          </p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  {(
                    [
                      ["symbol", "Saham"],
                      ["entry_price", "Entry"],
                      ["price", "Sekarang"],
                      ["change_pct", "Hari ini"],
                      ["return_pct", "Return"],
                      ["pnl", "P&L"],
                      ["quality", "Q"],
                      ["hint", "Hint"],
                    ] as [keyof LivePosition, string][]
                  ).map(([key, label]) => (
                    <th key={key}>
                      <button
                        type="button"
                        className={styles.sortBtn}
                        onClick={() => onSort(key)}
                      >
                        {label}
                        {sortKey === key
                          ? sortDir === "asc"
                            ? " ↑"
                            : " ↓"
                          : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => {
                  const delta = priceDelta[row.symbol] ?? 0;
                  const flash =
                    delta > 0
                      ? styles.flashUp
                      : delta < 0
                        ? styles.flashDown
                        : flashClass(row.change_pct);
                  return (
                    <tr key={row.symbol}>
                      <td>
                        <strong>{row.symbol}</strong>
                        <div className={styles.cellMuted}>
                          {row.name.slice(0, 28)}
                        </div>
                      </td>
                      <td>
                        {fmtPrice(row.entry_price, active.currency)}
                      </td>
                      <td className={flash}>
                        <strong>
                          {fmtPrice(row.price, active.currency)}
                        </strong>
                      </td>
                      <td className={retTone(row.change_pct)}>
                        {fmtPct(row.change_pct)}
                      </td>
                      <td>
                        <span
                          className={`${styles.uv} ${retTone(row.return_pct)}`}
                        >
                          {fmtPct(row.return_pct)}
                        </span>
                      </td>
                      <td className={retTone(
                        row.pnl == null ? null : row.pnl > 0 ? 1 : row.pnl < 0 ? -1 : 0
                      )}>
                        {fmtMoney(row.pnl, active.currency)}
                      </td>
                      <td>{row.quality || "—"}</td>
                      <td>
                        <span
                          className={`${styles.badge} ${actionClass(row.hint)}`}
                        >
                          {row.hint}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!filtered.length && (
              <p className={styles.empty}>Tidak ada baris yang cocok filter.</p>
            )}
          </div>
        )}

        <footer className={styles.meta}>
          <p>
            {live?.source
              ? `Sumber harga: ${live.source} (server-side).`
              : portfolio.disclaimer}
          </p>
          <p>
            Paper trade ≠ uang real. Fluktuasi &quot;Hari ini&quot; = vs previous
            close. Hint UI heuristik, bukan exit otomatis.
          </p>
        </footer>
      </section>
    </>
  );
}
