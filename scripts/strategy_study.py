#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterable


BINANCE_DATA_API = "https://data-api.binance.vision"
BINANCE_MAX_LIMIT = 1000
DEFAULT_FEE_BPS = 10.0
BTC_REFERENCE_SYMBOL = "BTCUSDT"
SIGNAL_SESSION_START_HOUR_UTC = 7
SIGNAL_SESSION_END_HOUR_UTC = 22
SIGNAL_CORRELATION_LOOKBACK_RETURNS = 96
SIGNAL_CORRELATION_MIN_SAMPLES = 48
SIGNAL_CORRELATION_THRESHOLD = 0.88
SIGNAL_STALK_ATR_DISTANCE_MAX = 0.5
SIGNAL_RECLAIM_ATR_DISTANCE_MAX = 0.5


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class StructureSnapshot:
    bias: str
    last_pivot_high: float | None
    previous_pivot_high: float | None
    last_pivot_low: float | None
    previous_pivot_low: float | None
    slope_up: bool


@dataclass(frozen=True)
class TriggerSnapshot:
    momentum_close: bool
    close_above_previous_high: bool
    body_ratio: float
    close_location: float


@dataclass(frozen=True)
class RiskPlan:
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_per_unit: float
    risk_amount: float
    suggested_quantity: float
    notional_estimate: float


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    pivot_span: int = 2
    stalk_atr_distance_max: float = SIGNAL_STALK_ATR_DISTANCE_MAX
    reclaim_atr_distance_max: float = SIGNAL_RECLAIM_ATR_DISTANCE_MAX
    allow_neutral_setup: bool = True
    trigger_body_ratio_min: float = 0.55
    trigger_close_location_min: float = 0.70
    require_close_above_previous_high: bool = True
    stop_support_buffer_atr_1h: float = 0.25
    stop_atr_mult_15m: float = 1.5
    tp1_r_multiple: float = 1.0
    tp2_r_multiple: float = 2.0
    risk_percent: float = 0.01
    serial_mode: bool = False


@dataclass(frozen=True)
class EvaluatedSignal:
    bias: str
    stage: str
    confidence: int
    support_level: float | None
    distance_to_support: float | None
    trigger: TriggerSnapshot
    risk_plan: RiskPlan | None
    cash_capped: bool


@dataclass(frozen=True)
class ReplayTrade:
    opened_at: int
    closed_at: int
    outcome: str
    gross_r: float
    net_r: float
    bars_held: int
    fees_paid: float


@dataclass
class SymbolStudy:
    symbol: str
    config: str
    lookback_trigger_candles: int
    executed_trades: int
    raw_ready_signals: int
    raw_setup_signals: int
    session_filtered_ready: int
    correlation_filtered_ready: int
    tp1_hits: int
    tp2_hits: int
    stop_losses: int
    breakeven_exits: int
    timeout_exits: int
    gross_total_r: float
    net_total_r: float
    gross_avg_r: float
    net_avg_r: float
    tp1_win_rate_percent: float
    median_bars_held: float


def json_request(path: str, query: dict[str, str | int]) -> list[list[object]]:
    url = f"{BINANCE_DATA_API}{path}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_klines(symbol: str, interval: str, total_limit: int) -> list[Candle]:
    candles: list[Candle] = []
    end_time: int | None = None

    while len(candles) < total_limit:
        request_limit = min(BINANCE_MAX_LIMIT, total_limit - len(candles))
        query: dict[str, str | int] = {
            "symbol": symbol,
            "interval": interval,
            "limit": request_limit,
        }
        if end_time is not None:
            query["endTime"] = end_time

        chunk = json_request("/api/v3/klines", query)
        if not chunk:
            break

        parsed = [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in chunk
        ]

        earliest = parsed[0].open_time
        candles = parsed + candles
        end_time = earliest - 1

        if len(parsed) < request_limit:
            break

        time.sleep(0.1)

    deduped: list[Candle] = []
    seen: set[int] = set()
    for candle in candles:
        if candle.open_time in seen:
            continue
        seen.add(candle.open_time)
        deduped.append(candle)

    deduped.sort(key=lambda item: item.open_time)
    return deduped[-total_limit:]


def interval_millis(interval: str) -> int:
    mapping = {
        "1m": 60_000,
        "5m": 5 * 60_000,
        "15m": 15 * 60_000,
        "1h": 60 * 60_000,
        "4h": 4 * 60 * 60_000,
    }
    return mapping[interval]


def closed_candles_until(candles: list[Candle], cutoff_time: int, interval: str) -> list[Candle]:
    millis = interval_millis(interval)
    left = 0
    right = len(candles)
    while left < right:
        middle = (left + right) // 2
        if candles[middle].open_time + millis <= cutoff_time:
            left = middle + 1
        else:
            right = middle
    return candles[:left]


def find_pivot_highs(candles: list[Candle], span: int) -> list[tuple[int, float]]:
    pivots: list[tuple[int, float]] = []
    if len(candles) < span * 2 + 1:
        return pivots

    for index in range(span, len(candles) - span):
        price = candles[index].high
        if all(candidate == index or candles[candidate].high < price for candidate in range(index - span, index + span + 1)):
            pivots.append((index, price))
    return pivots


def find_pivot_lows(candles: list[Candle], span: int) -> list[tuple[int, float]]:
    pivots: list[tuple[int, float]] = []
    if len(candles) < span * 2 + 1:
        return pivots

    for index in range(span, len(candles) - span):
        price = candles[index].low
        if all(candidate == index or candles[candidate].low > price for candidate in range(index - span, index + span + 1)):
            pivots.append((index, price))
    return pivots


def analyze_structure(candles: list[Candle], span: int) -> StructureSnapshot:
    highs = find_pivot_highs(candles, span)
    lows = find_pivot_lows(candles, span)
    previous_pivot_high = highs[-2][1] if len(highs) >= 2 else None
    last_pivot_high = highs[-1][1] if highs else None
    previous_pivot_low = lows[-2][1] if len(lows) >= 2 else None
    last_pivot_low = lows[-1][1] if lows else None

    slope_up = len(candles) >= 13 and candles[-1].close > candles[-13].close
    slope_down = len(candles) >= 13 and candles[-1].close < candles[-13].close

    bullish = (
        previous_pivot_high is not None
        and last_pivot_high is not None
        and previous_pivot_low is not None
        and last_pivot_low is not None
        and last_pivot_high > previous_pivot_high
        and last_pivot_low > previous_pivot_low
        and slope_up
    )
    bearish = (
        previous_pivot_high is not None
        and last_pivot_high is not None
        and previous_pivot_low is not None
        and last_pivot_low is not None
        and last_pivot_high < previous_pivot_high
        and last_pivot_low < previous_pivot_low
        and slope_down
    )

    if bullish:
        bias = "bullish"
    elif bearish:
        bias = "bearish"
    else:
        bias = "neutral"

    return StructureSnapshot(
        bias=bias,
        last_pivot_high=last_pivot_high,
        previous_pivot_high=previous_pivot_high,
        last_pivot_low=last_pivot_low,
        previous_pivot_low=previous_pivot_low,
        slope_up=slope_up,
    )


def calculate_atr(candles: list[Candle], period: int) -> float | None:
    if len(candles) <= period:
        return None

    true_ranges: list[float] = []
    for index in range(1, len(candles)):
        current = candles[index]
        previous_close = candles[index - 1].close
        range_1 = current.high - current.low
        range_2 = abs(current.high - previous_close)
        range_3 = abs(current.low - previous_close)
        true_ranges.append(max(range_1, range_2, range_3))

    atr_slice = true_ranges[-period:]
    return sum(atr_slice) / len(atr_slice)


def analyze_trigger(candles: list[Candle], config: StrategyConfig) -> TriggerSnapshot:
    if not candles:
        return TriggerSnapshot(False, False, 0.0, 0.0)

    last = candles[-1]
    previous = candles[-2] if len(candles) >= 2 else None
    range_size = max(last.high - last.low, 1e-9)
    body_ratio = min(max(abs(last.close - last.open) / range_size, 0.0), 1.0)
    close_location = min(max((last.close - last.low) / range_size, 0.0), 1.0)
    close_above_previous_high = previous is not None and last.close > previous.high
    momentum_close = (
        last.close > last.open
        and body_ratio >= config.trigger_body_ratio_min
        and close_location >= config.trigger_close_location_min
        and (
            not config.require_close_above_previous_high
            or close_above_previous_high
        )
    )

    return TriggerSnapshot(
        momentum_close=momentum_close,
        close_above_previous_high=close_above_previous_high,
        body_ratio=body_ratio,
        close_location=close_location,
    )


def max_affordable_quantity(available_cash: float, price: float, fee_bps: float) -> float:
    if available_cash <= 0.0 or price <= 0.0:
        return 0.0
    fee_multiplier = 1.0 + (fee_bps / 10_000.0)
    if not math.isfinite(fee_multiplier) or fee_multiplier <= 0.0:
        return 0.0
    return available_cash / (price * fee_multiplier)


def evaluate_session_filter(timestamp_ms: int) -> bool:
    hour = time.gmtime(timestamp_ms / 1000).tm_hour
    return SIGNAL_SESSION_START_HOUR_UTC <= hour < SIGNAL_SESSION_END_HOUR_UTC


def close_returns_by_time(candles: list[Candle]) -> list[tuple[int, float]]:
    values: list[tuple[int, float]] = []
    for previous, current in zip(candles, candles[1:]):
        if previous.close <= 0.0:
            continue
        values.append((current.open_time, (current.close - previous.close) / previous.close))
    return values


def pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    covariance = 0.0
    variance_x = 0.0
    variance_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        covariance += dx * dy
        variance_x += dx * dx
        variance_y += dy * dy
    denominator = math.sqrt(variance_x * variance_y)
    if denominator <= 1e-12:
        return None
    return max(min(covariance / denominator, 1.0), -1.0)


def calculate_return_correlation(
    left: list[Candle],
    right: list[Candle],
    lookback_returns: int,
) -> float | None:
    left_returns = close_returns_by_time(left)
    right_returns = close_returns_by_time(right)
    if not left_returns or not right_returns:
        return None

    right_map = {timestamp: value for timestamp, value in right_returns}
    xs: list[float] = []
    ys: list[float] = []

    for timestamp, left_value in reversed(left_returns):
        right_value = right_map.get(timestamp)
        if right_value is None:
            continue
        xs.append(left_value)
        ys.append(right_value)
        if len(xs) >= lookback_returns:
            break

    xs.reverse()
    ys.reverse()
    if len(xs) < SIGNAL_CORRELATION_MIN_SAMPLES:
        return None
    return pearson_correlation(xs, ys)


def evaluate_correlation_filter(
    symbol: str,
    symbol_trigger_candles: list[Candle],
    btc_trend_candles: list[Candle],
    btc_trigger_candles: list[Candle],
) -> bool:
    if symbol == BTC_REFERENCE_SYMBOL:
        return True

    btc_bias = analyze_structure(btc_trend_candles, 2).bias
    correlation = calculate_return_correlation(
        symbol_trigger_candles,
        btc_trigger_candles,
        SIGNAL_CORRELATION_LOOKBACK_RETURNS,
    )
    if correlation is None:
        return False
    if correlation >= SIGNAL_CORRELATION_THRESHOLD and btc_bias != "bullish":
        return False
    return True


def build_risk_plan(
    entry: float,
    support_level: float | None,
    atr_1h: float | None,
    atr_15m: float | None,
    available_cash: float,
    fee_bps: float,
    config: StrategyConfig,
) -> tuple[RiskPlan | None, bool]:
    if (
        support_level is None
        or atr_1h is None
        or atr_15m is None
        or entry <= 0.0
        or available_cash <= 0.0
    ):
        return None, False

    structural_stop = support_level - atr_1h * config.stop_support_buffer_atr_1h
    atr_stop = entry - atr_15m * config.stop_atr_mult_15m
    stop_loss = min(structural_stop, atr_stop)
    if stop_loss <= 0.0 or stop_loss >= entry:
        return None, False

    risk_per_unit = entry - stop_loss
    if risk_per_unit <= 0.0:
        return None, False

    desired_risk_amount = available_cash * config.risk_percent
    quantity_by_risk = desired_risk_amount / risk_per_unit
    quantity_by_cash = max_affordable_quantity(available_cash, entry, fee_bps)
    if quantity_by_cash <= 0.0:
        return None, False

    suggested_quantity = min(quantity_by_risk, quantity_by_cash)
    if not math.isfinite(suggested_quantity) or suggested_quantity <= 0.0:
        return None, False

    risk_amount = suggested_quantity * risk_per_unit
    return (
        RiskPlan(
            entry=entry,
            stop_loss=stop_loss,
            take_profit_1=entry + risk_per_unit * config.tp1_r_multiple,
            take_profit_2=entry + risk_per_unit * config.tp2_r_multiple,
            risk_per_unit=risk_per_unit,
            risk_amount=risk_amount,
            suggested_quantity=suggested_quantity,
            notional_estimate=suggested_quantity * entry,
        ),
        quantity_by_risk > quantity_by_cash + 1e-9,
    )


def calculate_signal_confidence(
    trend_ok: bool,
    stalk_ok: bool,
    setup_ok: bool,
    trigger_ok: bool,
    risk_ok: bool,
) -> int:
    score = 15
    if trend_ok:
        score += 25
    if stalk_ok:
        score += 15
    if setup_ok:
        score += 20
    if trigger_ok:
        score += 15
    if risk_ok:
        score += 10
    return min(score, 95)


def evaluate_signal(
    current_price: float,
    available_cash: float,
    fee_bps: float,
    trend_candles: list[Candle],
    setup_candles: list[Candle],
    trigger_candles: list[Candle],
    config: StrategyConfig,
) -> EvaluatedSignal:
    trend = analyze_structure(trend_candles, config.pivot_span)
    setup = analyze_structure(setup_candles, config.pivot_span)
    atr_1h = calculate_atr(setup_candles, 14)
    atr_15m = calculate_atr(trigger_candles, 14)

    support_level: float | None
    if setup.last_pivot_low is not None and setup.previous_pivot_high is not None:
        support_level = max(setup.last_pivot_low, setup.previous_pivot_high)
    else:
        support_level = setup.last_pivot_low if setup.last_pivot_low is not None else setup.previous_pivot_high

    setup_reference_price = setup_candles[-1].close if setup_candles else current_price
    distance_to_support = setup_reference_price - support_level if support_level is not None else None
    trend_ok = trend.bias == "bullish"
    setup_bias_ok = setup.bias == "bullish" or (config.allow_neutral_setup and setup.bias == "neutral")
    near_support = (
        distance_to_support is not None
        and atr_1h is not None
        and abs(distance_to_support) <= atr_1h * config.stalk_atr_distance_max
    )
    reclaim_ok = (
        distance_to_support is not None
        and atr_1h is not None
        and distance_to_support >= 0.0
        and distance_to_support <= atr_1h * config.reclaim_atr_distance_max
    )
    stalk_ok = (
        trend_ok
        and setup_bias_ok
        and support_level is not None
        and near_support
    )
    setup_ok = trend_ok and setup_bias_ok and support_level is not None and reclaim_ok

    trigger = analyze_trigger(trigger_candles, config)
    trigger_ok = setup_ok and trigger.momentum_close
    if setup_ok:
        risk_plan, cash_capped = build_risk_plan(
            current_price,
            support_level,
            atr_1h,
            atr_15m,
            available_cash,
            fee_bps,
            config,
        )
    else:
        risk_plan, cash_capped = None, False

    if trend_ok and setup_ok and trigger_ok and risk_plan is not None:
        stage = "ready"
    elif trend_ok and setup_ok:
        stage = "setup"
    elif stalk_ok:
        stage = "stalk"
    else:
        stage = "wait"

    confidence = calculate_signal_confidence(
        trend_ok,
        stalk_ok,
        setup_ok,
        trigger_ok,
        risk_plan is not None,
    )

    return EvaluatedSignal(
        bias=trend.bias,
        stage=stage,
        confidence=confidence,
        support_level=support_level,
        distance_to_support=distance_to_support,
        trigger=trigger,
        risk_plan=risk_plan,
        cash_capped=cash_capped,
    )


def fee_r_for_notional(notional: float, risk_amount: float, fee_bps: float) -> float:
    if risk_amount <= 0.0:
        return 0.0
    return (notional * fee_bps / 10_000.0) / risk_amount


def simulate_trade(
    opened_at: int,
    risk_plan: RiskPlan,
    future_candles: list[Candle],
    fee_bps: float,
) -> ReplayTrade:
    closed_at = opened_at
    outcome = "timeout"
    gross_r = 0.0
    bars_held = len(future_candles)
    tp1_hit_index: int | None = None
    exit_price = risk_plan.entry
    fees_paid = risk_plan.notional_estimate * fee_bps / 10_000.0

    for index, candle in enumerate(future_candles):
        hit_stop = candle.low <= risk_plan.stop_loss
        hit_tp1 = candle.high >= risk_plan.take_profit_1

        if hit_stop and hit_tp1:
            closed_at = candle.open_time + interval_millis("15m")
            outcome = "stop_loss"
            gross_r = -1.0
            bars_held = index + 1
            exit_price = risk_plan.stop_loss
            fees_paid += risk_plan.suggested_quantity * risk_plan.stop_loss * fee_bps / 10_000.0
            break
        if hit_stop:
            closed_at = candle.open_time + interval_millis("15m")
            outcome = "stop_loss"
            gross_r = -1.0
            bars_held = index + 1
            exit_price = risk_plan.stop_loss
            fees_paid += risk_plan.suggested_quantity * risk_plan.stop_loss * fee_bps / 10_000.0
            break
        if hit_tp1:
            tp1_hit_index = index
            break

    if tp1_hit_index is not None and outcome != "stop_loss":
        half_quantity = risk_plan.suggested_quantity / 2.0
        fees_paid += half_quantity * risk_plan.take_profit_1 * fee_bps / 10_000.0
        for offset, candle in enumerate(future_candles[tp1_hit_index:], start=tp1_hit_index):
            hit_break_even = candle.low <= risk_plan.entry
            hit_tp2 = candle.high >= risk_plan.take_profit_2
            closed_at = candle.open_time + interval_millis("15m")
            bars_held = offset + 1

            if hit_break_even and hit_tp2:
                outcome = "breakeven"
                gross_r = 0.5
                exit_price = risk_plan.entry
                fees_paid += half_quantity * risk_plan.entry * fee_bps / 10_000.0
                break
            if hit_tp2:
                outcome = "take_profit_2"
                gross_r = 1.5
                exit_price = risk_plan.take_profit_2
                fees_paid += half_quantity * risk_plan.take_profit_2 * fee_bps / 10_000.0
                break
            if hit_break_even:
                outcome = "breakeven"
                gross_r = 0.5
                exit_price = risk_plan.entry
                fees_paid += half_quantity * risk_plan.entry * fee_bps / 10_000.0
                break
        else:
            last = future_candles[-1]
            closed_at = last.open_time + interval_millis("15m")
            bars_held = len(future_candles)
            outcome = "timeout"
            exit_price = last.close
            gross_r = 0.5 + 0.5 * ((last.close - risk_plan.entry) / risk_plan.risk_per_unit)
            fees_paid += half_quantity * last.close * fee_bps / 10_000.0
    elif outcome == "timeout":
        last = future_candles[-1]
        closed_at = last.open_time + interval_millis("15m")
        bars_held = len(future_candles)
        exit_price = last.close
        gross_r = (last.close - risk_plan.entry) / risk_plan.risk_per_unit
        fees_paid += risk_plan.suggested_quantity * last.close * fee_bps / 10_000.0

    net_r = gross_r - (fees_paid / risk_plan.risk_amount)
    if not math.isfinite(net_r):
        net_r = gross_r

    return ReplayTrade(
        opened_at=opened_at,
        closed_at=closed_at,
        outcome=outcome,
        gross_r=gross_r,
        net_r=net_r,
        bars_held=bars_held,
        fees_paid=fees_paid,
    )


def study_symbol(
    symbol: str,
    trigger_limit: int,
    forward_candles: int,
    fee_bps: float,
    config: StrategyConfig,
) -> SymbolStudy:
    setup_limit = math.ceil(trigger_limit / 4) + 120
    trend_limit = math.ceil(trigger_limit / 16) + 120

    trigger_candles = fetch_klines(symbol, "15m", trigger_limit)
    setup_candles = fetch_klines(symbol, "1h", setup_limit)
    trend_candles = fetch_klines(symbol, "4h", trend_limit)
    if symbol == BTC_REFERENCE_SYMBOL:
        btc_trigger_candles = trigger_candles
        btc_trend_candles = trend_candles
    else:
        btc_trigger_candles = fetch_klines(BTC_REFERENCE_SYMBOL, "15m", trigger_limit)
        btc_trend_candles = fetch_klines(BTC_REFERENCE_SYMBOL, "4h", trend_limit)
    return study_symbol_with_candles(
        symbol=symbol,
        trigger_candles=trigger_candles,
        setup_candles=setup_candles,
        trend_candles=trend_candles,
        btc_trigger_candles=btc_trigger_candles,
        btc_trend_candles=btc_trend_candles,
        forward_candles=forward_candles,
        fee_bps=fee_bps,
        config=config,
    )


def study_symbol_with_candles(
    symbol: str,
    trigger_candles: list[Candle],
    setup_candles: list[Candle],
    trend_candles: list[Candle],
    btc_trigger_candles: list[Candle],
    btc_trend_candles: list[Candle],
    forward_candles: int,
    fee_bps: float,
    config: StrategyConfig,
) -> SymbolStudy:

    raw_ready_signals = 0
    raw_setup_signals = 0
    session_filtered_ready = 0
    correlation_filtered_ready = 0
    trades: list[ReplayTrade] = []
    tp1_hits = 0
    tp2_hits = 0
    stop_losses = 0
    breakeven_exits = 0
    timeout_exits = 0

    last_index = len(trigger_candles) - forward_candles - 1
    index = 0
    while index < last_index:
        signal_candle = trigger_candles[index]
        signal_close_time = signal_candle.open_time + interval_millis("15m")
        trend_slice = closed_candles_until(trend_candles, signal_close_time, "4h")
        setup_slice = closed_candles_until(setup_candles, signal_close_time, "1h")
        trigger_slice = trigger_candles[: index + 1]

        evaluation = evaluate_signal(
            signal_candle.close,
            10_000.0,
            fee_bps,
            trend_slice,
            setup_slice,
            trigger_slice,
            config,
        )

        if evaluation.stage in {"stalk", "setup", "ready"}:
            raw_setup_signals += 1
        if evaluation.stage == "ready" and evaluation.risk_plan is not None:
            if not evaluate_session_filter(signal_close_time):
                session_filtered_ready += 1
                index += 1
                continue

            if symbol != BTC_REFERENCE_SYMBOL:
                btc_trend_slice = closed_candles_until(btc_trend_candles, signal_close_time, "4h")
                btc_trigger_slice = closed_candles_until(btc_trigger_candles, signal_close_time, "15m")
                if not evaluate_correlation_filter(symbol, trigger_slice, btc_trend_slice, btc_trigger_slice):
                    correlation_filtered_ready += 1
                    index += 1
                    continue

            raw_ready_signals += 1
            future_slice = trigger_candles[index + 1 : index + 1 + forward_candles]
            trade = simulate_trade(signal_close_time, evaluation.risk_plan, future_slice, fee_bps)
            trades.append(trade)
            if trade.outcome == "take_profit_2":
                tp1_hits += 1
                tp2_hits += 1
            elif trade.outcome == "breakeven":
                tp1_hits += 1
                breakeven_exits += 1
            elif trade.outcome == "stop_loss":
                stop_losses += 1
            elif trade.outcome == "timeout":
                timeout_exits += 1

            if config.serial_mode:
                index += max(1, trade.bars_held)
                continue

        index += 1

    executed_trades = len(trades)
    gross_total_r = sum(trade.gross_r for trade in trades)
    net_total_r = sum(trade.net_r for trade in trades)
    gross_avg_r = gross_total_r / executed_trades if executed_trades else 0.0
    net_avg_r = net_total_r / executed_trades if executed_trades else 0.0
    tp1_win_rate = (tp1_hits / executed_trades) * 100.0 if executed_trades else 0.0
    median_bars_held = statistics.median([trade.bars_held for trade in trades]) if trades else 0.0

    return SymbolStudy(
        symbol=symbol,
        config=config.name,
        lookback_trigger_candles=len(trigger_candles),
        executed_trades=executed_trades,
        raw_ready_signals=raw_ready_signals,
        raw_setup_signals=raw_setup_signals,
        session_filtered_ready=session_filtered_ready,
        correlation_filtered_ready=correlation_filtered_ready,
        tp1_hits=tp1_hits,
        tp2_hits=tp2_hits,
        stop_losses=stop_losses,
        breakeven_exits=breakeven_exits,
        timeout_exits=timeout_exits,
        gross_total_r=gross_total_r,
        net_total_r=net_total_r,
        gross_avg_r=gross_avg_r,
        net_avg_r=net_avg_r,
        tp1_win_rate_percent=tp1_win_rate,
        median_bars_held=median_bars_held,
    )


def summarize(results: list[SymbolStudy]) -> list[dict[str, object]]:
    grouped: dict[str, list[SymbolStudy]] = {}
    for item in results:
        grouped.setdefault(item.config, []).append(item)

    summaries: list[dict[str, object]] = []
    for config_name, items in grouped.items():
        executed_trades = sum(item.executed_trades for item in items)
        raw_ready = sum(item.raw_ready_signals for item in items)
        raw_setup = sum(item.raw_setup_signals for item in items)
        session_filtered_ready = sum(item.session_filtered_ready for item in items)
        correlation_filtered_ready = sum(item.correlation_filtered_ready for item in items)
        tp1_hits = sum(item.tp1_hits for item in items)
        tp2_hits = sum(item.tp2_hits for item in items)
        stop_losses = sum(item.stop_losses for item in items)
        breakeven_exits = sum(item.breakeven_exits for item in items)
        timeout_exits = sum(item.timeout_exits for item in items)
        gross_total_r = sum(item.gross_total_r for item in items)
        net_total_r = sum(item.net_total_r for item in items)

        summaries.append(
            {
                "config": config_name,
                "symbols": len(items),
                "executed_trades": executed_trades,
                "raw_ready_signals": raw_ready,
                "raw_setup_signals": raw_setup,
                "session_filtered_ready": session_filtered_ready,
                "correlation_filtered_ready": correlation_filtered_ready,
                "tp1_win_rate_percent": round((tp1_hits / executed_trades) * 100.0, 2) if executed_trades else 0.0,
                "tp2_hits": tp2_hits,
                "stop_losses": stop_losses,
                "breakeven_exits": breakeven_exits,
                "timeout_exits": timeout_exits,
                "gross_total_r": round(gross_total_r, 3),
                "net_total_r": round(net_total_r, 3),
                "gross_avg_r": round(gross_total_r / executed_trades, 3) if executed_trades else 0.0,
                "net_avg_r": round(net_total_r / executed_trades, 3) if executed_trades else 0.0,
            }
        )

    summaries.sort(key=lambda item: (item["net_total_r"], item["net_avg_r"]), reverse=True)
    return summaries


def build_configs() -> list[StrategyConfig]:
    return [
        StrategyConfig(
            name="v2_reclaim",
        ),
        StrategyConfig(
            name="v2_reclaim_strong_trigger",
            allow_neutral_setup=False,
            trigger_body_ratio_min=0.65,
            trigger_close_location_min=0.80,
        ),
        StrategyConfig(
            name="v2_reclaim_strict_1h",
            allow_neutral_setup=False,
            trigger_body_ratio_min=0.60,
            trigger_close_location_min=0.75,
        ),
        StrategyConfig(
            name="v2_reclaim_serial",
            allow_neutral_setup=False,
            trigger_body_ratio_min=0.60,
            trigger_close_location_min=0.75,
            serial_mode=True,
        ),
    ]


def format_table(rows: Iterable[dict[str, object]]) -> str:
    rows = list(rows)
    if not rows:
        return ""
    columns = list(rows[0].keys())
    widths = {
        column: max(len(column), *(len(str(row[column])) for row in rows))
        for column in columns
    }
    header = "  ".join(column.ljust(widths[column]) for column in columns)
    divider = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(str(row[column]).ljust(widths[column]) for column in columns)
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a longer replay study against Binance market data.")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"])
    parser.add_argument("--trigger-limit", type=int, default=4000, help="How many 15m candles to study.")
    parser.add_argument("--forward-candles", type=int, default=32, help="How many 15m candles to inspect after entry.")
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--json-out", type=str, default=None)
    args = parser.parse_args()

    configs = build_configs()
    results: list[SymbolStudy] = []

    setup_limit = math.ceil(args.trigger_limit / 4) + 120
    trend_limit = math.ceil(args.trigger_limit / 16) + 120

    for symbol in args.symbols:
        print(f"[fetch] {symbol} :: 15m={args.trigger_limit}, 1h={setup_limit}, 4h={trend_limit}", file=sys.stderr)
        trigger_candles = fetch_klines(symbol, "15m", args.trigger_limit)
        setup_candles = fetch_klines(symbol, "1h", setup_limit)
        trend_candles = fetch_klines(symbol, "4h", trend_limit)
        if symbol == BTC_REFERENCE_SYMBOL:
            btc_trigger_candles = trigger_candles
            btc_trend_candles = trend_candles
        else:
            print(f"[fetch] {symbol} :: BTC reference", file=sys.stderr)
            btc_trigger_candles = fetch_klines(BTC_REFERENCE_SYMBOL, "15m", args.trigger_limit)
            btc_trend_candles = fetch_klines(BTC_REFERENCE_SYMBOL, "4h", trend_limit)

        for config in configs:
            print(f"[study] {symbol} :: {config.name}", file=sys.stderr)
            results.append(
                study_symbol_with_candles(
                    symbol=symbol,
                    trigger_candles=trigger_candles,
                    setup_candles=setup_candles,
                    trend_candles=trend_candles,
                    btc_trigger_candles=btc_trigger_candles,
                    btc_trend_candles=btc_trend_candles,
                    forward_candles=args.forward_candles,
                    fee_bps=args.fee_bps,
                    config=config,
                )
            )

    detail_rows = [
        {
            "config": item.config,
            "symbol": item.symbol,
            "trades": item.executed_trades,
            "ready": item.raw_ready_signals,
            "stalk_setup": item.raw_setup_signals,
            "session_cut": item.session_filtered_ready,
            "corr_cut": item.correlation_filtered_ready,
            "tp1_win_%": round(item.tp1_win_rate_percent, 2),
            "gross_R": round(item.gross_total_r, 3),
            "net_R": round(item.net_total_r, 3),
            "avg_net_R": round(item.net_avg_r, 3),
            "median_hold_bars": round(item.median_bars_held, 1),
        }
        for item in results
    ]
    summary_rows = summarize(results)

    print("\n=== Summary ===")
    print(format_table(summary_rows))
    print("\n=== Detail ===")
    print(format_table(detail_rows))

    if args.json_out:
        payload = {
            "generated_at": int(time.time() * 1000),
            "trigger_limit": args.trigger_limit,
            "forward_candles": args.forward_candles,
            "fee_bps": args.fee_bps,
            "summary": summary_rows,
            "detail": detail_rows,
        }
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
