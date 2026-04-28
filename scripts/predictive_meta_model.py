#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = Path("tmp/research_runs/derivatives_metrics_profile_20260427.json")
DEFAULT_OUTPUT_DIR = Path("tmp/research_runs")
MIN_PROMOTION_TRADES = 80
MIN_PROMOTION_NET_AVG_R = 0.10
MIN_PROMOTION_PROFIT_FACTOR = 1.25
MIN_HOLDOUT_NET_AVG_R = 0.05
MIN_POSITIVE_FOLDS = 4
MAX_PROMOTION_DRAWDOWN_R = 10.0
MAX_SYMBOL_CONCENTRATION = 0.40
MAX_SINGLE_TRADE_CONCENTRATION = 0.25

NUMERIC_FEATURES = [
    "fee_drag_r",
    "stop_pct",
    "volume_percentile_96",
    "atr_expansion_30_vs_90",
    "btc_return_24h_pct",
    "basket_positive_share_24h_pct",
    "relative_strength_percentile_24h",
    "funding_rate_bps",
    "metrics_open_interest_24h_change_pct",
    "global_account_long_short_ratio",
    "top_trader_account_long_short_ratio",
    "top_trader_position_long_short_ratio",
    "taker_buy_sell_ratio",
    "ai_score_v2",
]
SESSION_CATEGORIES = ["london", "london_ny_overlap", "new_york", "off_hours", "other"]
KEEP_FRACTIONS = [0.25, 0.40, 0.55, 0.70, 0.85, 1.00]


@dataclass(frozen=True)
class FeatureSchema:
    medians: dict[str, float]
    means: dict[str, float]
    stds: dict[str, float]
    names: list[str]
    candidate_categories: list[str]


@dataclass(frozen=True)
class Model:
    bias: float
    weights: list[float]
    schema: FeatureSchema


def rounded(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def load_trades(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    trades = payload.get("trade_context", {}).get("trades", [])
    if not isinstance(trades, list):
        return []
    return sorted(
        [trade for trade in trades if isinstance(trade, dict) and "net_r" in trade],
        key=lambda item: (int(item.get("opened_at", 0)), str(item.get("symbol", ""))),
    )


def finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def build_schema(records: list[dict[str, Any]]) -> FeatureSchema:
    medians: dict[str, float] = {}
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    names: list[str] = []
    for feature in NUMERIC_FEATURES:
        values = [value for record in records if (value := finite_float(record.get(feature))) is not None]
        med = median(values)
        imputed = [finite_float(record.get(feature)) or med for record in records] or [med]
        mean = statistics.fmean(imputed)
        variance = statistics.fmean([(value - mean) ** 2 for value in imputed]) if imputed else 0.0
        std = math.sqrt(variance) if variance > 1e-12 else 1.0
        medians[feature] = med
        means[feature] = mean
        stds[feature] = std
        names.append(feature)
        names.append(f"{feature}_missing")
    names.extend(f"session={category}" for category in SESSION_CATEGORIES)
    candidate_categories = sorted({str(record.get("candidate", "unknown")) for record in records})
    names.extend(f"candidate={candidate}" for candidate in candidate_categories)
    return FeatureSchema(
        medians=medians,
        means=means,
        stds=stds,
        names=names,
        candidate_categories=candidate_categories,
    )


def vectorize(record: dict[str, Any], schema: FeatureSchema) -> list[float]:
    values: list[float] = []
    for feature in NUMERIC_FEATURES:
        raw = finite_float(record.get(feature))
        missing = 1.0 if raw is None else 0.0
        value = schema.medians[feature] if raw is None else raw
        values.append((value - schema.means[feature]) / schema.stds[feature])
        values.append(missing)
    session = str(record.get("session", "other"))
    if session not in SESSION_CATEGORIES:
        session = "other"
    values.extend(1.0 if session == category else 0.0 for category in SESSION_CATEGORIES)
    candidate = str(record.get("candidate", "unknown"))
    values.extend(1.0 if candidate == category else 0.0 for category in schema.candidate_categories)
    return values


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        for item in range(column, size + 1):
            augmented[column][item] /= pivot_value
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) < 1e-15:
                continue
            for item in range(column, size + 1):
                augmented[row][item] -= factor * augmented[column][item]
    return [augmented[row][size] for row in range(size)]


def fit_ridge(records: list[dict[str, Any]], l2: float) -> Model:
    schema = build_schema(records)
    width = len(schema.names) + 1
    xtx = [[0.0 for _ in range(width)] for _ in range(width)]
    xty = [0.0 for _ in range(width)]
    for record in records:
        row = [1.0, *vectorize(record, schema)]
        target = float(record["net_r"])
        for i, left in enumerate(row):
            xty[i] += left * target
            for j, right in enumerate(row):
                xtx[i][j] += left * right
    for index in range(1, width):
        xtx[index][index] += l2
    solution = solve_linear_system(xtx, xty)
    if solution is None:
        solution = [0.0 for _ in range(width)]
    return Model(bias=solution[0], weights=solution[1:], schema=schema)


def predict(model: Model, record: dict[str, Any]) -> float:
    row = vectorize(record, model.schema)
    return model.bias + sum(weight * value for weight, value in zip(model.weights, row))


def segment_key(record: dict[str, Any]) -> tuple[int, str]:
    if record.get("segment_index") is not None and record.get("segment") is not None:
        return (int(record["segment_index"]), str(record["segment"]))
    if record.get("split") == "holdout":
        return (99, "holdout")
    fold = record.get("fold")
    fold_number = int(fold) if fold is not None else 98
    return (fold_number, f"validation_{fold_number}")


def segment_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        _, name = segment_key(record)
        grouped.setdefault(name, []).append(record)
    return {key: sorted(value, key=lambda item: int(item.get("opened_at", 0))) for key, value in grouped.items()}


def segment_order(records: list[dict[str, Any]]) -> list[str]:
    labels = {segment_key(record) for record in records}
    return [name for _, name in sorted(labels)]


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def profit_factor(values: list[float]) -> float:
    gains = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    if losses <= 1e-12:
        return 999.0 if gains > 0.0 else 0.0
    return gains / losses


def concentration_by_symbol(records: list[dict[str, Any]]) -> float:
    positive_total = sum(float(record["net_r"]) for record in records if float(record["net_r"]) > 0.0)
    if positive_total <= 1e-12:
        return 1.0 if records else 0.0
    by_symbol: dict[str, float] = {}
    for record in records:
        net_r = float(record["net_r"])
        if net_r > 0.0:
            symbol = str(record.get("symbol", ""))
            by_symbol[symbol] = by_symbol.get(symbol, 0.0) + net_r
    return max(by_symbol.values(), default=0.0) / positive_total


def concentration_by_trade(records: list[dict[str, Any]]) -> float:
    positive_total = sum(float(record["net_r"]) for record in records if float(record["net_r"]) > 0.0)
    if positive_total <= 1e-12:
        return 1.0 if records else 0.0
    return max((float(record["net_r"]) for record in records), default=0.0) / positive_total


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: (int(item.get("opened_at", 0)), str(item.get("symbol", ""))))
    values = [float(record["net_r"]) for record in ordered]
    return {
        "trades": len(values),
        "net_total_r": rounded(sum(values)) or 0.0,
        "net_avg_r": rounded(statistics.fmean(values)) if values else 0.0,
        "profit_factor": rounded(profit_factor(values)) if values else 0.0,
        "max_drawdown_r": rounded(max_drawdown(values)) if values else 0.0,
        "win_rate": rounded(sum(1 for value in values if value > 0.0) / len(values), 4) if values else 0.0,
        "symbol_concentration": rounded(concentration_by_symbol(ordered)) if ordered else 0.0,
        "single_trade_concentration": rounded(concentration_by_trade(ordered)) if ordered else 0.0,
    }


def promotion_failures(records: list[dict[str, Any]]) -> list[str]:
    metrics = summarize_records(records)
    failures: list[str] = []
    has_standard_protocol = any(record.get("split") == "holdout" for record in records) and any(
        record.get("split") == "validation" and record.get("fold") in {1, 2, 3, 4, 5}
        for record in records
    )
    if not has_standard_protocol:
        return ["not_promotion_protocol"]
    holdout = [record for record in records if record.get("split") == "holdout"]
    holdout_metrics = summarize_records(holdout)
    positive_folds = 0
    for fold in range(1, 6):
        fold_records = [record for record in records if record.get("split") == "validation" and record.get("fold") == fold]
        if sum(float(record["net_r"]) for record in fold_records) > 0.0:
            positive_folds += 1
    if metrics["trades"] < MIN_PROMOTION_TRADES:
        failures.append(f"executed_trades<{MIN_PROMOTION_TRADES}")
    if metrics["net_avg_r"] < MIN_PROMOTION_NET_AVG_R:
        failures.append(f"net_avg_r<{MIN_PROMOTION_NET_AVG_R}")
    if metrics["profit_factor"] < MIN_PROMOTION_PROFIT_FACTOR:
        failures.append(f"profit_factor<{MIN_PROMOTION_PROFIT_FACTOR}")
    if holdout_metrics["net_total_r"] <= 0.0:
        failures.append("holdout_net_total_r<=0")
    if holdout_metrics["net_avg_r"] < MIN_HOLDOUT_NET_AVG_R:
        failures.append(f"holdout_net_avg_r<{MIN_HOLDOUT_NET_AVG_R}")
    if positive_folds < MIN_POSITIVE_FOLDS:
        failures.append(f"folds_positive<{MIN_POSITIVE_FOLDS}")
    if metrics["max_drawdown_r"] > MAX_PROMOTION_DRAWDOWN_R:
        failures.append(f"max_drawdown_r>{MAX_PROMOTION_DRAWDOWN_R}")
    if metrics["symbol_concentration"] > MAX_SYMBOL_CONCENTRATION:
        failures.append(f"symbol_concentration>{MAX_SYMBOL_CONCENTRATION}")
    if metrics["single_trade_concentration"] > MAX_SINGLE_TRADE_CONCENTRATION:
        failures.append(f"single_trade_concentration>{MAX_SINGLE_TRADE_CONCENTRATION}")
    return failures


def select_top_scored(scored: list[tuple[float, dict[str, Any]]], keep_fraction: float) -> list[dict[str, Any]]:
    if not scored:
        return []
    keep = max(1, math.ceil(len(scored) * keep_fraction))
    return [record for _, record in sorted(scored, key=lambda item: item[0], reverse=True)[:keep]]


def evaluate_selected(name: str, selected: list[dict[str, Any]], segment_selected: dict[str, int]) -> dict[str, Any]:
    metrics = summarize_records(selected)
    failures = promotion_failures(selected)
    by_segment = {
        segment: summarize_records([record for record in selected if segment_key(record)[1] == segment])
        for segment in sorted(segment_selected)
    }
    return {
        "name": name,
        "passed_promotion_gates": not failures,
        "gate_failures": failures,
        "overall": metrics,
        "segment_selected": segment_selected,
        "by_segment": by_segment,
    }


def blocked_cv(records: list[dict[str, Any]], keep_fraction: float, l2: float) -> dict[str, Any]:
    grouped = segment_records(records)
    selected: list[dict[str, Any]] = []
    selected_counts: dict[str, int] = {}
    for segment in segment_order(records):
        target = grouped.get(segment, [])
        train = [record for name, rows in grouped.items() if name != segment for record in rows]
        if not target or not train:
            selected_counts[segment] = 0
            continue
        model = fit_ridge(train, l2)
        chosen = select_top_scored([(predict(model, record), record) for record in target], keep_fraction)
        selected.extend(chosen)
        selected_counts[segment] = len(chosen)
    return evaluate_selected(f"blocked_cv_keep_{keep_fraction:.2f}", selected, selected_counts)


def expanding_walk_forward(
    records: list[dict[str, Any]],
    keep_fraction: float,
    l2: float,
    min_train: int,
    fallback_all: bool,
) -> dict[str, Any]:
    grouped = segment_records(records)
    selected: list[dict[str, Any]] = []
    selected_counts: dict[str, int] = {}
    prior: list[dict[str, Any]] = []
    for segment in segment_order(records):
        target = grouped.get(segment, [])
        if not target:
            selected_counts[segment] = 0
        elif len(prior) >= min_train:
            model = fit_ridge(prior, l2)
            chosen = select_top_scored([(predict(model, record), record) for record in target], keep_fraction)
            selected.extend(chosen)
            selected_counts[segment] = len(chosen)
        elif fallback_all:
            selected.extend(target)
            selected_counts[segment] = len(target)
        else:
            selected_counts[segment] = 0
        prior.extend(target)
    label = "expanding_fallback_all" if fallback_all else "expanding_prior_only"
    return evaluate_selected(f"{label}_keep_{keep_fraction:.2f}", selected, selected_counts)


def baseline_filter(records: list[dict[str, Any]], name: str, predicate: Any) -> dict[str, Any]:
    selected = [record for record in records if predicate(record)]
    counts: dict[str, int] = {}
    for segment in segment_order(records):
        counts[segment] = sum(1 for record in selected if segment_key(record)[1] == segment)
    return evaluate_selected(name, selected, counts)


def full_model_coefficients(records: list[dict[str, Any]], l2: float) -> list[dict[str, Any]]:
    model = fit_ridge(records, l2)
    pairs = [
        {"feature": feature, "coefficient": rounded(weight, 6)}
        for feature, weight in zip(model.schema.names, model.weights)
    ]
    return sorted(pairs, key=lambda item: abs(float(item["coefficient"] or 0.0)), reverse=True)


def build_output_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return output_dir / f"predictive_meta_model_{stamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research an entry-time predictive meta-model for existing trades.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--l2", type=float, default=5.0)
    parser.add_argument("--min-train", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = load_trades(args.profile)
    output_path = args.json_out or build_output_path(args.output_dir)
    baseline = evaluate_selected(
        "all_trades_baseline",
        records,
        {segment: len(segment_records(records).get(segment, [])) for segment in segment_order(records)},
    )
    blocked = [blocked_cv(records, fraction, args.l2) for fraction in KEEP_FRACTIONS]
    expanding_prior = [
        expanding_walk_forward(records, fraction, args.l2, args.min_train, fallback_all=False)
        for fraction in KEEP_FRACTIONS
    ]
    expanding_fallback = [
        expanding_walk_forward(records, fraction, args.l2, args.min_train, fallback_all=True)
        for fraction in KEEP_FRACTIONS
    ]
    baselines = [
        baseline_filter(
            records,
            "rule_global_account_lte_1.20",
            lambda record: (finite_float(record.get("global_account_long_short_ratio")) or 999.0) <= 1.20,
        ),
        baseline_filter(
            records,
            "rule_taker_buy_sell_ge_1.25",
            lambda record: (finite_float(record.get("taker_buy_sell_ratio")) or -999.0) >= 1.25,
        ),
        baseline_filter(
            records,
            "rule_metrics_oi_down",
            lambda record: (finite_float(record.get("metrics_open_interest_24h_change_pct")) or 999.0) < 0.0,
        ),
        baseline_filter(
            records,
            "rule_funding_not_panic_and_taker_buy",
            lambda record: (finite_float(record.get("funding_rate_bps")) or -999.0) > -1.0
            and (finite_float(record.get("taker_buy_sell_ratio")) or -999.0) >= 1.25,
        ),
    ]
    payload = {
        "generated_at": int(time.time() * 1000),
        "source_profile": str(args.profile),
        "settings": {
            "features": NUMERIC_FEATURES,
            "session_categories": SESSION_CATEGORIES,
            "keep_fractions": KEEP_FRACTIONS,
            "l2": args.l2,
            "min_train": args.min_train,
            "note": "blocked_cv is diagnostic; expanding protocols avoid training on future segments but have limited early history.",
        },
        "baseline": baseline,
        "blocked_cv": blocked,
        "expanding_prior_only": expanding_prior,
        "expanding_fallback_all": expanding_fallback,
        "rule_baselines": baselines,
        "full_model_top_coefficients": full_model_coefficients(records, args.l2)[:15],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {output_path}")
    print("Baseline:", baseline["overall"], "failures=", baseline["gate_failures"])
    for section_name in ["blocked_cv", "expanding_prior_only", "expanding_fallback_all"]:
        best = max(payload[section_name], key=lambda item: item["overall"]["net_total_r"])
        print(section_name, best["name"], best["overall"], "failures=", best["gate_failures"])
    print("Rule baselines:")
    for item in baselines:
        print(" ", item["name"], item["overall"], "failures=", item["gate_failures"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
