#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runtime_telemetry_report as report


def create_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE telemetry_market_tickers (
                symbol TEXT,
                snapshot_time INTEGER,
                last_price REAL,
                price_change_percent REAL,
                high_price REAL,
                low_price REAL,
                volume REAL,
                quote_volume REAL,
                source TEXT
            );
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
            CREATE TABLE telemetry_news_events (
                event_key TEXT,
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
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                gross_value REAL,
                fee_paid REAL,
                realized_pnl REAL,
                note TEXT,
                source TEXT,
                source_order_id INTEGER,
                executed_at INTEGER
            );
            CREATE TABLE positions (
                symbol TEXT,
                quantity REAL,
                avg_price REAL,
                stop_loss REAL,
                take_profit REAL,
                note TEXT,
                updated_at INTEGER
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO telemetry_market_tickers
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("ETHUSDT", 1_000, 100.0, 2.0, 105.0, 95.0, 10.0, 1000.0, "fixture"),
                ("SOLUSDT", 1_000, 50.0, -1.0, 55.0, 45.0, 20.0, 2000.0, "fixture"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO telemetry_candles
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("ETHUSDT", "15m", 900, 99.0, 101.0, 98.0, 100.0, 1.0, 1_000, "fixture"),
                ("SOLUSDT", "15m", 900, 51.0, 52.0, 49.0, 50.0, 1.0, 1_000, "fixture"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO telemetry_funding_rates
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("ETHUSDT", 900, 0.5, 100.0, 1_000, "fixture"),
                ("SOLUSDT", 900, -1.5, 50.0, 1_000, "fixture"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO telemetry_futures_metric_rows
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("ETHUSDT", "global_long_short_account_ratio", 900, "5m", 1.1, None, None, None, 1_000, "fixture"),
                ("SOLUSDT", "global_long_short_account_ratio", 900, "5m", 1.3, None, None, None, 1_000, "fixture"),
                ("ETHUSDT", "taker_long_short_ratio", 900, "5m", None, 1.4, None, None, 1_000, "fixture"),
                ("SOLUSDT", "open_interest_hist", 900, "5m", None, None, 10.0, 1000.0, 1_000, "fixture"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO telemetry_signal_evaluations
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "ai_score_v2_base_score7",
                    "ETHUSDT",
                    900,
                    1_000,
                    1_000,
                    "SETUP",
                    "READY",
                    "bullish",
                    80,
                    6,
                    "blocked",
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    '["AI score v2","Session filter"]',
                    "[]",
                    "[]",
                    "[]",
                    "fixture",
                ),
                (
                    "ai_score_v2_ablate_oi",
                    "SOLUSDT",
                    900,
                    1_000,
                    1_000,
                    "WAIT",
                    "WAIT",
                    "neutral",
                    15,
                    0,
                    "wait",
                    0,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    '["4h trend"]',
                    "[]",
                    "[]",
                    "[]",
                    "fixture",
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO telemetry_news_events
            VALUES ('event-1', 'fixture', 'https://example.test', 'Ethereum upgrade',
                    'https://example.test/event-1', 1000, 1000, 'protocol_upgrade',
                    'symbol', 'positive', 4, 0.9, '["ETHUSDT"]', '["ETH"]',
                    '["upgrade"]', 'fixture', '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO telemetry_news_events
            VALUES ('event-2', 'fixture', 'https://example.test', 'Older market story',
                    'https://example.test/event-2', 500, 2000, 'general_news',
                    'market', 'neutral', 1, 0.4, '[]', '[]',
                    '[]', 'fixture', '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO auto_paper_decisions
            VALUES (1, 'ai_score_v2_base_score7', 'ETHUSDT', 900, 'rejected',
                    'blocked', 6, 'SETUP', 1000, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO trades
            VALUES (1, 'ETHUSDT', 'SELL', 1.0, 105.0, 105.0, 0.1, 5.0,
                    'exit', 'AUTO_TAKE_PROFIT', NULL, 1100)
            """
        )


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        db_path = Path(raw_dir) / "telemetry.db"
        create_fixture(db_path)
        data = report.load_data(db_path, None)
        summary = report.summarize(data, None)
        assert summary["row_counts"]["signals"] == 2
        assert summary["market"]["ticker_symbols"] == 2
        assert summary["news"]["events_total"] == 2
        assert summary["news"]["event_type_counts"]["protocol_upgrade"] == 1
        assert summary["news"]["recent_events"][0]["title"] == "Ethereum upgrade"
        assert summary["market"]["positive_24h_share_pct"] == 50.0
        assert summary["futures"]["funding_symbols"] == 2
        assert summary["signals"]["technical_ready_count"] == 1
        assert summary["signals"]["blocked_ready_count"] == 1
        assert summary["signals"]["failed_check_counts"]["AI score v2"] == 1
        assert summary["paper"]["decision_counts"]["rejected"] == 1
        markdown = report.render_markdown(summary)
        assert "Runtime Telemetry Report" in markdown
        assert "Recent blocked READY setups" in markdown
        assert "ETHUSDT" in markdown
    print("ok - 1 runtime telemetry report test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
