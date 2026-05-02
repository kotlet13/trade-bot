#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backup_paper_db as backup


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        root = Path(raw_dir)
        db_path = root / "tradebot.db"
        out_dir = root / "backups"
        db_path.write_bytes(b"sqlite-test")

        values = iter(["20260502_000001", "20260502_000002", "20260502_000003"])
        original_timestamp = backup.timestamp
        backup.timestamp = lambda: next(values)
        try:
            first = backup.create_backup(db_path, out_dir)
            second = backup.create_backup(db_path, out_dir, compress=True)
            third = backup.create_backup(db_path, out_dir, keep_last=2)
        finally:
            backup.timestamp = original_timestamp

        assert first.name == "tradebot_20260502_000001.db"
        assert second.name == "tradebot_20260502_000002.db.gz"
        assert third.name == "tradebot_20260502_000003.db"
        assert db_path.exists()
        backups = backup.matching_backups(out_dir)
        assert len(backups) == 2
        assert first not in backups
        try:
            backup.create_backup(root / "missing.db", out_dir)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing DB should fail gracefully")
    print("ok - backup paper db test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
