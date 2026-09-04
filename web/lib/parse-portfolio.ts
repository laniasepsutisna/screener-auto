import { parseFirstTable, parsePercent } from "./parse-md";

function stripMd(cell: string): string {
  return cell
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/\\\|/g, "|")
    .trim();
}

export type PortfolioMarketId = "idx" | "us" | "crypto";

export type PortfolioSummaryRow = {
  market: string;
  status: string;
  ret: string;
  benchmark: string;
  returnPct: number;
};

export type PortfolioBook = {
  id: PortfolioMarketId;
  label: string;
  title: string;
  summary: string;
  headers: string[];
  rows: Record<string, string>[];
  available: boolean;
};

export type PortfolioReport = {
  title: string;
  meta: string;
  mode: string;
  updatedLabel: string;
  disclaimer: string;
  summaryRows: PortfolioSummaryRow[];
  books: PortfolioBook[];
  available: boolean;
  priorityNote: string;
};

const BOOK_META: { id: PortfolioMarketId; label: string; heading: RegExp }[] = [
  { id: "idx", label: "IDX", heading: /^###\s+IDX\b/i },
  { id: "us", label: "US", heading: /^###\s+US\b/i },
  { id: "crypto", label: "Crypto", heading: /^###\s+Crypto/i },
];

function extractFenceAfterHeading(md: string, headingRe: RegExp): string | null {
  const lines = md.split(/\r?\n/);
  let i = lines.findIndex((l) => headingRe.test(l.trim()));
  if (i < 0) return null;
  // find opening fence ~~~ or ```
  while (i < lines.length && !/^~{3,}|`{3,}/.test(lines[i].trim())) i++;
  if (i >= lines.length) return null;
  const fence = lines[i].trim().slice(0, 3);
  i++;
  const body: string[] = [];
  for (; i < lines.length; i++) {
    if (lines[i].trim().startsWith(fence)) break;
    body.push(lines[i]);
  }
  return body.join("\n").trim() || null;
}

function parseSummaryRows(md: string): PortfolioSummaryRow[] {
  // Prefer the first table under "## 1. Ringkasan"
  const section = md.split(/^##\s+2\./m)[0] ?? md;
  const { headers, rows } = parseFirstTable(section);
  if (!headers.length) return [];
  const pasarKey = headers.find((h) => /pasar/i.test(h)) ?? headers[0];
  const statusKey = headers.find((h) => /status/i.test(h)) ?? headers[1];
  const retKey =
    headers.find((h) => /return/i.test(h)) ??
    headers.find((h) => /portofolio/i.test(h)) ??
    headers[2];
  const benchKey = headers.find((h) => /benchmark/i.test(h)) ?? headers[3];

  return rows.map((r) => {
    const ret = r[retKey] ?? "";
    return {
      market: r[pasarKey] ?? "",
      status: r[statusKey] ?? "",
      ret,
      benchmark: r[benchKey] ?? "",
      returnPct: parsePercent(ret),
    };
  });
}

function parseBook(
  id: PortfolioMarketId,
  label: string,
  fenceMd: string | null
): PortfolioBook {
  if (!fenceMd) {
    return {
      id,
      label,
      title: `${label} — belum ada detail`,
      summary: "",
      headers: [],
      rows: [],
      available: false,
    };
  }
  const titleMatch = fenceMd.match(/^#\s+(.+)$/m);
  const title = titleMatch ? stripMd(titleMatch[1]) : `${label} Paper Trade`;
  const retLine =
    fenceMd
      .split(/\r?\n/)
      .map((l) => l.trim())
      .find((l) => /\*\*Return portofolio/i.test(l)) ?? "";
  const summary = stripMd(retLine.replace(/\*\*/g, ""));
  const { headers, rows } = parseFirstTable(fenceMd);
  return {
    id,
    label,
    title,
    summary,
    headers,
    rows,
    available: headers.length > 0 && rows.length > 0,
  };
}

export function parsePortfolioMarkdown(
  md: string,
  sourceLabel: string
): PortfolioReport {
  const titleMatch = md.match(/^#\s+(.+)$/m);
  const title = titleMatch ? stripMd(titleMatch[1]) : "Portfolio Review";
  const metaLine =
    md
      .split(/\r?\n/)
      .map((l) => l.trim())
      .find((l) => /\*\*Tanggal:\*\*/i.test(l) || /\*\*Mode:\*\*/i.test(l)) ?? "";
  const modeMatch = metaLine.match(/\*\*Mode:\*\*\s*([^|]+)/i);
  const mode = modeMatch ? stripMd(modeMatch[1]) : "Paper";
  const disclaimer =
    md
      .split(/\r?\n/)
      .map((l) => l.trim())
      .find((l) => l.startsWith(">") && /bukan saran/i.test(l))
      ?.replace(/^>\s*/, "") ??
    "Paper trade = virtual. Bukan saran investasi.";

  const priorityNote =
    md
      .split(/\r?\n/)
      .map((l) => l.trim())
      .find((l) => /\*\*Prioritas modal:\*\*/i.test(l))
      ?.replace(/\*\*/g, "") ?? "";

  const summaryRows = parseSummaryRows(md);
  const books = BOOK_META.map((b) =>
    parseBook(b.id, b.label, extractFenceAfterHeading(md, b.heading))
  );

  return {
    title,
    meta: stripMd(metaLine.replace(/\*\*/g, "")),
    mode,
    updatedLabel: sourceLabel,
    disclaimer,
    summaryRows,
    books,
    available: summaryRows.length > 0 || books.some((b) => b.available),
    priorityNote: stripMd(priorityNote),
  };
}

export function emptyPortfolioReport(): PortfolioReport {
  return {
    title: "Portfolio Review — belum ada laporan",
    meta: "",
    mode: "Paper",
    updatedLabel: "—",
    disclaimer: "Paper trade = virtual. Bukan saran investasi.",
    summaryRows: [],
    books: BOOK_META.map((b) => parseBook(b.id, b.label, null)),
    available: false,
    priorityNote: "",
  };
}
