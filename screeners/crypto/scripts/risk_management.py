"""Risk management module for crypto undervalued screener."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from crypto_undervalued_screener import CryptoRow

# Sector mapping for correlation warnings
SECTOR_MAP: dict[str, str] = {
    "bitcoin": "L1", "ethereum": "L1", "solana": "L1", "cardano": "L1",
    "avalanche-2": "L1", "polkadot": "L1", "near": "L1", "aptos": "L1",
    "sui": "L1", "cosmos": "L1", "the-open-network": "L1", "tron": "L1",
    "bitcoin-cash": "L1", "litecoin": "L1", "hedera-hashgraph": "L1",
    "algorand": "L1", "internet-computer": "L1", "ethereum-classic": "L1",
    "uniswap": "DeFi", "aave": "DeFi", "maker": "DeFi", "curve-dao-token": "DeFi",
    "lido-dao": "DeFi", "chainlink": "Oracle", "compound-governance-token": "DeFi",
    "render-token": "AI", "fetch-ai": "AI", "pepe": "Meme", "dogecoin": "Meme",
    "shiba-inu": "Meme", "arbitrum": "L2", "optimism": "L2", "polygon-ecosystem-token": "L2",
}

QUALITY_WEIGHT = {"Best": 1.0, "Bagus": 0.85, "Fair": 0.65, "Weak": 0.4}
RISK_GRADE_SIZE = {"A": 5.0, "B": 3.0, "C": 2.0, "D": 1.0}
MAX_SINGLE_POSITION = 5.0
MAX_PORTFOLIO_CRYPTO = 80.0  # max % of total portfolio in crypto


@dataclass
class RiskProfile:
    risk_grade: str = "D"
    risk_score: int = 100  # 0=aman, 100=berisiko tinggi
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
    sector: str = "Other"
    warnings: list[str] = field(default_factory=list)


def classify_sector(coin_id: str) -> str:
    return SECTOR_MAP.get(coin_id, "Other")


def compute_atr_pct(prices: list[float], period: int = 14) -> float | None:
    """ATR as percentage of last price."""
    if len(prices) < period + 1:
        return None
    trs: list[float] = []
    for i in range(-period, 0):
        high = prices[i]
        low = prices[i]
        prev = prices[i - 1]
        tr = max(high - low, abs(high - prev), abs(low - prev))
        trs.append(tr)
    atr = sum(trs) / len(trs)
    last = prices[-1]
    if last <= 0:
        return None
    return round(atr / last * 100, 2)


def compute_support(prices: list[float], days: int = 14) -> float | None:
    if len(prices) < days:
        return None
    return min(prices[-days:])


def detect_value_trap(row: CryptoRow) -> tuple[bool, list[str]]:
    """Flag coins that look cheap but are likely value traps."""
    warnings: list[str] = []
    trap = False

    ath_dd = row.ath_drawdown_pct or 0
    underval = row.undervalued_pct or 0
    rank = row.market_cap_rank or 9999
    vol_ratio = (row.volume_mcap_ratio or 0) * 100
    fdv = row.fdv_mcap_ratio or 1
    chg30 = row.change_30d_pct or 0
    mvrv = row.mvrv_proxy

    # Extreme ATH discount without MVRV confirmation = likely dead/dying
    if ath_dd >= 95 and underval >= 80:
        if mvrv is None or mvrv > 1.1:
            trap = True
            warnings.append("Value trap: ATH DD ekstrem tanpa konfirmasi MVRV")

    # Illiquid
    if vol_ratio < 1.0 and rank > 50:
        trap = True
        warnings.append(f"Likuiditas rendah ({vol_ratio:.1f}% vol/MCap)")

    # Heavy unlock / inflated FDV
    if fdv > 3.0:
        trap = True
        warnings.append(f"FDV/MCap tinggi ({fdv:.1f}x) — risiko unlock")

    # Falling knife
    if chg30 < -30 and (row.change_7d_pct or 0) < 0:
        warnings.append("Falling knife: turun >30% dalam 30 hari")

    # Meme without quality
    sector = classify_sector(row.coin_id)
    if sector == "Meme" and row.quality not in ("Best", "Bagus"):
        trap = True
        warnings.append("Meme coin tanpa kualitas memadai")

    # Over-hyped undervalued on ATH band alone
    if underval >= 90 and rank > 80 and (mvrv is None or mvrv >= 1.0):
        trap = True
        warnings.append("Undervalued ekstrem hanya dari ATH band")

    return trap, warnings


def compute_risk_score(row: CryptoRow, atr_pct: float | None, is_trap: bool) -> int:
    """0 = safest, 100 = riskiest."""
    score = 0
    rank = row.market_cap_rank or 9999

    if rank > 200:
        score += 25
    elif rank > 100:
        score += 15
    elif rank > 50:
        score += 8

    if atr_pct:
        if atr_pct > 15:
            score += 25
        elif atr_pct > 8:
            score += 15
        elif atr_pct > 5:
            score += 8

    ath_dd = row.ath_drawdown_pct or 0
    if ath_dd > 90:
        score += 20
    elif ath_dd > 70:
        score += 10

    fdv = row.fdv_mcap_ratio or 1
    if fdv > 2.5:
        score += 15
    elif fdv > 1.8:
        score += 8

    vol_ratio = (row.volume_mcap_ratio or 0) * 100
    if vol_ratio < 2:
        score += 15
    elif vol_ratio < 3:
        score += 5

    if row.quality == "Weak":
        score += 20
    elif row.quality == "Fair":
        score += 10

    if is_trap:
        score += 25

    if row.whale_label.startswith("Distribusi"):
        score += 15

    return min(100, score)


def assign_risk_grade(row: CryptoRow, risk_score: int, rr: float | None, is_trap: bool) -> str:
    if is_trap or (rr is not None and rr < 1.0):
        return "D"
    rank = row.market_cap_rank or 9999
    if (
        risk_score <= 30
        and rank <= 50
        and row.quality in ("Best", "Bagus")
        and (rr is None or rr >= 2.0)
    ):
        return "A"
    if risk_score <= 50 and rank <= 100 and (rr is None or rr >= 1.5):
        return "B"
    if risk_score <= 70 and (rr is None or rr >= 1.2):
        return "C"
    return "D"


def compute_stop_take_profit(
    row: CryptoRow,
    atr_pct: float | None,
    support: float | None,
) -> tuple[float | None, float | None]:
    price = row.price
    if not price or price <= 0:
        return None, None

    # Stop loss: tighter of ATR-based or support-based
    sl_atr = price * (1 - (atr_pct or 8) / 100 * 2)  # 2x ATR
    sl_support = support * 0.98 if support else sl_atr
    stop_loss = min(sl_atr, sl_support) if support else sl_atr
    stop_loss = max(stop_loss, price * 0.70)  # max 30% SL for crypto

    # Take profit: realistic target, not full ATH recovery
    if row.fair_low and row.fair_high and row.fair_low > price:
        fair_mid = (row.fair_low + row.fair_high) / 2
        # If fair value implies >3x move, cap TP at 2x entry or fair_low
        if fair_mid > price * 3:
            take_profit = min(row.fair_low, price * 2.0)
        else:
            take_profit = fair_mid
    elif row.fair_low and row.fair_low > price:
        take_profit = min(row.fair_low, price * 1.5)
    else:
        take_profit = price * 1.25

    return round(stop_loss, 8), round(take_profit, 8)


def compute_risk_reward(price: float, sl: float | None, tp: float | None) -> float | None:
    if not sl or not tp or price <= sl:
        return None
    risk = price - sl
    reward = tp - price
    if risk <= 0:
        return None
    return round(reward / risk, 2)


def compute_position_size(grade: str, risk_score: int, max_position: float) -> float:
    base = RISK_GRADE_SIZE.get(grade, 1.0)
    # Reduce size as risk increases
    adj = base * (1 - risk_score / 200)
    return round(min(max_position, max(0.5, adj)), 1)


def compute_risk_adjusted_score(
    row: CryptoRow,
    risk_score: int,
    is_trap: bool,
    rr: float | None = None,
) -> float:
    if is_trap:
        return 0.0
    underval = row.undervalued_pct or 0
    q_weight = QUALITY_WEIGHT.get(row.quality, 0.5)
    rr_bonus = min((rr or 1.5) / 2, 1.5)
    safety = (100 - risk_score) / 100
    return round(underval * q_weight * safety * rr_bonus, 1)


def apply_risk_profile(
    row: CryptoRow,
    prices: list[float] | None,
    *,
    portfolio_usd: float = 10_000,
    max_position_pct: float = MAX_SINGLE_POSITION,
    min_rr: float = 1.5,
) -> RiskProfile:
    profile = RiskProfile()
    profile.sector = classify_sector(row.coin_id)

    atr_pct = compute_atr_pct(prices) if prices else None
    support = compute_support(prices) if prices else None
    profile.volatility_14d_pct = atr_pct

    is_trap, trap_warnings = detect_value_trap(row)
    profile.is_value_trap = is_trap
    profile.warnings = trap_warnings

    profile.risk_score = compute_risk_score(row, atr_pct, is_trap)

    sl, tp = compute_stop_take_profit(row, atr_pct, support)
    profile.stop_loss = sl
    profile.take_profit = tp
    profile.risk_reward = compute_risk_reward(row.price or 0, sl, tp)

    if row.price and sl:
        profile.max_loss_pct = round((row.price - sl) / row.price * 100, 1)

    profile.risk_grade = assign_risk_grade(row, profile.risk_score, profile.risk_reward, is_trap)
    profile.position_size_pct = compute_position_size(
        profile.risk_grade, profile.risk_score, max_position_pct,
    )
    profile.position_size_usd = round(portfolio_usd * profile.position_size_pct / 100, 0)

    # Pass criteria
    profile.passes_risk = (
        not is_trap
        and profile.risk_grade in ("A", "B", "C")
        and (profile.risk_reward is None or profile.risk_reward >= min_rr)
        and profile.risk_score <= 70
    )

    # Extra warnings
    if profile.risk_reward and profile.risk_reward < min_rr:
        profile.warnings.append(f"R:R rendah ({profile.risk_reward:.1f} < {min_rr})")
    if profile.max_loss_pct and profile.max_loss_pct > 20:
        profile.warnings.append(f"Max loss tinggi ({profile.max_loss_pct:.0f}%)")
    if atr_pct and atr_pct > 12:
        profile.warnings.append(f"Volatilitas tinggi (ATR {atr_pct:.1f}%)")

    profile.risk_adjusted_score = compute_risk_adjusted_score(
        row, profile.risk_score, is_trap, profile.risk_reward,
    )
    return profile


def apply_risk_to_row(
    row: CryptoRow,
    prices: list[float] | None,
    **kwargs: Any,
) -> None:
    profile = apply_risk_profile(row, prices, **kwargs)
    row.risk_grade = profile.risk_grade
    row.risk_score = profile.risk_score
    row.volatility_14d_pct = profile.volatility_14d_pct
    row.stop_loss = profile.stop_loss
    row.take_profit = profile.take_profit
    row.risk_reward = profile.risk_reward
    row.max_loss_pct = profile.max_loss_pct
    row.position_size_pct = profile.position_size_pct
    row.position_size_usd = profile.position_size_usd
    row.is_value_trap = profile.is_value_trap
    row.passes_risk = profile.passes_risk
    row.risk_adjusted_score = profile.risk_adjusted_score
    row.sector = profile.sector
    row.risk_warnings = profile.warnings


def portfolio_correlation_warnings(rows: list[CryptoRow]) -> list[str]:
    """Warn if portfolio is too concentrated in one sector."""
    warnings: list[str] = []
    sectors: dict[str, int] = {}
    for r in rows:
        if getattr(r, "passes_risk", False) or not getattr(r, "is_value_trap", True):
            sec = getattr(r, "sector", "Other")
            sectors[sec] = sectors.get(sec, 0) + 1

    for sec, count in sectors.items():
        if count >= 4:
            warnings.append(f"Konsentrasi tinggi: {count} coin di sektor {sec}")
        if sec == "Meme" and count >= 2:
            warnings.append(f"Terlalu banyak meme coin ({count})")

    return warnings


def suggest_portfolio_allocation(
    rows: list[CryptoRow],
    portfolio_usd: float,
    max_total_pct: float = MAX_PORTFOLIO_CRYPTO,
) -> list[dict[str, Any]]:
    """Equal-risk-ish allocation from top safe picks."""
    eligible = [
        r for r in rows
        if getattr(r, "passes_risk", False) and not getattr(r, "is_value_trap", True)
    ]
    eligible.sort(key=lambda r: getattr(r, "risk_adjusted_score", 0), reverse=True)
    eligible = eligible[:5]

    if not eligible:
        return []

    total_pct = sum(getattr(r, "position_size_pct", 0) for r in eligible)
    scale = min(1.0, max_total_pct / total_pct) if total_pct > 0 else 1.0

    out: list[dict[str, Any]] = []
    for r in eligible:
        pct = getattr(r, "position_size_pct", 0) * scale
        out.append({
            "symbol": r.symbol,
            "risk_grade": getattr(r, "risk_grade", "?"),
            "allocation_pct": round(pct, 1),
            "allocation_usd": round(portfolio_usd * pct / 100, 0),
            "stop_loss": getattr(r, "stop_loss", None),
            "take_profit": getattr(r, "take_profit", None),
            "risk_reward": getattr(r, "risk_reward", None),
            "max_loss_pct": getattr(r, "max_loss_pct", None),
        })
    return out
