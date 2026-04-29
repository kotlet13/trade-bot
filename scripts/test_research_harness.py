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

    def make_market_data(self, symbol: str, closes: list[float]) -> harness.MarketData:
        candles = [
            study.Candle(index * 900_000, close, close, close, close, 1.0)
            for index, close in enumerate(closes)
        ]
        return harness.MarketData(symbol, candles, candles, candles)

    def make_scorecard_context(
        self,
    ) -> tuple[int, list[harness.derivatives_data.FundingRate], list[harness.derivatives_data.FuturesMetric]]:
        signal_time = 60 * 60 * 60_000
        funding_rows = [
            harness.derivatives_data.FundingRate("ETHUSDT", signal_time - 60_000, -0.00005, 100.0)
        ]
        metric_rows = [
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                signal_time - 24 * 60 * 60_000 - 60_000,
                1.0,
                1_000.0,
                1.0,
                1.20,
                1.10,
                1.30,
            ),
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                signal_time - 60_000,
                1.0,
                950.0,
                1.0,
                1.20,
                1.10,
                1.30,
            ),
        ]
        return signal_time, funding_rows, metric_rows

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

    def test_short_time_stop_handles_short_profit(self) -> None:
        trade = harness.short_full_exit_trade(
            opened_at=0,
            risk_plan=study.RiskPlan(
                entry=100.0,
                stop_loss=110.0,
                take_profit_1=90.0,
                take_profit_2=80.0,
                risk_per_unit=10.0,
                risk_amount=100.0,
                suggested_quantity=10.0,
                notional_estimate=1_000.0,
            ),
            future_candles=[
                study.Candle(0, 100.0, 101.0, 84.0, 85.0, 1.0),
            ],
            fee_bps=10.0,
            target_multiple=1.5,
            max_bars=8,
        )
        self.assertEqual(trade.outcome, "take_profit_2")
        self.assertGreater(trade.gross_r, 0.0)
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

    def test_post_signal_fee_filter_rejects_costly_trade(self) -> None:
        candidate = harness.CandidateSpec(
            "fee_filter_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"max_fee_drag_r": 0.01},
        )

        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_post_signal_volume_filter_uses_recent_percentile(self) -> None:
        base = [
            study.Candle(index * 900_000, 100.0, 101.0, 99.0, 100.0, 1.0)
            for index in range(99)
        ]
        candidate = harness.CandidateSpec(
            "volume_filter_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"min_volume_percentile": 0.70},
        )

        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [*base, study.Candle(99 * 900_000, 100.0, 101.0, 99.0, 100.0, 2.0)],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [*base, study.Candle(99 * 900_000, 100.0, 101.0, 99.0, 100.0, 0.5)],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_focused_overlap_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "focused_overlap"]
        self.assertGreaterEqual(len(focused), 8)
        self.assertIn("v2_reclaim_overlap_volume_fee_ok", {candidate.name for candidate in focused})

    def test_exclude_btc_post_signal_filter(self) -> None:
        candidate = harness.CandidateSpec(
            "exclude_btc_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"exclude_btc": True},
        )

        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "BTCUSDT",
                0,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_excluded_symbols_post_signal_filter(self) -> None:
        candidate = harness.CandidateSpec(
            "excluded_symbols_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"excluded_symbols": "APTUSDT, AVAXUSDT"},
        )

        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "APTUSDT",
                0,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_max_volume_filter_rejects_extreme_volume(self) -> None:
        base = [
            study.Candle(index * 900_000, 100.0, 101.0, 99.0, 100.0, 1.0)
            for index in range(99)
        ]
        candidate = harness.CandidateSpec(
            "max_volume_filter_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"max_volume_percentile": 0.90},
        )

        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [*base, study.Candle(99 * 900_000, 100.0, 101.0, 99.0, 100.0, 2.0)],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [*base, study.Candle(99 * 900_000, 100.0, 101.0, 99.0, 100.0, 0.5)],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_focused_widening_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "focused_widening"]
        self.assertGreaterEqual(len(focused), 8)
        self.assertIn("v2_reclaim_overlap_ny_time_stop_atr_ok_no_btc", {candidate.name for candidate in focused})

    def test_focused_scale_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "focused_scale"]
        names = {candidate.name for candidate in focused}
        self.assertGreaterEqual(len(focused), 8)
        self.assertIn("v2_reclaim_active_time_stop_base_no_btc", names)
        self.assertIn("v2_reclaim_overlap_ny_time_stop_no_corr_no_btc", names)

    def test_focused_refinement_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "focused_refinement"]
        names = {candidate.name for candidate in focused}
        self.assertGreaterEqual(len(focused), 8)
        self.assertIn("v2_reclaim_active_no_corr_vol_lt90", names)
        self.assertIn("v2_reclaim_active_no_corr_ex_worst4", names)

    def test_absurd_candle_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "absurd_candle"]
        names = {candidate.name for candidate in focused}
        self.assertGreaterEqual(len(focused), 8)
        self.assertIn("crash_rebound_active", names)
        self.assertIn("session_trap_short", names)

    def test_funding_filter_uses_latest_non_stale_rate(self) -> None:
        candidate = harness.CandidateSpec(
            "funding_filter_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={
                "min_funding_bps": -0.9999,
                "max_funding_bps": -0.0001,
                "max_funding_age_hours": 12,
            },
        )
        fresh_mild_negative = [
            harness.derivatives_data.FundingRate("ETHUSDT", 9_000_000, -0.00005, 100.0)
        ]
        extreme_negative = [
            harness.derivatives_data.FundingRate("ETHUSDT", 9_000_000, -0.0002, 100.0)
        ]
        positive = [
            harness.derivatives_data.FundingRate("ETHUSDT", 9_000_000, 0.00001, 100.0)
        ]
        stale_mild_negative = [
            harness.derivatives_data.FundingRate("ETHUSDT", 1_000_000, -0.00005, 100.0)
        ]

        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                10_000_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                fresh_mild_negative,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                10_000_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                extreme_negative,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                10_000_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                positive,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                50_000_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                stale_mild_negative,
            )
        )

    def test_derivatives_filter_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "derivatives_filter"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 6)
        self.assertIn("v2_reclaim_active_no_corr_funding_mild_neg", names)
        self.assertIn("v2_reclaim_active_no_corr_funding_not_panic", names)

    def test_metrics_filter_uses_latest_taker_ratio(self) -> None:
        candidate = harness.CandidateSpec(
            "metrics_filter_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"min_taker_buy_sell_ratio": 1.25, "max_metrics_age_minutes": 20},
        )
        fresh_buy_pressure = [
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                9_900_000,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.30,
            )
        ]
        weak_buy_pressure = [
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                9_900_000,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.10,
            )
        ]

        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                10_000_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                metric_rows=fresh_buy_pressure,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                10_000_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                metric_rows=weak_buy_pressure,
            )
        )

    def test_post_signal_filter_uses_utc_hour_window(self) -> None:
        candidate = harness.CandidateSpec(
            "hour_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"min_hour_utc": 10, "max_hour_utc": 16},
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                9 * 60 * 60_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                10 * 60 * 60_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                16 * 60 * 60_000,
                [],
                [],
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_metrics_filter_uses_oi_cooling(self) -> None:
        signal_time = 100_000_000
        candidate = harness.CandidateSpec(
            "metrics_oi_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={
                "min_metrics_oi_24h_change_pct": -10.0,
                "max_metrics_oi_24h_change_pct": 0.0,
            },
        )
        cooling = [
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                signal_time - 24 * 60 * 60_000,
                1.0,
                1_000.0,
                1.0,
                1.0,
                1.0,
                1.30,
            ),
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                signal_time - 60_000,
                1.0,
                950.0,
                1.0,
                1.0,
                1.0,
                1.30,
            ),
        ]
        expanding = [
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                signal_time - 24 * 60 * 60_000,
                1.0,
                1_000.0,
                1.0,
                1.0,
                1.0,
                1.30,
            ),
            harness.derivatives_data.FuturesMetric(
                "ETHUSDT",
                signal_time - 60_000,
                1.0,
                1_050.0,
                1.0,
                1.0,
                1.0,
                1.30,
            ),
        ]

        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                signal_time,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                metric_rows=cooling,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                signal_time,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                metric_rows=expanding,
            )
        )

    def test_metrics_filter_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "metrics_filter"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 6)
        self.assertIn("v2_reclaim_active_base_funding_taker_buy", names)
        self.assertIn("v2_reclaim_active_base_taker_global_lte120", names)
        self.assertIn("v2_reclaim_overlap_base_funding_taker_buy", names)

    def test_event_rule_filter_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "event_rule_filters"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 14)
        self.assertIn("event_rule_v2_base_global_lte120", names)
        self.assertIn("event_rule_v2_base_funding_taker", names)
        self.assertIn("event_rule_v2_base_global_funding_taker", names)
        self.assertIn("event_rule_v2_moderate_global_lte120", names)
        self.assertIn("event_rule_v2_no_corr_global_funding_taker", names)

    def test_london_or_overlap_regime_filter_excludes_new_york(self) -> None:
        candidate = harness.CandidateSpec(
            "london_overlap_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            regime_filter="london_or_overlap",
        )
        self.assertTrue(harness.passes_regime_filter(candidate, "ETHUSDT", 7 * 60 * 60_000, [], [], {}))
        self.assertTrue(harness.passes_regime_filter(candidate, "ETHUSDT", 12 * 60 * 60_000, [], [], {}))
        self.assertFalse(harness.passes_regime_filter(candidate, "ETHUSDT", 16 * 60 * 60_000, [], [], {}))
        london_only = harness.CandidateSpec(
            "london_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            regime_filter="london_session",
        )
        self.assertTrue(harness.passes_regime_filter(london_only, "ETHUSDT", 7 * 60 * 60_000, [], [], {}))
        self.assertFalse(harness.passes_regime_filter(london_only, "ETHUSDT", 12 * 60 * 60_000, [], [], {}))

    def test_new_york_regime_filter(self) -> None:
        candidate = harness.CandidateSpec(
            "new_york_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            regime_filter="new_york_session",
        )
        self.assertFalse(harness.passes_regime_filter(candidate, "ETHUSDT", 12 * 60 * 60_000, [], [], {}))
        self.assertTrue(harness.passes_regime_filter(candidate, "ETHUSDT", 16 * 60 * 60_000, [], [], {}))
        self.assertFalse(harness.passes_regime_filter(candidate, "ETHUSDT", 22 * 60 * 60_000, [], [], {}))

    def test_btc_return_post_signal_filter(self) -> None:
        candidate = harness.CandidateSpec(
            "btc_return_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"btc_return_lookback_hours": 24, "max_btc_return_pct": -1.0},
        )
        down = [
            study.Candle(index * 4 * 60 * 60_000, close, close, close, close, 1.0)
            for index, close in enumerate([100.0, 99.0, 98.0, 97.0, 96.5, 96.0, 95.0])
        ]
        up = [
            study.Candle(index * 4 * 60 * 60_000, close, close, close, close, 1.0)
            for index, close in enumerate([100.0, 100.5, 100.8, 101.0, 101.1, 101.2, 101.5])
        ]
        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [],
                down,
                self.make_risk_plan(),
                10.0,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                0,
                [],
                up,
                self.make_risk_plan(),
                10.0,
            )
        )

    def test_broad_derivatives_entry_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "broad_derivatives_entry"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 5)
        self.assertIn("ema_pullback_london_overlap_funding_taker", names)
        self.assertIn("htf_continuation_london_overlap_funding_taker", names)
        self.assertIn("donchian_breakout_48_london_overlap_funding_taker", names)

    def test_broad_derivatives_refined_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "broad_derivatives_refined"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 6)
        self.assertIn("htf_continuation_london_funding_taker", names)
        self.assertIn("htf_continuation_london_funding_taker_oi_cooling", names)
        self.assertIn("v2_reclaim_london_base_funding_taker_oi_cooling", names)

    def test_broad_derivatives_oi_sweep_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "broad_derivatives_oi_sweep"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 5)
        self.assertIn("htf_london_funding_taker_oi_max0", names)
        self.assertIn("htf_london_funding_taker_oi_neg10_pos1", names)
        self.assertIn("htf_london_funding_taker_oi_neg10_0_maxbars8", names)

    def test_coverage_scan_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "coverage_scan"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 14)
        self.assertIn("coverage_htf_active_time16", names)
        self.assertIn("coverage_breakout_pullback48_active_time16", names)
        self.assertIn("coverage_session_trap_short_active", names)

    def test_coverage_refinement_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "coverage_refinement"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 5)
        self.assertIn("coverage_v2_moderate_london_overlap_time16", names)
        self.assertIn("coverage_v2_moderate_active_10_16_time16", names)
        self.assertIn("coverage_v2_moderate_10_16_funding_m2_p1", names)

    def test_coverage_short_trend_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "coverage_short_trend"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 5)
        self.assertIn("coverage_short_htf_active_time16", names)
        self.assertIn("coverage_short_donchian48_active_time16", names)
        self.assertIn("coverage_short_ema_active_time16", names)

    def test_fold2_risk_off_short_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "fold2_risk_off_short"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 8)
        self.assertIn("fold2_short_donchian80_ny_btc_down", names)
        self.assertIn("fold2_short_donchian80_offhours_oi_cooling", names)
        self.assertIn("fold2_short_donchian80_ny_sell_pressure", names)

    def test_relative_strength_percentile_uses_basket_returns(self) -> None:
        market_data = {
            "ETHUSDT": self.make_market_data("ETHUSDT", [100.0, 101.0, 102.0, 105.0, 110.0]),
            "SOLUSDT": self.make_market_data("SOLUSDT", [100.0, 99.0, 98.0, 95.0, 90.0]),
            "BNBUSDT": self.make_market_data("BNBUSDT", [100.0, 100.0, 100.0, 100.0, 100.0]),
        }
        signal_close_time = 5 * 900_000
        self.assertEqual(
            harness.relative_strength_percentile("ETHUSDT", market_data, signal_close_time, 1.0),
            1.0,
        )
        self.assertAlmostEqual(
            harness.basket_positive_share_pct(market_data, signal_close_time, 1.0) or 0.0,
            100.0 / 3.0,
        )

    def test_ai_scorecard_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "ai_scorecard_v2"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 7)
        self.assertIn("ai_score_v2_base_score5", names)
        self.assertIn("ai_score_v2_moderate_compression_score5", names)

    def test_ai_scorecard_ablation_candidates_are_available(self) -> None:
        focused = [
            candidate for candidate in harness.build_candidates() if candidate.family == "ai_scorecard_v2_ablation"
        ]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), len(harness.AI_SCORECARD_V2_ABLATION_COMPONENTS) + 1)
        self.assertIn("ai_score_v2_ablation_control_score7", names)
        self.assertIn("ai_score_v2_ablate_session", names)
        self.assertIn("ai_score_v2_ablate_top_position", names)

    def test_ai_scorecard_global_sweep_candidates_are_available(self) -> None:
        focused = [
            candidate for candidate in harness.build_candidates() if candidate.family == "ai_scorecard_v2_global_sweep"
        ]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 14)
        self.assertIn("ai_score_global_base_s6_g120", names)
        self.assertIn("ai_score_global_base_s7_g150_toppos160", names)
        self.assertIn("ai_score_global_oi_s6_g120", names)
        self.assertIn("ai_score_global_oi_s7_g150_toppos160", names)

    def test_ai_scorecard_ablation_removes_only_selected_component(self) -> None:
        signal_time, funding_rows, metric_rows = self.make_scorecard_context()
        base_candidate = harness.CandidateSpec(
            "ai_score_base_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
        )
        ablated_candidate = harness.CandidateSpec(
            "ai_score_ablate_fee_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"ablate_ai_components": "fee"},
        )

        base_score, base_components = harness.ai_scorecard_v2(
            base_candidate,
            "ETHUSDT",
            signal_time,
            [],
            [],
            self.make_risk_plan(),
            10.0,
            funding_rows,
            metric_rows,
            None,
        )
        ablated_score, ablated_components = harness.ai_scorecard_v2(
            ablated_candidate,
            "ETHUSDT",
            signal_time,
            [],
            [],
            self.make_risk_plan(),
            10.0,
            funding_rows,
            metric_rows,
            None,
        )

        self.assertEqual(base_components["fee_points"], 1)
        self.assertEqual(ablated_components["fee_points"], 0)
        self.assertEqual(ablated_components["fee_raw_points"], 1)
        self.assertTrue(ablated_components["fee_ablated"])
        self.assertEqual(base_score - ablated_score, 1)

    def test_ai_scorecard_ablation_affects_min_score_gate(self) -> None:
        signal_time, funding_rows, metric_rows = self.make_scorecard_context()
        candidate = harness.CandidateSpec(
            "ai_score_gate_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"min_ai_score": 11},
        )
        ablated_candidate = harness.CandidateSpec(
            "ai_score_gate_ablate_fee_fixture",
            "test",
            "v2_reclaim",
            study.StrategyConfig("test"),
            params={"min_ai_score": 11, "ablate_ai_components": "fee"},
        )

        self.assertTrue(
            harness.passes_post_signal_filters(
                candidate,
                "ETHUSDT",
                signal_time,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                funding_rows,
                metric_rows,
                None,
            )
        )
        self.assertFalse(
            harness.passes_post_signal_filters(
                ablated_candidate,
                "ETHUSDT",
                signal_time,
                [],
                [],
                self.make_risk_plan(),
                10.0,
                funding_rows,
                metric_rows,
                None,
            )
        )

    def test_risk_off_london_relief_candidates_are_available(self) -> None:
        focused = [candidate for candidate in harness.build_candidates() if candidate.family == "risk_off_london_relief"]
        names = {candidate.name for candidate in focused}
        self.assertEqual(len(focused), 6)
        self.assertIn("risk_off_london_relief_base", names)
        self.assertIn("risk_off_london_relief_fast", names)


if __name__ == "__main__":
    unittest.main()
