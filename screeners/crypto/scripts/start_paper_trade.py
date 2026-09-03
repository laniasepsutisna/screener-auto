#!/usr/bin/env python3
"""Start a 14–21 day paper trade from the live screener (safe rules).

Filters match what backtest preferred: Grade A/B, TA Entry OK/Selektif,
unlock risk != Tinggi. Max 4 positions, risk-adjusted sizing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from crypto_undervalued_screener import run_screener  # noqa: E402
from risk_management import suggest_portfolio_allocation  # noqa: E402

SKILL_DIR = SCRIPT_DIR.parent
DRY_RUN_DIR = SKILL_DIR / "dry-run"
try:
    from zoneinfo import ZoneInfo
    JAKARTA = ZoneInfo("Asia/Jakarta")
except Exception:
    JAKARTA = timezone(timedelta(hours=7))


def build_portfolio(
    rows,
    *,
    capital: float,
    max_positions: int,
    hold_days: int,
) -> dict:
    now = datetime.now(JAKARTA)
    review = (now + timedelta(days=7)).date().isoformat()
    end = (now + timedelta(days=hold_days)).date().isoformat()

    alloc = suggest_portfolio_allocation(rows, capital)[:max_positions]
    by_sym = {r.symbol: r for r in rows}
    positions = []
    for a in alloc:
        r = by_sym.get(a["symbol"])
        if not r:
            continue
        positions.append({
            "symbol": r.symbol,
            "coin_id": r.coin_id,
            "name": r.name,
            "weight_pct": a["allocation_pct"],
            "allocation_usd": a["allocation_usd"],
            "entry_price": r.price,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "risk_reward": r.risk_reward,
            "risk_grade": r.risk_grade,
            "entry_undervalued_pct": r.undervalued_pct,
            "entry_quality": r.quality,
            "entry_guidance": r.guidance_entry,
            "entry_mvrv": r.mvrv_proxy,
            "entry_ta": r.ta_signal,
            "entry_rsi": r.rsi_14,
            "unlock_risk": r.unlock_risk or "—",
            "unlock_note": r.unlock_note or "",
            "thesis": (
                f"{r.quality} · underval {r.undervalued_pct or 0:.0f}% · "
                f"TA {r.ta_signal} · Grade {r.risk_grade} · R:R {r.risk_reward}"
            ),
        })

    cash_pct = round(100 - sum(p["weight_pct"] for p in positions), 1)
    return {
        "id": f"paper-v2-{now.strftime('%Y-%m-%d')}",
        "type": "paper_trade",
        "version": 2,
        "asset_class": "crypto",
        "protocol": "safe-only + ta-confirm + unlock-filter",
        "created_at": now.isoformat(timespec="seconds"),
        "review_at": review,
        "end_at": end,
        "hold_days_max": hold_days,
        "hypothesis": (
            "Aturan live (kualitas + undervalued + risk A/B + TA Entry OK/Selektif "
            "+ unlock bukan Tinggi) menghasilkan expectancy positif dalam 14–21 hari, "
            "dengan DD terkendali — validasi pipeline penuh yang backtest tidak cover."
        ),
        "virtual_capital_usd": capital,
        "cash_pct": cash_pct,
        "allocation": "risk_adjusted",
        "positions": positions,
        "rules": {
            "entry": "Hanya Grade A/B + TA Entry OK/Selektif + unlock ≠ Tinggi",
            "exit_sl_tp": "Hormati stop_loss / take_profit di snapshot",
            "exit_time": f"Max hold {hold_days} hari",
            "review": "Setiap 7 hari via dry_run_review.ps1",
            "no_chase": "Jika 0 kandidat → tetap cash, re-screen minggu depan",
            "not_real_money": True,
        },
        "success_criteria": {
            "portfolio_return_pct_min": 0.0,
            "note": (
                "Sukses = proses diikuti + tidak melanggar SL; "
                "bukan wajib profit. Bandingkan vs hold BTC di periode sama."
            ),
        },
        "benchmark": "BTC buy-and-hold over same window",
    }


def print_summary(pf: dict) -> None:
    print("# Paper Trade Dimulai")
    print()
    print(f"**ID:** {pf['id']}  ")
    print(f"**Entry:** {pf['created_at'][:10]} · **Review:** {pf['review_at']} · **End:** {pf['end_at']}  ")
    print(f"**Modal virtual:** ${pf['virtual_capital_usd']:,.0f} · Cash idle: {pf['cash_pct']}%  ")
    print(f"**Protocol:** {pf['protocol']}")
    print()
    print(f"**Hipotesis:** {pf['hypothesis']}")
    print()
    if not pf["positions"]:
        print(
            "_Tidak ada posisi — filter ketat (aman). Tetap cash; "
            "jalankan ulang screener minggu depan._"
        )
        print()
        print("```powershell")
        print(
            '& "...\\run.ps1" --safe-only --ta-confirm --unlock-filter --limit 10'
        )
        print("```")
        return

    print("| Coin | Grade | TA | Alokasi | Entry | SL | TP | R:R | Unlock |")
    print("|------|-------|----|---------|-------|----|----|-----|--------|")
    for p in pf["positions"]:
        print(
            f"| **{p['symbol']}** | {p['risk_grade']} | {p['entry_ta']} "
            f"| {p['weight_pct']}% (${p['allocation_usd']:,.0f}) "
            f"| ${p['entry_price']} | ${p['stop_loss']} | ${p['take_profit']} "
            f"| {p['risk_reward']} | {p['unlock_risk']} |"
        )
    print()
    print("## Cara review (setiap 7 hari)")
    print()
    print("```powershell")
    print(
        '& "C:\\Users\\Kimia Farma\\.cursor\\skills\\crypto-undervalued-screener\\'
        "dry_run_review.ps1\""
    )
    print("```")
    print()
    print("_Paper trade — bukan uang real. Bukan saran investasi._")


def main() -> None:
    p = argparse.ArgumentParser(description="Start crypto paper trade (safe rules)")
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--max-positions", type=int, default=4)
    p.add_argument("--hold-days", type=int, default=21)
    p.add_argument("--universe", default="top100")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--min-quality", default="Bagus")
    args = p.parse_args()

    print("Menjalankan screener (safe-only + ta-confirm + unlock-filter)…", file=sys.stderr)
    rows = run_screener(
        universe=args.universe,
        min_pct=10.0,
        min_quality=args.min_quality,
        min_mcap=100_000_000,
        limit=args.limit,
        phase=4,
        risk=True,
        safe_only=True,
        min_rr=1.5,
        portfolio_usd=args.capital,
        max_position_pct=5.0,
        exclude_traps=True,
        ta=True,
        ta_confirm=True,
        macro=True,
        macro_filter=False,
        unlock=True,
        unlock_filter=True,
    )

    pf = build_portfolio(
        rows,
        capital=args.capital,
        max_positions=args.max_positions,
        hold_days=args.hold_days,
    )
    DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = DRY_RUN_DIR / f"portfolio-{pf['id']}.json"
    # id already has date; filename: portfolio-paper-v2-YYYY-MM-DD.json
    path = DRY_RUN_DIR / f"portfolio-{pf['id']}.json"
    pf["_path"] = str(path)
    to_save = {k: v for k, v in pf.items() if k != "_path"}
    path.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")

    # also point "latest"
    latest = DRY_RUN_DIR / "portfolio-latest.json"
    latest.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")

    report = SKILL_DIR / "reports" / "paper-trade-start.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    import io
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
    main()
