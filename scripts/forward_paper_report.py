#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


DEFAULT_DB_PATH = Path("data/tradebot.db")
FOLLOWUP_BARS = 32
TRIGGER_INTERVAL_MS = 15 * 60 * 1000


@dataclass(frozen=True)
class TradePair:
    strategy_version: str
    symbol: str
    opened_at: int | None
    closed_at: int | None
    entry_price: float | None
    exit_price: float | None
    quantity: float | None
    remaining_quantity: float | None
    risk_amount: float | None
    realized_pnl: float | None
    realized_r: float | None
    unrealized_pnl: float | None
    unrealized_r: float | None
    current_price: float | None
    stop_loss: float | None
    take_profit: float | None
    outcome: str
    session_bucket: str
    day: str
    open_validity: str | None


def row_dicts(cursor: sqlite3.Cursor, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    columns = [column[0] for column in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def utc_text(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "n/a"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def utc_day(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "unknown"
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def session_bucket(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "unknown"
    hour = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).hour
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 16:
        return "london_ny_overlap"
    if 16 <= hour < 22:
        return "new_york"
    return "off_hours"


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def signed_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+,.2f}"


def signed_r(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f}R"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def where_clause(
    since_ms: int | None,
    strategy: str | None,
    symbol: str | None,
    time_column: str,
    include_strategy: bool,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if since_ms is not None:
        clauses.append(f"{time_column} >= ?")
        params.append(since_ms)
    if include_strategy and strategy:
        clauses.append("strategy_version = ?")
        params.append(strategy)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), tuple(params)


def load_latest_prices(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    if table_exists(connection, "telemetry_market_tickers"):
        rows = row_dicts(
            connection.cursor(),
            """
            SELECT t.symbol, t.last_price AS current_price, t.snapshot_time
            FROM telemetry_market_tickers t
            JOIN (
                SELECT symbol, MAX(snapshot_time) AS snapshot_time
                FROM telemetry_market_tickers
                GROUP BY symbol
            ) latest
              ON latest.symbol = t.symbol AND latest.snapshot_time = t.snapshot_time
            """,
        )
        return {str(row["symbol"]): row for row in rows}

    if table_exists(connection, "trades"):
        rows = row_dicts(
            connection.cursor(),
            """
            SELECT t.symbol, t.price AS current_price, t.executed_at AS snapshot_time
            FROM trades t
            JOIN (
                SELECT symbol, MAX(executed_at) AS executed_at
                FROM trades
                GROUP BY symbol
            ) latest
              ON latest.symbol = t.symbol AND latest.executed_at = t.executed_at
            """,
        )
        return {str(row["symbol"]): row for row in rows}
    return {}


def simulate_followup_outcome(
    entry: float,
    stop_loss: float,
    take_profit_1: float,
    take_profit_2: float | None,
    candles: list[dict[str, Any]],
) -> str:
    tp1_index: int | None = None
    for index, candle in enumerate(candles):
        low = safe_float(candle.get("low"))
        high = safe_float(candle.get("high"))
        if low is None or high is None:
            continue
        hit_stop = low <= stop_loss
        hit_tp1 = high >= take_profit_1
        if hit_stop and hit_tp1:
            return "would_stop_same_candle"
        if hit_stop:
            return "would_stop"
        if hit_tp1:
            tp1_index = index
            break

    if tp1_index is None:
        return "no_tp1_or_stop_observed"
    if take_profit_2 is None:
        return "would_hit_tp1"

    for candle in candles[tp1_index:]:
        low = safe_float(candle.get("low"))
        high = safe_float(candle.get("high"))
        if low is None or high is None:
            continue
        hit_break_even = low <= entry
        hit_tp2 = high >= take_profit_2
        if hit_break_even and hit_tp2:
            return "would_breakeven_same_candle"
        if hit_tp2:
            return "would_hit_tp2"
        if hit_break_even:
            return "would_breakeven"
    return "would_timeout_after_tp1"


def annotate_rejected_followups(connection: sqlite3.Connection, decisions: list[dict[str, Any]]) -> None:
    if not table_exists(connection, "telemetry_signal_evaluations") or not table_exists(connection, "telemetry_candles"):
        for decision in decisions:
            if decision.get("decision") == "rejected":
                decision["rejected_followup_outcome"] = "unavailable_no_telemetry"
        return

    cursor = connection.cursor()
    for decision in decisions:
        if decision.get("decision") != "rejected":
            continue
        signal_close_time = safe_int(decision.get("signal_close_time"))
        strategy = decision.get("strategy_version")
        symbol = decision.get("symbol")
        if signal_close_time is None or not strategy or not symbol:
            decision["rejected_followup_outcome"] = "unavailable_missing_key"
            continue
        signal_row = cursor.execute(
            """
            SELECT entry_price, stop_loss, take_profit_1, take_profit_2, has_risk_plan
            FROM telemetry_signal_evaluations
            WHERE strategy_version = ?1 AND symbol = ?2 AND signal_close_time = ?3
            """,
            (strategy, symbol, signal_close_time),
        ).fetchone()
        if signal_row is None:
            decision["rejected_followup_outcome"] = "unavailable_no_signal_telemetry"
            continue
        entry = safe_float(signal_row[0])
        stop_loss = safe_float(signal_row[1])
        take_profit_1 = safe_float(signal_row[2])
        take_profit_2 = safe_float(signal_row[3])
        if not signal_row[4] or entry is None or stop_loss is None or take_profit_1 is None:
            decision["rejected_followup_outcome"] = "unavailable_no_risk_plan"
            continue
        candles = row_dicts(
            cursor,
            """
            SELECT open_time, high, low, close
            FROM telemetry_candles
            WHERE symbol = ?1 AND interval = '15m' AND open_time >= ?2
            ORDER BY open_time ASC
            LIMIT ?3
            """,
            (symbol, signal_close_time, FOLLOWUP_BARS),
        )
        if not candles:
            decision["rejected_followup_outcome"] = "unavailable_no_forward_candles"
            continue
        decision["rejected_followup_outcome"] = simulate_followup_outcome(
            entry,
            stop_loss,
            take_profit_1,
            take_profit_2,
            candles,
        )


def load_forward_data(
    db_path: Path,
    since_ms: int | None = None,
    strategy: str | None = None,
    symbol: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Paper database not found: {db_path}")

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        decisions: list[dict[str, Any]] = []
        if table_exists(connection, "auto_paper_decisions"):
            where, params = where_clause(since_ms, strategy, symbol, "created_at", include_strategy=True)
            decisions = row_dicts(
                cursor,
                f"SELECT * FROM auto_paper_decisions {where} ORDER BY created_at ASC, id ASC",
                params,
            )
            annotate_rejected_followups(connection, decisions)

        trades: list[dict[str, Any]] = []
        if table_exists(connection, "trades"):
            where, params = where_clause(since_ms, None, symbol, "executed_at", include_strategy=False)
            trades = row_dicts(
                cursor,
                f"SELECT * FROM trades {where} ORDER BY executed_at ASC, id ASC",
                params,
            )

        positions: list[dict[str, Any]] = []
        if table_exists(connection, "positions"):
            position_where = ""
            position_params: tuple[Any, ...] = ()
            if symbol:
                position_where = "WHERE symbol = ?"
                position_params = (symbol.upper(),)
            positions = row_dicts(
                cursor,
                f"SELECT * FROM positions {position_where} ORDER BY symbol ASC",
                position_params,
            )
            if strategy:
                positions = [
                    item
                    for item in positions
                    if strategy in str(item.get("note") or "")
                ]

        latest_prices = load_latest_prices(connection)
        for position in positions:
            latest = latest_prices.get(str(position.get("symbol")))
            if latest is not None:
                position["current_price"] = latest.get("current_price")
                position["current_price_time"] = latest.get("snapshot_time")

    return decisions, trades, positions


def load_telemetry_context(
    db_path: Path,
    since_ms: int | None,
    strategy: str | None,
    symbol: str | None,
) -> dict[str, Any]:
    if not db_path.exists():
        return {"available": False}
    with sqlite3.connect(db_path) as connection:
        if not table_exists(connection, "telemetry_signal_evaluations"):
            return {"available": False}
        where, params = where_clause(since_ms, strategy, symbol, "captured_at", include_strategy=True)
        rows = row_dicts(
            connection.cursor(),
            f"""
            SELECT strategy_version, symbol, stage, technical_stage, has_risk_plan, ai_score
            FROM telemetry_signal_evaluations {where}
            """,
            params,
        )
    stage_counts = Counter(str(row.get("stage") or "unknown") for row in rows)
    technical_counts = Counter(str(row.get("technical_stage") or "unknown") for row in rows)
    ready_rows = [row for row in rows if str(row.get("technical_stage") or "").upper() == "READY"]
    return {
        "available": True,
        "signal_evaluations_total": len(rows),
        "stage_counts": dict(stage_counts),
        "technical_stage_counts": dict(technical_counts),
        "technical_ready_count": len(ready_rows),
        "risk_plan_count": sum(1 for row in rows if int(row.get("has_risk_plan") or 0) == 1),
    }


def blockers_from_reason(reason: str | None) -> list[str]:
    if not reason:
        return ["unspecified"]
    if "duplicate_symbol_signal_conflict" in reason:
        return ["duplicate_symbol_signal_conflict"]
    marker = "Failed checks:"
    if marker not in reason:
        return [reason.strip().rstrip(".")[:120] or "unspecified"]
    raw = reason.split(marker, 1)[1].strip().rstrip(".")
    blockers = [item.strip() for item in raw.split(",") if item.strip()]
    return blockers or ["unspecified"]


def open_validity(
    entry: float | None,
    current: float | None,
    stop_loss: float | None,
    take_profit: float | None,
) -> str:
    if current is None:
        return "unknown_no_current_price"
    if stop_loss is not None and current <= stop_loss:
        return "degraded_below_stop"
    if take_profit is not None and current >= take_profit:
        return "at_or_above_take_profit"
    if entry is not None and current < entry:
        return "degraded_below_entry"
    if entry is not None and stop_loss is not None and entry > stop_loss:
        near_stop = stop_loss + (entry - stop_loss) * 0.25
        if current <= near_stop:
            return "near_stop"
    return "valid"


def pair_auto_trades(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
) -> list[TradePair]:
    trades_by_id = {int(trade["id"]): trade for trade in trades if trade.get("id") is not None}
    sell_trades = [
        trade
        for trade in trades
        if str(trade.get("side", "")).upper() == "SELL"
    ]
    sell_trades.sort(key=lambda item: (int(item.get("executed_at") or 0), int(item.get("id") or 0)))
    used_exit_ids: set[int] = set()
    positions_by_symbol = {str(item.get("symbol")): item for item in positions}
    pairs: list[TradePair] = []

    entries = [
        decision
        for decision in decisions
        if decision.get("decision") == "entered" and decision.get("trade_id") is not None
    ]
    entries.sort(key=lambda item: int(item.get("created_at") or 0))

    for decision in entries:
        entry_trade = trades_by_id.get(int(decision["trade_id"]))
        symbol = str(decision.get("symbol") or (entry_trade or {}).get("symbol") or "")
        opened_at = int((entry_trade or {}).get("executed_at") or decision.get("created_at") or 0)
        entry_price = safe_float(decision.get("entry_price")) or safe_float((entry_trade or {}).get("price"))
        quantity = safe_float(decision.get("quantity")) or safe_float((entry_trade or {}).get("quantity"))
        risk_amount = safe_float(decision.get("risk_amount"))
        stop_loss = safe_float(decision.get("stop_loss"))
        take_profit = safe_float(decision.get("take_profit"))

        exit_quantity = 0.0
        weighted_exit = 0.0
        realized_pnl = 0.0
        exit_sources: list[str] = []
        closed_at: int | None = None
        for candidate in sell_trades:
            candidate_id = int(candidate["id"])
            if candidate_id in used_exit_ids:
                continue
            if candidate.get("symbol") != symbol:
                continue
            if int(candidate.get("executed_at") or 0) < opened_at:
                continue
            sell_quantity = safe_float(candidate.get("quantity")) or 0.0
            sell_price = safe_float(candidate.get("price")) or 0.0
            exit_quantity += sell_quantity
            weighted_exit += sell_quantity * sell_price
            realized_pnl += safe_float(candidate.get("realized_pnl")) or 0.0
            exit_sources.append(str(candidate.get("source") or "sell"))
            closed_at = int(candidate.get("executed_at") or 0)
            used_exit_ids.add(candidate_id)
            if quantity is not None and exit_quantity + 1e-9 >= quantity:
                break

        completed = quantity is not None and exit_quantity + 1e-9 >= quantity
        remaining_quantity = None if quantity is None else max(0.0, quantity - exit_quantity)
        exit_price = weighted_exit / exit_quantity if exit_quantity > 0 else None
        pair_realized_pnl = realized_pnl if exit_quantity > 0 else None
        realized_r = (
            pair_realized_pnl / risk_amount
            if pair_realized_pnl is not None and risk_amount is not None and risk_amount > 0.0
            else None
        )

        position = positions_by_symbol.get(symbol, {})
        current_price = safe_float(position.get("current_price"))
        unrealized_pnl = None
        unrealized_r = None
        validity = None
        if not completed:
            if current_price is not None and entry_price is not None and remaining_quantity is not None:
                unrealized_pnl = (current_price - entry_price) * remaining_quantity
                unrealized_r = unrealized_pnl / risk_amount if risk_amount and risk_amount > 0.0 else None
            validity = open_validity(entry_price, current_price, stop_loss, take_profit)

        if completed:
            outcome = exit_sources[-1] if len(set(exit_sources)) == 1 else "partial_" + "+".join(exit_sources)
        else:
            outcome = "open"

        pairs.append(
            TradePair(
                strategy_version=str(decision.get("strategy_version") or "unknown"),
                symbol=symbol,
                opened_at=opened_at,
                closed_at=closed_at if completed else None,
                entry_price=entry_price,
                exit_price=exit_price if completed else None,
                quantity=quantity,
                remaining_quantity=remaining_quantity,
                risk_amount=risk_amount,
                realized_pnl=pair_realized_pnl if completed else None,
                realized_r=realized_r if completed else None,
                unrealized_pnl=unrealized_pnl,
                unrealized_r=unrealized_r,
                current_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                outcome=outcome,
                session_bucket=session_bucket(opened_at),
                day=utc_day(closed_at if completed else opened_at),
                open_validity=validity,
            )
        )

    return pairs


def max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def completed_trade_stats(pairs: list[TradePair]) -> dict[str, Any]:
    r_values = [pair.realized_r for pair in pairs if pair.realized_r is not None]
    wins = [value for value in r_values if value > 0.0]
    losses = [value for value in r_values if value < 0.0]
    pnl_values = [pair.realized_pnl for pair in pairs if pair.realized_pnl is not None]
    equity_curve: list[float] = []
    running = 0.0
    for value in r_values:
        running += value
        equity_curve.append(round(running, 4))
    return {
        "count": len(pairs),
        "total_realized_pnl": round(sum(pnl_values), 8),
        "total_realized_r": round(sum(r_values), 8),
        "average_r": round(sum(r_values) / len(r_values), 8) if r_values else None,
        "median_r": round(statistics.median(r_values), 8) if r_values else None,
        "win_rate": round(sum(1 for value in r_values if value > 0.0) / len(r_values) * 100.0, 4)
        if r_values
        else None,
        "max_win_r": round(max(wins), 8) if wins else None,
        "max_loss_r": round(min(losses), 8) if losses else None,
        "equity_curve_r": equity_curve,
        "max_drawdown_r": round(max_drawdown(r_values), 8),
    }


def grouped_stats(pairs: list[TradePair], key_fn: Callable[[TradePair], str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[TradePair]] = defaultdict(list)
    for pair in pairs:
        groups[key_fn(pair)].append(pair)
    return {key: completed_trade_stats(group) for key, group in sorted(groups.items())}


def flat_reason(decision_counts: dict[str, int], telemetry_context: dict[str, Any]) -> str:
    if decision_counts.get("entered", 0) > 0:
        return "entries_observed"
    if decision_counts.get("conflict_skipped", 0) > 0:
        return "duplicate_symbol_signal_conflicts"
    if decision_counts.get("rejected", 0) > 0:
        return "gates_rejecting_technical_ready_setups"
    if telemetry_context.get("available") and telemetry_context.get("signal_evaluations_total", 0) > 0:
        if telemetry_context.get("technical_ready_count", 0) == 0:
            return "no_technical_ready_setups"
        return "technical_ready_seen_but_no_auto_entries"
    return "no_logged_auto_decisions_or_auto_disabled"


def summarize(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    telemetry_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    telemetry_context = telemetry_context or {"available": False}
    pairs = pair_auto_trades(decisions, trades, positions)
    completed = [pair for pair in pairs if pair.closed_at is not None]
    open_pairs = [pair for pair in pairs if pair.closed_at is None]

    decision_counts = Counter(str(item.get("decision") or "unknown") for item in decisions)
    strategy_counts = Counter(str(item.get("strategy_version") or "unknown") for item in decisions)
    symbol_counts = Counter(str(item.get("symbol") or "unknown") for item in decisions)
    session_counts = Counter(session_bucket(safe_int(item.get("signal_close_time"))) for item in decisions)
    day_counts = Counter(utc_day(safe_int(item.get("created_at"))) for item in decisions)
    outcome_counts = Counter(pair.outcome for pair in pairs)

    rejected = [item for item in decisions if item.get("decision") in {"rejected", "conflict_skipped"}]
    blocker_counts: Counter[str] = Counter()
    strategy_blocker_counts: Counter[str] = Counter()
    symbol_blocker_counts: Counter[str] = Counter()
    for item in rejected:
        blockers = blockers_from_reason(item.get("reason"))
        strategy = str(item.get("strategy_version") or "unknown")
        symbol = str(item.get("symbol") or "unknown")
        for blocker in blockers:
            blocker_counts[blocker] += 1
            strategy_blocker_counts[f"{strategy}|{blocker}"] += 1
            symbol_blocker_counts[f"{symbol}|{blocker}"] += 1

    followup_counts = Counter(
        str(item.get("rejected_followup_outcome") or "not_applicable")
        for item in decisions
        if item.get("decision") == "rejected"
    )

    daily_pnl: dict[str, float] = defaultdict(float)
    daily_r: dict[str, float] = defaultdict(float)
    for pair in completed:
        day = utc_day(pair.closed_at)
        daily_pnl[day] += pair.realized_pnl or 0.0
        daily_r[day] += pair.realized_r or 0.0

    completed_overall = completed_trade_stats(completed)
    return {
        "generated_at": int(datetime.now(tz=UTC).timestamp() * 1000),
        "decisions_total": len(decisions),
        "decision_counts": dict(decision_counts),
        "strategy_counts": dict(strategy_counts),
        "symbol_counts": dict(symbol_counts),
        "session_counts": dict(session_counts),
        "day_counts": dict(sorted(day_counts.items())),
        "outcome_counts": dict(outcome_counts),
        "rejection_blockers": dict(blocker_counts),
        "rejection_blockers_by_strategy": dict(strategy_blocker_counts),
        "rejection_blockers_by_symbol": dict(symbol_blocker_counts),
        "rejected_followup_outcomes": dict(followup_counts),
        "flat_reason": flat_reason(dict(decision_counts), telemetry_context),
        "telemetry_context": telemetry_context,
        "auto_entries": len(pairs),
        "completed_trades": len(completed),
        "open_auto_trades": len(open_pairs),
        "realized_pnl": completed_overall["total_realized_pnl"],
        "realized_r": completed_overall["total_realized_r"],
        "avg_realized_r": completed_overall["average_r"],
        "daily_pnl": dict(sorted(daily_pnl.items())),
        "daily_r": dict(sorted(daily_r.items())),
        "completed_stats": completed_overall,
        "grouped_stats": {
            "by_strategy": grouped_stats(completed, lambda pair: pair.strategy_version),
            "by_symbol": grouped_stats(completed, lambda pair: pair.symbol),
            "by_session_bucket": grouped_stats(completed, lambda pair: pair.session_bucket),
            "by_day": grouped_stats(completed, lambda pair: pair.day),
            "by_outcome": grouped_stats(completed, lambda pair: pair.outcome),
        },
        "open_positions": positions,
        "open_auto_trades_detail": [asdict(pair) for pair in open_pairs],
        "trade_pairs": [asdict(pair) for pair in pairs],
    }


def render_stats_table(stats_by_key: dict[str, dict[str, Any]], heading: str, empty: str) -> list[str]:
    lines = ["", f"## {heading}", ""]
    if not stats_by_key:
        lines.append(f"- {empty}")
        return lines
    lines.extend(
        [
            "| Group | Count | Total PnL | Total R | Avg R | Median R | Win rate | Max win | Max loss | Max DD |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, stats in stats_by_key.items():
        lines.append(
            f"| `{name}` | `{stats['count']}` | `{signed_money(stats['total_realized_pnl'])}` "
            f"| `{signed_r(stats['total_realized_r'])}` | `{signed_r(stats['average_r'])}` "
            f"| `{signed_r(stats['median_r'])}` | `{pct(stats['win_rate'])}` "
            f"| `{signed_r(stats['max_win_r'])}` | `{signed_r(stats['max_loss_r'])}` "
            f"| `{signed_r(stats['max_drawdown_r'])}` |"
        )
    return lines


def render_count_map(title: str, values: dict[str, int], empty: str) -> list[str]:
    lines = ["", f"## {title}", ""]
    if not values:
        lines.append(f"- {empty}")
        return lines
    for name, count in sorted(values.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{name}`: `{count}`")
    return lines


def render_markdown(summary: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
    stats = summary["completed_stats"]
    lines = [
        "# Forward Paper Report",
        "",
        f"- Generated: `{utc_text(summary['generated_at'])}`",
        f"- Decisions logged: `{summary['decisions_total']}`",
        f"- Auto entries: `{summary['auto_entries']}`",
        f"- Completed auto trades: `{summary['completed_trades']}`",
        f"- Open auto trades: `{summary['open_auto_trades']}`",
        f"- Flat context: `{summary['flat_reason']}`",
        f"- Total realized PnL: `{signed_money(stats['total_realized_pnl'])}`",
        f"- Total realized R: `{signed_r(stats['total_realized_r'])}`",
        f"- Avg completed R: `{signed_r(stats['average_r'])}`",
        f"- Median completed R: `{signed_r(stats['median_r'])}`",
        f"- Win rate: `{pct(stats['win_rate'])}`",
        f"- Max drawdown: `{signed_r(stats['max_drawdown_r'])}`",
        "",
        "## Decisions",
        "",
    ]

    if summary["decision_counts"]:
        for name, count in sorted(summary["decision_counts"].items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- No auto-paper decisions logged yet.")

    lines.extend(render_stats_table(summary["grouped_stats"]["by_strategy"], "Strategy Performance", "No completed auto-paper exits yet."))
    lines.extend(render_stats_table(summary["grouped_stats"]["by_symbol"], "Symbol Performance", "No completed auto-paper exits yet."))
    lines.extend(render_stats_table(summary["grouped_stats"]["by_session_bucket"], "Session Performance", "No completed auto-paper exits yet."))
    lines.extend(render_stats_table(summary["grouped_stats"]["by_day"], "Daily Results", "No completed auto-paper exits yet."))
    lines.extend(render_stats_table(summary["grouped_stats"]["by_outcome"], "Outcome Results", "No completed auto-paper exits yet."))

    lines.extend(render_count_map("Rejection Blockers", summary["rejection_blockers"], "No rejected technical-ready setups logged yet."))
    lines.extend(render_count_map("Strategy + Blocker", summary["rejection_blockers_by_strategy"], "No rejected technical-ready setups logged yet."))
    lines.extend(render_count_map("Symbol + Blocker", summary["rejection_blockers_by_symbol"], "No rejected technical-ready setups logged yet."))
    lines.extend(render_count_map("Rejected Follow-up Outcomes", summary["rejected_followup_outcomes"], "No rejected setup follow-up telemetry available."))

    lines.extend(["", "## Open Auto Trades", ""])
    open_pairs = summary["open_auto_trades_detail"]
    if open_pairs:
        lines.extend(
            [
                "| Opened | Strategy | Symbol | Entry | Current | Stop | TP | Unrealized PnL | Unrealized R | Validity |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for pair in open_pairs:
            lines.append(
                f"| `{utc_text(pair['opened_at'])}` | `{pair['strategy_version']}` | `{pair['symbol']}` "
                f"| `{money(pair['entry_price'])}` | `{money(pair['current_price'])}` "
                f"| `{money(pair['stop_loss'])}` | `{money(pair['take_profit'])}` "
                f"| `{signed_money(pair['unrealized_pnl'])}` | `{signed_r(pair['unrealized_r'])}` "
                f"| `{pair['open_validity']}` |"
            )
    else:
        lines.append("- No open auto-paper entries from the selected scope.")

    lines.extend(["", "## Auto Trades", ""])
    pairs = summary["trade_pairs"]
    if pairs:
        for pair in pairs[-20:]:
            lines.append(
                "- `{strategy}` `{symbol}` opened `{opened}` outcome `{outcome}` "
                "entry `{entry}` exit `{exit}` PnL `{pnl}` R `{r}`".format(
                    strategy=pair["strategy_version"],
                    symbol=pair["symbol"],
                    opened=utc_text(pair["opened_at"]),
                    outcome=pair["outcome"],
                    entry=money(pair["entry_price"]),
                    exit=money(pair["exit_price"]),
                    pnl=signed_money(pair["realized_pnl"]),
                    r=signed_r(pair["realized_r"]),
                )
            )
    else:
        lines.append("- No auto-paper entries yet.")

    lines.extend(["", "## Recent Decisions", ""])
    if decisions:
        for item in decisions[-20:]:
            followup = item.get("rejected_followup_outcome")
            followup_text = f" follow-up `{followup}`" if followup else ""
            lines.append(
                f"- `{utc_text(item.get('created_at'))}` `{item.get('strategy_version')}` `{item.get('symbol')}` "
                f"`{item.get('decision')}` score `{item.get('ai_score')}`{followup_text}: {item.get('reason') or ''}"
            )
    else:
        lines.append("- No decisions yet.")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize guarded auto-paper forward-test results.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--since-hours", type=float)
    parser.add_argument("--strategy", help="Filter to one strategy_version.")
    parser.add_argument("--symbol", help="Filter to one symbol.")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = None
    if args.since_hours is not None:
        since_ms = int(datetime.now(tz=UTC).timestamp() * 1000 - args.since_hours * 60 * 60 * 1000)

    symbol = args.symbol.upper() if args.symbol else None
    decisions, trades, positions = load_forward_data(args.db, since_ms, args.strategy, symbol)
    telemetry_context = load_telemetry_context(args.db, since_ms, args.strategy, symbol)
    summary = summarize(decisions, trades, positions, telemetry_context)
    markdown = render_markdown(summary, decisions)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
