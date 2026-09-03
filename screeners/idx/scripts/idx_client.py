#!/usr/bin/env python3
"""IDX official-site client (idx.co.id/primary) for QC enrichment."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CACHE_ROOT = Path.home() / ".cache" / "idx-undervalued-screener" / "idx"
BASE_URL = "https://www.idx.co.id/primary"

CA_TYPES = [
    "BuybackSaham",
    "PrivatePlacement",
    "stockSplit",
    "reverseStock",
    "hmetd",
    "tanpaHmetd",
    "dividenSaham",
    "sahamBonus",
    "waran",
    "gabungUsaha",
    "kurangModal",
    "konversiSaham",
]

DILUTIVE_TYPES = {
    "PrivatePlacement",
    "hmetd",
    "HMETD",
    "tanpaHmetd",
    "TanpaHMETD",
    "waran",
    "Waran",
    "sahamBonus",
    "SahamBonus",
    "dividenSaham",
    "DividenSaham",
}

CA_LABEL = {
    "BuybackSaham": "Buyback",
    "PrivatePlacement": "Private placement",
    "stockSplit": "Stock split",
    "reverseStock": "Reverse split",
    "hmetd": "Rights issue (HMETD)",
    "tanpaHmetd": "Non-rights issue",
    "dividenSaham": "Dividen saham",
    "sahamBonus": "Saham bonus",
    "waran": "Waran",
    "gabungUsaha": "Merger",
    "kurangModal": "Pengurangan modal",
    "konversiSaham": "Konversi saham",
}

SECTOR_INDEX = {
    "energy": "IDXENERGY",
    "energi": "IDXENERGY",
    "thermal coal": "IDXENERGY",
    "batu bara": "IDXENERGY",
    "minyak": "IDXENERGY",
    "financial services": "IDXFINANCE",
    "keuangan": "IDXFINANCE",
    "banks": "IDXFINANCE",
    "bank": "IDXFINANCE",
    "basic materials": "IDXBASIC",
    "bahan baku": "IDXBASIC",
    "paper": "IDXBASIC",
    "building materials": "IDXBASIC",
    "gold": "IDXBASIC",
    "real estate": "IDXPROPERTY",
    "properti": "IDXPROPERTY",
    "consumer defensive": "IDXNONCYC",
    "consumer cyclical": "IDXCYCLIC",
    "barang konsumen": "IDXNONCYC",
    "industrials": "IDXINDUSTRIAL",
    "industri": "IDXINDUSTRIAL",
    "technology": "IDXTECHNO",
    "teknologi": "IDXTECHNO",
    "healthcare": "IDXHEALTH",
    "kesehatan": "IDXHEALTH",
    "infrastructure": "IDXINFRA",
    "infrastruktur": "IDXINFRA",
    "transportation": "IDXTRANS",
}

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "origin": "https://www.idx.co.id",
    "referer": "https://www.idx.co.id/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}


def _cache_file(name: str) -> Path:
    path = CACHE_ROOT / date.today().isoformat() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_json_cache(name: str) -> Any | None:
    path = _cache_file(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_json_cache(name: str, data: Any) -> None:
    _cache_file(name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _get_json_curl(url: str, params: dict[str, Any], timeout: int = 30) -> Any:
    from curl_cffi import requests as cf_requests

    resp = cf_requests.get(
        url,
        params=params,
        headers=HEADERS,
        impersonate="chrome",
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} {url}")
    return resp.json()


def _get_json_urllib(url: str, params: dict[str, Any], timeout: int = 30) -> Any:
    qs = urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{qs}" if qs else url
    req = Request(full, headers=HEADERS, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def idx_get(endpoint: str, params: dict[str, Any] | None = None, *, retries: int = 3) -> Any:
    url = endpoint if endpoint.startswith("http") else f"{BASE_URL}{endpoint}"
    params = params or {}
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            try:
                return _get_json_curl(url, params)
            except ImportError:
                return _get_json_urllib(url, params)
        except Exception as exc:
            last_err = exc
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"IDX request failed {endpoint}: {last_err}") from last_err


def _parse_dt(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _pct(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if abs(num) <= 1.5:
        return num * 100
    return num


def latest_trading_day(max_lookback: int = 10) -> date:
    cached = load_json_cache("trading_day.json")
    if cached and cached.get("date"):
        parsed = _parse_dt(cached["date"])
        if parsed:
            return parsed
    today = date.today()
    for i in range(max_lookback):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            payload = idx_get(
                "/TradingSummary/GetIndexSummary",
                {"date": d.strftime("%Y%m%d"), "start": 0, "length": 50},
            )
            rows = payload.get("data") or []
            if rows:
                save_json_cache("trading_day.json", {"date": d.isoformat()})
                save_json_cache(f"index_{d.isoformat()}.json", payload)
                return d
        except Exception:
            continue
    return today


def fetch_index_map(as_of: date | None = None) -> dict[str, dict[str, Any]]:
    as_of = as_of or latest_trading_day()
    name = f"index_{as_of.isoformat()}.json"
    payload = load_json_cache(name)
    if not payload:
        payload = idx_get(
            "/TradingSummary/GetIndexSummary",
            {"date": as_of.strftime("%Y%m%d"), "start": 0, "length": 9999},
        )
        save_json_cache(name, payload)
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("data") or []:
        code = str(row.get("IndexCode") or row.get("indexCode") or "").upper()
        if code:
            out[code] = row
    return out


def sector_index_code(sector: str | None, industry: str | None = None) -> str | None:
    blob = f"{sector or ''} {industry or ''}".lower()
    for key, code in SECTOR_INDEX.items():
        if key in blob:
            return code
    return None


def index_return(code: str, days: int = 28) -> float | None:
    latest = latest_trading_day()
    latest_map = fetch_index_map(latest)
    if code not in latest_map:
        return None
    for offset in (days, days + 2, days - 2, 30, 35):
        cand = latest - timedelta(days=max(offset, 20))
        if cand.weekday() >= 5:
            cand -= timedelta(days=cand.weekday() - 4)
        try:
            past_map = fetch_index_map(cand)
        except Exception:
            continue
        if code not in past_map:
            continue
        try:
            now_px = float(latest_map[code].get("Close") or latest_map[code].get("close"))
            then_px = float(past_map[code].get("Close") or past_map[code].get("close"))
            if then_px:
                return (now_px / then_px - 1) * 100
        except (TypeError, ValueError, KeyError):
            continue
    return None


def fetch_corporate_actions(months: int = 12) -> list[dict[str, Any]]:
    cached = load_json_cache("corporate_actions.json")
    if isinstance(cached, list):
        return cached
    rows: list[dict[str, Any]] = []
    for ca_type in CA_TYPES:
        try:
            payload = idx_get(
                "/ListingActivity/GetIssuedHistory",
                {
                    "caType": ca_type,
                    "start": 0,
                    "length": 9999,
                },
            )
            for item in payload.get("data") or []:
                item = dict(item)
                item["_type"] = ca_type
                rows.append(item)
            time.sleep(0.25)
        except Exception:
            continue
    save_json_cache("corporate_actions.json", rows)
    return rows


def actions_for_symbol(symbol: str, months: int = 12) -> list[dict[str, Any]]:
    cutoff = date.today() - timedelta(days=months * 31)
    out = []
    for item in fetch_corporate_actions(months=months):
        kode = str(item.get("KodeEmiten") or item.get("kodeEmiten") or "").strip().upper()
        if kode != symbol.upper():
            continue
        dt = _parse_dt(item.get("TanggalPencatatan") or item.get("date"))
        if dt and dt < cutoff:
            continue
        ca_type = item.get("JenisTindakan") or item.get("_type") or ""
        out.append(
            {
                "type": ca_type,
                "label": CA_LABEL.get(str(ca_type), str(ca_type)),
                "date": dt.isoformat() if dt else None,
                "dilutive": str(ca_type) in DILUTIVE_TYPES,
                "shares": item.get("JumlahSaham"),
            }
        )
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out


def fetch_announcements(symbol: str, months: int = 12) -> list[dict[str, Any]]:
    name = f"ann_{symbol.upper()}.json"
    cached = load_json_cache(name)
    if isinstance(cached, list):
        return cached
    payload = idx_get(
        "/NewsAnnouncement/GetAllAnnouncement",
        {
            "keywords": symbol.upper(),
            "pageNumber": 1,
            "pageSize": 50,
            "lang": "id",
        },
    )
    items = payload.get("Items") or payload.get("items") or []
    rows = []
    for item in items:
        code = str(item.get("Code") or "").strip().upper()
        if code and code != symbol.upper():
            continue
        dt = _parse_dt(item.get("PublishDate"))
        if dt and dt < date.today() - timedelta(days=months * 31):
            continue
        title = str(item.get("Title") or "")
        atts = item.get("Attachments") or []
        pdf = None
        if atts:
            pdf = atts[0].get("FullSavePath") or atts[0].get("PDFFilename")
        rows.append(
            {
                "title": title,
                "date": str(item.get("PublishDate") or "")[:10],
                "kind": classify_announcement(title),
                "pdf": pdf,
            }
        )
    save_json_cache(name, rows)
    return rows


def classify_announcement(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("laporan keuangan", "financial statement", "lk ", "lkq", "lk t")):
        return "laporan_keuangan"
    if "rups" in t or "pemegang saham" in t and "undangan" in t:
        return "rups"
    if any(k in t for k in ("hmetd", "rights", "waran", "private placement")):
        return "dilusi"
    if "buyback" in t or "pembelian kembali" in t:
        return "buyback"
    if any(k in t for k in ("direksi", "komisaris", "pengurus")):
        return "governance"
    if "dividen" in t:
        return "dividen"
    return "lainnya"


def fetch_company_profile(symbol: str) -> dict[str, Any]:
    name = f"profile_{symbol.upper()}.json"
    cached = load_json_cache(name)
    if isinstance(cached, dict) and cached:
        return cached
    payload = idx_get(
        "/ListedCompany/GetCompanyProfilesDetail",
        {"KodeEmiten": symbol.upper(), "language": "id-id"},
    )
    save_json_cache(name, payload if isinstance(payload, dict) else {})
    return payload if isinstance(payload, dict) else {}


def summarize_profile(payload: dict[str, Any]) -> dict[str, Any]:
    profiles = payload.get("Profiles") or payload.get("profiles") or []
    profile = profiles[0] if profiles else {}
    directors = payload.get("Direktur") or payload.get("direktur") or []
    commissioners = payload.get("Komisaris") or payload.get("komisaris") or []
    holders = payload.get("PemegangSaham") or payload.get("pemegangSaham") or []

    def _name(row: dict[str, Any]) -> str:
        return str(row.get("Nama") or row.get("Name") or row.get("nama") or "").strip()

    def _jabatan(row: dict[str, Any]) -> str:
        return str(row.get("Jabatan") or row.get("jabatan") or "").strip()

    independent = [
        _name(r)
        for r in commissioners
        if r.get("Independen") is True
        or r.get("independen") is True
        or "independen" in _jabatan(r).lower()
        or "independent" in _jabatan(r).lower()
    ]
    top_holders = []
    for row in holders[:5]:
        pct = row.get("Persentase") or row.get("persentase") or row.get("Jumlah")
        try:
            pct_f = float(str(pct).replace("%", "").replace(",", "."))
        except (TypeError, ValueError):
            pct_f = None
        top_holders.append(
            {
                "name": str(row.get("Nama") or row.get("name") or "").strip(),
                "pct": pct_f,
            }
        )
    return {
        "name": profile.get("NamaEmiten") or profile.get("namaEmiten"),
        "sector": profile.get("Sektor") or profile.get("sektor"),
        "subsector": profile.get("SubSektor") or profile.get("subSektor"),
        "board": profile.get("PapanPencatatan") or profile.get("papanPencatatan"),
        "directors_n": len(directors),
        "commissioners_n": len(commissioners),
        "independent_n": len(independent),
        "independent_names": independent[:4],
        "top_holders": top_holders,
        "top_holder_pct": top_holders[0]["pct"] if top_holders else None,
        "website": profile.get("Website") or profile.get("website"),
    }


def fetch_financial_ratio_map(year: int | None = None) -> dict[str, dict[str, Any]]:
    year = year or date.today().year - 1
    name = f"ratios_{year}.json"
    cached = load_json_cache(name)
    if isinstance(cached, dict) and cached:
        return cached
    mapping: dict[str, dict[str, Any]] = {}
    for page in range(1, 12):
        payload = idx_get(
            "/DigitalStatistic/GetApiDataPaginated",
            {
                "urlName": "LINK_FINANCIAL_DATA_RATIO",
                "periodQuarter": 4,
                "periodYear": year,
                "type": "yearly",
                "pageSize": 100,
                "pageNumber": page,
            },
        )
        rows = payload.get("data") or payload.get("Data") or payload.get("items") or []
        if not rows:
            break
        for row in rows:
            kode = str(
                row.get("code")
                or row.get("Code")
                or row.get("KodeEmiten")
                or row.get("kodeEmiten")
                or ""
            ).strip().upper()
            if kode:
                mapping[kode] = row
        if len(rows) < 100:
            break
        time.sleep(0.2)
    if not mapping and year > 2020:
        return fetch_financial_ratio_map(year - 1)
    save_json_cache(name, mapping)
    return mapping


def financials_for_symbol(symbol: str) -> dict[str, Any] | None:
    mapping = fetch_financial_ratio_map()
    row = mapping.get(symbol.upper())
    if not row:
        mapping = fetch_financial_ratio_map(date.today().year - 2)
        row = mapping.get(symbol.upper())
    if not row:
        return None
    return {
        "year": row.get("periodYear")
        or str(row.get("fsDate") or "")[:4]
        or row.get("tahun"),
        "per": _safe_float(row.get("per") or row.get("PER")),
        "pbv": _safe_float(row.get("priceBV") or row.get("pbv") or row.get("PBV")),
        "roe": _pct(row.get("roe") or row.get("ROE")),
        "roa": _pct(row.get("roa") or row.get("ROA")),
        "der": _safe_float(row.get("deRatio") or row.get("der") or row.get("DER")),
        "npm": _pct(row.get("npm") or row.get("NPM")),
        "eps": _safe_float(row.get("eps") or row.get("EPS")),
        "sales": _safe_float(row.get("sales") or row.get("Sales")),
        "equity": _safe_float(row.get("equity") or row.get("Equity")),
        "assets": _safe_float(row.get("assets") or row.get("Assets")),
        "audit": row.get("audit") or row.get("opini"),
        "sector": row.get("sector") or row.get("industry"),
    }


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def enrich_idx(
    symbol: str,
    *,
    sector: str | None = None,
    industry: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    if not use_cache:
        # per-symbol caches still used for the day unless caller clears CACHE_ROOT
        pass
    error = None
    profile_sum: dict[str, Any] = {}
    actions: list[dict[str, Any]] = []
    anns: list[dict[str, Any]] = []
    fin: dict[str, Any] | None = None
    sector_code = sector_index_code(sector, industry)
    sector_ret = None
    ihsg_ret = None
    try:
        profile_sum = summarize_profile(fetch_company_profile(symbol))
        if not sector_code:
            sector_code = sector_index_code(profile_sum.get("sector"))
    except Exception as exc:
        error = f"profile: {exc}"
    try:
        actions = actions_for_symbol(symbol)
    except Exception as exc:
        error = (error + "; " if error else "") + f"ca: {exc}"
    try:
        anns = fetch_announcements(symbol)
    except Exception as exc:
        error = (error + "; " if error else "") + f"ann: {exc}"
    try:
        fin = financials_for_symbol(symbol)
    except Exception as exc:
        error = (error + "; " if error else "") + f"fin: {exc}"
    try:
        if sector_code:
            sector_ret = index_return(sector_code)
        ihsg_ret = index_return("COMPOSITE") or index_return("IHSG")
    except Exception as exc:
        error = (error + "; " if error else "") + f"index: {exc}"

    lk = [a for a in anns if a.get("kind") == "laporan_keuangan"]
    rups = [a for a in anns if a.get("kind") == "rups"]
    dilutive = [a for a in actions if a.get("dilutive")]
    buyback = [a for a in actions if str(a.get("type") or "").lower() in ("buybacksaham", "buyback")]
    return {
        "symbol": symbol.upper(),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "error": error,
        "profile": profile_sum,
        "corporate_actions": actions[:8],
        "dilutive_n": len(dilutive),
        "buyback_n": len(buyback),
        "announcements": anns[:10],
        "financial_report_n": len(lk),
        "latest_financial_report": lk[0] if lk else None,
        "rups_n": len(rups),
        "latest_rups": rups[0] if rups else None,
        "financials": fin,
        "sector_index": sector_code,
        "sector_return_1m_pct": sector_ret,
        "ihsg_index_return_1m_pct": ihsg_ret,
    }
