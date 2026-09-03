#!/usr/bin/env python3
"""US Top Undervalued screener — Tuntun-style via Yahoo Finance."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yfinance as yf

SKILL_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path.home() / ".cache" / "us-undervalued-screener"

QUALITY_LABELS = ("Best", "Bagus", "Fair", "Weak")
DEFAULT_MIN_UV = 10.0

GUIDANCE_QUALITY_MAP = {
    "Best": "terbaik",
    "Bagus": "bagus",
    "Fair": "sedang",
    "Weak": "sedang",
}

GUIDANCE_ENTRY = {
    "terbaik": {
        "gt40": "Beli",
        "21_40": "Beli",
        "1_20": "Beli selektif",
        "fair": "Tunggu & amati",
        "ov": "Tunggu & amati",
    },
    "bagus": {
        "gt40": "Beli",
        "21_40": "Beli selektif",
        "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati",
        "ov": "Tunggu & amati",
    },
    "sedang": {
        "gt40": "Tunggu & amati",
        "21_40": "Tunggu & amati",
        "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati",
        "ov": "Tunggu & amati",
    },
}

GUIDANCE_HOLD = {
    "terbaik": {
        "gt40": "Hold",
        "21_40": "Hold",
        "1_20": "Hold",
        "fair": "Hold",
        "ov": "Jual selektif",
    },
    "bagus": {
        "gt40": "Hold",
        "21_40": "Hold",
        "1_20": "Hold",
        "fair": "Jual selektif",
        "ov": "Jual",
    },
    "sedang": {
        "gt40": "Tunggu & amati",
        "21_40": "Tunggu & amati",
        "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati",
        "ov": "Tunggu & amati",
    },
}

# Liquid large/mid US names (default universe)
UNIVERSE_LIQUID: tuple[str, ...] = (
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "BRK-B", "JNJ", "PG", "KO",
    "PEP", "COST", "UNH", "V", "MA",
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW",
    "XOM", "CVX", "COP", "OXY", "CAT", "GE", "HON", "UPS", "RTX", "LMT",
    "PFE", "MRK", "ABBV", "BMY", "AMGN", "T", "VZ", "CMCSA", "WMT", "HD",
    "LOW", "MCD", "NKE", "SBUX",
    "INTC", "CSCO", "IBM", "ORCL", "QCOM", "AMD", "AVGO", "TXN", "INTU", "CRM",
    "ADBE", "NFLX", "TSLA", "DIS", "BA", "F", "GM",
    "CVS", "PARA", "UBER", "ABNB", "MU", "AMAT", "KLAC", "DE", "MDT", "ISRG",
    "PLTR", "SOFI", "PYPL", "BKNG", "AXP", "MMM", "GEHC", "MO", "PM", "DUK",
    "NEE", "SO", "D", "SPG", "O", "AMT", "EQIX",
)

UNIVERSE_VALUE: tuple[str, ...] = (
    "BRK-B", "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW",
    "XOM", "CVX", "COP", "OXY",
    "T", "VZ", "CMCSA", "PFE", "BMY", "MRK", "ABBV", "MDT", "CVS",
    "INTC", "CSCO", "IBM", "UPS", "F", "GM", "BA", "DIS", "NKE",
    "JNJ", "PG", "KO", "PEP", "WMT", "MO", "PM", "MMM", "GE", "HON",
    "CAT", "DE", "RTX", "LMT", "PARA", "PYPL",
)

UNIVERSE_MEGA: tuple[str, ...] = (
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "BRK-B", "AVGO",
    "TSLA", "JPM", "V", "MA", "UNH", "XOM", "LLY", "COST", "PG", "JNJ",
    "HD", "ABBV", "CRM", "ORCL", "CVX", "KO", "PEP", "MRK", "WMT", "BAC",
    "AMD", "CSCO", "ACN", "LIN", "MCD", "ADBE", "TXN", "PM", "NFLX", "DIS",
)


@dataclass
class StockRow:
    symbol: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    price: float | None = None
    fair_low: float | None = None
    fair_high: float | None = None
    fair_mid: float | None = None
    fair_method: str | None = None
    undervalued_pct: float | None = None
    analyst_upside_pct: float | None = None
    target: float | None = None
    quality: str = "Weak"
    quality_score: int = 0
    pe: float | None = None
    forward_pe: float | None = None
    pb: float | None = None
    peg: float | None = None
    roe: float | None = None
    debt_equity: float | None = None
    div_yield: float | None = None
    profit_margin: float | None = None
    rev_growth: float | None = None
    market_cap_b: float | None = None
    lo52: float | None = None
    hi52: float | None = None
    signals: list[str] = field(default_factory=list)
    entry: str = "Tunggu & amati"
    hold: str = "Tunggu & amati"
    pass_value: bool = False
    caveat: str = ""


def safe(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def norm_div_yield(dy: float | None) -> float | None:
    """Yahoo dividendYield is usually a fraction (0.04 = 4%)."""
    if dy is None:
        return None
    if dy > 1:
        dy = dy / 100.0
    if dy > 0.25:  # >25% unlikely — treat as percent leftover
        dy = dy / 100.0
    return dy


def quality_label(
    roe: float | None,
    de: float | None,
    pm: float | None,
    dy: float | None,
    rg: float | None,
) -> tuple[str, int]:
    score = 0
    if roe is not None:
        if roe >= 0.20:
            score += 3
        elif roe >= 0.12:
            score += 2
        elif roe >= 0.08:
            score += 1
        elif roe < 0:
            score -= 2
    if de is not None:
        if de <= 50:
            score += 2
        elif de <= 100:
            score += 1
        elif de > 200:
            score -= 1
    if pm is not None:
        if pm >= 0.20:
            score += 2
        elif pm >= 0.10:
            score += 1
        elif pm < 0:
            score -= 1
    if dy is not None and dy >= 0.02:
        score += 1
    if rg is not None:
        if rg >= 0.10:
            score += 1
        elif rg < -0.05:
            score -= 1
    if score >= 7:
        return "Best", score
    if score >= 4:
        return "Bagus", score
    if score >= 1:
        return "Fair", score
    return "Weak", score


def fair_band(
    price: float,
    eps: float | None,
    feps: float | None,
    pe: float | None,
    pb: float | None,
    bvps: float | None,
) -> tuple[float | None, float | None, float | None, str | None]:
    methods: list[tuple[str, float, float]] = []

    bv_ok = (
        bvps is not None
        and 0 < bvps < price * 2.5
        and pb is not None
        and 0.05 < pb < 2.5
    )
    if bv_ok and bvps is not None:
        methods.append(("pbv", bvps * 1.15, bvps * 1.75))

    trailing_inflated = (
        eps is not None
        and feps is not None
        and eps > 0
        and feps > 0
        and eps > feps * 1.6
    )

    if feps and feps > 0:
        methods.append(("fwd_value_pe", feps * 15, feps * 20))
    if eps and eps > 0 and not trailing_inflated:
        methods.append(("value_pe", eps * 14, eps * 18))

    scored: list[tuple[str, float, float, float]] = []
    for name, lo, hi in methods:
        if lo <= 0 or hi <= 0 or hi < lo:
            continue
        mid = (lo + hi) / 2
        if mid > price * 3 and name != "pbv":
            continue
        if mid < price * 0.25:
            continue
        scored.append((name, lo, hi, mid))

    if not scored:
        return None, None, None, None

    pbv = next((s for s in scored if s[0] == "pbv"), None)
    if pbv and pb is not None and pb < 1.2:
        pick = pbv
    else:
        pe_bands = [s for s in scored if s[0] in ("value_pe", "fwd_value_pe")]
        if pe_bands:
            above = [s for s in pe_bands if price <= s[2]]
            pick = (
                min(above, key=lambda s: s[3])
                if above
                else min(pe_bands, key=lambda s: abs(s[3] - price))
            )
        else:
            pick = scored[0]
    return pick[1], pick[2], pick[3], pick[0]


def guidance(quality: str, uv: float | None) -> tuple[str, str]:
    q = GUIDANCE_QUALITY_MAP.get(quality, "sedang")
    if uv is None:
        bucket = "fair"
    elif uv >= 40:
        bucket = "gt40"
    elif uv >= 21:
        bucket = "21_40"
    elif uv >= 1:
        bucket = "1_20"
    elif uv >= -5:
        bucket = "fair"
    else:
        bucket = "ov"
    return GUIDANCE_ENTRY[q][bucket], GUIDANCE_HOLD[q][bucket]


def meets_min_quality(quality: str, min_quality: str) -> bool:
    order = {q: i for i, q in enumerate(reversed(QUALITY_LABELS))}
    return order.get(quality, -1) >= order.get(min_quality, 0)


def load_watchlist() -> list[str]:
    path = SKILL_DIR / "value_watchlist.txt"
    if not path.exists():
        return []
    syms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().upper()
        if not line:
            continue
        syms.append(line.replace(".", "-"))
    return syms


def resolve_universe(name: str, symbols: list[str] | None) -> list[str]:
    if symbols:
        return [s.strip().upper().replace(".", "-") for s in symbols if s.strip()]
    name = name.lower()
    if name == "liquid":
        base = list(UNIVERSE_LIQUID)
    elif name == "value":
        base = list(UNIVERSE_VALUE)
    elif name == "mega":
        base = list(UNIVERSE_MEGA)
    elif name == "watchlist":
        base = load_watchlist()
        if not base:
            print(
                "ERROR: value_watchlist.txt kosong — isi ticker atau pakai --universe liquid",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(f"ERROR: universe tidak dikenal: {name}", file=sys.stderr)
        sys.exit(1)
    # merge optional watchlist extras for liquid/value
    extras = load_watchlist()
    seen = set(base)
    for s in extras:
        if s not in seen:
            base.append(s)
            seen.add(s)
    return base


def fetch_stock(sym: str) -> StockRow | None:
    t = yf.Ticker(sym)
    i = t.info or {}
    price = safe(
        i.get("currentPrice") or i.get("regularMarketPrice") or i.get("previousClose")
    )
    if not price or price <= 0:
        return None

    pe = safe(i.get("trailingPE"))
    fpe = safe(i.get("forwardPE"))
    pb = safe(i.get("priceToBook"))
    peg = safe(i.get("pegRatio"))
    roe = safe(i.get("returnOnEquity"))
    de = safe(i.get("debtToEquity"))
    dy = norm_div_yield(safe(i.get("dividendYield")))
    pm = safe(i.get("profitMargins"))
    rg = safe(i.get("revenueGrowth"))
    mcap = safe(i.get("marketCap"))
    eps = safe(i.get("trailingEps"))
    feps = safe(i.get("forwardEps"))
    bvps = safe(i.get("bookValue"))
    target = safe(i.get("targetMeanPrice"))

    qlabel, qscore = quality_label(roe, de, pm, dy, rg)
    flo, fhi, fmid, method = fair_band(price, eps, feps, pe, pb, bvps)
    uv = (1 - price / fmid) * 100 if fmid and fmid > 0 else None
    analyst_up = ((target / price) - 1) * 100 if target else None

    signals: list[str] = []
    if pb is not None and 0.05 < pb < 1.0:
        signals.append("PBV<1")
    elif pb is not None and 0.05 < pb < 1.5:
        signals.append("PBV<1.5")
    if pe is not None and 0 < pe < 18:
        signals.append("PER<18")
    if fpe is not None and 0 < fpe < 16:
        signals.append("FwdPE<16")
    if peg is not None and 0 < peg < 1:
        signals.append("PEG<1")
    if analyst_up is not None and analyst_up >= 10:
        signals.append("Analyst>+10%")

    value_signal = any(
        s in signals for s in ("PBV<1", "PBV<1.5", "PER<18", "FwdPE<16", "PEG<1")
    )
    under_fair = bool(uv is not None and fhi and price <= fhi and uv >= 0)
    guide_uv = uv if under_fair and uv and uv > 0 else (uv if uv and uv > 0 else -10)
    entry, hold = guidance(qlabel, guide_uv)

    caveat = ""
    # Aggressive forward growth → flag
    if rg is not None and rg > 1.5:  # >150% YoY
        caveat = "Forward/rev growth ekstrem — cek ulang estimasi"
    if method == "fwd_value_pe" and feps and eps and eps > 0 and feps > eps * 2.5:
        caveat = "Forward EPS jauh di atas trailing — sensitif ke revisi analis"

    display_sym = sym.replace("-", ".")
    pb_out = round(pb, 2) if pb and pb > 0.05 else None

    return StockRow(
        symbol=display_sym,
        name=str(i.get("shortName") or i.get("longName") or display_sym),
        sector=str(i.get("sector") or "-"),
        industry=str(i.get("industry") or "-"),
        price=round(price, 2),
        fair_low=round(flo, 2) if flo else None,
        fair_high=round(fhi, 2) if fhi else None,
        fair_mid=round(fmid, 2) if fmid else None,
        fair_method=method,
        undervalued_pct=round(uv, 1) if uv is not None else None,
        analyst_upside_pct=round(analyst_up, 1) if analyst_up is not None else None,
        target=round(target, 2) if target else None,
        quality=qlabel,
        quality_score=qscore,
        pe=round(pe, 1) if pe else None,
        forward_pe=round(fpe, 1) if fpe else None,
        pb=pb_out,
        peg=round(peg, 2) if peg else None,
        roe=round(roe * 100, 1) if roe is not None else None,
        debt_equity=round(de, 1) if de is not None else None,
        div_yield=round(dy * 100, 2) if dy is not None else None,
        profit_margin=round(pm * 100, 1) if pm is not None else None,
        rev_growth=round(rg * 100, 1) if rg is not None else None,
        market_cap_b=round(mcap / 1e9, 1) if mcap else None,
        lo52=round(safe(i.get("fiftyTwoWeekLow")) or 0, 2) or None,
        hi52=round(safe(i.get("fiftyTwoWeekHigh")) or 0, 2) or None,
        signals=signals,
        entry=entry,
        hold=hold,
        pass_value=False,
        caveat=caveat,
    )


def fmt_money(v: float | None) -> str:
    if v is None:
        return "-"
    if v >= 1000:
        return f"{v:,.2f}"
    if v >= 100:
        return f"{v:.2f}"
    return f"{v:.2f}"


def fmt_fair(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "-"
    return f"{fmt_money(lo)} - {fmt_money(hi)}"


def render_markdown(
    rows: list[StockRow],
    *,
    min_pct: float,
    min_quality: str,
    universe: str,
    fetched_n: int,
    median_pe: float | None,
) -> str:
    lines = [
        "# Top Undervalued US",
        "",
        (
            f"**{len(rows)} saham dalam daftar** · Filter: Undervalued (%) ≥ {min_pct:g}% · "
            f"Kualitas ≥ {min_quality} · Universe: {universe} ({fetched_n} fetched)"
            + (f" · Median PER {median_pe}" if median_pe else "")
        ),
        "",
        "| Saham | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | Harga | Harga Wajar | PER | FwdPE | PBV | Yield |",
        "|-------|----------|-----------------|--------------|------------|-------|-------------|-----|-------|-----|-------|",
    ]
    for r in rows:
        name_short = (r.name[:22] + "…") if len(r.name) > 23 else r.name
        uv = f"{r.undervalued_pct:.0f}%" if r.undervalued_pct is not None else "-"
        dy = f"{r.div_yield:.1f}%" if r.div_yield is not None else "-"
        lines.append(
            f"| **{r.symbol}** {name_short} | {r.quality} | {uv} | {r.entry} | {r.hold} | "
            f"{fmt_money(r.price)} | {fmt_fair(r.fair_low, r.fair_high)} | "
            f"{r.pe if r.pe is not None else '-'} | {r.forward_pe if r.forward_pe is not None else '-'} | "
            f"{r.pb if r.pb is not None else '-'} | {dy} |"
        )

    caveats = [r for r in rows if r.caveat]
    if caveats:
        lines.extend(["", "### Catatan", ""])
        for r in caveats:
            lines.append(f"- **{r.symbol}**: {r.caveat}")

    lines.extend(
        [
            "",
            "_Tuntun Guidance: Tanpa Posisi = belum punya · Ada Posisi = sudah hold_",
            "",
            "_Data: Yahoo Finance · Metodologi: Tuntun-style (PE/PBV band + kualitas heuristik)_",
            "_Bukan saran investasi. Belum ada eksekusi broker US dari skill ini._",
            "",
        ]
    )
    return "\n".join(lines)


def run_screen(args: argparse.Namespace) -> int:
    symbols = resolve_universe(args.universe, args.symbols)
    rows: list[StockRow] = []
    errors: list[str] = []

    workers = max(1, min(args.workers, 10))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_stock, s): s for s in symbols}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                r = fut.result()
                if r:
                    rows.append(r)
                else:
                    errors.append(s)
            except Exception as e:
                errors.append(f"{s}:{type(e).__name__}")

    pes = [r.pe for r in rows if r.pe and r.pe > 0]
    median_pe = round(statistics.median(pes), 1) if pes else None

    passed: list[StockRow] = []
    for r in rows:
        uv_ok = r.undervalued_pct is not None and r.undervalued_pct >= args.min_pct
        under_fair = (
            r.fair_high is not None
            and r.price is not None
            and r.price <= r.fair_high
        )
        value_signal = any(
            s in r.signals
            for s in ("PBV<1", "PBV<1.5", "PER<18", "FwdPE<16", "PEG<1")
        )
        q_ok = meets_min_quality(r.quality, args.min_quality)
        r.pass_value = bool(uv_ok and under_fair and value_signal and q_ok)
        if r.pass_value:
            passed.append(r)
        elif args.include_all and uv_ok and q_ok:
            # still show if user wants broader list without value-signal hard require
            passed.append(r)

    if args.no_value_signal:
        passed = [
            r
            for r in rows
            if r.undervalued_pct is not None
            and r.undervalued_pct >= args.min_pct
            and r.fair_high is not None
            and r.price is not None
            and r.price <= r.fair_high
            and meets_min_quality(r.quality, args.min_quality)
        ]
        for r in passed:
            r.pass_value = True

    passed.sort(
        key=lambda r: (
            -(r.undervalued_pct or -999),
            -{"Best": 3, "Bagus": 2, "Fair": 1, "Weak": 0}.get(r.quality, 0),
        )
    )
    passed = passed[: args.limit]

    if args.format == "markdown":
        text = render_markdown(
            passed,
            min_pct=args.min_pct,
            min_quality=args.min_quality,
            universe=args.universe if not args.symbols else "symbols",
            fetched_n=len(rows),
            median_pe=median_pe,
        )
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        print(text)
    elif args.format == "json":
        payload = {
            "as_of": date.today().isoformat(),
            "universe": args.universe,
            "fetched_n": len(rows),
            "median_pe": median_pe,
            "min_pct": args.min_pct,
            "min_quality": args.min_quality,
            "rows": [asdict(r) for r in passed],
            "errors": errors[:30],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text)
    else:  # csv
        out = Path(args.output) if args.output else None
        fields = [
            "symbol",
            "name",
            "quality",
            "undervalued_pct",
            "entry",
            "hold",
            "price",
            "fair_low",
            "fair_high",
            "pe",
            "forward_pe",
            "pb",
            "peg",
            "div_yield",
            "roe",
            "sector",
            "fair_method",
            "caveat",
        ]
        buf = []
        import io

        sio = io.StringIO()
        w = csv.DictWriter(sio, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in passed:
            w.writerow(asdict(r))
        text = sio.getvalue()
        if out:
            out.write_text(text, encoding="utf-8")
        else:
            print(text)

    if errors and args.format == "markdown":
        print(f"\n_Fetch gagal/skip: {', '.join(errors[:12])}_", file=sys.stderr)

    if not passed and args.format == "markdown":
        print(
            "\n_0 hasil — coba turunkan --min-pct / --min-quality Fair / --no-value-signal_",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="US Top Undervalued screener (Yahoo Finance)")
    p.add_argument(
        "--universe",
        default="liquid",
        choices=["liquid", "value", "mega", "watchlist"],
        help="Preset universe (default: liquid ~90 names)",
    )
    p.add_argument("--symbols", nargs="+", help="Ticker tertentu (AAPL MSFT BRK-B)")
    p.add_argument("--min-pct", type=float, default=DEFAULT_MIN_UV, help="Min undervalued %%")
    p.add_argument(
        "--min-quality",
        default="Bagus",
        choices=list(QUALITY_LABELS),
        help="Min kualitas",
    )
    p.add_argument("--limit", type=int, default=30, help="Max baris tampil")
    p.add_argument("--workers", type=int, default=8, help="Parallel Yahoo fetch (max 10)")
    p.add_argument(
        "--no-value-signal",
        action="store_true",
        help="Jangan wajibkan sinyal PER/PBV/PEG/FwdPE",
    )
    p.add_argument(
        "--include-all",
        action="store_true",
        help="Legacy alias longgar (tidak disarankan)",
    )
    p.add_argument(
        "--format",
        default="markdown",
        choices=["markdown", "json", "csv"],
    )
    p.add_argument("--output", help="Tulis ke file")
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        import yfinance  # noqa: F401
    except ImportError:
        print(
            "ERROR: yfinance belum terpasang. Jalankan:\n"
            '  & "C:\\Users\\Kimia Farma\\.local\\bin\\python3.14.exe" '
            "-m pip install yfinance curl_cffi --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(run_screen(args))


if __name__ == "__main__":
    main()
