# Research Handoff - 2026-04-28

## Current Runtime State

- Active gated paper strategy: `ai_score_v2_base_score7`.
- Paper mode: guarded automatic paper trading is enabled through the local SQLite paper ledger only.
- Live funds: disabled and out of scope.
- Auto-paper guardrails remain: one global slot, no BTC entries, max 3 auto entries per UTC day, 2% daily realized-loss kill switch, idempotency by `strategy_version + symbol + signal_close_time`, and attached stop-loss / TP1.
- Runtime strategy replacement still requires a full promotion-gate pass plus explicit user approval.

## Completed In This Batch

- Wired the approved `ai_score_v2_base_score7` strategy into `SignalAssistant`.
- Added guarded auto-paper entry handling with local paper fills only.
- Added `docs/active-strategy.md` as the canonical marker for the active strategy.
- Added forward paper analytics in `scripts/forward_paper_report.py`.
- Added runtime-vs-harness parity checks in `scripts/runtime_harness_parity.py`.
- Added the research-only `ai_scorecard_v2_ablation` candidate family.
- Added ablation support to `ai_scorecard_v2` through `ablate_ai_components`.
- Added tests for ablation candidate availability and score-gate behavior.

## Last Known Research State

- Completed confirmation artifact: `tmp/research_runs/ai_scorecard_v2_confirm_universe30_20260428.json`.
- Confirmed passing strategy: `ai_score_v2_base_score7`.
- Completed ablation smoke artifact: `tmp/research_runs/smoke_ai_scorecard_v2_ablation.json`.
- Ablation smoke result: 13 candidates ran, but the small smoke window produced 0 qualifying trades.
- The full ablation command was started after the smoke run but was force-stopped before completion.
- No full ablation artifact exists yet for `tmp/research_runs/ai_scorecard_v2_ablation_universe30_20260428.json`.

## Next Research Step

Run the full scorecard ablation batch:

```powershell
python scripts\research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 4 --json-out tmp\research_runs\ai_scorecard_v2_ablation_universe30_20260428.json
```

If the machine is memory constrained or the run is disruptive, rerun with fewer workers:

```powershell
python scripts\research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\ai_scorecard_v2_ablation_universe30_20260428.json
```

## How To Interpret The Ablation Run

- `ai_score_v2_ablation_control_score7` should roughly match the current approved score-7 strategy.
- If removing a component improves performance, that component may be over-filtering or adding noise.
- If removing a component worsens performance, that component is likely carrying useful edge.
- Any ablation variant must still pass all promotion gates before it can be considered.
- Do not replace `ai_score_v2_base_score7` in runtime unless the new candidate passes gates and receives explicit approval.

## Operational Checks To Keep Running

Forward paper report:

```powershell
python scripts\forward_paper_report.py --markdown-out tmp\forward_paper_report_latest.md --json-out tmp\forward_paper_report_latest.json
```

Runtime/harness parity:

```powershell
python scripts\runtime_harness_parity.py --symbols ETHUSDT,SOLUSDT --markdown-out tmp\runtime_harness_parity_latest.md --json-out tmp\runtime_harness_parity_latest.json
```

Local app health:

```powershell
Invoke-RestMethod -Uri http://localhost:8081/health
```

## Guardrail Reminder

The correct action for non-passing candidates is to stay with the currently approved paper strategy and document the failed hypothesis. No live-funds execution should be added without explicit user approval and a separate safety review.
