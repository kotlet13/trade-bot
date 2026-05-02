#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import forward_paper_report as forward


DEFAULT_DB_PATH = Path("data/tradebot.db")
DEFAULT_STRATEGIES = ("ai_score_v2_base_score7", "ai_score_v2_ablate_oi")


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def strategy_decisions(decisions: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
    return [item for item in decisions if str(item.get("strategy_version") or "") == strategy]


def technical_ready_count(decisions: list[dict[str, Any]]) -> int:
    count = 0
    for item in decisions:
        technical_stage = str(item.get("technical_stage") or item.get("stage") or "").upper()
        if technical_stage == "READY":
            count += 1
    return count


def compare_strategy(
    decisions: list[dict[str, Any]],
    pairs: list[forward.TradePair],
    strategy: str,
    min_meaningful_trades: int,
) -> dict[str, Any]:
    own_decisions = strategy_decisions(decisions, strategy)
    own_pairs = [pair for pair in pairs if pair.strategy_version == strategy]
    completed = [pair for pair in own_pairs if pair.closed_at is not None]
    stats = forward.completed_trade_stats(completed)
    decision_counts = Counter(str(item.get("decision") or "unknown") for item in own_decisions)
    return {
        "strategy": strategy,
        "technical_ready_setups": technical_ready_count(own_decisions),
        "entered": decision_counts.get("entered", 0),
        "entry_attempts": decision_counts.get("entry_attempt", 0),
        "rejected": decision_counts.get("rejected", 0),
        "conflict_skipped": decision_counts.get("conflict_skipped", 0),
        "paused_blocked": decision_counts.get("paused_blocked", 0),
        "open_trades": sum(1 for pair in own_pairs if pair.closed_at is None),
        "completed_trades": len(completed),
        "realized_r": stats["total_realized_r"],
        "average_r": stats["average_r"],
        "median_r": stats["median_r"],
        "win_rate": stats["win_rate"],
        "profit_factor": stats["profit_factor"],
        "profit_factor_infinite": stats["profit_factor_infinite"],
        "max_drawdown_r": stats["max_drawdown_r"],
        "sample_too_small": len(completed) < min_meaningful_trades,
    }


def assess_difference(rows: list[dict[str, Any]], min_meaningful_trades: int) -> dict[str, Any]:
    if len(rows) < 2:
        return {
            "sample_assessment": "sample_too_small",
            "oi_ablation_helped": "inconclusive",
            "notes": ["comparison requires both active paper strategies"],
        }
    base = next((row for row in rows if row["strategy"] == DEFAULT_STRATEGIES[0]), rows[0])
    oi = next((row for row in rows if row["strategy"] == DEFAULT_STRATEGIES[1]), rows[1])
    if base["completed_trades"] < min_meaningful_trades or oi["completed_trades"] < min_meaningful_trades:
        return {
            "sample_assessment": "sample_too_small",
            "oi_ablation_helped": "inconclusive",
            "notes": ["completed forward-paper sample is too small for strategy replacement claims"],
        }
    base_avg = safe_float(base.get("average_r")) or 0.0
    oi_avg = safe_float(oi.get("average_r")) or 0.0
    base_dd = safe_float(base.get("max_drawdown_r")) or 0.0
    oi_dd = safe_float(oi.get("max_drawdown_r")) or 0.0
    helped = oi_avg > base_avg and oi_dd <= base_dd
    return {
        "sample_assessment": "meaningful_observation",
        "oi_ablation_helped": "yes_observe_only" if helped else "no_clear_edge",
        "notes": [
            "analysis only; this report does not promote, demote, or replace active strategies",
        ],
    }


def build_payload(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    strategies: list[str],
    min_meaningful_trades: int,
) -> dict[str, Any]:
    pairs = forward.pair_auto_trades(decisions, trades, positions)
    rows = [
        compare_strategy(decisions, pairs, strategy, min_meaningful_trades)
        for strategy in strategies
    ]
    return {
        "generated_at": int(datetime.now(tz=UTC).timestamp() * 1000),
        "strategies": rows,
        "comparison": assess_difference(rows, min_meaningful_trades),
        "analysis_only": True,
        "promotion_allowed": False,
    }


def signed_r(value: Any) -> str:
    parsed = safe_float(value)
    return "n/a" if parsed is None else f"{parsed:+.3f}R"


def render_markdown(payload: dict[str, Any]) -> str:
    comparison = payload["comparison"]
    lines = [
        "# Strategy Forward Compare",
        "",
        f"- Generated: `{forward.utc_text(payload['generated_at'])}`",
        f"- Sample assessment: `{comparison['sample_assessment']}`",
        f"- OI ablation helped: `{comparison['oi_ablation_helped']}`",
        "- Analysis only: `yes`",
        "- Promotion allowed: `no`",
        "",
        "| Strategy | READY setups | Entered | Rejected | Conflict skipped | Completed | Open | Realized R | Avg R | Median R | PF | Max DD | Sample small |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["strategies"]:
        pf = forward.format_profit_factor(row.get("profit_factor"), bool(row.get("profit_factor_infinite")))
        lines.append(
            f"| `{row['strategy']}` | `{row['technical_ready_setups']}` | `{row['entered']}` "
            f"| `{row['rejected']}` | `{row['conflict_skipped']}` | `{row['completed_trades']}` "
            f"| `{row['open_trades']}` | `{signed_r(row['realized_r'])}` | `{signed_r(row['average_r'])}` "
            f"| `{signed_r(row['median_r'])}` | `{pf}` | `{signed_r(row['max_drawdown_r'])}` "
            f"| `{'yes' if row['sample_too_small'] else 'no'}` |"
        )
    lines.extend(["", "## Notes", ""])
    for note in comparison["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare active guarded paper strategies.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--since-hours", type=float)
    parser.add_argument("--strategies", default=",".join(DEFAULT_STRATEGIES))
    parser.add_argument("--min-meaningful-trades", type=int, default=30)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = None
    if args.since_hours is not None:
        since_ms = int(datetime.now(tz=UTC).timestamp() * 1000 - args.since_hours * 60 * 60 * 1000)
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    decisions, trades, positions = forward.load_forward_data(args.db, since_ms)
    payload = build_payload(decisions, trades, positions, strategies, args.min_meaningful_trades)
    markdown = render_markdown(payload)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
