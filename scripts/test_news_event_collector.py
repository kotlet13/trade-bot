#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import news_event_collector as collector


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>SEC approves spot Bitcoin ETF as Ethereum upgrade nears</title>
      <link>https://example.test/btc-etf</link>
      <pubDate>Wed, 29 Apr 2026 10:00:00 GMT</pubDate>
      <description>ETF approval and Ethereum mainnet upgrade details.</description>
    </item>
    <item>
      <title>Solana bridge exploit drains funds</title>
      <link>https://example.test/sol-hack</link>
      <pubDate>Wed, 29 Apr 2026 11:00:00 GMT</pubDate>
      <description>Hack impacts SOL ecosystem liquidity.</description>
    </item>
  </channel>
</rss>
"""


def main() -> int:
    items = collector.parse_feed("fixture", "https://example.test/rss", RSS_FIXTURE, 10)
    assert len(items) == 2
    first = collector.classify_item(items[0], 1_000)
    assert first.event_type == "regulatory"
    assert "BTCUSDT" in first.symbols
    assert "ETHUSDT" in first.symbols
    assert first.scope == "symbol"
    assert first.severity >= 4

    second = collector.classify_item(items[1], 1_000)
    assert second.event_type == "security_incident"
    assert second.sentiment == "negative"
    assert second.symbols == ["SOLUSDT"]

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        db_path = Path(raw_dir) / "news.db"
        with sqlite3.connect(db_path) as connection:
            changed = collector.upsert_events(connection, [first, second])
            assert changed == 2
            changed_again = collector.upsert_events(connection, [first, second])
            assert changed_again == 2
            count = connection.execute("SELECT COUNT(*) FROM telemetry_news_events").fetchone()[0]
            assert count == 2

    markdown = collector.render_summary([first, second], [], changed=2)
    assert "News Event Collection" in markdown
    assert "BTCUSDT" in markdown
    print("ok - 1 news event collector test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
