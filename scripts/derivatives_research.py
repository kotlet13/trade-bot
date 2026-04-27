#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from derivatives_data import (
    FundingRate,
    FuturesMetric,
    OpenInterestStat,
    day_from_ms,
    fetch_daily_metrics,
    fetch_funding_rates,
    fetch_open_interest_hist,
    funding_at_or_before,
    metric_at_or_before,
    pct_change,
)


DEFAULT_SOURCE_ARTIFACT = Path("tmp/research_runs/focused_scale_top3_universe30_20260426.json")
DEFAULT_TRADE_DIAGNOSTICS = Path("tmp/research_runs/near_miss_full_trade_diagnostics_20260427_010625.json")
DEFAULT_CACHE_DIR = Path("tmp/derivatives_cache")
DEFAULT_CANDLE_CACHE_DIR = Path("tmp/research_cache")
DEFAULT_LOG_PATH = Path("tmp/strategy_test_log.md")
MS_PER_HOUR = 60 * 60 * 1000
MS_PER_DAY = 24 * MS_PER_HOUR


def utc_ms(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")


def now_stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def candle_cache_path(cache_dir: Path, symbol: str, interval: str, limit: int) -> Path:
    return cache_dir / f"{symbol}_{interval}_{limit}.json"


def candle_time_range(cache_dir: Path, symbol: str, trigger_limit: int) -> tuple[int, int] | None:
    path = candle_cache_path(cache_dir, symbol, "15m", trigger_limit)
    if not path.exists():
        return None
    try:
        payload = load_json(path)
        candles = payload.get("candles", [])
        open_times = sorted(int(item["open_time"]) for item in candles)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if not open_times:
        return None
    return open_times[0], open_times[-1] + 15 * 60 * 1000


def period_to_ms(period: str) -> int | None:
    if len(period) < 2:
        return None
    unit = period[-1]
    try:
        count = int(period[:-1])
    except ValueError:
        return None
    if count <= 0:
        return None
    if unit == "m":
        return count * 60 * 1000
    if unit == "h":
        return count * MS_PER_HOUR
    if unit == "d":
        return count * MS_PER_DAY
    return None


def rounded(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def summarize_funding(rows: list[FundingRate]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "avg_bps": None,
            "median_bps": None,
            "min_bps": None,
            "max_bps": None,
            "latest_bps": None,
        }
    bps = [row.funding_rate * 10_000.0 for row in rows]
    positives = sum(1 for item in bps if item > 0.0)
    negatives = sum(1 for item in bps if item < 0.0)
    return {
        "count": len(rows),
        "start_utc": utc_ms(rows[0].funding_time),
        "end_utc": utc_ms(rows[-1].funding_time),
        "avg_bps": rounded(statistics.fmean(bps)),
        "median_bps": rounded(statistics.median(bps)),
        "min_bps": rounded(min(bps)),
        "max_bps": rounded(max(bps)),
        "latest_bps": rounded(bps[-1]),
        "positive_share": rounded(positives / len(rows), 4),
        "negative_share": rounded(negatives / len(rows), 4),
        "abs_ge_1bp_count": sum(1 for item in bps if abs(item) >= 1.0),
        "abs_ge_2bp_count": sum(1 for item in bps if abs(item) >= 2.0),
    }


def rolling_pct_changes(rows: list[OpenInterestStat], lookback_rows: int) -> list[float]:
    changes: list[float] = []
    if lookback_rows <= 0:
        return changes
    for index in range(lookback_rows, len(rows)):
        change = pct_change(
            rows[index - lookback_rows].sum_open_interest_value,
            rows[index].sum_open_interest_value,
        )
        if change is not None and math.isfinite(change):
            changes.append(change)
    return changes


def summarize_open_interest(rows: list[OpenInterestStat], period: str) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "latest_value_usdt": None,
            "change_24h_pct": None,
            "change_7d_pct": None,
        }
    interval_ms = period_to_ms(period) or MS_PER_HOUR
    lookback_24h = max(1, round(MS_PER_DAY / interval_ms))
    lookback_7d = max(1, round(7 * MS_PER_DAY / interval_ms))
    latest = rows[-1]
    change_24h = (
        pct_change(rows[-1 - lookback_24h].sum_open_interest_value, latest.sum_open_interest_value)
        if len(rows) > lookback_24h
        else None
    )
    change_7d = (
        pct_change(rows[-1 - lookback_7d].sum_open_interest_value, latest.sum_open_interest_value)
        if len(rows) > lookback_7d
        else None
    )
    rolling_24h = rolling_pct_changes(rows, lookback_24h)
    return {
        "count": len(rows),
        "start_utc": utc_ms(rows[0].timestamp),
        "end_utc": utc_ms(latest.timestamp),
        "latest_open_interest": rounded(latest.sum_open_interest),
        "latest_value_usdt": rounded(latest.sum_open_interest_value, 2),
        "change_24h_pct": rounded(change_24h),
        "change_7d_pct": rounded(change_7d),
        "max_24h_up_pct": rounded(max(rolling_24h), 4) if rolling_24h else None,
        "max_24h_down_pct": rounded(min(rolling_24h), 4) if rolling_24h else None,
        "up_spike_20pct_24h_count": sum(1 for item in rolling_24h if item >= 20.0),
        "down_flush_20pct_24h_count": sum(1 for item in rolling_24h if item <= -20.0),
    }


def summarize_metrics(rows: list[FuturesMetric]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "avg_global_account_ls": None,
            "avg_top_account_ls": None,
            "avg_top_position_ls": None,
            "avg_taker_buy_sell": None,
        }
    return {
        "count": len(rows),
        "start_utc": utc_ms(rows[0].timestamp),
        "end_utc": utc_ms(rows[-1].timestamp),
        "avg_global_account_ls": rounded(statistics.fmean(row.count_long_short_ratio for row in rows)),
        "avg_top_account_ls": rounded(statistics.fmean(row.count_toptrader_long_short_ratio for row in rows)),
        "avg_top_position_ls": rounded(statistics.fmean(row.sum_toptrader_long_short_ratio for row in rows)),
        "avg_taker_buy_sell": rounded(statistics.fmean(row.sum_taker_long_short_vol_ratio for row in rows)),
        "latest_global_account_ls": rounded(rows[-1].count_long_short_ratio),
        "latest_top_account_ls": rounded(rows[-1].count_toptrader_long_short_ratio),
        "latest_top_position_ls": rounded(rows[-1].sum_toptrader_long_short_ratio),
        "latest_taker_buy_sell": rounded(rows[-1].sum_taker_long_short_vol_ratio),
    }


def funding_bucket(bps: float | None) -> str:
    if bps is None:
        return "missing"
    if bps <= -1.0:
        return "<=-1bp"
    if bps < 0.0:
        return "-1..0bp"
    if bps <= 1.0:
        return "0..1bp"
    return ">1bp"


def oi_change_bucket(change_pct: float | None) -> str:
    if change_pct is None:
        return "missing"
    if change_pct <= -10.0:
        return "<=-10%"
    if change_pct < 0.0:
        return "-10..0%"
    if change_pct <= 10.0:
        return "0..10%"
    return ">10%"


def ratio_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 0.80:
        return "<=0.80"
    if value < 1.00:
        return "0.80..1.00"
    if value <= 1.20:
        return "1.00..1.20"
    return ">1.20"


def taker_ratio_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 0.75:
        return "<=0.75"
    if value < 1.25:
        return "0.75..1.25"
    return ">=1.25"


def open_interest_at_or_before(rows: list[OpenInterestStat], timestamp: int) -> OpenInterestStat | None:
    selected: OpenInterestStat | None = None
    for row in rows:
        if row.timestamp > timestamp:
            break
        selected = row
    return selected


def oi_change_before(rows: list[OpenInterestStat], timestamp: int, lookback_ms: int) -> float | None:
    current = open_interest_at_or_before(rows, timestamp)
    previous = open_interest_at_or_before(rows, timestamp - lookback_ms)
    if current is None or previous is None:
        return None
    return pct_change(previous.sum_open_interest_value, current.sum_open_interest_value)


def metric_change_before(rows: list[FuturesMetric], timestamp: int, lookback_ms: int) -> float | None:
    current = metric_at_or_before(rows, timestamp)
    previous = metric_at_or_before(rows, timestamp - lookback_ms)
    if current is None or previous is None:
        return None
    return pct_change(previous.sum_open_interest_value, current.sum_open_interest_value)


def metric_days_for_trades(trades: list[dict[str, Any]]) -> dict[str, set[date]]:
    days_by_symbol: dict[str, set[date]] = defaultdict(set)
    for trade in trades:
        symbol = str(trade.get("symbol", ""))
        if not symbol:
            continue
        opened_at = int(trade.get("opened_at", 0))
        if opened_at <= 0:
            continue
        opened_day = day_from_ms(opened_at)
        days_by_symbol[symbol].add(opened_day)
        days_by_symbol[symbol].add(opened_day - timedelta(days=1))
    return days_by_symbol


def fetch_metrics_for_trade_days(
    trades: list[dict[str, Any]],
    cache_dir: Path,
    refresh_cache: bool,
    errors: dict[str, list[str]],
) -> dict[str, list[FuturesMetric]]:
    metrics_by_symbol: dict[str, list[FuturesMetric]] = {}
    for symbol, days in sorted(metric_days_for_trades(trades).items()):
        rows: list[FuturesMetric] = []
        for day in sorted(days):
            try:
                rows.extend(fetch_daily_metrics(symbol, day, cache_dir, refresh_cache))
            except Exception as exc:
                errors[symbol].append(f"metrics fetch failed for {day.isoformat()}: {exc}")
        deduped = {row.timestamp: row for row in rows}
        metrics_by_symbol[symbol] = [deduped[key] for key in sorted(deduped)]
        if not metrics_by_symbol[symbol]:
            errors[symbol].append("no metrics rows returned")
    return metrics_by_symbol


def summarize_trade_group(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "net_total_r": 0.0,
            "net_avg_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "win_rate": 0.0,
        }
    ordered = sorted(trades, key=lambda item: int(item.get("opened_at", 0)))
    values = [float(item.get("net_r", 0.0)) for item in ordered]
    gains = sum(value for value in values if value > 0.0)
    losses = sum(value for value in values if value < 0.0)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    profit_factor = gains / abs(losses) if losses < 0.0 else (None if gains > 0.0 else 0.0)
    return {
        "trades": len(values),
        "net_total_r": rounded(sum(values)),
        "net_avg_r": rounded(statistics.fmean(values)),
        "profit_factor": rounded(profit_factor),
        "max_drawdown_r": rounded(max_drawdown),
        "win_rate": rounded(sum(1 for value in values if value > 0.0) / len(values), 4),
    }


def group_trades(trades: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get(key, "missing"))].append(trade)
    return {name: summarize_trade_group(rows) for name, rows in sorted(grouped.items())}


def enrich_trades(
    trades: list[dict[str, Any]],
    funding_by_symbol: dict[str, list[FundingRate]],
    open_interest_by_symbol: dict[str, list[OpenInterestStat]],
    metrics_by_symbol: dict[str, list[FuturesMetric]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda item: int(item.get("opened_at", 0))):
        symbol = str(trade.get("symbol", ""))
        opened_at = int(trade.get("opened_at", 0))
        funding = funding_at_or_before(funding_by_symbol.get(symbol, []), opened_at)
        funding_bps = funding.funding_rate * 10_000.0 if funding is not None else None
        oi_change_24h = oi_change_before(open_interest_by_symbol.get(symbol, []), opened_at, MS_PER_DAY)
        oi = open_interest_at_or_before(open_interest_by_symbol.get(symbol, []), opened_at)
        metric = metric_at_or_before(metrics_by_symbol.get(symbol, []), opened_at)
        metric_oi_change_24h = metric_change_before(metrics_by_symbol.get(symbol, []), opened_at, MS_PER_DAY)
        row = dict(trade)
        row["funding_rate_bps"] = rounded(funding_bps)
        row["funding_bucket"] = funding_bucket(funding_bps)
        row["funding_age_hours"] = (
            rounded((opened_at - funding.funding_time) / MS_PER_HOUR, 2) if funding is not None else None
        )
        row["open_interest_value_usdt"] = rounded(oi.sum_open_interest_value, 2) if oi is not None else None
        row["open_interest_age_hours"] = (
            rounded((opened_at - oi.timestamp) / MS_PER_HOUR, 2) if oi is not None else None
        )
        row["open_interest_24h_change_pct"] = rounded(oi_change_24h)
        row["open_interest_24h_bucket"] = oi_change_bucket(oi_change_24h)
        row["metrics_open_interest_value_usdt"] = (
            rounded(metric.sum_open_interest_value, 2) if metric is not None else None
        )
        row["metrics_open_interest_24h_change_pct"] = rounded(metric_oi_change_24h)
        row["metrics_open_interest_24h_bucket"] = oi_change_bucket(metric_oi_change_24h)
        row["metrics_age_minutes"] = (
            rounded((opened_at - metric.timestamp) / (60 * 1000), 2) if metric is not None else None
        )
        row["global_account_long_short_ratio"] = rounded(
            metric.count_long_short_ratio if metric is not None else None
        )
        row["global_account_long_short_bucket"] = ratio_bucket(
            metric.count_long_short_ratio if metric is not None else None
        )
        row["top_trader_account_long_short_ratio"] = rounded(
            metric.count_toptrader_long_short_ratio if metric is not None else None
        )
        row["top_trader_account_long_short_bucket"] = ratio_bucket(
            metric.count_toptrader_long_short_ratio if metric is not None else None
        )
        row["top_trader_position_long_short_ratio"] = rounded(
            metric.sum_toptrader_long_short_ratio if metric is not None else None
        )
        row["top_trader_position_long_short_bucket"] = ratio_bucket(
            metric.sum_toptrader_long_short_ratio if metric is not None else None
        )
        row["taker_buy_sell_ratio"] = rounded(
            metric.sum_taker_long_short_vol_ratio if metric is not None else None
        )
        row["taker_buy_sell_bucket"] = taker_ratio_bucket(
            metric.sum_taker_long_short_vol_ratio if metric is not None else None
        )
        enriched.append(row)
    return enriched


def load_trade_diagnostics(path: Path | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if path is None or not path.exists():
        return None, []
    payload = load_json(path)
    trades = payload.get("trades", [])
    if not isinstance(trades, list):
        return payload, []
    return payload, [trade for trade in trades if isinstance(trade, dict)]


def selected_symbols(source: dict[str, Any], explicit_symbols: list[str] | None) -> list[str]:
    if explicit_symbols:
        seen: set[str] = set()
        symbols: list[str] = []
        for raw in explicit_symbols:
            for item in raw.split(","):
                symbol = item.strip().upper()
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)
        return symbols
    universe = source.get("universe", [])
    if isinstance(universe, list):
        return [str(symbol) for symbol in universe]
    return []


def append_log(path: Path, artifact: Path, source_artifact: Path, trade_diagnostics: Path | None, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    trade_summary = payload.get("trade_context", {}).get("overall", {})
    funding_groups = payload.get("trade_context", {}).get("by_funding_bucket", {})
    best_bucket = None
    if isinstance(funding_groups, dict) and funding_groups:
        best_bucket = max(
            funding_groups.items(),
            key=lambda item: float(item[1].get("net_avg_r", -999.0)) if isinstance(item[1], dict) else -999.0,
        )
    lines = [
        "",
        "",
        f"### Derivatives diagnostics {datetime.now(tz=UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "- Status: `done`",
        f"- Artifact: `{artifact}`",
        f"- Source artifact: `{source_artifact}`",
        f"- Trade diagnostics: `{trade_diagnostics}`" if trade_diagnostics else "- Trade diagnostics: `none`",
        f"- Symbols profiled: `{len(payload.get('symbols', []))}`",
        f"- Funding rows: `{payload.get('totals', {}).get('funding_rows', 0)}`",
        f"- Open-interest rows: `{payload.get('totals', {}).get('open_interest_rows', 0)}`",
        f"- Metrics rows: `{payload.get('totals', {}).get('metrics_rows', 0)}`",
        f"- Enriched trades: `{trade_summary.get('trades', 0)}`",
    ]
    if best_bucket is not None:
        name, metrics = best_bucket
        lines.append(
            "- Best funding bucket by avg R: "
            f"`{name}` with `trades={metrics.get('trades')}`, "
            f"`net_avg_r={metrics.get('net_avg_r')}`, `pf={metrics.get('profit_factor')}`"
        )
    lines.append("- Promoted strategies: `none`")
    path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile Binance derivatives context against research trades.")
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_SOURCE_ARTIFACT)
    parser.add_argument("--trade-diagnostics", type=Path, default=DEFAULT_TRADE_DIAGNOSTICS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--candle-cache-dir", type=Path, default=DEFAULT_CANDLE_CACHE_DIR)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--oi-period", default="1h")
    parser.add_argument("--oi-limit", type=int, default=500)
    parser.add_argument("--skip-metrics", action="store_true")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = load_json(args.source_artifact)
    symbols = selected_symbols(source, args.symbols)
    trigger_limit = int(source.get("settings", {}).get("trigger_limit", 12_000))
    trade_payload, trades = load_trade_diagnostics(args.trade_diagnostics)

    funding_by_symbol: dict[str, list[FundingRate]] = {}
    open_interest_by_symbol: dict[str, list[OpenInterestStat]] = {}
    metrics_by_symbol: dict[str, list[FuturesMetric]] = {}
    funding_summary: dict[str, dict[str, Any]] = {}
    open_interest_summary: dict[str, dict[str, Any]] = {}
    metrics_summary: dict[str, dict[str, Any]] = {}
    candle_ranges: dict[str, dict[str, Any]] = {}
    errors: dict[str, list[str]] = defaultdict(list)

    for symbol in symbols:
        time_range = candle_time_range(args.candle_cache_dir, symbol, trigger_limit)
        if time_range is None:
            errors[symbol].append(f"missing 15m candle cache for trigger_limit={trigger_limit}")
            funding_rows: list[FundingRate] = []
        else:
            start_time, end_time = time_range
            candle_ranges[symbol] = {
                "start_time": start_time,
                "end_time": end_time,
                "start_utc": utc_ms(start_time),
                "end_utc": utc_ms(end_time),
            }
            try:
                funding_rows = fetch_funding_rates(
                    symbol,
                    start_time,
                    end_time,
                    args.cache_dir,
                    refresh_cache=args.refresh_cache,
                )
            except Exception as exc:  # Network/API failures are symbol-local diagnostics.
                errors[symbol].append(f"funding fetch failed: {exc}")
                funding_rows = []
        funding_by_symbol[symbol] = funding_rows
        funding_summary[symbol] = summarize_funding(funding_rows)
        if not funding_rows:
            errors[symbol].append("no funding rows returned")

        try:
            oi_rows = fetch_open_interest_hist(
                symbol,
                args.oi_period,
                args.cache_dir,
                limit=args.oi_limit,
                refresh_cache=args.refresh_cache,
            )
        except Exception as exc:
            errors[symbol].append(f"open interest fetch failed: {exc}")
            oi_rows = []
        open_interest_by_symbol[symbol] = oi_rows
        open_interest_summary[symbol] = summarize_open_interest(oi_rows, args.oi_period)
        if not oi_rows:
            errors[symbol].append("no open-interest rows returned")

    if not args.skip_metrics and trades:
        metrics_by_symbol = fetch_metrics_for_trade_days(trades, args.cache_dir, args.refresh_cache, errors)
    for symbol in symbols:
        metrics_summary[symbol] = summarize_metrics(metrics_by_symbol.get(symbol, []))

    enriched_trades = enrich_trades(trades, funding_by_symbol, open_interest_by_symbol, metrics_by_symbol)
    trade_context = {
        "source_candidate": trade_payload.get("candidate") if trade_payload else None,
        "overall": summarize_trade_group(enriched_trades),
        "by_funding_bucket": group_trades(enriched_trades, "funding_bucket"),
        "by_open_interest_24h_bucket": group_trades(enriched_trades, "open_interest_24h_bucket"),
        "by_metrics_open_interest_24h_bucket": group_trades(enriched_trades, "metrics_open_interest_24h_bucket"),
        "by_global_account_long_short_bucket": group_trades(enriched_trades, "global_account_long_short_bucket"),
        "by_top_trader_account_long_short_bucket": group_trades(
            enriched_trades,
            "top_trader_account_long_short_bucket",
        ),
        "by_top_trader_position_long_short_bucket": group_trades(
            enriched_trades,
            "top_trader_position_long_short_bucket",
        ),
        "by_taker_buy_sell_bucket": group_trades(enriched_trades, "taker_buy_sell_bucket"),
        "by_symbol": group_trades(enriched_trades, "symbol"),
        "trades": enriched_trades,
    }

    output_path = args.json_out or Path(f"tmp/research_runs/derivatives_profile_{now_stamp()}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": int(time.time() * 1000),
        "generated_utc": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "source_artifact": str(args.source_artifact),
        "trade_diagnostics": str(args.trade_diagnostics) if args.trade_diagnostics and args.trade_diagnostics.exists() else None,
        "settings": {
            "trigger_limit": trigger_limit,
            "funding_source": "Binance USD-M /fapi/v1/fundingRate",
            "open_interest_source": "Binance USD-M /futures/data/openInterestHist",
            "open_interest_period": args.oi_period,
            "open_interest_limit": args.oi_limit,
            "metrics_source": "Binance Vision data/futures/um/daily/metrics",
            "metrics_scope": "trade_days_plus_prior_day" if not args.skip_metrics else "skipped",
        },
        "symbols": symbols,
        "totals": {
            "funding_rows": sum(len(rows) for rows in funding_by_symbol.values()),
            "open_interest_rows": sum(len(rows) for rows in open_interest_by_symbol.values()),
            "metrics_rows": sum(len(rows) for rows in metrics_by_symbol.values()),
        },
        "candle_ranges": candle_ranges,
        "funding_summary": funding_summary,
        "open_interest_summary": open_interest_summary,
        "metrics_summary": metrics_summary,
        "trade_context": trade_context,
        "errors": dict(errors),
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if not args.no_log:
        append_log(args.log_path, output_path, args.source_artifact, args.trade_diagnostics, payload)

    print(f"Wrote {output_path}")
    print(
        "Rows: "
        f"funding={payload['totals']['funding_rows']} "
        f"open_interest={payload['totals']['open_interest_rows']} "
        f"metrics={payload['totals']['metrics_rows']} "
        f"trades={trade_context['overall']['trades']}"
    )
    print("Funding buckets:")
    for name, metrics in trade_context["by_funding_bucket"].items():
        print(
            f"  {name}: trades={metrics['trades']} "
            f"net_avg_r={metrics['net_avg_r']} pf={metrics['profit_factor']}"
        )
    print("Open-interest 24h buckets:")
    for name, metrics in trade_context["by_open_interest_24h_bucket"].items():
        print(
            f"  {name}: trades={metrics['trades']} "
            f"net_avg_r={metrics['net_avg_r']} pf={metrics['profit_factor']}"
        )
    print("Metrics global long/short buckets:")
    for name, metrics in trade_context["by_global_account_long_short_bucket"].items():
        print(
            f"  {name}: trades={metrics['trades']} "
            f"net_avg_r={metrics['net_avg_r']} pf={metrics['profit_factor']}"
        )
    print("Metrics taker buy/sell buckets:")
    for name, metrics in trade_context["by_taker_buy_sell_bucket"].items():
        print(
            f"  {name}: trades={metrics['trades']} "
            f"net_avg_r={metrics['net_avg_r']} pf={metrics['profit_factor']}"
        )
    if errors:
        print(f"Symbol warnings: {len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
