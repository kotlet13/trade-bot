# AGENTS.md

## Project Purpose

This repository is a crypto trade-bot research and paper-trading project. The current goal is to paper-test the first approved gated strategy while continuing to search for more robust out-of-sample improvements.

The project is not approved for live trading. Do not add live-funds execution or real exchange order placement without explicit user approval and a separate safety review.

## Current Status

- Mode: approved gated paper testing plus ongoing research.
- Live funds: disabled / out of scope.
- Paper trading: enabled for `ai_score_v2_base_score7`; auto-paper can be enabled only for local paper ledger entries with the documented guardrails.
- Latest completed focused full walk-forward run: `tmp/research_runs/ai_scorecard_v2_confirm_universe30_20260428.json`.
- Latest focused full run result: `ai_score_v2_base_score7` confirmed its harness promotion-gate pass.
- Runtime status: `ai_score_v2_base_score7` is wired into live `SignalAssistant` as the active gated paper strategy. Auto-paper uses one global slot, idempotency by `strategy + symbol + signal_close_time`, daily caps, and local SQLite paper fills only.
- Previous best non-passing candidate: `v2_reclaim_overlap_only`, from `tmp/research_runs/research_run_20260426_150229.json`.
- Bot service may be running on `http://localhost:8081`; verify with `/health`.

## Core Rules

- Do not force trades.
- Do not paper trade unless a candidate passes promotion gates and is explicitly approved.
- Do not change the active `SignalAssistant` strategy only because a candidate looks interesting in a small run.
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
python -m py_compile scripts\strategy_study.py scripts\research_harness.py scripts\event_dataset.py scripts\predictive_meta_model.py scripts\test_research_harness.py scripts\test_predictive_meta_model.py
python scripts\test_research_harness.py
python scripts\test_predictive_meta_model.py
cargo check
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

## Current Private Repo

Private GitHub repo:

- `kotlet13/trade-bot`
- URL: `https://github.com/kotlet13/trade-bot`

The pushed private repo was created from a clean export, not the old local git history, because the old history had tracked runtime/cache/dependency files.

## Suggested Next Work

Next research step:

- Keep paper-testing `ai_score_v2_base_score7` in manual gated mode and journal every accepted/rejected signal.
- Add forward-paper diagnostics comparing runtime scorecard decisions against the harness assumptions.
- Run the `ai_scorecard_v2_ablation` family to measure which `ai_score_v2_base_score7` score components carry the edge.
- Broaden event-level predictive modeling only as research diagnostics; do not promote a model unless it passes the normal gates.
- Continue bounded candidate batches around derivatives data freshness, slippage/fill realism, session sensitivity, and scorecard ablations.
