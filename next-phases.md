Spodaj imaš nova navodila za Codex. Napisana so v angleščini in upoštevajo, da **guarded auto-paper ostane vklopljen v ozadju**.

````text
You are working on the `trade-bot` repository.

The project is now in an approved guarded forward-paper phase. Auto-paper trading is intentionally enabled in `docker-compose.yml` for local SQLite paper entries only. Do not disable it as part of this work. The goal is to make the background paper test safer, more observable, and more useful for decision-making.

Hard rules:
- Do not add live Binance execution.
- Do not add real exchange order placement.
- Do not add live-funds API key handling.
- Do not add testnet/live execution unless explicitly requested later.
- Do not promote any new strategy into runtime paper trading unless it passes the documented promotion gates and the user explicitly approves it.
- Keep `ai_score_v2_base_score7` as the primary control paper strategy.
- Keep `ai_score_v2_ablate_oi` as the secondary paper strategy.
- Keep `AUTO_PAPER_TRADING=true` in `docker-compose.yml`; this is intentional for the current guarded forward-paper test.
- Do not force trades.
- Do not reset the paper account unless explicitly asked.
- Do not commit local runtime state, DB files, caches, compiled artifacts, or generated research artifacts unless explicitly asked.
- Preserve user changes.
- Read and follow `AGENTS.md` before editing.

Current project state:
- Mode: local guarded paper testing plus ongoing research.
- Auto-paper is enabled in Compose for local SQLite paper ledger entries.
- Execution remains paper-only.
- Active paper strategies:
  - Primary: `ai_score_v2_base_score7`
  - Secondary: `ai_score_v2_ablate_oi`
- Auto-paper guardrails:
  - one global auto slot
  - max 3 auto entries per UTC day
  - 2% daily realized-loss kill switch
  - no BTC entries
  - no duplicate same-strategy same-symbol same-signal entries
  - no duplicate same-symbol same-signal entries across primary/secondary unless explicitly allowed
- Runtime paper exits currently use single full-position attached stop-loss / TP1.
- Research harness contains stricter/slippage-aware and runtime-exit-parity tooling.
- Near-miss research candidates are not promoted:
  - `regime_abs_oi_funding_not_panic_s7` is promising but too sparse and strict-fill sensitive.
  - `rs_refine_htf_position_loose_s5` remains holdout-skewed and fold-unstable.

Main objective for this development pass:
Build a stronger forward-paper operations layer around the already-enabled background paper bot. The bot may keep running, but the system must become easier to monitor, pause, audit, export, and judge.

---

## Phase 1: Add an auto-paper runtime status surface

Add a read-only API endpoint that exposes the current auto-paper status.

Suggested endpoint:

- `GET /api/auto-paper/status`

It should return:
- whether auto-paper is enabled by config
- max open slots
- current active auto slots
- max daily entries
- current daily entries
- daily realized PnL
- daily realized R if available
- daily loss kill-switch threshold
- whether kill switch is currently blocking new entries
- whether duplicate same-symbol/same-signal blocking is enabled
- current approved strategy list
- open auto positions
- latest auto-paper decision timestamp
- latest entered decision
- latest rejected decision
- latest conflict-skipped decision
- current UTC day
- generated_at

This endpoint must be read-only.
It must not place, cancel, or reset paper orders.

Also add this status into the existing `/api/dashboard` payload if that is low-risk. If that is too invasive, keep it as a separate endpoint first.

Acceptance:
- `GET /api/auto-paper/status` works when there are no decisions yet.
- It works when there are no open positions.
- It works when the `auto_paper_decisions` table exists but is empty.
- It does not mutate DB state.
- Add docs in `README.md` and `docs/architecture-ops.md`.

---

## Phase 2: Add manual local pause/resume for auto-paper without changing Compose

Because `AUTO_PAPER_TRADING=true` is intentional, add a local pause layer so the user can stop new paper entries without editing Docker Compose.

Implement a persistent DB-backed pause flag.

Suggested table:

```sql
auto_paper_control (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    note TEXT
)
````

Suggested keys:

* `paused`
* `pause_reason`
* `paused_until`

Add endpoints:

* `GET /api/auto-paper/status`

  * include pause state
* `POST /api/auto-paper/pause`

  * payload: `{ "reason": "...", "paused_until": optional timestamp }`
* `POST /api/auto-paper/resume`

  * payload: `{ "reason": "..." }`

Behavior:

* If paused, auto-paper worker must not open new entries.
* Existing paper positions should still be managed by normal local price-trigger exits.
* Pausing must not cancel positions.
* Pausing must not alter research telemetry.
* Resume must only allow new entries again; it must not force trades.

Log pause/resume actions in a table or in `auto_paper_decisions` as operational events if appropriate.

Acceptance:

* Paused auto-paper logs or reports why new entries are blocked.
* Resume restores normal gated paper behavior.
* The pause state survives container restart because it is stored in SQLite.
* Docs clearly state this is paper-only and does not affect live funds.

---

## Phase 3: Improve forward-paper report with campaign-level decision rules

Improve `scripts/forward_paper_report.py` so it produces a clear “campaign status” section.

Add campaign-level status:

* `sample_too_small`
* `healthy_observation`
* `warning_drawdown`
* `warning_parity_missing`
* `warning_strategy_underperforming`
* `pause_recommended`
* `promotion_not_allowed`
* `research_only`

Do not ever say “live ready”.

Add configurable thresholds:

* `--min-observation-trades`, default `30`
* `--min-serious-sample-trades`, default `60`
* `--promotion-like-sample-trades`, default `80`
* `--max-forward-drawdown-r`, default `5.0`
* `--min-forward-avg-r`, default `0.05`
* `--min-forward-profit-factor`, default `1.15`

Add per-strategy campaign summary:

* completed trades
* open trades
* realized R
* average R
* median R
* win rate
* profit factor
* max drawdown R
* worst symbol
* best symbol
* worst session
* best session
* most common blocker
* whether sample is too small

Add a “Recommended action” field:

* `keep_observing`
* `pause_and_review`
* `do_not_promote`
* `insufficient_sample`
* `check_parity`
* `investigate_session_or_symbol_drag`

Important:

* This is an analysis recommendation only.
* It must not pause the bot automatically.
* It must not change strategy settings.

Acceptance:

* Existing command still works:

```powershell
python scripts\forward_paper_report.py --markdown-out tmp\forward_paper_report_latest.md --json-out tmp\forward_paper_report_latest.json
```

* New fields appear in JSON.
* Markdown has a readable “Campaign Status” section.
* No crash when there are zero trades.
* Tests updated.

---

## Phase 4: Add a paper campaign observation log

Create a script:

* `scripts/paper_campaign_log.py`

Purpose:
Append a compact daily observation entry from the latest diagnostics into a durable markdown log.

Default output:

* `tmp/paper_campaign_log.md`

Each entry should include:

* date/time UTC
* auto-paper enabled/paused state
* open auto positions
* completed trades in the period
* total realized R in the period
* per-strategy realized R
* max drawdown R
* parity status summary
* top rejection blocker
* top symbol drag
* top session drag
* recommended action from forward report
* short notes field if provided by CLI

CLI:

* `--forward-json tmp/forward_paper_report_latest.json`
* `--parity-base-json tmp/runtime_harness_parity_base_latest.json`
* `--parity-oi-json tmp/runtime_harness_parity_oi_latest.json`
* `--out tmp/paper_campaign_log.md`
* `--note "..."`

Do not commit `tmp/paper_campaign_log.md` by default unless the user explicitly wants the campaign journal committed. Add it to docs as a local operations log.

Acceptance:

* Works even if parity JSON files are missing.
* Works with zero trades.
* Appends instead of overwriting.
* Does not call trading endpoints.
* Does not mutate DB.

---

## Phase 5: Add a daily diagnostics sidecar option, but keep it read-only

The user wants auto-paper to run in the background. Add an optional read-only diagnostics sidecar to Docker Compose, or document how to run it manually if adding the sidecar is too invasive.

Preferred:

* Add a service named `paper-diagnostics`.
* It should run `scripts/daily_paper_diagnostics_service.py`.
* It should run every configurable interval, for example every 6 hours or 24 hours.
* It must be read-only.
* It must not call `/api/paper/*`.
* It may call `/health` and `/api/dashboard` through parity scripts.
* It should write latest reports under `tmp/`.

Environment:

* `PAPER_DIAGNOSTICS_INTERVAL_SECONDS=21600`
* `PAPER_DIAGNOSTICS_SINCE_HOURS=24`
* `PAPER_DIAGNOSTICS_BASE_URL=http://app:3000`
* `PAPER_DIAGNOSTICS_SYMBOLS=ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT`

If Docker networking makes this awkward, document the manual host command instead and skip the sidecar.

Acceptance:

* Main app still starts normally.
* Diagnostics sidecar does not place trades.
* Failure in diagnostics sidecar must not stop the app.
* Reports are written under `tmp/`.

---

## Phase 6: Add UI visibility for auto-paper state

Improve the frontend so the user can see the background bot state without opening logs.

Show:

* auto-paper enabled
* paused/resumed state
* active open slot count
* today’s auto entries
* daily realized PnL/R
* current kill-switch status
* latest decision
* latest rejection reason
* current open auto position, if any
* strategy responsible for open position
* current open position validity if available

Optional UI buttons:

* Pause auto-paper
* Resume auto-paper

Only add pause/resume buttons if the backend endpoints from Phase 2 are implemented.

Acceptance:

* UI does not allow forced trades.
* UI does not add live execution.
* UI clearly labels everything as paper-only.
* UI handles missing status payload gracefully.

---

## Phase 7: Improve auto-paper decision logging

Enhance `auto_paper_decisions` logging so future analysis is better.

For every cycle where a technical READY setup exists, record enough context to explain the decision.

For entered/rejected/conflict_skipped/paused_blocked decisions, store:

* strategy_version
* symbol
* signal_close_time
* technical_stage
* final_stage
* ai_score
* failed checks
* blocker summary
* session bucket
* BTC 24h return if available
* basket breadth if available
* relative strength percentile if available
* funding bps if available
* taker buy/sell ratio if available
* global account long/short ratio if available
* top-trader position ratio if available
* OI 24h change if available
* news gate status if available
* duplicate/conflict reason if applicable
* risk plan fields if available

If the table schema is already fixed, either:

* add nullable columns via migration, or
* add `context_json TEXT` to avoid too many schema migrations.

Preferred:

* Add `context_json TEXT`.

Acceptance:

* Existing DB upgrades cleanly.
* Existing reports still work with old rows.
* New forward report can use context_json if present.
* No trading behavior changes except better logging.

---

## Phase 8: Add a strategy comparison report for active paper bots

Create or extend a script:

* `scripts/strategy_forward_compare.py`

Purpose:
Compare `ai_score_v2_base_score7` vs `ai_score_v2_ablate_oi` using forward paper decisions and trades.

It should answer:

* Which strategy generated more READY setups?
* Which entered more?
* Which was rejected more?
* Which had better realized R?
* Which had better avg R?
* Which had lower drawdown?
* Did duplicate conflict blocking suppress one strategy more than the other?
* Did OI ablation actually help forward paper quality?
* Are differences statistically meaningful yet, or sample too small?

Output:

* markdown
* JSON

Default command:

```powershell
python scripts\strategy_forward_compare.py --markdown-out tmp\strategy_forward_compare_latest.md --json-out tmp\strategy_forward_compare_latest.json
```

Acceptance:

* No crash with zero trades.
* Clearly says “sample too small” when sample is too small.
* Does not recommend replacing active strategies unless sample is meaningful and documented gates are considered.
* Does not promote any strategy.

---

## Phase 9: Keep research restrained

Do not add a large new strategy search in this pass.

Allowed research-only work:

* `candidate_diagnostics.py` improvements
* strict-fill sensitivity improvements
* analysis of why near-miss candidates fail
* runtime-exit-parity diagnostics
* regime bucket diagnostics

Do not wire new candidates into runtime.

Do not promote:

* `regime_abs_oi_funding_not_panic_s7`
* `rs_refine_htf_position_loose_s5`
* any relative-strength refinement candidate
* any regime-abstention candidate

Instead, add diagnostics that answer:

* Which fold kills the candidate?
* Which session kills it?
* Which symbols carry the holdout?
* How much performance disappears under strict fills?
* Is the candidate dependent on one recent market regime?
* Is there overlap with active approved paper signals?

Acceptance:

* New research output is clearly labeled research-only.
* Docs say no runtime change is warranted unless gates pass and user approves.

---

## Phase 10: Add SQLite backup/export utility

Since auto-paper is now running in the background, add a simple safety utility:

* `scripts/backup_paper_db.py`

Features:

* copy `data/tradebot.db` to `tmp/backups/tradebot_YYYYMMDD_HHMMSS.db`
* optional `--compress`
* optional `--keep-last N`
* optional `--include-reports`
* print backup path
* never delete the active DB
* never reset account

Add docs:

```powershell
python scripts\backup_paper_db.py --keep-last 10
```

Acceptance:

* Works if DB exists.
* Fails gracefully if DB is missing.
* Does not mutate trading state.
* Does not include secrets.

---

## Phase 11: Update documentation

Update:

* `AGENTS.md`
* `README.md`
* `docs/active-strategy.md`
* `docs/architecture-ops.md`
* `docs/research-campaign.md`

Clarify:

* Auto-paper is intentionally enabled in Compose for the approved guarded paper test.
* It remains local SQLite paper-only.
* The user can pause/resume via the new local pause control.
* Daily diagnostics are required while background paper testing is enabled.
* No live trading.
* No strategy promotion without gates and explicit approval.
* Near-miss candidates remain research-only.
* Forward-paper evidence is now the main evidence stream.

Add recommended daily workflow:

```powershell
docker compose up -d --build
python scripts\daily_paper_diagnostics.py
python scripts\paper_campaign_log.py --note "daily check"
```

Add recommended weekly workflow:

```powershell
python scripts\strategy_forward_compare.py --markdown-out tmp\strategy_forward_compare_latest.md --json-out tmp\strategy_forward_compare_latest.json
python scripts\candidate_diagnostics.py --candidate-name regime_abs_oi_funding_not_panic_s7 --candidate-name rs_refine_htf_position_loose_s5 --source-artifact tmp\research_runs\relative_strength_refinement_universe30_20260501.json --universe-limit 30 --json-out tmp\research_runs\candidate_diagnostics_latest.json --markdown-out tmp\research_runs\candidate_diagnostics_latest.md
python scripts\backup_paper_db.py --keep-last 10
```

---

## Phase 12: Tests and checks

Update or add tests for:

* auto-paper status endpoint if practical
* pause/resume persistence
* forward-paper campaign status
* strategy comparison with zero trades
* strategy comparison with small sample
* paper campaign log append behavior
* daily diagnostics health skip behavior
* backup script path generation and keep-last behavior
* session bucket consistency

Run:

```powershell
python -m py_compile scripts\strategy_study.py scripts\research_harness.py scripts\event_dataset.py scripts\predictive_meta_model.py scripts\candidate_diagnostics.py scripts\daily_paper_diagnostics.py scripts\forward_paper_report.py scripts\runtime_harness_parity.py scripts\runtime_telemetry_report.py scripts\market_memory_dataset.py
python scripts\test_research_harness.py
python scripts\test_predictive_meta_model.py
python scripts\test_forward_paper_report.py
python scripts\test_runtime_harness_parity.py
python scripts\test_runtime_telemetry_report.py
python scripts\test_market_memory_dataset.py
python scripts\test_event_dataset.py
python scripts\test_derivatives_data.py
python scripts\test_backfill_metrics.py
cargo check
```

If new scripts are added, include them in the py_compile list and add lightweight tests.

---

## Final response expected from Codex

When finished, summarize:

1. Files changed.
2. What was added.
3. Whether auto-paper remained enabled in Compose.
4. Whether all changes are paper-only.
5. Whether any endpoint can place/cancel/reset orders.
6. Which reports/scripts were added.
7. Tests/checks run and results.
8. Known limitations.
9. Recommended next command for the user.

Do not claim profitability.
Do not claim live readiness.
Do not enable live execution.
Do not promote new strategies.

```

Moj osebni vrstni red za Codex bi bil: najprej **Phase 1 + Phase 2 + Phase 3**, ker ko imaš paper bota stalno vklopljenega, je najpomembnejše, da ga lahko vidiš, pavziraš in objektivno oceniš.
```
