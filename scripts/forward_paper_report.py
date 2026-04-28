#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/tradebot.db")


@dataclass(frozen=True)
class TradePair:
    symbol: str
    opened_at: int | None
    closed_at: int | None
    entry_price: float | None
    exit_price: float | None
    quantity: float | None
    risk_amount: float | None
    realized_pnl: float | None
    realized_r: float | None
    outcome: str


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


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_forward_data(
    db_path: Path,
    since_ms: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Paper database not found: {db_path}")

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        decisions: list[dict[str, Any]] = []
        if table_exists(connection, "auto_paper_decisions"):
            where = "WHERE created_at >= ?" if since_ms is not None else ""
            params = (since_ms,) if since_ms is not None else ()
            decisions = row_dicts(
                cursor,
                f"SELECT * FROM auto_paper_decisions {where} ORDER BY created_at ASC",
                params,
            )

        trade_where = "WHERE executed_at >= ?" if since_ms is not None else ""
        trade_params = (since_ms,) if since_ms is not None else ()
        trades = row_dicts(
            cursor,
            f"SELECT * FROM trades {trade_where} ORDER BY executed_at ASC, id ASC",
            trade_params,
        )
        positions = row_dicts(
            cursor,
            "SELECT * FROM positions ORDER BY symbol ASC",
        )

    return decisions, trades, positions


def pair_auto_trades(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[TradePair]:
    trades_by_id = {int(trade["id"]): trade for trade in trades if trade.get("id") is not None}
    sell_trades = [
        trade
        for trade in trades
        if str(trade.get("side", "")).upper() == "SELL"
    ]
    used_exit_ids: set[int] = set()
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
        exit_trade = None
        for candidate in sell_trades:
            candidate_id = int(candidate["id"])
            if candidate_id in used_exit_ids:
                continue
            if candidate.get("symbol") != symbol:
                continue
            if int(candidate.get("executed_at") or 0) < opened_at:
                continue
            exit_trade = candidate
            used_exit_ids.add(candidate_id)
            break

        risk_amount = safe_float(decision.get("risk_amount"))
        realized_pnl = safe_float(exit_trade.get("realized_pnl")) if exit_trade else None
        realized_r = (
            realized_pnl / risk_amount
            if realized_pnl is not None and risk_amount is not None and risk_amount > 0.0
            else None
        )
        pairs.append(
            TradePair(
                symbol=symbol,
                opened_at=opened_at,
                closed_at=int(exit_trade["executed_at"]) if exit_trade else None,
                entry_price=safe_float(decision.get("entry_price"))
                or safe_float((entry_trade or {}).get("price")),
                exit_price=safe_float(exit_trade.get("price")) if exit_trade else None,
                quantity=safe_float(decision.get("quantity"))
                or safe_float((entry_trade or {}).get("quantity")),
                risk_amount=risk_amount,
                realized_pnl=realized_pnl,
                realized_r=realized_r,
                outcome=str(exit_trade.get("source")) if exit_trade else "open",
            )
        )

    return pairs


def blocker_from_reason(reason: str | None) -> str:
    if not reason:
        return "unspecified"
    marker = "Failed checks:"
    if marker not in reason:
        return reason.strip()[:120]
    return reason.split(marker, 1)[1].strip().rstrip(".")


def summarize(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    pairs = pair_auto_trades(decisions, trades)
    completed = [pair for pair in pairs if pair.closed_at is not None]
    open_pairs = [pair for pair in pairs if pair.closed_at is None]
    decision_counts = Counter(str(item.get("decision") or "unknown") for item in decisions)
    symbol_counts = Counter(str(item.get("symbol") or "unknown") for item in decisions)
    rejected = [item for item in decisions if item.get("decision") == "rejected"]
    blocker_counts = Counter(blocker_from_reason(item.get("reason")) for item in rejected)
    daily_pnl: dict[str, float] = defaultdict(float)
    daily_r: dict[str, float] = defaultdict(float)
    for pair in completed:
        day = utc_day(pair.closed_at)
        daily_pnl[day] += pair.realized_pnl or 0.0
        daily_r[day] += pair.realized_r or 0.0

    realized_pnl = sum(pair.realized_pnl or 0.0 for pair in completed)
    realized_r = sum(pair.realized_r or 0.0 for pair in completed)

    return {
        "generated_at": int(datetime.now(tz=UTC).timestamp() * 1000),
        "decisions_total": len(decisions),
        "decision_counts": dict(decision_counts),
        "symbol_counts": dict(symbol_counts),
        "rejection_blockers": dict(blocker_counts),
        "auto_entries": len(pairs),
        "completed_trades": len(completed),
        "open_auto_trades": len(open_pairs),
        "realized_pnl": realized_pnl,
        "realized_r": realized_r,
        "avg_realized_r": realized_r / len(completed) if completed else None,
        "daily_pnl": dict(sorted(daily_pnl.items())),
        "daily_r": dict(sorted(daily_r.items())),
        "open_positions": positions,
        "trade_pairs": [pair.__dict__ for pair in pairs],
    }


def render_markdown(summary: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
    lines = [
        "# Forward Paper Report",
        "",
        f"- Generated: `{utc_text(summary['generated_at'])}`",
        f"- Decisions logged: `{summary['decisions_total']}`",
        f"- Auto entries: `{summary['auto_entries']}`",
        f"- Completed auto trades: `{summary['completed_trades']}`",
        f"- Open auto trades: `{summary['open_auto_trades']}`",
        f"- Realized PnL: `{signed_money(summary['realized_pnl'])}`",
        f"- Realized R: `{signed_r(summary['realized_r'])}`",
        f"- Avg completed R: `{signed_r(summary['avg_realized_r'])}`",
        "",
        "## Decisions",
        "",
    ]

    if summary["decision_counts"]:
        for name, count in sorted(summary["decision_counts"].items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- No auto-paper decisions logged yet.")

    lines.extend(["", "## Rejection Blockers", ""])
    if summary["rejection_blockers"]:
        for name, count in sorted(summary["rejection_blockers"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- No rejected technical-ready setups logged yet.")

    lines.extend(["", "## Daily Results", ""])
    if summary["daily_pnl"]:
        for day, pnl in summary["daily_pnl"].items():
            lines.append(f"- `{day}`: `{signed_money(pnl)}`, `{signed_r(summary['daily_r'].get(day))}`")
    else:
        lines.append("- No completed auto-paper exits yet.")

    lines.extend(["", "## Auto Trades", ""])
    pairs = summary["trade_pairs"]
    if pairs:
        for pair in pairs[-20:]:
            lines.append(
                "- `{symbol}` opened `{opened}` outcome `{outcome}` "
                "entry `{entry}` exit `{exit}` PnL `{pnl}` R `{r}`".format(
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
            lines.append(
                f"- `{utc_text(item.get('created_at'))}` `{item.get('symbol')}` "
                f"`{item.get('decision')}` score `{item.get('ai_score')}`: {item.get('reason') or ''}"
            )
    else:
        lines.append("- No decisions yet.")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize guarded auto-paper forward-test results.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--since-hours", type=float)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = None
    if args.since_hours is not None:
        since_ms = int(datetime.now(tz=UTC).timestamp() * 1000 - args.since_hours * 60 * 60 * 1000)

    decisions, trades, positions = load_forward_data(args.db, since_ms)
    summary = summarize(decisions, trades, positions)
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
