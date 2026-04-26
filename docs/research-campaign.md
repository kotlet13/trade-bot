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
python -m py_compile scripts/strategy_study.py scripts/research_harness.py scripts/test_research_harness.py
python scripts/test_research_harness.py
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
