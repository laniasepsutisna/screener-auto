"use client";

import { useMemo, useState } from "react";
import type { MarketId, MarketReport } from "@/lib/parse-md";
import {
  parsePercent,
  qualityKey,
  symbolKey,
  undervaluedKey,
} from "@/lib/parse-md";
import styles from "./dashboard.module.css";

type Props = {
  reports: MarketReport[];
};

type SortDir = "asc" | "desc";

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

export default function Dashboard({ reports }: Props) {
  const available = reports.filter((r) => r.available);
  const [market, setMarket] = useState<MarketId>(
    available[0]?.id ?? reports[0]?.id ?? "idx"
  );
  const [query, setQuery] = useState("");
  const [quality, setQuality] = useState("all");
  const [minUv, setMinUv] = useState(0);
  const [sortKey, setSortKey] = useState<string>("");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const active = reports.find((r) => r.id === market) ?? reports[0];
  const uvCol = active ? undervaluedKey(active.headers) : null;
  const symCol = active ? symbolKey(active.headers) : null;
  const qCol = active ? qualityKey(active.headers) : null;

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
      rows = rows.filter((r) => (parsePercent(r[uvCol]) || 0) >= minUv);
    }
    const key = sortKey || uvCol || active.headers[0];
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
  }, [active, query, quality, minUv, sortKey, sortDir, uvCol, symCol, qCol]);

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

  const topUv =
    uvCol && filtered[0] ? parsePercent(filtered[0][uvCol]) : Number.NaN;

  return (
    <div className={styles.shell}>
      <header className={styles.hero}>
        <div className={styles.brandBlock}>
          <p className={styles.eyebrow}>screener-auto · live dari GitHub</p>
          <h1 className={styles.brand}>Top Picks</h1>
          <p className={styles.tagline}>
            Undervalued screen harian untuk IDX, US, dan Crypto. Filter, sort,
            dan bandingkan kandidat sebelum entry.
          </p>
        </div>
        <div className={styles.heroStat} aria-live="polite">
          <span className={styles.heroStatLabel}>Top undervalued</span>
          <strong className={styles.heroStatValue}>
            {Number.isNaN(topUv) ? "—" : `${Math.round(topUv)}%`}
          </strong>
          <span className={styles.heroStatMeta}>
            {filtered.length} baris · {active.updatedLabel}
          </span>
        </div>
      </header>

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
          <p className={styles.updated}>Update: {active.updatedLabel}</p>
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
                        {sortKey === h ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((row, i) => (
                  <tr key={`${i}-${symCol ? row[symCol] : i}`}>
                    {active.headers.map((h) => {
                      const val = row[h] ?? "";
                      const isUv = uvCol === h;
                      const isQ = qCol === h;
                      const pct = isUv ? parsePercent(val) : Number.NaN;
                      return (
                        <td key={h}>
                          {isUv ? (
                            <span className={`${styles.uv} ${uvTone(pct)}`}>
                              {val}
                            </span>
                          ) : isQ ? (
                            <span className={`${styles.badge} ${badgeClass(val)}`}>
                              {val}
                            </span>
                          ) : (
                            val
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
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
          </footer>
        )}
      </section>

      <p className={styles.disclaimer}>
        Heuristik Tuntun-style. Bukan saran investasi. Deploy gratis di Vercel
        dari repo GitHub.
      </p>
    </div>
  );
}
