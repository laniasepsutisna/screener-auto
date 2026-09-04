"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LivePicksPayload } from "@/lib/live-picks-types";
import type { MarketId, MarketReport } from "@/lib/parse-md";
import {
  parsePercent,
  qualityKey,
  symbolKey,
  undervaluedKey,
} from "@/lib/parse-md";
import {
  extractTicker,
  fairValueColumnKey,
  formatLivePrice,
  parseFairMid,
  priceColumnKey,
} from "@/lib/pick-symbols";
import styles from "./dashboard.module.css";

type Props = {
  reports: MarketReport[];
  embedded?: boolean;
};

type SortDir = "asc" | "desc";

const POLL_MS = 20_000;

function badgeClass(value: string): string {
  const v = value.toLowerCase();
  if (/(best|a\b|beli$)/.test(v)) return styles.badgeGood;
  if (/(bagus|b\b|selektif)/.test(v)) return styles.badgeMid;
  if (/(tunggu|hindari|c\b|d\b)/.test(v)) return styles.badgeWarn;
  return styles.badgeNeutral;
}

function uvTone(pct: number): string {
  if (Number.isNaN(pct)) return "";
  if (pct >= 40) return styles.uvHot;
  if (pct >= 20) return styles.uvWarm;
  return styles.uvCool;
}

function fmtChangePct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function flashClass(changePct: number | null | undefined): string {
  if (changePct == null) return "";
  if (changePct > 0.01) return styles.flashUp;
  if (changePct < -0.01) return styles.flashDown;
  return "";
}

export default function Dashboard({ reports, embedded = false }: Props) {
  const available = reports.filter((r) => r.available);
  const [market, setMarket] = useState<MarketId>(
    available[0]?.id ?? reports[0]?.id ?? "idx"
  );
  const [query, setQuery] = useState("");
  const [quality, setQuality] = useState("all");
  const [minUv, setMinUv] = useState(0);
  const [sortKey, setSortKey] = useState<string>("");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [live, setLive] = useState<LivePicksPayload | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveLoading, setLiveLoading] = useState(true);
  const prevPrices = useRef<Record<string, number>>({});

  const active = reports.find((r) => r.id === market) ?? reports[0];
  const uvCol = active ? undervaluedKey(active.headers) : null;
  const symCol = active ? symbolKey(active.headers) : null;
  const qCol = active ? qualityKey(active.headers) : null;
  const priceCol = active ? priceColumnKey(active.headers) : null;

  const pickRequest = useMemo(() => {
    return reports
      .filter((r) => r.available)
      .map((r) => {
        const symKey = symbolKey(r.headers);
        const fairKey = fairValueColumnKey(r.headers);
        if (!symKey) return null;
        const fairMids: Record<string, number | null> = {};
        const symbols = r.rows.map((row) => {
          const ticker = extractTicker(row[symKey] ?? "");
          if (fairKey) {
            fairMids[ticker] = parseFairMid(row[fairKey] ?? "");
          }
          return ticker;
        });
        return { id: r.id, symbols, fairMids };
      })
      .filter(Boolean) as Array<{
      id: MarketId;
      symbols: string[];
      fairMids: Record<string, number | null>;
    }>;
  }, [reports]);

  const refreshLive = useCallback(async () => {
    if (!pickRequest.length) {
      setLiveLoading(false);
      return;
    }
    try {
      const res = await fetch("/api/picks/live", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markets: pickRequest }),
        cache: "no-store",
      });
      const data = (await res.json()) as LivePicksPayload;
      if (!res.ok || data.error) {
        setLiveError(data.error || `HTTP ${res.status}`);
      } else {
        setLiveError(null);
      }
      if (data.markets?.length) setLive(data);
    } catch (e) {
      setLiveError(e instanceof Error ? e.message : "Gagal fetch live");
    } finally {
      setLiveLoading(false);
    }
  }, [pickRequest]);

  useEffect(() => {
    refreshLive();
    const id = setInterval(refreshLive, POLL_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") refreshLive();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [refreshLive]);

  const liveByMarket = useMemo(() => {
    const map = new Map<string, Map<string, LivePicksPayload["markets"][0]["quotes"][0]>>();
    for (const m of live?.markets ?? []) {
      const inner = new Map<string, LivePicksPayload["markets"][0]["quotes"][0]>();
      for (const q of m.quotes) inner.set(q.symbol, q);
      map.set(m.id, inner);
    }
    return map;
  }, [live]);

  const qualities = useMemo(() => {
    if (!active || !qCol) return [] as string[];
    return Array.from(
      new Set(active.rows.map((r) => r[qCol]).filter(Boolean))
    ).sort();
  }, [active, qCol]);

  const filtered = useMemo(() => {
    if (!active) return [];
    let rows = [...active.rows];
    const q = query.trim().toLowerCase();
    if (q && symCol) {
      rows = rows.filter((r) =>
        Object.values(r).some((c) => c.toLowerCase().includes(q))
      );
    }
    if (quality !== "all" && qCol) {
      rows = rows.filter((r) => r[qCol] === quality);
    }
    if (minUv > 0 && uvCol) {
      rows = rows.filter((r) => {
        const ticker = symCol ? extractTicker(r[symCol] ?? "") : "";
        const liveUv = liveByMarket.get(active.id)?.get(ticker)?.undervalued_pct;
        const uv =
          liveUv != null && !Number.isNaN(liveUv)
            ? liveUv
            : parsePercent(r[uvCol]) || 0;
        return uv >= minUv;
      });
    }
    const key = sortKey || uvCol || active.headers[0];
    if (key) {
      const mul = sortDir === "asc" ? 1 : -1;
      rows.sort((a, b) => {
        let av = a[key] ?? "";
        let bv = b[key] ?? "";
        if (uvCol && key === uvCol && symCol) {
          const aTicker = extractTicker(a[symCol] ?? "");
          const bTicker = extractTicker(b[symCol] ?? "");
          const aLive = liveByMarket.get(active.id)?.get(aTicker)?.undervalued_pct;
          const bLive = liveByMarket.get(active.id)?.get(bTicker)?.undervalued_pct;
          if (aLive != null) av = `${Math.round(aLive)}%`;
          if (bLive != null) bv = `${Math.round(bLive)}%`;
        }
        const an = parsePercent(av);
        const bn = parsePercent(bv);
        if (!Number.isNaN(an) && !Number.isNaN(bn)) return mul * (an - bn);
        return mul * av.localeCompare(bv, "id", { sensitivity: "base" });
      });
    }
    return rows;
  }, [
    active,
    query,
    quality,
    minUv,
    sortKey,
    sortDir,
    uvCol,
    symCol,
    qCol,
    liveByMarket,
  ]);

  const priceDelta = useMemo(() => {
    if (!active || !symCol || !priceCol) return {} as Record<string, number>;
    const map: Record<string, number> = {};
    const quotes = liveByMarket.get(active.id);
    for (const row of filtered) {
      const ticker = extractTicker(row[symCol] ?? "");
      const price = quotes?.get(ticker)?.price;
      if (price == null) continue;
      const key = `${active.id}:${ticker}`;
      const prev = prevPrices.current[key];
      if (prev != null && prev !== price) map[ticker] = price - prev;
      prevPrices.current[key] = price;
    }
    return map;
  }, [active, symCol, priceCol, filtered, liveByMarket, live?.asOf]);

  function onSort(header: string) {
    if (sortKey === header) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(header);
      setSortDir(/undervalued|uv|%/i.test(header) ? "desc" : "asc");
    }
  }

  function switchMarket(id: MarketId) {
    setMarket(id);
    setQuery("");
    setQuality("all");
    setMinUv(0);
    setSortKey("");
    setSortDir("desc");
  }

  if (!active) {
    return <p className={styles.empty}>Belum ada laporan.</p>;
  }

  const topRow = filtered[0];
  const topTicker = topRow && symCol ? extractTicker(topRow[symCol] ?? "") : "";
  const topLiveUv = topTicker
    ? liveByMarket.get(active.id)?.get(topTicker)?.undervalued_pct
    : null;
  const topUv =
    topLiveUv != null && !Number.isNaN(topLiveUv)
      ? topLiveUv
      : uvCol && topRow
        ? parsePercent(topRow[uvCol])
        : Number.NaN;

  const asOfLabel = live?.asOf
    ? new Date(live.asOf).toLocaleString("id-ID", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : null;

  return (
    <div className={embedded ? undefined : styles.shell}>
      <header className={styles.hero}>
        <div className={styles.brandBlock}>
          <p className={styles.eyebrow}>
            screener-auto · live dari GitHub
            <span className={styles.livePill} title="Harga di-refresh otomatis">
              LIVE
            </span>
          </p>
          <h1 className={styles.brand}>Top Picks</h1>
          <p className={styles.tagline}>
            Undervalued screen harian untuk IDX, US, dan Crypto. Harga pasar
            realtime (Yahoo · CoinGecko), filter, sort, dan bandingkan kandidat
            sebelum entry.
          </p>
        </div>
        <div className={styles.heroStat} aria-live="polite">
          <span className={styles.heroStatLabel}>Top undervalued</span>
          <strong className={styles.heroStatValue}>
            {Number.isNaN(topUv) ? "—" : `${Math.round(topUv)}%`}
          </strong>
          <span className={styles.heroStatMeta}>
            {filtered.length} baris · {active.updatedLabel}
            {asOfLabel ? ` · harga ${asOfLabel}` : ""}
          </span>
        </div>
      </header>

      {liveError && (
        <p className={styles.liveError} role="alert">
          Live feed: {liveError} — menampilkan harga dari laporan terakhir.
        </p>
      )}

      <nav className={styles.tabs} aria-label="Pilih pasar">
        {reports.map((r) => (
          <button
            key={r.id}
            type="button"
            className={r.id === market ? styles.tabActive : styles.tab}
            onClick={() => switchMarket(r.id)}
            disabled={!r.available && r.id !== market}
          >
            <span>{r.label}</span>
            <small>{r.available ? `${r.rows.length} picks` : "kosong"}</small>
          </button>
        ))}
      </nav>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div>
            <h2>{active.title}</h2>
            <p>{active.summary || "Laporan screener terbaru."}</p>
          </div>
          <p className={styles.updated}>
            Update: {active.updatedLabel}
            {asOfLabel ? ` · harga live ${asOfLabel}` : ""}
          </p>
        </div>

        <div className={styles.filters}>
          <label className={styles.field}>
            <span>Cari</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ticker, nama, guidance…"
            />
          </label>
          <label className={styles.field}>
            <span>Kualitas / Grade</span>
            <select
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
              disabled={!qualities.length}
            >
              <option value="all">Semua</option>
              {qualities.map((q) => (
                <option key={q} value={q}>
                  {q}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.field}>
            <span>Min undervalued %</span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={minUv}
              onChange={(e) => setMinUv(Number(e.target.value) || 0)}
            />
          </label>
        </div>

        {!active.available ? (
          <p className={styles.empty}>
            Belum ada tabel untuk pasar ini. Jalankan pipeline lalu push report.
          </p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  {active.headers.map((h) => (
                    <th key={h}>
                      <button
                        type="button"
                        className={styles.sortBtn}
                        onClick={() => onSort(h)}
                      >
                        {h}
                        {priceCol === h ? (
                          <span className={`${styles.badge} ${styles.badgeLive}`}>
                            LIVE
                          </span>
                        ) : null}
                        {sortKey === h ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((row, i) => {
                  const ticker = symCol ? extractTicker(row[symCol] ?? "") : "";
                  const quote = ticker
                    ? liveByMarket.get(active.id)?.get(ticker)
                    : undefined;
                  return (
                    <tr key={`${i}-${symCol ? row[symCol] : i}`}>
                      {active.headers.map((h) => {
                        const val = row[h] ?? "";
                        const isUv = uvCol === h;
                        const isQ = qCol === h;
                        const isPrice = priceCol === h;
                        const liveUv = quote?.undervalued_pct;
                        const pct = isUv
                          ? liveUv != null && !Number.isNaN(liveUv)
                            ? liveUv
                            : parsePercent(val)
                          : Number.NaN;
                        const uvDisplay =
                          isUv && liveUv != null && !Number.isNaN(liveUv)
                            ? `${Math.round(liveUv)}%`
                            : val;
                        const delta = priceDelta[ticker] ?? 0;
                        const flash =
                          isPrice && quote?.change_pct != null
                            ? flashClass(quote.change_pct)
                            : delta > 0
                              ? styles.flashUp
                              : delta < 0
                                ? styles.flashDown
                                : "";
                        return (
                          <td key={h}>
                            {isUv ? (
                              <span className={`${styles.uv} ${uvTone(pct)}`}>
                                {uvDisplay}
                              </span>
                            ) : isQ ? (
                              <span
                                className={`${styles.badge} ${badgeClass(val)}`}
                              >
                                {val}
                              </span>
                            ) : isPrice && quote?.price != null ? (
                              <span className={flash}>
                                {formatLivePrice(quote.price, active.id)}
                                {quote.change_pct != null ? (
                                  <span className={styles.cellMuted}>
                                    {fmtChangePct(quote.change_pct)} hari ini
                                  </span>
                                ) : liveLoading ? (
                                  <span className={styles.cellMuted}>
                                    memuat…
                                  </span>
                                ) : null}
                              </span>
                            ) : isPrice && liveLoading ? (
                              <span className={styles.cellMuted}>{val}…</span>
                            ) : (
                              val
                            )}
                          </td>
                        );
                      })}
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

        {!!active.metaLines.length && (
          <footer className={styles.meta}>
            {active.metaLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
            {live?.source ? (
              <p>
                Harga live: {live.source} (refresh ~{POLL_MS / 1000}s).
                Undervalued % dihitung ulang dari harga wajar laporan.
              </p>
            ) : null}
          </footer>
        )}
      </section>

      {!embedded && (
        <p className={styles.disclaimer}>
          Heuristik Tuntun-style. Bukan saran investasi. Deploy gratis di Vercel
          dari repo GitHub.
        </p>
      )}
    </div>
  );
}
