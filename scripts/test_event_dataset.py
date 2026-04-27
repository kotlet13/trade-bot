#!/usr/bin/env python3
from __future__ import annotations

import event_dataset


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_close(actual: float, expected: float, message: str, tolerance: float = 1e-9) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def test_build_segments() -> None:
    segments = event_dataset.build_segments(trigger_limit=3000, chunk_size=1000, forward_candles=32)
    assert_equal(len(segments), 3, "segment count")
    assert_equal(segments[0].name, "segment_01", "segment name")
    assert_equal(segments[-1].start, 2000, "last segment start")


def test_percentile_rank() -> None:
    assert_close(event_dataset.percentile_rank([1.0, 2.0, 3.0, 4.0], 3.0), 0.75, "percentile rank")
    assert_equal(event_dataset.percentile_rank([], 1.0), None, "empty percentile")


def test_dedupe_events() -> None:
    event = {
        "candidate": "a",
        "symbol": "ETHUSDT",
        "opened_at": 1,
        "closed_at": 2,
        "outcome": "timeout",
        "net_r": 0.1,
    }
    unique = event_dataset.dedupe_events([dict(event), dict(event)])
    assert_equal(len(unique), 1, "dedupe count")


def run_tests() -> None:
    tests = [test_build_segments, test_percentile_rank, test_dedupe_events]
    for test in tests:
        test()
    print(f"ok - {len(tests)} event dataset tests passed")


if __name__ == "__main__":
    run_tests()
