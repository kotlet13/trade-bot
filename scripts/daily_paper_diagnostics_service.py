#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def main() -> int:
    interval_seconds = env_int("PAPER_DIAGNOSTICS_INTERVAL_SECONDS", 21600)
    since_hours = env_int("PAPER_DIAGNOSTICS_SINCE_HOURS", 24)
    base_url = os.environ.get("PAPER_DIAGNOSTICS_BASE_URL", "http://app:3000")
    symbols = os.environ.get("PAPER_DIAGNOSTICS_SYMBOLS", "ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT")
    scripts_dir = Path(__file__).resolve().parent
    command = [
        sys.executable,
        str(scripts_dir / "daily_paper_diagnostics.py"),
        "--base-url",
        base_url,
        "--symbols",
        symbols,
        "--since-hours",
        str(since_hours),
        "--tmp-dir",
        "tmp",
        "--json-out",
        "tmp/daily_paper_diagnostics_latest.json",
        "--markdown-out",
        "tmp/daily_paper_diagnostics_latest.md",
    ]

    print(
        "paper diagnostics service starting: "
        f"interval={interval_seconds}s since_hours={since_hours} base_url={base_url} symbols={symbols}",
        flush=True,
    )
    while True:
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print(f"[{started}] running read-only daily paper diagnostics", flush=True)
        completed = subprocess.run(command, text=True)
        print(f"daily diagnostics exit={completed.returncode}", flush=True)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
