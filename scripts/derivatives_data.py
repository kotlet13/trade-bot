#!/usr/bin/env python3
from __future__ import annotations

import json
import csv
import io
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


FAPI_BASE_URL = "https://fapi.binance.com"
DATA_VISION_BASE_URL = "https://data.binance.vision"
FUNDING_LIMIT = 1000
OPEN_INTEREST_LIMIT = 500


@dataclass(frozen=True)
class FundingRate:
    symbol: str
    funding_time: int
    funding_rate: float
    mark_price: float


@dataclass(frozen=True)
class OpenInterestStat:
    symbol: str
    timestamp: int
    sum_open_interest: float
    sum_open_interest_value: float


@dataclass(frozen=True)
class FuturesMetric:
    symbol: str
    timestamp: int
    sum_open_interest: float
    sum_open_interest_value: float
    count_toptrader_long_short_ratio: float
    sum_toptrader_long_short_ratio: float
    count_long_short_ratio: float
    sum_taker_long_short_vol_ratio: float


def json_get(path: str, query: dict[str, str | int], timeout: int = 20) -> Any:
    url = f"{FAPI_BASE_URL}{path}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def funding_cache_path(cache_dir: Path, symbol: str, start_time: int, end_time: int) -> Path:
    return cache_dir / f"{symbol}_funding_{start_time}_{end_time}.json"


def open_interest_cache_path(cache_dir: Path, symbol: str, period: str, limit: int) -> Path:
    return cache_dir / f"{symbol}_open_interest_{period}_{limit}.json"


def metrics_cache_path(cache_dir: Path, symbol: str, day: date) -> Path:
    return cache_dir / "metrics" / f"{symbol}_metrics_{day.isoformat()}.json"


def metrics_url(symbol: str, day: date) -> str:
    day_string = day.isoformat()
    return (
        f"{DATA_VISION_BASE_URL}/data/futures/um/daily/metrics/"
        f"{symbol}/{symbol}-metrics-{day_string}.zip"
    )


def day_from_ms(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp / 1000, tz=UTC).date()


def parse_create_time_ms(value: str) -> int:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return float(text)


def funding_from_json(item: dict[str, Any]) -> FundingRate:
    funding_time = item.get("fundingTime", item.get("funding_time"))
    funding_rate = item.get("fundingRate", item.get("funding_rate"))
    mark_price = item.get("markPrice", item.get("mark_price", 0.0))
    return FundingRate(
        symbol=str(item["symbol"]),
        funding_time=int(funding_time),
        funding_rate=float(funding_rate),
        mark_price=float(mark_price or 0.0),
    )


def open_interest_from_json(item: dict[str, Any]) -> OpenInterestStat:
    sum_open_interest = item.get("sumOpenInterest", item.get("sum_open_interest"))
    sum_open_interest_value = item.get("sumOpenInterestValue", item.get("sum_open_interest_value"))
    return OpenInterestStat(
        symbol=str(item["symbol"]),
        timestamp=int(item["timestamp"]),
        sum_open_interest=float(sum_open_interest),
        sum_open_interest_value=float(sum_open_interest_value),
    )


def futures_metric_from_json(item: dict[str, Any]) -> FuturesMetric:
    timestamp = item.get("timestamp")
    if timestamp is None:
        timestamp = parse_create_time_ms(str(item["create_time"]))
    return FuturesMetric(
        symbol=str(item["symbol"]),
        timestamp=int(timestamp),
        sum_open_interest=parse_float(item.get("sum_open_interest")),
        sum_open_interest_value=parse_float(item.get("sum_open_interest_value")),
        count_toptrader_long_short_ratio=parse_float(item.get("count_toptrader_long_short_ratio")),
        sum_toptrader_long_short_ratio=parse_float(item.get("sum_toptrader_long_short_ratio")),
        count_long_short_ratio=parse_float(item.get("count_long_short_ratio")),
        sum_taker_long_short_vol_ratio=parse_float(item.get("sum_taker_long_short_vol_ratio")),
    )


def read_funding_cache(path: Path) -> list[FundingRate] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = [funding_from_json(item) for item in payload.get("funding", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    rows.sort(key=lambda item: item.funding_time)
    return rows


def read_open_interest_cache(path: Path) -> list[OpenInterestStat] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = [open_interest_from_json(item) for item in payload.get("open_interest", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    rows.sort(key=lambda item: item.timestamp)
    return rows


def read_metrics_cache(path: Path) -> list[FuturesMetric] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = [futures_metric_from_json(item) for item in payload.get("metrics", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    rows.sort(key=lambda item: item.timestamp)
    return rows


def fetch_funding_rates(
    symbol: str,
    start_time: int,
    end_time: int,
    cache_dir: Path,
    refresh_cache: bool = False,
) -> list[FundingRate]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = funding_cache_path(cache_dir, symbol, start_time, end_time)
    if not refresh_cache:
        cached = read_funding_cache(path)
        if cached is not None:
            return cached

    rows: list[FundingRate] = []
    cursor = start_time
    while cursor <= end_time:
        payload = json_get(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_time,
                "limit": FUNDING_LIMIT,
            },
        )
        if not isinstance(payload, list) or not payload:
            break
        parsed = [funding_from_json(item) for item in payload]
        rows.extend(parsed)
        next_cursor = parsed[-1].funding_time + 1
        if next_cursor <= cursor or len(parsed) < FUNDING_LIMIT:
            break
        cursor = next_cursor
        time.sleep(0.05)

    deduped = {row.funding_time: row for row in rows}
    ordered = [deduped[key] for key in sorted(deduped)]
    payload = {
        "symbol": symbol,
        "start_time": start_time,
        "end_time": end_time,
        "fetched_at": int(time.time() * 1000),
        "funding": [asdict(row) for row in ordered],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return ordered


def fetch_open_interest_hist(
    symbol: str,
    period: str,
    cache_dir: Path,
    limit: int = OPEN_INTEREST_LIMIT,
    refresh_cache: bool = False,
) -> list[OpenInterestStat]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    bounded_limit = max(1, min(limit, OPEN_INTEREST_LIMIT))
    path = open_interest_cache_path(cache_dir, symbol, period, bounded_limit)
    if not refresh_cache:
        cached = read_open_interest_cache(path)
        if cached is not None:
            return cached

    payload = json_get(
        "/futures/data/openInterestHist",
        {
            "symbol": symbol,
            "period": period,
            "limit": bounded_limit,
        },
    )
    rows = [open_interest_from_json(item) for item in payload] if isinstance(payload, list) else []
    rows.sort(key=lambda item: item.timestamp)
    cache_payload = {
        "symbol": symbol,
        "period": period,
        "limit": bounded_limit,
        "fetched_at": int(time.time() * 1000),
        "open_interest": [asdict(row) for row in rows],
    }
    path.write_text(json.dumps(cache_payload, indent=2) + "\n", encoding="utf-8")
    return rows


def fetch_daily_metrics(
    symbol: str,
    day: date,
    cache_dir: Path,
    refresh_cache: bool = False,
) -> list[FuturesMetric]:
    path = metrics_cache_path(cache_dir, symbol, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not refresh_cache:
        cached = read_metrics_cache(path)
        if cached is not None:
            return cached

    url = metrics_url(symbol, day)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            raw = response.read()
    except Exception:
        payload = {
            "symbol": symbol,
            "day": day.isoformat(),
            "fetched_at": int(time.time() * 1000),
            "metrics": [],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return []

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        csv_names = [name for name in archive.namelist() if name.endswith(".csv")]
        if not csv_names:
            rows: list[FuturesMetric] = []
        else:
            text = archive.read(csv_names[0]).decode("utf-8")
            rows = [futures_metric_from_json(row) for row in csv.DictReader(io.StringIO(text))]
    rows.sort(key=lambda item: item.timestamp)
    payload = {
        "symbol": symbol,
        "day": day.isoformat(),
        "fetched_at": int(time.time() * 1000),
        "metrics": [asdict(row) for row in rows],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return rows


def fetch_metrics(
    symbol: str,
    start_time: int,
    end_time: int,
    cache_dir: Path,
    refresh_cache: bool = False,
) -> list[FuturesMetric]:
    start_day = day_from_ms(start_time)
    end_day = day_from_ms(end_time)
    rows: list[FuturesMetric] = []
    current = start_day
    while current <= end_day:
        rows.extend(fetch_daily_metrics(symbol, current, cache_dir, refresh_cache))
        current += timedelta(days=1)
    deduped = {row.timestamp: row for row in rows if start_time <= row.timestamp <= end_time}
    return [deduped[key] for key in sorted(deduped)]


def funding_at_or_before(rows: list[FundingRate], timestamp: int) -> FundingRate | None:
    selected: FundingRate | None = None
    for row in rows:
        if row.funding_time > timestamp:
            break
        selected = row
    return selected


def metric_at_or_before(rows: list[FuturesMetric], timestamp: int) -> FuturesMetric | None:
    selected: FuturesMetric | None = None
    for row in rows:
        if row.timestamp > timestamp:
            break
        selected = row
    return selected


def pct_change(first: float, last: float) -> float | None:
    if first <= 0.0:
        return None
    return (last / first - 1.0) * 100.0
