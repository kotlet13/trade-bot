#!/usr/bin/env python3
from __future__ import annotations

import fold_regime_diagnostics as diag
import strategy_study as study


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_close(actual: float, expected: float, message: str, tolerance: float = 1e-9) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def test_funding_bucket_counts() -> None:
    counts = diag.funding_bucket_counts([-11.0, -3.0, -0.5, 0.5, 2.0])
    assert_equal(counts["panic_lt_-10bps"], 1, "panic bucket")
    assert_equal(counts["negative_-10_to_-2bps"], 1, "negative bucket")
    assert_equal(counts["slightly_negative_-2_to_0bps"], 1, "slightly negative bucket")
    assert_equal(counts["neutral_0_to_1bps"], 1, "neutral bucket")
    assert_equal(counts["positive_gt_1bps"], 1, "positive bucket")


def test_market_slice_summary() -> None:
    candles = [
        study.Candle(0, 100.0, 101.0, 99.0, 100.0, 1.0),
        study.Candle(900_000, 100.0, 103.0, 99.0, 102.0, 1.0),
        study.Candle(1_800_000, 102.0, 102.0, 95.0, 96.0, 1.0),
    ]
    summary = diag.summarize_market_slice(candles)
    assert_close(summary["return_pct"], -4.0, "return")
    assert_close(summary["max_drawdown_pct"], -5.8824, "drawdown", tolerance=1e-4)
    assert_close(summary["positive_bar_share_pct"], 50.0, "positive share")


def test_summarize_values_ignores_non_finite_values() -> None:
    summary = diag.summarize_values([1.0, float("nan"), 3.0])
    assert_equal(summary["count"], 2, "finite count")
    assert_close(summary["mean"], 2.0, "mean")
    assert_close(summary["median"], 2.0, "median")


def run_tests() -> None:
    tests = [
        test_funding_bucket_counts,
        test_market_slice_summary,
        test_summarize_values_ignores_non_finite_values,
    ]
    for test in tests:
        test()
    print(f"ok - {len(tests)} fold regime diagnostic tests passed")


if __name__ == "__main__":
    run_tests()
