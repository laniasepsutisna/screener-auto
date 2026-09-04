"use client";

import { useMemo, useState } from "react";
import { parsePercent } from "@/lib/parse-md";
import type {
  PortfolioBook,
  PortfolioMarketId,
  PortfolioReport,
} from "@/lib/parse-portfolio";
import styles from "./dashboard.module.css";

type Props = {
  portfolio: PortfolioReport;
};

type SortDir = "asc" | "desc";

function retTone(pct: number): string {
  if (Number.isNaN(pct)) return "";
  if (pct > 0.15) return styles.retPos;
  if (pct < -0.15) return styles.retNeg;
  return styles.retFlat;
}

function actionHint(row: Record<string, string>, headers: string[]): string {
  const retKey = headers.find((h) => /^return$/i.test(h));
  const statusKey = headers.find((h) => /status/i.test(h));
  const status = statusKey ? (row[statusKey] || "").toLowerCase() : "";
  if (/sl|stopped|closed/.test(status)) return "SL";
  if (/tp|taken/.test(status)) return "TP";
  const pct = retKey ? parsePercent(row[retKey]) : Number.NaN;
  if (!Number.isNaN(pct) && pct <= -8) return "Review";
  if (!Number.isNaN(pct) && pct >= 8) return "Scale?";
  return "Hold";
}

function actionClass(action: string): string {
  if (action === "SL") return styles.badgeWarn;
  if (action === "TP" || action === "Scale?") return styles.badgeGood;
  if (action === "Review") return styles.badgeMid;
  return styles.badgeNeutral;
}

export default function PortfolioView({ portfolio }: Props) {
  const available = portfolio.books.filter((b) => b.available);
  const [bookId, setBookId] = useState<PortfolioMarketId>(
    available[0]?.id ?? "idx"
  );
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const active: PortfolioBook =
    portfolio.books.find((b) => b.id === bookId) ?? portfolio.books[0];

  const retCol =
    active?.headers.find((h) => /^return$/i.test(h)) ??
    active?.headers.find((h) => /return/i.test(h)) ??
    null;

  const filtered = useMemo(() => {
    if (!active) return [];
    let rows = [...active.rows];
    const q = query.trim().toLowerCase();
    if (q) {
      rows = rows.filter((r) =>
        Object.values(r).some((c) => c.toLowerCase().includes(q))
      );
    }
    const key = sortKey || retCol || active.headers[0];
    if (key) {
      const mul = sortDir === "asc" ? 1 : -1;
      rows.sort((a, b) => {
        const av = a[key] ?? "";
        const bv = b[key] ?? "";
        const an = parsePercent(av);
        const bn = parsePercent(bv);
        if (!Number.isNaN(an) && !Number.isNaN(bn)) return mul * (an - bn);
        return mul * av.localeCompare(bv, "id", { sensitivity: "base" });
      });
    }
    return rows;
  }, [active, query, sortKey, sortDir, retCol]);

  const heroRet = portfolio.summaryRows.find((r) =>
    /idx/i.test(r.market)
  )?.returnPct;
  const heroDisplay = Number.isNaN(heroRet ?? Number.NaN)
    ? portfolio.summaryRows[0]?.returnPct
    : heroRet;

  function onSort(header: string) {
    if (sortKey === header) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(header);
      setSortDir(/return|p&l|pnl/i.test(header) ? "desc" : "asc");
    }
  }

  function switchBook(id: PortfolioMarketId) {
    setBookId(id);
    setQuery("");
    setSortKey("");
    setSortDir("desc");
  }

  if (!portfolio.available) {
    return (
      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div>
            <h2>Portfolio Review</h2>
            <p>
              Belum ada laporan. Jalankan skill{" "}
              <code>portfolio-review</code> lalu copy ke{" "}
              <code>reports/portfolio/</code> dan push.
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
            portfolio-review · mode {portfolio.mode}
          </p>
          <h1 className={styles.brand}>Portfolio</h1>
          <p className={styles.tagline}>
            Status posisi paper trade IDX · US · Crypto — return, P&amp;L, dan
            hint aksi Hold / SL / TP.
          </p>
          {portfolio.meta && (
            <p className={styles.metaInline}>{portfolio.meta}</p>
          )}
        </div>
        <div className={styles.heroStat} aria-live="polite">
          <span className={styles.heroStatLabel}>IDX return</span>
          <strong className={styles.heroStatValue}>
            {heroDisplay == null || Number.isNaN(heroDisplay)
              ? "—"
              : `${heroDisplay > 0 ? "+" : ""}${heroDisplay.toFixed(2)}%`}
          </strong>
          <span className={styles.heroStatMeta}>
            {portfolio.updatedLabel}
          </span>
        </div>
      </header>

      {!!portfolio.summaryRows.length && (
        <section className={styles.summaryGrid} aria-label="Ringkasan lintas pasar">
          {portfolio.summaryRows.map((row) => (
            <article key={row.market} className={styles.summaryCard}>
              <div className={styles.summaryTop}>
                <strong>{row.market}</strong>
                <span className={`${styles.badge} ${styles.badgeNeutral}`}>
                  {row.status || "—"}
                </span>
              </div>
              <p className={`${styles.summaryRet} ${retTone(row.returnPct)}`}>
                {row.ret || "—"}
              </p>
              <small>{row.benchmark || "—"}</small>
            </article>
          ))}
        </section>
      )}

      {portfolio.priorityNote && (
        <p className={styles.priorityNote}>{portfolio.priorityNote}</p>
      )}

      <nav className={styles.tabs} aria-label="Pilih buku portofolio">
        {portfolio.books.map((b) => (
          <button
            key={b.id}
            type="button"
            className={b.id === bookId ? styles.tabActive : styles.tab}
            onClick={() => switchBook(b.id)}
            disabled={!b.available && b.id !== bookId}
          >
            <span>{b.label}</span>
            <small>
              {b.available ? `${b.rows.length} posisi` : "kosong"}
            </small>
          </button>
        ))}
      </nav>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <div>
            <h2>{active?.title ?? "Detail posisi"}</h2>
            <p>{active?.summary || "Posisi paper trade."}</p>
          </div>
          <p className={styles.updated}>Update: {portfolio.updatedLabel}</p>
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

        {!active?.available ? (
          <p className={styles.empty}>Belum ada posisi untuk pasar ini.</p>
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
                        {sortKey === h
                          ? sortDir === "asc"
                            ? " ↑"
                            : " ↓"
                          : ""}
                      </button>
                    </th>
                  ))}
                  <th>
                    <span className={styles.sortBtn}>Hint</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row, i) => {
                  const hint = actionHint(row, active.headers);
                  return (
                    <tr key={`${i}-${Object.values(row)[0]}`}>
                      {active.headers.map((h) => {
                        const val = row[h] ?? "";
                        const isRet = retCol === h;
                        const pct = isRet ? parsePercent(val) : Number.NaN;
                        return (
                          <td key={h}>
                            {isRet ? (
                              <span
                                className={`${styles.uv} ${retTone(pct)}`}
                              >
                                {val}
                              </span>
                            ) : (
                              val
                            )}
                          </td>
                        );
                      })}
                      <td>
                        <span
                          className={`${styles.badge} ${actionClass(hint)}`}
                        >
                          {hint}
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
          <p>{portfolio.disclaimer}</p>
          <p>
            Hint aksi bersifat heuristik UI (bukan protokol exit otomatis).
            Paper trade ≠ uang real.
          </p>
        </footer>
      </section>
    </>
  );
}
