# Active Paper Strategy

Current active gated paper strategy:

- Name: `ai_score_v2_base_score7`
- Status: approved for guarded automatic paper trading
- Approval date: 2026-04-28
- Runtime: `SignalAssistant` and the auto-paper worker
- Execution: local SQLite paper trades only
- Live funds: disabled

Guardrails:

- One global auto-paper slot
- No BTC entries
- No duplicate entry for the same `strategy_version + symbol + signal_close_time`
- Max `3` auto entries per UTC day
- Daily realized-loss kill switch at `2%`
- Entry requires the approved scorecard gate, attached stop-loss, and TP1

Forward paper analytics:

```powershell
python scripts\forward_paper_report.py --markdown-out tmp\forward_paper_report_latest.md --json-out tmp\forward_paper_report_latest.json
```

The report reads `data/tradebot.db` and summarizes auto-paper entries, rejected technical-ready setups, blockers, exits, realized PnL, and realized R.

Runtime/harness parity:

```powershell
python scripts\runtime_harness_parity.py --symbols ETHUSDT,SOLUSDT --markdown-out tmp\runtime_harness_parity_latest.md --json-out tmp\runtime_harness_parity_latest.json
```

The parity report compares the live `SignalAssistant` technical stage, AI score, and paper-risk-plan availability against an independent Python evaluation using the promoted research harness candidate.

Scorecard ablation research:

```powershell
python scripts\research_harness.py --smoke --candidate-family ai_scorecard_v2_ablation --max-candidates 99 --workers 2 --json-out tmp\research_runs\smoke_ai_scorecard_v2_ablation.json
python scripts\research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 4 --json-out tmp\research_runs\ai_scorecard_v2_ablation_latest.json
```

This family keeps `ai_score_v2_base_score7` as a control and then removes one scorecard component at a time to measure which filters add value. It is research-only unless a new variant passes promotion gates and receives explicit approval.

Do not replace this active strategy unless a new candidate passes the documented promotion gates and receives explicit user approval.
