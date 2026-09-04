import fs from "fs";
import path from "path";
import {
  MARKET_META,
  parseMarketMarkdown,
  type MarketId,
  type MarketReport,
} from "./parse-md";

const GITHUB_RAW =
  "https://raw.githubusercontent.com/laniasepsutisna/screener-auto/main/reports";

function localReportsRoot(): string | null {
  const candidates = [
    path.join(process.cwd(), "reports"),
    path.join(process.cwd(), "..", "reports"),
  ];
  for (const dir of candidates) {
    if (fs.existsSync(dir)) return dir;
  }
  return null;
}

function listDatedFilesLocal(root: string, folder: string): string[] {
  const dir = path.join(root, folder);
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.md$/.test(f))
    .map((f) => f.replace(/\.md$/, ""))
    .sort()
    .reverse();
}

function readLatestLocal(
  root: string,
  folder: string
): { md: string; label: string } | null {
  const dir = path.join(root, folder);
  const latestPath = path.join(dir, "latest.md");
  if (fs.existsSync(latestPath)) {
    const dates = listDatedFilesLocal(root, folder);
    return {
      md: fs.readFileSync(latestPath, "utf8"),
      label: dates[0] ? `latest · ${dates[0]}` : "latest",
    };
  }
  const dates = listDatedFilesLocal(root, folder);
  if (!dates.length) return null;
  return {
    md: fs.readFileSync(path.join(dir, `${dates[0]}.md`), "utf8"),
    label: dates[0],
  };
}

async function fetchText(url: string): Promise<string | null> {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const text = await res.text();
    return text.trim() ? text : null;
  } catch {
    return null;
  }
}

async function readLatestRemote(
  folder: string
): Promise<{ md: string; label: string } | null> {
  const md = await fetchText(`${GITHUB_RAW}/${folder}/latest.md`);
  if (!md) return null;
  return { md, label: "latest · github" };
}

function emptyReport(id: MarketId): MarketReport {
  return {
    id,
    label: MARKET_META[id].label,
    title: `${MARKET_META[id].label} — belum ada laporan`,
    summary:
      "Jalankan screener lalu push ke GitHub agar data muncul di sini.",
    metaLines: [],
    headers: [],
    rows: [],
    updatedLabel: "—",
    available: false,
  };
}

export async function loadAllReports(): Promise<MarketReport[]> {
  const root = localReportsRoot();
  const ids = Object.keys(MARKET_META) as MarketId[];

  return Promise.all(
    ids.map(async (id) => {
      const folder = MARKET_META[id].folder;
      const data = root
        ? readLatestLocal(root, folder)
        : await readLatestRemote(folder);
      if (!data) return emptyReport(id);
      return parseMarketMarkdown(id, data.md, data.label);
    })
  );
}
