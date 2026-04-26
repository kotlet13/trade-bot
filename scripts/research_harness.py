#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import concurrent.futures
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


@dataclass(frozen=True)
class MarketData:
    symbol: str
    trigger: list[study.Candle]
    setup: list[study.Candle]
    trend: list[study.Candle]
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


def fetch_market_data(
    symbol: str,
    trigger_limit: int,
    cache_dir: Path,
    refresh_cache: bool,
) -> MarketData:
    setup_limit = math.ceil(trigger_limit / 4) + 200
    trend_limit = math.ceil(trigger_limit / 16) + 200
    return MarketData(
        symbol=symbol,
        trigger=fetch_cached_candles(cache_dir, symbol, "15m", trigger_limit, refresh_cache),
        setup=fetch_cached_candles(cache_dir, symbol, "1h", setup_limit, refresh_cache),
        trend=fetch_cached_candles(cache_dir, symbol, "4h", trend_limit, refresh_cache),
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
        CandidateSpec("ema_pullback", "benchmark", "ema_pullback", benchmark),
        CandidateSpec("donchian_breakout", "benchmark", "donchian_breakout", benchmark),
        CandidateSpec("opening_session_breakout", "benchmark", "opening_session_breakout", benchmark),
        CandidateSpec("htf_trend_continuation", "benchmark", "htf_trend_continuation", benchmark),
    ]


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
    if candidate.signal_kind == "donchian_breakout":
        return evaluate_donchian_breakout(candidate, current_price, trend_slice, setup_slice, trigger_slice, fee_bps)
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
            target_multiple=1.5,
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
    for fold in sorted({record.fold for record in validation_records if record.fold is not None}):
        fold_records = [record for record in validation_records if record.fold == fold]
        fold_metrics.append({"fold": fold, **summarize_records(fold_records)})
    validation_metrics = summarize_records(validation_records)
    holdout_metrics = summarize_records(holdout_records)
    oos_metrics = summarize_records(records)
    passed, failures = evaluate_promotion(records, fold_metrics, holdout_metrics, full_walk_forward)

    return {
        "candidate": candidate.name,
        "family": candidate.family,
        "signal_kind": candidate.signal_kind,
        "exit_style": candidate.exit_style,
        "regime_filter": candidate.regime_filter,
        "passed_promotion_gates": passed,
        "gate_failures": failures,
        "folds_positive": sum(1 for item in fold_metrics if item["net_total_r"] > 0.0),
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
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/research_runs"))
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=None)
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
    if args.max_candidates is not None:
        candidates = candidates[: args.max_candidates]

    full_walk_forward = args.trigger_limit >= RESEARCH_CANDLES + HOLDOUT_CANDLES
    splits = build_splits(args.trigger_limit, args.forward_candles)

    market_data: dict[str, MarketData] = {}
    for symbol in requested_symbols:
        if len(market_data) >= args.universe_limit:
            break
        print(f"[fetch] {symbol} trigger={args.trigger_limit}", file=sys.stderr)
        data = fetch_market_data(symbol, args.trigger_limit, args.cache_dir, args.refresh_cache)
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
