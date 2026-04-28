#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import runtime_harness_parity as parity


def main() -> int:
    assert parity.parse_symbols(" ethusdt, SOLUSDT ,,") == ["ETHUSDT", "SOLUSDT"]
    row = parity.ParityRow(
        symbol="ETHUSDT",
        runtime_stage="wait",
        python_stage="wait",
        runtime_technical_stage="wait",
        python_technical_stage="wait",
        runtime_ai_score=0,
        python_ai_score=0,
        runtime_risk_plan=False,
        python_risk_plan=False,
        signal_close_time=1_775_000_000_000,
        generated_at=1_775_000_000_000,
        status="pass",
        notes=[],
    )
    markdown = parity.render_markdown([row])
    assert "Runtime/Harness Parity Report" in markdown
    assert "ETHUSDT" in markdown
    assert "`pass`" in markdown
    print("ok - 1 runtime harness parity test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
