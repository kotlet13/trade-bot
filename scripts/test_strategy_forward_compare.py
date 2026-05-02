#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forward_paper_report as forward
import strategy_forward_compare as compare


def create_empty_db(path: Path) -> None:
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
                technical_stage TEXT,
                final_stage TEXT,
                created_at INTEGER,
                trade_id INTEGER,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                quantity REAL,
                risk_per_unit REAL,
                risk_amount REAL,
                context_json TEXT
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
        create_empty_db(db_path)
        decisions, trades, positions = forward.load_forward_data(db_path)
        payload = compare.build_payload(
            decisions,
            trades,
            positions,
            list(compare.DEFAULT_STRATEGIES),
            min_meaningful_trades=30,
        )
        assert payload["comparison"]["sample_assessment"] == "sample_too_small"
        assert payload["promotion_allowed"] is False
        assert len(payload["strategies"]) == 2
        markdown = compare.render_markdown(payload)
        assert "sample_too_small" in markdown
        assert "Promotion allowed: `no`" in markdown
    print("ok - strategy forward compare zero-trade test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
