#!/usr/bin/env python3
"""Review US paper-trade dry run vs current Yahoo prices."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from us_undervalued_screener import fetch_stock  # noqa: E402

SKILL_DIR = SCRIPT_DIR.parent
DRY_RUN_DIR = SKILL_DIR / "dry-run"


def load_portfolio(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_usd(v: float) -> str:
    if abs(v) >= 1000:
        return f"${v:,.2f}"
    return f"${v:.2f}"


def fmt_pct(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


def review_portfolio(portfolio: dict) -> dict:
    capital = float(portfolio.get("virtual_capital_usd", 10_000))
    positions_out: list[dict] = []
    total_entry = 0.0
    total_current = 0.0
    hit_sl = 0
    hit_tp = 0

    for pos in portfolio["positions"]:
        symbol = pos["symbol"]
        yahoo = pos.get("yahoo_symbol") or symbol.replace(".", "-")
        weight = float(pos.get("weight_pct", 0)) / 100.0
        alloc = capital * weight
        entry = float(pos["entry_price"])
        sl = float(pos.get("stop_loss") or 0) or None
        tp = float(pos.get("take_profit") or 0) or None

        row = fetch_stock(yahoo)
        current = float(row.price) if row and row.price else None
        if current is None:
            positions_out.append({"symbol": symbol, "error": "price_unavailable", **pos})
            continue

        shares = alloc / entry
        entry_value = shares * entry
        current_value = shares * current
        pnl = current_value - entry_value
        ret_pct = (current / entry - 1) * 100

        status = "open"
        if sl and current <= sl:
            status = "hit_SL"
            hit_sl += 1
        elif tp and current >= tp:
            status = "hit_TP"
            hit_tp += 1

        total_entry += entry_value
        total_current += current_value

        positions_out.append(
            {
                "symbol": symbol,
                "name": pos.get("name", row.name if row else ""),
                "weight_pct": pos.get("weight_pct"),
                "entry_price": entry,
                "current_price": round(current, 2),
                "return_pct": round(ret_pct, 2),
                "pnl_usd": round(pnl, 2),
                "stop_loss": sl,
                "take_profit": tp,
                "status": status,
                "entry_quality": pos.get("entry_quality"),
                "entry_undervalued_pct": pos.get("entry_undervalued_pct"),
                "current_undervalued_pct": row.undervalued_pct if row else None,
                "current_quality": row.quality if row else None,
                "thesis": pos.get("thesis", ""),
            }
        )

    portfolio_ret = ((total_current / total_entry) - 1) * 100 if total_entry else 0.0
    winners = sum(1 for p in positions_out if p.get("return_pct", 0) > 0)
    losers = sum(1 for p in positions_out if p.get("return_pct", 0) < 0)

    # SPY benchmark
    spy_ret = None
    try:
        spy = fetch_stock("SPY")
        # store only current; benchmark return needs entry SPY in portfolio
        entry_spy = portfolio.get("benchmark_entry_spy")
        if spy and spy.price and entry_spy:
            spy_ret = round((float(spy.price) / float(entry_spy) - 1) * 100, 2)
        elif spy and spy.price and not entry_spy:
            portfolio.setdefault("_spy_price_now", spy.price)
    except Exception:
        pass

    return {
        "portfolio_id": portfolio.get("id"),
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entry_date": portfolio.get("created_at"),
        "target_review_date": portfolio.get("review_at"),
        "virtual_capital_usd": capital,
        "portfolio_return_pct": round(portfolio_ret, 2),
        "portfolio_pnl_usd": round(total_current - total_entry, 2),
        "winners": winners,
        "losers": losers,
        "flat": len(positions_out) - winners - losers,
        "hit_sl": hit_sl,
        "hit_tp": hit_tp,
        "spy_return_pct": spy_ret,
        "positions": sorted(
            positions_out,
            key=lambda x: x.get("return_pct", -999),
            reverse=True,
        ),
    }


def print_markdown(result: dict, portfolio: dict) -> None:
    print("# Dry Run Review — Paper Trade US")
    print()
    print(f"**Portfolio:** {result.get('portfolio_id')}  ")
    print(f"**Entry:** {str(portfolio.get('created_at', ''))[:10]}  ")
    print(f"**Review:** {date.today().isoformat()}  ")
    print(f"**Modal virtual:** {fmt_usd(result['virtual_capital_usd'])}")
    print()
    ret = result["portfolio_return_pct"]
    n = len(result["positions"])
    verdict = (
        "Hipotesis on-track"
        if ret > 0 and result["winners"] >= max(1, n // 2)
        else "Belum terkonfirmasi"
    )
    spy_bit = ""
    if result.get("spy_return_pct") is not None:
        spy_bit = f" · SPY {fmt_pct(result['spy_return_pct'])}"
    print(
        f"**Return portofolio:** {fmt_pct(ret)} "
        f"({fmt_usd(result['portfolio_pnl_usd'])}) · "
        f"Menang {result['winners']}/{n} · SL hit {result['hit_sl']} · "
        f"TP hit {result['hit_tp']} · {verdict}{spy_bit}"
    )
    print()
    print("| Saham | Entry | Sekarang | Return | P&L | Status | Q entry | Thesis |")
    print("|-------|-------|----------|--------|-----|--------|---------|--------|")
    for p in result["positions"]:
        if p.get("error"):
            print(f"| **{p['symbol']}** | — | — | ERROR | — | — | — | — |")
            continue
        print(
            f"| **{p['symbol']}** | {fmt_usd(p['entry_price'])} "
            f"| {fmt_usd(p['current_price'])} | {fmt_pct(p['return_pct'])} "
            f"| {fmt_usd(p['pnl_usd'])} | {p.get('status')} "
            f"| {p.get('entry_quality', '')} "
            f"| {str(p.get('thesis', ''))[:42]} |"
        )
    print()
    print("_Paper trade — bukan transaksi real. Bukan saran investasi._")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review US paper trade")
    parser.add_argument("--portfolio", help="Path portfolio JSON (default: latest)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Save report")
    args = parser.parse_args()

    if args.portfolio:
        path = Path(args.portfolio)
    else:
        latest = DRY_RUN_DIR / "portfolio-latest.json"
        if not latest.exists():
            print("ERROR: tidak ada portfolio-latest.json — jalankan start_paper_trade.py", file=sys.stderr)
            sys.exit(1)
        path = latest

    portfolio = load_portfolio(path)
    # stamp SPY entry on first review if missing
    if "benchmark_entry_spy" not in portfolio:
        spy = fetch_stock("SPY")
        if spy and spy.price:
            portfolio["benchmark_entry_spy"] = spy.price
            path.write_text(json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")
            latest = DRY_RUN_DIR / "portfolio-latest.json"
            if latest.resolve() != path.resolve() and latest.exists():
                # keep latest in sync if reviewing dated file named latest
                pass
            latest.write_text(json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")

    result = review_portfolio(portfolio)
    if args.format == "json":
        text = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        import io

        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        print_markdown(result, portfolio)
        sys.stdout = old
        text = buf.getvalue()
        print(text)

    if args.output:
        Path(args.output).write_text(
            text if args.format == "json" else text,
            encoding="utf-8",
        )
    elif args.format == "json":
        print(text)


if __name__ == "__main__":
    main()
