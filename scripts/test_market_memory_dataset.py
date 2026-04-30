#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import market_memory_dataset as memory


def create_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE telemetry_candles (
                symbol TEXT,
                interval TEXT,
                open_time INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                fetched_at INTEGER,
                source TEXT
            );
            CREATE TABLE telemetry_funding_rates (
                symbol TEXT,
                funding_time INTEGER,
                funding_rate_bps REAL,
                mark_price REAL,
                fetched_at INTEGER,
                source TEXT
            );
            CREATE TABLE telemetry_futures_metric_rows (
                symbol TEXT,
                metric_name TEXT,
                timestamp INTEGER,
                period TEXT,
                long_short_ratio REAL,
                buy_sell_ratio REAL,
                sum_open_interest REAL,
                sum_open_interest_value REAL,
                fetched_at INTEGER,
                source TEXT
            );
            CREATE TABLE telemetry_news_events (
                event_key TEXT PRIMARY KEY,
                source TEXT,
                source_url TEXT,
                title TEXT,
                url TEXT,
                published_at INTEGER,
                fetched_at INTEGER,
                event_type TEXT,
                scope TEXT,
                sentiment TEXT,
                severity INTEGER,
                confidence REAL,
                symbols_json TEXT,
                bases_json TEXT,
                tags_json TEXT,
                summary TEXT,
                classification_json TEXT
            );
            CREATE TABLE auto_paper_decisions (
                id INTEGER PRIMARY KEY,
                strategy_version TEXT,
                symbol TEXT,
                signal_close_time INTEGER,
                decision TEXT,
                reason TEXT,
                ai_score INTEGER,
                stage TEXT,
                created_at INTEGER,
                trade_id INTEGER,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                quantity REAL,
                risk_per_unit REAL,
                risk_amount REAL
            );
            CREATE TABLE telemetry_signal_evaluations (
                strategy_version TEXT,
                symbol TEXT,
                signal_close_time INTEGER,
                generated_at INTEGER,
                captured_at INTEGER,
                stage TEXT,
                technical_stage TEXT,
                bias TEXT,
                confidence INTEGER,
                ai_score INTEGER,
                summary TEXT,
                has_risk_plan INTEGER,
                entry_price REAL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                suggested_quantity REAL,
                risk_amount REAL,
                failed_checks_json TEXT,
                checklist_json TEXT,
                warnings_json TEXT,
                journal_tags_json TEXT,
                source TEXT
            );
            """
        )
        for symbol, base in [("BTCUSDT", 100.0), ("ETHUSDT", 10.0)]:
            for index in range(0, 110):
                open_time = index * 15 * 60_000
                close = base + index * (1.0 if symbol == "BTCUSDT" else 0.2)
                connection.execute(
                    """
                    INSERT INTO telemetry_candles
                    VALUES (?, '15m', ?, ?, ?, ?, ?, ?, ?, 'fixture')
                    """,
                    (symbol, open_time, close, close, close, close, 1.0, open_time),
                )
        connection.execute(
            """
            INSERT INTO telemetry_funding_rates
            VALUES ('ETHUSDT', ?, 0.25, 20.0, ?, 'fixture')
            """,
            (96 * 15 * 60_000, 96 * 15 * 60_000),
        )
        for offset, value in [(92, 1_000.0), (96, 1_100.0)]:
            timestamp = offset * 15 * 60_000
            connection.execute(
                """
                INSERT INTO telemetry_futures_metric_rows
                VALUES ('ETHUSDT', 'open_interest_hist', ?, '5m', NULL, NULL, 10.0, ?, ?, 'fixture')
                """,
                (timestamp, value, timestamp),
            )
        connection.execute(
            """
            INSERT INTO telemetry_futures_metric_rows
            VALUES ('ETHUSDT', 'global_long_short_account_ratio', ?, '5m', 1.15, NULL, NULL, NULL, ?, 'fixture')
            """,
            (96 * 15 * 60_000, 96 * 15 * 60_000),
        )
        connection.execute(
            """
            INSERT INTO telemetry_futures_metric_rows
            VALUES ('ETHUSDT', 'taker_long_short_ratio', ?, '5m', NULL, 1.35, NULL, NULL, ?, 'fixture')
            """,
            (96 * 15 * 60_000, 96 * 15 * 60_000),
        )
        event_time = 95 * 15 * 60_000
        connection.execute(
            """
            INSERT INTO telemetry_news_events
            VALUES ('event-1', 'fixture', 'https://example.test', 'Ethereum upgrade',
                    'https://example.test/event-1', ?, ?, 'protocol_upgrade',
                    'symbol', 'positive', 4, 0.9, ?, '["ETH"]',
                    '["upgrade"]', 'fixture', '{}')
            """,
            (event_time, event_time, json.dumps(["ETHUSDT"])),
        )
        signal_time = 96 * 15 * 60_000
        connection.execute(
            """
            INSERT INTO auto_paper_decisions
            VALUES (1, 'ai_score_v2_base_score7', 'ETHUSDT', ?, 'entered',
                    'fixture', 8, 'READY', ?, NULL, 20.0, 19.5, 21.0, 1.0, 0.5, 1.0)
            """,
            (signal_time, signal_time),
        )
        connection.execute(
            """
            INSERT INTO telemetry_signal_evaluations
            VALUES ('ai_score_v2_base_score7', 'ETHUSDT', ?, ?, ?, 'READY',
                    'READY', 'bullish', 80, 8, 'fixture', 1, 20.0, 19.5,
                    21.0, 22.0, 1.0, 1.0, '[]', '[]', '[]', '[]', 'fixture')
            """,
            (signal_time, signal_time, signal_time),
        )


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        db_path = Path(raw_dir) / "memory.db"
        create_fixture(db_path)
        with sqlite3.connect(db_path) as connection:
            candles = memory.load_candles(connection, "15m", 96 * 15 * 60_000, 24 * 60 * 60 * 1000, [])
            funding = memory.load_funding(connection, 96 * 15 * 60_000, 24 * 60 * 60 * 1000, sorted(candles))
            metrics = memory.load_metrics(connection, 96 * 15 * 60_000, 24 * 60 * 60 * 1000, sorted(candles))
            news = memory.load_news_events(connection, 96 * 15 * 60_000, 24 * 60 * 60 * 1000)
            decisions = memory.load_decisions(connection, 96 * 15 * 60_000)
            signals = memory.load_signals(connection, 96 * 15 * 60_000)
        rows = memory.build_rows(candles, funding, metrics, news, decisions, signals, 96 * 15 * 60_000, [60])
        row = next(item for item in rows if item["symbol"] == "ETHUSDT" and item["open_time"] == 96 * 15 * 60_000)
        assert row["btc_regime"] in {"risk_on", "high_vol"}
        assert row["session"] == "off_hours"
        assert row["news_events_6h"] == 1
        assert row["news_symbol_events_6h"] == 1
        assert row["news_market_events_24h"] == 0
        assert row["latest_news_type"] == "protocol_upgrade"
        assert row["paper_entered"] == 1
        assert row["signal_max_ai_score"] == 8
        assert abs(row["open_interest_change_1h_pct"] - 10.0) < 1e-9
        summary = memory.summarize(rows, [60])
        markdown = memory.render_markdown(summary)
        assert "Market Memory Dataset" in markdown
        assert "Paper Entry Context" in markdown
    print("ok - 1 market memory dataset test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
