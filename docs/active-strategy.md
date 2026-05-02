# Active Paper Strategies

Current active gated paper strategies:

- Primary: `ai_score_v2_base_score7`
- Secondary: `ai_score_v2_ablate_oi`
- Status: approved for guarded automatic paper trading
- Approval date: 2026-04-28
- Runtime: `SignalAssistant` and the auto-paper worker
- Execution: local SQLite paper trades only
- Live funds: disabled
- Default runtime config: `docker-compose.yml` sets `AUTO_PAPER_TRADING=true` for the approved guarded local paper test
- Local control: DB-backed pause/resume can block new auto entries without changing Compose

The secondary bot uses the same reclaim setup, score threshold, guardrails, stop/TP handling, and fresh public Binance USD-M data requirements, but ignores the OI-change score component. The focused confirmation artifact is `tmp/research_runs/ai_scorecard_v2_ablate_oi_confirm_universe30_20260428.json`.

Guardrails:

- One global auto-paper slot
- No BTC entries
- No duplicate entry for the same `strategy_version + symbol + signal_close_time`
- No duplicate entry across primary and secondary for the same `symbol + signal_close_time` unless `AUTO_PAPER_ALLOW_MULTI_STRATEGY_SAME_SIGNAL=true`
- Max `3` auto entries per UTC day
- Daily realized-loss kill switch at `2%`
- Entry requires the approved scorecard gate, attached stop-loss, and TP1
- Manual pause blocks new auto entries only; it does not cancel positions, reset the account, or force trades

Runtime paper exits currently use a single full-position attached stop-loss and TP1. The research harness also has `runtime_exit_parity` candidates so this simpler runtime exit model can be compared directly against the older TP1/break-even/TP2 research exit model without changing the active paper strategies.

Status and local control:

```powershell
Invoke-RestMethod -Uri http://localhost:8081/api/auto-paper/status
Invoke-RestMethod -Uri http://localhost:8081/api/auto-paper/pause -Method Post -ContentType "application/json" -Body '{"reason":"manual review"}'
Invoke-RestMethod -Uri http://localhost:8081/api/auto-paper/resume -Method Post -ContentType "application/json" -Body '{"reason":"review complete"}'
```

These endpoints are paper-only. The status endpoint is read-only. Pause/resume only change the local SQLite control flag for future auto entries.

Forward paper analytics:

```powershell
python scripts\forward_paper_report.py --markdown-out tmp\forward_paper_report_latest.md --json-out tmp\forward_paper_report_latest.json
```

The report reads `data/tradebot.db` and summarizes auto-paper entries, rejected technical-ready setups, blockers, exits, realized PnL/R, strategy/symbol/session/day/outcome groupings, open-trade validity, conflict skips, and rejected-setup follow-up when telemetry is available.
It also includes campaign status, per-strategy campaign summaries, and analysis-only recommended actions such as `keep_observing`, `pause_and_review`, `insufficient_sample`, or `check_parity`. It does not pause the bot automatically.

Daily diagnostics:

```powershell
python scripts\daily_paper_diagnostics.py
```

This command is read-only. It writes latest reports under `tmp/`, runs parity for both active strategies, continues after individual report failures, and does not call `/api/paper/*`.

Append local campaign observations:

```powershell
python scripts\paper_campaign_log.py --note "daily check"
```

Compare active paper bots:

```powershell
python scripts\strategy_forward_compare.py --markdown-out tmp\strategy_forward_compare_latest.md --json-out tmp\strategy_forward_compare_latest.json
```

Back up the local paper DB:

```powershell
python scripts\backup_paper_db.py --keep-last 10
```

Runtime telemetry:

- `RUNTIME_TELEMETRY_ENABLED=true` archives public market data into `data/tradebot.db`.
- The archive stores recent ticker snapshots, `1m/15m/1h/4h` candles, USD-M funding, USD-M futures positioning rows, and `SignalAssistant` scorecard evaluations.
- Telemetry is analysis-only. It does not change the active paper strategies, force entries, or enable live exchange execution.

Telemetry report:

```powershell
python scripts\runtime_telemetry_report.py --markdown-out tmp\runtime_telemetry_report_latest.md --json-out tmp\runtime_telemetry_report_latest.json
```

The report reads the runtime telemetry archive and summarizes market breadth, futures data freshness, scorecard stages, failed gates, blocked READY setups, auto-paper decisions, and paper trade outcomes.

News/event diagnostics:

```powershell
python scripts\news_event_collector.py --markdown-out tmp\news_event_collection_latest.md --json-out tmp\news_event_collection_latest.json
python scripts\news_event_impact_dataset.py --markdown-out tmp\news_event_impact_latest.md --json-out tmp\news_event_impact_latest.json
python scripts\market_memory_dataset.py --markdown-out tmp\market_memory_latest.md --json-out tmp\market_memory_latest.json
```

The collector writes classified public RSS events to `telemetry_news_events`; the impact script joins them to archived candles and summarizes forward returns. The market-memory script combines candle, futures, news, signal, and paper-decision context for future harness research. This is research-only and does not change `ai_score_v2_base_score7`, `ai_score_v2_ablate_oi`, auto-paper slots, or live execution boundaries.

Docker Compose also runs the `news-events` sidecar with `restart: unless-stopped` and an optional read-only `paper-diagnostics` sidecar. The diagnostics sidecar runs `scripts\daily_paper_diagnostics_service.py`, writes latest reports under `tmp/`, may call `/health`, `/api/dashboard`, and `/api/auto-paper/status`, and does not call `/api/paper/*`.

Runtime/harness parity:

```powershell
python scripts\runtime_harness_parity.py --strategy ai_score_v2_base_score7 --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp\runtime_harness_parity_base_latest.md --json-out tmp\runtime_harness_parity_base_latest.json
python scripts\runtime_harness_parity.py --strategy ai_score_v2_ablate_oi --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp\runtime_harness_parity_oi_latest.md --json-out tmp\runtime_harness_parity_oi_latest.json
```

The parity report compares the live `SignalAssistant` technical stage, AI score, risk-plan availability, signal close time, funding/futures data availability, and live-only news-gate effects against an independent Python evaluation using the selected promoted research harness candidate. It exits `0` only when there are no warnings.

Scorecard ablation research:

```powershell
python scripts\research_harness.py --smoke --candidate-family ai_scorecard_v2_ablation --max-candidates 99 --workers 2 --json-out tmp\research_runs\smoke_ai_scorecard_v2_ablation.json
python scripts\research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 4 --json-out tmp\research_runs\ai_scorecard_v2_ablation_latest.json
```

This family keeps `ai_score_v2_base_score7` as a control and then removes one scorecard component at a time to measure which filters add value. `ai_score_v2_ablate_oi` passed the documented gates and was added as the secondary paper bot.

Do not add live execution or replace the guarded paper-only boundary without explicit user approval and a separate safety review.
