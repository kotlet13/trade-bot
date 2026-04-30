#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import news_event_impact_dataset as impact


def create_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
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
            """
        )
        connection.execute(
            """
            INSERT INTO telemetry_news_events
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "fixture",
                "https://example.test",
                "Ethereum upgrade ships",
                "https://example.test/event-1",
                1_000,
                1_000,
                "protocol_upgrade",
                "symbol",
                "positive",
                4,
                0.9,
                json.dumps(["ETHUSDT"]),
                json.dumps(["ETH"]),
                json.dumps(["upgrade"]),
                "fixture",
                "{}",
            ),
        )
        candles = [
            ("ETHUSDT", "15m", 1_000, 100.0),
            ("ETHUSDT", "15m", 61_000, 102.0),
            ("ETHUSDT", "15m", 241_000, 104.0),
            ("ETHUSDT", "15m", 1_441_000, 108.0),
        ]
        for symbol, interval, open_time, close in candles:
            connection.execute(
                """
                INSERT INTO telemetry_candles
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, interval, open_time, close, close, close, close, 1.0, open_time, "fixture"),
            )


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        db_path = Path(raw_dir) / "impact.db"
        create_fixture(db_path)
        with sqlite3.connect(db_path) as connection:
            events = impact.load_events(connection, None)
            candles = impact.load_candles(connection, ["ETHUSDT"], "15m", None)
        rows = impact.build_dataset(events, candles, ["BTCUSDT"], [1, 4, 24])
        assert len(rows) == 1
        assert abs(rows[0]["return_1m_pct"] - 2.0) < 1e-9
        summary = impact.summarize(rows, [1, 4, 24])
        assert summary["by_event_type"]["protocol_upgrade"]["events"] == 1
        markdown = impact.render_markdown(summary, 1)
        assert "News Event Impact Dataset" in markdown
        assert "ETHUSDT" in markdown
    print("ok - 1 news event impact dataset test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
