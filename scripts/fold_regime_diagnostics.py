#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import derivatives_data
import research_harness as harness
import strategy_study as study


METRIC_FIELDS = (
    "sum_open_interest_value",
    "count_long_short_ratio",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)


def load_cached_funding_range(
    cache_dir: Path,
    symbol: str,
    start_time: int,
    end_time: int,
) -> list[derivatives_data.FundingRate]:
    rows: list[derivatives_data.FundingRate] = []
    for path in cache_dir.glob(f"{symbol}_funding_*.json"):
        cached = derivatives_data.read_funding_cache(path)
        if cached is not None:
            rows.extend(cached)
    deduped = {row.funding_time: row for row in rows if start_time <= row.funding_time <= end_time}
    return [deduped[key] for key in sorted(deduped)]


def rounded(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def utc_iso(timestamp_ms: int) -> str:
    return dt.datetime.fromtimestamp(timestamp_ms / 1000, tz=dt.UTC).isoformat()


def mean(values: Iterable[float]) -> float | None:
    cleaned = [value for value in values if math.isfinite(value)]
    if not cleaned:
        return None
    return statistics.fmean(cleaned)


def median(values: Iterable[float]) -> float | None:
    cleaned = [value for value in values if math.isfinite(value)]
    if not cleaned:
        return None
    return statistics.median(cleaned)


def percentile(values: Iterable[float], pct: float) -> float | None:
    cleaned = sorted(value for value in values if math.isfinite(value))
    if not cleaned:
        return None
    index = int(round((len(cleaned) - 1) * pct))
    return cleaned[max(0, min(index, len(cleaned) - 1))]


def summarize_values(values: Iterable[float]) -> dict[str, Any]:
    cleaned = [value for value in values if math.isfinite(value)]
    return {
        "count": len(cleaned),
        "mean": rounded(mean(cleaned)),
        "median": rounded(median(cleaned)),
        "p25": rounded(percentile(cleaned, 0.25)),
        "p75": rounded(percentile(cleaned, 0.75)),
        "min": rounded(min(cleaned), 4) if cleaned else None,
        "max": rounded(max(cleaned), 4) if cleaned else None,
    }


def candle_return_pct(candles: list[study.Candle]) -> float | None:
    if not candles:
        return None
    return derivatives_data.pct_change(candles[0].open, candles[-1].close)


def close_returns(candles: list[study.Candle]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(candles, candles[1:]):
        if previous.close > 0.0:
            returns.append((current.close / previous.close - 1.0) * 100.0)
    return returns


def max_drawdown_pct(candles: list[study.Candle]) -> float | None:
    peak: float | None = None
    worst = 0.0
    for candle in candles:
        if peak is None or candle.close > peak:
            peak = candle.close
        if peak and peak > 0.0:
            drawdown = (candle.close / peak - 1.0) * 100.0
            worst = min(worst, drawdown)
    return worst if peak is not None else None


def realized_vol_pct(candles: list[study.Candle]) -> float | None:
    returns = close_returns(candles)
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns)


def average_atr_pct(candles: list[study.Candle], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    true_ranges: list[float] = []
    previous_close = candles[0].close
    for candle in candles[1:]:
        true_range = max(
            candle.high - candle.low,
            abs(candle.high - previous_close),
            abs(candle.low - previous_close),
        )
        if candle.close > 0.0:
            true_ranges.append((true_range / candle.close) * 100.0)
        previous_close = candle.close
    if len(true_ranges) < period:
        return None
    atr_values = [statistics.fmean(true_ranges[index - period : index]) for index in range(period, len(true_ranges) + 1)]
    return statistics.fmean(atr_values)


def slice_candles(candles: list[study.Candle], start_time: int, end_time: int) -> list[study.Candle]:
    return [candle for candle in candles if start_time <= candle.open_time < end_time]


def slice_funding(
    rows: list[derivatives_data.FundingRate],
    start_time: int,
    end_time: int,
) -> list[derivatives_data.FundingRate]:
    return [row for row in rows if start_time <= row.funding_time < end_time]


def slice_metrics(
    rows: list[derivatives_data.FuturesMetric],
    start_time: int,
    end_time: int,
) -> list[derivatives_data.FuturesMetric]:
    return [row for row in rows if start_time <= row.timestamp < end_time]


def funding_bucket_counts(values_bps: list[float]) -> dict[str, int]:
    return {
        "panic_lt_-10bps": sum(1 for value in values_bps if value < -10.0),
        "negative_-10_to_-2bps": sum(1 for value in values_bps if -10.0 <= value < -2.0),
        "slightly_negative_-2_to_0bps": sum(1 for value in values_bps if -2.0 <= value < 0.0),
        "neutral_0_to_1bps": sum(1 for value in values_bps if 0.0 <= value <= 1.0),
        "positive_gt_1bps": sum(1 for value in values_bps if value > 1.0),
    }


def summarize_market_slice(candles: list[study.Candle]) -> dict[str, Any]:
    returns = close_returns(candles)
    positive_bars = sum(1 for value in returns if value > 0.0)
    negative_bars = sum(1 for value in returns if value < 0.0)
    return {
        "bars": len(candles),
        "return_pct": rounded(candle_return_pct(candles)),
        "max_drawdown_pct": rounded(max_drawdown_pct(candles)),
        "realized_15m_vol_pct": rounded(realized_vol_pct(candles)),
        "average_atr_pct": rounded(average_atr_pct(candles)),
        "positive_bar_share_pct": rounded((positive_bars / len(returns)) * 100.0 if returns else None),
        "negative_bar_share_pct": rounded((negative_bars / len(returns)) * 100.0 if returns else None),
    }


def summarize_session_returns(candles: list[study.Candle]) -> dict[str, Any]:
    by_session: dict[str, list[float]] = {}
    for previous, current in zip(candles, candles[1:]):
        if previous.close <= 0.0:
            continue
        session = harness.session_bucket(current.open_time)
        by_session.setdefault(session, []).append((current.close / previous.close - 1.0) * 100.0)
    return {
        session: {
            "bars": len(values),
            "total_return_pct_sum": rounded(sum(values)),
            "avg_bar_return_pct": rounded(mean(values)),
            "positive_bar_share_pct": rounded((sum(1 for value in values if value > 0.0) / len(values)) * 100.0),
        }
        for session, values in sorted(by_session.items())
        if values
    }


def metric_oi_change_pct_at(
    rows: list[derivatives_data.FuturesMetric],
    timestamps: list[int],
    timestamp: int,
    lookback_ms: int,
) -> float | None:
    current_index = bisect.bisect_right(timestamps, timestamp) - 1
    previous_index = bisect.bisect_right(timestamps, timestamp - lookback_ms) - 1
    if current_index < 0 or previous_index < 0:
        return None
    current = rows[current_index]
    previous = rows[previous_index]
    return derivatives_data.pct_change(previous.sum_open_interest_value, current.sum_open_interest_value)


def summarize_metrics(
    all_metrics: dict[str, list[derivatives_data.FuturesMetric]],
    universe: list[str],
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    field_values: dict[str, list[float]] = {field: [] for field in METRIC_FIELDS}
    oi_change_24h: list[float] = []
    oi_change_4h: list[float] = []
    symbols_with_rows: list[str] = []
    missing_symbols: list[str] = []
    lookback_24h = 24 * 60 * 60 * 1000
    lookback_4h = 4 * 60 * 60 * 1000

    for symbol in universe:
        rows = all_metrics.get(symbol, [])
        window_rows = slice_metrics(rows, start_time, end_time)
        if not window_rows:
            missing_symbols.append(symbol)
            continue
        symbols_with_rows.append(symbol)
        timestamps = [row.timestamp for row in rows]
        for row in window_rows:
            for field in METRIC_FIELDS:
                value = getattr(row, field)
                if math.isfinite(value):
                    field_values[field].append(value)
            oi_24h = metric_oi_change_pct_at(rows, timestamps, row.timestamp, lookback_24h)
            if oi_24h is not None:
                oi_change_24h.append(oi_24h)
            oi_4h = metric_oi_change_pct_at(rows, timestamps, row.timestamp, lookback_4h)
            if oi_4h is not None:
                oi_change_4h.append(oi_4h)

    return {
        "symbols_with_rows": len(symbols_with_rows),
        "missing_symbols": missing_symbols,
        "fields": {field: summarize_values(values) for field, values in field_values.items()},
        "oi_value_change_4h_pct": summarize_values(oi_change_4h),
        "oi_value_change_24h_pct": summarize_values(oi_change_24h),
        "taker_buy_pressure_share_pct": rounded(
            (
                sum(1 for value in field_values["sum_taker_long_short_vol_ratio"] if value > 1.0)
                / len(field_values["sum_taker_long_short_vol_ratio"])
            )
            * 100.0
            if field_values["sum_taker_long_short_vol_ratio"]
            else None
        ),
        "global_long_bias_share_pct": rounded(
            (
                sum(1 for value in field_values["count_long_short_ratio"] if value > 1.0)
                / len(field_values["count_long_short_ratio"])
            )
            * 100.0
            if field_values["count_long_short_ratio"]
            else None
        ),
    }


def summarize_funding(
    all_funding: dict[str, list[derivatives_data.FundingRate]],
    universe: list[str],
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    values_bps: list[float] = []
    symbols_with_rows: list[str] = []
    missing_symbols: list[str] = []
    for symbol in universe:
        rows = slice_funding(all_funding.get(symbol, []), start_time, end_time)
        if not rows:
            missing_symbols.append(symbol)
            continue
        symbols_with_rows.append(symbol)
        values_bps.extend(row.funding_rate * 10_000.0 for row in rows)

    bucket_counts = funding_bucket_counts(values_bps)
    return {
        "symbols_with_rows": len(symbols_with_rows),
        "missing_symbols": missing_symbols,
        "funding_bps": summarize_values(values_bps),
        "bucket_counts": bucket_counts,
        "panic_share_pct": rounded(
            (bucket_counts["panic_lt_-10bps"] / len(values_bps)) * 100.0 if values_bps else None
        ),
        "negative_share_pct": rounded(
            (
                (
                    bucket_counts["panic_lt_-10bps"]
                    + bucket_counts["negative_-10_to_-2bps"]
                    + bucket_counts["slightly_negative_-2_to_0bps"]
                )
                / len(values_bps)
            )
            * 100.0
            if values_bps
            else None
        ),
    }


def top_and_bottom_returns(symbol_returns: dict[str, float | None], limit: int = 5) -> dict[str, Any]:
    cleaned = {symbol: value for symbol, value in symbol_returns.items() if value is not None}
    ordered = sorted(cleaned.items(), key=lambda item: item[1])
    return {
        "worst": [{"symbol": symbol, "return_pct": rounded(value)} for symbol, value in ordered[:limit]],
        "best": [{"symbol": symbol, "return_pct": rounded(value)} for symbol, value in ordered[-limit:][::-1]],
    }


def summarize_split(
    split: harness.SplitSpec,
    market: dict[str, harness.MarketData],
    universe: list[str],
) -> dict[str, Any]:
    btc = market["BTCUSDT"]
    start_time = btc.trigger[split.start].open_time
    end_time = btc.trigger[split.end - 1].open_time + study.interval_millis("15m")
    symbol_returns: dict[str, float | None] = {}
    symbol_dd: list[float] = []
    symbol_vol: list[float] = []
    symbols_positive = 0
    symbols_negative = 0

    for symbol in universe:
        candles = slice_candles(market[symbol].trigger, start_time, end_time)
        ret = candle_return_pct(candles)
        symbol_returns[symbol] = ret
        if ret is not None:
            if ret > 0.0:
                symbols_positive += 1
            elif ret < 0.0:
                symbols_negative += 1
        dd = max_drawdown_pct(candles)
        vol = realized_vol_pct(candles)
        if dd is not None:
            symbol_dd.append(dd)
        if vol is not None:
            symbol_vol.append(vol)

    all_funding = {symbol: market[symbol].funding for symbol in universe}
    all_metrics = {symbol: market[symbol].metrics for symbol in universe}
    btc_candles = slice_candles(btc.trigger, start_time, end_time)
    returns = [value for value in symbol_returns.values() if value is not None]

    return {
        "name": split.name,
        "fold": split.fold,
        "start": split.start,
        "end": split.end,
        "start_time": utc_iso(start_time),
        "end_time": utc_iso(end_time - study.interval_millis("15m")),
        "market": {
            "btc": summarize_market_slice(btc_candles),
            "basket_return_pct": summarize_values(returns),
            "basket_drawdown_pct": summarize_values(symbol_dd),
            "basket_realized_15m_vol_pct": summarize_values(symbol_vol),
            "symbols_positive": symbols_positive,
            "symbols_negative": symbols_negative,
            "symbol_returns": top_and_bottom_returns(symbol_returns),
            "btc_session_returns": summarize_session_returns(btc_candles),
        },
        "funding": summarize_funding(all_funding, universe, start_time, end_time),
        "metrics": summarize_metrics(all_metrics, universe, start_time, end_time),
    }


def load_universe_from_artifact(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    universe = payload.get("universe", [])
    if not isinstance(universe, list) or not all(isinstance(symbol, str) for symbol in universe):
        raise ValueError(f"{path} does not contain a string universe list")
    return universe


def load_local_market_data(
    symbol: str,
    trigger_limit: int,
    cache_dir: Path,
    refresh_cache: bool,
    derivatives_cache_dir: Path,
    fetch_metrics: bool,
) -> harness.MarketData:
    trigger = harness.fetch_cached_candles(cache_dir, symbol, "15m", trigger_limit, refresh_cache)
    if not trigger:
        return harness.MarketData(symbol=symbol, trigger=[], setup=[], trend=[])
    start_time = trigger[0].open_time
    end_time = trigger[-1].open_time + study.interval_millis("15m")
    funding = load_cached_funding_range(derivatives_cache_dir, symbol, start_time, end_time)
    metrics = (
        derivatives_data.fetch_metrics(symbol, start_time, end_time, derivatives_cache_dir, refresh_cache=False)
        if fetch_metrics
        else harness.load_cached_metrics_range(derivatives_cache_dir, symbol, start_time, end_time)
    )
    return harness.MarketData(
        symbol=symbol,
        trigger=trigger,
        setup=[],
        trend=[],
        funding=funding,
        metrics=metrics,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare fold-level market, funding, and OI regimes.")
    parser.add_argument(
        "--source-artifact",
        type=Path,
        default=Path("tmp/research_runs/coverage_refinement_universe30_20260427.json"),
        help="Research artifact to reuse the exact universe from.",
    )
    parser.add_argument("--trigger-limit", type=int, default=12_000)
    parser.add_argument("--forward-candles", type=int, default=16)
    parser.add_argument("--cache-dir", type=Path, default=Path("tmp/research_cache"))
    parser.add_argument("--derivatives-cache-dir", type=Path, default=Path("tmp/derivatives_cache"))
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--fetch-metrics", action="store_true", help="Fetch missing Binance Vision metrics instead of cache-only loading.")
    parser.add_argument("--json-out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    universe = load_universe_from_artifact(args.source_artifact)
    if "BTCUSDT" not in universe:
        universe = ["BTCUSDT", *universe]
    market: dict[str, harness.MarketData] = {}
    for index, symbol in enumerate(universe, start=1):
        print(f"[load] {index}/{len(universe)} {symbol}", file=sys.stderr)
        market[symbol] = load_local_market_data(
            symbol,
            args.trigger_limit,
            args.cache_dir,
            args.refresh_cache,
            args.derivatives_cache_dir,
            args.fetch_metrics,
        )
        if len(market[symbol].trigger) < args.trigger_limit:
            raise RuntimeError(f"{symbol} has insufficient trigger candles: {len(market[symbol].trigger)}")

    splits = harness.build_splits(args.trigger_limit, args.forward_candles)
    split_summaries = [summarize_split(split, market, universe) for split in splits]
    payload = {
        "generated_at": int(time.time()),
        "source_artifact": str(args.source_artifact),
        "settings": {
            "trigger_limit": args.trigger_limit,
            "forward_candles": args.forward_candles,
            "cache_dir": str(args.cache_dir),
            "derivatives_cache_dir": str(args.derivatives_cache_dir),
            "metrics_cache_only": not args.fetch_metrics,
        },
        "universe": universe,
        "splits": [asdict(split) for split in splits],
        "summary": split_summaries,
    }
    output_path = args.json_out or Path(
        f"tmp/research_runs/fold_regime_diagnostics_{dt.datetime.now(dt.UTC).strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {output_path}")
    print("split,btc_return,basket_median,funding_median_bps,panic_share,oi_24h_median,taker_buy_share")
    for item in split_summaries:
        label = f"fold_{item['fold']}" if item["fold"] is not None else "holdout"
        print(
            ",".join(
                [
                    label,
                    str(item["market"]["btc"]["return_pct"]),
                    str(item["market"]["basket_return_pct"]["median"]),
                    str(item["funding"]["funding_bps"]["median"]),
                    str(item["funding"]["panic_share_pct"]),
                    str(item["metrics"]["oi_value_change_24h_pct"]["median"]),
                    str(item["metrics"]["taker_buy_pressure_share_pct"]),
                ]
            )
        )


if __name__ == "__main__":
    main()
