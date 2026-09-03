#!/usr/bin/env python3
"""Review crypto paper-trade dry run vs current CoinGecko prices."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from crypto_undervalued_screener import cg_get, fmt_price  # noqa: E402

SKILL_DIR = SCRIPT_DIR.parent
DRY_RUN_DIR = SKILL_DIR / "dry-run"


def load_portfolio(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_price_usd(symbol: str) -> float | None:
    sym = symbol.upper()
    for page in range(1, 4):
        data = cg_get(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": "250",
                "page": str(page),
                "sparkline": "false",
            },
        )
        for row in data:
            if (row.get("symbol") or "").upper() == sym:
                return float(row["current_price"])
    return None


def review_portfolio(portfolio: dict) -> dict:
    capital = float(portfolio.get("virtual_capital_usd", 10_000))
    positions_out: list[dict] = []
    total_entry = 0.0
    total_current = 0.0

    for pos in portfolio["positions"]:
        symbol = pos["symbol"]
        weight = float(pos.get("weight_pct", 0)) / 100.0
        alloc = float(pos.get("allocation_usd") or capital * weight)
        entry = float(pos["entry_price"])
        current = fetch_price_usd(symbol)

        if current is None:
            positions_out.append({"symbol": symbol, "error": "price_unavailable", **pos})
            continue

        shares = alloc / entry if entry else 0
        entry_value = shares * entry
        current_value = shares * current
        pnl = current_value - entry_value
        ret_pct = (current / entry - 1) * 100 if entry else 0.0

        sl = pos.get("stop_loss")
        tp = pos.get("take_profit")
        status = "open"
        if sl is not None and current <= float(sl):
            status = "hit_SL"
        elif tp is not None and current >= float(tp):
            status = "hit_TP"

        total_entry += entry_value
        total_current += current_value

        positions_out.append({
            "symbol": symbol,
            "name": pos.get("name", ""),
            "weight_pct": pos.get("weight_pct"),
            "entry_price": entry,
            "current_price": round(current, 6),
            "return_pct": round(ret_pct, 2),
            "pnl_usd": round(pnl, 2),
            "stop_loss": sl,
            "take_profit": tp,
            "status": status,
            "entry_quality": pos.get("entry_quality"),
            "entry_undervalued_pct": pos.get("entry_undervalued_pct"),
            "entry_guidance": pos.get("entry_guidance"),
            "entry_ta": pos.get("entry_ta"),
            "thesis": pos.get("thesis", ""),
        })

    portfolio_ret = ((total_current / total_entry) - 1) * 100 if total_entry else 0.0
    winners = sum(1 for p in positions_out if p.get("return_pct", 0) > 0)

    return {
        "portfolio_id": portfolio.get("id"),
        "asset_class": "crypto",
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entry_date": portfolio.get("created_at"),
        "target_review_date": portfolio.get("review_at"),
        "virtual_capital_usd": capital,
        "portfolio_return_pct": round(portfolio_ret, 2),
        "portfolio_pnl_usd": round(total_current - total_entry, 2),
        "winners": winners,
        "losers": sum(1 for p in positions_out if p.get("return_pct", 0) < 0),
        "positions": sorted(positions_out, key=lambda x: x.get("return_pct", -999), reverse=True),
    }


def print_markdown(result: dict, portfolio: dict) -> None:
    print("# Dry Run Review — Crypto Paper Trade")
    print()
    print(f"**Portfolio:** {result.get('portfolio_id')}  ")
    print(f"**Entry:** {(portfolio.get('created_at') or '')[:10]}  ")
    print(f"**Review target:** {portfolio.get('review_at', '—')}  ")
    print(f"**End:** {portfolio.get('end_at', '—')}  ")
    print(f"**Modal virtual:** ${result['virtual_capital_usd']:,.0f}")
    if portfolio.get("cash_pct") is not None:
        print(f"**Cash idle (awal):** {portfolio['cash_pct']}%")
    print()
    ret = result["portfolio_return_pct"]
    criteria = portfolio.get("success_criteria") or {}
    min_ret = float(criteria.get("portfolio_return_pct_min", 0))
    winners_ok = result["winners"] >= int(criteria.get("winners_min", 0) or 0)
    verdict = (
        "✅ Hipotesis terkonfirmasi"
        if ret >= min_ret and winners_ok and ret > 0
        else "⏳ Belum terkonfirmasi / proses masih jalan"
    )
    print(
        f"**Return portofolio (invested):** {ret:+.2f}% "
        f"(${result['portfolio_pnl_usd']:+,.2f}) · "
        f"Menang {result['winners']}/{len(result['positions'])} coin · {verdict}"
    )
    print()
    print("| Coin | Entry | Sekarang | Return | P&L | Status | TA entry | Thesis |")
    print("|------|-------|----------|--------|-----|--------|----------|--------|")
    for p in result["positions"]:
        if p.get("error"):
            print(f"| **{p['symbol']}** | — | — | ERROR | — | — | — | — |")
            continue
        thesis = (p.get("thesis") or "")[:40]
        print(
            f"| **{p['symbol']}** | ${fmt_price(p['entry_price'])} "
            f"| ${fmt_price(p['current_price'])} | {p['return_pct']:+.2f}% "
            f"| ${p['pnl_usd']:+,.2f} | {p.get('status', 'open')} "
            f"| {p.get('entry_ta') or '—'} | {thesis} |"
        )
    print()
    print("_Paper trade crypto — bukan transaksi real. Bukan saran investasi._")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review crypto dry-run portfolio")
    parser.add_argument("--portfolio", help="Path to portfolio JSON")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Save report to file")
    args = parser.parse_args()

    if args.portfolio:
        path = Path(args.portfolio)
    else:
        files = sorted(DRY_RUN_DIR.glob("portfolio-*.json"), reverse=True)
        latest = DRY_RUN_DIR / "portfolio-latest.json"
        if latest.exists():
            path = latest
        elif not files:
            print("ERROR: No portfolio in dry-run/", file=sys.stderr)
            sys.exit(1)
        else:
            path = files[0]

    portfolio = load_portfolio(path)
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

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
