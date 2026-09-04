import fs from "fs";
import path from "path";
import {
  emptyPortfolioReport,
  parsePortfolioMarkdown,
  type PortfolioReport,
} from "./parse-portfolio";

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

function listDated(folder: string, root: string): string[] {
  const dir = path.join(root, folder);
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.md$/.test(f))
    .map((f) => f.replace(/\.md$/, ""))
    .sort()
    .reverse();
}

function readLocal(folder: string): { md: string; label: string } | null {
  const root = localReportsRoot();
  if (!root) return null;
  const dir = path.join(root, folder);
  const latest = path.join(dir, "latest.md");
  if (fs.existsSync(latest)) {
    const dates = listDated(folder, root);
    return {
      md: fs.readFileSync(latest, "utf8"),
      label: dates[0] ? `latest · ${dates[0]}` : "latest",
    };
  }
  const dates = listDated(folder, root);
  if (!dates.length) return null;
  return {
    md: fs.readFileSync(path.join(dir, `${dates[0]}.md`), "utf8"),
    label: dates[0],
  };
}

async function readRemote(
  folder: string
): Promise<{ md: string; label: string } | null> {
  try {
    const res = await fetch(`${GITHUB_RAW}/${folder}/latest.md`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const md = await res.text();
    if (!md.trim()) return null;
    return { md, label: "latest · github" };
  } catch {
    return null;
  }
}

export async function loadPortfolioReport(): Promise<PortfolioReport> {
  const data = readLocal("portfolio") ?? (await readRemote("portfolio"));
  if (!data) return emptyPortfolioReport();
  return parsePortfolioMarkdown(data.md, data.label);
}
