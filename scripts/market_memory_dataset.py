#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/tradebot.db")
DEFAULT_INTERVAL = "15m"
DEFAULT_SINCE_HOURS = 168.0
DEFAULT_HORIZON_MINUTES = [60, 240]
HALVING_TIMES_MS = [
    int(datetime(2012, 11, 28, tzinfo=UTC).timestamp() * 1000),
    int(datetime(2016, 7, 9, tzinfo=UTC).timestamp() * 1000),
    int(datetime(2020, 5, 11, tzinfo=UTC).timestamp() * 1000),
    int(datetime(2024, 4, 20, tzinfo=UTC).timestamp() * 1000),
]


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


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0.0:
        return None
    return (end - start) / start * 100.0


def stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


class TimeSeries:
    def __init__(self, rows: list[dict[str, Any]], time_column: str) -> None:
        self.rows = sorted(rows, key=lambda row: int(row.get(time_column) or 0))
        self.time_column = time_column
        self.times = [int(row.get(time_column) or 0) for row in self.rows]

    def at_or_before(self, timestamp_ms: int) -> dict[str, Any] | None:
        index = bisect.bisect_right(self.times, timestamp_ms) - 1
        if index < 0:
            return None
        return self.rows[index]

    def at_or_after(self, timestamp_ms: int) -> dict[str, Any] | None:
        index = bisect.bisect_left(self.times, timestamp_ms)
        if index >= len(self.rows):
            return None
        return self.rows[index]

    def window(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        start = bisect.bisect_left(self.times, start_ms)
        end = bisect.bisect_right(self.times, end_ms)
        return self.rows[start:end]


def load_candles(
    connection: sqlite3.Connection,
    interval: str,
    since_ms: int | None,
    lookback_ms: int,
    symbols: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not table_exists(connection, "telemetry_candles"):
        return {}
    params: list[Any] = [interval]
    where = "WHERE interval = ?"
    if since_ms is not None:
        where += " AND open_time >= ?"
        params.append(since_ms - lookback_ms)
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        where += f" AND symbol IN ({placeholders})"
        params.extend(symbols)
    rows = row_dicts(
        connection.cursor(),
        f"""
        SELECT symbol, interval, open_time, open, high, low, close, volume, fetched_at, source
        FROM telemetry_candles
        {where}
        ORDER BY symbol ASC, open_time ASC
        """,
        tuple(params),
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["symbol"])].append(row)
    return dict(grouped)


def load_funding(
    connection: sqlite3.Connection,
    since_ms: int | None,
    lookback_ms: int,
    symbols: list[str],
) -> dict[str, TimeSeries]:
    if not table_exists(connection, "telemetry_funding_rates"):
        return {}
    params: list[Any] = []
    where = ""
    clauses = []
    if since_ms is not None:
        clauses.append("funding_time >= ?")
        params.append(since_ms - lookback_ms)
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        clauses.append(f"symbol IN ({placeholders})")
        params.extend(symbols)
    if clauses:
        where = "WHERE " + " AND ".join(clauses)
    rows = row_dicts(
        connection.cursor(),
        f"""
        SELECT symbol, funding_time, funding_rate_bps, mark_price, fetched_at, source
        FROM telemetry_funding_rates
        {where}
        ORDER BY symbol ASC, funding_time ASC
        """,
        tuple(params),
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["symbol"])].append(row)
    return {symbol: TimeSeries(items, "funding_time") for symbol, items in grouped.items()}


def load_metrics(
    connection: sqlite3.Connection,
    since_ms: int | None,
    lookback_ms: int,
    symbols: list[str],
) -> dict[str, dict[str, TimeSeries]]:
    if not table_exists(connection, "telemetry_futures_metric_rows"):
        return {}
    params: list[Any] = []
    clauses = []
    if since_ms is not None:
        clauses.append("timestamp >= ?")
        params.append(since_ms - lookback_ms)
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        clauses.append(f"symbol IN ({placeholders})")
        params.extend(symbols)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = row_dicts(
        connection.cursor(),
        f"""
        SELECT symbol, metric_name, timestamp, period, long_short_ratio, buy_sell_ratio,
               sum_open_interest, sum_open_interest_value, fetched_at, source
        FROM telemetry_futures_metric_rows
        {where}
        ORDER BY symbol ASC, metric_name ASC, timestamp ASC
        """,
        tuple(params),
    )
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[str(row["symbol"])][str(row["metric_name"])].append(row)
    return {
        symbol: {metric: TimeSeries(items, "timestamp") for metric, items in metrics.items()}
        for symbol, metrics in grouped.items()
    }


def load_news_events(connection: sqlite3.Connection, since_ms: int | None, lookback_ms: int) -> list[dict[str, Any]]:
    if not table_exists(connection, "telemetry_news_events"):
        return []
    where = ""
    params: tuple[Any, ...] = ()
    if since_ms is not None:
        where = "WHERE COALESCE(published_at, fetched_at) >= ?"
        params = (since_ms - lookback_ms,)
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


def load_decisions(connection: sqlite3.Connection, since_ms: int | None) -> dict[tuple[str, int], list[dict[str, Any]]]:
    if not table_exists(connection, "auto_paper_decisions"):
        return {}
    where = "WHERE created_at >= ?" if since_ms is not None else ""
    params = (since_ms,) if since_ms is not None else ()
    rows = row_dicts(
        connection.cursor(),
        f"SELECT * FROM auto_paper_decisions {where} ORDER BY created_at ASC",
        params,
    )
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol") or "")
        signal_close_time = row.get("signal_close_time")
        if symbol and signal_close_time is not None:
            grouped[(symbol, int(signal_close_time))].append(row)
    return dict(grouped)


def load_signals(connection: sqlite3.Connection, since_ms: int | None) -> dict[tuple[str, int], list[dict[str, Any]]]:
    if not table_exists(connection, "telemetry_signal_evaluations"):
        return {}
    where = "WHERE captured_at >= ?" if since_ms is not None else ""
    params = (since_ms,) if since_ms is not None else ()
    rows = row_dicts(
        connection.cursor(),
        f"SELECT * FROM telemetry_signal_evaluations {where} ORDER BY captured_at ASC",
        params,
    )
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol = str(row.get("symbol") or "")
        signal_close_time = row.get("signal_close_time")
        if symbol and signal_close_time is not None:
            grouped[(symbol, int(signal_close_time))].append(row)
    return dict(grouped)


def session_label(timestamp_ms: int) -> str:
    hour = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).hour
    if 7 <= hour < 13:
        return "london"
    if 13 <= hour < 22:
        return "new_york"
    return "off_hours"


def calendar_features(timestamp_ms: int) -> dict[str, Any]:
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    last_halving = max((item for item in HALVING_TIMES_MS if item <= timestamp_ms), default=None)
    if last_halving is None:
        days_since = None
        quarter = None
    else:
        days_since = int((timestamp_ms - last_halving) / 86_400_000)
        quarter = min(4, days_since // 365 + 1)
    return {
        "utc_hour": dt.hour,
        "day_of_week": dt.weekday(),
        "month": dt.month,
        "session": session_label(timestamp_ms),
        "btc_days_since_halving": days_since,
        "btc_cycle_quarter": quarter,
    }


def close_at(series: TimeSeries | None, timestamp_ms: int, direction: str = "before") -> float | None:
    if series is None:
        return None
    row = series.at_or_before(timestamp_ms) if direction == "before" else series.at_or_after(timestamp_ms)
    return safe_float(row.get("close")) if row else None


def return_over(series: TimeSeries | None, timestamp_ms: int, minutes: int) -> float | None:
    return pct_change(close_at(series, timestamp_ms - minutes * 60_000), close_at(series, timestamp_ms))


def forward_return(series: TimeSeries | None, timestamp_ms: int, minutes: int) -> float | None:
    return pct_change(close_at(series, timestamp_ms), close_at(series, timestamp_ms + minutes * 60_000, "after"))


def realized_vol(series: TimeSeries | None, timestamp_ms: int, minutes: int) -> float | None:
    if series is None:
        return None
    rows = series.window(timestamp_ms - minutes * 60_000, timestamp_ms)
    returns = []
    previous_close: float | None = None
    for row in rows:
        close = safe_float(row.get("close"))
        if previous_close is not None and close is not None and previous_close > 0.0:
            returns.append((close - previous_close) / previous_close * 100.0)
        previous_close = close
    return stddev(returns)


def drawdown(series: TimeSeries | None, timestamp_ms: int, minutes: int) -> float | None:
    if series is None:
        return None
    rows = series.window(timestamp_ms - minutes * 60_000, timestamp_ms)
    closes = [safe_float(row.get("close")) for row in rows]
    closes = [value for value in closes if value is not None]
    current = close_at(series, timestamp_ms)
    if not closes or current is None:
        return None
    high = max(closes)
    if high <= 0.0:
        return None
    return (current - high) / high * 100.0


def btc_regime_label(return_24h_pct: float | None, drawdown_24h_pct: float | None, vol_24h_pct: float | None) -> str:
    if return_24h_pct is None:
        return "unknown"
    if return_24h_pct <= -2.0 or (drawdown_24h_pct is not None and drawdown_24h_pct <= -5.0):
        return "risk_off"
    if vol_24h_pct is not None and vol_24h_pct >= 0.35:
        return "high_vol"
    if return_24h_pct >= 1.0:
        return "risk_on"
    return "neutral"


def metric_value_at(
    metrics: dict[str, dict[str, TimeSeries]],
    symbol: str,
    metric_name: str,
    timestamp_ms: int,
    value_column: str,
) -> float | None:
    series = metrics.get(symbol, {}).get(metric_name)
    row = series.at_or_before(timestamp_ms) if series else None
    return safe_float(row.get(value_column)) if row else None


def oi_change_pct(metrics: dict[str, dict[str, TimeSeries]], symbol: str, timestamp_ms: int, minutes: int) -> float | None:
    series = metrics.get(symbol, {}).get("open_interest_hist")
    if series is None:
        return None
    current = series.at_or_before(timestamp_ms)
    previous = series.at_or_before(timestamp_ms - minutes * 60_000)
    return pct_change(
        safe_float(previous.get("sum_open_interest_value")) if previous else None,
        safe_float(current.get("sum_open_interest_value")) if current else None,
    )


def event_time(event: dict[str, Any]) -> int:
    return int(event.get("published_at") or event.get("fetched_at") or 0)


def event_applies_to_symbol(event: dict[str, Any], symbol: str) -> bool:
    symbols = [str(item) for item in parse_json_list(event.get("symbols_json"))]
    return not symbols or symbol in symbols


def news_features(news_events: list[dict[str, Any]], symbol: str, timestamp_ms: int) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    count_6h = 0
    count_24h = 0
    symbol_count_6h = 0
    symbol_count_24h = 0
    market_count_24h = 0
    negative_24h = 0
    macro_24h = 0
    max_severity_24h = 0
    for event in news_events:
        time_ms = event_time(event)
        event_symbols = [str(item) for item in parse_json_list(event.get("symbols_json"))]
        is_symbol_event = symbol in event_symbols
        is_market_event = not event_symbols
        if time_ms > timestamp_ms or not (is_symbol_event or is_market_event):
            continue
        age_ms = timestamp_ms - time_ms
        if age_ms <= 6 * 60 * 60 * 1000:
            count_6h += 1
            if is_symbol_event:
                symbol_count_6h += 1
        if age_ms <= 24 * 60 * 60 * 1000:
            count_24h += 1
            if is_symbol_event:
                symbol_count_24h += 1
            if is_market_event:
                market_count_24h += 1
            if str(event.get("sentiment") or "") == "negative":
                negative_24h += 1
            if str(event.get("event_type") or "") == "macro_policy":
                macro_24h += 1
            max_severity_24h = max(max_severity_24h, int(event.get("severity") or 0))
        if latest is None or time_ms > event_time(latest):
            latest = event
    minutes_since_latest = None
    latest_type = None
    latest_sentiment = None
    latest_severity = None
    if latest is not None:
        minutes_since_latest = (timestamp_ms - event_time(latest)) / 60_000
        latest_type = latest.get("event_type")
        latest_sentiment = latest.get("sentiment")
        latest_severity = latest.get("severity")
    return {
        "news_events_6h": count_6h,
        "news_events_24h": count_24h,
        "news_symbol_events_6h": symbol_count_6h,
        "news_symbol_events_24h": symbol_count_24h,
        "news_market_events_24h": market_count_24h,
        "news_negative_24h": negative_24h,
        "news_macro_24h": macro_24h,
        "news_max_severity_24h": max_severity_24h,
        "minutes_since_latest_news": minutes_since_latest,
        "latest_news_type": latest_type,
        "latest_news_sentiment": latest_sentiment,
        "latest_news_severity": latest_severity,
    }


def signal_features(signals: list[dict[str, Any]]) -> dict[str, Any]:
    if not signals:
        return {
            "signal_count": 0,
            "signal_max_ai_score": None,
            "signal_best_stage": None,
            "signal_best_technical_stage": None,
            "signal_failed_checks": None,
        }
    best = max(signals, key=lambda item: int(item.get("ai_score") or 0))
    failed_checks = Counter()
    for signal in signals:
        failed_checks.update(str(item) for item in parse_json_list(signal.get("failed_checks_json")))
    return {
        "signal_count": len(signals),
        "signal_max_ai_score": int(best.get("ai_score") or 0),
        "signal_best_stage": best.get("stage"),
        "signal_best_technical_stage": best.get("technical_stage"),
        "signal_failed_checks": ",".join(name for name, _ in failed_checks.most_common(5)) or None,
    }


def decision_features(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    if not decisions:
        return {
            "paper_decision_count": 0,
            "paper_entered": 0,
            "paper_rejected": 0,
            "paper_decisions": None,
            "paper_strategies": None,
            "paper_max_ai_score": None,
        }
    decision_counts = Counter(str(item.get("decision") or "unknown") for item in decisions)
    strategies = sorted({str(item.get("strategy_version") or "unknown") for item in decisions})
    scores = [int(item.get("ai_score") or 0) for item in decisions]
    return {
        "paper_decision_count": len(decisions),
        "paper_entered": decision_counts.get("entered", 0),
        "paper_rejected": decision_counts.get("rejected", 0),
        "paper_decisions": ",".join(f"{name}:{count}" for name, count in sorted(decision_counts.items())),
        "paper_strategies": ",".join(strategies),
        "paper_max_ai_score": max(scores) if scores else None,
    }


def build_rows(
    candles_by_symbol: dict[str, list[dict[str, Any]]],
    funding: dict[str, TimeSeries],
    metrics: dict[str, dict[str, TimeSeries]],
    news_events: list[dict[str, Any]],
    decisions: dict[tuple[str, int], list[dict[str, Any]]],
    signals: dict[tuple[str, int], list[dict[str, Any]]],
    since_ms: int | None,
    horizons: list[int],
) -> list[dict[str, Any]]:
    series_by_symbol = {symbol: TimeSeries(rows, "open_time") for symbol, rows in candles_by_symbol.items()}
    btc_series = series_by_symbol.get("BTCUSDT")
    rows: list[dict[str, Any]] = []
    for symbol, candle_rows in sorted(candles_by_symbol.items()):
        symbol_series = series_by_symbol[symbol]
        for candle in candle_rows:
            open_time = int(candle.get("open_time") or 0)
            if since_ms is not None and open_time < since_ms:
                continue
            close = safe_float(candle.get("close"))
            btc_ret_24h = return_over(btc_series, open_time, 1440)
            btc_drawdown_24h = drawdown(btc_series, open_time, 1440)
            btc_vol_24h = realized_vol(btc_series, open_time, 1440)
            symbol_ret_4h = return_over(symbol_series, open_time, 240)
            btc_ret_4h = return_over(btc_series, open_time, 240)
            funding_row = funding.get(symbol).at_or_before(open_time) if symbol in funding else None
            row: dict[str, Any] = {
                "symbol": symbol,
                "open_time": open_time,
                "close": close,
                "volume": safe_float(candle.get("volume")),
                **calendar_features(open_time),
                "btc_return_24h_pct": btc_ret_24h,
                "btc_drawdown_24h_pct": btc_drawdown_24h,
                "btc_realized_vol_24h_pct": btc_vol_24h,
                "btc_regime": btc_regime_label(btc_ret_24h, btc_drawdown_24h, btc_vol_24h),
                "symbol_return_1h_pct": return_over(symbol_series, open_time, 60),
                "symbol_return_4h_pct": symbol_ret_4h,
                "relative_return_4h_pct": (
                    symbol_ret_4h - btc_ret_4h if symbol_ret_4h is not None and btc_ret_4h is not None else None
                ),
                "funding_rate_bps": safe_float(funding_row.get("funding_rate_bps")) if funding_row else None,
                "global_long_short_ratio": metric_value_at(
                    metrics, symbol, "global_long_short_account_ratio", open_time, "long_short_ratio"
                ),
                "taker_buy_sell_ratio": metric_value_at(metrics, symbol, "taker_long_short_ratio", open_time, "buy_sell_ratio"),
                "top_position_long_short_ratio": metric_value_at(
                    metrics, symbol, "top_long_short_position_ratio", open_time, "long_short_ratio"
                ),
                "open_interest_value": metric_value_at(
                    metrics, symbol, "open_interest_hist", open_time, "sum_open_interest_value"
                ),
                "open_interest_change_1h_pct": oi_change_pct(metrics, symbol, open_time, 60),
                **news_features(news_events, symbol, open_time),
                **signal_features(signals.get((symbol, open_time), [])),
                **decision_features(decisions.get((symbol, open_time), [])),
            }
            for minutes in horizons:
                row[f"forward_return_{minutes}m_pct"] = forward_return(symbol_series, open_time, minutes)
            rows.append(row)
    return rows


def summarize_group(rows: list[dict[str, Any]], primary_horizon: int) -> dict[str, Any]:
    key = f"forward_return_{primary_horizon}m_pct"
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return {
        "rows": len(rows),
        "samples": len(values),
        "avg_forward_pct": avg(values),
        "positive_share_pct": (sum(1 for value in values if value > 0.0) / len(values) * 100.0 if values else None),
        "paper_entries": sum(int(row.get("paper_entered") or 0) for row in rows),
        "paper_rejections": sum(int(row.get("paper_rejected") or 0) for row in rows),
    }


def summarize_by(rows: list[dict[str, Any]], group_key: str, primary_horizon: int) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(group_key) if row.get(group_key) is not None else "unknown")].append(row)
    return {key: summarize_group(value, primary_horizon) for key, value in sorted(grouped.items())}


def summarize(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    primary = horizons[0]
    event_presence_rows = []
    for row in rows:
        enriched = dict(row)
        enriched["news_presence"] = "recent_news" if int(row.get("news_events_24h") or 0) > 0 else "no_recent_news"
        event_presence_rows.append(enriched)
    return {
        "generated_at": int(datetime.now(tz=UTC).timestamp() * 1000),
        "rows": len(rows),
        "symbols": len({row.get("symbol") for row in rows}),
        "time_range": {
            "first": min((int(row["open_time"]) for row in rows), default=None),
            "last": max((int(row["open_time"]) for row in rows), default=None),
        },
        "primary_horizon_minutes": primary,
        "by_btc_regime": summarize_by(rows, "btc_regime", primary),
        "by_session": summarize_by(rows, "session", primary),
        "by_news_presence": summarize_by(event_presence_rows, "news_presence", primary),
        "by_symbol": summarize_by(rows, "symbol", primary),
        "paper_entry_rows": [row for row in rows if int(row.get("paper_entered") or 0) > 0],
        "recent_rows": rows[-25:],
    }


def format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f}%"


def render_group_table(group: dict[str, dict[str, Any]]) -> list[str]:
    if not group:
        return ["- No rows."]
    lines = []
    for name, item in sorted(group.items(), key=lambda pair: (-(pair[1].get("samples") or 0), pair[0])):
        lines.append(
            f"- `{name}`: rows `{item['rows']}`, samples `{item['samples']}`, "
            f"avg `{format_pct(item['avg_forward_pct'])}`, "
            f"positive `{format_pct(item['positive_share_pct'])}`, "
            f"paper entries `{item['paper_entries']}`"
        )
    return lines


def render_markdown(summary: dict[str, Any]) -> str:
    primary = int(summary["primary_horizon_minutes"])
    lines = [
        "# Market Memory Dataset",
        "",
        f"- Generated: `{utc_text(summary['generated_at'])}`",
        f"- Rows: `{summary['rows']}`",
        f"- Symbols: `{summary['symbols']}`",
        f"- Time range: `{utc_text(summary['time_range']['first'])}` to `{utc_text(summary['time_range']['last'])}`",
        f"- Primary horizon: `{primary}m`",
        "",
        "## BTC Regime",
        "",
    ]
    lines.extend(render_group_table(summary["by_btc_regime"]))
    lines.extend(["", "## Session", ""])
    lines.extend(render_group_table(summary["by_session"]))
    lines.extend(["", "## News Presence", ""])
    lines.extend(render_group_table(summary["by_news_presence"]))
    lines.extend(["", "## Symbol", ""])
    lines.extend(render_group_table(summary["by_symbol"]))
    lines.extend(["", "## Paper Entry Context", ""])
    if summary["paper_entry_rows"]:
        for row in summary["paper_entry_rows"][-10:]:
            lines.append(
                f"- `{utc_text(row['open_time'])}` `{row['symbol']}` regime `{row['btc_regime']}` "
                f"session `{row['session']}` score `{row.get('paper_max_ai_score')}` "
                f"symbolNews24h `{row.get('news_symbol_events_24h')}` "
                f"marketNews24h `{row.get('news_market_events_24h')}` "
                f"forward `{format_pct(row.get(f'forward_return_{primary}m_pct'))}`"
            )
    else:
        lines.append("- No paper entries matched the market-memory rows.")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market-memory features from runtime telemetry.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--since-hours", type=float, default=DEFAULT_SINCE_HOURS)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--symbols", help="Comma-separated symbol override. Defaults to all archived candle symbols.")
    parser.add_argument("--horizons", default=",".join(str(item) for item in DEFAULT_HORIZON_MINUTES))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    since_ms = None if args.all else since_ms_from_hours(args.since_hours)
    symbols = parse_csv(args.symbols)
    horizons = [int(item) for item in parse_csv(args.horizons)]
    lookback_ms = max(24 * 60 * 60 * 1000, max(horizons, default=0) * 60_000)
    with sqlite3.connect(args.db, timeout=30.0) as connection:
        connection.execute("PRAGMA busy_timeout = 30000")
        candles = load_candles(connection, args.interval, since_ms, lookback_ms, symbols)
        all_symbols = sorted(candles)
        funding = load_funding(connection, since_ms, lookback_ms, all_symbols)
        metrics = load_metrics(connection, since_ms, lookback_ms, all_symbols)
        news = load_news_events(connection, since_ms, lookback_ms)
        decisions = load_decisions(connection, since_ms)
        signals = load_signals(connection, since_ms)

    rows = build_rows(candles, funding, metrics, news, decisions, signals, since_ms, horizons)
    summary = summarize(rows, horizons)
    markdown = render_markdown(summary)
    payload = {
        "settings": {
            "interval": args.interval,
            "since_ms": since_ms,
            "symbols": symbols or all_symbols,
            "horizons_minutes": horizons,
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
