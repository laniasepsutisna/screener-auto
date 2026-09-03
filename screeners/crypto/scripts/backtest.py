#!/usr/bin/env python3
"""Point-in-time backtest of the crypto screener rules (price-derived only).

No lookahead: MA200, ATH, RSI, S/R, ATR computed from data available on that day.
Does NOT replay Stockbit-style quality or live unlock calendar (those need
point-in-time fundamentals we don't have).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from crypto_undervalued_screener import SKILL_DIR, fetch_market_chart  # noqa: E402
from risk_management import compute_atr_pct  # noqa: E402
from ta_macro import (  # noqa: E402
    chart_support_resistance,
    dist_pct,
    rsi_wilder,
    ta_signal,
)

SYMBOL = {
    "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA",
    "polkadot": "DOT", "avalanche-2": "AVAX", "chainlink": "LINK", "aave": "AAVE",
    "arbitrum": "ARB", "near": "NEAR", "sui": "SUI", "aptos": "APT",
    "uniswap": "UNI", "litecoin": "LTC", "cosmos": "ATOM",
}
DEFAULT_UNIVERSE = (
    "bitcoin", "ethereum", "solana", "cardano", "polkadot",
    "avalanche-2", "chainlink", "aave", "arbitrum", "near",
)


@dataclass
class Trade:
    symbol: str
    coin_id: str
    entry_ts: int
    exit_ts: int | None = None
    entry: float = 0.0
    exit: float = 0.0
    stop: float = 0.0
    take: float = 0.0
    size_usd: float = 0.0
    reason: str = ""
    ta: str = ""
    undervalued_pct: float = 0.0
    r_multiple: float = 0.0
    pnl_usd: float = 0.0
    bars_held: int = 0


@dataclass
class BacktestResult:
    start_equity: float
    end_equity: float
    return_pct: float
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe: float
    time_in_market_pct: float
    trade_list: list[Trade] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    benchmarks: dict[str, float] = field(default_factory=dict)


def _ts_to_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()


def _fmt_px(x: float) -> str:
    if x >= 1000:
        return f"${x:,.0f}"
    if x >= 1:
        return f"${x:.2f}"
    return f"${x:.4g}"


def load_series(coin_id: str, days: int) -> list[tuple[int, float, float, float]]:
    """Daily bars [(ts_ms, high, low, close)] from CoinGecko market_chart.

    OHLC 365d is 4-day candles — skip. Daily chart is close-only (H=L=C)
    unless the API returns multiple points per UTC day.
    """
    chart = fetch_market_chart(coin_id, days=days)
    prices = [(int(p[0]), float(p[1])) for p in chart.get("prices", []) if p[1] > 0]
    by_date: dict[str, list[tuple[int, float]]] = {}
    for ts, px in prices:
        by_date.setdefault(_ts_to_date(ts), []).append((ts, px))
    bars: list[tuple[int, float, float, float]] = []
    for day in sorted(by_date):
        pts = by_date[day]
        pxs = [p for _, p in pts]
        bars.append((pts[-1][0], max(pxs), min(pxs), pxs[-1]))
    return bars


def undervalued_from_ma(price: float, ma200: float) -> float | None:
    if ma200 <= 0 or price <= 0:
        return None
    fair_low, fair_high = ma200 * 0.85, ma200 * 1.25
    if fair_high <= fair_low:
        return None
    mid = (fair_low + fair_high) / 2
    if price > fair_high:
        return None
    return max(0.0, (1 - price / mid) * 100)


def signals_at(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    i: int,
) -> dict:
    window = closes[: i + 1]
    price = closes[i]
    ma200 = sum(window[-200:]) / min(len(window), 200) if len(window) >= 30 else None
    ath = max(window)
    ath_dd = (1 - price / ath) * 100 if ath > 0 else 0.0
    underval = undervalued_from_ma(price, ma200) if ma200 else None
    mvrv = price / ma200 if ma200 else None
    rsi = rsi_wilder(window)
    ohlc = [[0, 0, highs[k], lows[k], closes[k]] for k in range(len(closes))]
    support, resist = chart_support_resistance(window, ohlc=ohlc, price=price)
    d_sup = dist_pct(price, support)
    d_res = round((resist - price) / price * 100, 2) if resist and price else None
    ta = ta_signal(rsi, d_sup, d_res)
    atr = compute_atr_pct(window)
    chg30 = (price / window[-31] - 1) * 100 if len(window) >= 31 else 0.0
    return {
        "price": price,
        "ma200": ma200,
        "underval": underval,
        "mvrv": mvrv,
        "ath_dd": ath_dd,
        "rsi": rsi,
        "ta": ta,
        "support": support,
        "atr": atr,
        "chg30": chg30,
        "high": highs[i],
        "low": lows[i],
    }


def want_entry(sig: dict, *, min_pct: float, ta_confirm: bool) -> bool:
    underval = sig["underval"]
    if underval is None or underval < min_pct:
        return False
    if sig["ath_dd"] >= 85:
        return False  # value-trap proxy
    if sig["mvrv"] is not None and sig["mvrv"] > 1.5:
        return False
    if sig["chg30"] < -35:
        return False  # falling knife
    ta = sig["ta"]
    if ta == "Hindari":
        return False
    if ta_confirm and ta not in ("Entry OK", "Selektif"):
        return False
    if not ta_confirm and ta == "Tunggu" and (sig["rsi"] or 50) >= 65:
        return False
    return True


def stops(price: float, atr_pct: float | None, support: float | None) -> tuple[float, float]:
    sl_atr = price * (1 - (atr_pct or 8) / 100 * 2)
    sl_sup = support * 0.98 if support else sl_atr
    sl = min(sl_atr, sl_sup)
    sl = max(sl, price * 0.70)
    risk = price - sl
    tp = price + max(risk * 2.0, price * 0.12)  # min ~2R or +12%
    tp = min(tp, price * 1.80)
    return sl, tp


def run_backtest(
    coin_ids: list[str],
    *,
    days: int = 365,
    warmup: int = 200,
    capital: float = 10_000,
    risk_pct: float = 1.0,
    max_positions: int = 4,
    max_hold: int = 21,
    min_pct: float = 10.0,
    ta_confirm: bool = True,
    cooldown: int = 5,
) -> BacktestResult:
    series: dict[str, list[tuple[int, float, float, float]]] = {}
    for cid in coin_ids:
        try:
            bars = load_series(cid, days)
        except RuntimeError as e:
            print(f"SKIP {cid}: {e}", file=sys.stderr)
            continue
        if len(bars) < warmup + 20:
            print(f"SKIP {cid}: data {len(bars)} bars < warmup {warmup}", file=sys.stderr)
            continue
        series[cid] = bars

    if not series:
        return BacktestResult(
            start_equity=capital, end_equity=capital, return_pct=0,
            trades=0, wins=0, losses=0, win_rate=0, avg_r=0, expectancy_r=0,
            profit_factor=0, max_drawdown_pct=0, sharpe=0, time_in_market_pct=0,
            notes=["Tidak ada data historis."],
        )

    # Align on UTC date (timestamps differ slightly across coins)
    ref_id = "bitcoin" if "bitcoin" in series else max(series, key=lambda k: len(series[k]))
    ref = series[ref_id]
    index_maps = {
        cid: {_ts_to_date(bar[0]): n for n, bar in enumerate(bars)}
        for cid, bars in series.items()
    }

    equity = capital
    peak = capital
    max_dd = 0.0
    daily_ret: list[float] = []
    open_pos: dict[str, Trade] = {}
    last_exit_i: dict[str, int] = {}
    trades: list[Trade] = []
    invested_days = 0

    start_i = warmup
    for i in range(start_i, len(ref)):
        ts, _, _, _ = ref[i]
        day = _ts_to_date(ts)
        eq_before = equity

        # --- exits (bar high/low vs SL/TP; daily chart often H=L=C) ---
        to_close: list[str] = []
        for cid, tr in open_pos.items():
            j = index_maps[cid].get(day)
            if j is None or j <= 0:
                continue
            _t, high, low, close = series[cid][j]
            risk = tr.entry - tr.stop
            exit_px = None
            reason = ""
            if low <= tr.stop and high >= tr.take:
                exit_px, reason = tr.stop, "SL (same bar as TP — count SL)"
            elif low <= tr.stop:
                exit_px, reason = tr.stop, "SL"
            elif high >= tr.take:
                exit_px, reason = tr.take, "TP"
            elif tr.bars_held >= max_hold:
                exit_px, reason = close, "time"
            if exit_px is None:
                tr.bars_held += 1
                continue
            qty = tr.size_usd / tr.entry
            pnl = qty * (exit_px - tr.entry)
            tr.exit = exit_px
            tr.exit_ts = ts
            tr.reason = reason
            tr.pnl_usd = round(pnl, 2)
            tr.r_multiple = round((exit_px - tr.entry) / risk, 2) if risk > 0 else 0.0
            equity += pnl
            trades.append(tr)
            last_exit_i[cid] = i
            to_close.append(cid)
        for cid in to_close:
            open_pos.pop(cid, None)

        # --- entries ---
        if len(open_pos) < max_positions:
            ranked: list[tuple[float, str, dict]] = []
            for cid, bars in series.items():
                if cid in open_pos:
                    continue
                if i - last_exit_i.get(cid, -999) < cooldown:
                    continue
                j = index_maps[cid].get(day)
                if j is None or j < warmup:
                    continue
                closes = [b[3] for b in bars[: j + 1]]
                highs = [b[1] for b in bars[: j + 1]]
                lows = [b[2] for b in bars[: j + 1]]
                sig = signals_at(closes, highs, lows, len(closes) - 1)
                if not want_entry(sig, min_pct=min_pct, ta_confirm=ta_confirm):
                    continue
                ranked.append((sig["underval"] or 0, cid, sig))
            ranked.sort(reverse=True)
            for _u, cid, sig in ranked:
                if len(open_pos) >= max_positions:
                    break
                price = sig["price"]
                sl, tp = stops(price, sig["atr"], sig["support"])
                if price <= sl:
                    continue
                risk_frac = (price - sl) / price
                if risk_frac <= 0:
                    continue
                used = sum(t.size_usd for t in open_pos.values())
                size = min(equity * 0.05, equity * (risk_pct / 100) / risk_frac, max(0.0, equity - used))
                if size < 50:
                    continue
                open_pos[cid] = Trade(
                    symbol=SYMBOL.get(cid, cid.split("-")[0].upper()[:6]),
                    coin_id=cid,
                    entry_ts=ts,
                    entry=price,
                    stop=sl,
                    take=tp,
                    size_usd=size,
                    ta=sig["ta"],
                    undervalued_pct=round(sig["underval"] or 0, 1),
                )
                # cash reserved conceptually; PnL realized on exit (fully invested model
                # uses equity for sizing only — no double-count)

        if open_pos:
            invested_days += 1
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)
        daily_ret.append((equity / eq_before - 1) if eq_before else 0.0)

    # Force close remaining at last close
    last_ts = ref[-1][0]
    for cid, tr in list(open_pos.items()):
        j = index_maps[cid].get(_ts_to_date(last_ts), len(series[cid]) - 1)
        close = series[cid][j][3]
        risk = tr.entry - tr.stop
        qty = tr.size_usd / tr.entry
        pnl = qty * (close - tr.entry)
        tr.exit = close
        tr.exit_ts = last_ts
        tr.reason = "eod"
        tr.pnl_usd = round(pnl, 2)
        tr.r_multiple = round((close - tr.entry) / risk, 2) if risk > 0 else 0.0
        equity += pnl
        trades.append(tr)

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    r_s = [t.r_multiple for t in trades]
    gp = sum(t.pnl_usd for t in wins)
    gl = abs(sum(t.pnl_usd for t in losses))
    std = (sum((x - (sum(daily_ret) / len(daily_ret))) ** 2 for x in daily_ret) / len(daily_ret)) ** 0.5 if daily_ret else 0
    mean = sum(daily_ret) / len(daily_ret) if daily_ret else 0
    sharpe = (mean / std * math.sqrt(365)) if std > 1e-12 else 0.0
    test_days = max(1, len(ref) - warmup)

    # Buy-and-hold over the same test window (warmup → last bar)
    start_day = _ts_to_date(ref[warmup][0])
    end_day = _ts_to_date(ref[-1][0])

    def _bh(cid: str) -> float | None:
        m = index_maps.get(cid)
        bars = series.get(cid)
        if not m or not bars:
            return None
        i0 = m.get(start_day)
        i1 = m.get(end_day)
        if i0 is None or i1 is None or bars[i0][3] <= 0:
            return None
        return round((bars[i1][3] / bars[i0][3] - 1) * 100, 2)

    benchmarks: dict[str, float] = {}
    for cid in ("bitcoin", "ethereum", "solana"):
        r = _bh(cid)
        if r is not None:
            benchmarks[SYMBOL.get(cid, cid)] = r
    eq_rets = [v for v in (_bh(c) for c in series) if v is not None]
    if eq_rets:
        benchmarks["EQW_univ"] = round(sum(eq_rets) / len(eq_rets), 2)

    return BacktestResult(
        start_equity=capital,
        end_equity=round(equity, 2),
        return_pct=round((equity / capital - 1) * 100, 2),
        trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        avg_r=round(sum(r_s) / len(r_s), 2) if r_s else 0.0,
        expectancy_r=round(sum(r_s) / len(r_s), 2) if r_s else 0.0,
        profit_factor=round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0),
        max_drawdown_pct=round(max_dd, 2),
        sharpe=round(sharpe, 2),
        time_in_market_pct=round(invested_days / test_days * 100, 1),
        trade_list=trades,
        benchmarks=benchmarks,
        notes=[
            f"Universe: {', '.join(series.keys())}",
            f"Bars uji ≈ {test_days} hari ({start_day} → {end_day}) setelah warmup {warmup}.",
            "Entry: MA200 undervalued + MVRV<1.5 + ATH DD<85% + TA (bukan Hindari).",
            "Exit: SL 2×ATR / TP ~2R / time 21 hari. Same-bar SL+TP dihitung SL.",
            "Data: CoinGecko daily close (H/L = close kecuali ada beberapa titik/hari).",
            "Bukan replay kualitas Tuntun/unlock live — hanya aturan harga.",
        ],
    )


def print_markdown(res: BacktestResult, ta_confirm: bool, *, compact: bool = False) -> None:
    print("# Backtest — Crypto Undervalued Rules")
    print()
    print(
        f"**Modal:** ${res.start_equity:,.0f} → **${res.end_equity:,.0f}** "
        f"({res.return_pct:+.2f}%)  "
    )
    print(
        f"**Trades:** {res.trades} · Win {res.wins}/{res.trades} "
        f"({res.win_rate:.1f}%) · Avg R {res.avg_r:+.2f} · "
        f"PF {res.profit_factor} · Max DD {res.max_drawdown_pct:.1f}% · "
        f"Sharpe {res.sharpe:.2f} · Time-in-mkt {res.time_in_market_pct:.0f}%"
    )
    print()
    print(f"Filter TA: {'Entry OK / Selektif only' if ta_confirm else 'bukan Hindari'}")
    if res.benchmarks:
        parts = " · ".join(f"{k} {v:+.1f}%" for k, v in res.benchmarks.items())
        print(f"**Buy & hold (window sama):** {parts}")
    print()
    for n in res.notes:
        print(f"- {n}")
    print()
    if compact or not res.trade_list:
        if not res.trade_list:
            print("_Tidak ada trade — longgarkan `--min-pct` atau matikan `--ta-confirm`._")
        print()
        print("_Bukan saran investasi. Past performance ≠ future results._")
        return

    print("| Coin | Entry | Exit | Alasan | TA | Underval | R | P&L |")
    print("|------|-------|------|--------|----|----------|---|-----|")
    for t in sorted(res.trade_list, key=lambda x: x.entry_ts):
        print(
            f"| **{t.symbol}** | {_ts_to_date(t.entry_ts)} {_fmt_px(t.entry)} "
            f"| {_ts_to_date(t.exit_ts or 0)} {_fmt_px(t.exit)} "
            f"| {t.reason} | {t.ta} | {t.undervalued_pct:.0f}% "
            f"| {t.r_multiple:+.2f} | ${t.pnl_usd:+,.0f} |"
        )
    print()
    print("_Bukan saran investasi. Backtest close/OHLC harian, biaya & slippage belum dihitung._")


def print_compare(strict: BacktestResult, loose: BacktestResult) -> None:
    print("# Perbandingan — TA ketat vs longgar + Buy & Hold")
    print()
    bh = strict.benchmarks or loose.benchmarks
    print("| Strategi | Return | Trades | Win% | Avg R | PF | Max DD | Sharpe | Time-in-mkt |")
    print("|----------|--------|--------|------|-------|----|--------|--------|-------------|")
    for label, r in (("TA Entry OK/Selektif", strict), ("TA longgar (bukan Hindari)", loose)):
        print(
            f"| **{label}** | {r.return_pct:+.2f}% | {r.trades} | {r.win_rate:.1f}% | "
            f"{r.avg_r:+.2f} | {r.profit_factor} | {r.max_drawdown_pct:.1f}% | "
            f"{r.sharpe:.2f} | {r.time_in_market_pct:.0f}% |"
        )
    for k, v in bh.items():
        label = f"Buy & hold {k}" if k != "EQW_univ" else "Buy & hold equal-weight universe"
        print(f"| {label} | {v:+.2f}% | — | — | — | — | — | — | 100% |")
    print()
    print(
        "Catatan: strategi aktif risk 1%/trade, max 4 posisi — return absolut tidak apple-to-apple "
        "dengan B&H full-invested; bandingkan lebih ke **arah edge** dan **DD/Sharpe**."
    )
    print()
    print("_Bukan saran investasi._")


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest crypto undervalued + TA rules")
    p.add_argument("--coins", nargs="+", default=list(DEFAULT_UNIVERSE),
                   help="CoinGecko ids")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--warmup", type=int, default=200)
    p.add_argument("--capital", type=float, default=10_000)
    p.add_argument("--risk-pct", type=float, default=1.0, help="Risk per trade %% of equity")
    p.add_argument("--max-positions", type=int, default=4)
    p.add_argument("--max-hold", type=int, default=21)
    p.add_argument("--min-pct", type=float, default=10.0)
    p.add_argument("--ta-confirm", action="store_true", default=True)
    p.add_argument("--no-ta-confirm", action="store_true")
    p.add_argument("--compare", action="store_true",
                   help="Bandingkan TA ketat vs longgar + buy&hold")
    p.add_argument("--format", dest="fmt", choices=["markdown", "json"], default="markdown")
    p.add_argument("--output", help="Save report")
    args = p.parse_args()
    if args.no_ta_confirm:
        args.ta_confirm = False

    kwargs = dict(
        days=args.days,
        warmup=args.warmup,
        capital=args.capital,
        risk_pct=args.risk_pct,
        max_positions=args.max_positions,
        max_hold=args.max_hold,
        min_pct=args.min_pct,
    )

    if args.compare:
        strict = run_backtest(args.coins, ta_confirm=True, **kwargs)
        loose = run_backtest(args.coins, ta_confirm=False, **kwargs)
        import io
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        print_compare(strict, loose)
        print()
        print("---")
        print()
        print_markdown(strict, True, compact=True)
        print()
        print("---")
        print()
        print_markdown(loose, False, compact=True)
        sys.stdout = old
        text = buf.getvalue()
    else:
        res = run_backtest(args.coins, ta_confirm=args.ta_confirm, **kwargs)
        if args.fmt == "json":
            payload = asdict(res)
            payload["trade_list"] = [asdict(t) for t in res.trade_list]
            text = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            import io
            buf = io.StringIO()
            old = sys.stdout
            sys.stdout = buf
            print_markdown(res, args.ta_confirm)
            sys.stdout = old
            text = buf.getvalue()

    out_dir = SKILL_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "backtest-latest.md" if args.fmt != "json" else out_dir / "backtest-latest.json"
    if args.compare:
        latest = out_dir / "backtest-compare.md"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
