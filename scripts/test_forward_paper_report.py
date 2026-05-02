#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forward_paper_report as report


def create_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
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
            )
            """
        )
        connection.execute(
            """
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
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE positions (
                symbol TEXT,
                quantity REAL,
                avg_price REAL,
                stop_loss REAL,
                take_profit REAL,
                note TEXT,
                updated_at INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO auto_paper_decisions (
                id, strategy_version, symbol, signal_close_time, decision, reason,
                ai_score, stage, created_at, trade_id, entry_price, stop_loss,
                take_profit, quantity, risk_per_unit, risk_amount
            ) VALUES
                (1, 'ai_score_v2_base_score7', 'ETHUSDT', 1000, 'entered', NULL,
                 8, 'READY', 1100, 10, 100.0, 95.0, 105.0, 2.0, 5.0, 10.0),
                (2, 'ai_score_v2_base_score7', 'SOLUSDT', 2000, 'rejected',
                 'SOL technical setup blocked. Failed checks: Score funding, AI score v2.',
                 5, 'SETUP', 2100, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO trades (
                id, symbol, side, quantity, price, gross_value, fee_paid,
                realized_pnl, note, source, source_order_id, executed_at
            ) VALUES
                (10, 'ETHUSDT', 'BUY', 2.0, 100.0, 200.0, 0.2, 0.0,
                 'auto entry', 'AUTO_PAPER_MARKET', NULL, 1100),
                (11, 'ETHUSDT', 'SELL', 2.0, 105.0, 210.0, 0.21, 9.79,
                 'tp', 'AUTO_TAKE_PROFIT', NULL, 2200)
            """
        )


def create_empty_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
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
            )
            """
        )
        connection.execute(
            """
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
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE positions (
                symbol TEXT,
                quantity REAL,
                avg_price REAL,
                stop_loss REAL,
                take_profit REAL,
                note TEXT,
                updated_at INTEGER
            )
            """
        )


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        db_path = Path(raw_dir) / "paper.db"
        create_fixture(db_path)
        decisions, trades, positions = report.load_forward_data(db_path)
        summary = report.summarize(decisions, trades, positions)
        assert summary["decision_counts"]["entered"] == 1
        assert summary["decision_counts"]["rejected"] == 1
        assert summary["completed_trades"] == 1
        assert abs(summary["realized_r"] - 0.979) < 1e-9
        assert summary["rejection_blockers"]["Score funding"] == 1
        assert summary["rejection_blockers"]["AI score v2"] == 1
        assert summary["grouped_stats"]["by_strategy"]["ai_score_v2_base_score7"]["count"] == 1
        assert "sample_too_small" in summary["campaign_status"]
        assert "promotion_not_allowed" in summary["campaign_status"]
        assert summary["recommended_action"] == "insufficient_sample"
        assert summary["per_strategy_campaign"]["ai_score_v2_base_score7"]["completed_trades"] == 1
        assert report.session_bucket(int(datetime(2026, 5, 1, 15, 30, tzinfo=UTC).timestamp() * 1000)) == "london_ny_overlap"
        assert report.session_bucket(int(datetime(2026, 5, 1, 16, 0, tzinfo=UTC).timestamp() * 1000)) == "new_york"
        markdown = report.render_markdown(summary, decisions)
        assert "Forward Paper Report" in markdown
        assert "Campaign Status" in markdown
        assert "ETHUSDT" in markdown
        empty_db_path = Path(raw_dir) / "empty.db"
        create_empty_fixture(empty_db_path)
        empty_decisions, empty_trades, empty_positions = report.load_forward_data(empty_db_path)
        empty_summary = report.summarize(empty_decisions, empty_trades, empty_positions)
        assert empty_summary["completed_trades"] == 0
        assert empty_summary["recommended_action"] == "insufficient_sample"
        assert "sample_too_small" in empty_summary["campaign_status"]
        empty_markdown = report.render_markdown(empty_summary, empty_decisions)
        assert "No decisions yet." in empty_markdown
    print("ok - 2 forward paper report tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
