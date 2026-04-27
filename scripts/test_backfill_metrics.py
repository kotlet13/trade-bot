#!/usr/bin/env python3
from __future__ import annotations

from datetime import date

import backfill_metrics


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def test_metric_days_inclusive() -> None:
    start = 1776729600000  # 2026-04-21 00:00 UTC
    end = 1776902400000  # 2026-04-23 00:00 UTC
    assert_equal(
        backfill_metrics.metric_days(start, end),
        [date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23)],
        "inclusive days",
    )


def test_selected_symbols_skip_handled_by_caller() -> None:
    source = {"universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]}
    assert_equal(
        backfill_metrics.selected_symbols(source, None, 2),
        ["BTCUSDT", "ETHUSDT"],
        "universe limit",
    )


def run_tests() -> None:
    tests = [test_metric_days_inclusive, test_selected_symbols_skip_handled_by_caller]
    for test in tests:
        test()
    print(f"ok - {len(tests)} metrics backfill tests passed")


if __name__ == "__main__":
    run_tests()
