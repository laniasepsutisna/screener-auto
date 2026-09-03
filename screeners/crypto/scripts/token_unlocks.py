"""Token unlock calendar — Tokenomist / DefiLlama Pro / Cryptorank / local seed."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path.home() / ".cache" / "crypto-undervalued-screener"
USER_AGENT = "crypto-undervalued-screener/1.0"

# Warn if unlock within this window and size is material
UNLOCK_WATCH_DAYS = 14
UNLOCK_HIGH_PCT = 1.0  # % of circulating / mcap
UNLOCK_MED_PCT = 0.4


@dataclass
class UnlockEvent:
    coin_id: str
    symbol: str
    unlock_date: date
    tokens: float | None = None
    pct_circ: float | None = None
    pct_mcap: float | None = None
    pct_supply: float | None = None
    note: str = ""
    source: str = "seed"

    @property
    def days_until(self) -> int:
        return (self.unlock_date - date.today()).days

    @property
    def impact_pct(self) -> float:
        for v in (self.pct_circ, self.pct_mcap, self.pct_supply):
            if v is not None:
                return float(v)
        return 0.0


def _http_json(url: str, headers: dict[str, str], timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers={**headers, "User-Agent": USER_AGENT, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_secret(env_name: str, filename: str) -> str:
    val = os.environ.get(env_name, "").strip()
    if val:
        return val
    path = Path.home() / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return ""


def load_seed_calendar() -> list[UnlockEvent]:
    path = SKILL_DIR / "data" / "unlocks_calendar.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    events: list[UnlockEvent] = []
    for row in raw.get("events") or []:
        try:
            d = datetime.strptime(str(row["date"])[:10], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        events.append(
            UnlockEvent(
                coin_id=str(row.get("coin_id") or "").lower(),
                symbol=str(row.get("symbol") or "").upper(),
                unlock_date=d,
                tokens=float(row["tokens"]) if row.get("tokens") is not None else None,
                pct_circ=float(row["pct_circ"]) if row.get("pct_circ") is not None else None,
                pct_mcap=float(row["pct_mcap"]) if row.get("pct_mcap") is not None else None,
                pct_supply=float(row["pct_supply"]) if row.get("pct_supply") is not None else None,
                note=str(row.get("note") or ""),
                source=str(raw.get("source") or "seed"),
            )
        )
    return events


def fetch_tokenomist_upcoming() -> list[UnlockEvent]:
    key = _load_secret("TOKENOMIST_API_KEY", ".tokenomist_key")
    if not key:
        return []
    cache = CACHE_DIR / date.today().isoformat() / "tokenomist_upcoming.json"
    if cache.exists():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = None
    else:
        payload = None
    if payload is None:
        start = date.today().isoformat()
        end = (date.today() + timedelta(days=45)).isoformat()
        url = (
            "https://api.tokenomist.ai/v5/unlock/events/upcoming"
            f"?start={start}&end={end}&minMarketCap=50000000"
        )
        payload = _http_json(url, {"x-api-key": key})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload), encoding="utf-8")
    events: list[UnlockEvent] = []
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and not rows:
        rows = payload.get("result") or payload.get("events")
    if not isinstance(rows, list):
        return events
    for row in rows:
        if not isinstance(row, dict):
            continue
        upcoming = row.get("upcomingEvent") or row
        date_s = (
            (upcoming.get("unlockDate") if isinstance(upcoming, dict) else None)
            or row.get("unlockDate")
            or row.get("date")
        )
        if not date_s:
            continue
        try:
            d = datetime.fromisoformat(str(date_s).replace("Z", "+00:00")).date()
        except ValueError:
            try:
                d = datetime.strptime(str(date_s)[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
        gecko = str(row.get("geckoId") or row.get("gecko_id") or row.get("id") or "").lower()
        symbol = str(row.get("symbol") or row.get("tokenSymbol") or "").upper()
        cliff = upcoming.get("cliffUnlocks") if isinstance(upcoming, dict) else None
        pct = None
        tokens = None
        if isinstance(cliff, dict):
            pct = cliff.get("unlockPercentage") or cliff.get("percentOfCirculating")
            tokens = cliff.get("amount") or cliff.get("tokens")
        events.append(
            UnlockEvent(
                coin_id=gecko,
                symbol=symbol,
                unlock_date=d,
                tokens=float(tokens) if tokens is not None else None,
                pct_circ=float(pct) if pct is not None else None,
                note="Tokenomist",
                source="tokenomist",
            )
        )
    return events


def fetch_llama_emissions() -> list[UnlockEvent]:
    key = _load_secret("DEFILLAMA_PRO_API_KEY", ".defillama_pro")
    if not key:
        return []
    cache = CACHE_DIR / date.today().isoformat() / "llama_emissions.json"
    if cache.exists():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = None
    else:
        payload = None
    if payload is None:
        url = f"https://pro-api.llama.fi/{key}/api/emissions"
        payload = _http_json(url, {})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload), encoding="utf-8")
    rows = payload if isinstance(payload, list) else (payload.get("data") if isinstance(payload, dict) else [])
    events: list[UnlockEvent] = []
    if not isinstance(rows, list):
        return events
    for row in rows:
        if not isinstance(row, dict):
            continue
        gecko = str(row.get("gecko_id") or "").lower()
        nxt = row.get("nextEvent") or {}
        if not isinstance(nxt, dict):
            continue
        ts = nxt.get("date") or nxt.get("timestamp") or nxt.get("time")
        if ts is None:
            continue
        try:
            if isinstance(ts, (int, float)):
                d = datetime.fromtimestamp(
                    ts / 1000 if ts > 10_000_000_000 else ts, tz=timezone.utc
                ).date()
            else:
                d = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        except (ValueError, OSError, OverflowError):
            continue
        events.append(
            UnlockEvent(
                coin_id=gecko,
                symbol=str(row.get("symbol") or row.get("name") or "").upper(),
                unlock_date=d,
                pct_circ=float(nxt["percentage"]) if nxt.get("percentage") is not None else None,
                note="DefiLlama",
                source="defillama",
            )
        )
    return events


def _index_events(events: list[UnlockEvent]) -> dict[str, UnlockEvent]:
    """Next upcoming (or today) event per coin_id / symbol."""
    best: dict[str, UnlockEvent] = {}
    for ev in events:
        if ev.days_until < 0:
            continue
        keys = [k for k in (ev.coin_id, ev.symbol.lower()) if k]
        for key in keys:
            cur = best.get(key)
            if cur is None or ev.unlock_date < cur.unlock_date or (
                ev.unlock_date == cur.unlock_date and ev.impact_pct > cur.impact_pct
            ):
                best[key] = ev
    return best


def load_unlock_index() -> tuple[dict[str, UnlockEvent], str]:
    """Prefer live API, fall back to seed JSON."""
    sources: list[tuple[str, list[UnlockEvent]]] = []
    for name, fn in (
        ("tokenomist", fetch_tokenomist_upcoming),
        ("defillama", fetch_llama_emissions),
    ):
        try:
            rows = fn()
            if rows:
                sources.append((name, rows))
        except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            continue
    seed = load_seed_calendar()
    if seed:
        sources.append(("seed", seed))
    merged: list[UnlockEvent] = []
    used = "none"
    for name, rows in sources:
        merged.extend(rows)
        used = name if used == "none" else f"{used}+{name}"
    return _index_events(merged), used


def unlock_risk_label(ev: UnlockEvent | None, *, circulating_pct: float | None, fdv_ratio: float | None) -> tuple[str, str]:
    """Return (label, note). Aman / Waspada / Tinggi / —."""
    if ev is not None and 0 <= ev.days_until <= UNLOCK_WATCH_DAYS:
        pct = ev.impact_pct
        if ev.days_until <= 7 and pct >= UNLOCK_HIGH_PCT:
            return "Tinggi", f"{ev.unlock_date.isoformat()} · {pct:.1f}% · {ev.days_until}h"
        if ev.days_until <= UNLOCK_WATCH_DAYS and pct >= UNLOCK_MED_PCT:
            return "Waspada", f"{ev.unlock_date.isoformat()} · {pct:.1f}% · {ev.days_until}h"
        if ev.days_until <= UNLOCK_WATCH_DAYS:
            return "Waspada", f"{ev.unlock_date.isoformat()} · {ev.days_until}h"
    if ev is not None and ev.days_until > UNLOCK_WATCH_DAYS:
        return "Aman", f"next {ev.unlock_date.isoformat()} ({ev.days_until}h)"
    # Proxy when calendar miss
    if circulating_pct is not None and circulating_pct < 45 and (fdv_ratio or 1) >= 1.4:
        return "Waspada", f"float {circulating_pct:.0f}% · FDV {fdv_ratio:.1f}x (kalender tidak ketemu)"
    return "—", ""


def apply_unlock(row: Any, index: dict[str, UnlockEvent]) -> None:
    ev = index.get(row.coin_id) or index.get((row.symbol or "").lower())
    label, note = unlock_risk_label(
        ev,
        circulating_pct=row.circulating_pct,
        fdv_ratio=row.fdv_mcap_ratio,
    )
    row.unlock_date = ev.unlock_date.isoformat() if ev else ""
    row.unlock_days = ev.days_until if ev else None
    row.unlock_pct = round(ev.impact_pct, 2) if ev else None
    row.unlock_risk = label
    row.unlock_note = note or (ev.note if ev else "")
    if label == "Tinggi":
        row.risk_warnings.append(f"Unlock: {note}")
        row.risk_adjusted_score = round((row.risk_adjusted_score or 0) * 0.35, 1)
        row.ta_signal = "Hindari" if getattr(row, "ta_signal", "") == "Entry OK" else row.ta_signal
    elif label == "Waspada":
        row.risk_warnings.append(f"Unlock: {note}")
        row.risk_adjusted_score = round((row.risk_adjusted_score or 0) * 0.7, 1)
