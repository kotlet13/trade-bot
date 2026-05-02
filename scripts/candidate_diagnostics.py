#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import research_harness as harness
import strategy_study as study


DEFAULT_CANDIDATES = [
    "regime_abs_oi_funding_not_panic_s7",
    "rs_refine_htf_position_loose_s5",
]


def rounded(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def median(values: list[float]) -> float | None:
    cleaned = [value for value in values if math.isfinite(value)]
    return statistics.median(cleaned) if cleaned else None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def load_artifact_universe(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    universe = payload.get("universe")
    if not isinstance(universe, list) or not all(isinstance(item, str) for item in universe):
        raise ValueError(f"{path} does not contain a string universe list.")
    return list(dict.fromkeys(item.upper() for item in universe))


def parse_csv_symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def build_fill_settings(args: argparse.Namespace, strict: bool | None = None) -> harness.FillSettings:
    strict_fills = args.strict_fills if strict is None else strict
    enabled = not args.no_slippage and (
        strict_fills
        or args.entry_slippage_bps is not None
        or args.stop_slippage_bps is not None
        or args.tp_slippage_bps is not None
    )
    return harness.FillSettings(
        enabled=enabled,
        strict_fills=bool(strict_fills),
        entry_slippage_bps=args.entry_slippage_bps
        if args.entry_slippage_bps is not None
        else (None if strict_fills else 0.0),
        stop_slippage_bps=args.stop_slippage_bps
        if args.stop_slippage_bps is not None
        else (None if strict_fills else 0.0),
        tp_slippage_bps=args.tp_slippage_bps
        if args.tp_slippage_bps is not None
        else (None if strict_fills else 0.0),
    )


def candidate_by_name(names: list[str]) -> list[harness.CandidateSpec]:
    available = {candidate.name: candidate for candidate in harness.build_candidates()}
    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f"Unknown candidate(s): {', '.join(missing)}")
    return [available[name] for name in names]


def choose_universe(args: argparse.Namespace) -> tuple[list[str], dict[str, Any] | None]:
    explicit = parse_csv_symbols(args.symbols)
    if explicit:
        symbols = explicit
        selection = None
    elif args.source_artifact:
        symbols = load_artifact_universe(args.source_artifact)
        selection = {"source_artifact": str(args.source_artifact)}
    else:
        selected = harness.select_top_usdt_symbols(
            args.universe_limit,
            profile=args.universe_profile,
            min_quote_volume=args.min_quote_volume,
            excluded_bases=set() if args.allow_excluded_bases else harness.STRICT_EXCLUDED_BASES,
            oversample=4,
        )
        symbols = selected.symbols
        selection = asdict(selected)
    if study.BTC_REFERENCE_SYMBOL not in symbols:
        symbols = [study.BTC_REFERENCE_SYMBOL, *symbols]
    return list(dict.fromkeys(symbols))[: args.universe_limit], selection


def load_market(
    symbols: list[str],
    candidates: list[harness.CandidateSpec],
    args: argparse.Namespace,
) -> dict[str, harness.MarketData]:
    include_funding = harness.candidates_need_funding(candidates)
    include_metrics = harness.candidates_need_metrics(candidates)
    market_data: dict[str, harness.MarketData] = {}
    for symbol in symbols:
        print(f"[fetch] {symbol} trigger={args.trigger_limit}", file=sys.stderr)
        data = harness.fetch_market_data(
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
            print(f"[skip] {symbol} insufficient 15m history: {len(data.trigger)}", file=sys.stderr)
            continue
        market_data[symbol] = data
    if study.BTC_REFERENCE_SYMBOL not in market_data:
        raise RuntimeError("BTCUSDT data is required for candidate diagnostics.")
    return market_data


def collect_records(
    candidate: harness.CandidateSpec,
    symbols: list[str],
    market_data: dict[str, harness.MarketData],
    splits: list[harness.SplitSpec],
    args: argparse.Namespace,
    fill_settings: harness.FillSettings,
) -> list[harness.TradeRecord]:
    records: list[harness.TradeRecord] = []
    active_symbols = [symbol for symbol in symbols if symbol in market_data]
    for split in splits:
        for symbol in active_symbols:
            records.extend(
                harness.collect_candidate_trades(
                    candidate,
                    symbol,
                    market_data[symbol],
                    market_data,
                    split,
                    args.forward_candles,
                    args.fee_bps,
                    fill_settings,
                )
            )
    return records


def group_records(
    records: list[harness.TradeRecord],
    key_fn: Callable[[harness.TradeRecord], str],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[harness.TradeRecord]] = defaultdict(list)
    for record in records:
        grouped[key_fn(record)].append(record)
    return {key: harness.summarize_records(items) for key, items in sorted(grouped.items())}


def diagnostic_value(record: harness.TradeRecord, key: str) -> float | None:
    value = record.diagnostics.get(key)
    if value is None and isinstance(record.diagnostics.get("ai_score_components"), dict):
        value = record.diagnostics["ai_score_components"].get(key)
    return as_float(value)


def bucket_missing(value: float | None, buckets: list[tuple[str, Callable[[float], bool]]]) -> str:
    if value is None:
        return "missing"
    for name, predicate in buckets:
        if predicate(value):
            return name
    return "other"


def regime_bucket(record: harness.TradeRecord, dimension: str) -> str:
    if dimension == "btc_24h":
        return bucket_missing(
            diagnostic_value(record, "btc_return_24h_pct"),
            [
                ("risk_off_lt_-1.5", lambda value: value < -1.5),
                ("constructive_-1.5_to_3.5", lambda value: -1.5 <= value <= 3.5),
                ("overheated_gt_3.5", lambda value: value > 3.5),
            ],
        )
    if dimension == "breadth":
        return bucket_missing(
            diagnostic_value(record, "basket_positive_share_24h_pct"),
            [
                ("weak_lt_35", lambda value: value < 35.0),
                ("constructive_35_to_80", lambda value: 35.0 <= value <= 80.0),
                ("euphoric_gt_80", lambda value: value > 80.0),
            ],
        )
    if dimension == "funding":
        return bucket_missing(
            diagnostic_value(record, "funding_rate_bps"),
            [
                ("panic_lt_-5bps", lambda value: value < -5.0),
                ("negative_-5_to_-1bps", lambda value: -5.0 <= value < -1.0),
                ("not_panic_ge_-1bps", lambda value: value >= -1.0),
            ],
        )
    if dimension == "oi_24h":
        return bucket_missing(
            diagnostic_value(record, "metrics_open_interest_24h_change_pct"),
            [
                ("collapse_lt_-15", lambda value: value < -15.0),
                ("cooling_-15_to_0", lambda value: -15.0 <= value <= 0.0),
                ("small_expansion_0_to_2", lambda value: 0.0 < value <= 2.0),
                ("hot_expansion_gt_2", lambda value: value > 2.0),
            ],
        )
    if dimension == "global_account":
        return bucket_missing(
            diagnostic_value(record, "global_account_long_short_ratio"),
            [
                ("lte_1.20", lambda value: value <= 1.20),
                ("1.20_to_1.35", lambda value: 1.20 < value <= 1.35),
                ("1.35_to_1.50", lambda value: 1.35 < value <= 1.50),
                ("gt_1.50", lambda value: value > 1.50),
            ],
        )
    if dimension == "top_position":
        return bucket_missing(
            diagnostic_value(record, "top_trader_position_long_short_ratio"),
            [
                ("lte_1.60", lambda value: value <= 1.60),
                ("1.60_to_2.00", lambda value: 1.60 < value <= 2.00),
                ("2.00_to_2.20", lambda value: 2.00 < value <= 2.20),
                ("gt_2.20", lambda value: value > 2.20),
            ],
        )
    if dimension == "taker":
        return bucket_missing(
            diagnostic_value(record, "taker_buy_sell_ratio"),
            [
                ("sell_pressure_lt_1.00", lambda value: value < 1.00),
                ("neutral_1.00_to_1.10", lambda value: 1.00 <= value < 1.10),
                ("buy_1.10_to_1.25", lambda value: 1.10 <= value < 1.25),
                ("strong_buy_gte_1.25", lambda value: value >= 1.25),
            ],
        )
    if dimension == "relative_strength":
        return bucket_missing(
            diagnostic_value(record, "relative_strength_percentile_24h"),
            [
                ("lt_0.60", lambda value: value < 0.60),
                ("0.60_to_0.70", lambda value: 0.60 <= value < 0.70),
                ("0.70_to_0.75", lambda value: 0.70 <= value < 0.75),
                ("gte_0.75", lambda value: value >= 0.75),
            ],
        )
    raise ValueError(f"Unsupported regime dimension: {dimension}")


def diagnostic_distribution(records: list[harness.TradeRecord], key: str) -> dict[str, Any]:
    values = [diagnostic_value(record, key) for record in records]
    cleaned = [value for value in values if value is not None]
    return {
        "count": len(cleaned),
        "median": rounded(median(cleaned)),
        "min": rounded(min(cleaned), 4) if cleaned else None,
        "max": rounded(max(cleaned), 4) if cleaned else None,
    }


def positive_folds(fold_metrics: list[dict[str, Any]]) -> int:
    return sum(1 for item in fold_metrics if float(item.get("net_total_r") or 0.0) > 0.0)


def group_summary_row(name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "trades": metrics["executed_trades"],
        "net_total_r": metrics["net_total_r"],
        "net_avg_r": metrics["net_avg_r"],
        "profit_factor": metrics["profit_factor"],
    }


def bottom_group(groups: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not groups:
        return None
    name, metrics = sorted(
        groups.items(),
        key=lambda item: (
            float(item[1].get("net_total_r") or 0.0),
            item[0],
        ),
    )[0]
    return group_summary_row(name, metrics)


def best_group(groups: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not groups:
        return None
    name, metrics = sorted(
        groups.items(),
        key=lambda item: (
            float(item[1].get("net_total_r") or 0.0),
            item[0],
        ),
        reverse=True,
    )[0]
    return group_summary_row(name, metrics)


def failure_analysis(
    fold_metrics: list[dict[str, Any]],
    by_symbol: dict[str, dict[str, Any]],
    by_session: dict[str, dict[str, Any]],
    holdout_records: list[harness.TradeRecord],
) -> dict[str, Any]:
    holdout_by_symbol = group_records(holdout_records, lambda record: record.symbol)
    holdout = harness.summarize_records(holdout_records)
    holdout_top = best_group(holdout_by_symbol)
    holdout_net = float(holdout.get("net_total_r") or 0.0)
    holdout_top_share = None
    if holdout_top and abs(holdout_net) > 1e-12:
        holdout_top_share = rounded(float(holdout_top["net_total_r"]) / holdout_net)
    worst_fold = None
    if fold_metrics:
        worst_fold = sorted(
            fold_metrics,
            key=lambda item: (
                float(item.get("net_total_r") or 0.0),
                int(item.get("fold") or 0),
            ),
        )[0]
    return {
        "worst_fold": worst_fold,
        "worst_symbol": bottom_group(by_symbol),
        "best_symbol": best_group(by_symbol),
        "worst_session": bottom_group(by_session),
        "best_session": best_group(by_session),
        "holdout_top_symbol": holdout_top,
        "holdout_top_symbol_net_share": holdout_top_share,
        "research_only": True,
    }


def evaluate_records(
    candidate: harness.CandidateSpec,
    records: list[harness.TradeRecord],
    splits: list[harness.SplitSpec],
    full_walk_forward: bool,
) -> dict[str, Any]:
    validation_records = [record for record in records if record.split == "validation"]
    holdout_records = [record for record in records if record.split == "holdout"]
    fold_ids = [split.fold for split in splits if split.name == "validation" and split.fold is not None]
    fold_metrics = [
        {"fold": fold, **harness.summarize_records([record for record in validation_records if record.fold == fold])}
        for fold in sorted(fold_ids)
    ]
    validation = harness.summarize_records(validation_records)
    holdout = harness.summarize_records(holdout_records)
    oos = harness.summarize_records(records)
    passed, failures = harness.evaluate_promotion(records, fold_metrics, holdout, full_walk_forward)
    by_symbol = group_records(records, lambda record: record.symbol)
    by_session = group_records(records, lambda record: record.session_bucket)
    by_outcome = group_records(records, lambda record: record.outcome)
    regime_dimensions = [
        "btc_24h",
        "breadth",
        "funding",
        "oi_24h",
        "global_account",
        "top_position",
        "taker",
        "relative_strength",
    ]
    regime = {
        dimension: group_records(records, lambda record, dim=dimension: regime_bucket(record, dim))
        for dimension in regime_dimensions
    }
    holdout_share = (
        holdout["net_total_r"] / oos["net_total_r"]
        if abs(float(oos.get("net_total_r") or 0.0)) > 1e-12
        else None
    )
    return {
        "candidate": candidate.name,
        "family": candidate.family,
        "signal_kind": candidate.signal_kind,
        "exit_style": candidate.exit_style,
        "regime_filter": candidate.regime_filter,
        "passed_promotion_gates": passed,
        "gate_failures": failures,
        "folds_positive": positive_folds(fold_metrics),
        "out_of_sample": oos,
        "validation": validation,
        "holdout": holdout,
        "holdout_net_share": rounded(holdout_share),
        "folds": fold_metrics,
        "by_symbol": by_symbol,
        "by_session": by_session,
        "by_outcome": by_outcome,
        "failure_analysis": failure_analysis(fold_metrics, by_symbol, by_session, holdout_records),
        "regime_buckets": regime,
        "diagnostic_distributions": {
            key: diagnostic_distribution(records, key)
            for key in [
                "ai_score_v2",
                "btc_return_24h_pct",
                "basket_positive_share_24h_pct",
                "relative_strength_percentile_24h",
                "funding_rate_bps",
                "metrics_open_interest_24h_change_pct",
                "taker_buy_sell_ratio",
                "global_account_long_short_ratio",
                "top_trader_position_long_short_ratio",
            ]
        },
        "trade_count_by_split": dict(Counter(record.split for record in records)),
        "trades_sample": [asdict(record) for record in sorted(records, key=lambda item: item.opened_at)[-20:]],
    }


def strict_fill_delta(
    base: dict[str, Any],
    strict: dict[str, Any],
) -> dict[str, Any]:
    base_oos = base["out_of_sample"]
    strict_oos = strict["out_of_sample"]
    return {
        "strict_candidate": strict["candidate"],
        "trades_delta": int(strict_oos["executed_trades"]) - int(base_oos["executed_trades"]),
        "net_total_r_delta": rounded(float(strict_oos["net_total_r"]) - float(base_oos["net_total_r"])),
        "net_avg_r_delta": rounded(float(strict_oos["net_avg_r"]) - float(base_oos["net_avg_r"])),
        "profit_factor_delta": rounded(float(strict_oos["profit_factor"]) - float(base_oos["profit_factor"])),
        "max_drawdown_r_delta": rounded(float(strict_oos["max_drawdown_r"]) - float(base_oos["max_drawdown_r"])),
        "base_gate_failures": base["gate_failures"],
        "strict_gate_failures": strict["gate_failures"],
    }


def top_groups(groups: dict[str, dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    items = sorted(
        groups.items(),
        key=lambda item: (
            float(item[1].get("net_total_r") or 0.0),
            int(item[1].get("executed_trades") or 0),
        ),
        reverse=True,
    )[:limit]
    return [group_summary_row(name, metrics) for name, metrics in items]


def group_label(group: dict[str, Any] | None) -> str:
    if not group:
        return "n/a"
    return (
        f"{group['name']} trades={group['trades']} "
        f"net={group['net_total_r']}R avg={group['net_avg_r']}R pf={group['profit_factor']}"
    )


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Candidate Diagnostics",
        "",
        f"- Generated: `{payload['generated_at_utc']}`",
        f"- Universe size: `{len(payload['universe'])}`",
        f"- Trigger limit: `{payload['settings']['trigger_limit']}`",
        f"- Forward candles: `{payload['settings']['forward_candles']}`",
        "",
    ]
    for item in payload["candidates"]:
        oos = item["out_of_sample"]
        holdout = item["holdout"]
        lines.extend(
            [
                f"## {item['candidate']}",
                "",
                f"- Gate status: `{'pass' if item['passed_promotion_gates'] else 'fail'}`",
                f"- Gate failures: `{', '.join(item['gate_failures']) if item['gate_failures'] else 'none'}`",
                f"- OOS: `trades={oos['executed_trades']}`, `net={oos['net_total_r']}R`, `avg={oos['net_avg_r']}R`, `pf={oos['profit_factor']}`, `dd={oos['max_drawdown_r']}R`",
                f"- Holdout: `net={holdout['net_total_r']}R`, `avg={holdout['net_avg_r']}R`, `share={item['holdout_net_share']}`",
                f"- Positive folds: `{item['folds_positive']}/5`",
                "",
                "### Folds",
                "",
                "| Fold | Trades | Net R | Avg R | PF | DD |",
                "| ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for fold in item["folds"]:
            lines.append(
                f"| `{fold['fold']}` | `{fold['executed_trades']}` | `{fold['net_total_r']}` "
                f"| `{fold['net_avg_r']}` | `{fold['profit_factor']}` | `{fold['max_drawdown_r']}` |"
            )
        failure = item.get("failure_analysis") or {}
        worst_fold = failure.get("worst_fold") or {}
        lines.extend(
            [
                "",
                "### Failure Analysis",
                "",
                f"- Research only: `{failure.get('research_only', True)}`",
                f"- Worst fold: `{worst_fold.get('fold', 'n/a')}` net `{worst_fold.get('net_total_r', 'n/a')}R` trades `{worst_fold.get('executed_trades', 'n/a')}`",
                f"- Worst symbol: `{group_label(failure.get('worst_symbol'))}`",
                f"- Best symbol: `{group_label(failure.get('best_symbol'))}`",
                f"- Worst session: `{group_label(failure.get('worst_session'))}`",
                f"- Best session: `{group_label(failure.get('best_session'))}`",
                f"- Holdout top symbol: `{group_label(failure.get('holdout_top_symbol'))}` share `{failure.get('holdout_top_symbol_net_share')}`",
            ]
        )
        lines.extend(["", "### Top Symbols", ""])
        for group in top_groups(item["by_symbol"]):
            lines.append(
                f"- `{group['name']}`: trades `{group['trades']}`, net `{group['net_total_r']}R`, avg `{group['net_avg_r']}R`, pf `{group['profit_factor']}`"
            )
        lines.extend(["", "### Sessions", ""])
        for name, metrics in sorted(item["by_session"].items()):
            lines.append(
                f"- `{name}`: trades `{metrics['executed_trades']}`, net `{metrics['net_total_r']}R`, avg `{metrics['net_avg_r']}R`, pf `{metrics['profit_factor']}`"
            )
        lines.extend(["", "### Regime Buckets", ""])
        for dimension, groups in item["regime_buckets"].items():
            best = top_groups(groups, limit=3)
            best_text = "; ".join(
                f"{group['name']} trades={group['trades']} net={group['net_total_r']}R"
                for group in best
            )
            lines.append(f"- `{dimension}`: {best_text if best_text else 'no trades'}")

        strict = item.get("strict_fill_comparison")
        if strict:
            lines.extend(
                [
                    "",
                    "### Strict Fill Sensitivity",
                    "",
                    f"- Net R delta: `{strict['net_total_r_delta']}R`",
                    f"- Avg R delta: `{strict['net_avg_r_delta']}R`",
                    f"- PF delta: `{strict['profit_factor_delta']}`",
                    f"- DD delta: `{strict['max_drawdown_r_delta']}R`",
                    f"- Strict gate failures: `{', '.join(strict['strict_gate_failures']) if strict['strict_gate_failures'] else 'none'}`",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Focused diagnostics for near-miss research candidates.")
    parser.add_argument("--candidate-name", action="append", default=[], help="Candidate name to diagnose. Can be repeated.")
    parser.add_argument("--source-artifact", type=Path, help="Reuse universe from a research artifact.")
    parser.add_argument("--symbols", help="Comma-separated symbol override.")
    parser.add_argument("--universe-limit", type=int, default=harness.DEFAULT_UNIVERSE_LIMIT)
    parser.add_argument("--universe-profile", choices=["strict", "permissive"], default="strict")
    parser.add_argument("--min-quote-volume", type=float, default=harness.DEFAULT_MIN_QUOTE_VOLUME)
    parser.add_argument("--allow-excluded-bases", action="store_true")
    parser.add_argument("--trigger-limit", type=int, default=harness.DEFAULT_TRIGGER_LIMIT)
    parser.add_argument("--forward-candles", type=int, default=harness.DEFAULT_FORWARD_CANDLES)
    parser.add_argument("--fee-bps", type=float, default=study.DEFAULT_FEE_BPS)
    parser.add_argument("--cache-dir", type=Path, default=Path("tmp/research_cache"))
    parser.add_argument("--derivatives-cache-dir", type=Path, default=Path("tmp/derivatives_cache"))
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--refresh-derivatives-cache", action="store_true")
    parser.add_argument("--fetch-metrics", action="store_true")
    parser.add_argument("--entry-slippage-bps", type=float, default=None)
    parser.add_argument("--stop-slippage-bps", type=float, default=None)
    parser.add_argument("--tp-slippage-bps", type=float, default=None)
    parser.add_argument("--strict-fills", action="store_true")
    parser.add_argument("--no-slippage", action="store_true")
    parser.add_argument("--compare-strict-fills", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--json-out", type=Path, default=Path("tmp/research_runs/candidate_diagnostics_latest.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("tmp/research_runs/candidate_diagnostics_latest.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate_names = args.candidate_name or DEFAULT_CANDIDATES
    candidates = candidate_by_name(candidate_names)
    symbols, universe_selection = choose_universe(args)
    market_data = load_market(symbols, candidates, args)
    active_symbols = [symbol for symbol in symbols if symbol in market_data]
    splits = harness.build_splits(args.trigger_limit, args.forward_candles)
    full_walk_forward = args.trigger_limit >= harness.RESEARCH_CANDLES + harness.HOLDOUT_CANDLES
    fill_settings = build_fill_settings(args)
    strict_settings = build_fill_settings(args, strict=True)

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        print(f"[diagnose] {candidate.name}", file=sys.stderr)
        records = collect_records(candidate, active_symbols, market_data, splits, args, fill_settings)
        result = evaluate_records(candidate, records, splits, full_walk_forward)
        if args.compare_strict_fills and not fill_settings.strict_fills:
            strict_records = collect_records(candidate, active_symbols, market_data, splits, args, strict_settings)
            strict_result = evaluate_records(candidate, strict_records, splits, full_walk_forward)
            result["strict_fill_comparison"] = strict_fill_delta(result, strict_result)
        results.append(result)

    payload = {
        "generated_at": int(time.time() * 1000),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settings": {
            "trigger_limit": args.trigger_limit,
            "forward_candles": args.forward_candles,
            "fee_bps": args.fee_bps,
            "fill_settings": asdict(fill_settings),
            "strict_fill_comparison": args.compare_strict_fills,
            "metrics_cache_only": not args.fetch_metrics,
        },
        "universe_selection": universe_selection,
        "universe": active_symbols,
        "splits": [asdict(split) for split in splits],
        "candidates": results,
    }
    markdown = render_markdown(payload)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
