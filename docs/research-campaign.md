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

A full scorecard ablation run completed in `tmp/research_runs/ai_scorecard_v2_ablation_universe30_20260428.json`. The only gate-passing ablation was `ai_score_v2_ablate_oi`: `86` OOS trades, `17.739R` net, `0.2063R` average, `pf=1.4703`, `max_drawdown=6.0666R`, holdout `7.9801R`, holdout average `0.1773R`, and `4/5` positive folds. The score-7 control remained strong but failed trade count with `77` trades, so the OI component is likely over-filtering or adding noise in this run. This is not a runtime promotion; keep `ai_score_v2_base_score7` active until `ai_score_v2_ablate_oi` is confirmed in a focused run and explicitly approved.

Next focused confirmation command:

```powershell
python scripts\research_harness.py --candidate-name ai_score_v2_ablate_oi --trigger-limit 12000 --universe-limit 30 --workers 1 --json-out tmp\research_runs\ai_scorecard_v2_ablate_oi_confirm_universe30_20260428.json
```

Focused confirmation completed in `tmp/research_runs/ai_scorecard_v2_ablate_oi_confirm_universe30_20260428.json` and reproduced the pass exactly: `86` OOS trades, `17.739R` net, `0.2063R` average, `pf=1.4703`, `max_drawdown=6.0666R`, holdout `7.9801R`, holdout average `0.1773R`, `4/5` positive folds, symbol concentration `15.36%`, and single-trade concentration `2.64%`. Treat `ai_score_v2_ablate_oi` as a confirmed research promotion-gate pass, but do not replace the active runtime strategy without explicit user approval.

Runtime update: `ai_score_v2_ablate_oi` is now wired as a secondary guarded paper bot. It shares the same local SQLite paper executor, one global slot, daily caps, loss kill switch, stop/TP attachment, news blackout, and public Binance data freshness requirements as the primary bot. It only differs by ignoring the OI-change score component. This remains paper-only.

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

Latest diagnostic: `tmp/research_runs/event_dataset_latest.json` and `tmp/research_runs/predictive_meta_model_event_dataset_latest.json` completed on April 29, 2026. The unfiltered event surface was flat/negative (`524` trades, `-0.7055R`, `pf=0.9972`, `max_drawdown=46.6536R`). The model filter improved but did not reach promotion-quality statistics (`blocked_cv_keep_0.25`: `136` trades, `10.6911R`, `0.0786R`, `pf=1.1694`, `max_drawdown=14.0524R`). Simple diagnostic rules were more promising: `rule_global_account_lte_1.20` produced `109` trades, `27.3078R`, `0.2505R`, `pf=1.6025`, and `max_drawdown=8.7569R`, while `rule_funding_not_panic_and_taker_buy` produced `242` trades, `47.4988R`, `0.1963R`, `pf=1.4896`, and `max_drawdown=14.4312R`. These are diagnostics only; the next step is to convert them into proper harness candidates and rerun the normal promotion gates before any runtime or paper-trading change.

That conversion is implemented as the `event_rule_filters` harness family. It keeps the active paper setup unchanged and tests the diagnostic filters as normal strategy candidates: global-account bias <= `1.20`, taker-buy pressure >= `1.25`, funding-not-panic, their combinations, session dampeners, and the base/moderate/no-correlation v2 reclaim source variants surfaced by the event dataset.

```powershell
python scripts\research_harness.py --candidate-family event_rule_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\event_rule_filters_universe30_latest.json
```

Full result: `tmp/research_runs/event_rule_filters_universe30_20260429.json` completed with `14` candidates and `0` promotion passes. The best-quality candidate was `event_rule_v2_base_global_lte120` (`31` trades, `15.4676R`, `0.499R`, `pf=2.7134`, `max_drawdown=2.3784R`, holdout `9.2679R`), but it failed trade count, fold stability, and symbol concentration. The broadest near miss was `event_rule_v2_base_funding_taker` (`76` trades, `9.2051R`, `0.1211R`, `pf=1.3122`, `max_drawdown=4.0306R`, `4/5` positive folds), but holdout was slightly negative and trade count remained below `80`. Conclusion: the diagnostic filters improve quality, especially global-account bias <= `1.20`, but they are not standalone promotable strategies and should not change the paper setup.

Next test: integrate the global-account lead back into the scorecard instead of treating it as a standalone rule. The `ai_scorecard_v2_global_sweep` family varies score threshold (`6`/`7`), global account ratio caps (`1.20`, `1.35`, `1.50`), OI ablation, and top-trader-position cap (`1.60`) around the already passing scorecard strategies. This checks whether global-bias filtering can improve robustness without collapsing trade count.

```powershell
python scripts\research_harness.py --candidate-family ai_scorecard_v2_global_sweep --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\ai_scorecard_v2_global_sweep_universe30_20260429.json
```

Full result: `tmp/research_runs/ai_scorecard_v2_global_sweep_universe30_20260429.json` completed with `14` candidates and `0` promotion passes. All candidates had positive holdout and strong aggregate quality, but every variant failed the trade-count gate and fold-stability gate. The top candidate was `ai_score_global_oi_s7_g150_toppos160` with `26` OOS trades, `20.1227R` net, `0.7739R` average, `pf=6.5461`, `max_drawdown=1.3108R`, holdout `8.5304R`, and `3/5` positive folds. The broader best score-6 branch, `ai_score_global_oi_s6_g150`, still reached only `39` trades with `3/5` positive folds. Conclusion: global-bias and top-position caps sharply improve quality but collapse coverage too far to promote. No runtime or paper-bot change is warranted.

## Runtime Telemetry Archive

Implemented on April 29, 2026 to make future analysis less dependent on ad hoc `tmp/` caches. The Rust runtime now creates SQLite archive tables for ticker snapshots, recent `1m/15m/1h/4h` candles, USD-M funding rows, USD-M futures metric rows, and `SignalAssistant` scorecard evaluations. The worker is low-frequency by default (`RUNTIME_TELEMETRY_INTERVAL_SECONDS=900`) and uses upserts so repeated cycles refresh recent rows instead of duplicating them.

This is infrastructure only. It does not change `ai_score_v2_base_score7` or `ai_score_v2_ablate_oi`, does not promote research candidates, and does not add live exchange execution.

## Public News/Event Diagnostics

Implemented on April 29, 2026 as a bounded first step toward news-aware strategy research. `scripts/news_event_collector.py` fetches public RSS feeds, classifies events with a deterministic schema, and upserts them into `telemetry_news_events`. `scripts/news_event_impact_dataset.py` joins those classified events to archived telemetry candles and reports forward returns by event type, sentiment, and symbol.

```powershell
python scripts\news_event_collector.py --markdown-out tmp\news_event_collection_latest.md --json-out tmp\news_event_collection_latest.json
python scripts\news_event_impact_dataset.py --markdown-out tmp\news_event_impact_latest.md --json-out tmp\news_event_impact_latest.json
```

First live diagnostic collected `145` events from CoinDesk, Cointelegraph, Decrypt, Fed, and SEC feeds. The impact pass produced `211` event-symbol rows. The only positive 60-minute bucket in that small sample was `macro_policy` (`16` samples, `+0.198%` average, `68.75%` positive). Generic, regulatory, security, and fund-flow buckets were weak or negative. Treat this as data plumbing and hypothesis generation only; it is not a promotion candidate and does not change the active paper setup.

The `news-events` Docker Compose sidecar now runs `scripts/news_event_service.py` every `900` seconds with `restart: unless-stopped`. Each cycle refreshes the public RSS event archive, the event-impact dataset, the market-memory dataset, and the runtime telemetry report. It only writes `telemetry_news_events` and ignored `tmp/*latest.*` report artifacts; it does not call paper-trading endpoints.

## Next Research Layer

The market-memory dataset is implemented in `scripts/market_memory_dataset.py`:

```powershell
python scripts\market_memory_dataset.py --markdown-out tmp\market_memory_latest.md --json-out tmp\market_memory_latest.json
```

It creates per-symbol `15m` rows from runtime telemetry with BTC cycle/halving phase, session/day/month, BTC regime, futures bias, market-wide and symbol-specific news proximity, signal context, paper-decision context, and forward returns. This is still diagnostic only.

The intended sequence after durable telemetry collection is:

1. Use market-memory diagnostics to identify robust regimes and symbol-specific behavior.
2. Convert the strongest diagnostics into harness-only higher-coverage candidates: broader reclaim variants, macro-policy filters, news-shock-then-reclaim entries, cycle-aware symbol variants, and lower score thresholds only with stricter regime filters.
3. Keep every new candidate out of paper trading until it passes the documented promotion gates and the user explicitly approves promotion.

That first conversion is implemented as the `market_memory_filters` harness family. It keeps the active paper setup unchanged and tests bounded variants around BTC 24h neutral regimes, London/New York session memory, basket breadth between `30%` and `70%`, derivatives global-account bias, funding-not-panic plus taker pressure, and scorecard/OI-ablation branches with score thresholds from `5` to `7`.

```powershell
python scripts\research_harness.py --smoke --candidate-family market_memory_filters --workers 2 --json-out tmp\research_runs\smoke_market_memory_filters.json
python scripts\research_harness.py --candidate-family market_memory_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\market_memory_filters_universe30_latest.json
```
