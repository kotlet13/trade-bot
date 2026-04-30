#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_INTERVAL_SECONDS = 900
DEFAULT_COLLECTOR_LIMIT_PER_SOURCE = 50
DEFAULT_IMPACT_SINCE_HOURS = 168.0
DEFAULT_MARKET_MEMORY_SINCE_HOURS = 168.0


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"[{utc_now()}] invalid {name}={raw!r}; using {default}", flush=True)
        return default
    if value <= 0:
        print(f"[{utc_now()}] invalid {name}={raw!r}; using {default}", flush=True)
        return default
    return value


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        print(f"[{utc_now()}] invalid {name}={raw!r}; using {default}", flush=True)
        return default
    if value <= 0.0:
        print(f"[{utc_now()}] invalid {name}={raw!r}; using {default}", flush=True)
        return default
    return value


def run_command(command: list[str]) -> int:
    print(f"[{utc_now()}] starting: {' '.join(command)}", flush=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(command, check=False)
    except Exception as error:  # noqa: BLE001 - service loop must survive script failures.
        print(f"[{utc_now()}] failed to launch {' '.join(command)}: {error}", flush=True)
        return 1
    elapsed = time.monotonic() - started
    print(
        f"[{utc_now()}] finished rc={completed.returncode} elapsed={elapsed:.1f}s: {' '.join(command)}",
        flush=True,
    )
    return int(completed.returncode)


def cycle_commands(
    limit_per_source: int,
    impact_since_hours: float,
    market_memory_since_hours: float,
) -> list[list[str]]:
    python = sys.executable
    return [
        [
            python,
            "scripts/news_event_collector.py",
            "--limit-per-source",
            str(limit_per_source),
            "--markdown-out",
            "tmp/news_event_collection_latest.md",
            "--json-out",
            "tmp/news_event_collection_latest.json",
        ],
        [
            python,
            "scripts/news_event_impact_dataset.py",
            "--since-hours",
            str(impact_since_hours),
            "--markdown-out",
            "tmp/news_event_impact_latest.md",
            "--json-out",
            "tmp/news_event_impact_latest.json",
        ],
        [
            python,
            "scripts/market_memory_dataset.py",
            "--since-hours",
            str(market_memory_since_hours),
            "--markdown-out",
            "tmp/market_memory_latest.md",
            "--json-out",
            "tmp/market_memory_latest.json",
        ],
        [
            python,
            "scripts/runtime_telemetry_report.py",
            "--markdown-out",
            "tmp/runtime_telemetry_report_latest.md",
            "--json-out",
            "tmp/runtime_telemetry_report_latest.json",
        ],
    ]


def run_cycle(limit_per_source: int, impact_since_hours: float, market_memory_since_hours: float) -> bool:
    Path("tmp").mkdir(parents=True, exist_ok=True)
    print(f"[{utc_now()}] news event research cycle started", flush=True)
    return_codes = [
        run_command(command)
        for command in cycle_commands(limit_per_source, impact_since_hours, market_memory_since_hours)
    ]
    ok = all(code == 0 for code in return_codes)
    status = "succeeded" if ok else f"completed with nonzero exits {return_codes}"
    print(f"[{utc_now()}] news event research cycle {status}", flush=True)
    return ok


def main() -> int:
    interval_seconds = env_int("NEWS_EVENT_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)
    limit_per_source = env_int("NEWS_EVENT_COLLECTOR_LIMIT_PER_SOURCE", DEFAULT_COLLECTOR_LIMIT_PER_SOURCE)
    impact_since_hours = env_float("NEWS_EVENT_IMPACT_SINCE_HOURS", DEFAULT_IMPACT_SINCE_HOURS)
    market_memory_since_hours = env_float("NEWS_EVENT_MARKET_MEMORY_SINCE_HOURS", DEFAULT_MARKET_MEMORY_SINCE_HOURS)
    run_once = os.environ.get("NEWS_EVENT_RUN_ONCE", "").strip().lower() in {"1", "true", "yes"}

    print(
        "[{}] news event service enabled: interval={}s, limit_per_source={}, impact_since_hours={}, market_memory_since_hours={}".format(
            utc_now(),
            interval_seconds,
            limit_per_source,
            impact_since_hours,
            market_memory_since_hours,
        ),
        flush=True,
    )

    while True:
        run_cycle(limit_per_source, impact_since_hours, market_memory_since_hours)
        if run_once:
            return 0
        print(f"[{utc_now()}] sleeping {interval_seconds}s", flush=True)
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print(f"[{utc_now()}] shutdown requested", flush=True)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
