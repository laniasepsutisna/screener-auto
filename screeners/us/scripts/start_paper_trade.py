#!/usr/bin/env python3
"""Start US paper trade from live undervalued screener (classic value rules)."""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from us_undervalued_screener import (  # noqa: E402
    StockRow,
    fetch_stock,
    meets_min_quality,
    resolve_universe,
)

SKILL_DIR = SCRIPT_DIR.parent
DRY_RUN_DIR = SKILL_DIR / "dry-run"

try:
    from zoneinfo import ZoneInfo

    JAKARTA = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA = timezone(timedelta(hours=7))

# Soft exclusions: not classic value for paper validation
EXCLUDE_SYMBOLS = {
    "MU",  # forward EPS ekstrem
    "NVDA",  # growth/AI narrative
    "AMD",
    "AVGO",
    "PLTR",
    "TSLA",
    "NFLX",
}


def passes_entry(row: StockRow, *, min_pct: float, min_quality: str) -> bool:
    if row.symbol in EXCLUDE_SYMBOLS:
        return False
    if row.caveat:
        return False
    if not meets_min_quality(row.quality, min_quality):
        return False
    if row.undervalued_pct is None or row.undervalued_pct < min_pct:
        return False
    if row.fair_high is None or row.price is None or row.price > row.fair_high:
        return False
    # Prefer actionable guidance; allow Tunggu if UV tinggi + quality Best
    if row.entry in ("Beli", "Beli selektif"):
        return True
    if row.quality == "Best" and row.undervalued_pct >= 15:
        return True
    if row.undervalued_pct >= 20 and row.entry == "Tunggu & amati":
        # still allow deep UV watch names with value signal
        return any(
            s in row.signals
            for s in ("PBV<1", "PBV<1.5", "PER<18", "FwdPE<16", "PEG<1")
        )
    return False


def suggest_weights(n: int, invested_pct: float = 80.0) -> list[float]:
    if n <= 0:
        return []
    each = round(invested_pct / n, 1)
    weights = [each] * n
    # fix rounding
    diff = round(invested_pct - sum(weights), 1)
    weights[0] = round(weights[0] + diff, 1)
    return weights


def stop_loss(price: float) -> float:
    return round(price * 0.88, 2)  # -12%


def take_profit(row: StockRow) -> float:
    if row.fair_mid:
        return round(row.fair_mid, 2)
    if row.fair_low:
        return round(row.fair_low, 2)
    assert row.price is not None
    return round(row.price * 1.15, 2)


def build_portfolio(
    rows: list[StockRow],
    *,
    capital: float,
    max_positions: int,
    hold_days: int,
    min_pct: float,
    min_quality: str,
    spy_price: float | None = None,
) -> dict:
    now = datetime.now(JAKARTA)
    candidates = [r for r in rows if passes_entry(r, min_pct=min_pct, min_quality=min_quality)]
    candidates.sort(
        key=lambda r: (
            -(r.undervalued_pct or -999),
            -{"Best": 3, "Bagus": 2, "Fair": 1, "Weak": 0}.get(r.quality, 0),
        )
    )
    picked = candidates[:max_positions]
    weights = suggest_weights(len(picked), invested_pct=80.0)

    positions = []
    for w, r in zip(weights, picked):
        assert r.price is not None
        tp = take_profit(r)
        sl = stop_loss(r.price)
        rr = round((tp - r.price) / (r.price - sl), 2) if r.price > sl else None
        alloc = round(capital * w / 100.0, 2)
        positions.append(
            {
                "symbol": r.symbol,
                "yahoo_symbol": r.symbol.replace(".", "-"),
                "name": r.name,
                "sector": r.sector,
                "weight_pct": w,
                "allocation_usd": alloc,
                "entry_price": r.price,
                "stop_loss": sl,
                "take_profit": tp,
                "risk_reward": rr,
                "fair_low": r.fair_low,
                "fair_high": r.fair_high,
                "fair_method": r.fair_method,
                "entry_undervalued_pct": r.undervalued_pct,
                "entry_quality": r.quality,
                "entry_guidance": r.entry,
                "entry_pe": r.pe,
                "entry_forward_pe": r.forward_pe,
                "entry_pb": r.pb,
                "entry_div_yield": r.div_yield,
                "signals": r.signals,
                "thesis": (
                    f"{r.quality} · UV {r.undervalued_pct or 0:.0f}% · "
                    f"{r.entry} · {r.fair_method} · "
                    f"PER {r.pe} / FwdPE {r.forward_pe}"
                ),
            }
        )

    cash_pct = round(100 - sum(p["weight_pct"] for p in positions), 1)
    return {
        "id": f"paper-us-v1-{now.strftime('%Y-%m-%d')}",
        "type": "paper_trade",
        "version": 1,
        "asset_class": "us_equity",
        "protocol": "classic-value: UV≥min + quality≥Bagus + value signal + no caveat/growth-name",
        "created_at": now.isoformat(timespec="seconds"),
        "review_at": (now + timedelta(days=7)).date().isoformat(),
        "end_at": (now + timedelta(days=hold_days)).date().isoformat(),
        "hold_days_max": hold_days,
        "hypothesis": (
            "Saham US kualitas ≥ Bagus + undervalued (PE/PBV band) + guidance "
            "Beli/Beli selektif (tanpa caveat forward EPS ekstrem) outperform "
            f"SPY buy-and-hold dalam {hold_days} hari, dengan SL -12% dihormati."
        ),
        "virtual_capital_usd": capital,
        "cash_pct": cash_pct,
        "allocation": "equal_weight_80pct_invested",
        "positions": positions,
        "excluded_examples": sorted(EXCLUDE_SYMBOLS),
        "rules": {
            "entry": (
                "UV% ≥ min · kualitas ≥ Bagus · harga ≤ fair_high · "
                "value signal · tanpa caveat · exclude growth-name list"
            ),
            "exit_sl_tp": "Hormati stop_loss (-12%) / take_profit (fair mid)",
            "exit_time": f"Max hold {hold_days} hari",
            "review": "Setiap 7 hari via dry_run_review.ps1",
            "no_chase": "Jika 0 kandidat → cash; re-screen minggu depan",
            "not_real_money": True,
        },
        "success_criteria": {
            "portfolio_return_pct_min": 0.0,
            "note": (
                "Sukses = proses diikuti + SL dihormati; bukan wajib profit. "
                "Bandingkan vs SPY di window yang sama."
            ),
        },
        "benchmark": "SPY buy-and-hold over same window",
        "benchmark_entry_spy": spy_price,
    }


def print_summary(pf: dict) -> None:
    print("# Paper Trade US Dimulai")
    print()
    print(f"**ID:** {pf['id']}  ")
    print(
        f"**Entry:** {pf['created_at'][:10]} · **Review:** {pf['review_at']} · "
        f"**End:** {pf['end_at']}  "
    )
    print(
        f"**Modal virtual:** ${pf['virtual_capital_usd']:,.0f} · "
        f"Cash idle: {pf['cash_pct']}%  "
    )
    print(f"**Protocol:** {pf['protocol']}")
    print()
    print(f"**Hipotesis:** {pf['hypothesis']}")
    print()
    if not pf["positions"]:
        print("_Tidak ada posisi — filter ketat. Tetap cash; screen ulang minggu depan._")
        return

    print("| Saham | Q | UV% | Alokasi | Entry | SL | TP | R:R | Guidance |")
    print("|-------|---|-----|---------|-------|----|----|-----|----------|")
    for p in pf["positions"]:
        print(
            f"| **{p['symbol']}** | {p['entry_quality']} | "
            f"{p['entry_undervalued_pct']:.0f}% | "
            f"{p['weight_pct']}% (${p['allocation_usd']:,.0f}) | "
            f"${p['entry_price']} | ${p['stop_loss']} | ${p['take_profit']} | "
            f"{p['risk_reward']} | {p['entry_guidance']} |"
        )
    print()
    print("## Cara review (setiap 7 hari)")
    print()
    print("```powershell")
    print(
        '& "C:\\Users\\Kimia Farma\\.cursor\\skills\\us-undervalued-screener\\'
        'dry_run_review.ps1"'
    )
    print("```")
    print()
    print("_Paper trade — bukan uang real. Bukan saran investasi._")


def collect_rows(universe: str, symbols: list[str] | None, workers: int) -> list[StockRow]:
    tickers = resolve_universe(universe, symbols)
    rows: list[StockRow] = []
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 10))) as ex:
        futs = {ex.submit(fetch_stock, s): s for s in tickers}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                if r:
                    rows.append(r)
            except Exception:
                continue
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description="Start US equity paper trade")
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--max-positions", type=int, default=5)
    p.add_argument("--hold-days", type=int, default=21)
    p.add_argument("--universe", default="liquid", choices=["liquid", "value", "mega", "watchlist"])
    p.add_argument("--symbols", nargs="+")
    p.add_argument("--min-pct", type=float, default=15.0)
    p.add_argument("--min-quality", default="Bagus")
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()

    print("Menjalankan screener US (classic value paper rules)…", file=sys.stderr)
    rows = collect_rows(args.universe, args.symbols, args.workers)
    spy = fetch_stock("SPY")
    pf = build_portfolio(
        rows,
        capital=args.capital,
        max_positions=args.max_positions,
        hold_days=args.hold_days,
        min_pct=args.min_pct,
        min_quality=args.min_quality,
        spy_price=spy.price if spy else None,
    )

    DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = DRY_RUN_DIR / f"portfolio-{pf['id']}.json"
    to_save = pf
    path.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = DRY_RUN_DIR / "portfolio-latest.json"
    latest.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")

    report = SKILL_DIR / "reports" / "paper-trade-start.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    print_summary(pf)
    sys.stdout = old
    text = buf.getvalue()
    report.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSnapshot: {path}", file=sys.stderr)


if __name__ == "__main__":
    # fix take_profit fallback
    main()
