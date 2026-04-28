# Research Campaign

This project uses `scripts/research_harness.py` for the 4-week profitability tuning campaign. The harness does not promote or change the live `SignalAssistant`; it only produces research artifacts and campaign log entries.

## Fast Smoke

```powershell
python scripts/research_harness.py --smoke --workers 2 --json-out tmp/research_runs/smoke_research_harness.json
```

Use this after code changes. It runs a small top-3, 1000-candle pass and should finish quickly.

## Universe Hygiene

The default universe profile is `strict`. It ranks Binance `*USDT` spot symbols by 24h quote volume, then applies hygiene filters before candle-history checks:

- standard ASCII Binance symbol names only
- no stable/fiat bases
- no leveraged-token suffixes
- no known meme/political/event-driven bases
- only mature/core assets from the strict allowlist
- `--min-quote-volume 5000000` by default

Use `--universe-profile permissive` only for exploratory research, not for promotion decisions.

## Checks

```powershell
python -m py_compile scripts/strategy_study.py scripts/research_harness.py scripts/derivatives_data.py scripts/derivatives_research.py scripts/backfill_metrics.py scripts/event_dataset.py scripts/predictive_meta_model.py scripts/test_research_harness.py scripts/test_derivatives_data.py scripts/test_backfill_metrics.py scripts/test_event_dataset.py scripts/test_predictive_meta_model.py
python scripts/test_research_harness.py
python scripts/test_derivatives_data.py
python scripts/test_backfill_metrics.py
python scripts/test_event_dataset.py
python scripts/test_predictive_meta_model.py
cargo check
```

## Full Weekly Run

```powershell
python scripts/research_harness.py --trigger-limit 12000 --universe-limit 20 --workers 4
```

The full run selects the strict top liquid Binance `*USDT` spot symbols, fetches `15m`, `1h`, and `4h` candles with local cache, evaluates candidate families, writes a JSON artifact to `tmp/research_runs/`, and appends a summary to `tmp/strategy_test_log.md`.

The artifact includes `diagnostics` with gate-failure counts, family summaries, no-trade candidates, positive-holdout candidates, and universe rejection counts. Treat this as the starting point for tuning; do not tune randomly from only the top-line result.

## Promotion Rules

A candidate is eligible for gated paper trading only if all promotion gates pass:

- at least `80` out-of-sample trades
- `net_avg_r >= 0.10`
- `profit_factor >= 1.25`
- positive holdout net R and `holdout_avg_r >= 0.05`
- at least `4` positive validation folds
- `max_drawdown_r <= 10`
- no symbol contributes more than `40%` of positive R
- no single trade contributes more than `25%` of positive R

If nothing passes, the correct action is to stay flat and document the failed hypothesis.

## Derivatives Context

After the candle-only research pass, use `scripts/derivatives_research.py` to add public Binance USD-M context before designing another candidate batch:

```powershell
python scripts/derivatives_research.py --source-artifact tmp/research_runs/focused_scale_top3_universe30_20260426.json --trade-diagnostics tmp/research_runs/near_miss_full_trade_diagnostics_20260427_010625.json
```

The script caches funding rates and open-interest statistics under `tmp/derivatives_cache/`, writes a profile artifact under `tmp/research_runs/`, and joins funding/OI buckets onto the current near-miss trade diagnostics. Treat this as hypothesis generation only. A derivatives-filtered candidate still needs a full clean research run and all promotion gates before paper trading is allowed.

It also reads Binance Vision USD-M daily metrics files when trade diagnostics are available. Those metrics add 5-minute open interest, global account long/short ratio, top-trader account and position long/short ratios, and taker buy/sell volume ratio around each historical trade.

To test funding-gated candidates in the main harness:

```powershell
python scripts/research_harness.py --candidate-family derivatives_filter --trigger-limit 12000 --universe-limit 30 --workers 4
```

To test metrics-gated candidates, use cached Binance Vision metrics by default:

```powershell
python scripts/research_harness.py --candidate-family metrics_filter --trigger-limit 12000 --universe-limit 12 --workers 4
```

Use `--fetch-metrics` only when intentionally backfilling missing metrics, because it may request one daily metrics ZIP per symbol per calendar day.

For controlled Binance Vision metrics backfills:

```powershell
python scripts/backfill_metrics.py --universe-limit 24 --skip-first 12 --json-out tmp/research_runs/metrics_backfill_missing12.json
```

## Current Bottleneck

The latest bounded tests moved from tightening `v2_reclaim` to checking whether the derivatives regime transfers to broader entries:

- `tmp/research_runs/broad_derivatives_entry_full24_20260427.json`: broad EMA, HTF, Donchian, breakout-pullback, and opening-session entries under funding-not-panic plus taker pressure produced enough trades, but all were negative or unstable.
- `tmp/research_runs/broad_derivatives_refined_full24_20260427.json`: London-only HTF continuation was positive overall, but too weak on average R and fold stability.
- `tmp/research_runs/broad_derivatives_oi_sweep_full24_20260427.json`: HTF London plus OI cooling reached acceptable avg R/PF in the best variants, but still failed promotion gates on fold stability, drawdown, or trade count.
- `tmp/research_runs/fold_diagnostics_htf_london_oi_neg10_pos1_20260427.json`: the closest HTF London/OI variant has enough trades and positive holdout, but no validation trades in folds 1-2 and negative folds 4-5. Simple feature filters can improve quality but cannot satisfy the 4-of-5 fold gate.
- `tmp/research_runs/fold_diagnostics_htf_baseline_20260427.json`: ungated HTF continuation has fold-2 trades, but the baseline is strongly negative. Fold 2 is mostly a funding-panic regime; New York panic trades help validation fold coverage but fail badly in holdout.

Current interpretation: the derivatives regime is useful as a filter, but it does not make generic entries robust. The HTF London/OI pocket looks recent-period biased and should not be promoted or kept as the main search path. Keep paper trading blocked.

Coverage-first scan artifacts:

- `tmp/research_runs/coverage_scan_trend_reclaim_full24_20260427.json`: v2 reclaim variants and HTF continuation were tested without derivatives filters. Moderate v2 reclaim was the least bad branch, with all five folds covered and drawdown below 10R, but it failed avg R, PF, holdout avg, and fold stability.
- `tmp/research_runs/coverage_scan_breakout_full24_20260427.json`: EMA, Donchian, breakout-pullback, and opening-breakout entries had strong coverage but were negative across the basket.
- `tmp/research_runs/coverage_scan_reversal_session_full24_20260427.json`: session traps and shock/reversal entries had coverage but were strongly negative.
- `tmp/research_runs/coverage_diagnostics_v2_moderate_20260427.json`: detailed diagnostics showed New York trades were the main drag for the moderate v2 reclaim branch.
- `tmp/research_runs/coverage_refinement_universe30_20260427.json`: no-New-York and 10-16 UTC moderate v2 refinements improved avg R/PF and drawdown, but the strict universe exhausted at 29 symbols and the best variants remained too sparse with only 2 of 5 positive folds.
- `tmp/research_runs/coverage_short_trend_universe30_20260427.json`: short HTF, Donchian breakdown, and EMA short variants were tested as a possible second source for weak folds. They helped fold 1 but were negative in fold 2, fold 5, and holdout.
- `tmp/research_runs/fold_regime_diagnostics_20260427.json`: fold 2 is a broad risk-off regime, not a random candidate failure. BTC returned `-13.7453%`, the basket median returned `-14.9692%`, all `29` inspected symbols were down, BTC max drawdown was `-23.9004%`, and median 24h OI value change was `-1.3229%`. The only intraday relief was London/overlap; New York and off-hours were the main BTC drag.
- `tmp/research_runs/fold2_risk_off_short_universe30_20260427.json`: risk-off short variants targeting New York/off-hours with BTC-down and OI-cooling gates failed. The best variant, `fold2_short_donchian80_offhours_oi_cooling`, still lost `-16.5786R` OOS with `pf=0.7353`, `max_drawdown_r=26.4022`, and `holdout=-5.8567R`. It also lost fold 2 (`-12.4828R`), so the simple answer is not "just short the crash."

Current interpretation after coverage scan: broad entries with good fold coverage are mostly negative. The only promising coverage branch is moderate `v2_reclaim` outside New York, but it remains too sparse and fold-unstable. Fold 2 is a high-volatility, broad-deleveraging regime; naive long entries lose, but naive short entries also lose after fees, stops, and whipsaw. The next search should focus on regime abstention and event-level prediction, not more hand-tightened long/short mirrors.

## AI Scorecard Batch

The next research batch added an explicit scorecard layer around existing entries rather than using AI as a standalone entry engine. The scorecard uses session, fee drag, volume percentile, ATR expansion, BTC 24h return, basket breadth, relative strength, funding, OI change, taker pressure, global account bias, and top-trader position bias.

Artifacts:

- `tmp/research_runs/smoke_ai_scorecard_v2.json`: tiny smoke window had no qualifying trades.
- `tmp/research_runs/smoke_risk_off_london_relief.json`: tiny smoke window had no qualifying trades.
- `tmp/research_runs/next_research_batch_universe12_20260427.json`: 13-candidate bounded pass. `ai_score_v2_base_score7` was strong but sparse: `trades=49`, `net_avg_r=0.3198`, `pf=1.9884`, failed only `executed_trades<80`. The risk-off London relief variants were negative and should not be broadened without redesign.
- `tmp/research_runs/ai_scorecard_v2_top2_universe30_20260427.json`: focused full walk-forward on the two strongest scorecard variants over the strict 30-symbol universe. `ai_score_v2_base_score7` passed the harness promotion gates with `trades=82`, `net_total_r=13.8474`, `net_avg_r=0.1689`, `pf=1.384`, `max_drawdown_r=6.0054`, `holdout_net_total_r=8.3462`, `holdout_avg_r=0.2087`, and `4 of 5` positive folds.
- `tmp/research_runs/ai_scorecard_v2_confirm_universe30_20260428.json`: focused confirmation run for only `ai_score_v2_base_score7`. It reproduced the pass with `trades=83`, `net_total_r=13.838`, `net_avg_r=0.1667`, `pf=1.3837`, `max_drawdown_r=6.0054`, `holdout_net_total_r=8.1486`, `holdout_avg_r=0.2037`, and `4 of 5` positive folds.

Approval update: on April 28, 2026, the user approved `ai_score_v2_base_score7` for gated paper testing, then approved guarded automatic paper entries. The live `SignalAssistant` now treats it as the active paper strategy and can prefill manual paper orders only when the technical reclaim setup, active session, score >= 7, stop-distance, fee-drag, fresh Binance USD-M funding/positioning data, and news blackout gates pass. The auto-paper worker uses the same gate with one global open slot, daily caps, idempotency by `strategy + symbol + signal_close_time`, and local SQLite paper fills only. This is still paper-only and does not enable live funds.

Next scorecard-ablation command:

```powershell
python scripts\research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 4 --json-out tmp\research_runs\ai_scorecard_v2_ablation_latest.json
```

The `ai_scorecard_v2_ablation` family contains a score-7 control plus one-component-disabled variants for session, fee drag, volume, ATR expansion, BTC return, relative strength, basket breadth, funding, taker pressure, OI change, global bias, and top-trader position. It is intended to identify which scorecard components are carrying the edge while paper trading continues under the already-approved control.

## Predictive Meta-Model

Use `scripts/predictive_meta_model.py` only as research diagnostics. It trains a small ridge-regression meta-model over entry-time features from `derivatives_metrics_profile_*.json` and reports blocked and chronological walk-forward filtering results:

```powershell
python scripts/predictive_meta_model.py --profile tmp/research_runs/derivatives_metrics_profile_20260427.json
```

The model is not an entry engine and is not eligible for paper trading by itself. If it finds a stable signal, convert that signal into a bounded candidate family and run the normal promotion gates.

For a larger training surface, first build a multi-candidate event dataset:

```powershell
python scripts/event_dataset.py --json-out tmp/research_runs/event_dataset_latest.json
python scripts/predictive_meta_model.py --profile tmp/research_runs/event_dataset_latest.json
```

This dataset includes multiple setup variants across chronological segments and is for model research only, not promotion.
