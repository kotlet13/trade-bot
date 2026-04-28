#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import derivatives_data
import research_harness as harness
import strategy_study as study


ACTIVE_STRATEGY = "ai_score_v2_base_score7"
DEFAULT_BASE_URL = "http://localhost:8081"
DEFAULT_SYMBOLS = "ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT"
FAPI_BASE_URL = "https://fapi.binance.com"
SCORE_TOLERANCE = 0


@dataclass(frozen=True)
class ParityRow:
    symbol: str
    runtime_stage: str
    python_stage: str
    runtime_technical_stage: str
    python_technical_stage: str
    runtime_ai_score: int
    python_ai_score: int
    runtime_risk_plan: bool
    python_risk_plan: bool
    signal_close_time: int
    generated_at: int
    status: str
    notes: list[str]


def json_get_url(url: str, timeout: int = 30) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fapi_json(path: str, query: dict[str, str | int], timeout: int = 30) -> Any:
    return json_get_url(f"{FAPI_BASE_URL}{path}?{urllib.parse.urlencode(query)}", timeout=timeout)


def runtime_dashboard(base_url: str, symbol: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": "1m"})
    return json_get_url(f"{base_url.rstrip('/')}/api/dashboard?{query}", timeout=60)


def active_candidate() -> harness.CandidateSpec:
    for candidate in harness.build_candidates():
        if candidate.name == ACTIVE_STRATEGY:
            return candidate
    raise RuntimeError(f"Active strategy candidate not found: {ACTIVE_STRATEGY}")


def closed(candles: list[study.Candle], cutoff_time: int, interval: str) -> list[study.Candle]:
    return study.closed_candles_until(candles, cutoff_time, interval)


def latest_row_before(rows: list[dict[str, Any]], cutoff_time: int) -> dict[str, Any] | None:
    selected: dict[str, Any] | None = None
    for row in rows:
        timestamp = int(row["timestamp"])
        if timestamp <= cutoff_time:
            selected = row
    return selected


def latest_funding_rows(symbol: str, signal_close_time: int) -> list[derivatives_data.FundingRate]:
    start_time = signal_close_time - 12 * 60 * 60 * 1000
    payload = fapi_json(
        "/fapi/v1/fundingRate",
        {
            "symbol": symbol,
            "startTime": start_time,
            "endTime": signal_close_time,
            "limit": 1000,
        },
    )
    rows = [derivatives_data.funding_from_json(item) for item in payload] if isinstance(payload, list) else []
    rows.sort(key=lambda item: item.funding_time)
    return rows


def fetch_ratio_rows(path: str, symbol: str, limit: int = 30) -> list[dict[str, Any]]:
    payload = fapi_json(path, {"symbol": symbol, "period": "5m", "limit": limit})
    rows = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    rows.sort(key=lambda item: int(item["timestamp"]))
    return rows


def build_live_metric_rows(
    symbol: str,
    signal_close_time: int,
) -> list[derivatives_data.FuturesMetric]:
    oi_rows = fetch_ratio_rows("/futures/data/openInterestHist", symbol, limit=300)
    global_rows = fetch_ratio_rows("/futures/data/globalLongShortAccountRatio", symbol, limit=30)
    top_position_rows = fetch_ratio_rows("/futures/data/topLongShortPositionRatio", symbol, limit=30)
    taker_rows = fetch_ratio_rows("/futures/data/takerlongshortRatio", symbol, limit=30)

    current_oi = latest_row_before(oi_rows, signal_close_time)
    current_global = latest_row_before(global_rows, signal_close_time)
    current_top_position = latest_row_before(top_position_rows, signal_close_time)
    current_taker = latest_row_before(taker_rows, signal_close_time)
    if not all([current_oi, current_global, current_top_position, current_taker]):
        return []

    current_times = [
        int(current_oi["timestamp"]),
        int(current_global["timestamp"]),
        int(current_top_position["timestamp"]),
        int(current_taker["timestamp"]),
    ]
    current_time = min(current_times)
    max_age_ms = 20 * 60 * 1000
    if any(signal_close_time - timestamp < 0 or signal_close_time - timestamp > max_age_ms for timestamp in current_times):
        return []

    previous_cutoff = signal_close_time - 24 * 60 * 60 * 1000
    previous_oi = latest_row_before(oi_rows, previous_cutoff)

    def metric(row: dict[str, Any], timestamp: int) -> derivatives_data.FuturesMetric:
        return derivatives_data.FuturesMetric(
            symbol=symbol,
            timestamp=timestamp,
            sum_open_interest=float(row.get("sumOpenInterest", 0.0)),
            sum_open_interest_value=float(row.get("sumOpenInterestValue", 0.0)),
            count_toptrader_long_short_ratio=float(current_top_position.get("longShortRatio", 0.0)),
            sum_toptrader_long_short_ratio=float(current_top_position.get("longShortRatio", 0.0)),
            count_long_short_ratio=float(current_global.get("longShortRatio", 0.0)),
            sum_taker_long_short_vol_ratio=float(current_taker.get("buySellRatio", 0.0)),
        )

    rows: list[derivatives_data.FuturesMetric] = []
    if previous_oi is not None:
        rows.append(metric(previous_oi, int(previous_oi["timestamp"])))
    rows.append(metric(current_oi, current_time))
    rows.sort(key=lambda item: item.timestamp)
    return rows


def build_market_data(
    symbols: list[str],
    signal_close_time: int,
    selected_symbol: str,
    selected_trigger: list[study.Candle],
) -> dict[str, harness.MarketData]:
    market_data: dict[str, harness.MarketData] = {}
    for symbol in symbols:
        if symbol == selected_symbol:
            trigger = selected_trigger
        else:
            trigger = closed(study.fetch_klines(symbol, "15m", 160), signal_close_time, "15m")
            time.sleep(0.03)
        market_data[symbol] = harness.MarketData(
            symbol=symbol,
            trigger=trigger,
            setup=[],
            trend=[],
        )
    return market_data


def python_signal(
    symbol: str,
    dashboard: dict[str, Any],
    candidate: harness.CandidateSpec,
) -> dict[str, Any]:
    signal = dashboard["signal_assistant"]
    paper = dashboard["paper"]
    generated_at = int(signal["generated_at"])
    signal_close_time = int(signal.get("signal_close_time") or generated_at)
    current_price = float(
        next(
            ticker["last_price"]
            for ticker in dashboard["tickers"]
            if ticker["symbol"] == symbol
        )
    )
    cash = float(paper["cash_balance"])
    fee_bps = float(paper["fee_bps"])

    trend = closed(study.fetch_klines(symbol, "4h", 160), generated_at, "4h")
    setup = closed(study.fetch_klines(symbol, "1h", 160), generated_at, "1h")
    trigger = closed(study.fetch_klines(symbol, "15m", 160), generated_at, "15m")
    evaluation = study.evaluate_signal(
        current_price,
        cash,
        fee_bps,
        trend,
        setup,
        trigger,
        candidate.config,
    )

    risk_plan = evaluation.risk_plan
    ai_score = 0
    if risk_plan is not None:
        btc_trend = trend if symbol == study.BTC_REFERENCE_SYMBOL else closed(
            study.fetch_klines(study.BTC_REFERENCE_SYMBOL, "4h", 160),
            signal_close_time,
            "4h",
        )
        funding_rows = [] if symbol == study.BTC_REFERENCE_SYMBOL else latest_funding_rows(symbol, signal_close_time)
        metric_rows = [] if symbol == study.BTC_REFERENCE_SYMBOL else build_live_metric_rows(symbol, signal_close_time)
        market_symbols = [item for item in dashboard["watchlist"] if isinstance(item, str)]
        market_data = build_market_data(market_symbols, signal_close_time, symbol, trigger)
        ai_score, _ = harness.ai_scorecard_v2(
            candidate,
            symbol,
            signal_close_time,
            trigger,
            btc_trend,
            risk_plan,
            fee_bps,
            funding_rows,
            metric_rows,
            market_data,
        )

    session_pass = 7 <= datetime.fromtimestamp(signal_close_time / 1000, tz=UTC).hour < 22
    score_pass = ai_score >= 7
    python_risk_plan = evaluation.stage == "ready" and risk_plan is not None and session_pass and score_pass
    return {
        "technical_stage": evaluation.stage,
        "stage": "ready" if python_risk_plan else ("setup" if evaluation.stage == "ready" else evaluation.stage),
        "ai_score": ai_score,
        "risk_plan": python_risk_plan,
        "signal_close_time": signal_close_time,
        "generated_at": generated_at,
    }


def compare_symbol(base_url: str, symbol: str, candidate: harness.CandidateSpec) -> ParityRow:
    dashboard = runtime_dashboard(base_url, symbol)
    runtime = dashboard["signal_assistant"]
    py = python_signal(symbol, dashboard, candidate)
    notes: list[str] = []

    runtime_stage = str(runtime["stage"])
    python_stage = str(py["stage"])
    runtime_technical_stage = str(runtime.get("technical_stage") or runtime_stage)
    python_technical_stage = str(py["technical_stage"])
    runtime_ai_score = int(runtime.get("ai_score") or 0)
    python_ai_score = int(py["ai_score"])
    runtime_risk_plan = bool(runtime.get("risk_plan"))
    python_risk_plan = bool(py["risk_plan"])

    if runtime_technical_stage != python_technical_stage:
        notes.append(f"technical_stage runtime={runtime_technical_stage} python={python_technical_stage}")
    if abs(runtime_ai_score - python_ai_score) > SCORE_TOLERANCE:
        notes.append(f"ai_score runtime={runtime_ai_score} python={python_ai_score}")
    if runtime_risk_plan != python_risk_plan:
        notes.append("risk_plan mismatch; runtime may include news gate that Python parity does not model")
    if int(runtime.get("signal_close_time") or 0) != int(py["signal_close_time"]):
        notes.append("signal_close_time mismatch")

    status = "pass" if not notes else "warn"
    return ParityRow(
        symbol=symbol,
        runtime_stage=runtime_stage,
        python_stage=python_stage,
        runtime_technical_stage=runtime_technical_stage,
        python_technical_stage=python_technical_stage,
        runtime_ai_score=runtime_ai_score,
        python_ai_score=python_ai_score,
        runtime_risk_plan=runtime_risk_plan,
        python_risk_plan=python_risk_plan,
        signal_close_time=int(runtime.get("signal_close_time") or py["signal_close_time"]),
        generated_at=int(runtime.get("generated_at") or py["generated_at"]),
        status=status,
        notes=notes,
    )


def utc_text(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def render_markdown(rows: list[ParityRow]) -> str:
    passed = sum(1 for row in rows if row.status == "pass")
    lines = [
        "# Runtime/Harness Parity Report",
        "",
        f"- Generated: `{utc_text(int(time.time() * 1000))}`",
        f"- Strategy: `{ACTIVE_STRATEGY}`",
        f"- Symbols checked: `{len(rows)}`",
        f"- Passing: `{passed}`",
        f"- Warnings: `{len(rows) - passed}`",
        "",
        "| Symbol | Status | Runtime technical | Python technical | Runtime score | Python score | Runtime risk | Python risk | Notes |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        notes = "<br>".join(row.notes) if row.notes else ""
        lines.append(
            f"| `{row.symbol}` | `{row.status}` | `{row.runtime_technical_stage}` | `{row.python_technical_stage}` "
            f"| `{row.runtime_ai_score}` | `{row.python_ai_score}` | `{row.runtime_risk_plan}` | `{row.python_risk_plan}` | {notes} |"
        )
    return "\n".join(lines) + "\n"


def parse_symbols(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare runtime SignalAssistant decisions with Python harness logic.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = active_candidate()
    rows = [compare_symbol(args.base_url, symbol, candidate) for symbol in parse_symbols(args.symbols)]
    payload = {
        "generated_at": int(time.time() * 1000),
        "strategy": ACTIVE_STRATEGY,
        "rows": [row.__dict__ for row in rows],
        "pass_count": sum(1 for row in rows if row.status == "pass"),
        "warn_count": sum(1 for row in rows if row.status != "pass"),
    }
    markdown = render_markdown(rows)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(markdown, end="")
    return 0 if payload["warn_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
