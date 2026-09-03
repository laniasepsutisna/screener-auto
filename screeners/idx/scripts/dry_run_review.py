#!/usr/bin/env python3
"""Review paper-trade dry run: compare current price vs entry snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from tuntun_undervalued_screener import fetch_stock, load_token  # noqa: E402

SKILL_DIR = SCRIPT_DIR.parent
DRY_RUN_DIR = SKILL_DIR / "dry-run"


def load_portfolio(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_idr(v: float) -> str:
    return f"{v:,.0f}"


def fmt_pct(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


def review_portfolio(portfolio: dict, *, use_cache: bool = False) -> dict:
    token = load_token()
    capital = float(portfolio.get("virtual_capital_idr", 100_000_000))
    positions_out: list[dict] = []
    total_entry = 0.0
    total_current = 0.0

    for pos in portfolio["positions"]:
        symbol = pos["symbol"]
        weight = float(pos.get("weight_pct", 0)) / 100.0
        alloc = capital * weight
        entry = float(pos["entry_price"])
        row = fetch_stock(token, symbol, light=True, use_cache=use_cache)
        current = float(row.price) if row and row.price else None

        if current is None:
            positions_out.append(
                {
                    "symbol": symbol,
                    "error": "price_unavailable",
                    **pos,
                }
            )
            continue

        shares = alloc / entry
        entry_value = shares * entry
        current_value = shares * current
        pnl = current_value - entry_value
        ret_pct = (current / entry - 1) * 100

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
                "pnl_idr": round(pnl, 0),
                "entry_quality": pos.get("entry_quality"),
                "entry_undervalued_pct": pos.get("entry_undervalued_pct"),
                "entry_bandar": pos.get("entry_bandar"),
                "entry_rs": pos.get("entry_rs"),
                "current_undervalued_pct": row.undervalued_pct if row else None,
                "current_quality": row.quality if row else None,
                "thesis": pos.get("thesis", ""),
            }
        )

    portfolio_ret = ((total_current / total_entry) - 1) * 100 if total_entry else 0.0
    winners = sum(1 for p in positions_out if p.get("return_pct", 0) > 0)
    losers = sum(1 for p in positions_out if p.get("return_pct", 0) < 0)

    return {
        "portfolio_id": portfolio.get("id"),
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entry_date": portfolio.get("created_at"),
        "target_review_date": portfolio.get("review_at"),
        "virtual_capital_idr": capital,
        "portfolio_return_pct": round(portfolio_ret, 2),
        "portfolio_pnl_idr": round(total_current - total_entry, 0),
        "winners": winners,
        "losers": losers,
        "flat": len(positions_out) - winners - losers,
        "positions": sorted(
            positions_out,
            key=lambda x: x.get("return_pct", -999),
            reverse=True,
        ),
    }


def print_markdown(result: dict, portfolio: dict) -> None:
    print("# Dry Run Review — Paper Trade")
    print()
    print(f"**Portfolio:** {result.get('portfolio_id')}  ")
    print(f"**Entry:** {portfolio.get('created_at', '')[:10]}  ")
    print(f"**Review:** {date.today().isoformat()}  ")
    print(f"**Modal virtual:** Rp {fmt_idr(result['virtual_capital_idr'])}")
    print()
    ret = result["portfolio_return_pct"]
    verdict = "✅ Hipotesis terkonfirmasi" if ret > 0 and result["winners"] >= 3 else "❌ Belum terkonfirmasi"
    print(
        f"**Return portofolio:** {fmt_pct(ret)} "
        f"(Rp {fmt_idr(result['portfolio_pnl_idr'])}) · "
        f"Menang {result['winners']}/{len(result['positions'])} saham · {verdict}"
    )
    print()
    print("| Saham | Entry | Sekarang | Return | P&L (Rp) | Kualitas | Thesis |")
    print("|-------|-------|----------|--------|----------|----------|--------|")
    for p in result["positions"]:
        if p.get("error"):
            print(f"| **{p['symbol']}** | — | — | ERROR | — | — | — |")
            continue
        print(
            f"| **{p['symbol']}** | {fmt_idr(p['entry_price'])} "
            f"| {fmt_idr(p['current_price'])} | {fmt_pct(p['return_pct'])} "
            f"| {fmt_idr(p['pnl_idr'])} | {p.get('entry_quality', '')} "
            f"| {p.get('thesis', '')[:40]}… |"
        )
    print()
    print("_Paper trade — bukan transaksi real. Bukan saran investasi._")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review dry-run paper trade portfolio")
    parser.add_argument(
        "--portfolio",
        help="Path to portfolio JSON (default: latest in dry-run/)",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Save report to file")
    parser.add_argument("--no-cache", action="store_true", help="Fetch fresh prices")
    args = parser.parse_args()

    if args.portfolio:
        path = Path(args.portfolio)
    else:
        files = sorted(DRY_RUN_DIR.glob("portfolio-*.json"), reverse=True)
        if not files:
            print("ERROR: No portfolio in dry-run/", file=sys.stderr)
            sys.exit(1)
        path = files[0]

    portfolio = load_portfolio(path)
    result = review_portfolio(portfolio, use_cache=not args.no_cache)

    if args.format == "json":
        text = json.dumps(result, indent=2, ensure_ascii=False)
    else:
        import io

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        print_markdown(result, portfolio)
        sys.stdout = old_stdout
        text = buf.getvalue()

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
