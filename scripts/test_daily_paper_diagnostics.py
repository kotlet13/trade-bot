#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import daily_paper_diagnostics as diagnostics


def main() -> int:
    run = diagnostics.run_health_check("http://127.0.0.1:9", timeout_seconds=0.1)
    assert run.name == "app_health"
    assert not run.ok
    markdown = diagnostics.render_markdown([run], ["runtime/harness parity; app health check failed"])
    assert "runtime/harness parity" in markdown
    assert "failed" in markdown
    print("ok - daily diagnostics health skip test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
