#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_FORWARD_JSON = Path("tmp/forward_paper_report_latest.json")
DEFAULT_STATUS_JSON = Path("tmp/auto_paper_status_latest.json")
DEFAULT_PARITY_BASE_JSON = Path("tmp/runtime_harness_parity_base_latest.json")
DEFAULT_PARITY_OI_JSON = Path("tmp/runtime_harness_parity_oi_latest.json")
DEFAULT_OUT = Path("tmp/paper_campaign_log.md")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def top_counter_item(values: dict[str, Any] | None) -> str:
    if not values:
        return "n/a"
    key, value = sorted(values.items(), key=lambda item: (-int(item[1] or 0), item[0]))[0]
    return f"{key} ({value})"


def worst_group(stats: dict[str, Any] | None) -> str:
    if not stats:
        return "n/a"
    items = []
    for name, item in stats.items():
        if not isinstance(item, dict):
            continue
        total_r = item.get("total_realized_r")
        if total_r is None:
            continue
        items.append((str(name), float(total_r), int(item.get("count") or 0)))
    if not items:
        return "n/a"
    name, total_r, count = sorted(items, key=lambda item: (item[1], item[0]))[0]
    return f"{name} ({total_r:+.3f}R, {count} trades)"


def parity_summary(path: Path, payload: dict[str, Any] | None) -> str:
    if payload is None:
        return f"{path.name}: missing"
    strategy = payload.get("strategy") or path.stem
    pass_count = int(payload.get("pass_count") or 0)
    warn_count = int(payload.get("warn_count") or 0)
    return f"{strategy}: pass {pass_count}, warn {warn_count}"


def status_summary(status: dict[str, Any] | None) -> tuple[str, str, str]:
    if not status:
        return ("unknown", "unknown", "0")
    enabled = "enabled" if status.get("enabled_by_config") else "disabled"
    pause = status.get("pause") if isinstance(status.get("pause"), dict) else {}
    paused = "paused" if pause.get("paused") else "resumed"
    reason = pause.get("reason")
    if reason:
        paused = f"{paused}: {reason}"
    open_positions = str(status.get("open_auto_position_count") or 0)
    return enabled, paused, open_positions


def render_entry(
    forward: dict[str, Any] | None,
    status: dict[str, Any] | None,
    parity_base: dict[str, Any] | None,
    parity_oi: dict[str, Any] | None,
    args: argparse.Namespace,
) -> str:
    generated = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    forward = forward or {}
    enabled, paused, open_auto_positions = status_summary(status)
    grouped = forward.get("grouped_stats") if isinstance(forward.get("grouped_stats"), dict) else {}
    by_strategy = grouped.get("by_strategy") if isinstance(grouped.get("by_strategy"), dict) else {}
    by_symbol = grouped.get("by_symbol") if isinstance(grouped.get("by_symbol"), dict) else {}
    by_session = grouped.get("by_session_bucket") if isinstance(grouped.get("by_session_bucket"), dict) else {}
    per_strategy_r = ", ".join(
        f"{name}: {float(item.get('total_realized_r') or 0.0):+.3f}R"
        for name, item in sorted(by_strategy.items())
        if isinstance(item, dict)
    ) or "n/a"
    parity = "; ".join(
        [
            parity_summary(args.parity_base_json, parity_base),
            parity_summary(args.parity_oi_json, parity_oi),
        ]
    )
    campaign = forward.get("campaign") if isinstance(forward.get("campaign"), dict) else {}
    lines = [
        f"## {generated}",
        "",
        f"- Auto-paper config/state: `{enabled}` / `{paused}`",
        f"- Open auto positions: `{open_auto_positions}`",
        f"- Completed trades in report: `{forward.get('completed_trades', 0)}`",
        f"- Total realized R in report: `{float(forward.get('realized_r') or 0.0):+.3f}R`",
        f"- Per-strategy realized R: `{per_strategy_r}`",
        f"- Max drawdown R: `{float((forward.get('completed_stats') or {}).get('max_drawdown_r') or 0.0):+.3f}R`",
        f"- Parity status: `{parity}`",
        f"- Top rejection blocker: `{top_counter_item(forward.get('rejection_blockers'))}`",
        f"- Top symbol drag: `{worst_group(by_symbol)}`",
        f"- Top session drag: `{worst_group(by_session)}`",
        f"- Recommended action: `{forward.get('recommended_action') or campaign.get('recommended_action') or 'n/a'}`",
        f"- Note: `{args.note or 'n/a'}`",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append a daily forward-paper campaign observation.")
    parser.add_argument("--forward-json", type=Path, default=DEFAULT_FORWARD_JSON)
    parser.add_argument("--status-json", type=Path, default=DEFAULT_STATUS_JSON)
    parser.add_argument("--parity-base-json", type=Path, default=DEFAULT_PARITY_BASE_JSON)
    parser.add_argument("--parity-oi-json", type=Path, default=DEFAULT_PARITY_OI_JSON)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--note", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    entry = render_entry(
        load_json(args.forward_json),
        load_json(args.status_json),
        load_json(args.parity_base_json),
        load_json(args.parity_oi_json),
        args,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not args.out.exists():
        args.out.write_text("# Paper Campaign Log\n\n", encoding="utf-8")
    with args.out.open("a", encoding="utf-8") as handle:
        handle.write(entry)
        handle.write("\n")
    print(f"appended {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
