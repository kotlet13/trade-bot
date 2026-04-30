#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/tradebot.db")
DEFAULT_RECENT_LIMIT = 10


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


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def signed(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:+.4f}{suffix}"


def money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def signed_money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+,.2f}"


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_json_list(raw: Any) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def since_ms_from_hours(hours: float | None) -> int | None:
    if hours is None:
        return None
    return int(datetime.now(tz=UTC).timestamp() * 1000 - hours * 60 * 60 * 1000)


def where_since(column: str, since_ms: int | None) -> tuple[str, tuple[Any, ...]]:
    if since_ms is None:
        return "", ()
    return f"WHERE {column} >= ?", (since_ms,)


def load_table(
    connection: sqlite3.Connection,
    table: str,
    order_column: str,
    since_ms: int | None,
) -> list[dict[str, Any]]:
    if not table_exists(connection, table):
        return []
    cursor = connection.cursor()
    where, params = where_since(order_column, since_ms)
    return row_dicts(cursor, f"SELECT * FROM {table} {where} ORDER BY {order_column} ASC", params)


def load_data(db_path: Path, since_ms: int | None) -> dict[str, list[dict[str, Any]]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path, timeout=30.0) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        return {
            "tickers": load_table(connection, "telemetry_market_tickers", "snapshot_time", since_ms),
            "candles": load_table(connection, "telemetry_candles", "fetched_at", since_ms),
            "funding": load_table(connection, "telemetry_funding_rates", "fetched_at", since_ms),
            "futures_metrics": load_table(connection, "telemetry_futures_metric_rows", "fetched_at", since_ms),
            "signals": load_table(connection, "telemetry_signal_evaluations", "captured_at", since_ms),
            "news_events": load_table(connection, "telemetry_news_events", "fetched_at", since_ms),
            "decisions": load_table(connection, "auto_paper_decisions", "created_at", since_ms),
            "trades": load_table(connection, "trades", "executed_at", since_ms),
            "positions": load_table(connection, "positions", "updated_at", None),
        }


def time_range(rows: list[dict[str, Any]], column: str) -> dict[str, int | None]:
    values = [int(row[column]) for row in rows if row.get(column) is not None]
    return {
        "first": min(values) if values else None,
        "last": max(values) if values else None,
    }


def latest_by_key(rows: list[dict[str, Any]], key: str, time_column: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item_key = str(row.get(key) or "")
        if not item_key:
            continue
        current = latest.get(item_key)
        if current is None or int(row.get(time_column) or 0) > int(current.get(time_column) or 0):
            latest[item_key] = row
    return latest


def latest_metric_by_symbol(
    rows: list[dict[str, Any]],
    metric_name: str,
) -> dict[str, dict[str, Any]]:
    filtered = [row for row in rows if row.get("metric_name") == metric_name]
    return latest_by_key(filtered, "symbol", "timestamp")


def summarize_signal_checks(signals: list[dict[str, Any]]) -> dict[str, Any]:
    failed_checks: Counter[str] = Counter()
    near_ready = []
    ready = []
    for signal in signals:
        checks = [str(item) for item in parse_json_list(signal.get("failed_checks_json"))]
        failed_checks.update(checks)
        technical_stage = str(signal.get("technical_stage") or "")
        has_risk_plan = int(signal.get("has_risk_plan") or 0) == 1
        if technical_stage == "READY":
            ready.append(signal)
        if technical_stage == "READY" and not has_risk_plan:
            near_ready.append(signal)
    return {
        "failed_check_counts": dict(failed_checks.most_common()),
        "technical_ready_count": len(ready),
        "blocked_ready_count": len(near_ready),
        "recent_blocked_ready": near_ready[-DEFAULT_RECENT_LIMIT:],
    }


def summarize_paper(decisions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    decision_counts = Counter(str(item.get("decision") or "unknown") for item in decisions)
    strategy_counts = Counter(str(item.get("strategy_version") or "unknown") for item in decisions)
    symbol_counts = Counter(str(item.get("symbol") or "unknown") for item in decisions)
    realized_pnl = sum(
        safe_float(trade.get("realized_pnl")) or 0.0
        for trade in trades
        if str(trade.get("side") or "").upper() == "SELL"
    )
    buy_count = sum(1 for trade in trades if str(trade.get("side") or "").upper() == "BUY")
    sell_count = sum(1 for trade in trades if str(trade.get("side") or "").upper() == "SELL")
    return {
        "decisions_total": len(decisions),
        "decision_counts": dict(decision_counts),
        "strategy_counts": dict(strategy_counts),
        "symbol_counts": dict(symbol_counts),
        "buy_trades": buy_count,
        "sell_trades": sell_count,
        "realized_pnl": realized_pnl,
        "recent_decisions": decisions[-DEFAULT_RECENT_LIMIT:],
        "recent_trades": trades[-DEFAULT_RECENT_LIMIT:],
    }


def summarize_news(events: list[dict[str, Any]]) -> dict[str, Any]:
    event_counts = Counter(str(item.get("event_type") or "unknown") for item in events)
    sentiment_counts = Counter(str(item.get("sentiment") or "unknown") for item in events)
    symbol_counts: Counter[str] = Counter()
    for event in events:
        symbols = parse_json_list(event.get("symbols_json"))
        for symbol in symbols:
            symbol_counts[str(symbol)] += 1
    return {
        "events_total": len(events),
        "event_type_counts": dict(event_counts),
        "sentiment_counts": dict(sentiment_counts),
        "symbol_counts": dict(symbol_counts),
        "latest_event_time": max(
            (int(event.get("published_at") or event.get("fetched_at") or 0) for event in events),
            default=None,
        ),
        "recent_events": sorted(
            events,
            key=lambda item: int(item.get("published_at") or item.get("fetched_at") or 0),
            reverse=True,
        )[:DEFAULT_RECENT_LIMIT],
    }


def summarize_market(tickers: list[dict[str, Any]], candles: list[dict[str, Any]]) -> dict[str, Any]:
    latest_tickers = latest_by_key(tickers, "symbol", "snapshot_time")
    changes = [safe_float(row.get("price_change_percent")) for row in latest_tickers.values()]
    changes = [value for value in changes if value is not None]
    positive = [value for value in changes if value > 0]
    candle_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for candle in candles:
        candle_counts[str(candle.get("symbol") or "")][str(candle.get("interval") or "")] += 1
    return {
        "ticker_symbols": len(latest_tickers),
        "latest_ticker_time": max((int(row.get("snapshot_time") or 0) for row in latest_tickers.values()), default=None),
        "positive_24h_share_pct": (len(positive) / len(changes) * 100.0) if changes else None,
        "median_24h_change_pct": median(changes),
        "top_24h_gainers": sorted(
            [
                {
                    "symbol": symbol,
                    "price_change_percent": safe_float(row.get("price_change_percent")),
                    "last_price": safe_float(row.get("last_price")),
                    "quote_volume": safe_float(row.get("quote_volume")),
                }
                for symbol, row in latest_tickers.items()
            ],
            key=lambda item: item["price_change_percent"] if item["price_change_percent"] is not None else -999999.0,
            reverse=True,
        )[:5],
        "candle_rows": len(candles),
        "candle_counts": {symbol: dict(intervals) for symbol, intervals in sorted(candle_counts.items()) if symbol},
    }


def summarize_futures(
    funding: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_funding = latest_by_key(funding, "symbol", "funding_time")
    latest_global = latest_metric_by_symbol(metrics, "global_long_short_account_ratio")
    latest_taker = latest_metric_by_symbol(metrics, "taker_long_short_ratio")
    latest_top_position = latest_metric_by_symbol(metrics, "top_long_short_position_ratio")
    latest_open_interest = latest_metric_by_symbol(metrics, "open_interest_hist")
    metric_counts = Counter(str(row.get("metric_name") or "unknown") for row in metrics)
    funding_values = [safe_float(row.get("funding_rate_bps")) for row in latest_funding.values()]
    funding_values = [value for value in funding_values if value is not None]
    global_ratios = [safe_float(row.get("long_short_ratio")) for row in latest_global.values()]
    global_ratios = [value for value in global_ratios if value is not None]
    taker_ratios = [safe_float(row.get("buy_sell_ratio")) for row in latest_taker.values()]
    taker_ratios = [value for value in taker_ratios if value is not None]
    return {
        "funding_symbols": len(latest_funding),
        "metric_row_counts": dict(metric_counts),
        "metric_symbols": {
            "global_long_short_account_ratio": len(latest_global),
            "taker_long_short_ratio": len(latest_taker),
            "top_long_short_position_ratio": len(latest_top_position),
            "open_interest_hist": len(latest_open_interest),
        },
        "median_funding_bps": median(funding_values),
        "median_global_account_long_short_ratio": median(global_ratios),
        "median_taker_buy_sell_ratio": median(taker_ratios),
        "latest_funding_time": max((int(row.get("funding_time") or 0) for row in latest_funding.values()), default=None),
        "latest_metric_time": max((int(row.get("timestamp") or 0) for row in metrics), default=None),
    }


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def summarize(data: dict[str, list[dict[str, Any]]], since_ms: int | None) -> dict[str, Any]:
    signals = data["signals"]
    signal_strategy_counts = Counter(str(item.get("strategy_version") or "unknown") for item in signals)
    signal_stage_counts = Counter(str(item.get("stage") or "unknown") for item in signals)
    signal_technical_stage_counts = Counter(str(item.get("technical_stage") or "unknown") for item in signals)
    scores = [int(item.get("ai_score") or 0) for item in signals]
    return {
        "generated_at": int(datetime.now(tz=UTC).timestamp() * 1000),
        "since_ms": since_ms,
        "archive_ranges": {
            "tickers": time_range(data["tickers"], "snapshot_time"),
            "candles": time_range(data["candles"], "fetched_at"),
            "funding": time_range(data["funding"], "fetched_at"),
            "futures_metrics": time_range(data["futures_metrics"], "fetched_at"),
            "signals": time_range(signals, "captured_at"),
            "news_events": time_range(data["news_events"], "fetched_at"),
        },
        "row_counts": {name: len(rows) for name, rows in data.items()},
        "news": summarize_news(data["news_events"]),
        "market": summarize_market(data["tickers"], data["candles"]),
        "futures": summarize_futures(data["funding"], data["futures_metrics"]),
        "signals": {
            "strategy_counts": dict(signal_strategy_counts),
            "stage_counts": dict(signal_stage_counts),
            "technical_stage_counts": dict(signal_technical_stage_counts),
            "min_ai_score": min(scores) if scores else None,
            "max_ai_score": max(scores) if scores else None,
            "avg_ai_score": sum(scores) / len(scores) if scores else None,
            **summarize_signal_checks(signals),
            "recent_signals": signals[-DEFAULT_RECENT_LIMIT:],
        },
        "paper": summarize_paper(data["decisions"], data["trades"]),
    }


def render_count_map(items: dict[str, Any], empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    return [f"- `{key}`: `{value}`" for key, value in sorted(items.items(), key=lambda item: (-int(item[1]), item[0]))]


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Runtime Telemetry Report",
        "",
        f"- Generated: `{utc_text(summary['generated_at'])}`",
        f"- Window start: `{utc_text(summary['since_ms']) if summary['since_ms'] else 'all available telemetry'}`",
        "",
        "## Archive Coverage",
        "",
    ]
    for name, count in sorted(summary["row_counts"].items()):
        lines.append(f"- `{name}`: `{count}` rows")

    lines.extend(
        [
            "",
            "## News Events",
            "",
            f"- Classified events: `{summary['news']['events_total']}`",
            f"- Latest event time: `{utc_text(summary['news']['latest_event_time'])}`",
            "",
            "Event types:",
            "",
        ]
    )
    lines.extend(render_count_map(summary["news"]["event_type_counts"], "No news events collected yet."))
    lines.extend(["", "Event symbols:", ""])
    lines.extend(render_count_map(summary["news"]["symbol_counts"], "No symbol-specific news events yet."))
    lines.extend(["", "Recent classified news:", ""])
    if summary["news"]["recent_events"]:
        for item in summary["news"]["recent_events"]:
            symbols = ",".join(str(symbol) for symbol in parse_json_list(item.get("symbols_json"))) or "market"
            lines.append(
                f"- `{utc_text(item.get('published_at') or item.get('fetched_at'))}` "
                f"`{item.get('source')}` `{item.get('event_type')}` `{item.get('sentiment')}` "
                f"symbols `{symbols}`: {item.get('title')}"
            )
    else:
        lines.append("- No news events collected yet.")

    lines.extend(
        [
            "",
            "## Market Snapshot",
            "",
            f"- Symbols with latest ticker: `{summary['market']['ticker_symbols']}`",
            f"- Latest ticker time: `{utc_text(summary['market']['latest_ticker_time'])}`",
            f"- Positive 24h share: `{pct(summary['market']['positive_24h_share_pct'])}`",
            f"- Median 24h change: `{signed(summary['market']['median_24h_change_pct'], '%')}`",
            f"- Candle rows in window: `{summary['market']['candle_rows']}`",
            "",
            "Top 24h gainers:",
            "",
        ]
    )
    for item in summary["market"]["top_24h_gainers"]:
        lines.append(
            f"- `{item['symbol']}` `{signed(item['price_change_percent'], '%')}` "
            f"last `{item['last_price']}` quote volume `{item['quote_volume']}`"
        )
    if not summary["market"]["top_24h_gainers"]:
        lines.append("- No ticker telemetry yet.")

    lines.extend(
        [
            "",
            "## Futures Telemetry",
            "",
            f"- Funding symbols: `{summary['futures']['funding_symbols']}`",
            f"- Latest funding time: `{utc_text(summary['futures']['latest_funding_time'])}`",
            f"- Latest metric time: `{utc_text(summary['futures']['latest_metric_time'])}`",
            f"- Median funding: `{signed(summary['futures']['median_funding_bps'], ' bps')}`",
            f"- Median global account L/S: `{format_optional_float(summary['futures']['median_global_account_long_short_ratio'])}`",
            f"- Median taker buy/sell: `{format_optional_float(summary['futures']['median_taker_buy_sell_ratio'])}`",
            "",
            "Metric symbols:",
            "",
        ]
    )
    for name, count in sorted(summary["futures"]["metric_symbols"].items()):
        lines.append(f"- `{name}`: `{count}`")

    lines.extend(["", "## Signal Evaluations", ""])
    lines.extend(render_count_map(summary["signals"]["strategy_counts"], "No signal telemetry yet."))
    lines.extend(["", "Displayed stages:", ""])
    lines.extend(render_count_map(summary["signals"]["stage_counts"], "No stages yet."))
    lines.extend(["", "Technical stages:", ""])
    lines.extend(render_count_map(summary["signals"]["technical_stage_counts"], "No technical stages yet."))
    lines.extend(
        [
            "",
            f"- AI score range: `{summary['signals']['min_ai_score']}` to `{summary['signals']['max_ai_score']}`",
            f"- Average AI score: `{format_optional_float(summary['signals']['avg_ai_score'])}`",
            f"- Technical READY evaluations: `{summary['signals']['technical_ready_count']}`",
            f"- Blocked technical READY evaluations: `{summary['signals']['blocked_ready_count']}`",
            "",
            "Top failed checks:",
            "",
        ]
    )
    lines.extend(render_count_map(summary["signals"]["failed_check_counts"], "No failed checks captured."))

    lines.extend(["", "Recent blocked READY setups:", ""])
    blocked = summary["signals"]["recent_blocked_ready"]
    if blocked:
        for item in blocked:
            failed = ", ".join(str(check) for check in parse_json_list(item.get("failed_checks_json")))
            lines.append(
                f"- `{utc_text(item.get('captured_at'))}` `{item.get('strategy_version')}` "
                f"`{item.get('symbol')}` score `{item.get('ai_score')}` failed `{failed}`"
            )
    else:
        lines.append("- No blocked technical READY evaluations in this window.")

    lines.extend(["", "## Paper Outcomes", ""])
    lines.append(f"- Decisions: `{summary['paper']['decisions_total']}`")
    lines.append(f"- Buy trades: `{summary['paper']['buy_trades']}`")
    lines.append(f"- Sell trades: `{summary['paper']['sell_trades']}`")
    lines.append(f"- Realized PnL from sells: `{signed_money(summary['paper']['realized_pnl'])}`")
    lines.extend(["", "Decision counts:", ""])
    lines.extend(render_count_map(summary["paper"]["decision_counts"], "No paper decisions yet."))
    lines.extend(["", "Recent decisions:", ""])
    if summary["paper"]["recent_decisions"]:
        for item in summary["paper"]["recent_decisions"]:
            lines.append(
                f"- `{utc_text(item.get('created_at'))}` `{item.get('strategy_version')}` "
                f"`{item.get('symbol')}` `{item.get('decision')}` score `{item.get('ai_score')}`"
            )
    else:
        lines.append("- No paper decisions yet.")

    return "\n".join(lines) + "\n"


def format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize runtime telemetry and paper decision context.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--since-hours", type=float, default=24.0)
    parser.add_argument("--all", action="store_true", help="Use all available telemetry instead of --since-hours.")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = None if args.all else since_ms_from_hours(args.since_hours)
    data = load_data(args.db, since_ms)
    summary = summarize(data, since_ms)
    markdown = render_markdown(summary)

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
