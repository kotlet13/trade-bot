#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import derivatives_data


DEFAULT_SOURCE_ARTIFACT = Path("tmp/research_runs/focused_scale_top3_universe30_20260426.json")
DEFAULT_CANDLE_CACHE_DIR = Path("tmp/research_cache")
DEFAULT_DERIVATIVES_CACHE_DIR = Path("tmp/derivatives_cache")
DEFAULT_OUTPUT_DIR = Path("tmp/research_runs")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_symbols(source: dict[str, Any], explicit_symbols: list[str] | None, universe_limit: int) -> list[str]:
    if explicit_symbols:
        raw_symbols = explicit_symbols
    else:
        raw_symbols = [str(symbol) for symbol in source.get("universe", [])]
    symbols: list[str] = []
    for raw in raw_symbols:
        for item in str(raw).split(","):
            symbol = item.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols[:universe_limit]


def candle_cache_path(cache_dir: Path, symbol: str, interval: str, limit: int) -> Path:
    return cache_dir / f"{symbol}_{interval}_{limit}.json"


def candle_time_range(cache_dir: Path, symbol: str, trigger_limit: int) -> tuple[int, int] | None:
    path = candle_cache_path(cache_dir, symbol, "15m", trigger_limit)
    if not path.exists():
        return None
    try:
        payload = load_json(path)
        open_times = sorted(int(item["open_time"]) for item in payload.get("candles", []))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if not open_times:
        return None
    return open_times[0], open_times[-1] + 15 * 60 * 1000


def metric_days(start_time: int, end_time: int) -> list[Any]:
    current = derivatives_data.day_from_ms(start_time)
    end_day = derivatives_data.day_from_ms(end_time)
    days = []
    while current <= end_day:
        days.append(current)
        current += timedelta(days=1)
    return days


def build_output_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"metrics_backfill_{stamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Binance Vision USD-M daily metrics caches.")
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_SOURCE_ARTIFACT)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--universe-limit", type=int, default=24)
    parser.add_argument("--skip-first", type=int, default=0)
    parser.add_argument("--trigger-limit", type=int, default=12_000)
    parser.add_argument("--candle-cache-dir", type=Path, default=DEFAULT_CANDLE_CACHE_DIR)
    parser.add_argument("--derivatives-cache-dir", type=Path, default=DEFAULT_DERIVATIVES_CACHE_DIR)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = load_json(args.source_artifact)
    symbols = selected_symbols(source, args.symbols, args.universe_limit)[args.skip_first :]
    output_path = args.json_out or build_output_path(args.output_dir)
    totals = {
        "symbols": len(symbols),
        "requests_attempted": 0,
        "cache_hits": 0,
        "rows": 0,
        "empty_days": 0,
        "missing_candle_cache": 0,
    }
    by_symbol: dict[str, dict[str, Any]] = {}
    errors: dict[str, list[str]] = {}

    for symbol in symbols:
        time_range = candle_time_range(args.candle_cache_dir, symbol, args.trigger_limit)
        if time_range is None:
            totals["missing_candle_cache"] += 1
            errors.setdefault(symbol, []).append("missing candle cache")
            continue
        days = metric_days(*time_range)
        symbol_rows = 0
        symbol_hits = 0
        symbol_requests = 0
        symbol_empty = 0
        for day in days:
            path = derivatives_data.metrics_cache_path(args.derivatives_cache_dir, symbol, day)
            if path.exists() and not args.refresh_cache:
                symbol_hits += 1
                totals["cache_hits"] += 1
                cached = derivatives_data.read_metrics_cache(path) or []
                symbol_rows += len(cached)
                continue
            if args.max_requests is not None and totals["requests_attempted"] >= args.max_requests:
                break
            symbol_requests += 1
            totals["requests_attempted"] += 1
            rows = derivatives_data.fetch_daily_metrics(symbol, day, args.derivatives_cache_dir, args.refresh_cache)
            symbol_rows += len(rows)
            if not rows:
                symbol_empty += 1
                totals["empty_days"] += 1
        totals["rows"] += symbol_rows
        by_symbol[symbol] = {
            "days": len(days),
            "cache_hits": symbol_hits,
            "requests_attempted": symbol_requests,
            "rows": symbol_rows,
            "empty_days": symbol_empty,
        }
        print(
            f"{symbol}: days={len(days)} cache_hits={symbol_hits} "
            f"requests={symbol_requests} rows={symbol_rows} empty={symbol_empty}",
            flush=True,
        )
        if args.max_requests is not None and totals["requests_attempted"] >= args.max_requests:
            break

    payload = {
        "generated_at": int(time.time() * 1000),
        "settings": {
            "source_artifact": str(args.source_artifact),
            "trigger_limit": args.trigger_limit,
            "universe_limit": args.universe_limit,
            "skip_first": args.skip_first,
            "max_requests": args.max_requests,
            "refresh_cache": args.refresh_cache,
        },
        "symbols": symbols,
        "totals": totals,
        "by_symbol": by_symbol,
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Totals: {totals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
