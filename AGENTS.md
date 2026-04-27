# AGENTS.md

## Project Purpose

This repository is a crypto trade-bot research and paper-trading project. The current goal is to find a robust, out-of-sample positive strategy before allowing any paper entries.

The project is not approved for live trading. Do not add live-funds execution or real exchange order placement without explicit user approval and a separate safety review.

## Current Status

- Mode: research-first, gated paper trading only.
- Live funds: disabled / out of scope.
- Paper trading: blocked until a strategy passes promotion gates and is explicitly marked promoted.
- Latest full clean research run: `tmp/research_runs/research_run_20260426_150229.json`.
- Latest full run result: no promoted strategy.
- Best candidate from that run: `v2_reclaim_overlap_only`, but it failed promotion gates.
- Bot service may be running on `http://localhost:8081`; verify with `/health`.

## Core Rules

- Do not force trades.
- Do not paper trade unless a candidate passes promotion gates.
- Do not change live `SignalAssistant` strategy only because a candidate looks interesting in a small run.
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
python -m py_compile scripts\strategy_study.py scripts\research_harness.py scripts\test_research_harness.py
python scripts\test_research_harness.py
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

- Add deeper diagnostics for `v2_reclaim_overlap_only`.
- Break down performance by symbol, session, outcome, stop distance, and fee drag.
- Add focused variants combining overlap session with BTC trend, volume, ATR expansion, and fee-efficiency filters.
- Run a full clean pass after each bounded candidate batch.

Keep paper trading blocked until a full run passes promotion gates.
