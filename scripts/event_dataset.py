#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import derivatives_research
import research_harness as harness
import strategy_study as study


DEFAULT_SOURCE_ARTIFACT = Path("tmp/research_runs/focused_scale_top3_universe30_20260426.json")
DEFAULT_CANDIDATE_NAMES = [
    "v2_reclaim_active_time_stop_no_corr_no_btc",
    "v2_reclaim_active_time_stop_moderate_no_btc",
    "v2_reclaim_active_time_stop_base_no_btc",
]
DEFAULT_CACHE_DIR = Path("tmp/research_cache")
DEFAULT_DERIVATIVES_CACHE_DIR = Path("tmp/derivatives_cache")
DEFAULT_OUTPUT_DIR = Path("tmp/research_runs")


def rounded(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


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
    if study.BTC_REFERENCE_SYMBOL not in symbols:
        symbols.insert(0, study.BTC_REFERENCE_SYMBOL)
    return symbols[:universe_limit]


def build_segments(trigger_limit: int, chunk_size: int, forward_candles: int) -> list[harness.SplitSpec]:
    segments: list[harness.SplitSpec] = []
    segment_index = 1
    for start in range(0, trigger_limit, chunk_size):
        end = min(trigger_limit, start + chunk_size)
        if end - start <= forward_candles + 1:
            continue
        segments.append(
            harness.SplitSpec(
                name=f"segment_{segment_index:02d}",
                start=start,
                end=end,
                fold=segment_index,
            )
        )
        segment_index += 1
    return segments


def percentile_rank(values: list[float], current: float) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value <= current) / len(values)


def atr_expansion(trigger_slice: list[study.Candle]) -> float | None:
    if len(trigger_slice) < 120:
        return None
    recent_atr = study.calculate_atr(trigger_slice[-30:], 14)
    baseline_atr = study.calculate_atr(trigger_slice[-120:-30], 14)
    if recent_atr is None or baseline_atr is None or baseline_atr <= 0.0:
        return None
    return recent_atr / baseline_atr


def volume_percentile(trigger_slice: list[study.Candle]) -> float | None:
    if len(trigger_slice) < 100:
        return None
    return percentile_rank([candle.volume for candle in trigger_slice[-97:-1]], trigger_slice[-1].volume)


def candidate_lookup(names: list[str]) -> list[harness.CandidateSpec]:
    candidates_by_name = {candidate.name: candidate for candidate in harness.build_candidates()}
    missing = [name for name in names if name not in candidates_by_name]
    if missing:
        raise ValueError(f"Unknown candidate names: {', '.join(missing)}")
    return [candidates_by_name[name] for name in names]


def collect_detailed_events(
    candidate: harness.CandidateSpec,
    symbol: str,
    data: harness.MarketData,
    market_data: dict[str, harness.MarketData],
    split: harness.SplitSpec,
    forward_candles: int,
    fee_bps: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
        setup_slice = harness.closed_setup_slice(data, signal_close_time)
        trend_slice = harness.closed_trend_slice(data, signal_close_time)
        btc_trigger_slice = harness.closed_trigger_slice(btc_data, signal_close_time)
        btc_trend_slice = harness.closed_trend_slice(btc_data, signal_close_time)
        if (
            candidate.use_correlation_filter
            and symbol != study.BTC_REFERENCE_SYMBOL
            and not study.evaluate_correlation_filter(symbol, trigger_slice, btc_trend_slice, btc_trigger_slice)
        ):
            index += 1
            continue
        if not harness.passes_regime_filter(candidate, symbol, signal_close_time, trigger_slice, btc_trend_slice, market_data):
            index += 1
            continue

        risk_plan = harness.evaluate_candidate_signal(
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
        if not harness.passes_post_signal_filters(
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
        trade = harness.simulate_candidate_trade(candidate, signal_close_time, risk_plan, future, fee_bps, trigger_slice)
        estimated_fee_drag = harness.estimated_round_trip_fee_r(risk_plan, fee_bps)
        diagnostics = harness.market_feature_diagnostics(
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
        )
        row = {
            "candidate": candidate.name,
            "family": candidate.family,
            "symbol": symbol,
            "split": split.name,
            "fold": split.fold,
            "segment": split.name,
            "segment_index": split.fold,
            "opened_at": trade.opened_at,
            "closed_at": trade.closed_at,
            "session": harness.session_bucket(trade.opened_at),
            "session_bucket": harness.session_bucket(trade.opened_at),
            "outcome": trade.outcome,
            "gross_r": rounded(trade.gross_r),
            "net_r": rounded(trade.net_r),
            "bars_held": trade.bars_held,
            "fees_paid": rounded(trade.fees_paid, 6),
            "fee_drag_r": rounded(estimated_fee_drag),
            "actual_fee_drag_r": rounded(trade.gross_r - trade.net_r),
            "stop_pct": rounded(risk_plan.risk_per_unit / risk_plan.entry * 100.0),
            "estimated_round_trip_fee_r": rounded(estimated_fee_drag),
            "volume_percentile_96": rounded(volume_percentile(trigger_slice)),
            "atr_expansion_30_vs_90": rounded(atr_expansion(trigger_slice)),
            "btc_return_24h_pct": diagnostics.get("btc_return_24h_pct"),
            "basket_positive_share_24h_pct": diagnostics.get("basket_positive_share_24h_pct"),
            "relative_strength_percentile_24h": diagnostics.get("relative_strength_percentile_24h"),
            "ai_score_v2": diagnostics.get("ai_score_v2"),
        }
        if diagnostics.get("funding_rate_bps") is not None:
            row["funding_rate_bps"] = diagnostics["funding_rate_bps"]
        if diagnostics.get("metrics_open_interest_24h_change_pct") is not None:
            row["metrics_open_interest_24h_change_pct"] = diagnostics["metrics_open_interest_24h_change_pct"]
        if diagnostics.get("global_account_long_short_ratio") is not None:
            row["global_account_long_short_ratio"] = diagnostics["global_account_long_short_ratio"]
        if diagnostics.get("top_trader_account_long_short_ratio") is not None:
            row["top_trader_account_long_short_ratio"] = diagnostics["top_trader_account_long_short_ratio"]
        if diagnostics.get("top_trader_position_long_short_ratio") is not None:
            row["top_trader_position_long_short_ratio"] = diagnostics["top_trader_position_long_short_ratio"]
        if diagnostics.get("taker_buy_sell_ratio") is not None:
            row["taker_buy_sell_ratio"] = diagnostics["taker_buy_sell_ratio"]
        rows.append(row)
        if candidate.config.serial_mode:
            index += max(1, trade.bars_held)
            continue
        index += 1
    return rows


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: (item["opened_at"], item["symbol"], item["candidate"])):
        key = (
            event["candidate"],
            event["symbol"],
            event["opened_at"],
            event["closed_at"],
            event["outcome"],
            event["net_r"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def build_output_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"event_dataset_{stamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a larger candidate-event dataset for predictive research.")
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_SOURCE_ARTIFACT)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--candidate-name", action="append", default=[])
    parser.add_argument("--trigger-limit", type=int, default=harness.DEFAULT_TRIGGER_LIMIT)
    parser.add_argument("--universe-limit", type=int, default=24)
    parser.add_argument("--forward-candles", type=int, default=harness.DEFAULT_FORWARD_CANDLES)
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument(
        "--research-splits",
        action="store_true",
        help="Use the same validation/holdout splits as the promotion harness.",
    )
    parser.add_argument("--fee-bps", type=float, default=study.DEFAULT_FEE_BPS)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--derivatives-cache-dir", type=Path, default=DEFAULT_DERIVATIVES_CACHE_DIR)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--refresh-derivatives-cache", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = load_json(args.source_artifact)
    symbols = selected_symbols(source, args.symbols, args.universe_limit)
    candidate_names = args.candidate_name or DEFAULT_CANDIDATE_NAMES
    candidates = candidate_lookup(candidate_names)
    include_funding = True
    include_metrics = harness.candidates_need_metrics(candidates)

    market_data: dict[str, harness.MarketData] = {}
    for symbol in symbols:
        print(f"[fetch] {symbol} trigger={args.trigger_limit}", flush=True)
        data = harness.fetch_market_data(
            symbol,
            args.trigger_limit,
            args.cache_dir,
            args.refresh_cache,
            derivatives_cache_dir=args.derivatives_cache_dir,
            refresh_derivatives_cache=args.refresh_derivatives_cache,
            include_funding=include_funding,
            include_metrics=include_metrics,
        )
        if len(data.trigger) < args.trigger_limit:
            print(f"[skip] {symbol} insufficient history {len(data.trigger)} < {args.trigger_limit}", flush=True)
            continue
        market_data[symbol] = data
    if study.BTC_REFERENCE_SYMBOL not in market_data:
        raise SystemExit("[error] BTCUSDT data is required.")
    symbols = [symbol for symbol in symbols if symbol in market_data]
    segments = (
        harness.build_splits(args.trigger_limit, args.forward_candles)
        if args.research_splits
        else build_segments(args.trigger_limit, args.chunk_size, args.forward_candles)
    )

    events: list[dict[str, Any]] = []
    for candidate in candidates:
        print(f"[candidate] {candidate.name}", flush=True)
        for split in segments:
            for symbol in symbols:
                rows = collect_detailed_events(
                    candidate,
                    symbol,
                    market_data[symbol],
                    market_data,
                    split,
                    args.forward_candles,
                    args.fee_bps,
                )
                events.extend(rows)
    events = dedupe_events(events)

    errors: dict[str, list[str]] = defaultdict(list)
    funding_by_symbol = {symbol: data.funding for symbol, data in market_data.items()}
    metrics_by_symbol = derivatives_research.fetch_metrics_for_trade_days(
        events,
        args.derivatives_cache_dir,
        args.refresh_derivatives_cache,
        errors,
    )
    enriched_events = derivatives_research.enrich_trades(events, funding_by_symbol, {}, metrics_by_symbol)

    output_path = args.json_out or build_output_path(args.output_dir)
    payload = {
        "generated_at": int(time.time() * 1000),
        "source_artifact": str(args.source_artifact),
        "settings": {
            "trigger_limit": args.trigger_limit,
            "forward_candles": args.forward_candles,
            "chunk_size": args.chunk_size,
            "research_splits": args.research_splits,
            "fee_bps": args.fee_bps,
            "candidate_names": candidate_names,
            "note": "Research dataset only; not a promotion artifact and not paper-trading eligible.",
        },
        "symbols": symbols,
        "segments": [asdict(segment) for segment in segments],
        "totals": {
            "events": len(enriched_events),
            "metrics_rows": sum(len(rows) for rows in metrics_by_symbol.values()),
        },
        "trade_context": {
            "source_candidate": "multi_candidate_event_dataset",
            "overall": derivatives_research.summarize_trade_group(enriched_events),
            "by_candidate": derivatives_research.group_trades(enriched_events, "candidate"),
            "by_split": derivatives_research.group_trades(enriched_events, "split"),
            "by_segment": derivatives_research.group_trades(enriched_events, "segment"),
            "by_funding_bucket": derivatives_research.group_trades(enriched_events, "funding_bucket"),
            "by_metrics_open_interest_24h_bucket": derivatives_research.group_trades(
                enriched_events,
                "metrics_open_interest_24h_bucket",
            ),
            "by_global_account_long_short_bucket": derivatives_research.group_trades(
                enriched_events,
                "global_account_long_short_bucket",
            ),
            "by_taker_buy_sell_bucket": derivatives_research.group_trades(enriched_events, "taker_buy_sell_bucket"),
            "trades": enriched_events,
        },
        "errors": dict(errors),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Events: {len(enriched_events)}")
    print(f"Overall: {payload['trade_context']['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
