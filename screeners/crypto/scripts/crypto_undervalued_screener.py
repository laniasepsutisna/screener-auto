#!/usr/bin/env python3
"""Crypto undervalued screener — Tuntun-style guidance for digital assets.

Phases:
  1. CoinGecko markets — price, MCap, ATH drawdown, volume, quality, fair value
  2. MVRV proxy (price/MA200) + NVT proxy (MCap / annualized volume)
  3. Whale accumulation proxy (volume trend + price momentum)
  4. Tuntun Guidance matrix + dry-run compatible JSON output
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from risk_management import (
    apply_risk_to_row,
    detect_value_trap,
    portfolio_correlation_warnings,
    suggest_portfolio_allocation,
)
from ta_macro import (
    MacroSnapshot,
    apply_macro_penalty,
    apply_ta,
    complete_macro,
    fetch_macro,
    passes_macro_filter,
    print_macro_header,
)
from token_unlocks import apply_unlock, load_unlock_index

_LAST_MACRO: MacroSnapshot | None = None

BASE_URL = "https://api.coingecko.com/api/v3"
USER_AGENT = "crypto-undervalued-screener/1.0"
MIN_SPACING = 1.2
CACHE_DIR = Path.home() / ".cache" / "crypto-undervalued-screener"
SKILL_DIR = Path(__file__).resolve().parent.parent

STABLECOIN_IDS = frozenset({
    "tether", "usd-coin", "dai", "first-digital-usd", "usds", "frax",
    "true-usd", "paxos-standard", "gemini-dollar", "liquity-usd",
    "paypal-usd", "ethena-usde", "usdd", "crvusd",
})

LAYER1_IDS = frozenset({
    "bitcoin", "ethereum", "solana", "cardano", "avalanche-2", "polkadot",
    "near", "aptos", "sui", "cosmos", "the-open-network", "tron",
    "bitcoin-cash", "litecoin", "hedera-hashgraph", "algorand",
})

DEFI_IDS = frozenset({
    "uniswap", "aave", "maker", "curve-dao-token", "lido-dao", "chainlink",
    "compound-governance-token", "synthetix-network-token", "pancakeswap-token",
    "gmx", "dydx", "pendle", "jupiter-exchange-solana",
})

QUALITY_LABELS = ("Best", "Bagus", "Fair", "Weak")

GUIDANCE_QUALITY_MAP: dict[str, str] = {
    "Best": "terbaik",
    "Bagus": "bagus",
    "Fair": "sedang",
    "Weak": "sedang",
}

GUIDANCE_ENTRY: dict[str, dict[str, str]] = {
    "terbaik": {
        "gt40": "Beli", "21_40": "Beli", "1_20": "Beli selektif",
        "fair": "Tunggu & amati", "ov1_99": "Tunggu & amati", "ov100": "Tunggu & amati",
    },
    "bagus": {
        "gt40": "Beli", "21_40": "Beli selektif", "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati", "ov1_99": "Tunggu & amati", "ov100": "Tunggu & amati",
    },
    "sedang": {
        "gt40": "Tunggu & amati", "21_40": "Tunggu & amati", "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati", "ov1_99": "Tunggu & amati", "ov100": "Tunggu & amati",
    },
}

GUIDANCE_HOLD: dict[str, dict[str, str]] = {
    "terbaik": {
        "gt40": "Hold", "21_40": "Hold", "1_20": "Hold",
        "fair": "Hold", "ov1_99": "Jual selektif", "ov100": "Jual",
    },
    "bagus": {
        "gt40": "Hold", "21_40": "Hold", "1_20": "Hold",
        "fair": "Jual selektif", "ov1_99": "Jual", "ov100": "Jual",
    },
    "sedang": {
        "gt40": "Tunggu & amati", "21_40": "Tunggu & amati", "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati", "ov1_99": "Tunggu & amati", "ov100": "Tunggu & amati",
    },
}

_last_request = 0.0


def throttle() -> None:
    global _last_request
    wait = MIN_SPACING - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def cg_get(path: str, params: dict[str, str] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(4):
        throttle()
        req = urllib.request.Request(
            url,
            headers={"accept": "application/json", "User-Agent": USER_AGENT},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(15 * (attempt + 1))
                continue
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"CoinGecko HTTP {e.code}: {body}") from e
    raise RuntimeError(f"CoinGecko failed: {path}")


def load_watchlist() -> list[str]:
    path = SKILL_DIR / "value_watchlist.txt"
    if not path.exists():
        return []
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ids.append(line.lower())
    return ids


def fetch_markets(pages: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        data = cg_get(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": str(per_page),
                "page": str(page),
                "sparkline": "false",
                "price_change_percentage": "7d,30d",
            },
        )
        rows.extend(data)
    return rows


def fetch_market_chart(coin_id: str, days: int = 90) -> dict[str, list]:
    cache = CACHE_DIR / date.today().isoformat() / f"chart_{coin_id}_{days}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data = cg_get(
        f"/coins/{coin_id}/market_chart",
        {"vs_currency": "usd", "days": str(days), "interval": "daily"},
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def fetch_ohlc(coin_id: str, days: int = 30) -> list[list[float]]:
    cache = CACHE_DIR / date.today().isoformat() / f"ohlc_{coin_id}_{days}.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    data = cg_get(
        f"/coins/{coin_id}/ohlc",
        {"vs_currency": "usd", "days": str(days)},
    )
    bars = data if isinstance(data, list) else []
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(bars), encoding="utf-8")
    return bars


@dataclass
class CryptoRow:
    coin_id: str
    symbol: str
    name: str = ""
    price: float | None = None
    market_cap: float | None = None
    market_cap_rank: int | None = None
    fdv: float | None = None
    volume_24h: float | None = None
    ath: float | None = None
    ath_drawdown_pct: float | None = None
    change_7d_pct: float | None = None
    change_30d_pct: float | None = None
    circulating_pct: float | None = None
    fdv_mcap_ratio: float | None = None
    volume_mcap_ratio: float | None = None
    # Phase 2
    ma200: float | None = None
    mvrv_proxy: float | None = None
    nvt_proxy: float | None = None
    # Phase 1 valuation
    fair_low: float | None = None
    fair_high: float | None = None
    undervalued_pct: float | None = None
    overvalued_pct: float | None = None
    quality: str = ""
    # Phase 3 whale
    whale_label: str = ""
    whale_net_pct: float | None = None
    whale_accumulating: bool = False
    # Phase 4 guidance
    guidance_entry: str = ""
    guidance_hold: str = ""
    # signals
    value_signals: list[str] = field(default_factory=list)
    phase: str = "1"
    # Risk management
    risk_grade: str = ""
    risk_score: int = 100
    volatility_14d_pct: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward: float | None = None
    max_loss_pct: float | None = None
    position_size_pct: float = 0.0
    position_size_usd: float = 0.0
    is_value_trap: bool = False
    passes_risk: bool = False
    risk_adjusted_score: float = 0.0
    sector: str = ""
    risk_warnings: list[str] = field(default_factory=list)
    # TA + macro
    rsi_14: float | None = None
    support: float | None = None
    resistance: float | None = None
    dist_support_pct: float | None = None
    dist_resist_pct: float | None = None
    ta_signal: str = ""
    unlock_date: str = ""
    unlock_days: int | None = None
    unlock_pct: float | None = None
    unlock_risk: str = ""
    unlock_note: str = ""

    def passes_value(self) -> bool:
        return len(self.value_signals) > 0

    def passes_quality(self, min_quality: str) -> bool:
        order = {q: i for i, q in enumerate(reversed(QUALITY_LABELS))}
        if not self.quality:
            return False
        return order.get(self.quality, -1) >= order.get(min_quality, 0)


def fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:,.4f}"
    return f"{v:.6f}"


def fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v:,.0f}"


def fair_range_str(row: CryptoRow) -> str:
    if row.fair_low is None or row.fair_high is None:
        return "—"
    return f"{fmt_price(row.fair_low)} - {fmt_price(row.fair_high)}"


def _undervalued_pct(price: float, fair_low: float, fair_high: float) -> float | None:
    if fair_high <= fair_low or price > fair_high:
        return None
    mid = (fair_low + fair_high) / 2
    return max(0.0, round((1 - price / mid) * 100))


def _overvalued_pct(price: float, fair_low: float, fair_high: float) -> float | None:
    if fair_high <= fair_low or price <= fair_high:
        return None
    mid = (fair_low + fair_high) / 2
    return max(0.0, round((price / mid - 1) * 100))


def valuation_guidance_bucket(
    undervalued_pct: float | None,
    overvalued_pct: float | None,
) -> str:
    if undervalued_pct is not None and undervalued_pct > 0:
        if undervalued_pct > 40:
            return "gt40"
        if undervalued_pct >= 21:
            return "21_40"
        return "1_20"
    if overvalued_pct is not None and overvalued_pct > 0:
        if overvalued_pct >= 100:
            return "ov100"
        return "ov1_99"
    return "fair"


def tuntun_guidance(quality: str, bucket: str, *, with_position: bool) -> str:
    q = GUIDANCE_QUALITY_MAP.get(quality, "sedang")
    table = GUIDANCE_HOLD if with_position else GUIDANCE_ENTRY
    return table.get(q, {}).get(bucket, "—")


def apply_guidance(row: CryptoRow) -> None:
    if row.fair_low is None or row.fair_high is None or row.price is None:
        row.guidance_entry = "—"
        row.guidance_hold = "—"
        return
    ov = row.overvalued_pct
    if ov is None and row.price > row.fair_high:
        ov = _overvalued_pct(row.price, row.fair_low, row.fair_high)
    bucket = valuation_guidance_bucket(row.undervalued_pct, ov)
    row.guidance_entry = tuntun_guidance(row.quality, bucket, with_position=False)
    row.guidance_hold = tuntun_guidance(row.quality, bucket, with_position=True)


def score_quality(row: CryptoRow) -> str:
    rank = row.market_cap_rank or 9999
    fdv_ratio = row.fdv_mcap_ratio or 99
    circ = row.circulating_pct or 0
    vol_ratio = row.volume_mcap_ratio or 0

    if rank <= 50 and fdv_ratio < 1.3 and circ >= 70 and vol_ratio >= 0.03:
        return "Best"
    if rank <= 200 and fdv_ratio < 2.0 and vol_ratio >= 0.01:
        return "Bagus"
    if rank <= 500 and fdv_ratio < 3.0:
        return "Fair"
    return "Weak"


def compute_fair_value(row: CryptoRow, *, use_ma: bool) -> None:
    price = row.price
    if price is None or price <= 0:
        return

    rank = row.market_cap_rank or 999
    ath = row.ath

    if use_ma and row.ma200 and row.ma200 > 0 and rank <= 50:
        row.fair_low = row.ma200 * 0.85
        row.fair_high = row.ma200 * 1.25
    elif ath and ath > 0:
        if rank <= 20:
            row.fair_low = ath * 0.55
            row.fair_high = ath * 0.80
        else:
            row.fair_low = ath * 0.30
            row.fair_high = ath * 0.55
    else:
        return

    row.undervalued_pct = _undervalued_pct(price, row.fair_low, row.fair_high)
    row.overvalued_pct = (
        _overvalued_pct(price, row.fair_low, row.fair_high)
        if row.undervalued_pct is None
        else None
    )


def compute_value_signals(row: CryptoRow, nvt_median: float | None) -> None:
    signals: list[str] = []
    if row.ath_drawdown_pct is not None and row.ath_drawdown_pct >= 40:
        signals.append(f"ATH DD {row.ath_drawdown_pct:.0f}%")
    if row.mvrv_proxy is not None and row.mvrv_proxy < 1.5:
        signals.append(f"MVRV {row.mvrv_proxy:.2f}")
    if row.fdv_mcap_ratio is not None and row.fdv_mcap_ratio < 1.5:
        signals.append(f"FDV/MCap {row.fdv_mcap_ratio:.2f}")
    if row.nvt_proxy is not None and nvt_median and row.nvt_proxy > 0 and row.nvt_proxy < nvt_median:
        signals.append(f"NVT {row.nvt_proxy:.0f}")
    if row.volume_mcap_ratio is not None and row.volume_mcap_ratio >= 0.03:
        signals.append("Likuid")
    row.value_signals = signals


def enrich_phase2(row: CryptoRow) -> None:
    try:
        chart = fetch_market_chart(row.coin_id, days=200)
        prices = [p[1] for p in chart.get("prices", []) if p[1] > 0]
        volumes = [v[1] for v in chart.get("total_volumes", []) if v[1] > 0]
        if len(prices) >= 30:
            row.ma200 = sum(prices[-200:]) / min(len(prices), 200)
            if row.ma200 and row.price:
                row.mvrv_proxy = round(row.price / row.ma200, 3)
        if row.market_cap and volumes:
            avg_vol = sum(volumes[-30:]) / min(len(volumes), 30)
            if avg_vol > 0:
                row.nvt_proxy = round(row.market_cap / (avg_vol * 365), 1)
        row.phase = "2"
    except RuntimeError:
        pass


def enrich_risk(
    row: CryptoRow,
    *,
    portfolio_usd: float,
    max_position_pct: float,
    min_rr: float,
    chart_cache: dict[str, list[float]],
) -> None:
    """Apply risk profile using cached or fetched price history."""
    prices = chart_cache.get(row.coin_id)
    if prices is None:
        try:
            chart = fetch_market_chart(row.coin_id, days=30)
            prices = [p[1] for p in chart.get("prices", []) if p[1] > 0]
            chart_cache[row.coin_id] = prices
        except RuntimeError:
            prices = []
    apply_risk_to_row(
        row,
        prices if prices else None,
        portfolio_usd=portfolio_usd,
        max_position_pct=max_position_pct,
        min_rr=min_rr,
    )


def enrich_phase3_whale(row: CryptoRow, window_days: int = 7) -> None:
    try:
        chart = fetch_market_chart(row.coin_id, days=max(30, window_days + 5))
        volumes = [v[1] for v in chart.get("total_volumes", []) if v[1] > 0]
        prices = [p[1] for p in chart.get("prices", []) if p[1] > 0]
        if len(volumes) < window_days + 7 or len(prices) < window_days + 1:
            return

        vol_recent = sum(volumes[-window_days:]) / window_days
        vol_prior = sum(volumes[-(window_days + 14):-window_days]) / 14
        price_chg = (prices[-1] / prices[-window_days] - 1) * 100 if prices[-window_days] else 0

        if vol_prior <= 0:
            return

        vol_ratio = (vol_recent / vol_prior - 1) * 100
        # Accumulation proxy: volume rising + price not falling hard
        if price_chg >= -3:
            net = vol_ratio * (1 + max(price_chg, 0) / 100)
        else:
            net = vol_ratio * 0.3  # distribution penalty

        row.whale_net_pct = round(net, 2)

        if net >= 15:
            row.whale_label = f"Big Acc (+{net:.1f}%)"
            row.whale_accumulating = True
        elif net >= 5:
            row.whale_label = f"Normal Acc (+{net:.1f}%)"
            row.whale_accumulating = True
        elif net >= 2:
            row.whale_label = f"Small Acc (+{net:.1f}%)"
            row.whale_accumulating = True
        elif net <= -5:
            row.whale_label = f"Distribusi ({net:.1f}%)"
        else:
            row.whale_label = "Netral"
        row.phase = "3"
    except RuntimeError:
        pass


def market_to_row(m: dict[str, Any]) -> CryptoRow | None:
    coin_id = m.get("id", "")
    if coin_id in STABLECOIN_IDS:
        return None

    price = m.get("current_price")
    if price is None or price <= 0:
        return None

    mcap = m.get("market_cap") or 0
    if mcap <= 0:
        return None

    ath = m.get("ath")
    ath_dd = abs(m.get("ath_change_percentage") or 0)
    max_supply = m.get("max_supply")
    circ = m.get("circulating_supply") or 0
    total = m.get("total_supply") or circ
    fdv = m.get("fully_diluted_valuation") or mcap
    vol = m.get("total_volume") or 0

    circ_pct = (circ / max_supply * 100) if max_supply else (circ / total * 100 if total else 0)
    fdv_ratio = fdv / mcap if mcap > 0 else None
    vol_ratio = vol / mcap if mcap > 0 else None

    return CryptoRow(
        coin_id=coin_id,
        symbol=(m.get("symbol") or "").upper(),
        name=m.get("name") or "",
        price=float(price),
        market_cap=float(mcap),
        market_cap_rank=m.get("market_cap_rank"),
        fdv=float(fdv),
        volume_24h=float(vol),
        ath=float(ath) if ath else None,
        ath_drawdown_pct=round(ath_dd, 1),
        change_7d_pct=m.get("price_change_percentage_7d_in_currency"),
        change_30d_pct=m.get("price_change_percentage_30d_in_currency"),
        circulating_pct=round(circ_pct, 1),
        fdv_mcap_ratio=round(fdv_ratio, 3) if fdv_ratio else None,
        volume_mcap_ratio=round(vol_ratio, 4) if vol_ratio else None,
    )


def filter_universe(rows: list[CryptoRow], universe: str, min_mcap: float) -> list[CryptoRow]:
    out: list[CryptoRow] = []
    watchlist = set(load_watchlist())
    for r in rows:
        if (r.market_cap or 0) < min_mcap:
            continue
        if universe == "top50" and (r.market_cap_rank or 999) > 50:
            continue
        if universe == "top100" and (r.market_cap_rank or 999) > 100:
            continue
        if universe == "layer1" and r.coin_id not in LAYER1_IDS:
            continue
        if universe == "defi" and r.coin_id not in DEFI_IDS:
            continue
        if universe == "watchlist" and r.coin_id not in watchlist:
            continue
        out.append(r)
    return out


def run_screener(
    *,
    universe: str = "top100",
    min_pct: float = 10.0,
    min_quality: str = "Bagus",
    min_mcap: float = 100_000_000,
    limit: int = 30,
    phase: int = 4,
    whale: bool = False,
    min_whale_pct: float = 5.0,
    whale_window: int = 7,
    symbols: list[str] | None = None,
    enrich_limit: int = 40,
    risk: bool = True,
    safe_only: bool = False,
    min_rr: float = 1.5,
    portfolio_usd: float = 10_000,
    max_position_pct: float = 5.0,
    exclude_traps: bool = True,
    ta: bool = True,
    ta_confirm: bool = False,
    macro: bool = True,
    macro_filter: bool = False,
    unlock: bool = True,
    unlock_filter: bool = False,
) -> list[CryptoRow]:
    if symbols:
        # Fetch specific coins by symbol lookup via markets
        markets = fetch_markets(pages=3, per_page=250)
        sym_set = {s.upper() for s in symbols}
        raw = [m for m in markets if (m.get("symbol") or "").upper() in sym_set]
        if not raw:
            markets_all = fetch_markets(pages=5, per_page=250)
            raw = [m for m in markets_all if (m.get("symbol") or "").upper() in sym_set]
    else:
        pages = 1 if universe in ("top50", "top100") else 2
        per_page = 100 if universe == "top100" else 50
        if universe in ("layer1", "defi", "watchlist"):
            pages = 3
            per_page = 250
        raw = fetch_markets(pages=pages, per_page=per_page)

    rows: list[CryptoRow] = []
    for m in raw:
        row = market_to_row(m)
        if row:
            rows.append(row)

    global _LAST_MACRO
    _LAST_MACRO = None
    if macro:
        try:
            snap = fetch_macro(cg_get)
            _LAST_MACRO = complete_macro(snap, rows)
        except RuntimeError:
            _LAST_MACRO = MacroSnapshot(regime="Neutral")

    if universe not in ("top50", "top100") or symbols:
        rows = filter_universe(rows, universe if not symbols else "top100", min_mcap)
    else:
        rows = [r for r in rows if (r.market_cap or 0) >= min_mcap]

    # Phase 1: quality + fair value (ATH-based first pass)
    for row in rows:
        row.quality = score_quality(row)
        compute_fair_value(row, use_ma=False)
        apply_guidance(row)

    # Phase 2: enrich top candidates with MA200/MVRV/NVT
    if phase >= 2:
        candidates = sorted(
            rows,
            key=lambda r: r.undervalued_pct or 0,
            reverse=True,
        )[:enrich_limit]
        for row in candidates:
            enrich_phase2(row)
        nvt_vals = [r.nvt_proxy for r in rows if r.nvt_proxy]
        nvt_med = median(nvt_vals) if nvt_vals else None
        for row in rows:
            compute_value_signals(row, nvt_med)
            if row.ma200:
                compute_fair_value(row, use_ma=True)
                apply_guidance(row)
    else:
        for row in rows:
            compute_value_signals(row, None)

    # Phase 3: whale proxy on filtered set
    if phase >= 3 and whale:
        whale_candidates = [
            r for r in rows
            if r.passes_quality(min_quality)
            and (r.undervalued_pct or 0) >= min_pct * 0.5
        ]
        whale_candidates = sorted(
            whale_candidates,
            key=lambda r: r.undervalued_pct or 0,
            reverse=True,
        )[:enrich_limit]
        for row in whale_candidates:
            enrich_phase3_whale(row, window_days=whale_window)

    # Pre-filter candidates for risk enrichment
    pre_filtered: list[CryptoRow] = []
    for row in rows:
        if not row.passes_value():
            continue
        if not row.passes_quality(min_quality):
            continue
        if (row.undervalued_pct or 0) < min_pct:
            continue
        if whale and phase >= 3:
            if not row.whale_accumulating:
                continue
            if (row.whale_net_pct or 0) < min_whale_pct:
                continue
        pre_filtered.append(row)

    # Risk management — trap scan on all, full profile on top candidates
    chart_cache: dict[str, list[float]] = {}
    if risk and pre_filtered:
        for row in pre_filtered:
            trap, warnings = detect_value_trap(row)
            row.is_value_trap = trap
            row.risk_warnings = list(warnings)

        survivors = [
            r for r in pre_filtered
            if not (exclude_traps and r.is_value_trap)
        ]
        risk_candidates = sorted(
            survivors,
            key=lambda r: r.undervalued_pct or 0,
            reverse=True,
        )[:enrich_limit]
        for row in risk_candidates:
            if phase >= 2 and row.coin_id not in chart_cache:
                try:
                    chart = fetch_market_chart(row.coin_id, days=200)
                    chart_cache[row.coin_id] = [
                        p[1] for p in chart.get("prices", []) if p[1] > 0
                    ]
                except RuntimeError:
                    pass
        for row in risk_candidates:
            enrich_risk(
                row,
                portfolio_usd=portfolio_usd,
                max_position_pct=max_position_pct,
                min_rr=min_rr,
                chart_cache=chart_cache,
            )

    # TA confirmation from the same price history (top candidates only)
    if ta and pre_filtered:
        ta_pool = [
            r for r in pre_filtered
            if not (risk and exclude_traps and r.is_value_trap)
        ]
        ta_rows = sorted(
            ta_pool,
            key=lambda r: r.undervalued_pct or 0,
            reverse=True,
        )[:enrich_limit]
        for row in ta_rows:
            prices = chart_cache.get(row.coin_id)
            if prices is None:
                try:
                    chart = fetch_market_chart(row.coin_id, days=30)
                    prices = [p[1] for p in chart.get("prices", []) if p[1] > 0]
                    chart_cache[row.coin_id] = prices
                except RuntimeError:
                    prices = []
            ohlc: list[list[float]] = []
            try:
                ohlc = fetch_ohlc(row.coin_id, days=30)
            except RuntimeError:
                ohlc = []
            apply_ta(row, prices if prices else None, ohlc=ohlc or None)
            if macro and _LAST_MACRO:
                apply_macro_penalty(row, _LAST_MACRO)

    if unlock and pre_filtered:
        try:
            unlock_index, _src = load_unlock_index()
        except Exception:
            unlock_index = {}
        for row in pre_filtered:
            if risk and exclude_traps and row.is_value_trap:
                continue
            apply_unlock(row, unlock_index)

    # Final filter with risk / TA / macro gates
    filtered: list[CryptoRow] = []
    for row in pre_filtered:
        if risk and exclude_traps and row.is_value_trap:
            continue
        if risk and safe_only:
            if not row.risk_grade or row.risk_grade not in ("A", "B"):
                continue
            if not row.passes_risk:
                continue
        if ta and ta_confirm and row.ta_signal not in ("Entry OK", "Selektif"):
            continue
        if unlock and unlock_filter and getattr(row, "unlock_risk", "") == "Tinggi":
            continue
        if macro and macro_filter and _LAST_MACRO and not passes_macro_filter(row, _LAST_MACRO):
            continue
        filtered.append(row)

    if risk:
        filtered.sort(key=lambda r: r.risk_adjusted_score or 0, reverse=True)
    else:
        filtered.sort(key=lambda r: r.undervalued_pct or 0, reverse=True)
    return filtered[:limit]


def print_markdown(rows: list[CryptoRow], args: argparse.Namespace) -> None:
    filters = [f"Undervalued (%) ≥ {args.min_pct:.0f}%", f"Kualitas ≥ {args.min_quality}"]
    if args.whale and args.phase >= 3:
        filters.append(f"Akumulasi whale ({args.whale_window}d, net ≥ {args.min_whale_pct:.0f}%)")
    if getattr(args, "risk", True):
        filters.append("Risk: value trap excluded")
        if getattr(args, "safe_only", False):
            filters.append("Grade A/B only")
    if getattr(args, "ta_confirm", False):
        filters.append("TA: Entry OK / Selektif")
    if getattr(args, "macro_filter", False):
        filters.append("Macro filter on")
    if getattr(args, "unlock_filter", False):
        filters.append("Unlock Tinggi excluded")
    print("# Top Undervalued Crypto")
    print()
    print(f"**{len(rows)} coin dalam daftar** · Filter: {' · '.join(filters)}")
    print()
    print_macro_header(_LAST_MACRO)

    use_risk = getattr(args, "risk", True)
    use_ta = getattr(args, "ta", True)
    show_whale = args.whale and args.phase >= 3

    if use_risk:
        if use_ta:
            print(
                "| Coin | Grade | Undervalued | TA | RSI | Dist S | Unlock | Guidance | "
                "Harga | Stop Loss | R:R |"
            )
            print(
                "|------|-------|-------------|----|-----|--------|--------|----------|"
                "-------|-----------|-----|"
            )
            for r in rows:
                trap = " ⚠️" if r.is_value_trap else ""
                dist = f"{r.dist_support_pct:.1f}%" if r.dist_support_pct is not None else "—"
                rsi = f"{r.rsi_14:.0f}" if r.rsi_14 is not None else "—"
                ul = r.unlock_risk or "—"
                print(
                    f"| **{r.symbol}**{trap} | {r.risk_grade or '—'} "
                    f"| {r.undervalued_pct or 0:.0f}% | {r.ta_signal or '—'} | {rsi} | {dist} "
                    f"| {ul} | {r.guidance_entry} | {fmt_price(r.price)} | {fmt_price(r.stop_loss)} "
                    f"| {r.risk_reward or '—'} |"
                )
        else:
            print(
                "| Coin | Grade | Risk Score | Undervalued | Guidance | Harga | Stop Loss | "
                "Take Profit | R:R | Size | Max Loss |"
            )
            print(
                "|------|-------|------------|-------------|----------|-------|-----------|"
                "------------|-----|------|----------|"
            )
            for r in rows:
                trap = " ⚠️" if r.is_value_trap else ""
                print(
                    f"| **{r.symbol}**{trap} | {r.risk_grade or '—'} | {r.risk_score} "
                    f"| {r.undervalued_pct or 0:.0f}% | {r.guidance_entry} "
                    f"| {fmt_price(r.price)} | {fmt_price(r.stop_loss)} "
                    f"| {fmt_price(r.take_profit)} | {r.risk_reward or '—'} "
                    f"| {r.position_size_pct:.0f}% | {r.max_loss_pct or '—'}% |"
                )
        print()
        # Portfolio suggestion
        alloc = suggest_portfolio_allocation(rows, getattr(args, "portfolio_usd", 10_000))
        if alloc:
            print("## Rekomendasi Alokasi Portofolio (risk-adjusted)")
            print()
            print("| Coin | Grade | Alokasi | USD | Stop Loss | Take Profit | R:R |")
            print("|------|-------|---------|-----|-----------|-------------|-----|")
            for a in alloc:
                print(
                    f"| **{a['symbol']}** | {a['risk_grade']} | {a['allocation_pct']}% "
                    f"| ${a['allocation_usd']:,.0f} | {fmt_price(a['stop_loss'])} "
                    f"| {fmt_price(a['take_profit'])} | {a['risk_reward'] or '—'} |"
                )
            print()
        corr = portfolio_correlation_warnings(rows)
        if corr:
            print("**⚠️ Peringatan diversifikasi:**")
            for w in corr:
                print(f"- {w}")
            print()
        # Top picks summary
        safe = [r for r in rows if r.passes_risk and r.risk_grade in ("A", "B")]
        if safe:
            print("**Kandidat teraman (Grade A/B):**", ", ".join(
                f"{r.symbol} ({r.risk_grade}, R:R {r.risk_reward})" for r in safe[:5]
            ))
            print()
        if use_ta:
            entry_ok = [r for r in rows if r.ta_signal == "Entry OK"]
            selektif = [r for r in rows if r.ta_signal == "Selektif"]
            if entry_ok or selektif:
                bits = []
                if entry_ok:
                    bits.append("Entry OK: " + ", ".join(r.symbol for r in entry_ok[:5]))
                if selektif:
                    bits.append("Selektif: " + ", ".join(r.symbol for r in selektif[:5]))
                print("**TA timing:** " + " · ".join(bits))
                print()
        hot_unlock = [r for r in rows if r.unlock_risk in ("Tinggi", "Waspada") and r.unlock_note]
        if hot_unlock:
            print("**Unlock calendar:**")
            for r in hot_unlock[:8]:
                print(f"- **{r.symbol}** {r.unlock_risk}: {r.unlock_note}")
            print()
    elif show_whale and args.phase >= 2:
        print(
            "| Coin | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | "
            "Harga | Harga Wajar | MVRV | ATH DD | Whale | 7d |"
        )
        print(
            "|------|----------|-----------------|--------------|------------|"
            "-------|-------------|------|--------|-------|-----|"
        )
        for r in rows:
            coin = f"**{r.symbol}**"
            print(
                f"| {coin} | {r.quality} | {r.undervalued_pct or 0:.0f}% "
                f"| {r.guidance_entry} | {r.guidance_hold} "
                f"| {fmt_price(r.price)} | {fair_range_str(r)} "
                f"| {r.mvrv_proxy or '—'} | {r.ath_drawdown_pct or 0:.0f}% "
                f"| {r.whale_label} | {r.change_7d_pct or 0:+.1f}% |"
            )
    elif show_whale:
        print(
            "| Coin | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | "
            "Harga | Harga Wajar | MVRV | NVT | ATH DD | 7d |"
        )
        print(
            "|------|----------|-----------------|--------------|------------|"
            "-------|-------------|------|-----|--------|-----|"
        )
        for r in rows:
            coin = f"**{r.symbol}**"
            print(
                f"| {coin} | {r.quality} | {r.undervalued_pct or 0:.0f}% "
                f"| {r.guidance_entry} | {r.guidance_hold} "
                f"| {fmt_price(r.price)} | {fair_range_str(r)} "
                f"| {r.mvrv_proxy or '—'} | {r.nvt_proxy or '—'} "
                f"| {r.ath_drawdown_pct or 0:.0f}% | {r.change_7d_pct or 0:+.1f}% |"
            )
    else:
        print(
            "| Coin | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | "
            "Harga | Harga Wajar | MCap | ATH DD | Vol/MCap |"
        )
        print(
            "|------|----------|-----------------|--------------|------------|"
            "-------|-------------|------|--------|----------|"
        )
        for r in rows:
            coin = f"**{r.symbol}**"
            print(
                f"| {coin} | {r.quality} | {r.undervalued_pct or 0:.0f}% "
                f"| {r.guidance_entry} | {r.guidance_hold} "
                f"| {fmt_price(r.price)} | {fair_range_str(r)} "
                f"| {fmt_usd(r.market_cap)} | {r.ath_drawdown_pct or 0:.0f}% "
                f"| {(r.volume_mcap_ratio or 0) * 100:.1f}% |"
            )

    print()
    print("_Tuntun Guidance: Tanpa Posisi = belum punya coin · Ada Posisi = sudah hold_")
    if use_risk:
        print("_Risk: Grade A=aman · B=moderat · C=agresif · D=tolak · Stop loss = 2×ATR atau support 14d_")
    if getattr(args, "ta", True):
        print("_TA: RSI(14) + jarak ke support 14d · Entry OK / Selektif / Tunggu / Hindari_")
    if _LAST_MACRO:
        print("_Macro: BTC.D + regime (BTC/Alt/Neutral) + Fear & Greed — filter alt saat BTC season_")
    print("_Data: CoinGecko · MVRV/NVT = proxy heuristik · Whale = volume+momentum proxy_")
    print("_Bukan saran investasi. Crypto sangat volatil — selalu gunakan stop loss._")


def print_table(rows: list[CryptoRow], args: argparse.Namespace) -> None:
    print_markdown(rows, args)


def write_csv(rows: list[CryptoRow], path: Path) -> None:
    fields = [
        "symbol", "coin_id", "name", "quality", "risk_grade", "risk_score",
        "undervalued_pct", "risk_adjusted_score", "guidance_entry", "guidance_hold",
        "price", "stop_loss", "take_profit", "risk_reward", "max_loss_pct",
        "position_size_pct", "position_size_usd", "fair_low", "fair_high",
        "market_cap", "market_cap_rank", "ath_drawdown_pct", "mvrv_proxy", "nvt_proxy",
        "whale_label", "whale_net_pct", "change_7d_pct", "sector", "is_value_trap",
        "rsi_14", "support", "resistance", "dist_support_pct", "ta_signal",
        "unlock_date", "unlock_days", "unlock_pct", "unlock_risk", "unlock_note",
        "value_signals", "risk_warnings",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            d = asdict(r)
            d["value_signals"] = "; ".join(r.value_signals)
            d["risk_warnings"] = "; ".join(r.risk_warnings)
            w.writerow({k: d.get(k) for k in fields})


def main() -> None:
    parser = argparse.ArgumentParser(description="Crypto undervalued screener (Tuntun-style)")
    parser.add_argument("--universe", default="top100",
                        choices=["top50", "top100", "layer1", "defi", "watchlist"])
    parser.add_argument("--symbols", nargs="+", help="Specific symbols e.g. BTC ETH SOL")
    parser.add_argument("--min-pct", type=float, default=10.0)
    parser.add_argument("--min-quality", default="Bagus", choices=list(QUALITY_LABELS))
    parser.add_argument("--min-mcap", type=float, default=100_000_000, help="Min market cap USD")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--phase", type=int, default=4, choices=[1, 2, 3, 4],
                        help="Max phase to run (1=basic, 2=+MVRV/NVT, 3=+whale, 4=+guidance)")
    parser.add_argument("--whale", action="store_true", help="Filter whale accumulation (phase 3+)")
    parser.add_argument("--whale-window", type=int, default=7, help="Whale window days")
    parser.add_argument("--min-whale-pct", type=float, default=5.0)
    parser.add_argument("--risk", action="store_true", default=True,
                        help="Enable risk management (default on)")
    parser.add_argument("--no-risk", action="store_true", help="Disable risk module")
    parser.add_argument("--safe-only", action="store_true",
                        help="Only Grade A/B coins that pass risk checks")
    parser.add_argument("--min-rr", type=float, default=1.5, help="Min risk/reward ratio")
    parser.add_argument("--portfolio-usd", type=float, default=10_000,
                        help="Portfolio size for allocation display")
    parser.add_argument("--max-position", type=float, default=5.0,
                        help="Max position size %% per coin")
    parser.add_argument("--include-traps", action="store_true",
                        help="Include value trap coins in results")
    parser.add_argument("--ta", action="store_true", default=True, help="Enable RSI + S/R (default on)")
    parser.add_argument("--no-ta", action="store_true", help="Disable TA module")
    parser.add_argument("--ta-confirm", action="store_true",
                        help="Only coins with TA Entry OK or Selektif")
    parser.add_argument("--macro", action="store_true", default=True, help="BTC.D + Fear & Greed (default on)")
    parser.add_argument("--no-macro", action="store_true", help="Disable macro header/penalty")
    parser.add_argument("--macro-filter", action="store_true",
                        help="Hard-exclude weak alts during BTC season / risk-off")
    parser.add_argument("--unlock", action="store_true", default=True, help="Token unlock calendar (default on)")
    parser.add_argument("--no-unlock", action="store_true", help="Disable unlock calendar")
    parser.add_argument("--unlock-filter", action="store_true",
                        help="Exclude coins with unlock risk Tinggi (14h, ≥1% supply)")
    parser.add_argument("--format", dest="fmt", default="markdown",
                        choices=["markdown", "table", "json", "csv"])
    parser.add_argument("--output", help="Output file for csv/json")
    args = parser.parse_args()
    if args.no_risk:
        args.risk = False
    if args.no_ta:
        args.ta = False
    if args.no_macro:
        args.macro = False
    if getattr(args, "no_unlock", False):
        args.unlock = False

    try:
        rows = run_screener(
            universe=args.universe,
            min_pct=args.min_pct,
            min_quality=args.min_quality,
            min_mcap=args.min_mcap,
            limit=args.limit,
            phase=args.phase,
            whale=args.whale,
            min_whale_pct=args.min_whale_pct,
            whale_window=args.whale_window,
            symbols=args.symbols,
            risk=args.risk,
            safe_only=args.safe_only,
            min_rr=args.min_rr,
            portfolio_usd=args.portfolio_usd,
            max_position_pct=args.max_position,
            exclude_traps=not args.include_traps,
            ta=args.ta,
            ta_confirm=args.ta_confirm,
            macro=args.macro,
            macro_filter=args.macro_filter,
            unlock=getattr(args, "unlock", True),
            unlock_filter=getattr(args, "unlock_filter", False),
        )
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.fmt == "json":
        text = json.dumps([asdict(r) for r in rows], indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text)
    elif args.fmt == "csv":
        out = Path(args.output) if args.output else Path("crypto_screener.csv")
        write_csv(rows, out)
        print(f"Written to {out}", file=sys.stderr)
    elif args.fmt == "table":
        print_table(rows, args)
    else:
        print_markdown(rows, args)

    if not rows:
        print("\n_0 coin — coba turunkan --min-pct atau --min-quality Fair_", file=sys.stderr)


if __name__ == "__main__":
    main()
