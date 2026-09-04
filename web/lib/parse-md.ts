export type MarketId = "idx" | "us" | "crypto";

export type MarketReport = {
  id: MarketId;
  label: string;
  title: string;
  summary: string;
  metaLines: string[];
  headers: string[];
  rows: Record<string, string>[];
  updatedLabel: string;
  available: boolean;
};

const MARKET_META: Record<MarketId, { label: string; folder: string }> = {
  idx: { label: "IDX", folder: "idx" },
  us: { label: "US", folder: "us" },
  crypto: { label: "Crypto", folder: "crypto" },
};

function stripMd(cell: string): string {
  return cell
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/\\\|/g, "|")
    .trim();
}

function parsePercent(value: string): number {
  const m = value.replace(/,/g, "").match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : Number.NaN;
}

/** Parse first GFM table in markdown into headers + row objects. */
export function parseFirstTable(md: string): {
  headers: string[];
  rows: Record<string, string>[];
} {
  const lines = md.split(/\r?\n/);
  let start = -1;
  for (let i = 0; i < lines.length - 1; i++) {
    if (
      lines[i].trim().startsWith("|") &&
      /^\|?\s*:?-{3,}/.test(lines[i + 1].trim())
    ) {
      start = i;
      break;
    }
  }
  if (start < 0) return { headers: [], rows: [] };

  const splitRow = (line: string) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map(stripMd);

  const headers = splitRow(lines[start]);
  const rows: Record<string, string>[] = [];
  for (let i = start + 2; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line.startsWith("|")) break;
    const cells = splitRow(line);
    if (cells.every((c) => !c)) continue;
    const row: Record<string, string> = {};
    headers.forEach((h, idx) => {
      row[h] = cells[idx] ?? "";
    });
    rows.push(row);
  }
  return { headers, rows };
}

function extractTitle(md: string): string {
  const m = md.match(/^#\s+(.+)$/m);
  return m ? stripMd(m[1]) : "Laporan";
}

function extractSummary(md: string): string {
  const lines = md.split(/\r?\n/).map((l) => l.trim());
  for (const line of lines) {
    if (!line || line.startsWith("#") || line.startsWith("|")) continue;
    if (line.startsWith(">") || line.startsWith("_")) continue;
    return stripMd(line.replace(/\*\*/g, ""));
  }
  return "";
}

function extractMetaLines(md: string): string[] {
  return md
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.startsWith("_") && l.endsWith("_"))
    .map((l) => stripMd(l.replace(/^_+|_+$/g, "")));
}

export function undervaluedKey(headers: string[]): string | null {
  return (
    headers.find((h) => /undervalued/i.test(h)) ??
    headers.find((h) => /uv/i.test(h)) ??
    null
  );
}

export function symbolKey(headers: string[]): string | null {
  return (
    headers.find((h) => /^(saham|coin|ticker|symbol)$/i.test(h)) ??
    headers[0] ??
    null
  );
}

export function qualityKey(headers: string[]): string | null {
  return (
    headers.find((h) => /kualitas|grade/i.test(h)) ?? null
  );
}

export function sortByUndervalued(
  rows: Record<string, string>[],
  headers: string[],
  dir: "desc" | "asc" = "desc"
): Record<string, string>[] {
  const key = undervaluedKey(headers);
  if (!key) return rows;
  const mul = dir === "desc" ? -1 : 1;
  return [...rows].sort(
    (a, b) => mul * ((parsePercent(a[key]) || 0) - (parsePercent(b[key]) || 0))
  );
}

export function parseMarketMarkdown(
  id: MarketId,
  md: string,
  sourceLabel: string
): MarketReport {
  const { headers, rows } = parseFirstTable(md);
  return {
    id,
    label: MARKET_META[id].label,
    title: extractTitle(md),
    summary: extractSummary(md),
    metaLines: extractMetaLines(md),
    headers,
    rows: sortByUndervalued(rows, headers),
    updatedLabel: sourceLabel,
    available: headers.length > 0 && rows.length > 0,
  };
}

export { MARKET_META, parsePercent };
