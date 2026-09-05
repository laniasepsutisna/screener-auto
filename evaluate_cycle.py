#!/usr/bin/env python3
"""Evaluation scorecard — checkpoint & gate tracking for paper trade cycles.

Reads reports/portfolio/positions.json, fetches live prices, compares vs
benchmarks, evaluates gate criteria, and appends to reports/evaluation/.

Usage:
  python evaluate_cycle.py                    # auto-detect checkpoint vs gate
  python evaluate_cycle.py --type checkpoint
  python evaluate_cycle.py --type gate1
  python evaluate_cycle.py --cycle cycle-001 --lessons "INKP lemah"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

ROOT = Path(__file__).resolve().parent
EVAL_DIR = ROOT / "reports" / "evaluation"
POSITIONS_PATH = ROOT / "reports" / "portfolio" / "positions.json"
CYCLES_PATH = EVAL_DIR / "cycles.json"
GATES_PATH = EVAL_DIR / "gates.json"
SNAPSHOTS_DIR = EVAL_DIR / "snapshots"
REPORTS_DIR = EVAL_DIR / "reports"

BENCHMARKS = {
    "idx": {"symbol": "^JKSE", "label": "IHSG"},
    "us": {"symbol": "SPY", "label": "SPY"},
    "crypto": {"symbol": "BTC-USD", "label": "BTC"},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_yahoo_prices(symbols: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    if not symbols:
        return prices
    unique = list(dict.fromkeys(symbols))
    try:
        tickers = yf.Tickers(" ".join(unique))
        for sym in unique:
            try:
                t = tickers.tickers[sym]
                info = t.fast_info
                price = getattr(info, "last_price", None) or getattr(
                    info, "regular_market_price", None
                )
                if price is None:
                    hist = t.history(period="5d")
                    if not hist.empty:
                        price = float(hist["Close"].iloc[-1])
                if price:
                    prices[sym] = float(price)
            except Exception:
                pass
    except Exception:
        pass
    for sym in unique:
        if sym not in prices:
            try:
                hist = yf.Ticker(sym).history(period="5d")
                if not hist.empty:
                    prices[sym] = float(hist["Close"].iloc[-1])
            except Exception:
                pass
    return prices


def fetch_crypto_prices(positions: list[dict]) -> dict[str, float]:
    sys.path.insert(0, str(ROOT / "screeners" / "crypto" / "scripts"))
    from crypto_undervalued_screener import cg_get  # noqa: E402

    price_map: dict[str, float] = {}
    for page in range(1, 3):
        rows = cg_get(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": "250",
                "page": str(page),
                "sparkline": "false",
            },
        )
        for r in rows:
            price_map[r["id"]] = float(r["current_price"])
            price_map[(r.get("symbol") or "").upper()] = float(r["current_price"])
    out: dict[str, float] = {}
    for pos in positions:
        sym = pos["symbol"]
        cg_id = pos.get("coingecko_id")
        p = price_map.get(cg_id) or price_map.get(sym.upper())
        if p is not None:
            out[sym] = p
    return out


def fetch_benchmark_price(symbol: str) -> float | None:
    return fetch_yahoo_prices([symbol]).get(symbol)


def fetch_price_on_date(symbol: str, on_date: str) -> float | None:
    """Close price on or just after on_date (for benchmark since entry)."""
    try:
        start = date.fromisoformat(on_date)
        end = start + timedelta(days=7)
        hist = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat())
        if hist.empty:
            return fetch_benchmark_price(symbol)
        return float(hist["Close"].iloc[0])
    except Exception:
        return fetch_benchmark_price(symbol)


def benchmark_return_since(entry_price: float | None, current: float | None) -> float | None:
    if entry_price and current and entry_price > 0:
        return round((current / entry_price - 1) * 100, 2)
    return None


def review_book(book_id: str, book: dict, prices: dict[str, float]) -> dict[str, Any]:
    capital = float(book["capital"])
    positions_out: list[dict] = []
    total_entry = 0.0
    total_current = 0.0
    hit_sl = hit_tp = 0

    for pos in book["positions"]:
        sym = pos["symbol"]
        weight = float(pos["weight_pct"]) / 100
        alloc = float(pos.get("allocation_usd") or capital * weight)
        entry = float(pos["entry_price"])
        sl = pos.get("stop_loss")
        tp = pos.get("take_profit")
        current = prices.get(sym)

        if current is None:
            positions_out.append({"symbol": sym, "error": "price_unavailable"})
            continue

        shares = alloc / entry if entry else 0
        entry_val = shares * entry
        cur_val = shares * current
        ret = (current / entry - 1) * 100 if entry else 0.0
        total_entry += entry_val
        total_current += cur_val

        status = "open"
        if sl is not None and current <= float(sl):
            status = "hit_SL"
            hit_sl += 1
        elif tp is not None and current >= float(tp):
            status = "hit_TP"
            hit_tp += 1

        positions_out.append(
            {
                "symbol": sym,
                "name": pos.get("name", sym),
                "entry_price": entry,
                "current_price": round(current, 6 if book_id == "crypto" else 2),
                "return_pct": round(ret, 2),
                "pnl": round(cur_val - entry_val, 2),
                "status": status,
                "weight_pct": pos.get("weight_pct"),
                "quality": pos.get("quality", ""),
                "thesis": pos.get("thesis", ""),
            }
        )

    port_ret = round(((total_current / total_entry) - 1) * 100, 2) if total_entry else 0.0
    winners = sum(1 for p in positions_out if not p.get("error") and p.get("return_pct", 0) > 0)
    n = sum(1 for p in positions_out if not p.get("error"))

    return {
        "book_id": book_id,
        "label": book.get("label", book_id.upper()),
        "currency": book.get("currency", "USD"),
        "capital": capital,
        "cash_pct": book.get("cash_pct"),
        "portfolio_id": book.get("portfolio_id"),
        "entry_date": book.get("entry_date"),
        "portfolio_return_pct": port_ret,
        "portfolio_pnl": round(total_current - total_entry, 2),
        "winners": winners,
        "losers": n - winners,
        "positions_total": n,
        "hit_sl": hit_sl,
        "hit_tp": hit_tp,
        "positions": sorted(
            positions_out,
            key=lambda x: x.get("return_pct", -999),
            reverse=True,
        ),
    }


def capture_benchmark_entry(cycle: dict) -> dict[str, Any]:
    bench = cycle.get("benchmark_entry") or {}
    if bench.get("captured_at") and bench.get("idx"):
        return bench
    entry_date = cycle.get("entry_date") or _today()
    captured: dict[str, Any] = {
        "captured_at": _now_iso(),
        "entry_date": entry_date,
    }
    for market, meta in BENCHMARKS.items():
        px = fetch_price_on_date(meta["symbol"], entry_date)
        captured[market] = px
    cycle["benchmark_entry"] = captured
    return captured


def get_benchmark_returns(cycle: dict) -> dict[str, dict[str, Any]]:
    bench = cycle.get("benchmark_entry") or {}
    out: dict[str, dict[str, Any]] = {}
    for market, meta in BENCHMARKS.items():
        entry_px = bench.get(market)
        current = fetch_benchmark_price(meta["symbol"])
        ret = benchmark_return_since(entry_px, current)
        out[market] = {
            "label": meta["label"],
            "symbol": meta["symbol"],
            "entry_price": entry_px,
            "current_price": current,
            "return_pct": ret,
        }
    return out


def detect_eval_type(cycle: dict, forced: str | None) -> str:
    if forced and forced != "auto":
        return forced
    today = _today()
    end = cycle.get("end_date", "")
    if today >= end:
        return "gate1"
    checkpoints = cycle.get("checkpoint_dates") or []
    if today in checkpoints:
        return "checkpoint"
    review = cycle.get("entry_date", "")
    # weekly-ish: every 7 days from entry
    try:
        entry_d = date.fromisoformat(cycle.get("entry_date", today))
        days_in = (date.today() - entry_d).days
        if days_in > 0 and days_in % 7 == 0:
            return "checkpoint"
    except ValueError:
        pass
    return "checkpoint"


def evaluate_gate1(
    markets: dict[str, dict],
    benchmarks: dict[str, dict],
    gates_cfg: dict,
) -> dict[str, Any]:
    crit = gates_cfg.get("gates", {}).get("gate1", {}).get("criteria", {})
    idx = markets.get("idx", {})
    us = markets.get("us", {})
    crypto = markets.get("crypto", {})

    idx_ret = idx.get("portfolio_return_pct", 0)
    us_ret = us.get("portfolio_return_pct", 0)
    crypto_ret = crypto.get("portfolio_return_pct", 0)
    ihsg_ret = benchmarks.get("idx", {}).get("return_pct")
    spy_ret = benchmarks.get("us", {}).get("return_pct")

    checks = {
        "process_sl_respected": (
            idx.get("hit_sl", 0) + us.get("hit_sl", 0) + crypto.get("hit_sl", 0) == 0
        ),
        "idx_return_ok": idx_ret >= float(crit.get("idx_return_min_pct", 0)),
        "idx_winners_ok": idx.get("winners", 0) >= int(crit.get("idx_winners_min", 3)),
        "idx_beat_benchmark": ihsg_ret is not None and idx_ret >= ihsg_ret,
        "us_return_ok": us_ret >= float(crit.get("us_return_min_pct", -2)),
        "us_beat_benchmark": spy_ret is not None and us_ret >= spy_ret,
        "crypto_sl_ok": crypto.get("hit_sl", 0) <= int(crit.get("crypto_sl_hit_max", 0)),
        "crypto_return_ok": crypto_ret >= float(crit.get("crypto_invested_return_min_pct", -5)),
    }

    # Pass: process + idx (return OR beat) + us min + crypto sl
    idx_pass = checks["idx_return_ok"] or checks["idx_beat_benchmark"]
    us_pass = checks["us_return_ok"]
    crypto_pass = checks["crypto_sl_ok"] and checks["crypto_return_ok"]
    passed = checks["process_sl_respected"] and idx_pass and us_pass and crypto_pass

    reasons: list[str] = []
    if not checks["process_sl_respected"]:
        reasons.append("Ada posisi hit SL — evaluasi apakah sudah di-exit")
    if not idx_pass:
        reasons.append(
            f"IDX return {idx_ret:+.2f}% di bawah target & belum beat IHSG ({ihsg_ret}%)"
        )
    if not us_pass:
        reasons.append(f"US return {us_ret:+.2f}% di bawah minimum {crit.get('us_return_min_pct')}%")
    if not checks["crypto_sl_ok"]:
        reasons.append("Crypto ada SL hit")
    if not checks["crypto_return_ok"]:
        reasons.append(f"Crypto invested return {crypto_ret:+.2f}% terlalu rendah")

    return {
        "gate": "gate1",
        "pass": passed,
        "checks": checks,
        "fail_reasons": reasons if not passed else [],
        "summary": "PASS" if passed else "FAIL",
    }


def suggest_lessons(markets: dict[str, dict], gate_result: dict | None) -> list[str]:
    lessons: list[str] = []
    for bid, m in markets.items():
        losers = [p for p in m.get("positions", []) if p.get("return_pct", 0) < -1]
        for p in losers:
            lessons.append(f"{bid.upper()} {p['symbol']} melemah ({p.get('return_pct', 0):+.2f}%) — pantau thesis")
        if m.get("hit_sl", 0) > 0:
            lessons.append(f"{bid.upper()}: {m['hit_sl']} posisi hit SL — review disiplin exit")
    if gate_result and gate_result.get("pass"):
        lessons.append("Gate lulus — pertimbangkan lanjut ke siklus berikutnya")
    elif gate_result and not gate_result.get("pass"):
        lessons.append("Gate gagal — ulang paper trade, jangan real money")
    return lessons[:8]


def suggest_improvements(markets: dict[str, dict], gate_result: dict | None) -> list[str]:
    improvements: list[str] = []
    idx = markets.get("idx", {})
    if idx.get("losers", 0) >= 2:
        improvements.append("IDX: pertimbangkan filter sektor (hindari kertas/siklikal lemah bersamaan)")
    us = markets.get("us", {})
    if us.get("portfolio_return_pct", 0) < 0:
        improvements.append("US: prioritaskan saham dengan UV tertinggi + guidance Beli (bukan Tunggu)")
    crypto = markets.get("crypto", {})
    if crypto.get("cash_pct", 0) and float(crypto.get("cash_pct", 0)) > 50:
        improvements.append("Crypto: cash idle tinggi sudah benar saat makro risk-off — pertahankan")
    if gate_result and not gate_result.get("pass"):
        improvements.append("Catat secara manual pelanggaran proses (chase, ignore SL) di --lessons")
    return improvements[:6]


def render_markdown(
    eval_type: str,
    cycle: dict,
    markets: dict[str, dict],
    benchmarks: dict[str, dict],
    gate_result: dict | None,
    lessons: list[str],
    improvements: list[str],
    eval_id: str,
) -> str:
    today = _today()
    lines = [
        f"# Evaluation Scorecard — {eval_type.upper()}",
        "",
        f"**Eval ID:** {eval_id}  ",
        f"**Siklus:** {cycle['id']}  ",
        f"**Tanggal:** {today}  ",
        f"**Entry siklus:** {cycle.get('entry_date')} → **End:** {cycle.get('end_date')}  ",
        f"**Gate target:** {cycle.get('gate_target', 'gate1')}  ",
        "",
        "> Bukan saran investasi. Data untuk evaluasi proses paper trade.",
        "",
        "---",
        "",
        "## Ringkasan pasar",
        "",
        "| Pasar | Return | P&L | Menang | SL hit | vs Benchmark |",
        "|-------|--------|-----|--------|--------|--------------|",
    ]

    for bid in ("idx", "us", "crypto"):
        m = markets.get(bid, {})
        b = benchmarks.get(bid, {})
        cur = m.get("currency", "USD")
        pnl = m.get("portfolio_pnl", 0)
        if cur == "IDR":
            pnl_s = f"Rp {pnl:,.0f}"
        else:
            pnl_s = f"${pnl:,.2f}"
        b_ret = b.get("return_pct")
        b_label = b.get("label", "")
        vs = "—"
        if b_ret is not None and m.get("portfolio_return_pct") is not None:
            diff = round(m["portfolio_return_pct"] - b_ret, 2)
            vs = f"{b_label} {b_ret:+.2f}% ({'+' if diff >= 0 else ''}{diff:.2f}%)"
        lines.append(
            f"| **{m.get('label', bid)}** | {m.get('portfolio_return_pct', 0):+.2f}% "
            f"| {pnl_s} | {m.get('winners', 0)}/{m.get('positions_total', 0)} "
            f"| {m.get('hit_sl', 0)} | {vs} |"
        )

    if gate_result:
        title = f"## Gate 1 — {gate_result['summary']}"
        if gate_result.get("note"):
            title += " (preview)"
        lines.extend(
            [
                "",
                "---",
                "",
                title,
                "",
            ]
        )
        if gate_result.get("note"):
            lines.append(f"_{gate_result['note']}_")
            lines.append("")
        lines.extend(
            [
                "| Check | Hasil |",
                "|-------|-------|",
            ]
        )
        for k, v in gate_result.get("checks", {}).items():
            lines.append(f"| {k} | {'✅' if v else '❌'} |")
        if gate_result.get("fail_reasons"):
            lines.extend(["", "**Alasan gagal (jika final):**"])
            for r in gate_result["fail_reasons"]:
                lines.append(f"- {r}")

    lines.extend(["", "---", "", "## Lessons learned", ""])
    for lesson in lessons or ["_(belum ada — isi manual via --lessons)_"]:
        lines.append(f"- {lesson}")

    lines.extend(["", "## Perbaikan ke depan", ""])
    for imp in improvements or ["_(belum ada)_"]:
        lines.append(f"- {imp}")

    lines.extend(
        [
            "",
            "---",
            "",
            "## Keputusan",
            "",
            "| Item | Nilai |",
            "|------|-------|",
            f"| Tipe evaluasi | {eval_type} |",
            f"| Gate 1 | {gate_result['summary'] if gate_result else 'N/A (checkpoint)'} |",
            f"| Lanjut real money? | **{'PERTIMBANGKAN' if gate_result and gate_result.get('pass') is True else 'BELUM'}** |",
            "",
            f"_Generated by `evaluate_cycle.py` · {eval_id}_",
        ]
    )
    return "\n".join(lines) + "\n"


def update_go_live(cycles_data: dict, gate_result: dict | None, cycle_id: str) -> None:
    gl = cycles_data.setdefault("go_live", {})
    if gate_result and gate_result.get("pass"):
        gl["gate1_passed"] = True
        gl["gate1_passed_at"] = _today()
        # Count gate1 passes across cycles
        passes = sum(
            1
            for c in cycles_data.get("cycles", [])
            if c.get("gate1_result") == "PASS"
        )
        if passes >= 2:
            gl["gate2_passed"] = True
            gl["gate2_passed_at"] = _today()
        gl["ready_for_real_money"] = passes >= 2
        note = f"{cycle_id} gate1 PASS pada {_today()}"
        if note not in gl.get("notes", []):
            gl.setdefault("notes", []).append(note)


def is_cycle_end_reached(cycle: dict) -> bool:
    try:
        return _today() >= (cycle.get("end_date") or _today())
    except (TypeError, ValueError):
        return False


def run_evaluation(
    *,
    cycle_id: str | None = None,
    eval_type: str = "auto",
    lessons_extra: str = "",
    improvements_extra: str = "",
    positions_path: Path = POSITIONS_PATH,
    dry_run: bool = False,
    force_gate: bool = False,
) -> dict[str, Any]:
    if not positions_path.exists():
        raise FileNotFoundError(f"positions.json tidak ditemukan: {positions_path}")
    if not CYCLES_PATH.exists():
        raise FileNotFoundError(f"cycles.json tidak ditemukan: {CYCLES_PATH}")

    positions = load_json(positions_path)
    cycles_data = load_json(CYCLES_PATH)
    gates_cfg = load_json(GATES_PATH) if GATES_PATH.exists() else {}

    active_id = cycle_id or cycles_data.get("active_cycle_id", "cycle-001")
    cycle = next((c for c in cycles_data["cycles"] if c["id"] == active_id), None)
    if not cycle:
        raise ValueError(f"Siklus tidak ditemukan: {active_id}")

    resolved_type = detect_eval_type(cycle, eval_type if eval_type != "auto" else None)

    # Prices
    books = positions.get("books", {})
    idx_prices: dict[str, float] = {}
    us_prices: dict[str, float] = {}
    crypto_prices: dict[str, float] = {}

    if "idx" in books:
        yahoo_syms = [p.get("yahoo") or f"{p['symbol']}.JK" for p in books["idx"]["positions"]]
        fetched = fetch_yahoo_prices(yahoo_syms)
        for p in books["idx"]["positions"]:
            y = p.get("yahoo") or f"{p['symbol']}.JK"
            if y in fetched:
                idx_prices[p["symbol"]] = fetched[y]

    if "us" in books:
        yahoo_syms = [p.get("yahoo") or p["symbol"] for p in books["us"]["positions"]]
        fetched = fetch_yahoo_prices(yahoo_syms + ["SPY"])
        for p in books["us"]["positions"]:
            y = p.get("yahoo") or p["symbol"]
            if y in fetched:
                us_prices[p["symbol"]] = fetched[y]

    if "crypto" in books:
        crypto_prices = fetch_crypto_prices(books["crypto"]["positions"])

    markets: dict[str, dict] = {}
    if "idx" in books:
        markets["idx"] = review_book("idx", books["idx"], idx_prices)
    if "us" in books:
        markets["us"] = review_book("us", books["us"], us_prices)
    if "crypto" in books:
        markets["crypto"] = review_book("crypto", books["crypto"], crypto_prices)

    capture_benchmark_entry(cycle)
    benchmarks = get_benchmark_returns(cycle)

    gate_result = None
    gate_final = False
    if resolved_type == "gate1":
        gate_result = evaluate_gate1(markets, benchmarks, gates_cfg)
        gate_final = is_cycle_end_reached(cycle) or force_gate
        if not gate_final:
            gate_result = {
                **gate_result,
                "summary": "PREVIEW",
                "pass": None,
                "note": (
                    f"Siklus belum selesai (end {cycle.get('end_date')}). "
                    "Ini preview saja — gate resmi dijalankan otomatis pada end_date."
                ),
            }

    lessons = suggest_lessons(markets, gate_result)
    improvements = suggest_improvements(markets, gate_result)
    if lessons_extra:
        lessons.append(lessons_extra)
    if improvements_extra:
        improvements.append(improvements_extra)

    eval_id = f"eval-{active_id}-{_today()}-{resolved_type}"
    snapshot = {
        "id": eval_id,
        "cycle_id": active_id,
        "type": resolved_type,
        "date": _today(),
        "created_at": _now_iso(),
        "markets": markets,
        "benchmarks": benchmarks,
        "gate1": gate_result,
        "lessons": lessons,
        "improvements": improvements,
    }

    md = render_markdown(
        resolved_type, cycle, markets, benchmarks, gate_result, lessons, improvements, eval_id
    )

    if dry_run:
        return {"eval_id": eval_id, "type": resolved_type, "snapshot": snapshot, "markdown": md}

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    snap_path = SNAPSHOTS_DIR / f"{eval_id}.json"
    save_json(snap_path, snapshot)

    report_path = REPORTS_DIR / f"{_today()}-{resolved_type}.md"
    report_latest = REPORTS_DIR / "latest.md"
    report_path.write_text(md, encoding="utf-8")
    report_latest.write_text(md, encoding="utf-8")

    # Update cycle registry (avoid duplicate same-day same-type)
    existing_ids = {e.get("id") for e in cycle.get("evaluations", [])}
    if eval_id not in existing_ids:
        cycle.setdefault("evaluations", []).append(
            {
                "id": eval_id,
                "date": _today(),
                "type": resolved_type,
                "snapshot": str(snap_path.relative_to(ROOT)),
                "report": str(report_path.relative_to(ROOT)),
            }
        )

    if gate_result and gate_final:
        cycle["gate1_result"] = gate_result["summary"]
        if gate_result.get("pass"):
            cycle["status"] = "completed_pass"
        elif gate_result.get("pass") is False:
            cycle["status"] = "completed_fail"
        update_go_live(cycles_data, gate_result, active_id)
    elif gate_result and not gate_final:
        cycle["gate1_preview"] = gate_result.get("checks")

    cycle.setdefault("lessons", [])
    for lesson in lessons:
        if lesson not in cycle["lessons"]:
            cycle["lessons"].append(lesson)
    cycle.setdefault("improvements", [])
    for imp in improvements:
        if imp not in cycle["improvements"]:
            cycle["improvements"].append(imp)

    cycles_data["updated_at"] = _now_iso()
    save_json(CYCLES_PATH, cycles_data)

    return {
        "eval_id": eval_id,
        "type": resolved_type,
        "snapshot_path": str(snap_path),
        "report_path": str(report_path),
        "gate1": gate_result,
        "markets": {k: {"return_pct": v.get("portfolio_return_pct"), "hit_sl": v.get("hit_sl")} for k, v in markets.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluation scorecard paper trade")
    parser.add_argument("--cycle", default=None, help="Cycle ID (default: active)")
    parser.add_argument(
        "--type",
        default="auto",
        choices=["auto", "checkpoint", "gate1", "gate2", "gate3", "gate4"],
    )
    parser.add_argument("--lessons", default="", help="Lessons learned tambahan")
    parser.add_argument("--improvements", default="", help="Perbaikan tambahan")
    parser.add_argument("--positions", type=Path, default=POSITIONS_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Jangan simpan file")
    parser.add_argument(
        "--force-gate",
        action="store_true",
        help="Finalisasi gate1 meski end_date belum tiba (testing/admin)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON ke stdout")
    args = parser.parse_args()

    try:
        result = run_evaluation(
            cycle_id=args.cycle,
            eval_type=args.type,
            lessons_extra=args.lessons,
            improvements_extra=args.improvements,
            positions_path=args.positions,
            dry_run=args.dry_run,
            force_gate=args.force_gate,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json or args.dry_run:
        out = {k: v for k, v in result.items() if k != "markdown"}
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"✅ Evaluation selesai: {result['eval_id']}")
        print(f"   Tipe: {result['type']}")
        print(f"   Snapshot: {result['snapshot_path']}")
        print(f"   Report: {result['report_path']}")
        if result.get("gate1"):
            print(f"   Gate 1: {result['gate1']['summary']}")
        for bid, m in result.get("markets", {}).items():
            print(f"   {bid.upper()}: {m['return_pct']:+.2f}% · SL hit {m['hit_sl']}")


if __name__ == "__main__":
    main()
