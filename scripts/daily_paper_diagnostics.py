#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/tradebot.db")
DEFAULT_BASE_URL = "http://localhost:8081"
DEFAULT_SYMBOLS = "ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT"


@dataclass(frozen=True)
class DiagnosticRun:
    name: str
    command: list[str]
    returncode: int
    stdout_tail: str
    stderr_tail: str
    ok: bool


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def db_has_tables(db_path: Path, names: list[str]) -> bool:
    if not db_path.exists():
        return False
    with sqlite3.connect(db_path) as connection:
        return all(table_exists(connection, name) for name in names)


def tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


def run_command(name: str, command: list[str]) -> DiagnosticRun:
    completed = subprocess.run(command, capture_output=True, text=True)
    return DiagnosticRun(
        name=name,
        command=command,
        returncode=completed.returncode,
        stdout_tail=tail(completed.stdout),
        stderr_tail=tail(completed.stderr),
        ok=completed.returncode == 0,
    )


def run_health_check(base_url: str, timeout_seconds: float) -> DiagnosticRun:
    url = f"{base_url.rstrip('/')}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            ok = response.status == 200 and body == "ok"
            return DiagnosticRun(
                name="app_health",
                command=["GET", url],
                returncode=0 if ok else 1,
                stdout_tail=f"HTTP {response.status}: {body}",
                stderr_tail="" if ok else "health endpoint returned an unexpected response",
                ok=ok,
            )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return DiagnosticRun(
            name="app_health",
            command=["GET", url],
            returncode=1,
            stdout_tail="",
            stderr_tail=f"health check failed for {url}: {error}",
            ok=False,
        )


def render_markdown(runs: list[DiagnosticRun], skipped: list[str]) -> str:
    lines = ["# Daily Paper Diagnostics", ""]
    for run in runs:
        status = "ok" if run.ok else "failed"
        lines.append(f"- `{run.name}`: `{status}` exit `{run.returncode}`")
    for item in skipped:
        lines.append(f"- `skipped`: {item}")
    if any(not run.ok for run in runs):
        lines.extend(["", "## Failures", ""])
        for run in runs:
            if run.ok:
                continue
            lines.append(f"### {run.name}")
            lines.append("")
            lines.append("```text")
            lines.append(run.stderr_tail or run.stdout_tail or "no output")
            lines.append("```")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only daily paper-trading diagnostics.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--health-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--since-hours", type=float, default=24.0)
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp"))
    parser.add_argument("--json-out", type=Path, default=Path("tmp/daily_paper_diagnostics_latest.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("tmp/daily_paper_diagnostics_latest.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.tmp_dir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    scripts_dir = Path(__file__).resolve().parent
    skipped: list[str] = []
    runs: list[DiagnosticRun] = []

    if not args.db.exists():
        skipped.append(f"database not found at `{args.db}`; local report scripts may not have data")

    runs.append(run_health_check(args.base_url, args.health_timeout_seconds))
    app_healthy = runs[-1].ok

    commands: list[tuple[str, list[str]]] = [
        (
            "forward_paper_report",
            [
                py,
                str(scripts_dir / "forward_paper_report.py"),
                "--db",
                str(args.db),
                "--since-hours",
                str(args.since_hours),
                "--markdown-out",
                str(args.tmp_dir / "forward_paper_report_latest.md"),
                "--json-out",
                str(args.tmp_dir / "forward_paper_report_latest.json"),
            ],
        ),
        (
            "runtime_telemetry_report",
            [
                py,
                str(scripts_dir / "runtime_telemetry_report.py"),
                "--db",
                str(args.db),
                "--since-hours",
                str(args.since_hours),
                "--markdown-out",
                str(args.tmp_dir / "runtime_telemetry_report_latest.md"),
                "--json-out",
                str(args.tmp_dir / "runtime_telemetry_report_latest.json"),
            ],
        ),
    ]

    if app_healthy:
        commands.extend(
            [
                (
                    "runtime_harness_parity_base",
                    [
                        py,
                        str(scripts_dir / "runtime_harness_parity.py"),
                        "--base-url",
                        args.base_url,
                        "--strategy",
                        "ai_score_v2_base_score7",
                        "--symbols",
                        args.symbols,
                        "--markdown-out",
                        str(args.tmp_dir / "runtime_harness_parity_base_latest.md"),
                        "--json-out",
                        str(args.tmp_dir / "runtime_harness_parity_base_latest.json"),
                    ],
                ),
                (
                    "runtime_harness_parity_oi",
                    [
                        py,
                        str(scripts_dir / "runtime_harness_parity.py"),
                        "--base-url",
                        args.base_url,
                        "--strategy",
                        "ai_score_v2_ablate_oi",
                        "--symbols",
                        args.symbols,
                        "--markdown-out",
                        str(args.tmp_dir / "runtime_harness_parity_oi_latest.md"),
                        "--json-out",
                        str(args.tmp_dir / "runtime_harness_parity_oi_latest.json"),
                    ],
                ),
            ]
        )
    else:
        skipped.append("runtime/harness parity; app health check failed")

    for name, command in commands:
        runs.append(run_command(name, command))

    if db_has_tables(
        args.db,
        [
            "telemetry_candles",
            "telemetry_funding_rates",
            "telemetry_futures_metric_rows",
            "telemetry_signal_evaluations",
        ],
    ):
        runs.append(
            run_command(
                "market_memory_dataset",
                [
                    py,
                    str(scripts_dir / "market_memory_dataset.py"),
                    "--db",
                    str(args.db),
                    "--since-hours",
                    str(max(args.since_hours, 168.0)),
                    "--markdown-out",
                    str(args.tmp_dir / "market_memory_dataset_latest.md"),
                    "--json-out",
                    str(args.tmp_dir / "market_memory_dataset_latest.json"),
                ],
            )
        )
    else:
        skipped.append("market-memory report; required telemetry tables are not all present")

    payload: dict[str, Any] = {
        "runs": [asdict(run) for run in runs],
        "skipped": skipped,
        "ok": all(run.ok for run in runs),
    }
    markdown = render_markdown(runs, skipped)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
