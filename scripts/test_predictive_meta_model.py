#!/usr/bin/env python3
from __future__ import annotations

import predictive_meta_model as model


def assert_greater(actual: float, expected_floor: float, message: str) -> None:
    if actual <= expected_floor:
        raise AssertionError(f"{message}: expected > {expected_floor!r}, got {actual!r}")


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def synthetic_record(taker_ratio: float, net_r: float) -> dict[str, object]:
    return {
        "opened_at": 1770000000000,
        "symbol": "ETHUSDT",
        "split": "validation",
        "fold": 1,
        "session": "london",
        "fee_drag_r": 0.2,
        "stop_pct": 1.0,
        "volume_percentile_96": 0.5,
        "atr_expansion_30_vs_90": 1.0,
        "funding_rate_bps": 0.1,
        "metrics_open_interest_24h_change_pct": 0.0,
        "global_account_long_short_ratio": 1.0,
        "top_trader_account_long_short_ratio": 1.0,
        "top_trader_position_long_short_ratio": 1.0,
        "taker_buy_sell_ratio": taker_ratio,
        "net_r": net_r,
    }


def test_ridge_model_learns_ordering() -> None:
    records = [
        synthetic_record(0.5, -1.0),
        synthetic_record(0.8, -0.5),
        synthetic_record(1.2, 0.25),
        synthetic_record(1.6, 1.0),
        synthetic_record(2.0, 1.3),
    ]
    fitted = model.fit_ridge(records, l2=0.1)
    low_score = model.predict(fitted, synthetic_record(0.6, 0.0))
    high_score = model.predict(fitted, synthetic_record(1.8, 0.0))
    assert_greater(high_score, low_score, "higher taker ratio should score higher")


def test_summary_and_gate_failures() -> None:
    records = [synthetic_record(1.5, 1.0), synthetic_record(0.8, -1.0)]
    summary = model.summarize_records(records)
    assert_equal(summary["trades"], 2, "trade count")
    assert_equal(summary["net_total_r"], 0.0, "net total")
    failures = model.promotion_failures(records)
    assert_equal(failures, ["not_promotion_protocol"], "generic protocol failure")


def run_tests() -> None:
    tests = [
        test_ridge_model_learns_ordering,
        test_summary_and_gate_failures,
    ]
    for test in tests:
        test()
    print(f"ok - {len(tests)} predictive meta-model tests passed")


if __name__ == "__main__":
    run_tests()
