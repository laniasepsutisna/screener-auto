#!/usr/bin/env python3
"""Yahoo Finance QC enrichment for IDX undervalued screener."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CACHE_ROOT = Path.home() / ".cache" / "idx-undervalued-screener" / "yfinance"

DEFAULT_MIN_LIQUIDITY_IDR = 500_000_000  # Rp 500 juta/hari


def fmt_idr(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000_000_000:
        return f"Rp {value / 1_000_000_000_000:.2f} triliun"
    if value >= 1_000_000_000:
        return f"Rp {value / 1_000_000_000:.1f} miliar"
    if value >= 1_000_000:
        return f"Rp {value / 1_000_000:.0f} juta"
    return f"Rp {value:,.0f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def yahoo_ticker(symbol: str) -> str:
    sym = symbol.upper().replace(".JK", "")
    return f"{sym}.JK"


def cache_path(symbol: str) -> Path:
    return CACHE_ROOT / date.today().isoformat() / f"{symbol.upper()}.json"


def load_yf_cache(symbol: str) -> dict[str, Any] | None:
    path = cache_path(symbol)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_yf_cache(symbol: str, data: dict[str, Any]) -> None:
    path = cache_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_pct_metric(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = str(value).replace("%", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_stockbit_cache(symbol: str) -> dict[str, Any] | None:
    root = Path.home() / ".cache" / "idx-undervalued-screener"
    for day_dir in sorted(root.glob("*"), reverse=True):
        if not day_dir.is_dir() or day_dir.name == "yfinance":
            continue
        path = day_dir / f"{symbol.upper()}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return None


def load_stockbit_summary(symbol: str) -> dict[str, Any] | None:
    """Load screener fields from cache/API; fallback ke keystats cache mentah."""
    sym = symbol.upper()
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from tuntun_undervalued_screener import fetch_stock, load_token

        token = load_token()
        row = fetch_stock(token, sym, light=True, use_cache=True)
        if row:
            return {
                "undervalued_pct": row.undervalued_pct,
                "quality": row.quality,
                "guidance_entry": row.guidance_entry,
                "guidance_hold": row.guidance_hold,
                "roe": row.roe,
                "debt_equity": row.debt_equity,
                "div_yield": row.div_yield,
                "rel_strength": row.rel_strength,
                "per_ttm": row.per_ttm,
                "pbv": row.pbv,
                "peg_forward": row.peg_forward,
            }
    except Exception:
        pass

    metrics = load_stockbit_cache(sym)
    if not metrics:
        return None
    return {
        "undervalued_pct": None,
        "quality": "",
        "guidance_entry": "",
        "guidance_hold": "",
        "roe": parse_pct_metric(metrics.get("Return on Equity (TTM)")),
        "debt_equity": parse_pct_metric(metrics.get("Debt to Equity Ratio (Quarter)")),
        "div_yield": parse_pct_metric(metrics.get("Dividend Yield")),
        "rel_strength": parse_pct_metric(metrics.get("Relative Strength Rating")),
        "per_ttm": parse_pct_metric(metrics.get("Current PE Ratio (TTM)")),
        "pbv": parse_pct_metric(metrics.get("Current Price to Book Value")),
        "peg_forward": parse_pct_metric(metrics.get("PEG (Forward)")),
        "keystats_only": True,
    }


def fetch_yahoo(symbol: str, *, use_cache: bool = True) -> dict[str, Any]:
    sym = symbol.upper().replace(".JK", "")
    if use_cache:
        cached = load_yf_cache(sym)
        if cached:
            return cached

    try:
        import yfinance as yf
    except ImportError:
        return {"symbol": sym, "error": "yfinance_not_installed"}

    ticker = yf.Ticker(yahoo_ticker(sym))
    info = ticker.info or {}
    hist = ticker.history(period="1mo", auto_adjust=True)
    hist_3m = ticker.history(period="3mo", auto_adjust=True)

    avg_volume = float(hist["Volume"].mean()) if not hist.empty else None
    last_close = float(hist["Close"].iloc[-1]) if not hist.empty else info.get("regularMarketPrice")
    avg_value_idr = None
    if avg_volume is not None and last_close is not None:
        avg_value_idr = avg_volume * float(last_close)

    ret_1m = None
    if len(hist) >= 2:
        first = float(hist["Close"].iloc[0])
        last = float(hist["Close"].iloc[-1])
        if first:
            ret_1m = (last / first - 1) * 100

    ret_3m = None
    if len(hist_3m) >= 2:
        first = float(hist_3m["Close"].iloc[0])
        last = float(hist_3m["Close"].iloc[-1])
        if first:
            ret_3m = (last / first - 1) * 100

    dividends: list[dict[str, Any]] = []
    try:
        actions = ticker.actions
        if actions is not None and not actions.empty and "Dividends" in actions.columns:
            div_series = actions["Dividends"].dropna()
            for ts, amount in div_series.tail(3).items():
                dividends.append(
                    {
                        "date": str(ts.date()),
                        "amount": float(amount),
                    }
                )
    except Exception:
        pass

    roe = info.get("returnOnEquity")
    if roe is not None:
        roe = float(roe)
        if abs(roe) <= 1.5:
            roe *= 100

    debt_equity = info.get("debtToEquity")
    if debt_equity is not None:
        debt_equity = float(debt_equity)
        if debt_equity > 500:
            debt_equity = debt_equity / 100

    div_yield = info.get("dividendYield")
    if div_yield is not None:
        div_yield = float(div_yield)
        if div_yield < 1:
            div_yield *= 100

    pb = info.get("priceToBook")
    if pb is not None:
        pb = float(pb)
        if pb > 50:
            pb = None

    data: dict[str, Any] = {
        "symbol": sym,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": float(last_close) if last_close is not None else None,
        "market_cap": info.get("marketCap"),
        "avg_volume_1mo": avg_volume,
        "avg_daily_value_idr": avg_value_idr,
        "return_1m_pct": ret_1m,
        "return_3m_pct": ret_3m,
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": pb,
        "roe_pct": roe,
        "debt_to_equity": debt_equity,
        "dividend_yield_pct": div_yield,
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "has_financials": bool(ticker.financials is not None and not ticker.financials.empty),
        "has_balance_sheet": bool(ticker.balance_sheet is not None and not ticker.balance_sheet.empty),
        "recent_dividends": dividends,
    }

    if use_cache and "error" not in data:
        save_yf_cache(sym, data)
    return data


def fetch_ihsg_return_1m() -> float | None:
    cached = load_yf_cache("_IHSG")
    if cached and cached.get("return_1m_pct") is not None:
        return float(cached["return_1m_pct"])

    try:
        import yfinance as yf
    except ImportError:
        return None

    hist = yf.Ticker("^JKSE").history(period="1mo", auto_adjust=True)
    if len(hist) < 2:
        return None
    first = float(hist["Close"].iloc[0])
    last = float(hist["Close"].iloc[-1])
    ret = (last / first - 1) * 100 if first else None
    if ret is not None:
        save_yf_cache(
            "_IHSG",
            {
                "symbol": "_IHSG",
                "return_1m_pct": ret,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return ret


def liquidity_tier(avg_value_idr: float | None, min_liquidity: float) -> str:
    if avg_value_idr is None:
        return "UNKNOWN"
    if avg_value_idr >= 5_000_000_000:
        return "TINGGI"
    if avg_value_idr >= 1_000_000_000:
        return "SEDANG"
    if avg_value_idr >= min_liquidity:
        return "CUKUP"
    return "RENDAH"


def qc_verdict(
    yf_data: dict[str, Any],
    stockbit: dict[str, Any] | None,
    *,
    min_liquidity: float,
    ihsg_ret_1m: float | None,
    idx_data: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    score = 0

    tier = liquidity_tier(yf_data.get("avg_daily_value_idr"), min_liquidity)
    if tier == "TINGGI":
        score += 2
        notes.append(f"Likuiditas tinggi ({fmt_idr(yf_data.get('avg_daily_value_idr'))}/hari)")
    elif tier == "SEDANG":
        score += 2
        notes.append(f"Likuiditas sedang ({fmt_idr(yf_data.get('avg_daily_value_idr'))}/hari)")
    elif tier == "CUKUP":
        score += 1
        notes.append(f"Likuiditas cukup ({fmt_idr(yf_data.get('avg_daily_value_idr'))}/hari)")
    elif tier == "RENDAH":
        score -= 2
        notes.append(f"Likuiditas rendah ({fmt_idr(yf_data.get('avg_daily_value_idr'))}/hari)")
    else:
        notes.append("Likuiditas tidak tersedia")

    if yf_data.get("sector"):
        notes.append(f"Sektor {yf_data['sector']}/{yf_data.get('industry', '')}")

    ret_1m = yf_data.get("return_1m_pct")
    if ret_1m is not None and ihsg_ret_1m is not None:
        if ret_1m > ihsg_ret_1m + 2:
            score += 1
            notes.append(f"Momentum 1M {fmt_pct(ret_1m)} vs IHSG {fmt_pct(ihsg_ret_1m)}")
        elif ret_1m < ihsg_ret_1m - 5:
            score -= 1
            notes.append(f"Underperform IHSG 1M ({fmt_pct(ret_1m)} vs {fmt_pct(ihsg_ret_1m)})")

    if yf_data.get("has_financials") and yf_data.get("has_balance_sheet"):
        score += 1
        notes.append("Financials Yahoo tersedia")

    if yf_data.get("recent_dividends"):
        notes.append(f"Dividen terakhir {yf_data['recent_dividends'][-1]['date']}")

    if stockbit:
        uv = stockbit.get("undervalued_pct")
        if uv is not None and uv >= 30:
            score += 2
        elif uv is not None and uv >= 15:
            score += 1
        q = stockbit.get("quality")
        if q == "Best":
            score += 1

        sb_roe = stockbit.get("roe")
        yf_roe = yf_data.get("roe_pct")
        if sb_roe is not None and yf_roe is not None and abs(sb_roe - yf_roe) > 10:
            notes.append(f"ROE gap Stockbit {sb_roe:.1f}% vs Yahoo {yf_roe:.1f}%")

    de = yf_data.get("debt_to_equity")
    if de is not None and de > 150:
        score -= 1
        notes.append(f"Utang/de tinggi (Yahoo {de:.0f})")

    if idx_data:
        score, idx_notes = apply_idx_qc(score, idx_data)
        notes.extend(idx_notes)

    if tier == "RENDAH":
        verdict = "TIDAK LAYAK QC"
    elif score >= 5:
        verdict = "LAYAK QC"
    elif score >= 3:
        verdict = "LAYAK HATI-HATI"
    else:
        verdict = "WASPADA"

    return verdict, notes


def apply_idx_qc(score: int, idx_data: dict[str, Any]) -> tuple[int, list[str]]:
    notes: list[str] = []
    if not idx_data:
        return score, notes
    profile = idx_data.get("profile") or {}
    if profile.get("board"):
        notes.append(f"Papan {profile['board']} · komisaris independen {profile.get('independent_n', 0)}/{profile.get('commissioners_n', 0)}")
    if profile.get("independent_n"):
        score += 1
    elif profile.get("commissioners_n"):
        score -= 1
        notes.append("Tidak ada komisaris independen di data IDX")
    if profile.get("top_holder_pct") and profile.get("top_holders"):
        notes.append(f"Pemegang terbesar {profile['top_holders'][0]['name']} {profile['top_holder_pct']:.1f}%")

    if idx_data.get("dilutive_n"):
        score -= 2
        labels = ", ".join(a["label"] for a in idx_data.get("corporate_actions", []) if a.get("dilutive"))
        notes.append(f"Aksi dilusi 12 bln: {labels or idx_data['dilutive_n']} event")
    if idx_data.get("buyback_n"):
        score += 1
        notes.append("Ada buyback 12 bulan terakhir")

    fin = idx_data.get("financials") or {}
    if fin:
        audit = str(fin.get("audit") or "").upper()
        if audit in ("U", "WTP", "UNQUALIFIED"):
            score += 1
            notes.append(f"Opini audit WTP (IDX {fin.get('year') or ''})".strip())
        elif audit:
            score -= 2
            notes.append(f"Opini audit bukan WTP: {audit}")
        if fin.get("roe") is not None:
            notes.append(f"IDX rasio tahunan: ROE {fin['roe']:.1f}% · DER {fin.get('der') or '—'} · NPM {fin.get('npm') or '—'}")

    lk = idx_data.get("latest_financial_report")
    if lk:
        score += 1
        notes.append(f"Laporan keuangan IDX: {lk.get('date')} — {lk.get('title')}")
    rups = idx_data.get("latest_rups")
    if rups:
        notes.append(f"RUPS: {rups.get('date')} — {rups.get('title')}")

    sec_ret = idx_data.get("sector_return_1m_pct")
    ihsg_idx = idx_data.get("ihsg_index_return_1m_pct")
    code = idx_data.get("sector_index")
    if sec_ret is not None and ihsg_idx is not None and code:
        if sec_ret < ihsg_idx - 3:
            score -= 1
            notes.append(f"Sektor {code} 1M {fmt_pct(sec_ret)} kalah vs IHSG {fmt_pct(ihsg_idx)}")
        elif sec_ret > ihsg_idx + 3:
            score += 1
            notes.append(f"Sektor {code} 1M {fmt_pct(sec_ret)} unggul vs IHSG {fmt_pct(ihsg_idx)}")
        else:
            notes.append(f"Sektor {code} 1M {fmt_pct(sec_ret)} (IHSG {fmt_pct(ihsg_idx)})")
    elif code:
        notes.append(f"Indeks sektor {code}")

    if idx_data.get("error") and not profile:
        notes.append(f"IDX partial: {idx_data['error']}")
    return score, notes


def enrich_symbol(
    symbol: str,
    *,
    use_cache: bool = True,
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY_IDR,
    ihsg_ret_1m: float | None = None,
    with_idx: bool = True,
) -> dict[str, Any]:
    from idx_client import enrich_idx

    sym = symbol.upper().replace(".JK", "")
    yf_data = fetch_yahoo(sym, use_cache=use_cache)
    stockbit = load_stockbit_summary(sym)
    idx_data = None
    if with_idx:
        print(f"IDX QC {sym}...", file=sys.stderr)
        idx_data = enrich_idx(
            sym,
            sector=yf_data.get("sector"),
            industry=yf_data.get("industry"),
            use_cache=use_cache,
        )
    verdict, notes = qc_verdict(
        yf_data,
        stockbit,
        min_liquidity=min_liquidity,
        ihsg_ret_1m=ihsg_ret_1m,
        idx_data=idx_data,
    )
    tier = liquidity_tier(yf_data.get("avg_daily_value_idr"), min_liquidity)
    return {
        "symbol": sym,
        "yahoo": yf_data,
        "stockbit": stockbit,
        "idx": idx_data,
        "liquidity_tier": tier,
        "qc_verdict": verdict,
        "qc_notes": notes,
        "passes_liquidity": tier not in ("RENDAH", "UNKNOWN"),
    }


def parse_symbols_from_markdown(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return list(dict.fromkeys(re.findall(r"\*\*([A-Z]{4})\*\*", text)))


def parse_symbols_from_json(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "stocks" in data:
        return [s.get("symbol", "").upper() for s in data["stocks"] if s.get("symbol")]
    if isinstance(data, list):
        return [s.get("symbol", "").upper() for s in data if isinstance(s, dict) and s.get("symbol")]
    return []


def parse_symbols_from_portfolio(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [p["symbol"].upper() for p in data.get("positions", []) if p.get("symbol")]


def print_screener_from_json(
    path: Path,
    *,
    min_pct: float = 10.0,
    min_quality: str = "Bagus",
    show_bandar: bool = False,
    bandar_window: str = "1month",
    min_bandar_pct: float = 5.0,
) -> None:
    """Re-print screener markdown from JSON output (avoids second Stockbit API run)."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from dataclasses import fields

    from tuntun_undervalued_screener import StockRow, print_markdown

    data = json.loads(path.read_text(encoding="utf-8"))
    stocks = data.get("stocks", [])
    field_names = {f.name for f in fields(StockRow)}
    rows = []
    for item in stocks:
        if not isinstance(item, dict):
            continue
        payload = {k: v for k, v in item.items() if k in field_names}
        if payload.get("symbol"):
            rows.append(StockRow(**payload))

    meta = data.get("meta", {})
    print_markdown(
        rows,
        meta.get("min_pct", min_pct),
        meta.get("min_quality", min_quality),
        meta.get("bandar", show_bandar),
        meta.get("bandar_window", bandar_window),
        meta.get("min_bandar_pct", min_bandar_pct),
    )


def print_markdown_report(
    rows: list[dict[str, Any]],
    *,
    min_liquidity: float,
    ihsg_ret_1m: float | None,
    title: str = "QC Enrichment (Yahoo Finance)",
) -> None:
    print(f"# {title}")
    print()
    print(
        f"**{len(rows)} saham** · Likuiditas min {fmt_idr(min_liquidity)}/hari · "
        f"IHSG 1M {fmt_pct(ihsg_ret_1m)} · Yahoo + IDX resmi"
    )
    print()
    print(
        "| Saham | Likuiditas | Nilai/hari | Sektor | Ret 1M | Audit | Dilusi | QC |"
    )
    print("|-------|------------|----------|--------|--------|-------|--------|-----|")
    for row in rows:
        sym = row["symbol"]
        yf = row.get("yahoo", {})
        idx = row.get("idx") or {}
        if yf.get("error"):
            print(f"| **{sym}** | — | — | — | — | — | — | ERROR |")
            continue
        sector = yf.get("sector") or (idx.get("profile") or {}).get("sector") or "—"
        fin = idx.get("financials") or {}
        audit = fin.get("audit") or "—"
        if str(audit).upper() in ("U", "WTP"):
            audit = "WTP"
        dilusi = idx.get("dilutive_n") or 0
        print(
            f"| **{sym}** | {row['liquidity_tier']} | "
            f"{fmt_idr(yf.get('avg_daily_value_idr'))} | {sector} | "
            f"{fmt_pct(yf.get('return_1m_pct'))} | {audit} | {dilusi} | {row['qc_verdict']} |"
        )

    print()
    print("## Detail QC")
    print()
    for row in rows:
        sym = row["symbol"]
        yf = row.get("yahoo", {})
        if yf.get("error"):
            print(f"### {sym} — ERROR: {yf['error']}")
            print()
            continue
        sb = row.get("stockbit") or {}
        per_disp = sb.get("per_ttm") or yf.get("trailing_pe")
        pbv_disp = sb.get("pbv") or yf.get("price_to_book")
        roe_disp = sb.get("roe") or yf.get("roe_pct")
        de_disp = sb.get("debt_equity") or yf.get("debt_to_equity")
        print(f"### {sym} — {row['qc_verdict']}")
        print()
        if sb.get("undervalued_pct") is not None:
            print(
                f"- Stockbit: undervalued {sb.get('undervalued_pct')}% · "
                f"kualitas {sb.get('quality')} · guidance hold {sb.get('guidance_hold', '—')}"
            )
        print(
            f"- Valuasi: PER {per_disp} · PBV {pbv_disp} · "
            f"ROE {roe_disp}% · utang/de {de_disp}"
        )
        if yf.get("avg_volume_1mo"):
            print(f"- Likuiditas: avg volume {float(yf['avg_volume_1mo']):,.0f} lot")
        else:
            print("- Likuiditas: —")
        idx = row.get("idx") or {}
        prof = idx.get("profile") or {}
        if prof:
            print(
                f"- Governance IDX: papan {prof.get('board') or '—'} · "
                f"direksi {prof.get('directors_n', 0)} · komisaris {prof.get('commissioners_n', 0)} "
                f"(independen {prof.get('independent_n', 0)})"
            )
        lk = idx.get("latest_financial_report")
        if lk:
            pdf = f" · [PDF]({lk['pdf']})" if lk.get("pdf") else ""
            print(f"- Laporan keuangan: {lk.get('date')} — {lk.get('title')}{pdf}")
        cas = idx.get("corporate_actions") or []
        if cas:
            print("- Corporate action 12 bln: " + "; ".join(f"{a.get('date')} {a.get('label')}" for a in cas[:4]))
        for note in row.get("qc_notes", []):
            print(f"- {note}")
        print()

    passed = sum(1 for r in rows if r.get("passes_liquidity") and r.get("qc_verdict") in ("LAYAK QC", "LAYAK HATI-HATI"))
    print(f"_Lolos filter likuiditas + QC: {passed}/{len(rows)} saham_")
    print("_Sumber: Stockbit + Yahoo Finance + IDX (idx.co.id) · Bukan saran investasi._")


def main() -> None:
    parser = argparse.ArgumentParser(description="Yahoo Finance QC enrichment for IDX stocks")
    parser.add_argument("--symbols", nargs="*", help="Ticker IDX tanpa .JK")
    parser.add_argument("--from-json", help="JSON output dari screener")
    parser.add_argument("--from-markdown", help="Markdown report (reports/latest.md)")
    parser.add_argument("--portfolio", help="Portfolio JSON dry-run")
    parser.add_argument(
        "--min-liquidity-idr",
        type=float,
        default=DEFAULT_MIN_LIQUIDITY_IDR,
        help="Min rata-rata nilai transaksi/hari (default 500jt)",
    )
    parser.add_argument("--no-cache", action="store_true", help="Fetch fresh dari Yahoo/IDX")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Simpan report ke file")
    parser.add_argument(
        "--print-screener",
        action="store_true",
        help="Cetak tabel screener dari --from-json sebelum QC (untuk --with-qc)",
    )
    parser.add_argument(
        "--idx",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enrich dari IDX resmi: governance, CA, laporan, indeks sektor (default: on)",
    )
    args = parser.parse_args()

    symbols: list[str] = []
    title = "QC Enrichment — Yahoo + IDX"

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    elif args.from_json:
        symbols = parse_symbols_from_json(Path(args.from_json))
        title = "QC Enrichment — Screener + Yahoo + IDX"
    elif args.from_markdown:
        symbols = parse_symbols_from_markdown(Path(args.from_markdown))
        title = "QC Enrichment — Screener + Yahoo + IDX"
    elif args.portfolio:
        symbols = parse_symbols_from_portfolio(Path(args.portfolio))
        title = "QC Enrichment — Portfolio + Yahoo + IDX"
    else:
        latest = SKILL_DIR / "reports" / "latest.md"
        if latest.exists():
            symbols = parse_symbols_from_markdown(latest)
            title = "QC Enrichment — Screener + Yahoo + IDX"
        else:
            print("ERROR: Berikan --symbols, --from-json, --portfolio, atau reports/latest.md", file=sys.stderr)
            sys.exit(1)

    if not symbols:
        print("ERROR: Tidak ada symbol untuk di-enrich", file=sys.stderr)
        sys.exit(1)

    ihsg_ret_1m = fetch_ihsg_return_1m()
    if args.idx:
        print("IDX warmup (CA, rasio, indeks)...", file=sys.stderr)
        try:
            from idx_client import fetch_corporate_actions, fetch_financial_ratio_map, latest_trading_day

            latest_trading_day()
            fetch_corporate_actions()
            fetch_financial_ratio_map()
        except Exception as exc:
            print(f"WARN IDX warmup: {exc}", file=sys.stderr)
    rows = [
        enrich_symbol(
            sym,
            use_cache=not args.no_cache,
            min_liquidity=args.min_liquidity_idr,
            ihsg_ret_1m=ihsg_ret_1m,
            with_idx=args.idx,
        )
        for sym in symbols
    ]

    if args.print_screener and args.from_json:
        print_screener_from_json(Path(args.from_json))
        print()

    if args.format == "json":
        text = json.dumps(
            {
                "min_liquidity_idr": args.min_liquidity_idr,
                "ihsg_return_1m_pct": ihsg_ret_1m,
                "count": len(rows),
                "stocks": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        import io

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        print_markdown_report(
            rows,
            min_liquidity=args.min_liquidity_idr,
            ihsg_ret_1m=ihsg_ret_1m,
            title=title,
        )
        sys.stdout = old_stdout
        text = buf.getvalue()

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
