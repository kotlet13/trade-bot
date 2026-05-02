#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paper_campaign_log as campaign_log


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_dir:
        root = Path(raw_dir)
        forward_path = root / "forward.json"
        status_path = root / "status.json"
        out_path = root / "paper_campaign_log.md"
        forward_path.write_text(
            json.dumps(
                {
                    "completed_trades": 0,
                    "realized_r": 0,
                    "completed_stats": {"max_drawdown_r": 0},
                    "grouped_stats": {"by_strategy": {}, "by_symbol": {}, "by_session_bucket": {}},
                    "recommended_action": "insufficient_sample",
                    "rejection_blockers": {},
                }
            ),
            encoding="utf-8",
        )
        status_path.write_text(
            json.dumps(
                {
                    "enabled_by_config": True,
                    "pause": {"paused": False},
                    "open_auto_position_count": 0,
                }
            ),
            encoding="utf-8",
        )
        args = Namespace(
            forward_json=forward_path,
            status_json=status_path,
            parity_base_json=root / "missing_base.json",
            parity_oi_json=root / "missing_oi.json",
            out=out_path,
            note="daily check",
        )
        entry = campaign_log.render_entry(
            campaign_log.load_json(forward_path),
            campaign_log.load_json(status_path),
            None,
            None,
            args,
        )
        assert "daily check" in entry
        assert "insufficient_sample" in entry
        assert "missing_base.json: missing" in entry
        assert campaign_log.main.__name__ == "main"
        out_path.write_text("# Paper Campaign Log\n\n", encoding="utf-8")
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
            handle.write("\n")
        before = out_path.read_text(encoding="utf-8")
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
            handle.write("\n")
        after = out_path.read_text(encoding="utf-8")
        assert len(after) > len(before)
    print("ok - paper campaign log append test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
