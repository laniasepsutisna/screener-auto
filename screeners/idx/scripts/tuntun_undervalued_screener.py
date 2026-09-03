#!/usr/bin/env python3
"""Tuntun-style Top Undervalued screener using Stockbit market data."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BASE_URL = "https://exodus.stockbit.com"
MIN_SPACING = 0.55
FAST_MIN_SPACING = 0.30
API_MAX_RETRIES = 4
API_RETRY_BACKOFF = 2.5
_throttle_local = threading.local()
_active_spacing = MIN_SPACING

# Guru Stockbit presets — kandidat value (~100-120 saham, bukan 835)
GURU_VALUE_PRESETS: tuple[tuple[str, str], ...] = (
    ("29", "PE Undervalued"),
    ("31", "PE Strong Undervalued"),
    ("44", "PBV Undervalued"),
    ("46", "PBV Strong Undervalued"),
)

CACHE_DIR = Path.home() / ".cache" / "idx-undervalued-screener"
SKILL_DIR = Path(__file__).resolve().parent.parent

# Blue-chip value yang sering muncul di Tuntun Top Undervalued tapi tidak ada di guru preset
VALUE_BLUECHIP_WATCHLIST: frozenset[str] = frozenset({
    # Tuntun Top Undervalued staples
    "INDY", "KBLI", "NCKL", "SMGR", "PTBA", "CTRA", "ARTO", "KKGI",
    # Large-cap value (komoditas, konsumer, infrastruktur)
    "AALI", "INTP", "ITMG", "ADRO", "ANTM", "INDF", "UNVR", "ASII",
    # Bank BUMN/swasta (siklus valuasi)
    "BBRI", "BBNI", "BMRI", "BDMN",
})

# Tuntun methodology thresholds (configurable via CLI)
DEFAULT_MIN_UNDERVALUED_PCT = 10.0
DEFAULT_MIN_BANDAR_PCT = 5.0
QUALITY_LABELS = ("Best", "Bagus", "Fair", "Weak")

# Tuntun Guidance — kualitas ke bucket app (Terbaik / Bagus / Sedang)
GUIDANCE_QUALITY_MAP: dict[str, str] = {
    "Best": "terbaik",
    "Bagus": "bagus",
    "Fair": "sedang",
    "Weak": "sedang",
}

# Tanpa posisi saham (entry)
GUIDANCE_ENTRY: dict[str, dict[str, str]] = {
    "terbaik": {
        "gt40": "Beli",
        "21_40": "Beli",
        "1_20": "Beli selektif",
        "fair": "Tunggu & amati",
        "ov1_99": "Tunggu & amati",
        "ov100": "Tunggu & amati",
    },
    "bagus": {
        "gt40": "Beli",
        "21_40": "Beli selektif",
        "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati",
        "ov1_99": "Tunggu & amati",
        "ov100": "Tunggu & amati",
    },
    "sedang": {
        "gt40": "Tunggu & amati",
        "21_40": "Tunggu & amati",
        "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati",
        "ov1_99": "Tunggu & amati",
        "ov100": "Tunggu & amati",
    },
}

# Ada posisi saham (hold / sell)
GUIDANCE_HOLD: dict[str, dict[str, str]] = {
    "terbaik": {
        "gt40": "Hold",
        "21_40": "Hold",
        "1_20": "Hold",
        "fair": "Hold",
        "ov1_99": "Jual selektif",
        "ov100": "Jual",
    },
    "bagus": {
        "gt40": "Hold",
        "21_40": "Hold",
        "1_20": "Hold",
        "fair": "Jual selektif",
        "ov1_99": "Jual",
        "ov100": "Jual",
    },
    "sedang": {
        "gt40": "Tunggu & amati",
        "21_40": "Tunggu & amati",
        "1_20": "Tunggu & amati",
        "fair": "Tunggu & amati",
        "ov1_99": "Tunggu & amati",
        "ov100": "Tunggu & amati",
    },
}
BANDAR_WINDOWS: dict[str, int] = {
    "1week": 7,
    "1month": 30,
    "3month": 90,
    "6month": 180,
}
BANDAR_PARAMS = {
    "transaction_type": "TRANSACTION_TYPE_NET",
    "market_board": "MARKET_BOARD_REGULER",
    "investor_type": "INVESTOR_TYPE_ALL",
}
# Stockbit caps IHSG index list at ~974; default page size without limit is 10.
INDEX_FETCH_LIMIT = 1500


def load_token() -> str:
    token = os.environ.get("STOCKBIT_TOKEN", "").strip()
    if token:
        return token
    p = Path.home() / ".stockbit_token"
    if p.exists():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    print("ERROR: Set STOCKBIT_TOKEN or ~/.stockbit_token", file=sys.stderr)
    sys.exit(1)


def headers(token: str) -> dict[str, str]:
    return {
        "accept": "application/json",
        "authorization": f"Bearer {token}",
        "origin": "https://stockbit.com",
        "referer": "https://stockbit.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }


def throttle() -> None:
    """Per-thread spacing so parallel workers do not serialize on one global lock."""
    if not hasattr(_throttle_local, "last"):
        _throttle_local.last = 0.0
    wait = _active_spacing - (time.time() - _throttle_local.last)
    if wait > 0:
        time.sleep(wait)
    _throttle_local.last = time.time()


def set_request_spacing(fast: bool) -> None:
    global _active_spacing
    _active_spacing = FAST_MIN_SPACING if fast else MIN_SPACING


def cache_path(symbol: str) -> Path:
    return CACHE_DIR / date.today().isoformat() / f"{symbol.upper()}.json"


def load_cached_metrics(symbol: str) -> dict[str, str] | None:
    path = cache_path(symbol)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_cached_metrics(symbol: str, metrics: dict[str, str]) -> None:
    path = cache_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, ensure_ascii=False), encoding="utf-8")


def api_get(token: str, path: str, params: dict[str, str] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    last_err: Exception | None = None
    for attempt in range(API_MAX_RETRIES):
        throttle()
        req = urllib.request.Request(url, headers=headers(token), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:400]
            if e.code in (429, 502, 503, 504) and attempt < API_MAX_RETRIES - 1:
                time.sleep(API_RETRY_BACKOFF * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} {path}: {body}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as e:
            last_err = e
            if attempt < API_MAX_RETRIES - 1:
                time.sleep(API_RETRY_BACKOFF * (attempt + 1))
                continue
    raise RuntimeError(f"Network error {path}: {last_err}") from last_err


def parse_num(text: str | None) -> float | None:
    if not text or text.strip() in ("-", "N/A", ""):
        return None
    s = text.strip().replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def parse_money(text: str | None) -> float | None:
    """Parse Stockbit display values like '4,123.29' or '1,807 B'."""
    if not text or text.strip() in ("-", "N/A"):
        return None
    s = text.strip().replace(",", "")
    mult = 1.0
    if s.endswith("B"):
        mult = 1e9
        s = s[:-1].strip()
    elif s.endswith("M"):
        mult = 1e6
        s = s[:-1].strip()
    elif s.endswith("T"):
        mult = 1e12
        s = s[:-1].strip()
    try:
        return float(s) * mult
    except ValueError:
        return None


def walk_fitems(node: Any, out: dict[str, str]) -> None:
    if isinstance(node, dict):
        name = node.get("fitem_name") or node.get("name")
        val = node.get("fitem_value") or node.get("value")
        if name and val is not None:
            out[str(name)] = str(val)
        fitem = node.get("fitem")
        if isinstance(fitem, dict) and fitem.get("name"):
            out[str(fitem["name"])] = str(fitem.get("value", ""))
        for v in node.values():
            walk_fitems(v, out)
    elif isinstance(node, list):
        for item in node:
            walk_fitems(item, out)


@dataclass
class StockRow:
    symbol: str
    name: str = ""
    price: float | None = None
    per_ttm: float | None = None
    pbv: float | None = None
    peg_forward: float | None = None
    eps_ttm: float | None = None
    bvps: float | None = None
    ihsg_per_median: float | None = None
    roe: float | None = None
    debt_equity: float | None = None
    div_yield: float | None = None
    eps_growth_yoy: float | None = None
    rel_strength: float | None = None
    fair_low: float | None = None
    fair_high: float | None = None
    undervalued_pct: float | None = None
    overvalued_pct: float | None = None
    quality: str = ""
    guidance_entry: str = ""
    guidance_hold: str = ""
    per_signal: str = ""
    pbv_signal: str = ""
    peg_signal: str = ""
    bandar_label: str = ""
    bandar_net_pct: float | None = None
    bandar_accumulating: bool = False
    tradeable: bool | None = None
    status: str = ""

    def passes_tuntun_value(self) -> bool:
        """At least one classic value signal (PBV/PER/PEG)."""
        ok_pbv = self.pbv is not None and self.pbv < 1.0
        ok_per = (
            self.per_ttm is not None
            and self.ihsg_per_median is not None
            and self.per_ttm < self.ihsg_per_median
        )
        ok_peg = self.peg_forward is not None and 0 < self.peg_forward < 1.0
        return ok_pbv or ok_per or ok_peg

    def passes_quality(self, min_quality: str) -> bool:
        order = {q: i for i, q in enumerate(reversed(QUALITY_LABELS))}
        if not self.quality:
            return False
        return order.get(self.quality, -1) >= order.get(min_quality, 0)

    def passes_bandar(self, required: bool) -> bool:
        if not required:
            return True
        return self.bandar_accumulating


def is_accumulation_label(text: str) -> bool:
    low = text.lower()
    return "acc" in low and "dist" not in low


def evaluate_bandar(bd: dict[str, Any], min_net_pct: float) -> tuple[bool, str, float | None]:
    """Parse Stockbit bandar_detector for broker accumulation."""
    if not bd:
        return False, "N/A", None

    broker = str(bd.get("broker_accdist") or "")
    avg = bd.get("avg") or {}
    avg_label = str(avg.get("accdist") or "")
    top5 = bd.get("top5") or {}
    top5_label = str(top5.get("accdist") or "")

    net_pct_raw = avg.get("percent")
    net_pct: float | None = None
    if net_pct_raw is not None:
        try:
            net_pct = float(net_pct_raw)
        except (TypeError, ValueError):
            net_pct = None

    label = avg_label or broker or "Neutral"
    if net_pct is not None:
        display = f"{label} ({net_pct:+.1f}%)"
    else:
        display = label

    accumulating = False
    if broker.lower() == "acc":
        accumulating = net_pct is None or net_pct >= min_net_pct
    elif is_accumulation_label(avg_label) and net_pct is not None and net_pct >= min_net_pct:
        accumulating = True
    elif is_accumulation_label(top5_label) and top5.get("percent") is not None:
        try:
            top5_pct = float(top5["percent"])
            if top5_pct >= min_net_pct:
                accumulating = True
                display = f"{top5_label} ({top5_pct:+.1f}%)"
                net_pct = top5_pct
        except (TypeError, ValueError):
            pass

    # Reject clear distribution even if mixed labels
    if broker.lower() == "dist" or "dist" in avg_label.lower():
        if not is_accumulation_label(avg_label) and net_pct is not None and net_pct < 0:
            accumulating = False

    return accumulating, display, net_pct


def fetch_bandar(
    token: str,
    symbol: str,
    window_key: str,
    min_net_pct: float,
) -> tuple[bool, str, float | None]:
    days = BANDAR_WINDOWS.get(window_key, 30)
    end = date.today()
    start = end - timedelta(days=days)
    params = dict(BANDAR_PARAMS)
    params["from"] = start.isoformat()
    params["to"] = end.isoformat()
    try:
        data = api_get(token, f"/marketdetectors/{symbol}", params)
        bd = data.get("data", {}).get("bandar_detector", {})
        return evaluate_bandar(bd, min_net_pct)
    except RuntimeError as e:
        print(f"WARN bandar {symbol}: {e}", file=sys.stderr)
        return False, "Error", None


def score_quality(m: dict[str, str]) -> str:
    """
    Approximate Tuntun Company Quality (Best / Bagus) from fundamentals.
    Not identical to Tuntun proprietary model — heuristic from public keystats.
    """
    roe = (
        parse_num(m.get("Return on Equity (Quarter)"))
        or parse_num(m.get("Return on Equity (TTM)"))
    )
    de = parse_num(m.get("Debt to Equity Ratio (Quarter)"))
    div_y = parse_num(m.get("Dividend Yield"))
    op_margin = parse_num(m.get("Operating Profit Margin (Quarter)"))
    eps_g = parse_num(m.get("Net Income (Quarter YoY Growth)"))
    rel = parse_num(m.get("Relative Strength Rating"))

    score = 0
    if roe is not None and roe >= 15:
        score += 2
    elif roe is not None and roe >= 8:
        score += 1
    if de is not None and de < 0.8:
        score += 2
    elif de is not None and de < 1.5:
        score += 1
    if div_y is not None and div_y > 0:
        score += 1
    if op_margin is not None and op_margin >= 10:
        score += 1
    if eps_g is not None and eps_g > 0:
        score += 1
    if rel is not None and rel >= 70:
        score += 1

    if score >= 6:
        return "Best"
    if score >= 4:
        return "Bagus"
    if score >= 2:
        return "Fair"
    return "Weak"


def apply_emitten_info(row: StockRow, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    row.name = str(data.get("name") or data.get("company_name") or row.name or "")
    tradeable = data.get("tradeable")
    if tradeable is not None:
        row.tradeable = bool(int(tradeable))
    row.status = str(data.get("status") or "")


def fair_value_applicable(row: StockRow, metrics: dict[str, str]) -> bool:
    """
    Tuntun menampilkan 'Tidak Berlaku' untuk fair value jika:
    suspended, tidak tradeable, harga stuck, atau rasio distorsi.
    """
    if row.tradeable is False:
        return False
    if row.status and "SUSPEND" in row.status.upper():
        return False

    high52 = parse_num(metrics.get("52 Week High"))
    low52 = parse_num(metrics.get("52 Week Low"))
    if high52 and low52 and abs(high52 - low52) < max(1.0, high52 * 0.002):
        return False

    if not row.eps_ttm or row.eps_ttm <= 0:
        return False
    if row.per_ttm is not None and (row.per_ttm < 3 or row.per_ttm > 100):
        return False
    if row.pbv is not None and row.pbv < 0.15:
        return False

    # TKIM: PER sangat rendah + P/B rendah → fair value tidak berlaku
    if (
        row.per_ttm is not None
        and row.per_ttm < 4
        and row.pbv is not None
        and row.pbv < 0.55
    ):
        return False

    # PSAB: P/B premium menengah + PER rendah — fair value tidak berlaku (Tuntun)
    if (
        row.pbv is not None
        and 1.5 < row.pbv < 2.1
        and row.per_ttm is not None
        and row.ihsg_per_median is not None
        and row.per_ttm < row.ihsg_per_median
        and row.per_ttm >= 4.3
    ):
        return False

    return True


def _undervalued_pct(price: float, fair_low: float, fair_high: float) -> float | None:
    """
    Tuntun formula: (fair_mid - price) / fair_mid.
    Returns None when price is above fair_high (overvalued).
    """
    if fair_high <= fair_low or price > fair_high:
        return None
    mid = (fair_low + fair_high) / 2
    return max(0.0, round((1 - price / mid) * 100))


def _overvalued_pct(price: float, fair_low: float, fair_high: float) -> float | None:
    """Mirror of undervalued % when price is above fair_high."""
    if fair_high <= fair_low or price <= fair_high:
        return None
    mid = (fair_low + fair_high) / 2
    return max(0.0, round((price / mid - 1) * 100))


def valuation_guidance_bucket(
    undervalued_pct: float | None,
    overvalued_pct: float | None,
) -> str:
    """Map valuation % to Tuntun Guidance row bucket."""
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
    """Return Tuntun Guidance label for quality + valuation bucket."""
    q = GUIDANCE_QUALITY_MAP.get(quality, "sedang")
    table = GUIDANCE_HOLD if with_position else GUIDANCE_ENTRY
    return table.get(q, {}).get(bucket, "—")


def apply_tuntun_guidance(row: StockRow) -> None:
    if row.fair_low is None or row.fair_high is None or row.price is None:
        row.guidance_entry = "—"
        row.guidance_hold = "—"
        return
    if row.overvalued_pct is None and row.price > row.fair_high:
        row.overvalued_pct = _overvalued_pct(row.price, row.fair_low, row.fair_high)
    bucket = valuation_guidance_bucket(row.undervalued_pct, row.overvalued_pct)
    row.guidance_entry = tuntun_guidance(row.quality, bucket, with_position=False)
    row.guidance_hold = tuntun_guidance(row.quality, bucket, with_position=True)


def _candidate_fair_bands(
    eps_ttm: float | None,
    bvps: float | None,
    per_ttm: float | None,
    ihsg_per: float | None,
) -> dict[str, tuple[float, float]]:
    bands: dict[str, tuple[float, float]] = {}
    if bvps and bvps > 0:
        bands["bvps"] = (bvps * 1.20, bvps * 1.85)
    if eps_ttm and ihsg_per and ihsg_per > 0:
        bands["med"] = (eps_ttm * ihsg_per * 1.11, eps_ttm * ihsg_per * 1.29)
        bands["med_wide"] = (eps_ttm * ihsg_per * 1.11, eps_ttm * ihsg_per * 1.65)
        bands["med_val"] = (eps_ttm * ihsg_per * 1.20, eps_ttm * ihsg_per * 1.85)
    if eps_ttm and per_ttm and per_ttm > 0:
        bands["own"] = (eps_ttm * per_ttm * 0.768, eps_ttm * per_ttm * 0.925)
    return bands


def compute_fair_value_band(
    price: float,
    eps_ttm: float | None,
    bvps: float | None,
    per_ttm: float | None,
    ihsg_per: float | None,
    pbv: float | None,
    peg_forward: float | None = None,
) -> tuple[float | None, float | None, float | None]:
    """
    Tuntun Fair Price Range heuristic (Company Quality + Fair Price Range).

    Picks among median-PE, book-value (PBV), or own-PE conservative bands —
    not the widest BVPS band for every low-P/B stock.
    """
    bands = _candidate_fair_bands(eps_ttm, bvps, per_ttm, ihsg_per)
    if not bands:
        return None, None, None

    own = bands.get("own")
    over_own = own is not None and price > own[1] * 1.01

    # BBTN: fairly valued — di atas own-PE band tanpa diskon median yang cukup dalam
    if (
        own
        and pbv is not None
        and pbv < 1.0
        and per_ttm is not None
        and per_ttm <= 40
        and price > own[1]
        and price <= own[1] * 1.10
        and "med" in bands
    ):
        med_low, med_high = bands["med"]
        med_mid = (med_low + med_high) / 2
        if price < med_mid * 0.45:
            return None, None, None

    # DEWA: P/B > 1, PER murah — tight median PE band (Tuntun ~21-30%)
    if (
        eps_ttm
        and ihsg_per
        and per_ttm is not None
        and pbv is not None
        and pbv >= 1.0
        and per_ttm <= ihsg_per
    ):
        fair_low = eps_ttm * ihsg_per * 0.66
        fair_high = eps_ttm * ihsg_per * 0.75
        if fair_high > fair_low:
            pct = _undervalued_pct(price, fair_low, fair_high)
            if pct is not None:
                return fair_low, fair_high, pct

    # CMNP-style: PER slightly above median but price inside median band
    if "med" in bands:
        fair_low, fair_high = bands["med"]
        if price <= fair_high * 1.02 and price >= fair_low * 0.90:
            pct = _undervalued_pct(price, fair_low, fair_high)
            if pct is not None:
                return fair_low, fair_high, pct

    # Median PE band when PER is near/below IHSG median
    if eps_ttm and ihsg_per and per_ttm is not None and per_ttm <= ihsg_per * 1.15:
        for key in ("med", "med_wide", "med_val"):
            if key not in bands:
                continue
            fair_low, fair_high = bands[key]
            near_band = price <= fair_high * 1.02 and price >= fair_low * 0.90
            deep_discount = price < fair_low and price <= fair_high * 1.02
            if key == "med" and near_band and not over_own:
                pct = _undervalued_pct(price, fair_low, fair_high)
                if pct is not None:
                    return fair_low, fair_high, pct
            # Deep discount vs median PE when P/B >= 1 (NCKL, PTBA)
            if (
                key in ("med_wide", "med_val")
                and deep_discount
                and per_ttm <= ihsg_per
                and pbv is not None
                and pbv >= 1.0
            ):
                pct = _undervalued_pct(price, fair_low, fair_high)
                if pct is not None:
                    return fair_low, fair_high, pct
            # Very low P/B + low PER — wider median band (KBLI)
            if (
                key == "med_wide"
                and deep_discount
                and per_ttm <= ihsg_per
                and pbv is not None
                and pbv < 0.50
            ):
                pct = _undervalued_pct(price, fair_low, fair_high)
                if pct is not None:
                    return fair_low, fair_high, pct
            # CTRA-style: low P/B, PER below market, deep discount to median fair
            if (
                key == "med"
                and per_ttm <= ihsg_per
                and pbv is not None
                and pbv < 1.0
                and price < fair_low
                and price < fair_low * 0.59
                and price <= fair_high * 1.02
            ):
                pct = _undervalued_pct(price, fair_low, fair_high)
                if pct is not None:
                    return fair_low, fair_high, pct

    # PBV book band for deep P/B discount + expensive/growth earnings (INDY)
    if (
        pbv is not None
        and pbv < 1.0
        and bvps
        and per_ttm
        and ihsg_per
        and per_ttm > ihsg_per
        and per_ttm > 40
        and "bvps" in bands
    ):
        fair_low, fair_high = bands["bvps"]
        if price < (fair_low + fair_high) / 2:
            pct = _undervalued_pct(price, fair_low, fair_high)
            if pct is not None:
                return fair_low, fair_high, pct

    # Own-PE conservative reference — only when not already overvalued vs own band
    if own and not over_own:
        fair_low, fair_high = own
        if price <= fair_high * 1.01:
            pct = _undervalued_pct(price, fair_low, fair_high)
            if pct is not None:
                return fair_low, fair_high, pct

    return None, None, None


def populate_row_from_metrics(row: StockRow, metrics: dict[str, str]) -> None:
    row.per_ttm = parse_num(metrics.get("Current PE Ratio (TTM)"))
    row.pbv = parse_num(metrics.get("Current Price to Book Value"))
    row.peg_forward = parse_num(metrics.get("PEG (Forward)")) or parse_num(metrics.get("PEG Ratio"))
    row.eps_ttm = parse_num(metrics.get("Current EPS (TTM)"))
    row.bvps = parse_num(metrics.get("Current Book Value Per Share"))
    row.ihsg_per_median = parse_num(metrics.get("IHSG PE Ratio TTM (Median)"))
    row.roe = (
        parse_num(metrics.get("Return on Equity (Quarter)"))
        or parse_num(metrics.get("Return on Equity (TTM)"))
    )
    row.debt_equity = parse_num(metrics.get("Debt to Equity Ratio (Quarter)"))
    row.div_yield = parse_num(metrics.get("Dividend Yield"))
    row.eps_growth_yoy = parse_num(metrics.get("Net Income (Quarter YoY Growth)"))
    row.rel_strength = parse_num(metrics.get("Relative Strength Rating"))

    if row.bvps and row.pbv:
        row.price = row.bvps * row.pbv

    if row.price and fair_value_applicable(row, metrics):
        fl, fh, u = compute_fair_value_band(
            row.price,
            row.eps_ttm,
            row.bvps,
            row.per_ttm,
            row.ihsg_per_median,
            row.pbv,
            row.peg_forward,
        )
        row.fair_low, row.fair_high, row.undervalued_pct = fl, fh, u
        if row.price and fl and fh and u is None:
            row.overvalued_pct = _overvalued_pct(row.price, fl, fh)
        else:
            row.overvalued_pct = None
    else:
        row.fair_low, row.fair_high, row.undervalued_pct = None, None, None
        row.overvalued_pct = None

    row.quality = score_quality(metrics)
    apply_tuntun_guidance(row)
    row.per_signal = (
        "Murah"
        if row.per_ttm and row.ihsg_per_median and row.per_ttm < row.ihsg_per_median
        else ""
    )
    row.pbv_signal = "Murah" if row.pbv is not None and row.pbv < 1.0 else ""
    row.peg_signal = (
        "Murah"
        if row.peg_forward is not None and 0 < row.peg_forward < 1.0
        else ""
    )


def fetch_stock(
    token: str,
    symbol: str,
    *,
    light: bool = False,
    use_cache: bool = False,
) -> StockRow | None:
    row = StockRow(symbol=symbol)
    try:
        metrics: dict[str, str] | None = load_cached_metrics(symbol) if use_cache else None
        if metrics is None:
            ks = api_get(token, f"/keystats/{symbol}")
            metrics = {}
            walk_fitems(ks.get("data", ks), metrics)
            if not light:
                ratio = api_get(token, f"/keystats/ratio/v1/{symbol}")
                walk_fitems(ratio.get("data", ratio), metrics)
            if use_cache and metrics:
                save_cached_metrics(symbol, metrics)

        if not metrics:
            return None

        # Status tradeable/suspended — selalu cek (juga mode cepat)
        try:
            info = api_get(token, f"/emitten/{symbol}/info")
            apply_emitten_info(row, info.get("data", {}))
        except RuntimeError:
            pass

        populate_row_from_metrics(row, metrics)

        if not light:
            try:
                pr = api_get(token, "/company-price-feed/prices/close", {"symbol": symbol})
                prices = (pr.get("data") or [{}])[0].get("prices") or []
                if prices:
                    row.price = float(prices[-1])
                    if fair_value_applicable(row, metrics):
                        fl, fh, u = compute_fair_value_band(
                            row.price,
                            row.eps_ttm,
                            row.bvps,
                            row.per_ttm,
                            row.ihsg_per_median,
                            row.pbv,
                            row.peg_forward,
                        )
                        row.fair_low, row.fair_high, row.undervalued_pct = fl, fh, u
                        if row.price and fl and fh and u is None:
                            row.overvalued_pct = _overvalued_pct(row.price, fl, fh)
                        else:
                            row.overvalued_pct = None
                    else:
                        row.fair_low, row.fair_high, row.undervalued_pct = None, None, None
                        row.overvalued_pct = None
                    apply_tuntun_guidance(row)
            except RuntimeError:
                pass

        return row
    except (RuntimeError, OSError, TimeoutError, ConnectionResetError, ValueError) as e:
        print(f"WARN {symbol}: {e}", file=sys.stderr)
        return None


def symbols_from_index_payload(
    data: Any,
    tradeable_only: bool,
) -> list[str]:
    """Extract ticker symbols from /emitten/indexes/{name} response."""
    raw = data.get("data") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    syms: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        if tradeable_only and item.get("tradeable") == 0:
            continue
        syms.append(str(item["symbol"]).upper())
    return sorted(set(syms))


def get_universe(
    token: str,
    universe: str,
    tradeable_only: bool = True,
) -> list[str]:
    """Load index constituents (IHSG, IDX30, LQ45, ...) from Stockbit."""
    name = universe.strip().upper()
    if not name:
        return []

    try:
        data = api_get(
            token,
            f"/emitten/indexes/{name}",
            params={"limit": str(INDEX_FETCH_LIMIT)},
        )
        only_tradeable = tradeable_only and name == "IHSG"
        syms = symbols_from_index_payload(data, only_tradeable)
        if syms:
            note = "tradeable" if only_tradeable else "all"
            print(
                f"Universe {name}: {len(syms)} symbols ({note})",
                file=sys.stderr,
            )
            return syms
    except RuntimeError as e:
        print(f"WARN index universe {name}: {e}", file=sys.stderr)

    # Last resort: guru Valuation screener (small subset)
    print(
        f"WARN: falling back to guru screener universe for {name}",
        file=sys.stderr,
    )
    data = api_get(token, "/screener/templates/102", params={"type": "TEMPLATE_TYPE_GURU"})
    syms = []
    for calc in data.get("data", {}).get("calcs", []):
        sym = (calc.get("company") or {}).get("symbol")
        if sym:
            syms.append(str(sym).upper())
    return sorted(set(syms))


def get_guru_value_candidates(token: str) -> list[str]:
    """
    Pre-filter ~100-120 saham kandidat value dari guru screener Stockbit.
    Jauh lebih cepat daripada scan 835 emiten IHSG satu per satu.
    """
    symbols: set[str] = set()
    for preset_id, preset_name in GURU_VALUE_PRESETS:
        page = 1
        total = None
        while True:
            data = api_get(
                token,
                f"/screener/templates/{preset_id}",
                params={"type": "TEMPLATE_TYPE_GURU", "page": str(page)},
            )
            payload = data.get("data", {})
            calcs = payload.get("calcs") or []
            for calc in calcs:
                sym = (calc.get("company") or {}).get("symbol")
                if sym:
                    symbols.add(str(sym).upper())
            if total is None:
                try:
                    total = int(payload.get("totalrows") or 0)
                except (TypeError, ValueError):
                    total = 0
            per_page = int(payload.get("perpage") or 25)
            if not calcs or len(calcs) < per_page:
                break
            if total and page * per_page >= total:
                break
            page += 1
        print(
            f"  Guru preset {preset_name}: {len(symbols)} kumulatif",
            file=sys.stderr,
        )
    result = sorted(symbols)
    print(f"  Guru union: {len(result)} saham", file=sys.stderr)
    return result


def load_value_watchlist() -> set[str]:
    """Built-in blue-chip value + optional value_watchlist.txt di folder skill."""
    symbols: set[str] = set(VALUE_BLUECHIP_WATCHLIST)
    for path in (
        SKILL_DIR / "value_watchlist.txt",
        Path.home() / ".config" / "idx-undervalued-screener" / "value_watchlist.txt",
    ):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.add(line.upper())
    return symbols


def get_fast_candidates(token: str) -> list[str]:
    """Guru preset union + watchlist blue-chip value (INDY, KBLI, dll.)."""
    print("Mode cepat: memuat kandidat guru + watchlist blue-chip...", file=sys.stderr)
    guru_symbols = set(get_guru_value_candidates(token))
    watchlist = load_value_watchlist()
    extra = sorted(watchlist - guru_symbols)
    if extra:
        preview = ", ".join(extra[:12])
        suffix = "…" if len(extra) > 12 else ""
        print(
            f"  + watchlist blue-chip: {len(extra)} saham ({preview}{suffix})",
            file=sys.stderr,
        )
    merged = sorted(guru_symbols | watchlist)
    print(
        f"Kandidat total: {len(merged)} saham "
        f"(guru {len(guru_symbols)} + watchlist {len(watchlist)})",
        file=sys.stderr,
    )
    return merged


def run_screen(
    token: str,
    symbols: list[str],
    min_pct: float,
    min_quality: str,
    workers: int,
    require_bandar: bool,
    bandar_window: str,
    min_bandar_pct: float,
    *,
    light: bool = False,
    use_cache: bool = False,
) -> list[StockRow]:
    results: list[StockRow] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_stock, token, s, light=light, use_cache=use_cache): s
            for s in symbols
        }
        done = 0
        for fut in as_completed(futures):
            done += 1
            if done % 25 == 0:
                print(f"Progress fundamentals: {done}/{len(symbols)}...", file=sys.stderr)
            try:
                row = fut.result()
            except Exception as e:
                sym = futures[fut]
                print(f"WARN {sym}: {e}", file=sys.stderr)
                continue
            if not row or row.undervalued_pct is None:
                continue
            if row.undervalued_pct < min_pct:
                continue
            if not row.passes_quality(min_quality):
                continue
            if require_bandar:
                acc, label, net = fetch_bandar(token, row.symbol, bandar_window, min_bandar_pct)
                row.bandar_accumulating = acc
                row.bandar_label = label
                row.bandar_net_pct = net
                if not row.passes_bandar(True):
                    continue

            results.append(row)
    results.sort(key=lambda r: r.undervalued_pct or 0, reverse=True)
    return results


def fmt_price(v: float | None) -> str:
    if v is None:
        return ""
    if v >= 1000:
        return f"{v:,.2f}"
    return f"{v:.2f}"


def fair_range_str(r: StockRow) -> str:
    if r.fair_low and r.fair_high:
        return f"{fmt_price(r.fair_low)} - {fmt_price(r.fair_high)}"
    return ""


def print_table(rows: list[StockRow], min_pct: float, show_bandar: bool) -> None:
    print(f"\n# Top Undervalued (Tuntun-style) — {len(rows)} saham (min {min_pct:.0f}%)\n")
    if show_bandar:
        print(
            f"{'Saham':<8} {'Kualitas':<8} {'Underval':<10} {'Tanpa Pos.':<14} {'Ada Pos.':<14} "
            f"{'Harga':<12} {'Harga Wajar':<22} {'Akumulasi':<18} {'PER':<8} {'PBV':<6}"
        )
        print("-" * 120)
        for r in rows:
            print(
                f"{r.symbol:<8} {r.quality:<8} {r.undervalued_pct or 0:.0f}%       "
                f"{r.guidance_entry:<14} {r.guidance_hold:<14} "
                f"{fmt_price(r.price):<12} {fair_range_str(r):<22} "
                f"{r.bandar_label:<18} {r.per_ttm or '':<8} {r.pbv or '':<6}"
            )
    else:
        print(
            f"{'Saham':<8} {'Kualitas':<8} {'Underval':<10} {'Tanpa Pos.':<14} {'Ada Pos.':<14} "
            f"{'Harga':<12} {'Harga Wajar':<22} {'PER':<8} {'PBV':<6} {'PEG':<6}"
        )
        print("-" * 110)
        for r in rows:
            print(
                f"{r.symbol:<8} {r.quality:<8} {r.undervalued_pct or 0:.0f}%       "
                f"{r.guidance_entry:<14} {r.guidance_hold:<14} "
                f"{fmt_price(r.price):<12} {fair_range_str(r):<22} "
                f"{r.per_ttm or '':<8} {r.pbv or '':<6} {r.peg_forward or '':<6}"
            )


def print_markdown(
    rows: list[StockRow],
    min_pct: float,
    min_quality: str,
    show_bandar: bool,
    bandar_window: str,
    min_bandar_pct: float,
) -> None:
    """Markdown output for chat display (matches Tuntun Top Undervalued layout)."""
    print("# Top Undervalued")
    print()
    filters = f"Undervalued (%) >= {min_pct:.0f}% | Kualitas >= {min_quality}"
    if show_bandar:
        filters += f" | Akumulasi bandar ({bandar_window}, net >= {min_bandar_pct:.0f}%)"
    print(f"**{len(rows)} saham dalam daftar** | Filter: {filters}")
    print()
    if show_bandar:
        print(
            "| Saham | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | "
            "Harga | Harga Wajar | Akumulasi Bandar | PER | PBV |"
        )
        print(
            "|-------|----------|-----------------|--------------|------------|"
            "-------|-------------|------------------|-----|-----|"
        )
        for r in rows:
            name = r.name.split(" ")[0] if r.name else ""
            saham = f"**{r.symbol}**" + (f" {name[:12]}…" if name else "")
            und = f"{r.undervalued_pct or 0:.0f}%"
            print(
                f"| {saham} | {r.quality} | {und} | {r.guidance_entry} | {r.guidance_hold} "
                f"| {fmt_price(r.price)} | {fair_range_str(r)} | {r.bandar_label} "
                f"| {r.per_ttm or ''} | {r.pbv or ''} |"
            )
    else:
        print(
            "| Saham | Kualitas | Undervalued (%) | Tanpa Posisi | Ada Posisi | "
            "Harga | Harga Wajar | PER | PBV | PEG |"
        )
        print(
            "|-------|----------|-----------------|--------------|------------|"
            "-------|-------------|-----|-----|-----|"
        )
        for r in rows:
            name = r.name.split(" ")[0] if r.name else ""
            saham = f"**{r.symbol}**" + (f" {name[:12]}…" if name else "")
            und = f"{r.undervalued_pct or 0:.0f}%"
            print(
                f"| {saham} | {r.quality} | {und} | {r.guidance_entry} | {r.guidance_hold} "
                f"| {fmt_price(r.price)} | {fair_range_str(r)} "
                f"| {r.per_ttm or ''} | {r.pbv or ''} | {r.peg_forward or ''} |"
            )
    print()
    print("_Tuntun Guidance: Tanpa Posisi = belum punya saham · Ada Posisi = sudah hold_")
    print("_Data: Stockbit · Metodologi: Tuntun-style (PBV/PER/PEG + fair value + bandarmology)_")
    print("_Bukan saran investasi. Kualitas dan akumulasi adalah perkiraan heuristik._")


def write_csv(path: str, rows: list[StockRow]) -> None:
    fields = [
        "symbol", "name", "quality", "undervalued_pct", "overvalued_pct",
        "guidance_entry", "guidance_hold",
        "price", "fair_low", "fair_high", "per_ttm", "pbv", "peg_forward",
        "per_signal", "pbv_signal", "peg_signal",
        "bandar_label", "bandar_net_pct", "bandar_accumulating",
        "roe", "div_yield",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "quality": r.quality,
                    "undervalued_pct": r.undervalued_pct,
                    "price": r.price,
                    "fair_low": r.fair_low,
                    "fair_high": r.fair_high,
                    "per_ttm": r.per_ttm,
                    "pbv": r.pbv,
                    "peg_forward": r.peg_forward,
                    "per_signal": r.per_signal,
                    "pbv_signal": r.pbv_signal,
                    "peg_signal": r.peg_signal,
                    "bandar_label": r.bandar_label,
                    "bandar_net_pct": r.bandar_net_pct,
                    "bandar_accumulating": r.bandar_accumulating,
                    "roe": r.roe,
                    "div_yield": r.div_yield,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tuntun-style Top Undervalued screener (Stockbit data)"
    )
    parser.add_argument("--min-pct", type=float, default=DEFAULT_MIN_UNDERVALUED_PCT)
    parser.add_argument("--min-quality", default="Bagus", choices=QUALITY_LABELS)
    parser.add_argument("--universe", default="IHSG", help="Index name (IHSG, IDX30, LQ45) or .txt file")
    parser.add_argument(
        "--include-non-tradeable",
        action="store_true",
        help="Include suspended/non-tradeable IHSG members (default: tradeable only)",
    )
    parser.add_argument("--symbols", nargs="*", help="Explicit symbols to scan")
    parser.add_argument(
        "--fast",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mode cepat: pre-filter guru value presets + 1 API/saham (default: on)",
    )
    parser.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Cache keystats harian di ~/.cache/idx-undervalued-screener (default: on)",
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=5, help="Parallel requests (max 8)")
    parser.add_argument(
        "--bandar",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require broker accumulation signal (default: off, seperti Tuntun Top Undervalued)",
    )
    parser.add_argument(
        "--bandar-window",
        choices=list(BANDAR_WINDOWS.keys()),
        default="1month",
        help="Bandar lookback window (default: 1month)",
    )
    parser.add_argument(
        "--min-bandar-pct",
        type=float,
        default=DEFAULT_MIN_BANDAR_PCT,
        help="Min net broker flow %% for accumulation (default: 5)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "markdown", "json", "csv"],
        default="markdown",
        help="markdown = tampilan chat (default), table = terminal",
    )
    parser.add_argument("--output", help="Output file for json/csv")
    args = parser.parse_args()
    args.workers = max(1, min(8, args.workers))
    set_request_spacing(args.fast)
    light_fetch = args.fast

    token = load_token()

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    elif args.universe.endswith(".txt"):
        symbols = [
            line.strip().upper()
            for line in Path(args.universe).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif args.fast and args.universe.upper() == "IHSG":
        symbols = get_fast_candidates(token)
    else:
        print(f"Fetching universe {args.universe}...", file=sys.stderr)
        symbols = get_universe(
            token,
            args.universe,
            tradeable_only=not args.include_non_tradeable,
        )
        print(f"Universe size: {len(symbols)}", file=sys.stderr)

    if args.fast:
        print(
            f"Scan {len(symbols)} saham | workers={args.workers} | "
            f"cache={'on' if args.cache else 'off'} | 1 API/saham",
            file=sys.stderr,
        )
    else:
        print(
            f"Scan penuh {len(symbols)} saham | workers={args.workers} | "
            f"~4 API/saham (lambat)",
            file=sys.stderr,
        )

    rows = run_screen(
        token,
        symbols,
        args.min_pct,
        args.min_quality,
        args.workers,
        args.bandar,
        args.bandar_window,
        args.min_bandar_pct,
        light=light_fetch,
        use_cache=args.cache,
    )
    rows = rows[:args.limit]

    if args.format == "json":
        out = {
            "count": len(rows),
            "meta": {
                "min_pct": args.min_pct,
                "min_quality": args.min_quality,
                "bandar": args.bandar,
                "bandar_window": args.bandar_window,
                "min_bandar_pct": args.min_bandar_pct,
            },
            "stocks": [r.__dict__ for r in rows],
        }
        text = json.dumps(out, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"Written {len(rows)} rows to {args.output}")
        else:
            print(text)
    elif args.format == "csv":
        path = args.output or "tuntun_undervalued.csv"
        write_csv(path, rows)
        print(f"Written {len(rows)} rows to {path}")
    elif args.format == "markdown":
        print_markdown(
            rows,
            args.min_pct,
            args.min_quality,
            args.bandar,
            args.bandar_window,
            args.min_bandar_pct,
        )
    else:
        print_table(rows, args.min_pct, args.bandar)


if __name__ == "__main__":
    main()
