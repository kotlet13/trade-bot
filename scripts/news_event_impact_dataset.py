#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/tradebot.db")
DEFAULT_HORIZON_MINUTES = [60, 240, 1440]
DEFAULT_MARKET_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


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


def since_ms_from_hours(hours: float | None) -> int | None:
    if hours is None:
        return None
    return int(datetime.now(tz=UTC).timestamp() * 1000 - hours * 60 * 60 * 1000)


def parse_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def load_events(connection: sqlite3.Connection, since_ms: int | None) -> list[dict[str, Any]]:
    if not table_exists(connection, "telemetry_news_events"):
        return []
    where = "WHERE COALESCE(published_at, fetched_at) >= ?" if since_ms is not None else ""
    params = (since_ms,) if since_ms is not None else ()
    return row_dicts(
        connection.cursor(),
        f"""
        SELECT *
        FROM telemetry_news_events
        {where}
        ORDER BY COALESCE(published_at, fetched_at) ASC
        """,
        params,
    )


def load_candles(
    connection: sqlite3.Connection,
    symbols: list[str],
    interval: str,
    min_time: int | None,
) -> dict[str, list[dict[str, Any]]]:
    if not table_exists(connection, "telemetry_candles") or not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    params: list[Any] = [interval, *symbols]
    time_clause = ""
    if min_time is not None:
        time_clause = "AND open_time >= ?"
        params.append(min_time)
    rows = row_dicts(
        connection.cursor(),
        f"""
        SELECT symbol, interval, open_time, close
        FROM telemetry_candles
        WHERE interval = ? AND symbol IN ({placeholders}) {time_clause}
        ORDER BY symbol ASC, open_time ASC
        """,
        tuple(params),
    )
    candles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        candles[str(row["symbol"])].append(row)
    return dict(candles)


def first_candle_at_or_after(candles: list[dict[str, Any]], timestamp_ms: int) -> dict[str, Any] | None:
    for candle in candles:
        if int(candle["open_time"]) >= timestamp_ms:
            return candle
    return None


def close_return_pct(
    candles: list[dict[str, Any]],
    event_time: int,
    horizon_minutes: int,
) -> float | None:
    start = first_candle_at_or_after(candles, event_time)
    end = first_candle_at_or_after(candles, event_time + horizon_minutes * 60_000)
    if not start or not end:
        return None
    start_close = float(start["close"])
    end_close = float(end["close"])
    if start_close <= 0.0:
        return None
    return (end_close - start_close) / start_close * 100.0


def build_dataset(
    events: list[dict[str, Any]],
    candles_by_symbol: dict[str, list[dict[str, Any]]],
    market_symbols: list[str],
    horizon_minutes: list[int],
) -> list[dict[str, Any]]:
    rows = []
    for event in events:
        event_time = event.get("published_at") or event.get("fetched_at")
        if event_time is None:
            continue
        symbols = parse_json_list(event.get("symbols_json")) or market_symbols
        for symbol in symbols:
            candles = candles_by_symbol.get(symbol, [])
            if not candles:
                continue
            returns = {
                f"return_{minutes}m_pct": close_return_pct(candles, int(event_time), minutes)
                for minutes in horizon_minutes
            }
            if all(value is None for value in returns.values()):
                continue
            rows.append(
                {
                    "event_key": event.get("event_key"),
                    "source": event.get("source"),
                    "title": event.get("title"),
                    "published_at": event.get("published_at"),
                    "fetched_at": event.get("fetched_at"),
                    "event_type": event.get("event_type"),
                    "scope": event.get("scope"),
                    "sentiment": event.get("sentiment"),
                    "severity": event.get("severity"),
                    "confidence": event.get("confidence"),
                    "symbol": symbol,
                    **returns,
                }
            )
    return rows


def avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_group(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    summary: dict[str, Any] = {"events": len(rows)}
    for minutes in horizons:
        key = f"return_{minutes}m_pct"
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        summary[f"avg_{minutes}m_pct"] = avg(values)
        summary[f"positive_share_{minutes}m_pct"] = (
            sum(1 for value in values if value > 0.0) / len(values) * 100.0 if values else None
        )
        summary[f"samples_{minutes}m"] = len(values)
    return summary


def summarize(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_sentiment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_type[str(row.get("event_type") or "unknown")].append(row)
        by_sentiment[str(row.get("sentiment") or "unknown")].append(row)
        by_symbol[str(row.get("symbol") or "unknown")].append(row)
    return {
        "generated_at": int(datetime.now(tz=UTC).timestamp() * 1000),
        "rows": len(rows),
        "by_event_type": {key: summarize_group(value, horizons) for key, value in sorted(by_type.items())},
        "by_sentiment": {key: summarize_group(value, horizons) for key, value in sorted(by_sentiment.items())},
        "by_symbol": {key: summarize_group(value, horizons) for key, value in sorted(by_symbol.items())},
        "recent_rows": rows[-25:],
    }


def format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f}%"


def render_group_table(group: dict[str, dict[str, Any]], horizon: int) -> list[str]:
    if not group:
        return ["- No samples."]
    rows = []
    for name, item in sorted(
        group.items(),
        key=lambda pair: (
            -(pair[1].get(f"samples_{horizon}m") or 0),
            pair[0],
        ),
    ):
        rows.append(
            f"- `{name}`: samples `{item.get(f'samples_{horizon}m')}`, "
            f"avg `{format_pct(item.get(f'avg_{horizon}m_pct'))}`, "
            f"positive `{format_pct(item.get(f'positive_share_{horizon}m_pct'))}`"
        )
    return rows


def render_markdown(summary: dict[str, Any], primary_horizon: int) -> str:
    lines = [
        "# News Event Impact Dataset",
        "",
        f"- Generated: `{utc_text(summary['generated_at'])}`",
        f"- Event-symbol rows: `{summary['rows']}`",
        f"- Primary horizon: `{primary_horizon}m`",
        "",
        "## By Event Type",
        "",
    ]
    lines.extend(render_group_table(summary["by_event_type"], primary_horizon))
    lines.extend(["", "## By Sentiment", ""])
    lines.extend(render_group_table(summary["by_sentiment"], primary_horizon))
    lines.extend(["", "## By Symbol", ""])
    lines.extend(render_group_table(summary["by_symbol"], primary_horizon))
    lines.extend(["", "## Recent Rows", ""])
    if summary["recent_rows"]:
        for row in summary["recent_rows"]:
            lines.append(
                f"- `{utc_text(row.get('published_at') or row.get('fetched_at'))}` `{row.get('symbol')}` "
                f"`{row.get('event_type')}` `{row.get('sentiment')}` "
                f"{format_pct(row.get(f'return_{primary_horizon}m_pct'))}: {row.get('title')}"
            )
    else:
        lines.append("- No event rows with matching candle telemetry yet.")
    return "\n".join(lines) + "\n"


def parse_csv(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join classified news events to telemetry candle returns.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--since-hours", type=float, default=168.0)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--market-symbols", default=",".join(DEFAULT_MARKET_SYMBOLS))
    parser.add_argument("--horizons", default=",".join(str(item) for item in DEFAULT_HORIZON_MINUTES))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = None if args.all else since_ms_from_hours(args.since_hours)
    market_symbols = parse_csv(args.market_symbols)
    horizons = [int(item) for item in parse_csv(args.horizons)]
    with sqlite3.connect(args.db) as connection:
        events = load_events(connection, since_ms)
        event_symbols = sorted(
            {
                symbol
                for event in events
                for symbol in (parse_json_list(event.get("symbols_json")) or market_symbols)
            }
        )
        min_time = min(
            (int(event.get("published_at") or event.get("fetched_at")) for event in events),
            default=None,
        )
        candles = load_candles(connection, event_symbols, args.interval, min_time)
    rows = build_dataset(events, candles, market_symbols, horizons)
    summary = summarize(rows, horizons)
    markdown = render_markdown(summary, horizons[0])
    payload = {
        "settings": {
            "interval": args.interval,
            "market_symbols": market_symbols,
            "horizons_minutes": horizons,
            "since_ms": since_ms,
        },
        "summary": summary,
        "rows": rows,
    }

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
