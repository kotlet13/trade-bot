# AGENTS.md

## Project Purpose

This repository is a crypto trade-bot research and paper-trading project. The current goal is to paper-test the first approved gated strategy while continuing to search for more robust out-of-sample improvements.

The project is not approved for live trading. Do not add live-funds execution or real exchange order placement without explicit user approval and a separate safety review.

## Current Status

- Mode: approved gated paper testing plus ongoing research.
- Live funds: disabled / out of scope.
- Paper trading: approved for primary `ai_score_v2_base_score7` and secondary `ai_score_v2_ablate_oi`; auto-paper is enabled in Compose for local paper ledger entries only, with the documented guardrails.
- Latest completed focused full walk-forward run: `tmp/research_runs/ai_scorecard_v2_ablate_oi_confirm_universe30_20260428.json`.
- Latest focused full run result: `ai_score_v2_ablate_oi` confirmed its harness promotion-gate pass after the full ablation run.
- Runtime status: `ai_score_v2_base_score7` and `ai_score_v2_ablate_oi` are wired into live `SignalAssistant` as gated paper strategies. Auto-paper uses one global slot, idempotency by `strategy + symbol + signal_close_time`, duplicate same-symbol/same-signal conflict blocking across strategies, daily caps, DB-backed local pause/resume, and local SQLite paper fills only.
- Previous best non-passing candidate: `v2_reclaim_overlap_only`, from `tmp/research_runs/research_run_20260426_150229.json`.
- Bot service may be running on `http://localhost:8081`; verify with `/health`.

## Core Rules

- Do not force trades.
- Do not paper trade unless a candidate passes promotion gates and is explicitly approved.
- Do not add or change a `SignalAssistant` paper strategy only because a candidate looks interesting in a small run.
- Do not commit runtime state, caches, compiled artifacts, or local databases.
- Preserve user changes. Never revert unrelated dirty worktree changes without explicit request.

## Promotion Gates

A strategy can be promoted to gated paper trading only if all are true:

- At least `80` executed validation + holdout trades across the basket.
- Aggregate out-of-sample `net_avg_r >= +0.10R`.
- Aggregate out-of-sample `profit_factor >= 1.25`.
- Holdout `net_total_r > 0` and `holdout_avg_r >= +0.05R`.
- At least `4 of 5` research folds are net positive.
- `max_drawdown_r <= 10R`.
- No single symbol contributes more than `40%` of total net R.
- No single trade contributes more than `25%` of total net R.
- Fees use `10 bps` unless explicitly changed.

If no strategy passes, the correct action is to stay flat and document the failed hypothesis.

## Important Commands

Run checks:

```powershell
python -m py_compile scripts\strategy_study.py scripts\research_harness.py scripts\event_dataset.py scripts\predictive_meta_model.py scripts\candidate_diagnostics.py scripts\daily_paper_diagnostics.py scripts\daily_paper_diagnostics_service.py scripts\forward_paper_report.py scripts\paper_campaign_log.py scripts\strategy_forward_compare.py scripts\backup_paper_db.py scripts\runtime_harness_parity.py scripts\runtime_telemetry_report.py scripts\market_memory_dataset.py
python scripts\test_research_harness.py
python scripts\test_predictive_meta_model.py
python scripts\test_forward_paper_report.py
python scripts\test_paper_campaign_log.py
python scripts\test_strategy_forward_compare.py
python scripts\test_backup_paper_db.py
python scripts\test_daily_paper_diagnostics.py
python scripts\test_runtime_harness_parity.py
python scripts\test_runtime_telemetry_report.py
python scripts\test_market_memory_dataset.py
python scripts\test_event_dataset.py
python scripts\test_derivatives_data.py
python scripts\test_backfill_metrics.py
cargo check
```

Daily read-only diagnostics:

```powershell
python scripts\daily_paper_diagnostics.py
python scripts\paper_campaign_log.py --note "daily check"
```

Compare active paper bots:

```powershell
python scripts\strategy_forward_compare.py --markdown-out tmp\strategy_forward_compare_latest.md --json-out tmp\strategy_forward_compare_latest.json
```

Backup local paper DB:

```powershell
python scripts\backup_paper_db.py --keep-last 10
```

Run fast smoke research:

```powershell
python scripts\research_harness.py --smoke --workers 2 --json-out tmp\research_runs\smoke_research_harness.json
```

Run full clean research:

```powershell
python scripts\research_harness.py --trigger-limit 12000 --universe-limit 20 --workers 4
```

Check local app:

```powershell
Invoke-RestMethod -Uri http://localhost:8081/health
```

Check Docker:

```powershell
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
```

## Research Harness Notes

Main harness:

- `scripts/research_harness.py`
- Uses strict Binance USDT spot universe by default.
- Excludes non-standard symbols, stable/fiat bases, leveraged tokens, meme/event-driven bases, and non-mature assets.
- Supports `--workers` for parallel candidate evaluation.
- Writes full artifacts to `tmp/research_runs/`.
- Appends summaries to `tmp/strategy_test_log.md` unless `--no-log` is used.

Main strategy study helper:

- `scripts/strategy_study.py`

Test fixture:

- `scripts/test_research_harness.py`

## Logs And Artifacts

Keep:

- `tmp/strategy_test_log.md` as the campaign journal.
- `docs/research-campaign.md` as the research workflow documentation.

Do not commit by default:

- `tmp/research_cache/`
- `tmp/research_runs/`
- `tmp/pylibs/`
- `tmp/pdfs/`
- `tmp/strategy_study_*.json`
- `scripts/__pycache__/`
- `*.pyc`
- `data/*.db`
- `target/`

## Suggested Next Work

Next research step:

- Keep paper-testing `ai_score_v2_base_score7` and `ai_score_v2_ablate_oi` in guarded mode and journal every accepted/rejected signal.
- Use `GET /api/auto-paper/status` and the dashboard status panel to monitor enabled/paused state, open slots, daily entries, kill switch state, and latest decisions.
- Use `POST /api/auto-paper/pause` / `resume` only as local paper controls for new entries; never treat them as live execution controls.
- Add forward-paper diagnostics comparing runtime scorecard decisions against the harness assumptions.
- Run parity for both runtime strategies and monitor whether the OI-ablation secondary bot improves forward paper quality.
- Use `regime_abstention_filters`, `runtime_exit_parity`, and `relative_strength_refinement` as harness-only research families; do not wire them into runtime without normal promotion gates and explicit approval.
- Broaden event-level predictive modeling only as research diagnostics; do not promote a model unless it passes the normal gates.
- Continue bounded candidate batches around derivatives data freshness, slippage/fill realism, session sensitivity, and scorecard ablations.
