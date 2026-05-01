You are working on the `trade-bot` repository. Continue development based on the current project direction: this is a crypto research and paper-trading bot, not a live trading system.

Hard rules:
- Do not add live Binance execution.
- Do not add private API key handling for live funds.
- Do not promote any new strategy into runtime paper trading unless it passes the documented promotion gates and the user explicitly approves it.
- Preserve the paper-only boundary.
- Preserve existing user changes.
- Do not commit runtime state, local DB files, caches, compiled files, or temporary research artifacts unless explicitly asked.
- Read and follow `AGENTS.md` before editing.
- Prefer small, testable changes over large rewrites.

Current project context:
- Active paper strategies are:
  - `ai_score_v2_base_score7`
  - `ai_score_v2_ablate_oi`
- Both must remain guarded paper-only strategies.
- `ai_score_v2_ablate_oi` should stay as the secondary strategy and `ai_score_v2_base_score7` should stay as the control strategy.
- The strongest next research path is relative-strength HTF continuation / refinement.
- The main weakness is not lack of more entry rules; it is regime selection, fill realism, runtime/harness parity, and forward-paper validation.
- Do not keep randomly tightening reclaim rules just to find a backtest pass.

Primary goals:
1. Make paper trading safer by default.
2. Improve forward-paper diagnostics.
3. Enforce runtime/harness parity checks.
4. Improve fill/slippage realism in the research harness.
5. Align runtime paper exits with research exits.
6. Add or improve regime-abstention research.
7. Continue focused research on relative-strength continuation/refinement.
8. Keep all new candidates harness-only until promotion gates pass.

---

## Phase 1: Safer default runtime config

Change `docker-compose.yml` so auto-paper trading is disabled by default:

- Set:
  - `AUTO_PAPER_TRADING: "false"`

Do not remove the feature. The user should still be able to enable it manually by changing the env var.

Update docs where needed:
- `README.md`
- `docs/active-strategy.md`
- `docs/architecture-ops.md`

Make the docs clear:
- Auto-paper exists.
- It is guarded.
- It is local SQLite paper-only.
- It is disabled by default unless explicitly enabled.

Acceptance:
- `docker compose up --build` still works.
- The app still serves normally.
- Auto-paper worker should not start unless `AUTO_PAPER_TRADING=true`.

---

## Phase 2: Improve forward-paper reporting

Improve `scripts/forward_paper_report.py`.

Current report is useful, but expand it so it can answer:

- Which strategy is doing better forward:
  - `ai_score_v2_base_score7`
  - `ai_score_v2_ablate_oi`
- Which symbols are profitable or weak.
- Which sessions perform best:
  - London
  - London/New York overlap
  - New York
  - off-hours
- Which blockers reject most technical-ready setups.
- Whether rejected setups later would have worked, if enough telemetry exists.
- Whether open positions are still valid or have degraded.
- Whether the bot is mostly flat because no signals occur or because gates reject signals.

Add grouped statistics:
- by strategy
- by symbol
- by session bucket
- by day
- by outcome
- by rejection blocker
- by strategy + blocker
- by symbol + blocker

For completed auto trades, include:
- count
- total realized PnL
- total realized R
- average R
- median R
- win rate
- max win R
- max loss R
- simple equity curve in R
- max drawdown in R

For open auto trades, include:
- opened time
- strategy
- symbol
- entry
- current price if available
- stop
- take profit
- unrealized PnL if available
- approximate unrealized R if risk amount is available

Add CLI options:
- `--since-hours`
- `--strategy`
- `--symbol`
- `--json`
- `--markdown-out`
- `--json-out`

Keep backward compatibility with existing options.

Acceptance:
- Existing command still works:

  `python scripts/forward_paper_report.py --markdown-out tmp/forward_paper_report_latest.md --json-out tmp/forward_paper_report_latest.json`

- If there are no trades or no decisions, the script should still render a useful report and not crash.
- Add or update tests if there is already a relevant test pattern.
- Do not require live internet for this report.

---

## Phase 3: Add a daily diagnostics command/script

Create a small script, for example:

- `scripts/daily_paper_diagnostics.py`

It should run or orchestrate these diagnostics:

1. Forward paper report.
2. Runtime telemetry report, if available.
3. Runtime/harness parity for both active strategies.
4. Optional market-memory report, if the DB contains required telemetry.

The script should write outputs under `tmp/`:

- `tmp/forward_paper_report_latest.md`
- `tmp/forward_paper_report_latest.json`
- `tmp/runtime_harness_parity_base_latest.md`
- `tmp/runtime_harness_parity_base_latest.json`
- `tmp/runtime_harness_parity_oi_latest.md`
- `tmp/runtime_harness_parity_oi_latest.json`
- any other already-standard latest report names

It should not place trades.
It should not call `/api/paper/*`.
It should only inspect data and produce reports.

Acceptance:
- If the app is not running, the script should fail gracefully and explain which parity checks could not run.
- If the DB does not exist, the script should fail gracefully.
- If one report fails, the script should continue with the others and summarize failures at the end.

---

## Phase 4: Strengthen runtime/harness parity workflow

Keep `scripts/runtime_harness_parity.py`, but improve reliability if needed.

Requirements:
- It must support both active strategies:
  - `ai_score_v2_base_score7`
  - `ai_score_v2_ablate_oi`
- It should clearly identify:
  - technical stage mismatch
  - AI score mismatch
  - risk-plan mismatch
  - signal close time mismatch
  - missing futures/funding data mismatch
  - news gate mismatch, if runtime includes news but harness does not

Add a clear markdown summary:
- number of symbols checked
- pass count
- warning count
- strategy checked
- rows with mismatches
- exact reason for mismatch

Add/keep commands in docs:

```powershell
python scripts\runtime_harness_parity.py --strategy ai_score_v2_base_score7 --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp\runtime_harness_parity_base_latest.md --json-out tmp\runtime_harness_parity_base_latest.json

python scripts\runtime_harness_parity.py --strategy ai_score_v2_ablate_oi --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp\runtime_harness_parity_oi_latest.md --json-out tmp\runtime_harness_parity_oi_latest.json
````

Acceptance:

* Parity script exits `0` only if there are no warnings.
* It produces useful markdown even when warnings exist.
* It does not mutate paper state.

---

## Phase 5: Improve fill/slippage realism in the research harness

Improve `scripts/research_harness.py` and/or `scripts/strategy_study.py` so research can optionally simulate more realistic fills.

Add configurable slippage settings:

* market entry slippage bps
* stop-loss slippage bps
* take-profit slippage bps or touch-buffer
* optional per-symbol liquidity bucket multiplier
* optional volatility multiplier

Suggested defaults for research-only stricter mode:

* entry market slippage: 2 bps for BTC/ETH, 3 bps for liquid large caps, 5 bps for smaller alts
* stop slippage: 5 bps base, higher during high ATR expansion
* take-profit: require price to clear the TP by a small buffer or apply conservative TP fill slippage
* keep existing 10 bps fee model unless explicitly changed

Add CLI args:

* `--entry-slippage-bps`
* `--stop-slippage-bps`
* `--tp-slippage-bps`
* `--strict-fills`
* `--no-slippage`, defaulting to existing behavior if needed for backward compatibility

Important:

* Do not break existing saved research logic by silently changing defaults.
* Either keep old defaults and add strict mode, or document the change clearly.
* Prefer adding strict mode first.

Acceptance:

* Existing tests still pass.
* Add tests for:

  * slippage reduces net R
  * same-candle stop/TP remains conservative
  * strict TP fill is harder than old TP fill
  * stop slippage worsens stop-loss trades
* Research artifact should include fill/slippage settings in `settings`.

---

## Phase 6: Align runtime paper exit model with research exit model

Audit mismatch between research exits and runtime paper exits.

Research currently models variants like:

* TP1
* move remainder to break-even
* TP2
* timeout

Runtime paper execution appears simpler, with attached stop-loss and take-profit on a position.

Do one of these, in order of preference:

Option A, preferred:
Implement paper-only bracket/partial exits:

* On entry, store:

  * stop_loss
  * take_profit_1
  * take_profit_2
  * remaining quantity
  * whether TP1 has been hit
  * break-even stop after TP1
* When price hits TP1:

  * sell half position
  * mark TP1 hit
  * move stop on remainder to break-even
* When price hits TP2:

  * sell remaining position
* When price hits break-even after TP1:

  * sell remaining position
* Keep all of this paper-only in SQLite.
* Do not call exchange APIs.

Option B:
If Option A is too large, add a harness candidate/execution mode that matches current runtime exactly:

* single full-position stop
* single full-position take-profit
* no partial TP
* no break-even move

Then compare active strategies under runtime-matched exits.

Acceptance:

* Runtime and harness should not claim the same strategy behavior if exits differ.
* Docs must clearly explain which exit model active paper strategies use.
* Add regression tests for partial TP / BE behavior if implemented.

---

## Phase 7: Improve auto-paper idempotency and conflict handling

Current idempotency is by `strategy_version + symbol + signal_close_time`.

Add a global conflict guard so the same symbol/signal does not get duplicated across primary and secondary strategy when both fire at the same time.

Suggested behavior:

* If primary and secondary both pass for same `symbol + signal_close_time`, choose one entry.
* Prefer the strategy with higher AI score.
* If scores tie, prefer `ai_score_v2_ablate_oi` only if explicitly configured, otherwise prefer primary control.
* Log the skipped strategy as `rejected` or `conflict_skipped`, with reason:

  * `duplicate_symbol_signal_conflict`

Add a config option:

* `AUTO_PAPER_ALLOW_MULTI_STRATEGY_SAME_SIGNAL=false`

Default should be false.

Acceptance:

* With one global slot, behavior remains safe.
* If max slots is raised in the future, duplicate same-signal entries are still blocked unless explicitly allowed.
* Forward report should show conflict skips.

---

## Phase 8: Add regime-abstention research candidates

Add a harness-only candidate family, for example:

* `regime_abstention_filters`

Goal:
Improve existing approved strategy candidates by blocking bad regimes, not by adding more aggressive entries.

Test filters around:

* BTC 24h return too negative
* BTC 24h return too positive / overheated
* basket breadth too weak
* basket breadth too euphoric
* funding panic
* OI expansion/collapse extremes
* global account crowding
* top-trader position crowding
* high ATR expansion / volatility shock
* off-hours avoidance
* New York weakness, if supported by data
* macro/news blackout if historical data is available; otherwise keep it diagnostic-only

Candidate examples:

* active scorecard + BTC return band
* active scorecard + breadth band
* active scorecard + funding-not-panic
* active scorecard + global account cap
* active scorecard + top-position cap
* active scorecard + volatility shock block
* active scorecard + London/overlap only
* OI-ablation scorecard + the same abstention filters

Do not wire these into runtime.

Acceptance:

* Candidate family is available through:

  `python scripts/research_harness.py --candidate-family regime_abstention_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp/research_runs/regime_abstention_filters_universe30_latest.json`

* Results must be evaluated by existing promotion gates.

* If no candidate passes, document that no runtime change is warranted.

---

## Phase 9: Continue relative-strength refinement

Continue the documented `relative_strength_refinement` path.

Focus only on the near-miss HTF continuation branch. Do not add a huge unfocused search space.

Research dimensions:

* relative strength threshold:

  * 0.60
  * 0.65
  * 0.70
  * 0.75
* BTC return band:

  * avoid risk-off
  * avoid overheated blowoff
* breadth band:

  * constructive but not euphoric
* taker buy pressure:

  * minimum 1.00
  * 1.10
  * 1.25
* global account cap:

  * 1.20
  * 1.35
  * 1.50
  * 1.80
* top-trader position cap:

  * 1.60
  * 2.00
  * 2.20
* target multiple and max bars:

  * avoid over-optimizing
  * test a small number of sensible combinations
* session:

  * London
  * London/NY overlap
  * active session excluding weak buckets

Acceptance:

* Keep the candidate count bounded.
* Do not promote unless all promotion gates pass.
* If the best candidate is still below 80 trades or below 4/5 positive folds, keep it research-only.
* Update `docs/research-campaign.md` with the result summary.

---

## Phase 10: Add documentation updates

Update docs to reflect the improved workflow.

Files likely needing updates:

* `README.md`
* `AGENTS.md`
* `docs/active-strategy.md`
* `docs/research-campaign.md`
* `docs/architecture-ops.md`

Add a recommended daily workflow:

```powershell
docker compose up --build

python scripts\forward_paper_report.py --markdown-out tmp\forward_paper_report_latest.md --json-out tmp\forward_paper_report_latest.json

python scripts\runtime_harness_parity.py --strategy ai_score_v2_base_score7 --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp\runtime_harness_parity_base_latest.md --json-out tmp\runtime_harness_parity_base_latest.json

python scripts\runtime_harness_parity.py --strategy ai_score_v2_ablate_oi --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp\runtime_harness_parity_oi_latest.md --json-out tmp\runtime_harness_parity_oi_latest.json
```

Add clear guidance:

* Backtests are hypothesis filters, not proof.
* Forward-paper results are the main evidence before testnet.
* No live trading until separate safety review.
* No strategy promotion without promotion gates and explicit user approval.

---

## Phase 11: Testing and validation

Run these checks before finishing:

```powershell
python -m py_compile scripts\strategy_study.py scripts\research_harness.py scripts\derivatives_data.py scripts\derivatives_research.py scripts\backfill_metrics.py scripts\event_dataset.py scripts\predictive_meta_model.py scripts\runtime_harness_parity.py scripts\forward_paper_report.py scripts\test_research_harness.py scripts\test_derivatives_data.py scripts\test_backfill_metrics.py scripts\test_event_dataset.py scripts\test_predictive_meta_model.py

python scripts\test_research_harness.py
python scripts\test_derivatives_data.py
python scripts\test_backfill_metrics.py
python scripts\test_event_dataset.py
python scripts\test_predictive_meta_model.py

cargo check
```

If new scripts are added, include them in py_compile checks.

If any test fails:

* Diagnose the cause.
* Fix the code if the test is valid.
* Only update tests if the old expectation is clearly obsolete and the new behavior is documented.

---

## Final deliverable

When done, provide a concise summary with:

1. Files changed.
2. What was implemented.
3. What was intentionally left research-only.
4. Whether tests/checks passed.
5. Any known limitations.
6. Recommended next command for the user to run.

Do not claim a strategy is profitable.
Do not claim anything is live-ready.
Do not enable live execution.

```
```
