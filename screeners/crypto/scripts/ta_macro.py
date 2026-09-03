"""TA confirmation (RSI, S/R) and BTC dominance / macro filter."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from crypto_undervalued_screener import CryptoRow

CACHE_DIR = Path.home() / ".cache" / "crypto-undervalued-screener"
FNG_URL = "https://api.alternative.me/fng/?limit=1"
USER_AGENT = "crypto-undervalued-screener/1.0"

BTC_DOM_HIGH = 58.0
BTC_DOM_MID = 52.0
NEAR_SUPPORT_PCT = 5.0
NEAR_RESIST_PCT = 4.0
RSI_OVERSOLD = 35.0
RSI_OVERBOUGHT = 70.0
RSI_EXTREME = 75.0


@dataclass
class MacroSnapshot:
    btc_dominance: float | None = None
    btc_dominance_zone: str = "—"
    mcap_chg_24h_pct: float | None = None
    btc_chg_7d_pct: float | None = None
    alt_chg_7d_pct: float | None = None
    regime: str = "Neutral"
    fear_greed: int | None = None
    fear_greed_label: str = "—"
    warnings: list[str] = field(default_factory=list)

    def is_btc_season(self) -> bool:
        return self.regime == "BTC season"

    def is_risk_off(self) -> bool:
        if self.mcap_chg_24h_pct is not None and self.mcap_chg_24h_pct <= -5:
            return True
        if self.fear_greed is not None and self.fear_greed <= 20:
            return True
        return self.is_btc_season() and (self.btc_dominance or 0) >= BTC_DOM_HIGH


def rsi_wilder(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def swing_levels(prices: list[float], window: int = 14) -> tuple[float | None, float | None]:
    if not prices:
        return None, None
    look = prices[-window:] if len(prices) >= window else prices
    return min(look), max(look)


def _local_extrema(values: list[float], k: int = 2, find_min: bool = True) -> list[float]:
    out: list[float] = []
    if len(values) < k * 2 + 1:
        return out
    for i in range(k, len(values) - k):
        window = values[i - k : i + k + 1]
        if find_min and values[i] <= min(window):
            out.append(values[i])
        elif not find_min and values[i] >= max(window):
            out.append(values[i])
    return out


def chart_support_resistance(
    closes: list[float],
    ohlc: list[list[float]] | None = None,
    price: float | None = None,
) -> tuple[float | None, float | None]:
    """Nearest swing support below price / resistance above price.

    OHLC bars: [timestamp, open, high, low, close] from CoinGecko.
    """
    lows: list[float]
    highs: list[float]
    if ohlc and len(ohlc) >= 5:
        highs = [float(b[2]) for b in ohlc if len(b) >= 5]
        lows = [float(b[3]) for b in ohlc if len(b) >= 5]
    else:
        highs = closes
        lows = closes

    troughs = _local_extrema(lows, k=2, find_min=True)
    peaks = _local_extrema(highs, k=2, find_min=False)
    win_low, win_high = swing_levels(lows if lows else closes, 14)
    if win_low:
        troughs.append(win_low)
    if win_high:
        peaks.append(win_high)

    px = price or (closes[-1] if closes else None)
    support = None
    resist = None
    if px:
        below = [v for v in troughs if v <= px * 1.002]
        above = [v for v in peaks if v >= px * 0.998]
        support = max(below) if below else win_low
        resist = min(above) if above else win_high
    else:
        support, resist = win_low, win_high
    return support, resist


def dist_pct(price: float, level: float | None) -> float | None:
    if level is None or price <= 0:
        return None
    return round((price - level) / price * 100, 2)


def ta_signal(
    rsi: float | None,
    dist_support_pct: float | None,
    dist_resist_pct: float | None,
) -> str:
    """Entry OK hanya jika RSI oversold DAN harga dekat support, bukan resistance."""
    overbought = rsi is not None and rsi >= RSI_OVERBOUGHT
    extreme = rsi is not None and rsi >= RSI_EXTREME
    oversold = rsi is not None and rsi <= RSI_OVERSOLD
    near_sup = dist_support_pct is not None and 0 <= dist_support_pct <= NEAR_SUPPORT_PCT
    far_above = dist_support_pct is not None and dist_support_pct > 12
    near_res = dist_resist_pct is not None and 0 <= dist_resist_pct <= NEAR_RESIST_PCT

    if extreme or (overbought and near_res):
        return "Hindari"
    if near_res and (rsi is None or rsi >= 60):
        return "Hindari"
    if overbought or far_above:
        return "Tunggu"
    if oversold and near_sup and not near_res:
        return "Entry OK"
    if near_sup and (rsi is None or rsi < RSI_OVERBOUGHT) and not near_res:
        return "Selektif"
    if oversold and not near_res:
        return "Selektif"
    return "Tunggu"


def ta_score_multiplier(signal: str) -> float:
    return {
        "Entry OK": 1.25,
        "Selektif": 1.0,
        "Tunggu": 0.55,
        "Hindari": 0.2,
    }.get(signal, 0.7)


def apply_ta(
    row: CryptoRow,
    prices: list[float] | None,
    ohlc: list[list[float]] | None = None,
) -> None:
    price = row.price
    if not price or not prices:
        row.rsi_14 = None
        row.support = None
        row.resistance = None
        row.dist_support_pct = None
        row.dist_resist_pct = None
        row.ta_signal = "—"
        return

    support, resistance = chart_support_resistance(prices, ohlc=ohlc, price=price)
    row.rsi_14 = rsi_wilder(prices)
    row.support = round(support, 8) if support else None
    row.resistance = round(resistance, 8) if resistance else None
    row.dist_support_pct = dist_pct(price, support)
    if resistance and price > 0:
        row.dist_resist_pct = round((resistance - price) / price * 100, 2)
    else:
        row.dist_resist_pct = None
    row.ta_signal = ta_signal(row.rsi_14, row.dist_support_pct, row.dist_resist_pct)

    if row.ta_signal == "Hindari":
        row.risk_warnings.append("TA: RSI overbought / dekat resistance")
    elif row.ta_signal == "Tunggu" and (row.rsi_14 or 0) >= RSI_OVERBOUGHT:
        row.risk_warnings.append("TA: RSI overbought — tunggu pullback")
    elif row.dist_support_pct and row.dist_support_pct > 12:
        row.risk_warnings.append("TA: harga jauh dari support — entry kurang ideal")
    elif row.ta_signal == "Entry OK":
        row.risk_warnings.append("TA konfirmasi: RSI oversold + dekat support")

    row.risk_adjusted_score = round(
        (row.risk_adjusted_score or 0) * ta_score_multiplier(row.ta_signal), 1
    )


def _fng_cache_path() -> Path:
    return CACHE_DIR / date.today().isoformat() / "fear_greed.json"


def fetch_fear_greed() -> tuple[int | None, str]:
    path = _fng_cache_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return int(data["value"]), str(data["label"])
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
            pass
    try:
        req = urllib.request.Request(
            FNG_URL,
            headers={"User-Agent": USER_AGENT, "accept": "application/json"},
        )
        raw = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        row = (raw.get("data") or [{}])[0]
        value = int(row.get("value", 0))
        label = str(row.get("value_classification") or "—")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"value": value, "label": label}), encoding="utf-8")
        return value, label
    except Exception:
        return None, "—"


def fetch_macro(cg_get: Callable[[str, dict[str, str] | None], Any]) -> MacroSnapshot:
    snap = MacroSnapshot()
    cache = CACHE_DIR / date.today().isoformat() / "global.json"
    data: dict[str, Any] = {}
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    if not data:
        payload = cg_get("/global", None)
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")

    pct = data.get("market_cap_percentage") or {}
    snap.btc_dominance = round(float(pct.get("btc") or 0), 2) if pct.get("btc") is not None else None
    chg = data.get("market_cap_change_percentage_24h_usd")
    snap.mcap_chg_24h_pct = round(float(chg), 2) if chg is not None else None

    if snap.btc_dominance is None:
        snap.btc_dominance_zone = "—"
    elif snap.btc_dominance >= BTC_DOM_HIGH:
        snap.btc_dominance_zone = "Tinggi (alt underperform risk)"
    elif snap.btc_dominance >= BTC_DOM_MID:
        snap.btc_dominance_zone = "Sedang"
    else:
        snap.btc_dominance_zone = "Rendah (alt season bias)"

    snap.fear_greed, snap.fear_greed_label = fetch_fear_greed()
    try:
        btc_m = cg_get(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "ids": "bitcoin",
                "sparkline": "false",
                "price_change_percentage": "7d",
            },
        )
        if isinstance(btc_m, list) and btc_m:
            chg7 = btc_m[0].get("price_change_percentage_7d_in_currency")
            if chg7 is not None:
                snap.btc_chg_7d_pct = round(float(chg7), 2)
    except Exception:
        pass
    return snap


def complete_macro(snap: MacroSnapshot, rows: list[CryptoRow]) -> MacroSnapshot:
    btc = next((r for r in rows if r.coin_id == "bitcoin" or r.symbol == "BTC"), None)
    if btc and btc.change_7d_pct is not None:
        snap.btc_chg_7d_pct = round(float(btc.change_7d_pct), 2)
    alts = [
        r.change_7d_pct for r in rows
        if r.coin_id != "bitcoin" and r.symbol != "BTC" and r.change_7d_pct is not None
    ]
    if alts:
        alts_sorted = sorted(alts)
        snap.alt_chg_7d_pct = round(alts_sorted[len(alts_sorted) // 2], 2)

    btc7 = snap.btc_chg_7d_pct
    alt7 = snap.alt_chg_7d_pct
    dom = snap.btc_dominance or 0
    if btc7 is not None and alt7 is not None:
        if dom >= BTC_DOM_MID and btc7 > alt7 + 2:
            snap.regime = "BTC season"
        elif alt7 > btc7 + 3 and dom < BTC_DOM_HIGH:
            snap.regime = "Alt season"
        else:
            snap.regime = "Neutral"
    elif dom >= BTC_DOM_HIGH:
        snap.regime = "BTC season"

    if snap.is_btc_season():
        snap.warnings.append(
            f"BTC.D {snap.btc_dominance}% · regime BTC season — altcoin high-beta lebih berisiko"
        )
    if snap.mcap_chg_24h_pct is not None and snap.mcap_chg_24h_pct <= -3:
        snap.warnings.append(f"Total market cap 24j {snap.mcap_chg_24h_pct:+.1f}% — risk-off")
    if snap.fear_greed is not None and snap.fear_greed <= 25:
        snap.warnings.append(f"Fear & Greed {snap.fear_greed} ({snap.fear_greed_label})")
    if snap.fear_greed is not None and snap.fear_greed >= 75:
        snap.warnings.append(f"Greed ekstrem {snap.fear_greed} — FOMO risk")
    return snap


def passes_macro_filter(row: CryptoRow, snap: MacroSnapshot) -> bool:
    """Hard filter during BTC season / risk-off. BTC itself always passes."""
    if row.coin_id == "bitcoin" or row.symbol == "BTC":
        return True
    if not snap.is_risk_off() and not snap.is_btc_season():
        return True
    rank = row.market_cap_rank or 999
    sector = getattr(row, "sector", "") or ""
    if sector == "Meme":
        return False
    if snap.is_btc_season() and rank > 50 and row.quality != "Best":
        return False
    if snap.is_risk_off() and rank > 30 and row.quality != "Best":
        return False
    return True


def apply_macro_penalty(row: CryptoRow, snap: MacroSnapshot) -> None:
    if row.coin_id == "bitcoin" or row.symbol == "BTC":
        return
    if snap.is_btc_season() and (row.market_cap_rank or 999) > 30:
        row.risk_adjusted_score = round((row.risk_adjusted_score or 0) * 0.6, 1)
        row.risk_warnings.append("Macro: BTC season — ukuran posisi diperkecil")
    elif snap.is_risk_off() and (row.market_cap_rank or 999) > 20:
        row.risk_adjusted_score = round((row.risk_adjusted_score or 0) * 0.7, 1)
        row.risk_warnings.append("Macro: risk-off market")


def print_macro_header(snap: MacroSnapshot | None) -> None:
    if not snap:
        return
    print("## Kondisi Makro")
    print()
    print(
        f"**BTC.D:** {snap.btc_dominance if snap.btc_dominance is not None else '—'}% "
        f"({snap.btc_dominance_zone}) · **Regime:** {snap.regime}  "
    )
    btc7 = f"{snap.btc_chg_7d_pct:+.1f}%" if snap.btc_chg_7d_pct is not None else "—"
    alt7 = f"{snap.alt_chg_7d_pct:+.1f}%" if snap.alt_chg_7d_pct is not None else "—"
    mcap = f"{snap.mcap_chg_24h_pct:+.1f}%" if snap.mcap_chg_24h_pct is not None else "—"
    print(
        f"**BTC 7d:** {btc7} · **Alt median 7d:** {alt7} · "
        f"**MCap 24j:** {mcap} · **Fear & Greed:** {snap.fear_greed or '—'} ({snap.fear_greed_label})"
    )
    print()
    if snap.warnings:
        for w in snap.warnings:
            print(f"- {w}")
        print()
