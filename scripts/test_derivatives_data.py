#!/usr/bin/env python3
from __future__ import annotations

from derivatives_data import (
    funding_at_or_before,
    funding_from_json,
    futures_metric_from_json,
    metric_at_or_before,
    open_interest_from_json,
    parse_create_time_ms,
    pct_change,
)


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_close(actual: float, expected: float, message: str, tolerance: float = 1e-9) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def test_funding_api_shape() -> None:
    row = funding_from_json(
        {
            "symbol": "BTCUSDT",
            "fundingTime": 1770000000000,
            "fundingRate": "0.00010000",
            "markPrice": "100000.0",
        }
    )
    assert_equal(row.symbol, "BTCUSDT", "symbol")
    assert_equal(row.funding_time, 1770000000000, "funding time")
    assert_close(row.funding_rate, 0.0001, "funding rate")
    assert_close(row.mark_price, 100000.0, "mark price")


def test_funding_cache_shape() -> None:
    row = funding_from_json(
        {
            "symbol": "ETHUSDT",
            "funding_time": 1770000000001,
            "funding_rate": -0.000025,
            "mark_price": 4000.0,
        }
    )
    assert_equal(row.symbol, "ETHUSDT", "symbol")
    assert_equal(row.funding_time, 1770000000001, "funding time")
    assert_close(row.funding_rate, -0.000025, "funding rate")
    assert_close(row.mark_price, 4000.0, "mark price")


def test_open_interest_api_shape() -> None:
    row = open_interest_from_json(
        {
            "symbol": "SOLUSDT",
            "sumOpenInterest": "12345.5",
            "sumOpenInterestValue": "2500000.25",
            "timestamp": 1770000000000,
        }
    )
    assert_equal(row.symbol, "SOLUSDT", "symbol")
    assert_close(row.sum_open_interest, 12345.5, "open interest")
    assert_close(row.sum_open_interest_value, 2500000.25, "open interest value")


def test_open_interest_cache_shape() -> None:
    row = open_interest_from_json(
        {
            "symbol": "XRPUSDT",
            "sum_open_interest": 12345.5,
            "sum_open_interest_value": 2500000.25,
            "timestamp": 1770000000000,
        }
    )
    assert_equal(row.symbol, "XRPUSDT", "symbol")
    assert_close(row.sum_open_interest, 12345.5, "open interest")
    assert_close(row.sum_open_interest_value, 2500000.25, "open interest value")


def test_funding_at_or_before() -> None:
    rows = [
        funding_from_json({"symbol": "BTCUSDT", "funding_time": 1000, "funding_rate": 0.1, "mark_price": 1.0}),
        funding_from_json({"symbol": "BTCUSDT", "funding_time": 2000, "funding_rate": 0.2, "mark_price": 1.0}),
    ]
    assert_equal(funding_at_or_before(rows, 999), None, "before first")
    assert_close(funding_at_or_before(rows, 1000).funding_rate, 0.1, "exact match")
    assert_close(funding_at_or_before(rows, 2500).funding_rate, 0.2, "after second")


def test_pct_change() -> None:
    assert_close(pct_change(100.0, 125.0), 25.0, "positive change")
    assert_close(pct_change(100.0, 75.0), -25.0, "negative change")
    assert_equal(pct_change(0.0, 100.0), None, "zero base")


def test_futures_metric_csv_shape() -> None:
    row = futures_metric_from_json(
        {
            "create_time": "2026-04-24 00:05:00",
            "symbol": "BTCUSDT",
            "sum_open_interest": "99187.398",
            "sum_open_interest_value": "7749771261.629414",
            "count_toptrader_long_short_ratio": "0.70409796",
            "sum_toptrader_long_short_ratio": "0.81782900",
            "count_long_short_ratio": "0.67000481",
            "sum_taker_long_short_vol_ratio": "1.12641200",
        }
    )
    assert_equal(row.symbol, "BTCUSDT", "symbol")
    assert_equal(row.timestamp, parse_create_time_ms("2026-04-24 00:05:00"), "timestamp")
    assert_close(row.sum_open_interest_value, 7749771261.629414, "oi value")
    assert_close(row.count_long_short_ratio, 0.67000481, "global long short")
    assert_close(row.sum_taker_long_short_vol_ratio, 1.126412, "taker ratio")


def test_futures_metric_cache_shape() -> None:
    row = futures_metric_from_json(
        {
            "timestamp": 1770000000000,
            "symbol": "ETHUSDT",
            "sum_open_interest": 1000.0,
            "sum_open_interest_value": 2500000.0,
            "count_toptrader_long_short_ratio": 1.1,
            "sum_toptrader_long_short_ratio": 1.2,
            "count_long_short_ratio": 0.9,
            "sum_taker_long_short_vol_ratio": 1.5,
        }
    )
    assert_equal(row.timestamp, 1770000000000, "timestamp")
    assert_close(row.sum_toptrader_long_short_ratio, 1.2, "top position ratio")


def test_metric_at_or_before() -> None:
    rows = [
        futures_metric_from_json(
            {
                "timestamp": 1000,
                "symbol": "BTCUSDT",
                "sum_open_interest": 1,
                "sum_open_interest_value": 1,
                "count_toptrader_long_short_ratio": 1,
                "sum_toptrader_long_short_ratio": 1,
                "count_long_short_ratio": 0.9,
                "sum_taker_long_short_vol_ratio": 1,
            }
        ),
        futures_metric_from_json(
            {
                "timestamp": 2000,
                "symbol": "BTCUSDT",
                "sum_open_interest": 1,
                "sum_open_interest_value": 2,
                "count_toptrader_long_short_ratio": 1,
                "sum_toptrader_long_short_ratio": 1,
                "count_long_short_ratio": 1.1,
                "sum_taker_long_short_vol_ratio": 1,
            }
        ),
    ]
    assert_equal(metric_at_or_before(rows, 999), None, "before first")
    assert_close(metric_at_or_before(rows, 2500).count_long_short_ratio, 1.1, "after second")


def test_futures_metric_blank_numeric_defaults_to_zero() -> None:
    row = futures_metric_from_json(
        {
            "timestamp": 1770000000000,
            "symbol": "HBARUSDT",
            "sum_open_interest": "1",
            "sum_open_interest_value": "1",
            "count_toptrader_long_short_ratio": "",
            "sum_toptrader_long_short_ratio": "1",
            "count_long_short_ratio": "1",
            "sum_taker_long_short_vol_ratio": "",
        }
    )
    assert_close(row.count_toptrader_long_short_ratio, 0.0, "blank top account ratio")
    assert_close(row.sum_taker_long_short_vol_ratio, 0.0, "blank taker ratio")


def run_tests() -> None:
    tests = [
        test_funding_api_shape,
        test_funding_cache_shape,
        test_open_interest_api_shape,
        test_open_interest_cache_shape,
        test_funding_at_or_before,
        test_pct_change,
        test_futures_metric_csv_shape,
        test_futures_metric_cache_shape,
        test_metric_at_or_before,
        test_futures_metric_blank_numeric_defaults_to_zero,
    ]
    for test in tests:
        test()
    print(f"ok - {len(tests)} derivatives data tests passed")


if __name__ == "__main__":
    run_tests()
