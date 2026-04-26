#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import strategy_study as study
import research_harness as harness


class ResearchHarnessFixtures(unittest.TestCase):
    def make_risk_plan(self) -> study.RiskPlan:
        return study.RiskPlan(
            entry=100.0,
            stop_loss=90.0,
            take_profit_1=110.0,
            take_profit_2=120.0,
            risk_per_unit=10.0,
            risk_amount=100.0,
            suggested_quantity=10.0,
            notional_estimate=1_000.0,
        )

    def test_same_candle_stop_before_tp_is_conservative(self) -> None:
        trade = study.simulate_trade(
            opened_at=0,
            risk_plan=self.make_risk_plan(),
            future_candles=[
                study.Candle(
                    open_time=0,
                    open=100.0,
                    high=111.0,
                    low=89.0,
                    close=105.0,
                    volume=1.0,
                )
            ],
            fee_bps=10.0,
        )
        self.assertEqual(trade.outcome, "stop_loss")
        self.assertEqual(trade.gross_r, -1.0)

    def test_fees_reduce_net_r(self) -> None:
        trade = study.simulate_trade(
            opened_at=0,
            risk_plan=self.make_risk_plan(),
            future_candles=[
                study.Candle(0, 100.0, 111.0, 101.0, 110.0, 1.0),
                study.Candle(900_000, 110.0, 121.0, 109.0, 120.0, 1.0),
            ],
            fee_bps=10.0,
        )
        self.assertEqual(trade.outcome, "take_profit_2")
        self.assertLess(trade.net_r, trade.gross_r)

    def test_closed_candles_exclude_unclosed_reclaim_candle(self) -> None:
        candles = [
            study.Candle(0, 99.0, 101.0, 98.0, 99.0, 1.0),
            study.Candle(3_600_000, 99.0, 103.0, 98.0, 102.0, 1.0),
        ]
        closed_at_75m = study.closed_candles_until(candles, 4_500_000, "1h")
        closed_at_120m = study.closed_candles_until(candles, 7_200_000, "1h")
        self.assertEqual(len(closed_at_75m), 1)
        self.assertEqual(len(closed_at_120m), 2)

    def test_max_affordable_quantity_includes_fees(self) -> None:
        quantity = study.max_affordable_quantity(10_000.0, 100.0, 10.0)
        self.assertLess(quantity, 100.0)
        self.assertLessEqual(quantity * 100.0 * 1.001, 10_000.000001)

    def test_strict_universe_rejects_noisy_symbols(self) -> None:
        noisy = [
            {"symbol": "TRUMPUSDT", "quoteVolume": "1000000000"},
            {"symbol": "USD1USDT", "quoteVolume": "1000000000"},
            {"symbol": "币安人生USDT", "quoteVolume": "1000000000"},
            {"symbol": "ETHUPUSDT", "quoteVolume": "1000000000"},
        ]
        reasons = [
            harness.symbol_rejection_reason(
                item,
                profile="strict",
                min_quote_volume=50_000_000.0,
                excluded_bases=harness.STRICT_EXCLUDED_BASES,
            )
            for item in noisy
        ]
        self.assertEqual(
            reasons,
            [
                "strict_excluded_base",
                "stable_or_fiat_base",
                "non_ascii_or_non_standard_symbol",
                "leveraged_token",
            ],
        )


if __name__ == "__main__":
    unittest.main()
