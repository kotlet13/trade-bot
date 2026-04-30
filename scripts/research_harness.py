#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import concurrent.futures
import datetime
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import derivatives_data
import strategy_study as study


DEFAULT_TRIGGER_LIMIT = 12_000
DEFAULT_FORWARD_CANDLES = 32
DEFAULT_UNIVERSE_LIMIT = 20
DEFAULT_STARTING_CASH = 10_000.0
RESEARCH_CANDLES = 8_000
HOLDOUT_CANDLES = 4_000
FOLD_TRAIN_CANDLES = 3_000
FOLD_VALIDATION_CANDLES = 1_000
FOLD_COUNT = 5
MIN_PROMOTION_TRADES = 80
MIN_PROMOTION_NET_AVG_R = 0.10
MIN_PROMOTION_PROFIT_FACTOR = 1.25
MIN_HOLDOUT_NET_AVG_R = 0.05
MIN_POSITIVE_FOLDS = 4
MAX_PROMOTION_DRAWDOWN_R = 10.0
MAX_SYMBOL_CONCENTRATION = 0.40
MAX_SINGLE_TRADE_CONCENTRATION = 0.25
LOG_PATH = Path("tmp/strategy_test_log.md")
AI_SCORECARD_V2_SCORING_COMPONENTS = (
    "session",
    "fee",
    "volume",
    "atr",
    "btc",
    "relative_strength",
    "breadth",
    "funding",
    "metrics_missing",
    "taker",
    "oi",
    "global_bias",
    "top_position",
)
AI_SCORECARD_V2_ABLATION_COMPONENTS = tuple(
    component for component in AI_SCORECARD_V2_SCORING_COMPONENTS if component != "metrics_missing"
)
AI_SCORECARD_V2_COMPONENT_ALIASES = {
    "rs": "relative_strength",
    "relative": "relative_strength",
    "basket": "breadth",
    "market_breadth": "breadth",
    "global": "global_bias",
    "top_trader": "top_position",
    "top_trader_position": "top_position",
    "positioning": "top_position",
}

STABLE_OR_FIAT_BASES = {
    "USDC",
    "FDUSD",
    "TUSD",
    "BUSD",
    "DAI",
    "USDP",
    "PAX",
    "USDS",
    "USD1",
    "USDE",
    "USDD",
    "USDJ",
    "SUSD",
    "UST",
    "EUR",
    "GBP",
    "TRY",
    "BRL",
    "AUD",
    "RUB",
    "UAH",
    "AEUR",
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+USDT$")
DEFAULT_MIN_QUOTE_VOLUME = 5_000_000.0
STRICT_MATURE_BASES = {
    "AAVE",
    "ADA",
    "ALGO",
    "APT",
    "ARB",
    "ATOM",
    "AVAX",
    "AXS",
    "BCH",
    "BNB",
    "BTC",
    "COMP",
    "CRV",
    "DASH",
    "DOT",
    "EGLD",
    "ENS",
    "EOS",
    "ETC",
    "ETH",
    "FIL",
    "GALA",
    "HBAR",
    "ICP",
    "INJ",
    "LDO",
    "LINK",
    "LTC",
    "MANA",
    "MKR",
    "NEAR",
    "OP",
    "PENDLE",
    "POL",
    "QNT",
    "RAY",
    "RENDER",
    "RUNE",
    "SAND",
    "SOL",
    "SUI",
    "THETA",
    "TON",
    "TRX",
    "UNI",
    "VET",
    "XLM",
    "XMR",
    "XRP",
    "XTZ",
    "ZEC",
}
STRICT_EXCLUDED_BASES = {
    # Meme, political, fan, and very event-driven symbols are intentionally
    # excluded from the default research universe to avoid selection by one-day
    # turnover spikes instead of mature liquidity.
    "1000CAT",
    "1000CHEEMS",
    "1000SATS",
    "AIDOGE",
    "BABYDOGE",
    "BONK",
    "CAT",
    "CHEEMS",
    "DOGE",
    "DOGS",
    "FLOKI",
    "LADYS",
    "MEME",
    "MOG",
    "NEIRO",
    "PEPE",
    "PNUT",
    "SHIB",
    "TRUMP",
    "TURBO",
    "WIF",
}
_ROW_TIME_CACHE: dict[tuple[int, str, int], tuple[int, ...]] = {}


def row_times(rows: list[Any], attribute: str) -> tuple[int, ...]:
    key = (id(rows), attribute, len(rows))
    cached = _ROW_TIME_CACHE.get(key)
    if cached is not None:
        return cached
    values = tuple(int(getattr(row, attribute)) for row in rows)
    _ROW_TIME_CACHE[key] = values
    return values


@dataclass(frozen=True)
class MarketData:
    symbol: str
    trigger: list[study.Candle]
    setup: list[study.Candle]
    trend: list[study.Candle]
    funding: list[derivatives_data.FundingRate] = field(default_factory=list)
    metrics: list[derivatives_data.FuturesMetric] = field(default_factory=list)
    trigger_open_times: tuple[int, ...] = field(init=False, repr=False)
    setup_open_times: tuple[int, ...] = field(init=False, repr=False)
    trend_open_times: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_open_times", tuple(candle.open_time for candle in self.trigger))
        object.__setattr__(self, "setup_open_times", tuple(candle.open_time for candle in self.setup))
        object.__setattr__(self, "trend_open_times", tuple(candle.open_time for candle in self.trend))


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    family: str
    signal_kind: str
    config: study.StrategyConfig
    exit_style: str = "tp1_be_tp2"
    regime_filter: str = "none"
    use_session_filter: bool = True
    use_correlation_filter: bool = True
    params: dict[str, float | int | str | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class SplitSpec:
    name: str
    start: int
    end: int
    fold: int | None = None
    train_start: int | None = None
    train_end: int | None = None


@dataclass(frozen=True)
class TradeRecord:
    candidate: str
    family: str
    symbol: str
    split: str
    fold: int | None
    opened_at: int
    closed_at: int
    outcome: str
    gross_r: float
    net_r: float
    bars_held: int
    fees_paid: float
    session_bucket: str
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UniverseSelection:
    symbols: list[str]
    rejections: dict[str, int]
    min_quote_volume: float
    profile: str


def json_get(url: str, timeout: int = 20) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_24h_tickers() -> list[dict[str, Any]]:
    url = f"{study.BINANCE_DATA_API}/api/v3/ticker/24hr"
    payload = json_get(url)
    if not isinstance(payload, list):
        raise RuntimeError("Binance 24h ticker endpoint did not return a list.")
    return [item for item in payload if isinstance(item, dict)]


def quote_volume(item: dict[str, Any]) -> float:
    try:
        return float(item.get("quoteVolume", 0.0))
    except (TypeError, ValueError):
        return 0.0


def symbol_rejection_reason(
    item: dict[str, Any],
    *,
    profile: str,
    min_quote_volume: float,
    excluded_bases: set[str],
) -> str | None:
    symbol = str(item.get("symbol", ""))
    if not symbol.endswith("USDT"):
        return "not_usdt_quote"
    if not SYMBOL_PATTERN.fullmatch(symbol):
        return "non_ascii_or_non_standard_symbol"
    base = symbol[:-4]
    if base in STABLE_OR_FIAT_BASES:
        return "stable_or_fiat_base"
    if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
        return "leveraged_token"
    if quote_volume(item) <= 0.0:
        return "missing_quote_volume"
    if quote_volume(item) < min_quote_volume:
        return "quote_volume_below_min"
    if profile == "strict" and base in excluded_bases:
        return "strict_excluded_base"
    if profile == "strict" and base not in STRICT_MATURE_BASES:
        return "not_in_strict_mature_allowlist"
    return None


def is_allowed_usdt_symbol(item: dict[str, Any]) -> bool:
    return (
        symbol_rejection_reason(
            item,
            profile="permissive",
            min_quote_volume=0.0,
            excluded_bases=set(),
        )
        is None
    )


def select_top_usdt_symbols(
    limit: int,
    *,
    profile: str = "strict",
    min_quote_volume: float = DEFAULT_MIN_QUOTE_VOLUME,
    excluded_bases: set[str] | None = None,
    oversample: int = 3,
) -> UniverseSelection:
    excluded_bases = excluded_bases or STRICT_EXCLUDED_BASES
    rejections: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    for item in fetch_24h_tickers():
        reason = symbol_rejection_reason(
            item,
            profile=profile,
            min_quote_volume=min_quote_volume,
            excluded_bases=excluded_bases,
        )
        if reason is None:
            candidates.append(item)
        else:
            rejections[reason] += 1
    candidates.sort(key=quote_volume, reverse=True)
    symbols: list[str] = []
    for item in candidates:
        symbol = str(item["symbol"])
        if symbol not in symbols:
            symbols.append(symbol)
        if len(symbols) >= limit * max(1, oversample):
            break
    return UniverseSelection(
        symbols=symbols,
        rejections=dict(sorted(rejections.items())),
        min_quote_volume=min_quote_volume,
        profile=profile,
    )


def candle_cache_path(cache_dir: Path, symbol: str, interval: str, limit: int) -> Path:
    return cache_dir / f"{symbol}_{interval}_{limit}.json"


def candle_to_json(candle: study.Candle) -> dict[str, float | int]:
    return asdict(candle)


def candle_from_json(item: dict[str, Any]) -> study.Candle:
    return study.Candle(
        open_time=int(item["open_time"]),
        open=float(item["open"]),
        high=float(item["high"]),
        low=float(item["low"]),
        close=float(item["close"]),
        volume=float(item["volume"]),
    )


def load_cached_candles(path: Path, limit: int) -> list[study.Candle] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candles = [candle_from_json(item) for item in payload.get("candles", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    candles.sort(key=lambda item: item.open_time)
    if len(candles) < limit:
        return None
    return candles[-limit:]


def fetch_cached_candles(
    cache_dir: Path,
    symbol: str,
    interval: str,
    limit: int,
    refresh_cache: bool,
) -> list[study.Candle]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = candle_cache_path(cache_dir, symbol, interval, limit)
    if not refresh_cache:
        cached = load_cached_candles(path, limit)
        if cached is not None:
            return cached

    candles = study.fetch_klines(symbol, interval, limit)
    payload = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
        "fetched_at": int(time.time() * 1000),
        "candles": [candle_to_json(candle) for candle in candles],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return candles


def load_cached_metrics_range(
    cache_dir: Path,
    symbol: str,
    start_time: int,
    end_time: int,
) -> list[derivatives_data.FuturesMetric]:
    rows: list[derivatives_data.FuturesMetric] = []
    current_day = derivatives_data.day_from_ms(start_time)
    end_day = derivatives_data.day_from_ms(end_time)
    while current_day <= end_day:
        path = derivatives_data.metrics_cache_path(cache_dir, symbol, current_day)
        cached = derivatives_data.read_metrics_cache(path)
        if cached is not None:
            rows.extend(cached)
        current_day += datetime.timedelta(days=1)
    deduped = {row.timestamp: row for row in rows if start_time <= row.timestamp <= end_time}
    return [deduped[key] for key in sorted(deduped)]


def fetch_market_data(
    symbol: str,
    trigger_limit: int,
    cache_dir: Path,
    refresh_cache: bool,
    derivatives_cache_dir: Path | None = None,
    refresh_derivatives_cache: bool = False,
    include_funding: bool = False,
    include_metrics: bool = False,
    metrics_cache_only: bool = True,
) -> MarketData:
    setup_limit = math.ceil(trigger_limit / 4) + 200
    trend_limit = math.ceil(trigger_limit / 16) + 200
    trigger = fetch_cached_candles(cache_dir, symbol, "15m", trigger_limit, refresh_cache)
    funding: list[derivatives_data.FundingRate] = []
    metrics: list[derivatives_data.FuturesMetric] = []
    if include_funding and trigger and derivatives_cache_dir is not None:
        start_time = trigger[0].open_time
        end_time = trigger[-1].open_time + study.interval_millis("15m")
        try:
            funding = derivatives_data.fetch_funding_rates(
                symbol,
                start_time,
                end_time,
                derivatives_cache_dir,
                refresh_cache=refresh_derivatives_cache,
            )
        except Exception as exc:
            print(f"[warn] {symbol} funding unavailable: {exc}", file=sys.stderr)
    if include_metrics and trigger and derivatives_cache_dir is not None:
        start_time = trigger[0].open_time
        end_time = trigger[-1].open_time + study.interval_millis("15m")
        try:
            if metrics_cache_only:
                metrics = load_cached_metrics_range(derivatives_cache_dir, symbol, start_time, end_time)
            else:
                metrics = derivatives_data.fetch_metrics(
                    symbol,
                    start_time,
                    end_time,
                    derivatives_cache_dir,
                    refresh_cache=refresh_derivatives_cache,
                )
        except Exception as exc:
            print(f"[warn] {symbol} metrics unavailable: {exc}", file=sys.stderr)
    return MarketData(
        symbol=symbol,
        trigger=trigger,
        setup=fetch_cached_candles(cache_dir, symbol, "1h", setup_limit, refresh_cache),
        trend=fetch_cached_candles(cache_dir, symbol, "4h", trend_limit, refresh_cache),
        funding=funding,
        metrics=metrics,
    )


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2.0 / (period + 1)
    value = statistics.fmean(values[:period])
    for price in values[period:]:
        value = price * multiplier + value * (1.0 - multiplier)
    return value


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile_value))
    return ordered[max(0, min(index, len(ordered) - 1))]


def rounded(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def ai_scorecard_disabled_components(candidate: CandidateSpec) -> set[str]:
    raw = candidate.params.get("ablate_ai_components")
    if raw is None:
        return set()
    disabled: set[str] = set()
    for token in re.split(r"[,\s]+", str(raw).strip().lower()):
        if not token:
            continue
        component = AI_SCORECARD_V2_COMPONENT_ALIASES.get(token, token)
        if component == "all":
            return set(AI_SCORECARD_V2_SCORING_COMPONENTS)
        disabled.add(component)
    return disabled


def ai_scorecard_component_points(
    components: dict[str, Any],
    disabled_components: set[str],
    component: str,
    points_key: str,
    raw_points: int,
) -> int:
    active_points = 0 if component in disabled_components else raw_points
    components[points_key] = active_points
    if component in disabled_components:
        components[f"{component}_raw_points"] = raw_points
        components[f"{component}_ablated"] = True
    return active_points


def percentile_rank(values: list[float], current: float) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value <= current) / len(values)


def volume_percentile_rank(trigger_slice: list[study.Candle]) -> float | None:
    if len(trigger_slice) < 100:
        return None
    return percentile_rank([candle.volume for candle in trigger_slice[-97:-1]], trigger_slice[-1].volume)


def atr_expansion_multiple(trigger_slice: list[study.Candle]) -> float | None:
    if len(trigger_slice) < 120:
        return None
    recent_atr = study.calculate_atr(trigger_slice[-30:], 14)
    baseline_atr = study.calculate_atr(trigger_slice[-120:-30], 14)
    if recent_atr is None or baseline_atr is None or baseline_atr <= 0.0:
        return None
    return recent_atr / baseline_atr


def close_return_pct(candles: list[study.Candle], lookback_candles: int) -> float | None:
    if lookback_candles <= 0 or len(candles) <= lookback_candles:
        return None
    return derivatives_data.pct_change(candles[-lookback_candles - 1].close, candles[-1].close)


def btc_return_pct(btc_trend_slice: list[study.Candle], lookback_hours: float = 24.0) -> float | None:
    lookback_candles = max(1, int(round(lookback_hours / 4.0)))
    return close_return_pct(btc_trend_slice, lookback_candles)


def trigger_return_pct(data: MarketData, signal_close_time: int, lookback_hours: float) -> float | None:
    lookback_candles = max(1, int(round(lookback_hours * 4.0)))
    cutoff = signal_close_time - study.interval_millis("15m")
    end_index = bisect.bisect_right(data.trigger_open_times, cutoff) - 1
    start_index = end_index - lookback_candles
    if start_index < 0 or end_index < 0:
        return None
    return derivatives_data.pct_change(data.trigger[start_index].close, data.trigger[end_index].close)


def basket_return_values(
    market_data: dict[str, MarketData],
    signal_close_time: int,
    lookback_hours: float,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for symbol, data in market_data.items():
        value = trigger_return_pct(data, signal_close_time, lookback_hours)
        if value is not None:
            values[symbol] = value
    return values


def basket_positive_share_pct(
    market_data: dict[str, MarketData],
    signal_close_time: int,
    lookback_hours: float = 24.0,
) -> float | None:
    values = list(basket_return_values(market_data, signal_close_time, lookback_hours).values())
    if not values:
        return None
    return sum(1 for value in values if value > 0.0) / len(values) * 100.0


def relative_strength_percentile(
    symbol: str,
    market_data: dict[str, MarketData],
    signal_close_time: int,
    lookback_hours: float = 24.0,
) -> float | None:
    values = basket_return_values(market_data, signal_close_time, lookback_hours)
    current = values.get(symbol)
    if current is None:
        return None
    return percentile_rank(list(values.values()), current)


def session_bucket(timestamp_ms: int) -> str:
    hour = time.gmtime(timestamp_ms / 1000).tm_hour
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 16:
        return "london_ny_overlap"
    if 16 <= hour < 22:
        return "new_york"
    return "off_hours"


def closed_prefix(
    candles: list[study.Candle],
    open_times: tuple[int, ...],
    close_time: int,
    interval: str,
) -> list[study.Candle]:
    cutoff = close_time - study.interval_millis(interval)
    return candles[: bisect.bisect_right(open_times, cutoff)]


def closed_trigger_slice(data: MarketData, close_time: int) -> list[study.Candle]:
    return closed_prefix(data.trigger, data.trigger_open_times, close_time, "15m")


def closed_setup_slice(data: MarketData, close_time: int) -> list[study.Candle]:
    return closed_prefix(data.setup, data.setup_open_times, close_time, "1h")


def closed_trend_slice(data: MarketData, close_time: int) -> list[study.Candle]:
    return closed_prefix(data.trend, data.trend_open_times, close_time, "4h")


def build_splits(trigger_limit: int, forward_candles: int) -> list[SplitSpec]:
    if trigger_limit >= RESEARCH_CANDLES + HOLDOUT_CANDLES:
        splits = [
            SplitSpec(
                name="validation",
                start=fold * FOLD_VALIDATION_CANDLES + FOLD_TRAIN_CANDLES,
                end=fold * FOLD_VALIDATION_CANDLES + FOLD_TRAIN_CANDLES + FOLD_VALIDATION_CANDLES,
                fold=fold + 1,
                train_start=fold * FOLD_VALIDATION_CANDLES,
                train_end=fold * FOLD_VALIDATION_CANDLES + FOLD_TRAIN_CANDLES,
            )
            for fold in range(FOLD_COUNT)
        ]
        splits.append(
            SplitSpec(
                name="holdout",
                start=RESEARCH_CANDLES,
                end=RESEARCH_CANDLES + HOLDOUT_CANDLES,
            )
        )
        return splits

    holdout_size = max(forward_candles + 100, trigger_limit // 3)
    holdout_start = max(trigger_limit - holdout_size, trigger_limit // 2)
    validation_size = max(forward_candles + 80, min(250, holdout_start // 3))
    validation_start = max(0, holdout_start - validation_size)
    return [
        SplitSpec(
            name="validation",
            start=validation_start,
            end=holdout_start,
            fold=1,
            train_start=0,
            train_end=validation_start,
        ),
        SplitSpec(name="holdout", start=holdout_start, end=trigger_limit),
    ]


def with_config(base: study.StrategyConfig, name: str, **updates: Any) -> study.StrategyConfig:
    data = {
        "name": name,
        "pivot_span": base.pivot_span,
        "stalk_atr_distance_max": base.stalk_atr_distance_max,
        "reclaim_atr_distance_max": base.reclaim_atr_distance_max,
        "allow_neutral_setup": base.allow_neutral_setup,
        "trigger_body_ratio_min": base.trigger_body_ratio_min,
        "trigger_close_location_min": base.trigger_close_location_min,
        "require_close_above_previous_high": base.require_close_above_previous_high,
        "stop_support_buffer_atr_1h": base.stop_support_buffer_atr_1h,
        "stop_atr_mult_15m": base.stop_atr_mult_15m,
        "tp1_r_multiple": base.tp1_r_multiple,
        "tp2_r_multiple": base.tp2_r_multiple,
        "risk_percent": 0.01,
        "serial_mode": base.serial_mode,
    }
    data.update(updates)
    return study.StrategyConfig(**data)


def build_candidates() -> list[CandidateSpec]:
    base = study.StrategyConfig(name="v2_reclaim")
    strict_trigger = with_config(
        base,
        "v2_reclaim_strong_trigger",
        allow_neutral_setup=False,
        trigger_body_ratio_min=0.65,
        trigger_close_location_min=0.80,
    )
    strict_1h = with_config(
        base,
        "v2_reclaim_strict_1h",
        allow_neutral_setup=False,
        trigger_body_ratio_min=0.60,
        trigger_close_location_min=0.75,
    )
    moderate_1h = with_config(
        base,
        "v2_reclaim_moderate_1h",
        allow_neutral_setup=False,
        trigger_body_ratio_min=0.55,
        trigger_close_location_min=0.70,
    )
    tight = with_config(
        strict_1h,
        "v2_reclaim_tight",
        stalk_atr_distance_max=0.35,
        reclaim_atr_distance_max=0.35,
    )
    loose = with_config(
        base,
        "v2_reclaim_loose",
        reclaim_atr_distance_max=0.75,
        require_close_above_previous_high=False,
    )
    serial = with_config(strict_1h, "v2_reclaim_serial", serial_mode=True)
    benchmark = with_config(
        base,
        "benchmark",
        allow_neutral_setup=False,
        trigger_body_ratio_min=0.55,
        trigger_close_location_min=0.65,
        require_close_above_previous_high=False,
    )
    coverage_time16 = {
        "max_bars": 16,
        "min_stop_pct": 0.004,
        "max_fee_drag_r": 0.45,
        "exclude_btc": True,
    }
    coverage_time8 = {
        "max_bars": 8,
        "min_stop_pct": 0.004,
        "max_fee_drag_r": 0.45,
        "exclude_btc": True,
    }
    coverage_short8 = {
        "max_bars": 8,
        "min_stop_pct": 0.004,
        "max_fee_drag_r": 0.45,
        "exclude_btc": True,
    }
    ai_score_common = {
        "max_bars": 16,
        "min_stop_pct": 0.004,
        "max_fee_drag_r": 0.45,
        "exclude_btc": True,
        "use_ai_scorecard": True,
        "require_funding_data": True,
        "max_funding_age_hours": 12,
        "require_metrics_data": True,
        "max_metrics_age_minutes": 20,
    }
    risk_off_relief_common = {
        "max_bars": 8,
        "target_multiple": 1.2,
        "min_stop_pct": 0.004,
        "max_fee_drag_r": 0.45,
        "exclude_btc": True,
        "btc_return_lookback_hours": 24,
        "max_btc_return_pct": -1.0,
        "basket_breadth_lookback_hours": 24,
        "max_basket_positive_share_pct": 40.0,
        "relative_strength_lookback_hours": 24,
        "min_relative_strength_percentile": 0.50,
        "min_funding_bps": -5.0,
        "max_funding_age_hours": 12,
        "min_metrics_oi_24h_change_pct": -15.0,
        "max_metrics_oi_24h_change_pct": 2.0,
        "max_metrics_age_minutes": 20,
        "min_flush_atr": 1.35,
        "min_close_location": 0.60,
        "stop_atr_mult": 0.45,
    }
    event_rule_common = {**coverage_time16}
    event_rule_metrics_common = {
        **event_rule_common,
        "max_metrics_age_minutes": 20,
    }
    event_rule_funding_common = {
        **event_rule_common,
        "min_funding_bps": -0.9999,
        "max_funding_age_hours": 12,
    }
    event_rule_funding_metrics_common = {
        **event_rule_funding_common,
        "max_metrics_age_minutes": 20,
    }
    market_memory_neutral_common = {
        **ai_score_common,
        "btc_return_lookback_hours": 24,
        "min_btc_return_pct": -1.0,
        "max_btc_return_pct": 1.0,
    }
    market_memory_global120_common = {
        **market_memory_neutral_common,
        "max_global_account_long_short_ratio": 1.20,
    }
    market_memory_breadth_common = {
        **market_memory_global120_common,
        "basket_breadth_lookback_hours": 24,
        "min_basket_positive_share_pct": 30.0,
        "max_basket_positive_share_pct": 70.0,
    }
    market_memory_funding_taker_common = {
        **market_memory_neutral_common,
        "min_funding_bps": -0.9999,
        "min_taker_buy_sell_ratio": 1.10,
    }
    relative_strength_continuation_common = {
        **coverage_time16,
        "relative_strength_lookback_hours": 24,
        "min_relative_strength_percentile": 0.70,
        "basket_breadth_lookback_hours": 24,
        "min_basket_positive_share_pct": 45.0,
        "max_basket_positive_share_pct": 85.0,
        "btc_return_lookback_hours": 24,
        "min_btc_return_pct": -1.5,
        "max_btc_return_pct": 3.5,
        "use_ai_scorecard": True,
        "require_funding_data": True,
        "max_funding_age_hours": 12,
        "require_metrics_data": True,
        "max_metrics_age_minutes": 20,
    }
    relative_strength_quality_common = {
        **relative_strength_continuation_common,
        "min_taker_buy_sell_ratio": 1.10,
        "max_global_account_long_short_ratio": 1.80,
        "max_top_trader_position_long_short_ratio": 2.20,
    }
    relative_strength_refine_rs65 = {
        **relative_strength_quality_common,
        "min_relative_strength_percentile": 0.65,
    }
    relative_strength_refine_rs60 = {
        **relative_strength_quality_common,
        "min_relative_strength_percentile": 0.60,
    }
    relative_strength_refine_breadth_wide = {
        **relative_strength_quality_common,
        "min_basket_positive_share_pct": 40.0,
        "max_basket_positive_share_pct": 90.0,
    }
    relative_strength_refine_btc_loose = {
        **relative_strength_quality_common,
        "min_btc_return_pct": -2.0,
        "max_btc_return_pct": 4.0,
    }
    relative_strength_refine_position_loose = {
        **relative_strength_continuation_common,
        "min_taker_buy_sell_ratio": 1.00,
        "max_global_account_long_short_ratio": 2.00,
        "max_top_trader_position_long_short_ratio": 2.40,
    }
    relative_strength_refine_active_rs80 = {
        **relative_strength_continuation_common,
        "min_relative_strength_percentile": 0.80,
    }

    return [
        CandidateSpec("v2_reclaim", "v2_reclaim", "v2_reclaim", base),
        CandidateSpec("v2_reclaim_tight", "v2_reclaim", "v2_reclaim", tight),
        CandidateSpec("v2_reclaim_loose", "v2_reclaim", "v2_reclaim", loose),
        CandidateSpec("v2_reclaim_strong_trigger", "v2_reclaim", "v2_reclaim", strict_trigger),
        CandidateSpec("v2_reclaim_serial", "v2_reclaim", "v2_reclaim", serial),
        CandidateSpec(
            "v2_reclaim_partial_no_be",
            "exit_variant",
            "v2_reclaim",
            strict_1h,
            exit_style="partial_no_be",
        ),
        CandidateSpec(
            "v2_reclaim_time_stop_16",
            "exit_variant",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            params={"max_bars": 16},
        ),
        CandidateSpec(
            "v2_reclaim_atr_trail",
            "exit_variant",
            "v2_reclaim",
            strict_1h,
            exit_style="atr_trail",
            params={"trail_atr_mult": 2.0},
        ),
        CandidateSpec(
            "v2_reclaim_no_be_trail",
            "exit_variant",
            "v2_reclaim",
            strict_1h,
            exit_style="atr_trail",
            params={"trail_atr_mult": 1.5},
        ),
        CandidateSpec(
            "v2_reclaim_btc_bullish",
            "regime_filter",
            "v2_reclaim",
            strict_1h,
            regime_filter="btc_bullish",
        ),
        CandidateSpec(
            "v2_reclaim_breadth_60",
            "regime_filter",
            "v2_reclaim",
            strict_1h,
            regime_filter="breadth_60",
        ),
        CandidateSpec(
            "v2_reclaim_atr_expansion",
            "regime_filter",
            "v2_reclaim",
            strict_1h,
            regime_filter="atr_expansion",
        ),
        CandidateSpec(
            "v2_reclaim_volume_70",
            "regime_filter",
            "v2_reclaim",
            strict_1h,
            regime_filter="volume_70",
        ),
        CandidateSpec(
            "v2_reclaim_overlap_only",
            "regime_filter",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
        ),
        CandidateSpec(
            "v2_reclaim_overlap_fee_ok",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={"min_stop_pct": 0.006, "max_fee_drag_r": 0.35},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_wide_fee_ok",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={"min_stop_pct": 0.008, "max_fee_drag_r": 0.28},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_volume_70",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={"min_volume_percentile": 0.70},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_volume_fee_ok",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={"min_volume_percentile": 0.70, "min_stop_pct": 0.006, "max_fee_drag_r": 0.35},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_atr_expansion",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={"min_atr_expansion_multiple": 1.10},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_btc_bullish",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={"require_btc_bullish": True},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_btc_volume_fee_ok",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            regime_filter="overlap_session",
            params={
                "require_btc_bullish": True,
                "min_volume_percentile": 0.70,
                "min_stop_pct": 0.006,
                "max_fee_drag_r": 0.35,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_time_stop_fee_ok",
            "focused_overlap",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            params={"max_bars": 16, "min_stop_pct": 0.006, "max_fee_drag_r": 0.35},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_time_stop_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            params={"max_bars": 16, "min_stop_pct": 0.006, "max_fee_drag_r": 0.35, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_time_stop_atr_ok",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            params={"max_bars": 16, "min_stop_pct": 0.006, "max_fee_drag_r": 0.35, "min_atr_expansion_multiple": 0.90},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_time_stop_atr_ok_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            params={
                "max_bars": 16,
                "min_stop_pct": 0.006,
                "max_fee_drag_r": 0.35,
                "min_atr_expansion_multiple": 0.90,
                "exclude_btc": True,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_time_stop_atr_exp_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            params={
                "max_bars": 16,
                "min_stop_pct": 0.006,
                "max_fee_drag_r": 0.35,
                "min_atr_expansion_multiple": 1.10,
                "exclude_btc": True,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            params={"max_bars": 16, "min_stop_pct": 0.006, "max_fee_drag_r": 0.35, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_atr_ok_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            params={
                "max_bars": 16,
                "min_stop_pct": 0.006,
                "max_fee_drag_r": 0.35,
                "min_atr_expansion_multiple": 0.90,
                "exclude_btc": True,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_loose_fee_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_volume_no_btc",
            "focused_widening",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            params={
                "max_bars": 16,
                "min_stop_pct": 0.006,
                "max_fee_drag_r": 0.35,
                "min_volume_percentile": 0.70,
                "exclude_btc": True,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_time_stop_loose_fee_no_btc",
            "focused_scale",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_active_time_stop_atr_ok_no_btc",
            "focused_scale",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                "max_bars": 16,
                "min_stop_pct": 0.006,
                "max_fee_drag_r": 0.35,
                "min_atr_expansion_multiple": 0.90,
                "exclude_btc": True,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_moderate_no_btc",
            "focused_scale",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_active_time_stop_moderate_no_btc",
            "focused_scale",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_base_no_btc",
            "focused_scale",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_active_time_stop_base_no_btc",
            "focused_scale",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_time_stop_no_corr_no_btc",
            "focused_scale",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            use_correlation_filter=False,
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_active_time_stop_no_corr_no_btc",
            "focused_scale",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={"max_bars": 16, "min_stop_pct": 0.004, "max_fee_drag_r": 0.45, "exclude_btc": True},
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_vol_lt90",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "max_volume_percentile": 0.90,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_vol_50_90",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_volume_percentile": 0.50,
                "max_volume_percentile": 0.90,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_vol_50_85",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_volume_percentile": 0.50,
                "max_volume_percentile": 0.85,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_ex_worst4",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "excluded_symbols": "APTUSDT,AVAXUSDT,ADAUSDT,LDOUSDT",
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_ex_worst6",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "excluded_symbols": "APTUSDT,AVAXUSDT,ADAUSDT,LDOUSDT,AAVEUSDT,LINKUSDT",
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_vol_lt90_ex_worst4",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "max_volume_percentile": 0.90,
                "excluded_symbols": "APTUSDT,AVAXUSDT,ADAUSDT,LDOUSDT",
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_atr_lt110",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "max_atr_expansion_multiple": 1.10,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_corr_vol_lt90",
            "focused_refinement",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "max_volume_percentile": 0.90,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_funding_mild_neg",
            "derivatives_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_bps": -0.0001,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_funding_not_panic",
            "derivatives_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_funding_abs_lt1",
            "derivatives_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "max_abs_funding_bps": 1.0,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_no_corr_funding_neg_to_pos1",
            "derivatives_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_bps": 1.0,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_moderate_funding_not_panic",
            "derivatives_filter",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_ny_no_corr_funding_not_panic",
            "derivatives_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_or_new_york",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_base_taker_buy",
            "metrics_filter",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_base_funding_taker_buy",
            "metrics_filter",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_base_taker_global_lte120",
            "metrics_filter",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_taker_buy_sell_ratio": 1.25,
                "max_global_account_long_short_ratio": 1.20,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_base_funding_taker_buy",
            "metrics_filter",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="overlap_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_overlap_strict_funding_taker_buy",
            "metrics_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_active_strict_funding_taker_buy",
            "metrics_filter",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_global_lte120",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_taker_ge125",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_metrics_common,
                "min_taker_buy_sell_ratio": 1.25,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_funding_not_panic",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={**event_rule_funding_common},
        ),
        CandidateSpec(
            "event_rule_v2_base_global_taker",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
                "min_taker_buy_sell_ratio": 1.25,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_funding_taker",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_funding_metrics_common,
                "min_taker_buy_sell_ratio": 1.25,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_global_funding",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_funding_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_global_funding_taker",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_funding_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
                "min_taker_buy_sell_ratio": 1.25,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_global_london_overlap",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            params={
                **event_rule_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_global_taker_10_16",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
                "min_taker_buy_sell_ratio": 1.25,
                "min_hour_utc": 10,
                "max_hour_utc": 16,
            },
        ),
        CandidateSpec(
            "event_rule_v2_base_funding_taker_10_16",
            "event_rule_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_funding_metrics_common,
                "min_taker_buy_sell_ratio": 1.25,
                "min_hour_utc": 10,
                "max_hour_utc": 16,
            },
        ),
        CandidateSpec(
            "event_rule_v2_moderate_global_lte120",
            "event_rule_filters",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
            },
        ),
        CandidateSpec(
            "event_rule_v2_no_corr_global_lte120",
            "event_rule_filters",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **event_rule_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
            },
        ),
        CandidateSpec(
            "event_rule_v2_moderate_global_funding_taker",
            "event_rule_filters",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                **event_rule_funding_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
                "min_taker_buy_sell_ratio": 1.25,
            },
        ),
        CandidateSpec(
            "event_rule_v2_no_corr_global_funding_taker",
            "event_rule_filters",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **event_rule_funding_metrics_common,
                "max_global_account_long_short_ratio": 1.20,
                "min_taker_buy_sell_ratio": 1.25,
            },
        ),
        CandidateSpec(
            "ema_pullback_london_overlap_funding_taker",
            "broad_derivatives_entry",
            "ema_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_continuation_london_overlap_funding_taker",
            "broad_derivatives_entry",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "donchian_breakout_48_london_overlap_funding_taker",
            "broad_derivatives_entry",
            "donchian_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "lookback": 48,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "breakout_pullback_london_overlap_funding_taker",
            "broad_derivatives_entry",
            "breakout_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "lookback": 48,
                "pullback_bars": 16,
                "level_buffer_atr": 0.35,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "opening_session_breakout_london_overlap_funding_taker",
            "broad_derivatives_entry",
            "opening_session_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_continuation_london_funding_taker",
            "broad_derivatives_refined",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_continuation_london_funding_taker_global_lte120",
            "broad_derivatives_refined",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_global_account_long_short_ratio": 1.20,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_continuation_london_funding_taker_oi_cooling",
            "broad_derivatives_refined",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_continuation_london_funding_taker_oi_cooling_global_lte120",
            "broad_derivatives_refined",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_global_account_long_short_ratio": 1.20,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_london_base_funding_taker_oi_cooling",
            "broad_derivatives_refined",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "v2_reclaim_london_strict_funding_taker_oi_cooling",
            "broad_derivatives_refined",
            "v2_reclaim",
            strict_1h,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_london_funding_taker_oi_max0",
            "broad_derivatives_oi_sweep",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_london_funding_taker_oi_neg15_0",
            "broad_derivatives_oi_sweep",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -15.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_london_funding_taker_oi_neg10_pos1",
            "broad_derivatives_oi_sweep",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 16,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 1.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_london_funding_taker_oi_neg10_0_maxbars12",
            "broad_derivatives_oi_sweep",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 12,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "htf_london_funding_taker_oi_neg10_0_maxbars8",
            "broad_derivatives_oi_sweep",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={
                "max_bars": 8,
                "min_stop_pct": 0.004,
                "max_fee_drag_r": 0.45,
                "exclude_btc": True,
                "min_funding_bps": -0.9999,
                "max_funding_age_hours": 12,
                "min_taker_buy_sell_ratio": 1.25,
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 20,
            },
        ),
        CandidateSpec(
            "coverage_v2_base_active_time16",
            "coverage_scan",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_v2_moderate_active_time16",
            "coverage_scan",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_v2_loose_active_time16",
            "coverage_scan",
            "v2_reclaim",
            loose,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_htf_active_time16",
            "coverage_scan",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_htf_active_time8",
            "coverage_scan",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time8},
        ),
        CandidateSpec(
            "coverage_ema_active_time16",
            "coverage_scan",
            "ema_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_donchian48_active_time16",
            "coverage_scan",
            "donchian_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16, "lookback": 48},
        ),
        CandidateSpec(
            "coverage_donchian80_active_time16",
            "coverage_scan",
            "donchian_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16, "lookback": 80},
        ),
        CandidateSpec(
            "coverage_breakout_pullback48_active_time16",
            "coverage_scan",
            "breakout_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16, "lookback": 48, "pullback_bars": 16, "level_buffer_atr": 0.35},
        ),
        CandidateSpec(
            "coverage_opening_breakout_active_time16",
            "coverage_scan",
            "opening_session_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_session_trap_long_active",
            "coverage_scan",
            "session_trap_long",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16, "max_bars": 12, "range_minutes": 60, "trade_window_hours": 5},
        ),
        CandidateSpec(
            "coverage_session_trap_short_active",
            "coverage_scan",
            "session_trap_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_short8, "max_bars": 12, "range_minutes": 60, "trade_window_hours": 5},
        ),
        CandidateSpec(
            "coverage_crash_rebound_loose_active",
            "coverage_scan",
            "crash_rebound",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **coverage_time8,
                "min_flush_atr": 1.75,
                "min_close_location": 0.50,
                "stop_atr_mult": 0.80,
            },
        ),
        CandidateSpec(
            "coverage_exhaustion_short_loose_active",
            "coverage_scan",
            "exhaustion_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "min_push_atr": 1.75,
                "min_close_location": 0.75,
                "stop_atr_mult": 0.80,
            },
        ),
        CandidateSpec(
            "coverage_v2_moderate_london_overlap_time16",
            "coverage_refinement",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_v2_moderate_overlap_time16",
            "coverage_refinement",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="overlap_session",
            use_correlation_filter=False,
            params={**coverage_time16},
        ),
        CandidateSpec(
            "coverage_v2_moderate_active_10_16_time16",
            "coverage_refinement",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_time16, "min_hour_utc": 10, "max_hour_utc": 16},
        ),
        CandidateSpec(
            "coverage_v2_moderate_london_overlap_funding_m2_p1",
            "coverage_refinement",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={
                **coverage_time16,
                "min_funding_bps": -2.0,
                "max_funding_bps": 1.0,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "coverage_v2_moderate_10_16_funding_m2_p1",
            "coverage_refinement",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **coverage_time16,
                "min_hour_utc": 10,
                "max_hour_utc": 16,
                "min_funding_bps": -2.0,
                "max_funding_bps": 1.0,
                "max_funding_age_hours": 12,
            },
        ),
        CandidateSpec(
            "coverage_short_htf_active_time16",
            "coverage_short_trend",
            "htf_trend_continuation_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_short8, "max_bars": 16},
        ),
        CandidateSpec(
            "coverage_short_htf_active_time8",
            "coverage_short_trend",
            "htf_trend_continuation_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_short8},
        ),
        CandidateSpec(
            "coverage_short_donchian48_active_time16",
            "coverage_short_trend",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_short8, "max_bars": 16, "lookback": 48},
        ),
        CandidateSpec(
            "coverage_short_donchian80_active_time16",
            "coverage_short_trend",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_short8, "max_bars": 16, "lookback": 80},
        ),
        CandidateSpec(
            "coverage_short_ema_active_time16",
            "coverage_short_trend",
            "ema_pullback_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**coverage_short8, "max_bars": 16},
        ),
        CandidateSpec(
            "fold2_short_donchian80_ny_btc_down",
            "fold2_risk_off_short",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "lookback": 80,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
            },
        ),
        CandidateSpec(
            "fold2_short_donchian80_ny_oi_cooling",
            "fold2_risk_off_short",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "lookback": 80,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "fold2_short_donchian48_ny_oi_cooling",
            "fold2_risk_off_short",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "lookback": 48,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "fold2_short_htf_ny_oi_cooling",
            "fold2_risk_off_short",
            "htf_trend_continuation_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "fold2_short_ema_ny_oi_cooling",
            "fold2_risk_off_short",
            "ema_pullback_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "fold2_short_donchian80_offhours_oi_cooling",
            "fold2_risk_off_short",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="off_hours",
            use_session_filter=False,
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "lookback": 80,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "fold2_short_donchian48_offhours_oi_cooling",
            "fold2_risk_off_short",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="off_hours",
            use_session_filter=False,
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "lookback": 48,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "fold2_short_donchian80_ny_sell_pressure",
            "fold2_risk_off_short",
            "donchian_breakdown",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={
                **coverage_short8,
                "lookback": 80,
                "max_bars": 8,
                "btc_return_lookback_hours": 24,
                "max_btc_return_pct": -1.0,
                "max_metrics_oi_24h_change_pct": 0.0,
                "max_taker_buy_sell_ratio": 1.0,
                "max_metrics_age_minutes": 15,
            },
        ),
        CandidateSpec(
            "ai_score_v2_base_score5",
            "ai_scorecard_v2",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "ai_score_v2_base_score7",
            "ai_scorecard_v2",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 7},
        ),
        CandidateSpec(
            "ai_score_v2_moderate_score5",
            "ai_scorecard_v2",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "ai_score_v2_moderate_score7",
            "ai_scorecard_v2",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 7},
        ),
        CandidateSpec(
            "ai_score_v2_moderate_10_16_score5",
            "ai_scorecard_v2",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 5, "min_hour_utc": 10, "max_hour_utc": 16},
        ),
        CandidateSpec(
            "ai_score_v2_moderate_relstrength_score6",
            "ai_scorecard_v2",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 6, "min_relative_strength_percentile": 0.60},
        ),
        CandidateSpec(
            "ai_score_v2_moderate_compression_score5",
            "ai_scorecard_v2",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 5,
                "min_volume_percentile": 0.50,
                "max_volume_percentile": 0.90,
                "max_atr_expansion_multiple": 1.10,
            },
        ),
        CandidateSpec(
            "ai_score_v2_ablation_control_score7",
            "ai_scorecard_v2_ablation",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 7},
        ),
        *[
            CandidateSpec(
                f"ai_score_v2_ablate_{component}",
                "ai_scorecard_v2_ablation",
                "v2_reclaim",
                base,
                exit_style="time_stop",
                regime_filter="active_session",
                use_correlation_filter=False,
                params={**ai_score_common, "min_ai_score": 7, "ablate_ai_components": component},
            )
            for component in AI_SCORECARD_V2_ABLATION_COMPONENTS
        ],
        CandidateSpec(
            "memory_v2_base_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "memory_v2_base_neutral_s6",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 6},
        ),
        CandidateSpec(
            "memory_v2_base_neutral_s7",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 7},
        ),
        CandidateSpec(
            "memory_v2_oi_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 5, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "memory_v2_oi_neutral_s6",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 6, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "memory_v2_oi_neutral_s7",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 7, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "memory_v2_base_london_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "memory_v2_oi_london_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="london_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 5, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "memory_v2_base_new_york_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "memory_v2_oi_new_york_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="new_york_session",
            use_correlation_filter=False,
            params={**market_memory_neutral_common, "min_ai_score": 5, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "memory_v2_base_global120_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_global120_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "memory_v2_oi_global120_neutral_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_global120_common, "min_ai_score": 5, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "memory_v2_base_breadth30_70_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_breadth_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "memory_v2_oi_funding_taker110_s5",
            "market_memory_filters",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**market_memory_funding_taker_common, "min_ai_score": 5, "ablate_ai_components": "oi"},
        ),
        CandidateSpec(
            "rs_htf_active_s5",
            "relative_strength_continuation",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_htf_active_s6",
            "relative_strength_continuation",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "min_ai_score": 6},
        ),
        CandidateSpec(
            "rs_htf_london_overlap_s5",
            "relative_strength_continuation",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_htf_quality_s5",
            "relative_strength_continuation",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_htf_quality_s6",
            "relative_strength_continuation",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 6},
        ),
        CandidateSpec(
            "rs_htf_quality_taker125_s5",
            "relative_strength_continuation",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_taker_buy_sell_ratio": 1.25, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_donchian48_active_s5",
            "relative_strength_continuation",
            "donchian_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "lookback": 48, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_donchian80_active_s5",
            "relative_strength_continuation",
            "donchian_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "lookback": 80, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_breakout_pullback48_active_s5",
            "relative_strength_continuation",
            "breakout_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **relative_strength_continuation_common,
                "lookback": 48,
                "pullback_bars": 16,
                "level_buffer_atr": 0.35,
                "min_ai_score": 5,
            },
        ),
        CandidateSpec(
            "rs_ema_active_s5",
            "relative_strength_continuation",
            "ema_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_opening_breakout_active_s5",
            "relative_strength_continuation",
            "opening_session_breakout",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_v2_moderate_active_s5",
            "relative_strength_continuation",
            "v2_reclaim",
            moderate_1h,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_continuation_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_control",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s6_control",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 6},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_rs65",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_rs65, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s6_rs65",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_rs65, "min_ai_score": 6},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_rs60",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_rs60, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_breadth40_90",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_breadth_wide, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_btc_loose",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_btc_loose, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_position_loose_s5",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_position_loose, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_oi_max2",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 5, "max_metrics_oi_24h_change_pct": 2.0},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_target12",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 5, "target_multiple": 1.2},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_maxbars24",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 5, "max_bars": 24},
        ),
        CandidateSpec(
            "rs_refine_htf_quality_s5_overlap",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**relative_strength_quality_common, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_active_rs80",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**relative_strength_refine_active_rs80, "min_ai_score": 5},
        ),
        CandidateSpec(
            "rs_refine_htf_overlap_rs80",
            "relative_strength_refinement",
            "htf_trend_continuation",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**relative_strength_refine_active_rs80, "min_ai_score": 5},
        ),
        CandidateSpec(
            "ai_score_global_base_s6_g120",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 6, "max_global_account_long_short_ratio": 1.20},
        ),
        CandidateSpec(
            "ai_score_global_base_s6_g135",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 6, "max_global_account_long_short_ratio": 1.35},
        ),
        CandidateSpec(
            "ai_score_global_base_s6_g150",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 6, "max_global_account_long_short_ratio": 1.50},
        ),
        CandidateSpec(
            "ai_score_global_base_s7_g135",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 7, "max_global_account_long_short_ratio": 1.35},
        ),
        CandidateSpec(
            "ai_score_global_base_s7_g150",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={**ai_score_common, "min_ai_score": 7, "max_global_account_long_short_ratio": 1.50},
        ),
        CandidateSpec(
            "ai_score_global_base_s6_g150_toppos160",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 6,
                "max_global_account_long_short_ratio": 1.50,
                "max_top_trader_position_long_short_ratio": 1.60,
            },
        ),
        CandidateSpec(
            "ai_score_global_base_s7_g150_toppos160",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 7,
                "max_global_account_long_short_ratio": 1.50,
                "max_top_trader_position_long_short_ratio": 1.60,
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s6_g120",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 6,
                "max_global_account_long_short_ratio": 1.20,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s6_g135",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 6,
                "max_global_account_long_short_ratio": 1.35,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s6_g150",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 6,
                "max_global_account_long_short_ratio": 1.50,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s7_g135",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 7,
                "max_global_account_long_short_ratio": 1.35,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s7_g150",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 7,
                "max_global_account_long_short_ratio": 1.50,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s6_g150_toppos160",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 6,
                "max_global_account_long_short_ratio": 1.50,
                "max_top_trader_position_long_short_ratio": 1.60,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "ai_score_global_oi_s7_g150_toppos160",
            "ai_scorecard_v2_global_sweep",
            "v2_reclaim",
            base,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={
                **ai_score_common,
                "min_ai_score": 7,
                "max_global_account_long_short_ratio": 1.50,
                "max_top_trader_position_long_short_ratio": 1.60,
                "ablate_ai_components": "oi",
            },
        ),
        CandidateSpec(
            "risk_off_london_relief_base",
            "risk_off_london_relief",
            "risk_off_london_relief",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**risk_off_relief_common},
        ),
        CandidateSpec(
            "risk_off_london_relief_relstrong",
            "risk_off_london_relief",
            "risk_off_london_relief",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**risk_off_relief_common, "min_relative_strength_percentile": 0.65},
        ),
        CandidateSpec(
            "risk_off_london_relief_taker",
            "risk_off_london_relief",
            "risk_off_london_relief",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**risk_off_relief_common, "min_taker_buy_sell_ratio": 1.10},
        ),
        CandidateSpec(
            "risk_off_london_relief_oi_cooling",
            "risk_off_london_relief",
            "risk_off_london_relief",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**risk_off_relief_common, "max_metrics_oi_24h_change_pct": 0.0},
        ),
        CandidateSpec(
            "risk_off_london_relief_strict_btc",
            "risk_off_london_relief",
            "risk_off_london_relief",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**risk_off_relief_common, "max_btc_return_pct": -3.0, "min_relative_strength_percentile": 0.60},
        ),
        CandidateSpec(
            "risk_off_london_relief_fast",
            "risk_off_london_relief",
            "risk_off_london_relief",
            benchmark,
            exit_style="time_stop",
            regime_filter="london_or_overlap",
            use_correlation_filter=False,
            params={**risk_off_relief_common, "max_bars": 4, "target_multiple": 1.0, "stop_atr_mult": 0.35},
        ),
        CandidateSpec(
            "crash_rebound_active",
            "absurd_candle",
            "crash_rebound",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            params={
                "max_bars": 8,
                "min_flush_atr": 2.5,
                "min_close_location": 0.55,
                "min_volume_percentile": 0.70,
                "stop_atr_mult": 0.80,
            },
        ),
        CandidateSpec(
            "crash_rebound_off_hours",
            "absurd_candle",
            "crash_rebound",
            benchmark,
            exit_style="time_stop",
            regime_filter="off_hours",
            use_session_filter=False,
            params={
                "max_bars": 8,
                "min_flush_atr": 2.5,
                "min_close_location": 0.55,
                "min_volume_percentile": 0.70,
                "stop_atr_mult": 0.80,
            },
        ),
        CandidateSpec(
            "breakout_pullback_active",
            "absurd_candle",
            "breakout_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            params={"max_bars": 16, "lookback": 48, "pullback_bars": 16, "level_buffer_atr": 0.35},
        ),
        CandidateSpec(
            "breakout_pullback_no_corr",
            "absurd_candle",
            "breakout_pullback",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            use_correlation_filter=False,
            params={"max_bars": 16, "lookback": 48, "pullback_bars": 16, "level_buffer_atr": 0.35},
        ),
        CandidateSpec(
            "session_trap_long",
            "absurd_candle",
            "session_trap_long",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            params={"max_bars": 12, "range_minutes": 60, "trade_window_hours": 5},
        ),
        CandidateSpec(
            "session_trap_short",
            "absurd_candle",
            "session_trap_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            params={"max_bars": 12, "range_minutes": 60, "trade_window_hours": 5},
        ),
        CandidateSpec(
            "exhaustion_short_active",
            "absurd_candle",
            "exhaustion_short",
            benchmark,
            exit_style="short_time_stop",
            regime_filter="active_session",
            params={
                "max_bars": 8,
                "min_push_atr": 2.5,
                "min_close_location": 0.80,
                "min_volume_percentile": 0.90,
                "stop_atr_mult": 0.80,
            },
        ),
        CandidateSpec(
            "monday_london_trap_long",
            "absurd_candle",
            "session_trap_long",
            benchmark,
            exit_style="time_stop",
            regime_filter="active_session",
            params={"max_bars": 12, "range_minutes": 60, "trade_window_hours": 5, "allowed_weekdays": "0"},
        ),
        CandidateSpec("ema_pullback", "benchmark", "ema_pullback", benchmark),
        CandidateSpec("donchian_breakout", "benchmark", "donchian_breakout", benchmark),
        CandidateSpec("opening_session_breakout", "benchmark", "opening_session_breakout", benchmark),
        CandidateSpec("htf_trend_continuation", "benchmark", "htf_trend_continuation", benchmark),
    ]


def candidate_needs_funding(candidate: CandidateSpec) -> bool:
    funding_keys = {
        "min_funding_bps",
        "max_funding_bps",
        "max_abs_funding_bps",
        "max_funding_age_hours",
        "require_funding_data",
        "min_ai_score",
        "use_ai_scorecard",
    }
    return any(key in candidate.params for key in funding_keys)


def candidate_needs_metrics(candidate: CandidateSpec) -> bool:
    metric_keys = {
        "min_taker_buy_sell_ratio",
        "max_taker_buy_sell_ratio",
        "min_global_account_long_short_ratio",
        "max_global_account_long_short_ratio",
        "min_top_trader_account_long_short_ratio",
        "max_top_trader_account_long_short_ratio",
        "min_top_trader_position_long_short_ratio",
        "max_top_trader_position_long_short_ratio",
        "min_metrics_oi_24h_change_pct",
        "max_metrics_oi_24h_change_pct",
        "metrics_oi_change_lookback_hours",
        "max_metrics_age_minutes",
        "require_metrics_data",
        "min_ai_score",
        "use_ai_scorecard",
    }
    return any(key in candidate.params for key in metric_keys)


def candidates_need_funding(candidates: list[CandidateSpec]) -> bool:
    return any(candidate_needs_funding(candidate) for candidate in candidates)


def candidates_need_metrics(candidates: list[CandidateSpec]) -> bool:
    return any(candidate_needs_metrics(candidate) for candidate in candidates)


def evaluate_v2_reclaim(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    evaluation = study.evaluate_signal(
        current_price,
        DEFAULT_STARTING_CASH,
        fee_bps,
        trend_slice,
        setup_slice,
        trigger_slice,
        candidate.config,
    )
    if evaluation.stage == "ready":
        return evaluation.risk_plan
    return None


def build_direct_long_risk_plan(
    entry: float,
    stop_loss: float,
    fee_bps: float,
    config: study.StrategyConfig,
) -> study.RiskPlan | None:
    if entry <= 0.0 or stop_loss <= 0.0 or stop_loss >= entry:
        return None
    risk_per_unit = entry - stop_loss
    risk_amount = DEFAULT_STARTING_CASH * config.risk_percent
    quantity_by_risk = risk_amount / risk_per_unit
    quantity_by_cash = study.max_affordable_quantity(DEFAULT_STARTING_CASH, entry, fee_bps)
    suggested_quantity = min(quantity_by_risk, quantity_by_cash)
    if suggested_quantity <= 0.0 or not math.isfinite(suggested_quantity):
        return None
    actual_risk = suggested_quantity * risk_per_unit
    return study.RiskPlan(
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=entry + risk_per_unit * config.tp1_r_multiple,
        take_profit_2=entry + risk_per_unit * config.tp2_r_multiple,
        risk_per_unit=risk_per_unit,
        risk_amount=actual_risk,
        suggested_quantity=suggested_quantity,
        notional_estimate=suggested_quantity * entry,
    )


def build_direct_short_risk_plan(
    entry: float,
    stop_loss: float,
    fee_bps: float,
    config: study.StrategyConfig,
) -> study.RiskPlan | None:
    if entry <= 0.0 or stop_loss <= entry:
        return None
    risk_per_unit = stop_loss - entry
    risk_amount = DEFAULT_STARTING_CASH * config.risk_percent
    quantity_by_risk = risk_amount / risk_per_unit
    quantity_by_cash = study.max_affordable_quantity(DEFAULT_STARTING_CASH, entry, fee_bps)
    suggested_quantity = min(quantity_by_risk, quantity_by_cash)
    if suggested_quantity <= 0.0 or not math.isfinite(suggested_quantity):
        return None
    actual_risk = suggested_quantity * risk_per_unit
    return study.RiskPlan(
        entry=entry,
        stop_loss=stop_loss,
        take_profit_1=entry - risk_per_unit * config.tp1_r_multiple,
        take_profit_2=entry - risk_per_unit * config.tp2_r_multiple,
        risk_per_unit=risk_per_unit,
        risk_amount=actual_risk,
        suggested_quantity=suggested_quantity,
        notional_estimate=suggested_quantity * entry,
    )


def evaluate_ema_pullback(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trend_slice) < 100 or len(setup_slice) < 60 or len(trigger_slice) < 20:
        return None
    trend_closes = [candle.close for candle in trend_slice]
    setup_closes = [candle.close for candle in setup_slice]
    ema_50_4h = ema(trend_closes, 50)
    ema_100_4h = ema(trend_closes, 100)
    ema_20_1h = ema(setup_closes, 20)
    ema_50_1h = ema(setup_closes, 50)
    atr_1h = study.calculate_atr(setup_slice, 14)
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if None in (ema_50_4h, ema_100_4h, ema_20_1h, ema_50_1h, atr_1h, atr_15m):
        return None
    if not (trend_slice[-1].close > ema_50_4h > ema_100_4h):
        return None
    setup_close = setup_slice[-1].close
    if setup_close < ema_50_1h or abs(setup_close - ema_20_1h) > atr_1h * 0.75:
        return None
    trigger = study.analyze_trigger(trigger_slice, candidate.config)
    if not trigger.momentum_close:
        return None
    support = min(float(ema_20_1h), min(candle.low for candle in setup_slice[-10:]))
    risk_plan, _ = study.build_risk_plan(
        current_price,
        support,
        atr_1h,
        atr_15m,
        DEFAULT_STARTING_CASH,
        fee_bps,
        candidate.config,
    )
    return risk_plan


def bearish_momentum_close(trigger_slice: list[study.Candle], config: study.StrategyConfig) -> bool:
    if len(trigger_slice) < 2:
        return False
    last = trigger_slice[-1]
    previous = trigger_slice[-2]
    candle_range = max(last.high - last.low, 1e-9)
    body_ratio = abs(last.close - last.open) / candle_range
    close_location = (last.close - last.low) / candle_range
    if last.close >= last.open:
        return False
    if body_ratio < config.trigger_body_ratio_min:
        return False
    if close_location > 1.0 - config.trigger_close_location_min:
        return False
    if config.require_close_above_previous_high and last.close >= previous.low:
        return False
    return True


def evaluate_ema_pullback_short(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trend_slice) < 100 or len(setup_slice) < 60 or len(trigger_slice) < 20:
        return None
    trend_closes = [candle.close for candle in trend_slice]
    setup_closes = [candle.close for candle in setup_slice]
    ema_50_4h = ema(trend_closes, 50)
    ema_100_4h = ema(trend_closes, 100)
    ema_20_1h = ema(setup_closes, 20)
    ema_50_1h = ema(setup_closes, 50)
    atr_1h = study.calculate_atr(setup_slice, 14)
    if None in (ema_50_4h, ema_100_4h, ema_20_1h, ema_50_1h, atr_1h):
        return None
    if not (trend_slice[-1].close < ema_50_4h < ema_100_4h):
        return None
    setup_close = setup_slice[-1].close
    if setup_close > ema_50_1h or abs(setup_close - ema_20_1h) > atr_1h * 0.75:
        return None
    if not bearish_momentum_close(trigger_slice, candidate.config):
        return None
    stop_loss = max(float(ema_20_1h), max(candle.high for candle in setup_slice[-10:]))
    return build_direct_short_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_donchian_breakout(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    lookback = int(candidate.params.get("lookback", 80))
    if len(trigger_slice) < lookback + 2 or len(trend_slice) < 80 or len(setup_slice) < 20:
        return None
    trend_closes = [candle.close for candle in trend_slice]
    ema_50_4h = ema(trend_closes, 50)
    if ema_50_4h is None or trend_slice[-1].close < ema_50_4h:
        return None
    prior = trigger_slice[-lookback - 1 : -1]
    breakout = max(candle.high for candle in prior)
    last = trigger_slice[-1]
    if not (last.close > breakout and last.close > last.open):
        return None
    atr_1h = study.calculate_atr(setup_slice, 14)
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_1h is None or atr_15m is None:
        return None
    support = min(candle.low for candle in trigger_slice[-20:])
    risk_plan, _ = study.build_risk_plan(
        current_price,
        support,
        atr_1h,
        atr_15m,
        DEFAULT_STARTING_CASH,
        fee_bps,
        candidate.config,
    )
    return risk_plan


def evaluate_donchian_breakdown(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    lookback = int(candidate.params.get("lookback", 80))
    if len(trigger_slice) < lookback + 2 or len(trend_slice) < 80 or len(setup_slice) < 20:
        return None
    trend_closes = [candle.close for candle in trend_slice]
    ema_50_4h = ema(trend_closes, 50)
    if ema_50_4h is None or trend_slice[-1].close > ema_50_4h:
        return None
    prior = trigger_slice[-lookback - 1 : -1]
    breakdown = min(candle.low for candle in prior)
    last = trigger_slice[-1]
    if not (last.close < breakdown and last.close < last.open):
        return None
    stop_loss = max(candle.high for candle in trigger_slice[-20:])
    return build_direct_short_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_opening_session_breakout(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
    signal_close_time: int,
) -> study.RiskPlan | None:
    if len(trigger_slice) < 64 or len(setup_slice) < 20:
        return None
    timestamp = time.gmtime(signal_close_time / 1000)
    session_start_hour = 7 if 7 <= timestamp.tm_hour < 12 else 13 if 13 <= timestamp.tm_hour < 17 else None
    if session_start_hour is None:
        return None
    day_start = signal_close_time - (
        (timestamp.tm_hour * 60 + timestamp.tm_min) * 60 + timestamp.tm_sec
    ) * 1000
    session_start = day_start + session_start_hour * 60 * 60_000
    range_end = session_start + 60 * 60_000
    if not (range_end < signal_close_time <= session_start + 4 * 60 * 60_000):
        return None
    range_candles = [
        candle for candle in trigger_slice if session_start <= candle.open_time < range_end
    ]
    if len(range_candles) < 4:
        return None
    session_high = max(candle.high for candle in range_candles)
    session_low = min(candle.low for candle in range_candles)
    last = trigger_slice[-1]
    if not (last.close > session_high and last.close > last.open):
        return None
    atr_1h = study.calculate_atr(setup_slice, 14)
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_1h is None or atr_15m is None:
        return None
    risk_plan, _ = study.build_risk_plan(
        current_price,
        session_low,
        atr_1h,
        atr_15m,
        DEFAULT_STARTING_CASH,
        fee_bps,
        candidate.config,
    )
    return risk_plan


def evaluate_htf_trend_continuation(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trend_slice) < 80 or len(setup_slice) < 30 or len(trigger_slice) < 20:
        return None
    trend = study.analyze_structure(trend_slice, 2)
    trend_closes = [candle.close for candle in trend_slice]
    setup_closes = [candle.close for candle in setup_slice]
    ema_50_4h = ema(trend_closes, 50)
    ema_20_1h = ema(setup_closes, 20)
    if ema_50_4h is None or ema_20_1h is None:
        return None
    if trend.bias != "bullish" or trend_slice[-1].close < ema_50_4h:
        return None
    if setup_slice[-1].close < ema_20_1h:
        return None
    trigger = study.analyze_trigger(trigger_slice, candidate.config)
    if not trigger.momentum_close:
        return None
    atr_1h = study.calculate_atr(setup_slice, 14)
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_1h is None or atr_15m is None:
        return None
    support = min(candle.low for candle in setup_slice[-6:])
    risk_plan, _ = study.build_risk_plan(
        current_price,
        support,
        atr_1h,
        atr_15m,
        DEFAULT_STARTING_CASH,
        fee_bps,
        candidate.config,
    )
    return risk_plan


def evaluate_htf_trend_continuation_short(
    candidate: CandidateSpec,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trend_slice) < 80 or len(setup_slice) < 30 or len(trigger_slice) < 20:
        return None
    trend = study.analyze_structure(trend_slice, 2)
    trend_closes = [candle.close for candle in trend_slice]
    setup_closes = [candle.close for candle in setup_slice]
    ema_50_4h = ema(trend_closes, 50)
    ema_20_1h = ema(setup_closes, 20)
    if ema_50_4h is None or ema_20_1h is None:
        return None
    if trend.bias != "bearish" or trend_slice[-1].close > ema_50_4h:
        return None
    if setup_slice[-1].close > ema_20_1h:
        return None
    if not bearish_momentum_close(trigger_slice, candidate.config):
        return None
    stop_loss = max(candle.high for candle in setup_slice[-6:])
    return build_direct_short_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_crash_rebound(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trigger_slice) < 120 or len(setup_slice) < 20:
        return None
    last = trigger_slice[-1]
    previous = trigger_slice[-2]
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_15m is None or atr_15m <= 0.0:
        return None
    flush_atr = (previous.close - last.low) / atr_15m
    candle_range = max(last.high - last.low, 1e-9)
    close_location = (last.close - last.low) / candle_range
    min_flush_atr = float(candidate.params.get("min_flush_atr", 2.5))
    min_close_location = float(candidate.params.get("min_close_location", 0.55))
    if flush_atr < min_flush_atr or close_location < min_close_location:
        return None
    stop_atr_mult = float(candidate.params.get("stop_atr_mult", 0.8))
    stop_loss = min(last.low, min(candle.low for candle in trigger_slice[-4:])) - atr_15m * stop_atr_mult
    return build_direct_long_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_risk_off_london_relief(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trigger_slice) < 120 or len(setup_slice) < 20:
        return None
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_15m is None or atr_15m <= 0.0:
        return None
    last = trigger_slice[-1]
    prior_window = trigger_slice[-int(candidate.params.get("flush_lookback_bars", 12)) - 1 : -1]
    if len(prior_window) < 4:
        return None
    prior_low = min(candle.low for candle in prior_window)
    prior_high = max(candle.high for candle in prior_window)
    candle_range = max(last.high - last.low, 1e-9)
    close_location = (last.close - last.low) / candle_range
    flush_atr = (prior_high - min(last.low, prior_low)) / atr_15m
    min_flush_atr = float(candidate.params.get("min_flush_atr", 1.35))
    min_close_location = float(candidate.params.get("min_close_location", 0.60))
    if flush_atr < min_flush_atr:
        return None
    if last.low > prior_low:
        return None
    if close_location < min_close_location:
        return None
    if candidate.params.get("require_green_close") and last.close <= last.open:
        return None
    reclaim_buffer = atr_15m * float(candidate.params.get("reclaim_buffer_atr", 0.20))
    if last.close < prior_low + reclaim_buffer:
        return None
    stop_atr_mult = float(candidate.params.get("stop_atr_mult", 0.45))
    stop_loss = min(last.low, prior_low) - atr_15m * stop_atr_mult
    return build_direct_long_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_exhaustion_short(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    if len(trigger_slice) < 120 or len(setup_slice) < 20:
        return None
    last = trigger_slice[-1]
    previous = trigger_slice[-2]
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_15m is None or atr_15m <= 0.0:
        return None
    push_atr = (last.high - previous.close) / atr_15m
    candle_range = max(last.high - last.low, 1e-9)
    close_location = (last.close - last.low) / candle_range
    min_push_atr = float(candidate.params.get("min_push_atr", 2.5))
    min_close_location = float(candidate.params.get("min_close_location", 0.80))
    if push_atr < min_push_atr or close_location < min_close_location or last.close <= last.open:
        return None
    stop_atr_mult = float(candidate.params.get("stop_atr_mult", 0.8))
    stop_loss = max(last.high, max(candle.high for candle in trigger_slice[-4:])) + atr_15m * stop_atr_mult
    return build_direct_short_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_breakout_pullback(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
) -> study.RiskPlan | None:
    lookback = int(candidate.params.get("lookback", 48))
    pullback_bars = int(candidate.params.get("pullback_bars", 16))
    if len(trigger_slice) < lookback + pullback_bars + 4 or len(setup_slice) < 20:
        return None
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_15m is None or atr_15m <= 0.0:
        return None
    breakout_level: float | None = None
    search_start = len(trigger_slice) - pullback_bars - 1
    for index in range(search_start, len(trigger_slice) - 1):
        if index < lookback:
            continue
        prior_high = max(candle.high for candle in trigger_slice[index - lookback : index])
        candle = trigger_slice[index]
        if candle.close > prior_high and candle.close > candle.open:
            breakout_level = prior_high
    if breakout_level is None:
        return None
    last = trigger_slice[-1]
    level_buffer = atr_15m * float(candidate.params.get("level_buffer_atr", 0.35))
    if not (
        last.low <= breakout_level + level_buffer
        and last.close > breakout_level
        and last.close > last.open
    ):
        return None
    stop_loss = min(breakout_level - level_buffer, min(candle.low for candle in trigger_slice[-6:]))
    return build_direct_long_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def session_range(
    trigger_slice: list[study.Candle],
    signal_close_time: int,
    range_minutes: int,
    trade_window_hours: int,
) -> tuple[float, float] | None:
    timestamp = time.gmtime(signal_close_time / 1000)
    session_start_hour = 7 if 7 <= timestamp.tm_hour < 12 else 12 if 12 <= timestamp.tm_hour < 16 else 16 if 16 <= timestamp.tm_hour < 22 else None
    if session_start_hour is None:
        return None
    day_start = signal_close_time - (
        (timestamp.tm_hour * 60 + timestamp.tm_min) * 60 + timestamp.tm_sec
    ) * 1000
    session_start = day_start + session_start_hour * 60 * 60_000
    range_end = session_start + range_minutes * 60_000
    trade_end = session_start + trade_window_hours * 60 * 60_000
    if not (range_end < signal_close_time <= trade_end):
        return None
    candles = [candle for candle in trigger_slice if session_start <= candle.open_time < range_end]
    if len(candles) < max(2, range_minutes // 15):
        return None
    return max(candle.high for candle in candles), min(candle.low for candle in candles)


def evaluate_session_trap_long(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
    signal_close_time: int,
) -> study.RiskPlan | None:
    if len(trigger_slice) < 80 or len(setup_slice) < 20:
        return None
    session = session_range(
        trigger_slice,
        signal_close_time,
        int(candidate.params.get("range_minutes", 60)),
        int(candidate.params.get("trade_window_hours", 5)),
    )
    if session is None:
        return None
    _, session_low = session
    last = trigger_slice[-1]
    candle_range = max(last.high - last.low, 1e-9)
    close_location = (last.close - last.low) / candle_range
    if not (last.low < session_low and last.close > session_low and close_location >= 0.55):
        return None
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_15m is None:
        return None
    stop_loss = min(last.low, session_low) - atr_15m * 0.35
    return build_direct_long_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def evaluate_session_trap_short(
    candidate: CandidateSpec,
    current_price: float,
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
    signal_close_time: int,
) -> study.RiskPlan | None:
    if len(trigger_slice) < 80 or len(setup_slice) < 20:
        return None
    session = session_range(
        trigger_slice,
        signal_close_time,
        int(candidate.params.get("range_minutes", 60)),
        int(candidate.params.get("trade_window_hours", 5)),
    )
    if session is None:
        return None
    session_high, _ = session
    last = trigger_slice[-1]
    candle_range = max(last.high - last.low, 1e-9)
    close_location = (last.close - last.low) / candle_range
    if not (last.high > session_high and last.close < session_high and close_location <= 0.45):
        return None
    atr_15m = study.calculate_atr(trigger_slice, 14)
    if atr_15m is None:
        return None
    stop_loss = max(last.high, session_high) + atr_15m * 0.35
    return build_direct_short_risk_plan(current_price, stop_loss, fee_bps, candidate.config)


def passes_regime_filter(
    candidate: CandidateSpec,
    symbol: str,
    signal_close_time: int,
    trigger_slice: list[study.Candle],
    btc_trend_slice: list[study.Candle],
    market_data: dict[str, MarketData],
) -> bool:
    if candidate.regime_filter == "none":
        return True
    if candidate.regime_filter == "btc_bullish":
        return study.analyze_structure(btc_trend_slice, 2).bias == "bullish"
    if candidate.regime_filter == "atr_expansion":
        if len(trigger_slice) < 120:
            return False
        recent_atr = study.calculate_atr(trigger_slice[-30:], 14)
        baseline_atr = study.calculate_atr(trigger_slice[-120:-30], 14)
        return recent_atr is not None and baseline_atr is not None and recent_atr > baseline_atr * 1.10
    if candidate.regime_filter == "volume_70":
        if len(trigger_slice) < 100:
            return False
        threshold = percentile([candle.volume for candle in trigger_slice[-97:-1]], 0.70)
        return threshold is not None and trigger_slice[-1].volume >= threshold
    if candidate.regime_filter == "overlap_session":
        return session_bucket(signal_close_time) == "london_ny_overlap"
    if candidate.regime_filter == "london_session":
        return session_bucket(signal_close_time) == "london"
    if candidate.regime_filter == "london_or_overlap":
        return session_bucket(signal_close_time) in {"london", "london_ny_overlap"}
    if candidate.regime_filter == "overlap_or_new_york":
        return session_bucket(signal_close_time) in {"london_ny_overlap", "new_york"}
    if candidate.regime_filter == "new_york_session":
        return session_bucket(signal_close_time) == "new_york"
    if candidate.regime_filter == "active_session":
        return session_bucket(signal_close_time) in {"london", "london_ny_overlap", "new_york"}
    if candidate.regime_filter == "off_hours":
        return session_bucket(signal_close_time) == "off_hours"
    if candidate.regime_filter == "breadth_60":
        bullish = 0
        checked = 0
        for item in market_data.values():
            trend_slice = closed_trend_slice(item, signal_close_time)
            if len(trend_slice) < 8:
                continue
            checked += 1
            if trend_slice[-1].close > trend_slice[-7].close:
                bullish += 1
        return checked >= 5 and bullish / checked >= 0.60
    raise ValueError(f"Unsupported regime filter: {candidate.regime_filter}")


def estimated_round_trip_fee_r(risk_plan: study.RiskPlan, fee_bps: float) -> float:
    if risk_plan.risk_amount <= 0.0:
        return math.inf
    entry_fee = risk_plan.notional_estimate * fee_bps / 10_000.0
    estimated_exit_fee = risk_plan.suggested_quantity * risk_plan.entry * fee_bps / 10_000.0
    return (entry_fee + estimated_exit_fee) / risk_plan.risk_amount


def latest_funding_bps(
    funding_rows: list[derivatives_data.FundingRate] | None,
    signal_close_time: int,
    max_age_hours: float | None,
) -> float | None:
    if not funding_rows:
        return None
    times = row_times(funding_rows, "funding_time")
    index = bisect.bisect_right(times, signal_close_time) - 1
    if index < 0:
        return None
    funding = funding_rows[index]
    if max_age_hours is not None:
        age_hours = (signal_close_time - funding.funding_time) / (60 * 60 * 1000)
        if age_hours < 0.0 or age_hours > max_age_hours:
            return None
    return funding.funding_rate * 10_000.0


def latest_metric(
    metric_rows: list[derivatives_data.FuturesMetric] | None,
    signal_close_time: int,
    max_age_minutes: float | None,
) -> derivatives_data.FuturesMetric | None:
    if not metric_rows:
        return None
    times = row_times(metric_rows, "timestamp")
    index = bisect.bisect_right(times, signal_close_time) - 1
    if index < 0:
        return None
    metric = metric_rows[index]
    if max_age_minutes is not None:
        age_minutes = (signal_close_time - metric.timestamp) / (60 * 1000)
        if age_minutes < 0.0 or age_minutes > max_age_minutes:
            return None
    return metric


def metric_oi_change_pct(
    metric_rows: list[derivatives_data.FuturesMetric] | None,
    signal_close_time: int,
    lookback_hours: float = 24.0,
    max_age_minutes: float | None = None,
) -> float | None:
    metric = latest_metric(metric_rows, signal_close_time, max_age_minutes)
    if metric is None or not metric_rows:
        return None
    times = row_times(metric_rows, "timestamp")
    previous_time = signal_close_time - int(lookback_hours * 60 * 60 * 1000)
    previous_index = bisect.bisect_right(times, previous_time) - 1
    if previous_index < 0:
        return None
    previous_metric = metric_rows[previous_index]
    return derivatives_data.pct_change(previous_metric.sum_open_interest_value, metric.sum_open_interest_value)


def ai_scorecard_v2(
    candidate: CandidateSpec,
    symbol: str,
    signal_close_time: int,
    trigger_slice: list[study.Candle],
    btc_trend_slice: list[study.Candle],
    risk_plan: study.RiskPlan,
    fee_bps: float,
    funding_rows: list[derivatives_data.FundingRate] | None,
    metric_rows: list[derivatives_data.FuturesMetric] | None,
    market_data: dict[str, MarketData] | None,
) -> tuple[int, dict[str, Any]]:
    score = 0
    components: dict[str, Any] = {}
    disabled_components = ai_scorecard_disabled_components(candidate)
    if disabled_components:
        components["ablated_ai_components"] = sorted(disabled_components)

    session = session_bucket(signal_close_time)
    session_points = {"london_ny_overlap": 2, "london": 1, "new_york": -2, "off_hours": -1}.get(session, 0)
    score += ai_scorecard_component_points(
        components,
        disabled_components,
        "session",
        "session_points",
        session_points,
    )
    components["session"] = session

    fee_drag = estimated_round_trip_fee_r(risk_plan, fee_bps)
    if fee_drag <= 0.35:
        fee_points = 1
    elif fee_drag > 0.45:
        fee_points = -2
    else:
        fee_points = 0
    score += ai_scorecard_component_points(components, disabled_components, "fee", "fee_points", fee_points)
    components["fee_drag_r"] = rounded(fee_drag)

    volume_rank = volume_percentile_rank(trigger_slice)
    if volume_rank is None:
        volume_points = 0
    elif 0.50 <= volume_rank <= 0.90:
        volume_points = 1
    elif volume_rank >= 0.90 or volume_rank < 0.20:
        volume_points = -1
    else:
        volume_points = 0
    score += ai_scorecard_component_points(
        components,
        disabled_components,
        "volume",
        "volume_points",
        volume_points,
    )
    components["volume_percentile_96"] = rounded(volume_rank)

    atr_multiple = atr_expansion_multiple(trigger_slice)
    if atr_multiple is None:
        atr_points = 0
    elif atr_multiple <= 1.10:
        atr_points = 1
    elif atr_multiple >= 1.50:
        atr_points = -1
    else:
        atr_points = 0
    score += ai_scorecard_component_points(components, disabled_components, "atr", "atr_points", atr_points)
    components["atr_expansion_30_vs_90"] = rounded(atr_multiple)

    btc_24h = btc_return_pct(btc_trend_slice, 24.0)
    if btc_24h is None:
        btc_points = 0
    elif -5.0 <= btc_24h <= 5.0:
        btc_points = 1
    elif btc_24h < -10.0:
        btc_points = -2
    elif btc_24h > 10.0:
        btc_points = -1
    else:
        btc_points = 0
    score += ai_scorecard_component_points(components, disabled_components, "btc", "btc_points", btc_points)
    components["btc_return_24h_pct"] = rounded(btc_24h)

    if market_data is not None:
        rs_24h = relative_strength_percentile(symbol, market_data, signal_close_time, 24.0)
        basket_share = basket_positive_share_pct(market_data, signal_close_time, 24.0)
    else:
        rs_24h = None
        basket_share = None
    if rs_24h is None:
        relative_points = 0
    elif rs_24h >= 0.60:
        relative_points = 2
    elif rs_24h <= 0.30:
        relative_points = -2
    else:
        relative_points = 0
    score += ai_scorecard_component_points(
        components,
        disabled_components,
        "relative_strength",
        "relative_strength_points",
        relative_points,
    )
    components["relative_strength_percentile_24h"] = rounded(rs_24h)

    if basket_share is None:
        breadth_points = 0
    elif basket_share < 25.0:
        breadth_points = -1
    elif basket_share > 70.0:
        breadth_points = 1
    else:
        breadth_points = 0
    score += ai_scorecard_component_points(
        components,
        disabled_components,
        "breadth",
        "breadth_points",
        breadth_points,
    )
    components["basket_positive_share_24h_pct"] = rounded(basket_share)

    funding_bps = latest_funding_bps(
        funding_rows,
        signal_close_time,
        float(candidate.params["max_funding_age_hours"]) if "max_funding_age_hours" in candidate.params else None,
    )
    if funding_bps is None:
        funding_points = -2 if candidate.params.get("require_funding_data") else 0
    elif funding_bps >= -1.0:
        funding_points = 2
    elif funding_bps >= -2.0:
        funding_points = 1
    elif funding_bps < -5.0:
        funding_points = -3
    else:
        funding_points = -2
    score += ai_scorecard_component_points(
        components,
        disabled_components,
        "funding",
        "funding_points",
        funding_points,
    )
    components["funding_rate_bps"] = rounded(funding_bps)

    max_metrics_age = (
        float(candidate.params["max_metrics_age_minutes"]) if "max_metrics_age_minutes" in candidate.params else None
    )
    metric = latest_metric(metric_rows, signal_close_time, max_metrics_age)
    if metric is None:
        metric_missing_points = -2 if candidate.params.get("require_metrics_data") else 0
        score += ai_scorecard_component_points(
            components,
            disabled_components,
            "metrics_missing",
            "metrics_missing_points",
            metric_missing_points,
        )
    else:
        taker = metric.sum_taker_long_short_vol_ratio
        if taker >= 1.25:
            taker_points = 2
        elif taker < 1.0:
            taker_points = -1
        else:
            taker_points = 0
        score += ai_scorecard_component_points(
            components,
            disabled_components,
            "taker",
            "taker_points",
            taker_points,
        )
        components["taker_buy_sell_ratio"] = rounded(taker)

        oi_change = metric_oi_change_pct(metric_rows, signal_close_time, 24.0, max_metrics_age)
        if oi_change is None:
            oi_points = 0
        elif -10.0 <= oi_change <= 0.0:
            oi_points = 1
        elif oi_change > 2.0 or oi_change < -15.0:
            oi_points = -1
        else:
            oi_points = 0
        score += ai_scorecard_component_points(components, disabled_components, "oi", "oi_points", oi_points)
        components["metrics_open_interest_24h_change_pct"] = rounded(oi_change)

        global_ratio = metric.count_long_short_ratio
        if global_ratio <= 1.20:
            global_points = 2
        elif global_ratio >= 2.00:
            global_points = -2
        else:
            global_points = 0
        score += ai_scorecard_component_points(
            components,
            disabled_components,
            "global_bias",
            "global_bias_points",
            global_points,
        )
        components["global_account_long_short_ratio"] = rounded(global_ratio)

        top_position = metric.sum_toptrader_long_short_ratio
        if top_position <= 1.40:
            top_position_points = 1
        elif top_position >= 2.00:
            top_position_points = -1
        else:
            top_position_points = 0
        score += ai_scorecard_component_points(
            components,
            disabled_components,
            "top_position",
            "top_position_points",
            top_position_points,
        )
        components["top_trader_position_long_short_ratio"] = rounded(top_position)

    components["ai_score_v2"] = score
    return score, components


def market_feature_diagnostics(
    candidate: CandidateSpec,
    symbol: str,
    signal_close_time: int,
    trigger_slice: list[study.Candle],
    btc_trend_slice: list[study.Candle],
    risk_plan: study.RiskPlan,
    fee_bps: float,
    funding_rows: list[derivatives_data.FundingRate] | None,
    metric_rows: list[derivatives_data.FuturesMetric] | None,
    market_data: dict[str, MarketData] | None,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "fee_drag_r": rounded(estimated_round_trip_fee_r(risk_plan, fee_bps)),
        "stop_pct": rounded(risk_plan.risk_per_unit / risk_plan.entry * 100.0),
        "volume_percentile_96": rounded(volume_percentile_rank(trigger_slice)),
        "atr_expansion_30_vs_90": rounded(atr_expansion_multiple(trigger_slice)),
        "btc_return_24h_pct": rounded(btc_return_pct(btc_trend_slice, 24.0)),
    }
    if market_data is not None:
        diagnostics["basket_positive_share_24h_pct"] = rounded(
            basket_positive_share_pct(market_data, signal_close_time, 24.0)
        )
        diagnostics["relative_strength_percentile_24h"] = rounded(
            relative_strength_percentile(symbol, market_data, signal_close_time, 24.0)
        )
    funding_bps = latest_funding_bps(
        funding_rows,
        signal_close_time,
        float(candidate.params["max_funding_age_hours"]) if "max_funding_age_hours" in candidate.params else None,
    )
    diagnostics["funding_rate_bps"] = rounded(funding_bps)
    max_metrics_age = (
        float(candidate.params["max_metrics_age_minutes"]) if "max_metrics_age_minutes" in candidate.params else None
    )
    metric = latest_metric(metric_rows, signal_close_time, max_metrics_age)
    if metric is not None:
        diagnostics["taker_buy_sell_ratio"] = rounded(metric.sum_taker_long_short_vol_ratio)
        diagnostics["global_account_long_short_ratio"] = rounded(metric.count_long_short_ratio)
        diagnostics["top_trader_account_long_short_ratio"] = rounded(metric.count_toptrader_long_short_ratio)
        diagnostics["top_trader_position_long_short_ratio"] = rounded(metric.sum_toptrader_long_short_ratio)
        diagnostics["metrics_open_interest_24h_change_pct"] = rounded(
            metric_oi_change_pct(metric_rows, signal_close_time, 24.0, max_metrics_age)
        )
    if candidate.params.get("use_ai_scorecard"):
        score, components = ai_scorecard_v2(
            candidate,
            symbol,
            signal_close_time,
            trigger_slice,
            btc_trend_slice,
            risk_plan,
            fee_bps,
            funding_rows,
            metric_rows,
            market_data,
        )
        diagnostics["ai_score_v2"] = score
        diagnostics["ai_score_components"] = components
    return diagnostics


def passes_post_signal_filters(
    candidate: CandidateSpec,
    symbol: str,
    signal_close_time: int,
    trigger_slice: list[study.Candle],
    btc_trend_slice: list[study.Candle],
    risk_plan: study.RiskPlan,
    fee_bps: float,
    funding_rows: list[derivatives_data.FundingRate] | None = None,
    metric_rows: list[derivatives_data.FuturesMetric] | None = None,
    market_data: dict[str, MarketData] | None = None,
) -> bool:
    if candidate.params.get("exclude_btc") and symbol == study.BTC_REFERENCE_SYMBOL:
        return False

    min_hour_utc = candidate.params.get("min_hour_utc")
    max_hour_utc = candidate.params.get("max_hour_utc")
    if min_hour_utc is not None or max_hour_utc is not None:
        hour = time.gmtime(signal_close_time / 1000).tm_hour
        if min_hour_utc is not None and hour < int(min_hour_utc):
            return False
        if max_hour_utc is not None and hour >= int(max_hour_utc):
            return False

    allowed_weekdays = candidate.params.get("allowed_weekdays")
    if allowed_weekdays is not None:
        allowed = {int(item.strip()) for item in str(allowed_weekdays).split(",") if item.strip()}
        if time.gmtime(signal_close_time / 1000).tm_wday not in allowed:
            return False

    excluded_symbols = candidate.params.get("excluded_symbols")
    if excluded_symbols is not None:
        excluded = {item.strip().upper() for item in str(excluded_symbols).split(",") if item.strip()}
        if symbol in excluded:
            return False

    min_stop_pct = candidate.params.get("min_stop_pct")
    if min_stop_pct is not None and risk_plan.risk_per_unit / risk_plan.entry < float(min_stop_pct):
        return False

    max_fee_drag_r = candidate.params.get("max_fee_drag_r")
    if max_fee_drag_r is not None and estimated_round_trip_fee_r(risk_plan, fee_bps) > float(max_fee_drag_r):
        return False

    min_volume_percentile = candidate.params.get("min_volume_percentile")
    if min_volume_percentile is not None:
        if len(trigger_slice) < 100:
            return False
        threshold = percentile([candle.volume for candle in trigger_slice[-97:-1]], float(min_volume_percentile))
        if threshold is None or trigger_slice[-1].volume < threshold:
            return False

    max_volume_percentile = candidate.params.get("max_volume_percentile")
    if max_volume_percentile is not None:
        if len(trigger_slice) < 100:
            return False
        threshold = percentile([candle.volume for candle in trigger_slice[-97:-1]], float(max_volume_percentile))
        if threshold is None or trigger_slice[-1].volume > threshold:
            return False

    min_atr_expansion_multiple = candidate.params.get("min_atr_expansion_multiple")
    if min_atr_expansion_multiple is not None:
        if len(trigger_slice) < 120:
            return False
        recent_atr = study.calculate_atr(trigger_slice[-30:], 14)
        baseline_atr = study.calculate_atr(trigger_slice[-120:-30], 14)
        if (
            recent_atr is None
            or baseline_atr is None
            or recent_atr <= baseline_atr * float(min_atr_expansion_multiple)
        ):
            return False

    max_atr_expansion_multiple = candidate.params.get("max_atr_expansion_multiple")
    if max_atr_expansion_multiple is not None:
        if len(trigger_slice) < 120:
            return False
        recent_atr = study.calculate_atr(trigger_slice[-30:], 14)
        baseline_atr = study.calculate_atr(trigger_slice[-120:-30], 14)
        if (
            recent_atr is None
            or baseline_atr is None
            or recent_atr > baseline_atr * float(max_atr_expansion_multiple)
        ):
            return False

    if candidate.params.get("require_btc_bullish") and study.analyze_structure(btc_trend_slice, 2).bias != "bullish":
        return False

    min_btc_return = candidate.params.get("min_btc_return_pct")
    max_btc_return = candidate.params.get("max_btc_return_pct")
    if min_btc_return is not None or max_btc_return is not None:
        lookback_hours = float(candidate.params.get("btc_return_lookback_hours", 24.0))
        lookback_candles = max(1, int(round(lookback_hours / 4.0)))
        if len(btc_trend_slice) <= lookback_candles:
            return False
        btc_return = derivatives_data.pct_change(
            btc_trend_slice[-lookback_candles - 1].close,
            btc_trend_slice[-1].close,
        )
        if btc_return is None:
            return False
        if min_btc_return is not None and btc_return < float(min_btc_return):
            return False
        if max_btc_return is not None and btc_return > float(max_btc_return):
            return False

    min_relative_strength = candidate.params.get("min_relative_strength_percentile")
    max_relative_strength = candidate.params.get("max_relative_strength_percentile")
    if min_relative_strength is not None or max_relative_strength is not None:
        if market_data is None:
            return False
        lookback_hours = float(candidate.params.get("relative_strength_lookback_hours", 24.0))
        relative_strength = relative_strength_percentile(symbol, market_data, signal_close_time, lookback_hours)
        if relative_strength is None:
            return False
        if min_relative_strength is not None and relative_strength < float(min_relative_strength):
            return False
        if max_relative_strength is not None and relative_strength > float(max_relative_strength):
            return False

    min_basket_positive_share = candidate.params.get("min_basket_positive_share_pct")
    max_basket_positive_share = candidate.params.get("max_basket_positive_share_pct")
    if min_basket_positive_share is not None or max_basket_positive_share is not None:
        if market_data is None:
            return False
        lookback_hours = float(candidate.params.get("basket_breadth_lookback_hours", 24.0))
        basket_share = basket_positive_share_pct(market_data, signal_close_time, lookback_hours)
        if basket_share is None:
            return False
        if min_basket_positive_share is not None and basket_share < float(min_basket_positive_share):
            return False
        if max_basket_positive_share is not None and basket_share > float(max_basket_positive_share):
            return False

    if candidate.params.get("require_overlap_session") and session_bucket(signal_close_time) != "london_ny_overlap":
        return False

    if candidate_needs_funding(candidate):
        max_age_hours = candidate.params.get("max_funding_age_hours")
        funding_bps = latest_funding_bps(
            funding_rows,
            signal_close_time,
            float(max_age_hours) if max_age_hours is not None else None,
        )
        if funding_bps is None:
            return False
        min_funding_bps = candidate.params.get("min_funding_bps")
        if min_funding_bps is not None and funding_bps < float(min_funding_bps):
            return False
        max_funding_bps = candidate.params.get("max_funding_bps")
        if max_funding_bps is not None and funding_bps > float(max_funding_bps):
            return False
        max_abs_funding_bps = candidate.params.get("max_abs_funding_bps")
        if max_abs_funding_bps is not None and abs(funding_bps) > float(max_abs_funding_bps):
            return False

    if candidate_needs_metrics(candidate):
        max_age_minutes = candidate.params.get("max_metrics_age_minutes")
        metric = latest_metric(
            metric_rows,
            signal_close_time,
            float(max_age_minutes) if max_age_minutes is not None else None,
        )
        if metric is None:
            return False

        min_taker = candidate.params.get("min_taker_buy_sell_ratio")
        if min_taker is not None and metric.sum_taker_long_short_vol_ratio < float(min_taker):
            return False
        max_taker = candidate.params.get("max_taker_buy_sell_ratio")
        if max_taker is not None and metric.sum_taker_long_short_vol_ratio > float(max_taker):
            return False

        min_oi_change = candidate.params.get("min_metrics_oi_24h_change_pct")
        max_oi_change = candidate.params.get("max_metrics_oi_24h_change_pct")
        if min_oi_change is not None or max_oi_change is not None:
            lookback_hours = float(candidate.params.get("metrics_oi_change_lookback_hours", 24.0))
            oi_change = metric_oi_change_pct(
                metric_rows,
                signal_close_time,
                lookback_hours,
                float(max_age_minutes) if max_age_minutes is not None else None,
            )
            if oi_change is None:
                return False
            if min_oi_change is not None and oi_change < float(min_oi_change):
                return False
            if max_oi_change is not None and oi_change > float(max_oi_change):
                return False

        min_global = candidate.params.get("min_global_account_long_short_ratio")
        if min_global is not None and metric.count_long_short_ratio < float(min_global):
            return False
        max_global = candidate.params.get("max_global_account_long_short_ratio")
        if max_global is not None and metric.count_long_short_ratio > float(max_global):
            return False

        min_top_account = candidate.params.get("min_top_trader_account_long_short_ratio")
        if min_top_account is not None and metric.count_toptrader_long_short_ratio < float(min_top_account):
            return False
        max_top_account = candidate.params.get("max_top_trader_account_long_short_ratio")
        if max_top_account is not None and metric.count_toptrader_long_short_ratio > float(max_top_account):
            return False

        min_top_position = candidate.params.get("min_top_trader_position_long_short_ratio")
        if min_top_position is not None and metric.sum_toptrader_long_short_ratio < float(min_top_position):
            return False
        max_top_position = candidate.params.get("max_top_trader_position_long_short_ratio")
        if max_top_position is not None and metric.sum_toptrader_long_short_ratio > float(max_top_position):
            return False

    min_ai_score = candidate.params.get("min_ai_score")
    if min_ai_score is not None:
        score, _ = ai_scorecard_v2(
            candidate,
            symbol,
            signal_close_time,
            trigger_slice,
            btc_trend_slice,
            risk_plan,
            fee_bps,
            funding_rows,
            metric_rows,
            market_data,
        )
        if score < int(min_ai_score):
            return False

    return True


def evaluate_candidate_signal(
    candidate: CandidateSpec,
    symbol: str,
    current_price: float,
    trend_slice: list[study.Candle],
    setup_slice: list[study.Candle],
    trigger_slice: list[study.Candle],
    fee_bps: float,
    signal_close_time: int,
) -> study.RiskPlan | None:
    if candidate.signal_kind == "v2_reclaim":
        return evaluate_v2_reclaim(candidate, current_price, trend_slice, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "ema_pullback":
        return evaluate_ema_pullback(candidate, current_price, trend_slice, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "ema_pullback_short":
        return evaluate_ema_pullback_short(candidate, current_price, trend_slice, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "donchian_breakout":
        return evaluate_donchian_breakout(candidate, current_price, trend_slice, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "donchian_breakdown":
        return evaluate_donchian_breakdown(candidate, current_price, trend_slice, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "opening_session_breakout":
        return evaluate_opening_session_breakout(
            candidate,
            current_price,
            setup_slice,
            trigger_slice,
            fee_bps,
            signal_close_time,
        )
    if candidate.signal_kind == "htf_trend_continuation":
        return evaluate_htf_trend_continuation(
            candidate,
            current_price,
            trend_slice,
            setup_slice,
            trigger_slice,
            fee_bps,
        )
    if candidate.signal_kind == "htf_trend_continuation_short":
        return evaluate_htf_trend_continuation_short(
            candidate,
            current_price,
            trend_slice,
            setup_slice,
            trigger_slice,
            fee_bps,
        )
    if candidate.signal_kind == "crash_rebound":
        return evaluate_crash_rebound(candidate, current_price, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "risk_off_london_relief":
        return evaluate_risk_off_london_relief(candidate, current_price, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "exhaustion_short":
        return evaluate_exhaustion_short(candidate, current_price, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "breakout_pullback":
        return evaluate_breakout_pullback(candidate, current_price, setup_slice, trigger_slice, fee_bps)
    if candidate.signal_kind == "session_trap_long":
        return evaluate_session_trap_long(
            candidate,
            current_price,
            setup_slice,
            trigger_slice,
            fee_bps,
            signal_close_time,
        )
    if candidate.signal_kind == "session_trap_short":
        return evaluate_session_trap_short(
            candidate,
            current_price,
            setup_slice,
            trigger_slice,
            fee_bps,
            signal_close_time,
        )
    raise ValueError(f"Unsupported signal kind for {symbol}: {candidate.signal_kind}")


def full_exit_trade(
    opened_at: int,
    risk_plan: study.RiskPlan,
    future_candles: list[study.Candle],
    fee_bps: float,
    target_multiple: float,
    max_bars: int | None = None,
    trail_atr: float | None = None,
) -> study.ReplayTrade:
    candles = future_candles[:max_bars] if max_bars is not None else future_candles
    closed_at = opened_at
    outcome = "timeout"
    exit_price = risk_plan.entry
    bars_held = len(candles)
    stop_loss = risk_plan.stop_loss
    target = risk_plan.entry + risk_plan.risk_per_unit * target_multiple
    highest_high = risk_plan.entry

    for index, candle in enumerate(candles):
        if candle.low <= stop_loss:
            closed_at = candle.open_time + study.interval_millis("15m")
            outcome = "stop_loss" if stop_loss <= risk_plan.entry else "trail_stop"
            exit_price = stop_loss
            bars_held = index + 1
            break
        if candle.high >= target:
            closed_at = candle.open_time + study.interval_millis("15m")
            outcome = "take_profit_2"
            exit_price = target
            bars_held = index + 1
            break
        if trail_atr is not None:
            highest_high = max(highest_high, candle.high)
            stop_loss = max(stop_loss, highest_high - trail_atr)
    else:
        if candles:
            last = candles[-1]
            closed_at = last.open_time + study.interval_millis("15m")
            exit_price = last.close

    gross_r = (exit_price - risk_plan.entry) / risk_plan.risk_per_unit
    fees_paid = (
        risk_plan.notional_estimate * fee_bps / 10_000.0
        + risk_plan.suggested_quantity * exit_price * fee_bps / 10_000.0
    )
    net_r = gross_r - fees_paid / risk_plan.risk_amount
    return study.ReplayTrade(
        opened_at=opened_at,
        closed_at=closed_at,
        outcome=outcome,
        gross_r=gross_r,
        net_r=net_r,
        bars_held=bars_held,
        fees_paid=fees_paid,
    )


def short_full_exit_trade(
    opened_at: int,
    risk_plan: study.RiskPlan,
    future_candles: list[study.Candle],
    fee_bps: float,
    target_multiple: float,
    max_bars: int | None = None,
) -> study.ReplayTrade:
    candles = future_candles[:max_bars] if max_bars is not None else future_candles
    closed_at = opened_at
    outcome = "timeout"
    exit_price = risk_plan.entry
    bars_held = len(candles)
    target = risk_plan.entry - risk_plan.risk_per_unit * target_multiple

    for index, candle in enumerate(candles):
        hit_stop = candle.high >= risk_plan.stop_loss
        hit_target = candle.low <= target
        if hit_stop and hit_target:
            closed_at = candle.open_time + study.interval_millis("15m")
            outcome = "stop_loss"
            exit_price = risk_plan.stop_loss
            bars_held = index + 1
            break
        if hit_stop:
            closed_at = candle.open_time + study.interval_millis("15m")
            outcome = "stop_loss"
            exit_price = risk_plan.stop_loss
            bars_held = index + 1
            break
        if hit_target:
            closed_at = candle.open_time + study.interval_millis("15m")
            outcome = "take_profit_2"
            exit_price = target
            bars_held = index + 1
            break
    else:
        if candles:
            last = candles[-1]
            closed_at = last.open_time + study.interval_millis("15m")
            exit_price = last.close

    gross_r = (risk_plan.entry - exit_price) / risk_plan.risk_per_unit
    fees_paid = (
        risk_plan.notional_estimate * fee_bps / 10_000.0
        + risk_plan.suggested_quantity * exit_price * fee_bps / 10_000.0
    )
    net_r = gross_r - fees_paid / risk_plan.risk_amount
    return study.ReplayTrade(
        opened_at=opened_at,
        closed_at=closed_at,
        outcome=outcome,
        gross_r=gross_r,
        net_r=net_r,
        bars_held=bars_held,
        fees_paid=fees_paid,
    )


def partial_no_be_trade(
    opened_at: int,
    risk_plan: study.RiskPlan,
    future_candles: list[study.Candle],
    fee_bps: float,
) -> study.ReplayTrade:
    closed_at = opened_at
    outcome = "timeout"
    bars_held = len(future_candles)
    fees_paid = risk_plan.notional_estimate * fee_bps / 10_000.0
    half_quantity = risk_plan.suggested_quantity / 2.0
    tp1_hit_index: int | None = None

    for index, candle in enumerate(future_candles):
        if candle.low <= risk_plan.stop_loss and candle.high >= risk_plan.take_profit_1:
            fees_paid += risk_plan.suggested_quantity * risk_plan.stop_loss * fee_bps / 10_000.0
            return study.ReplayTrade(
                opened_at,
                candle.open_time + study.interval_millis("15m"),
                "stop_loss",
                -1.0,
                -1.0 - fees_paid / risk_plan.risk_amount,
                index + 1,
                fees_paid,
            )
        if candle.low <= risk_plan.stop_loss:
            fees_paid += risk_plan.suggested_quantity * risk_plan.stop_loss * fee_bps / 10_000.0
            return study.ReplayTrade(
                opened_at,
                candle.open_time + study.interval_millis("15m"),
                "stop_loss",
                -1.0,
                -1.0 - fees_paid / risk_plan.risk_amount,
                index + 1,
                fees_paid,
            )
        if candle.high >= risk_plan.take_profit_1:
            tp1_hit_index = index
            fees_paid += half_quantity * risk_plan.take_profit_1 * fee_bps / 10_000.0
            break

    if tp1_hit_index is not None:
        for offset, candle in enumerate(future_candles[tp1_hit_index:], start=tp1_hit_index):
            closed_at = candle.open_time + study.interval_millis("15m")
            bars_held = offset + 1
            hit_stop = candle.low <= risk_plan.stop_loss
            hit_tp2 = candle.high >= risk_plan.take_profit_2
            if hit_stop and hit_tp2:
                outcome = "partial_stop"
                gross_r = 0.0
                fees_paid += half_quantity * risk_plan.stop_loss * fee_bps / 10_000.0
                break
            if hit_tp2:
                outcome = "take_profit_2"
                gross_r = 1.5
                fees_paid += half_quantity * risk_plan.take_profit_2 * fee_bps / 10_000.0
                break
            if hit_stop:
                outcome = "partial_stop"
                gross_r = 0.0
                fees_paid += half_quantity * risk_plan.stop_loss * fee_bps / 10_000.0
                break
        else:
            last = future_candles[-1]
            closed_at = last.open_time + study.interval_millis("15m")
            gross_r = 0.5 + 0.5 * ((last.close - risk_plan.entry) / risk_plan.risk_per_unit)
            fees_paid += half_quantity * last.close * fee_bps / 10_000.0
    else:
        last = future_candles[-1]
        closed_at = last.open_time + study.interval_millis("15m")
        gross_r = (last.close - risk_plan.entry) / risk_plan.risk_per_unit
        fees_paid += risk_plan.suggested_quantity * last.close * fee_bps / 10_000.0

    net_r = gross_r - fees_paid / risk_plan.risk_amount
    return study.ReplayTrade(
        opened_at=opened_at,
        closed_at=closed_at,
        outcome=outcome,
        gross_r=gross_r,
        net_r=net_r,
        bars_held=bars_held,
        fees_paid=fees_paid,
    )


def simulate_candidate_trade(
    candidate: CandidateSpec,
    opened_at: int,
    risk_plan: study.RiskPlan,
    future_candles: list[study.Candle],
    fee_bps: float,
    trigger_slice: list[study.Candle],
) -> study.ReplayTrade:
    if candidate.exit_style == "tp1_be_tp2":
        return study.simulate_trade(opened_at, risk_plan, future_candles, fee_bps)
    if candidate.exit_style == "partial_no_be":
        return partial_no_be_trade(opened_at, risk_plan, future_candles, fee_bps)
    if candidate.exit_style == "time_stop":
        return full_exit_trade(
            opened_at,
            risk_plan,
            future_candles,
            fee_bps,
            target_multiple=float(candidate.params.get("target_multiple", 1.5)),
            max_bars=int(candidate.params.get("max_bars", 16)),
        )
    if candidate.exit_style == "short_time_stop":
        return short_full_exit_trade(
            opened_at,
            risk_plan,
            future_candles,
            fee_bps,
            target_multiple=float(candidate.params.get("target_multiple", 1.5)),
            max_bars=int(candidate.params.get("max_bars", 16)),
        )
    if candidate.exit_style == "atr_trail":
        atr_15m = study.calculate_atr(trigger_slice, 14)
        trail_atr = None
        if atr_15m is not None:
            trail_atr = atr_15m * float(candidate.params.get("trail_atr_mult", 2.0))
        return full_exit_trade(
            opened_at,
            risk_plan,
            future_candles,
            fee_bps,
            target_multiple=2.0,
            trail_atr=trail_atr,
        )
    raise ValueError(f"Unsupported exit style: {candidate.exit_style}")


def collect_candidate_trades(
    candidate: CandidateSpec,
    symbol: str,
    data: MarketData,
    market_data: dict[str, MarketData],
    split: SplitSpec,
    forward_candles: int,
    fee_bps: float,
) -> list[TradeRecord]:
    records: list[TradeRecord] = []
    btc_data = market_data[study.BTC_REFERENCE_SYMBOL]
    last_index = min(split.end, len(data.trigger)) - forward_candles - 1
    index = split.start
    while index < last_index:
        signal_candle = data.trigger[index]
        signal_close_time = signal_candle.open_time + study.interval_millis("15m")
        if candidate.use_session_filter and not study.evaluate_session_filter(signal_close_time):
            index += 1
            continue

        trigger_slice = data.trigger[: index + 1]
        setup_slice = closed_setup_slice(data, signal_close_time)
        trend_slice = closed_trend_slice(data, signal_close_time)
        btc_trigger_slice = closed_trigger_slice(btc_data, signal_close_time)
        btc_trend_slice = closed_trend_slice(btc_data, signal_close_time)
        if (
            candidate.use_correlation_filter
            and symbol != study.BTC_REFERENCE_SYMBOL
            and not study.evaluate_correlation_filter(symbol, trigger_slice, btc_trend_slice, btc_trigger_slice)
        ):
            index += 1
            continue
        if not passes_regime_filter(
            candidate,
            symbol,
            signal_close_time,
            trigger_slice,
            btc_trend_slice,
            market_data,
        ):
            index += 1
            continue

        risk_plan = evaluate_candidate_signal(
            candidate,
            symbol,
            signal_candle.close,
            trend_slice,
            setup_slice,
            trigger_slice,
            fee_bps,
            signal_close_time,
        )
        if risk_plan is None:
            index += 1
            continue
        if not passes_post_signal_filters(
            candidate,
            symbol,
            signal_close_time,
            trigger_slice,
            btc_trend_slice,
            risk_plan,
            fee_bps,
            data.funding,
            data.metrics,
            market_data,
        ):
            index += 1
            continue

        future = data.trigger[index + 1 : index + 1 + forward_candles]
        trade = simulate_candidate_trade(
            candidate,
            signal_close_time,
            risk_plan,
            future,
            fee_bps,
            trigger_slice,
        )
        records.append(
            TradeRecord(
                candidate=candidate.name,
                family=candidate.family,
                symbol=symbol,
                split=split.name,
                fold=split.fold,
                opened_at=trade.opened_at,
                closed_at=trade.closed_at,
                outcome=trade.outcome,
                gross_r=trade.gross_r,
                net_r=trade.net_r,
                bars_held=trade.bars_held,
                fees_paid=trade.fees_paid,
                session_bucket=session_bucket(trade.opened_at),
                diagnostics=market_feature_diagnostics(
                    candidate,
                    symbol,
                    signal_close_time,
                    trigger_slice,
                    btc_trend_slice,
                    risk_plan,
                    fee_bps,
                    data.funding,
                    data.metrics,
                    market_data,
                ),
            )
        )
        if candidate.config.serial_mode:
            index += max(1, trade.bars_held)
            continue
        index += 1
    return records


def max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def profit_factor(values: list[float]) -> float:
    gross_profit = sum(value for value in values if value > 0.0)
    gross_loss = abs(sum(value for value in values if value < 0.0))
    if gross_loss <= 1e-12:
        return 999.0 if gross_profit > 0.0 else 0.0
    return gross_profit / gross_loss


def concentration_by_symbol(records: list[TradeRecord]) -> float:
    positive_total = sum(record.net_r for record in records if record.net_r > 0.0)
    if positive_total <= 1e-12:
        return 1.0 if records else 0.0
    by_symbol: dict[str, float] = {}
    for record in records:
        if record.net_r > 0.0:
            by_symbol[record.symbol] = by_symbol.get(record.symbol, 0.0) + record.net_r
    return max(by_symbol.values(), default=0.0) / positive_total


def concentration_by_trade(records: list[TradeRecord]) -> float:
    positive_total = sum(record.net_r for record in records if record.net_r > 0.0)
    if positive_total <= 1e-12:
        return 1.0 if records else 0.0
    return max((record.net_r for record in records), default=0.0) / positive_total


def summarize_records(records: list[TradeRecord]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: (item.opened_at, item.symbol, item.candidate))
    net_values = [record.net_r for record in ordered]
    gross_values = [record.gross_r for record in ordered]
    session_counts: dict[str, int] = {}
    session_net_r: dict[str, float] = {}
    for record in ordered:
        session_counts[record.session_bucket] = session_counts.get(record.session_bucket, 0) + 1
        session_net_r[record.session_bucket] = session_net_r.get(record.session_bucket, 0.0) + record.net_r
    return {
        "executed_trades": len(ordered),
        "gross_total_r": round(sum(gross_values), 4),
        "net_total_r": round(sum(net_values), 4),
        "net_avg_r": round(sum(net_values) / len(net_values), 4) if net_values else 0.0,
        "profit_factor": round(profit_factor(net_values), 4),
        "max_drawdown_r": round(max_drawdown(net_values), 4),
        "tp1_win_rate": round(
            sum(1 for record in ordered if record.outcome in {"take_profit_2", "breakeven", "partial_stop"})
            / len(ordered)
            * 100.0,
            2,
        )
        if ordered
        else 0.0,
        "median_hold_bars": round(statistics.median([record.bars_held for record in ordered]), 2)
        if ordered
        else 0.0,
        "symbol_concentration": round(concentration_by_symbol(ordered), 4),
        "single_trade_concentration": round(concentration_by_trade(ordered), 4),
        "session_breakdown": {
            key: {
                "trades": session_counts[key],
                "net_r": round(session_net_r[key], 4),
            }
            for key in sorted(session_counts)
        },
    }


def evaluate_promotion(
    records: list[TradeRecord],
    fold_metrics: list[dict[str, Any]],
    holdout_metrics: dict[str, Any],
    full_walk_forward: bool,
) -> tuple[bool, list[str]]:
    metrics = summarize_records(records)
    failures: list[str] = []
    folds_positive = sum(1 for item in fold_metrics if item["net_total_r"] > 0.0)
    if not full_walk_forward:
        failures.append("not_full_12000_candle_walk_forward")
    if metrics["executed_trades"] < MIN_PROMOTION_TRADES:
        failures.append(f"executed_trades<{MIN_PROMOTION_TRADES}")
    if metrics["net_avg_r"] < MIN_PROMOTION_NET_AVG_R:
        failures.append(f"net_avg_r<{MIN_PROMOTION_NET_AVG_R}")
    if metrics["profit_factor"] < MIN_PROMOTION_PROFIT_FACTOR:
        failures.append(f"profit_factor<{MIN_PROMOTION_PROFIT_FACTOR}")
    if holdout_metrics["net_total_r"] <= 0.0:
        failures.append("holdout_net_total_r<=0")
    if holdout_metrics["net_avg_r"] < MIN_HOLDOUT_NET_AVG_R:
        failures.append(f"holdout_net_avg_r<{MIN_HOLDOUT_NET_AVG_R}")
    if folds_positive < MIN_POSITIVE_FOLDS:
        failures.append(f"folds_positive<{MIN_POSITIVE_FOLDS}")
    if metrics["max_drawdown_r"] > MAX_PROMOTION_DRAWDOWN_R:
        failures.append(f"max_drawdown_r>{MAX_PROMOTION_DRAWDOWN_R}")
    if metrics["symbol_concentration"] > MAX_SYMBOL_CONCENTRATION:
        failures.append(f"symbol_concentration>{MAX_SYMBOL_CONCENTRATION}")
    if metrics["single_trade_concentration"] > MAX_SINGLE_TRADE_CONCENTRATION:
        failures.append(f"single_trade_concentration>{MAX_SINGLE_TRADE_CONCENTRATION}")
    return not failures, failures


def evaluate_candidate(
    candidate: CandidateSpec,
    symbols: list[str],
    market_data: dict[str, MarketData],
    splits: list[SplitSpec],
    forward_candles: int,
    fee_bps: float,
    full_walk_forward: bool,
) -> dict[str, Any]:
    records: list[TradeRecord] = []
    for split in splits:
        for symbol in symbols:
            records.extend(
                collect_candidate_trades(
                    candidate,
                    symbol,
                    market_data[symbol],
                    market_data,
                    split,
                    forward_candles,
                    fee_bps,
                )
            )

    validation_records = [record for record in records if record.split == "validation"]
    holdout_records = [record for record in records if record.split == "holdout"]
    fold_metrics = []
    validation_fold_ids = [
        split.fold
        for split in splits
        if split.name == "validation" and split.fold is not None
    ]
    for fold in sorted(validation_fold_ids):
        fold_records = [record for record in validation_records if record.fold == fold]
        fold_metrics.append({"fold": fold, **summarize_records(fold_records)})
    validation_metrics = summarize_records(validation_records)
    holdout_metrics = summarize_records(holdout_records)
    oos_metrics = summarize_records(records)
    passed, failures = evaluate_promotion(records, fold_metrics, holdout_metrics, full_walk_forward)
    fold_trade_counts = [int(item["executed_trades"]) for item in fold_metrics]

    return {
        "candidate": candidate.name,
        "family": candidate.family,
        "signal_kind": candidate.signal_kind,
        "exit_style": candidate.exit_style,
        "regime_filter": candidate.regime_filter,
        "passed_promotion_gates": passed,
        "gate_failures": failures,
        "folds_positive": sum(1 for item in fold_metrics if item["net_total_r"] > 0.0),
        "folds_with_trades": sum(1 for item in fold_metrics if int(item["executed_trades"]) > 0),
        "min_validation_fold_trades": min(fold_trade_counts) if fold_trade_counts else 0,
        "validation": validation_metrics,
        "holdout": holdout_metrics,
        "out_of_sample": oos_metrics,
        "folds": fold_metrics,
        "trades_sample": [asdict(record) for record in sorted(records, key=lambda item: item.opened_at)[-20:]],
    }


def evaluate_candidate_job(args: tuple[CandidateSpec, list[str], dict[str, MarketData], list[SplitSpec], int, float, bool]) -> dict[str, Any]:
    return evaluate_candidate(*args)


def candidate_sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, int]:
    oos = item["out_of_sample"]
    holdout = item["holdout"]
    return (
        1.0 if item["passed_promotion_gates"] else 0.0,
        1.0 if int(oos["executed_trades"]) > 0 else 0.0,
        float(oos["net_total_r"]),
        float(holdout["net_total_r"]),
        int(oos["executed_trades"]),
    )


def summarize_family(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    families: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        families.setdefault(str(item["family"]), []).append(item)

    summary: dict[str, dict[str, Any]] = {}
    for family, items in sorted(families.items()):
        best = max(items, key=candidate_sort_key)
        summary[family] = {
            "candidates": len(items),
            "best_candidate": best["candidate"],
            "best_net_total_r": best["out_of_sample"]["net_total_r"],
            "best_net_avg_r": best["out_of_sample"]["net_avg_r"],
            "best_profit_factor": best["out_of_sample"]["profit_factor"],
            "passed": sum(1 for item in items if item["passed_promotion_gates"]),
        }
    return summary


def build_diagnostics(
    results: list[dict[str, Any]],
    universe_selection: UniverseSelection | None,
) -> dict[str, Any]:
    gate_failures: Counter[str] = Counter()
    no_trade_candidates: list[str] = []
    positive_holdout_candidates: list[str] = []
    for item in results:
        gate_failures.update(item["gate_failures"])
        if int(item["out_of_sample"]["executed_trades"]) == 0:
            no_trade_candidates.append(str(item["candidate"]))
        if float(item["holdout"]["net_total_r"]) > 0.0:
            positive_holdout_candidates.append(str(item["candidate"]))

    best_by_avg = sorted(
        results,
        key=lambda item: (
            1.0 if int(item["out_of_sample"]["executed_trades"]) > 0 else 0.0,
            float(item["out_of_sample"]["net_avg_r"]),
            float(item["out_of_sample"]["net_total_r"]),
        ),
        reverse=True,
    )[:5]

    return {
        "passed_count": sum(1 for item in results if item["passed_promotion_gates"]),
        "gate_failure_counts": dict(gate_failures.most_common()),
        "no_trade_candidates": no_trade_candidates,
        "positive_holdout_candidates": positive_holdout_candidates,
        "family_summary": summarize_family(results),
        "best_by_net_avg_r": [
            {
                "candidate": item["candidate"],
                "trades": item["out_of_sample"]["executed_trades"],
                "net_total_r": item["out_of_sample"]["net_total_r"],
                "net_avg_r": item["out_of_sample"]["net_avg_r"],
                "profit_factor": item["out_of_sample"]["profit_factor"],
                "holdout_net_r": item["holdout"]["net_total_r"],
            }
            for item in best_by_avg
        ],
        "universe_selection": asdict(universe_selection) if universe_selection is not None else None,
    }


def append_campaign_log(payload: dict[str, Any], output_path: Path) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    top = payload["summary"][0] if payload["summary"] else None
    promoted = [item["candidate"] for item in payload["summary"] if item["passed_promotion_gates"]]
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lines = [
        "",
        f"### Research campaign {timestamp}",
        "",
        "- Status: `done`",
        "- Scope: `4-week-profitability-campaign`",
        f"- Artifact: `{output_path}`",
        f"- Universe: `{', '.join(payload['universe'])}`",
        f"- Candidates tested: `{len(payload['summary'])}`",
    ]
    diagnostics = payload.get("diagnostics") or {}
    if diagnostics.get("universe_selection"):
        selection = diagnostics["universe_selection"]
        lines.append(
            f"- Universe filter: `profile={selection['profile']}`, `min_quote_volume={selection['min_quote_volume']}`"
        )
    if top is not None:
        oos = top["out_of_sample"]
        lines.extend(
            [
                f"- Top candidate: `{top['candidate']}`",
                f"- Top OOS: `trades={oos['executed_trades']}`, `net_total_r={oos['net_total_r']}`, `net_avg_r={oos['net_avg_r']}`, `pf={oos['profit_factor']}`",
                f"- Top gate status: `{'pass' if top['passed_promotion_gates'] else 'fail'}`",
                f"- Top gate failures: `{', '.join(top['gate_failures']) if top['gate_failures'] else 'none'}`",
            ]
        )
    if diagnostics.get("gate_failure_counts"):
        top_failures = ", ".join(
            f"{key}={value}" for key, value in list(diagnostics["gate_failure_counts"].items())[:5]
        )
        lines.append(f"- Top gate failure counts: `{top_failures}`")
    lines.append(f"- Promoted strategies: `{', '.join(promoted) if promoted else 'none'}`")
    lines.append("")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def build_output_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"research_run_{stamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the 4-week profitability campaign research harness.")
    parser.add_argument("--symbols", nargs="+", default=None, help="Optional explicit symbols. Defaults to top liquid USDT spot symbols.")
    parser.add_argument("--universe-limit", type=int, default=DEFAULT_UNIVERSE_LIMIT)
    parser.add_argument(
        "--universe-profile",
        choices=["strict", "permissive"],
        default="strict",
        help="strict excludes meme/event-driven/non-standard symbols before history checks.",
    )
    parser.add_argument("--min-quote-volume", type=float, default=DEFAULT_MIN_QUOTE_VOLUME)
    parser.add_argument(
        "--allow-excluded-bases",
        action="store_true",
        help="Disable the strict meme/event-driven base blocklist while keeping other symbol hygiene filters.",
    )
    parser.add_argument("--trigger-limit", type=int, default=DEFAULT_TRIGGER_LIMIT)
    parser.add_argument("--forward-candles", type=int, default=DEFAULT_FORWARD_CANDLES)
    parser.add_argument("--fee-bps", type=float, default=study.DEFAULT_FEE_BPS)
    parser.add_argument("--cache-dir", type=Path, default=Path("tmp/research_cache"))
    parser.add_argument("--derivatives-cache-dir", type=Path, default=Path("tmp/derivatives_cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/research_runs"))
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--refresh-derivatives-cache", action="store_true")
    parser.add_argument(
        "--fetch-metrics",
        action="store_true",
        help="Fetch missing Binance Vision metrics for metrics-filter candidates. Default uses cached metrics only.",
    )
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument(
        "--candidate-family",
        action="append",
        default=[],
        help="Evaluate only candidates from this family. Can be repeated.",
    )
    parser.add_argument(
        "--candidate-name",
        action="append",
        default=[],
        help="Evaluate only this candidate name. Can be repeated.",
    )
    parser.add_argument("--workers", type=int, default=1, help="Parallel candidate workers. Use 1 for deterministic low-memory runs.")
    parser.add_argument("--smoke", action="store_true", help="Run a fast top-3/1000-candle sanity pass.")
    parser.add_argument("--no-log", action="store_true", help="Do not append a campaign summary to tmp/strategy_test_log.md.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.smoke:
        args.universe_limit = min(args.universe_limit, 3)
        args.trigger_limit = min(args.trigger_limit, 1_000)
        args.max_candidates = args.max_candidates or 6
        args.min_quote_volume = min(args.min_quote_volume, 10_000_000.0)

    universe_selection: UniverseSelection | None = None
    if args.symbols:
        requested_symbols = [symbol.upper() for symbol in args.symbols]
    else:
        universe_selection = select_top_usdt_symbols(
            args.universe_limit,
            profile=args.universe_profile,
            min_quote_volume=args.min_quote_volume,
            excluded_bases=set() if args.allow_excluded_bases else STRICT_EXCLUDED_BASES,
            oversample=4,
        )
        requested_symbols = universe_selection.symbols
    if study.BTC_REFERENCE_SYMBOL not in requested_symbols:
        requested_symbols = [study.BTC_REFERENCE_SYMBOL, *requested_symbols]
    requested_symbols = list(dict.fromkeys(requested_symbols))

    candidates = build_candidates()
    if args.candidate_family:
        families = set(args.candidate_family)
        candidates = [candidate for candidate in candidates if candidate.family in families]
    if args.candidate_name:
        names = set(args.candidate_name)
        candidates = [candidate for candidate in candidates if candidate.name in names]
    if args.max_candidates is not None:
        candidates = candidates[: args.max_candidates]
    if not candidates:
        print("[error] no candidates selected.", file=sys.stderr)
        return 2
    include_funding = candidates_need_funding(candidates)
    include_metrics = candidates_need_metrics(candidates)

    full_walk_forward = args.trigger_limit >= RESEARCH_CANDLES + HOLDOUT_CANDLES
    splits = build_splits(args.trigger_limit, args.forward_candles)

    market_data: dict[str, MarketData] = {}
    for symbol in requested_symbols:
        if len(market_data) >= args.universe_limit:
            break
        print(f"[fetch] {symbol} trigger={args.trigger_limit}", file=sys.stderr)
        data = fetch_market_data(
            symbol,
            args.trigger_limit,
            args.cache_dir,
            args.refresh_cache,
            derivatives_cache_dir=args.derivatives_cache_dir,
            refresh_derivatives_cache=args.refresh_derivatives_cache,
            include_funding=include_funding,
            include_metrics=include_metrics,
            metrics_cache_only=not args.fetch_metrics,
        )
        if len(data.trigger) < args.trigger_limit:
            print(
                f"[skip] {symbol} insufficient 15m history: {len(data.trigger)} < {args.trigger_limit}",
                file=sys.stderr,
            )
            continue
        market_data[symbol] = data

    symbols = [symbol for symbol in requested_symbols if symbol in market_data][: args.universe_limit]
    if study.BTC_REFERENCE_SYMBOL not in market_data:
        print("[error] BTCUSDT data is required for correlation/regime filters.", file=sys.stderr)
        return 2

    jobs = [
        (
            candidate,
            symbols,
            market_data,
            splits,
            args.forward_candles,
            args.fee_bps,
            full_walk_forward,
        )
        for candidate in candidates
    ]
    results: list[dict[str, Any]] = []
    workers = max(1, min(int(args.workers), len(jobs), os.cpu_count() or 1))
    if workers == 1:
        for job in jobs:
            print(f"[candidate] {job[0].name}", file=sys.stderr)
            results.append(evaluate_candidate_job(job))
    else:
        print(f"[workers] evaluating {len(jobs)} candidates with {workers} processes", file=sys.stderr)
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_name = {executor.submit(evaluate_candidate_job, job): job[0].name for job in jobs}
            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                print(f"[candidate-done] {name}", file=sys.stderr)
                results.append(future.result())

    results.sort(key=candidate_sort_key, reverse=True)
    output_path = args.json_out or build_output_path(args.output_dir)
    diagnostics = build_diagnostics(results, universe_selection)
    payload = {
        "generated_at": int(time.time() * 1000),
        "settings": {
            "trigger_limit": args.trigger_limit,
            "forward_candles": args.forward_candles,
            "fee_bps": args.fee_bps,
            "universe_limit": args.universe_limit,
            "universe_profile": args.universe_profile,
            "min_quote_volume": args.min_quote_volume,
            "workers": workers,
            "full_walk_forward": full_walk_forward,
            "include_funding": include_funding,
            "include_metrics": include_metrics,
            "metrics_cache_only": not args.fetch_metrics,
            "promotion_gates": {
                "min_trades": MIN_PROMOTION_TRADES,
                "min_net_avg_r": MIN_PROMOTION_NET_AVG_R,
                "min_profit_factor": MIN_PROMOTION_PROFIT_FACTOR,
                "min_holdout_net_avg_r": MIN_HOLDOUT_NET_AVG_R,
                "min_positive_folds": MIN_POSITIVE_FOLDS,
                "max_drawdown_r": MAX_PROMOTION_DRAWDOWN_R,
                "max_symbol_concentration": MAX_SYMBOL_CONCENTRATION,
                "max_single_trade_concentration": MAX_SINGLE_TRADE_CONCENTRATION,
            },
        },
        "universe": symbols,
        "splits": [asdict(split) for split in splits],
        "diagnostics": diagnostics,
        "summary": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not args.no_log:
        append_campaign_log(payload, output_path)

    print("\n=== Top candidates ===")
    for item in results[:10]:
        oos = item["out_of_sample"]
        holdout = item["holdout"]
        print(
            f"{item['candidate']:<32} pass={item['passed_promotion_gates']} "
            f"trades={oos['executed_trades']:<4} net={oos['net_total_r']:<8} "
            f"avg={oos['net_avg_r']:<7} pf={oos['profit_factor']:<7} "
            f"dd={oos['max_drawdown_r']:<7} holdout={holdout['net_total_r']}"
        )
    print(f"\nJSON artifact: {output_path}")
    print("\n=== Diagnostics ===")
    print(f"Promotion passes: {diagnostics['passed_count']}")
    top_failures = list(diagnostics["gate_failure_counts"].items())[:5]
    if top_failures:
        print("Top gate failures: " + ", ".join(f"{name}={count}" for name, count in top_failures))
    if universe_selection is not None:
        rejection_text = ", ".join(f"{name}={count}" for name, count in universe_selection.rejections.items())
        print(f"Universe filter: profile={universe_selection.profile} min_quote_volume={universe_selection.min_quote_volume:g}")
        print(f"Universe rejections: {rejection_text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
