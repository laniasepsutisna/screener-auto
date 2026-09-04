import fs from "fs";
import path from "path";
import {
  MARKET_META,
  parseMarketMarkdown,
  type MarketId,
  type MarketReport,
} from "./parse-md";

function reportsRoot(): string {
  // web/ → repo root → reports/
  return path.join(process.cwd(), "..", "reports");
}

function listDatedFiles(folder: string): string[] {
  const dir = path.join(reportsRoot(), folder);
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.md$/.test(f))
    .map((f) => f.replace(/\.md$/, ""))
    .sort()
    .reverse();
}

function readLatest(folder: string): { md: string; label: string } | null {
  const dir = path.join(reportsRoot(), folder);
  const latestPath = path.join(dir, "latest.md");
  if (fs.existsSync(latestPath)) {
    const dates = listDatedFiles(folder);
    return {
      md: fs.readFileSync(latestPath, "utf8"),
      label: dates[0] ? `latest · ${dates[0]}` : "latest",
    };
  }
  const dates = listDatedFiles(folder);
  if (!dates.length) return null;
  const file = path.join(dir, `${dates[0]}.md`);
  return {
    md: fs.readFileSync(file, "utf8"),
    label: dates[0],
  };
}

export function loadAllReports(): MarketReport[] {
  const ids = Object.keys(MARKET_META) as MarketId[];
  return ids.map((id) => {
    const folder = MARKET_META[id].folder;
    const data = readLatest(folder);
    if (!data) {
      return {
        id,
        label: MARKET_META[id].label,
        title: `${MARKET_META[id].label} — belum ada laporan`,
        summary: "Jalankan screener lalu push ke GitHub agar data muncul di sini.",
        metaLines: [],
        headers: [],
        rows: [],
        updatedLabel: "—",
        available: false,
      };
    }
    return parseMarketMarkdown(id, data.md, data.label);
  });
}

export function loadReportDates(): Record<MarketId, string[]> {
  const out = {} as Record<MarketId, string[]>;
  (Object.keys(MARKET_META) as MarketId[]).forEach((id) => {
    out[id] = listDatedFiles(MARKET_META[id].folder);
  });
  return out;
}
