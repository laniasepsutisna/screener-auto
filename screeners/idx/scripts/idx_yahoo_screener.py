#!/usr/bin/env python3
"""IDX Top Undervalued screener — Tuntun-style via Yahoo Finance (no Stockbit token).

Phase 2: pengganti default untuk review/screener harian tanpa Bearer token.
Metodologi selaras us_undervalued_screener + threshold IDX (PBV/PER/PEG).
"""
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

SKILL_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path.home() / ".cache" / "idx-undervalued-screener" / "yahoo-screener"

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

# Built-in blue-chip / liquid IDX (tanpa .JK) — overlap dengan VALUE_BLUECHIP_WATCHLIST Stockbit
UNIVERSE_LIQUID: tuple[str, ...] = (
    # Banks
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "BTPS", "BDMN", "PNBN", "MEGA", "NISP",
    # Consumer / retail
    "ICBP", "INDF", "UNVR", "MYOR", "GGRM", "HMSP", "KLBF", "SIDO", "ACES", "MAPI",
    "AMRT", "MIDI", "CPIN", "JPFA",
    # Auto / industrial
    "ASII", "AUTO", "UNTR", "HEXA", "SMGR", "INTP", "WSKT", "WIKA", "PTPP", "ADHI",
    # Energy / mining / plantation
    "ADRO", "PTBA", "ITMG", "HRUM", "INDY", "MEDC", "PGAS", "AKRA", "ANTM", "INCO",
    "TINS", "MDKA", "NCKL", "BRPT", "AALI", "LSIP", "SIMP", "SSMS",
    # Telco / infra / property
    "TLKM", "EXCL", "ISAT", "JSMR", "TOWR", "TBIG", "PWON", "CTRA", "BSDE", "SMRA",
    "DMAS", "JRPT", "LPKR",
    # Conglomerate / other liquid
    "GOTO", "BUKA", "EMTK", "SCMA", "MNCN", "ERAA", "MIKA", "HEAL", "SILO",
    "KBLI", "KKGI", "ARTO", "BFIN", "ADMF", "CFIN",
)

UNIVERSE_VALUE: tuple[str, ...] = (
    "BBRI", "BMRI", "BBNI", "BDMN", "BRIS",
    "ADRO", "PTBA", "ITMG", "HRUM", "INDY", "MEDC", "PGAS", "AKRA",
    "ANTM", "INCO", "TINS", "NCKL", "MDKA",
    "SMGR", "INTP", "SMRA", "CTRA", "PWON", "BSDE",
    "AALI", "LSIP", "INDF", "ICBP", "UNVR", "GGRM", "HMSP",
    "ASII", "UNTR", "TLKM", "EXCL", "JSMR",
    "KBLI", "KKGI", "ARTO",
)

UNIVERSE_MEGA: tuple[str, ...] = (
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "UNVR", "ICBP", "INDF",
    "ADRO", "PTBA", "ANTM", "PGAS", "UNTR", "SMGR", "KLBF", "CPIN", "GOTO",
    "BRIS", "EXCL", "INTP", "ITMG", "MDKA", "AMRT", "MYOR",
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
    market_cap_t: float | None = None  # triliun IDR
    signals: list[str] = field(default_factory=list)
    entry: str = "Tunggu & amati"
    hold: str = "Tunggu & amati"
    pass_value: bool = False
    caveat: str = ""
    yahoo_symbol: str = ""
    # Internal — untuk recompute fair band setelah median PE diketahui
    _eps: float | None = None
    _feps: float | None = None
    _bvps: float | None = None
    _pb_raw: float | None = None


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
    if dy is None:
        return None
    if dy > 1:
        dy = dy / 100.0
    if dy > 0.25:
        dy = dy / 100.0
    return dy


def yahoo_sym(symbol: str) -> str:
    s = symbol.upper().replace(".JK", "").strip()
    return f"{s}.JK"


def bare_sym(symbol: str) -> str:
    return symbol.upper().replace(".JK", "").strip()


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
        # Banks often have high D/E on Yahoo — soft-penalize only extreme
        if de <= 50:
            score += 2
        elif de <= 150:
            score += 1
        elif de > 300:
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
    *,
    median_pe: float | None,
) -> tuple[float | None, float | None, float | None, str | None]:
    """Fair value band — konservatif ala Tuntun IDX (PBV band / PE band)."""
    methods: list[tuple[str, float, float]] = []

    bv_ok = (
        bvps is not None
        and 0 < bvps < price * 3.0
        and pb is not None
        and 0.05 < pb < 2.0
    )
    if bv_ok and bvps is not None:
        # Stockbit/Tuntun sering pakai BV × ~1.20–1.85
        methods.append(("pbv", bvps * 1.20, bvps * 1.85))

    trailing_inflated = (
        eps is not None
        and feps is not None
        and eps > 0
        and feps > 0
        and eps > feps * 1.6
    )

    pe_lo = 10.0
    pe_hi = 14.0
    if median_pe and 5 < median_pe < 25:
        pe_lo = max(8.0, median_pe * 0.75)
        pe_hi = max(pe_lo + 2, median_pe * 1.05)

    if feps and feps > 0:
        methods.append(("fwd_value_pe", feps * pe_lo, feps * (pe_hi + 2)))
    if eps and eps > 0 and not trailing_inflated:
        methods.append(("value_pe", eps * pe_lo, eps * pe_hi))

    scored: list[tuple[str, float, float, float]] = []
    for name, lo, hi in methods:
        if lo <= 0 or hi <= 0 or hi < lo:
            continue
        mid = (lo + hi) / 2
        if mid > price * 3.5 and name != "pbv":
            continue
        if mid < price * 0.2:
            continue
        scored.append((name, lo, hi, mid))

    if not scored:
        return None, None, None, None

    pbv = next((s for s in scored if s[0] == "pbv"), None)
    if pbv and pb is not None and pb < 1.0:
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
    symbols: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip().upper()
            if not line:
                continue
            symbols.append(bare_sym(line))
    return symbols


def resolve_universe(name: str, symbols: list[str] | None) -> list[str]:
    if symbols:
        return [bare_sym(s) for s in symbols if s.strip()]
    name = name.lower()
    if name in ("liquid", "fast", "ihsg"):
        # ihsg tanpa Stockbit → liquid proxy (bukan 835 full)
        base = list(UNIVERSE_LIQUID)
    elif name == "value":
        base = list(UNIVERSE_VALUE)
    elif name == "mega":
        base = list(UNIVERSE_MEGA)
    elif name == "watchlist":
        base = load_watchlist()
        if not base:
            base = list(UNIVERSE_VALUE)
    else:
        print(f"ERROR: universe tidak dikenal: {name}", file=sys.stderr)
        sys.exit(1)

    extras = load_watchlist()
    seen = set(base)
    for s in extras:
        if s not in seen:
            base.append(s)
            seen.add(s)
    return base


def fetch_stock(sym: str, *, median_pe: float | None = None) -> StockRow | None:
    import yfinance as yf

    ysym = yahoo_sym(sym)
    t = yf.Ticker(ysym)
    i = t.info or {}
    price = safe(
        i.get("currentPrice") or i.get("regularMarketPrice") or i.get("previousClose")
    )
    if not price or price <= 0:
        # fallback history
        try:
            hist = t.history(period="5d", auto_adjust=True)
            if not hist.empty:
                price = safe(hist["Close"].iloc[-1])
        except Exception:
            price = None
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

    # Yahoo bookValue quirk for some IDX names
    if pb is not None and (pb <= 0.01 or pb > 40):
        pb = None

    qlabel, qscore = quality_label(roe, de, pm, dy, rg)
    flo, fhi, fmid, method = fair_band(
        price, eps, feps, pe, pb, bvps, median_pe=median_pe
    )
    uv = (1 - price / fmid) * 100 if fmid and fmid > 0 else None

    signals: list[str] = []
    if pb is not None and 0.05 < pb < 1.0:
        signals.append("PBV<1")
    elif pb is not None and 0.05 < pb < 1.5:
        signals.append("PBV<1.5")
    med = median_pe if median_pe else 15.0
    if pe is not None and 0 < pe < med:
        signals.append("PER<median")
    if pe is not None and 0 < pe < 12:
        signals.append("PER<12")
    if fpe is not None and 0 < fpe < 14:
        signals.append("FwdPE<14")
    if peg is not None and 0 < peg < 1:
        signals.append("PEG<1")

    under_fair = bool(uv is not None and fhi and price <= fhi and uv >= 0)
    guide_uv = uv if under_fair and uv and uv > 0 else (uv if uv and uv > 0 else -10)
    entry, hold = guidance(qlabel, guide_uv)

    caveat = ""
    if rg is not None and rg > 1.5:
        caveat = "Rev growth ekstrem — cek ulang"
    if method == "fwd_value_pe" and feps and eps and eps > 0 and feps > eps * 2.5:
        caveat = "Forward EPS jauh di atas trailing — sensitif revisi"

    display = bare_sym(sym)
    pb_out = round(pb, 2) if pb and pb > 0.05 else None

    return StockRow(
        symbol=display,
        name=str(i.get("shortName") or i.get("longName") or display),
        sector=str(i.get("sector") or "-"),
        industry=str(i.get("industry") or "-"),
        price=round(price, 2),
        fair_low=round(flo, 2) if flo else None,
        fair_high=round(fhi, 2) if fhi else None,
        fair_mid=round(fmid, 2) if fmid else None,
        fair_method=method,
        undervalued_pct=round(uv, 1) if uv is not None else None,
        quality=qlabel,
        quality_score=qscore,
        pe=round(pe, 2) if pe else None,
        forward_pe=round(fpe, 2) if fpe else None,
        pb=pb_out,
        peg=round(peg, 2) if peg else None,
        roe=round(roe * 100, 1) if roe is not None else None,
        debt_equity=round(de, 1) if de is not None else None,
        div_yield=round(dy * 100, 2) if dy is not None else None,
        profit_margin=round(pm * 100, 1) if pm is not None else None,
        rev_growth=round(rg * 100, 1) if rg is not None else None,
        market_cap_t=round(mcap / 1e12, 2) if mcap else None,
        signals=signals,
        entry=entry,
        hold=hold,
        pass_value=False,
        caveat=caveat,
        yahoo_symbol=ysym,
        _eps=eps,
        _feps=feps,
        _bvps=bvps,
        _pb_raw=pb,
    )


def fmt_idr(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:,.0f}" if v >= 100 else f"{v:,.2f}"


def fmt_fair(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "-"
    return f"{fmt_idr(lo)} - {fmt_idr(hi)}"


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
        "# Top Undervalued",
        "",
        (
            f"**{len(rows)} saham dalam daftar** · Filter: Undervalued (%) ≥ {min_pct:g}% · "
            f"Kualitas ≥ {min_quality} · Universe: {universe} ({fetched_n} fetched) · "
            f"Sumber: Yahoo Finance"
            + (f" · Median PER {median_pe}" if median_pe else "")
        ),
        "",
        "| Saham | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | Harga | Harga Wajar | PER | PBV | PEG |",
        "|-------|----------|-----------------|--------------|------------|-------|-------------|-----|-----|-----|",
    ]
    for r in rows:
        name_short = (r.name[:18] + "…") if len(r.name) > 19 else r.name
        uv = f"{r.undervalued_pct:.0f}%" if r.undervalued_pct is not None else "-"
        peg = f"{r.peg:.2f}" if r.peg is not None else "-"
        lines.append(
            f"| **{r.symbol}** {name_short} | {r.quality} | {uv} | {r.entry} | {r.hold} | "
            f"{fmt_idr(r.price)} | {fmt_fair(r.fair_low, r.fair_high)} | "
            f"{r.pe if r.pe is not None else '-'} | {r.pb if r.pb is not None else '-'} | {peg} |"
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
            "_Data: Yahoo Finance (.JK) · Metodologi: Tuntun-style (PBV/PER/PEG band + kualitas heuristik)_",
            "_Tanpa token Stockbit. Angka UV%/kualitas bisa beda dari app Tuntun._",
            "_Bukan saran investasi._",
            "",
        ]
    )
    return "\n".join(lines)


def run_screen(args: argparse.Namespace) -> int:
    symbols = resolve_universe(args.universe, args.symbols)
    if args.universe.lower() == "ihsg" and not args.symbols:
        print(
            "WARN: universe IHSG tanpa Stockbit memakai proxy liquid "
            f"({len(symbols)} ticker), bukan 835 full.",
            file=sys.stderr,
        )

    # Pass 1: fetch all (median PE computed after)
    raw: list[StockRow] = []
    errors: list[str] = []
    workers = max(1, min(args.workers, 10))

    def _fetch(s: str) -> StockRow | None:
        return fetch_stock(s, median_pe=None)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch, s): s for s in symbols}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                r = fut.result()
                if r:
                    raw.append(r)
                else:
                    errors.append(s)
            except Exception as e:
                errors.append(f"{s}:{type(e).__name__}")

    pes = [r.pe for r in raw if r.pe and r.pe > 0]
    median_pe = round(statistics.median(pes), 1) if pes else None

    # Pass 2: recompute fair band + UV dengan median PER universe
    rows: list[StockRow] = []
    for r in raw:
        if r.price:
            flo, fhi, fmid, method = fair_band(
                r.price,
                r._eps,
                r._feps,
                r.pe,
                r._pb_raw,
                r._bvps,
                median_pe=median_pe,
            )
            r.fair_low = round(flo, 2) if flo else None
            r.fair_high = round(fhi, 2) if fhi else None
            r.fair_mid = round(fmid, 2) if fmid else None
            r.fair_method = method
            uv = (1 - r.price / fmid) * 100 if fmid and fmid > 0 else None
            r.undervalued_pct = round(uv, 1) if uv is not None else None
            under_fair = bool(uv is not None and fhi and r.price <= fhi and uv >= 0)
            guide_uv = uv if under_fair and uv and uv > 0 else (uv if uv and uv > 0 else -10)
            r.entry, r.hold = guidance(r.quality, guide_uv)
        if median_pe and r.pe and 0 < r.pe < median_pe and "PER<median" not in r.signals:
            r.signals.append("PER<median")
        rows.append(r)

    passed: list[StockRow] = []
    for r in rows:
        uv_ok = r.undervalued_pct is not None and r.undervalued_pct >= args.min_pct
        under_fair = (
            r.fair_high is not None and r.price is not None and r.price <= r.fair_high
        )
        value_signal = any(
            s in r.signals
            for s in ("PBV<1", "PBV<1.5", "PER<median", "PER<12", "FwdPE<14", "PEG<1")
        )
        q_ok = meets_min_quality(r.quality, args.min_quality)
        if args.no_value_signal:
            r.pass_value = bool(uv_ok and under_fair and q_ok)
        else:
            r.pass_value = bool(uv_ok and under_fair and value_signal and q_ok)
        if r.pass_value:
            passed.append(r)

    passed.sort(
        key=lambda r: (
            -(r.undervalued_pct or -999),
            -{"Best": 3, "Bagus": 2, "Fair": 1, "Weak": 0}.get(r.quality, 0),
        )
    )
    passed = passed[: args.limit]

    uni_label = args.universe if not args.symbols else "symbols"
    if args.format == "markdown":
        text = render_markdown(
            passed,
            min_pct=args.min_pct,
            min_quality=args.min_quality,
            universe=uni_label,
            fetched_n=len(rows),
            median_pe=median_pe,
        )
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        print(text)
    elif args.format == "json":
        payload = {
            "as_of": date.today().isoformat(),
            "source": "yahoo",
            "universe": uni_label,
            "fetched_n": len(rows),
            "median_pe": median_pe,
            "min_pct": args.min_pct,
            "min_quality": args.min_quality,
            "rows": [
                {k: v for k, v in asdict(r).items() if not k.startswith("_")}
                for r in passed
            ],
            "errors": errors[:40],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text)
    else:
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
            "pb",
            "peg",
            "div_yield",
            "roe",
            "sector",
            "fair_method",
            "caveat",
        ]
        import io

        sio = io.StringIO()
        w = csv.DictWriter(sio, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in passed:
            w.writerow(asdict(r))
        text = sio.getvalue()
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text)

    if errors and args.format == "markdown":
        print(
            f"\n_Fetch gagal/skip ({len(errors)}): {', '.join(errors[:15])}_",
            file=sys.stderr,
        )
    if not passed and args.format == "markdown":
        print(
            "\n_0 hasil — coba --min-pct 5 / --min-quality Fair / --no-value-signal_",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="IDX Top Undervalued screener via Yahoo Finance (no Stockbit token)"
    )
    p.add_argument(
        "--universe",
        default="liquid",
        help="liquid|fast|value|mega|watchlist|ihsg (ihsg=liquid proxy)",
    )
    p.add_argument("--symbols", nargs="+", help="Ticker IDX tanpa .JK (PTBA BMRI)")
    p.add_argument("--min-pct", type=float, default=DEFAULT_MIN_UV)
    p.add_argument(
        "--min-quality",
        default="Bagus",
        choices=list(QUALITY_LABELS),
    )
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument(
        "--no-value-signal",
        action="store_true",
        help="Jangan wajibkan sinyal PBV/PER/PEG",
    )
    p.add_argument("--format", default="markdown", choices=["markdown", "json", "csv"])
    p.add_argument("--output", help="Tulis ke file")
    # Compatibility flags from Stockbit CLI (ignored with warn)
    p.add_argument("--fast", action="store_true", help="(compat) sama dengan universe liquid")
    p.add_argument("--no-fast", action="store_true", help="(compat) diabaikan di mode Yahoo")
    p.add_argument("--bandar", action="store_true", help="(compat) bandar tidak tersedia di Yahoo")
    p.add_argument("--no-bandar", action="store_true", help="(compat) default")
    p.add_argument("--cache", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--with-qc", action="store_true", help="(compat) ditangani run.ps1")
    return p


def main() -> None:
    args = build_parser().parse_args()
    # Strip unknown stockbit-only leftovers silently via parse_known? keep simple.
    if args.bandar:
        print(
            "WARN: --bandar tidak tersedia di sumber Yahoo (butuh Stockbit). Diabaikan.",
            file=sys.stderr,
        )
    if args.no_fast:
        print(
            "WARN: --no-fast (scan 835) butuh Stockbit. Mode Yahoo memakai universe liquid/value.",
            file=sys.stderr,
        )
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
