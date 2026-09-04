"use client";

import { useState } from "react";
import type { MarketReport } from "@/lib/parse-md";
import type { PortfolioReport } from "@/lib/parse-portfolio";
import Dashboard from "./Dashboard";
import PortfolioView from "./PortfolioView";
import styles from "./dashboard.module.css";

type ViewId = "picks" | "portfolio";

type Props = {
  reports: MarketReport[];
  portfolio: PortfolioReport;
};

export default function AppShell({ reports, portfolio }: Props) {
  const [view, setView] = useState<ViewId>("picks");

  return (
    <div className={styles.shell}>
      <div className={styles.viewSwitch} role="tablist" aria-label="Mode dashboard">
        <button
          type="button"
          role="tab"
          aria-selected={view === "picks"}
          className={
            view === "picks" ? styles.viewTabActive : styles.viewTab
          }
          onClick={() => setView("picks")}
        >
          Top Picks
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "portfolio"}
          className={
            view === "portfolio" ? styles.viewTabActive : styles.viewTab
          }
          onClick={() => setView("portfolio")}
        >
          Portfolio
          {portfolio.available ? (
            <small>
              {portfolio.books.reduce((n, b) => n + b.rows.length, 0)} posisi
            </small>
          ) : (
            <small>kosong</small>
          )}
        </button>
      </div>

      {view === "picks" ? (
        <Dashboard reports={reports} embedded />
      ) : (
        <PortfolioView portfolio={portfolio} />
      )}

      <p className={styles.disclaimer}>
        Heuristik Tuntun-style · paper trade virtual. Bukan saran investasi.
        Deploy gratis di Vercel dari repo GitHub.
      </p>
    </div>
  );
}
