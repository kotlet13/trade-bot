# Strategy Test Log

## Naming

- `Txxx` = unique test id for this strategy-testing session
- `Status` values: `done`, `in_progress`, `planned`

## Entries

### T001

- Timestamp: `2026-04-22 21:54-21:59 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper execution / UI regression`
- Goal: Verify and then fix the `Prefill trade -> Submit paper order` flow.
- Inputs:
  - Browser E2E on `http://localhost:8081/`
  - Symbol focus: `ETHUSDT`
- Procedure:
  - Reproduced `Not enough paper cash` after `Prefill trade`.
  - Patched fee-aware market-buy sizing in backend.
  - Rebuilt Docker image and reran the same browser flow.
- Result:
  - Bug reproduced first, then fixed.
  - Final E2E result: `BUY ETHUSDT @ 2396.9200 executed as a paper market trade.`
  - Verified portfolio row and trade log row appeared in UI.
  - Paper account reset after test.
- Notes:
  - Remaining minor browser issue: `favicon.ico` 404 only.

### T002

- Timestamp: `2026-04-22 22:06 Europe/Ljubljana`
- Status: `done`
- Scope: `Current replay baseline`
- Goal: Capture the bot's existing `/api/replay` baseline before any broader tuning.
- Inputs:
  - Endpoint: `/api/replay`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Window: existing in-app replay (`720 x 15m`, `32` forward candles)
- Result:
  - `BTCUSDT`: `ready=1`, `avg_r=0.507`
  - `ETHUSDT`: `ready=2`, `avg_r=1.000`
  - `SOLUSDT`: `ready=3`, `avg_r=0.974`
  - `BNBUSDT`: `ready=14`, `avg_r=-0.033`
- Notes:
  - Baseline suggests frequency concentration and weakness on `BNBUSDT`.

### T003

- Timestamp: `2026-04-22 22:08-22:11 Europe/Ljubljana`
- Status: `done`
- Scope: `Replay parity harness`
- Goal: Validate that the local study harness matches the current Rust replay logic before longer sweeps.
- Inputs:
  - Script: [scripts/strategy_study.py](/C:/Users/novsakanze/github/trade-bot/scripts/strategy_study.py:1)
  - Command: `python scripts/strategy_study.py --trigger-limit 720`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- Result:
  - `baseline` gross totals matched the in-app replay behavior.
  - Additional `net_R` showed that fees compress the baseline from `gross_total_r=4.964` to `net_total_r=0.175`.
- Artifacts:
  - [tmp/strategy_study_720.json](/C:/Users/novsakanze/github/trade-bot/tmp/strategy_study_720.json:1)
- Notes:
  - This established the harness as reliable enough for longer sweeps.

### T004

- Timestamp: `2026-04-22 22:11-22:15 Europe/Ljubljana`
- Status: `done`
- Scope: `Mid-window sweep`
- Goal: Test current strategy and stricter variants over a materially longer window.
- Inputs:
  - Script: [scripts/strategy_study.py](/C:/Users/novsakanze/github/trade-bot/scripts/strategy_study.py:1)
  - Command: `python scripts/strategy_study.py --trigger-limit 4000 --forward-candles 32`
  - Configs:
    - `baseline`
    - `tight_pullback`
    - `strong_trigger`
    - `balanced`
    - `balanced_serial`
- Result:
  - All tested configs were net negative after fees on aggregate.
  - Best aggregate result in this sweep: `strong_trigger`, `net_total_r=-7.733`.
  - `baseline` stayed gross-positive (`gross_total_r=10.109`) but net-negative (`net_total_r=-16.059`), which exposed fee drag and overtrading.
- Artifacts:
  - [tmp/strategy_study_4000.json](/C:/Users/novsakanze/github/trade-bot/tmp/strategy_study_4000.json:1)

### T005

- Timestamp: `2026-04-22 22:15-22:25 Europe/Ljubljana`
- Status: `done`
- Scope: `Longer-window stability sweep`
- Goal: Check whether any candidate holds up over a broader sample.
- Inputs:
  - Script: [scripts/strategy_study.py](/C:/Users/novsakanze/github/trade-bot/scripts/strategy_study.py:1)
  - Command: `python scripts/strategy_study.py --trigger-limit 8000 --forward-candles 32`
  - Same config set as `T004`
- Result:
  - All configs remained net negative.
  - Best aggregate result in this sweep: `balanced_serial`, `net_total_r=-13.504`.
  - `baseline` deteriorated to `net_total_r=-49.859`.
- Artifacts:
  - [tmp/strategy_study_8000.json](/C:/Users/novsakanze/github/trade-bot/tmp/strategy_study_8000.json:1)
- Notes:
  - Current technique is not stable enough yet for confident live-style paper deployment.

### T006

- Timestamp: `2026-04-22 22:26-22:29 Europe/Ljubljana`
- Status: `done`
- Scope: `Timeout sensitivity`
- Goal: Check whether the fixed `32 x 15m` forward horizon is truncating valid trades too early.
- Inputs:
  - Script: [scripts/strategy_study.py](/C:/Users/novsakanze/github/trade-bot/scripts/strategy_study.py:1)
  - Command: `python scripts/strategy_study.py --trigger-limit 4000 --forward-candles 64`
  - Same config set as `T004`
- Result:
  - Extending hold time helped some symbols, especially `ETHUSDT` and `BNBUSDT`.
  - Aggregate outcome still stayed net negative for all configs.
  - Best aggregate result in this sweep: `strong_trigger`, `net_total_r=-6.459`.
- Artifacts:
  - [tmp/strategy_study_4000_f64.json](/C:/Users/novsakanze/github/trade-bot/tmp/strategy_study_4000_f64.json:1)
- Notes:
  - Timeout length matters, but it is not enough on its own to rescue the current edge.

## Next planned items

### T007

- Timestamp: `2026-04-22 22:31 Europe/Ljubljana`
- Status: `done`
- Scope: `Current live-signal scan`
- Goal: Check whether any symbol currently has a `READY` setup worth a slower paper-trade observation.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- Result:
  - `BTCUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - No symbol currently meets a clean `READY` condition.
  - No paper trade was forced from this scan.

### T008

- Status: `planned`
- Scope: `Paper-trade observation`
- Goal: If a valid setup exists, place a paper trade, then revisit after `15+` minutes to inspect fills, stops, TP behavior, and position state.

### T009

- Status: `planned`
- Scope: `Filter expansion`
- Goal: Test one additional automatable filter inspired by the PDF, most likely `session/time filter` or stricter `market structure` gating.

### T010

- Timestamp: `2026-04-22 22:46 Europe/Ljubljana`
- Status: `done`
- Scope: `Heartbeat live-signal scan #1`
- Goal: Re-scan the watchlist and place one observation paper trade only if a clean `READY` signal exists and the account is flat.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000`
- Result:
  - `BTCUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - No symbol reached a clean `READY` condition.
  - No paper trade was opened.

### T011

- Timestamp: `2026-04-22 23:02 Europe/Ljubljana`
- Status: `done`
- Scope: `Heartbeat live-signal scan #2`
- Goal: Re-scan the watchlist and place one observation paper trade only if a clean `READY` signal exists and the account is flat.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000`
- Result:
  - `BTCUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - `ETHUSDT` and `BNBUSDT` showed stronger last-trigger bodies, but still did not qualify as clean `READY` setups.
  - No paper trade was opened.

### T012

- Timestamp: `2026-04-22 23:18 Europe/Ljubljana`
- Status: `done`
- Scope: `Heartbeat live-signal scan #3`
- Goal: Re-scan the watchlist and place one observation paper trade only if a clean `READY` signal exists and the account is flat.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000`
- Result:
  - `BTCUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - `BTCUSDT` still has structure and setup, but the `15m` trigger remains missing.
  - No paper trade was opened.

### T013

- Timestamp: `2026-04-22 23:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Heartbeat live-signal scan #4 + paper-trade entry`
- Goal: Re-scan the watchlist and, if flat, open one observation paper trade only on a clean `READY` setup.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000`
- Scan result:
  - `BTCUSDT`: `stage=ready`, `bias=bullish`, `confidence=95`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Action:
  - Opened one paper long on `BTCUSDT`.
  - Order response: `BUY BTCUSDT @ 78681.0500 executed as a paper market trade. Quantity was reduced from 0.127012 to 0.126968 because the live price moved before execution.`
- Position baseline after entry:
  - `symbol=BTCUSDT`
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `last=78699.9800`
  - `market_value=9992.4135`
  - `unrealized=-7.5865`
  - `cash≈0`
- Notes:
  - `avg_price` is above fill price because fees are included in position cost basis.
  - Next wakeup should monitor whether the position remains open, and whether `SL/TP` or unrealized PnL changed materially.

### T014

- Timestamp: `2026-04-22 23:50 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #1`
- Goal: Check the first observation trade after roughly `15+` minutes and record any material state change.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78779.0000`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=+2.4465`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` fell from `READY` back to `SETUP`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` remain outside clean `READY`.
- Notes:
  - This confirms the current trigger can disappear quickly after entry.
  - No additional paper trade was opened while the observation position remains active.

### T015

- Timestamp: `2026-04-23 00:06 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #2`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether anything material changed.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78777.6800`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=+2.2790`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` remains at `SETUP`, not `READY`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` still do not qualify as clean `READY`.
- Notes:
  - This scan is directionally unchanged from `T014`: the observation trade remains open, slightly positive, and unsupported by a still-active trigger.
  - No new paper trade was opened.

### T016

- Timestamp: `2026-04-23 00:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #3`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether the position is improving, degrading, or closing.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78633.2400`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-16.0604`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` remains at `SETUP`, not `READY`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` still do not qualify as clean `READY`.
- Notes:
  - The observation trade flipped from slightly positive to moderately negative while remaining between stop and take-profit.
  - No new paper trade was opened.

### T017

- Timestamp: `2026-04-23 00:38 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #4`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether downside pressure is increasing or whether the trade has closed.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78530.0000`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-29.1686`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` remains at `SETUP`, not `READY`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` still do not qualify as clean `READY`.
- Notes:
  - Downside drift increased materially compared with `T016`, but the trade still has not hit the configured stop-loss.
  - No new paper trade was opened.

### T018

- Timestamp: `2026-04-23 00:54 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #5`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether the open loss is expanding, stabilizing, or reversing.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78553.8600`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-26.1391`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` remains at `SETUP`, not `READY`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` still do not qualify as clean `READY`.
- Notes:
  - Loss remains meaningful but has eased slightly versus `T017`; the position is still between stop and take-profit.
  - No new paper trade was opened.

### T019

- Timestamp: `2026-04-23 01:10 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #6`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether the open loss is stabilizing or worsening.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78573.4400`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-23.6531`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` remains at `SETUP`, not `READY`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` still do not qualify as clean `READY`.
- Notes:
  - The open loss narrowed slightly again compared with `T018`, but the setup still lacks renewed trigger confirmation.
  - No new paper trade was opened.

### T020

- Timestamp: `2026-04-23 01:26 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #7`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether the position is approaching failure or recovering.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78263.1100`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-63.0552`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` degraded from `SETUP` to `WAIT`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` still do not qualify as clean `READY`.
- Notes:
  - This is the weakest state so far: the open loss expanded materially and price is now much closer to stop-loss than take-profit.
  - No new paper trade was opened.

### T021

- Timestamp: `2026-04-23 01:42 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #8`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether the position is nearing stop-loss or stabilizing.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78228.1600`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-67.4927`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT` remains at `WAIT`.
  - `ETHUSDT`, `SOLUSDT`, `BNBUSDT` also remain outside clean `READY`.
- Notes:
  - This is slightly worse than `T020`; the position remains open but is now very close to stop-loss relative to the original risk budget.
  - No new paper trade was opened.

### T022

- Timestamp: `2026-04-23 01:58 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #9`
- Goal: Re-check the BTCUSDT observation trade after another ~15 minutes and record whether stop-loss is close to being hit.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - Position is still open.
  - `qty=0.126968`
  - `avg_price=78759.7310`
  - `current_price=78189.4400`
  - `stop_loss=78114.5514`
  - `take_profit=79193.1086`
  - `unrealized=-72.4090`
  - `realized=0.0000`
  - Account still has `0` open orders and `1` trade in log.
- Live-signal context:
  - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` are all currently at `WAIT`.
- Notes:
  - This is the weakest state so far; BTCUSDT is now very close to the configured stop-loss.
  - No new paper trade was opened.

### T023

- Timestamp: `2026-04-23 02:14 Europe/Ljubljana`
- Status: `done`
- Scope: `Paper-trade observation #10 / stop-loss resolution`
- Goal: Check whether the BTCUSDT observation trade remained open or resolved, then decide whether a new observation trade should be opened.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Focus position: `BTCUSDT` from `T013`
- Result:
  - The BTCUSDT observation trade is no longer open.
  - Latest closing trade:
    - `symbol=BTCUSDT`
    - `side=SELL`
    - `source=AUTO_STOP_LOSS`
    - `price=77874.9600`
    - `realized_pnl=-122.2257`
    - `note=AUTO_STOP_LOSS: T013 heartbeat observation | BTCUSDT READY scan 2026-04-22 23:34 Europe/Ljubljana`
  - Account state after close:
    - `positions=0`
    - `orders=0`
    - `trades=2`
    - `cash=9877.7743`
    - `realized_pnl=-122.2257`
- Live-signal context:
  - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` are all currently at `WAIT`.
- Notes:
  - The first observation trade finished via automatic stop-loss.
  - No new paper trade was opened because no symbol currently has a clean `READY` setup.

### T024

- Timestamp: `2026-04-23 02:30 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan`
- Goal: Check whether a new clean `READY` opportunity appeared after the first observation trade was stopped out.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat after the stop-loss event.
  - No new paper trade was opened because no symbol currently has a clean `READY` setup.

### T025

- Timestamp: `2026-04-23 02:46 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #2`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - This is weaker than `T024`: all four symbols are currently at `WAIT`.
  - No new paper trade was opened because no symbol currently has a clean `READY` setup.

### T026

- Timestamp: `2026-04-23 03:02 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #3`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - No new paper trade was opened.

### T027

- Timestamp: `2026-04-23 03:18 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #4`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - No new paper trade was opened.

### T028

- Timestamp: `2026-04-23 03:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #5`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - No new paper trade was opened.

### T029

- Timestamp: `2026-04-23 03:50 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #6`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - No new paper trade was opened.

### T030

- Timestamp: `2026-04-23 04:06 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #7`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat.
  - `BTCUSDT` recovered to `SETUP`, but there is still no clean `READY` setup.
  - No new paper trade was opened.

### T031

- Timestamp: `2026-04-23 04:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #8`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat.
  - This scan is weaker than `T030` because `BTCUSDT` fell back from `SETUP` to `WAIT`.
  - No new paper trade was opened.

### T032

- Timestamp: `2026-04-23 04:38 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #9`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - Despite stronger last-trigger body ratios on some symbols, no setup cleared the full trigger gate.
  - No new paper trade was opened.

### T033

- Timestamp: `2026-04-23 04:54 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #10`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - No new paper trade was opened.

### T034

- Timestamp: `2026-04-23 05:10 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #11`
- Goal: Check whether any symbol has recovered into a clean `READY` setup after the stop-loss event.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - This was the eleventh post-stop-loss scan with no actionable re-entry.
  - No new paper trade was opened.

### T035

- Timestamp: `2026-04-23 05:26 Europe/Ljubljana`
- Status: `done`
- Scope: `Post-stop-loss live-signal scan #12`
- Goal: Final check before ending low-value repeated monitoring.
- Inputs:
  - Endpoint: `/api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `2 trades`, `cash=9877.7743`, `realized_pnl=-122.2257`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`
- Notes:
  - The account remains flat and there is still no clean `READY` setup.
  - Repeated scans after the stop-loss are no longer producing new information.
  - Monitoring should be stopped until the strategy or filters materially change.

### T036

- Timestamp: `2026-04-23 16:08 Europe/Ljubljana`
- Status: `done`
- Scope: `Signal filter implementation + live verification`
- Goal: Add `session`, `BTC correlation`, and `public news blackout` gates without requiring signup-based data sources.
- Inputs:
  - Public sources:
    - `https://apps.bea.gov/API/signup/release_dates.json`
    - `https://www.federalreserve.gov/feeds/press_monetary.xml`
    - `https://www.sec.gov/news/pressreleases.rss`
    - `https://www.coindesk.com/arc/outboundfeeds/rss`
  - Commands:
    - `cargo fmt`
    - `cargo check`
    - `docker compose up --build -d`
    - `GET /health`
    - `GET /api/dashboard?symbol=BTCUSDT`
    - `GET /api/dashboard?symbol=ETHUSDT`
    - `GET /api/dashboard?symbol=BNBUSDT`
    - `GET /api/replay?symbol=ETHUSDT`
- Result:
  - Added live `session` gate for new entries in `07:00-22:00 UTC`.
  - Added live/replay `BTC correlation` gate using rolling `15m` return correlation.
  - Added live-only `news blackout` gate with cached public-source checks from `BEA`, `Fed`, `SEC`, and `CoinDesk`.
  - Docker rebuild and runtime health check succeeded.
  - `ETHUSDT` dashboard verification showed:
    - `session filter = pass`
    - `correlation filter = pass`
    - `news filter = pass`
    - `stage = wait` because the technical setup itself was weak
  - `BTCUSDT` dashboard verification showed:
    - `correlation filter = pass` via BTC reference bypass
    - `news filter = fail` on a fresh CoinDesk headline mentioning Bitcoin
    - `risk_plan = null` in output because blocked/non-ready setups do not expose prefill execution
  - `ETHUSDT` replay verification returned the new replay notes for session/correlation and explicitly marked `news blackout` as live-only.
- Notes:
  - The first CoinDesk heuristic was too noisy and incorrectly blocked `ETHUSDT` on an XRP-focused ETF headline; it was tightened before the final verification pass.
  - `evaluate_signal` stayed structurally pure; all new filters were added as post-eval gates in live signal assembly, with replay only adopting the deterministic session/correlation parts.

### T037

- Timestamp: `2026-04-23 16:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Historical sweep (filtered study, 1200 x 15m candles)`
- Goal: Re-run the local strategy study after adding deterministic `session` and `BTC correlation` replay gates.
- Inputs:
  - Command: `python scripts/strategy_study.py --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT --trigger-limit 1200 --forward-candles 32 --json-out tmp/strategy_study_1200_filters.json`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- Result:
  - Best config on this shorter sample was still negative after fees:
    - `strong_trigger`: `11?` no, correction below
    - `strong_trigger` summary on `1200` candles: `5 trades`, `net_total_r=-2.294`, `net_avg_r=-0.459`
  - `baseline` stayed materially negative despite more trades:
    - `30 trades`, `net_total_r=-8.640`, `net_avg_r=-0.288`
  - Filter cuts on the short sample were small but real:
    - `baseline`: `session_filtered_ready=9`, `correlation_filtered_ready=2`
  - Symbol-level standouts:
    - `SOLUSDT baseline`: `2 trades`, `net_R=2.108`
    - `BTCUSDT baseline`: `13 trades`, `net_R=-6.322`
    - `BNBUSDT baseline`: `13 trades`, `net_R=-3.141`
- Notes:
  - This short-window rerun does not show a positive edge yet.
  - The new deterministic gates reduce some technically-ready trades, but not enough to flip the basket positive on this sample.

### T038

- Timestamp: `2026-04-23 16:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Historical sweep (filtered study, 4000 x 15m candles)`
- Goal: Test the filtered strategy on a materially larger sample than the quick 1200-candle pass.
- Inputs:
  - Command: `python scripts/strategy_study.py --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT --trigger-limit 4000 --forward-candles 32 --json-out tmp/strategy_study_4000_filters.json`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- Result:
  - Best configuration on the larger sample was still negative:
    - `strong_trigger`: `11 trades`, `net_total_r=-5.931`, `net_avg_r=-0.539`
  - Other configurations were worse:
    - `baseline`: `65 trades`, `net_total_r=-24.936`, `net_avg_r=-0.384`
    - `tight_pullback`: `15 trades`, `net_total_r=-11.191`, `net_avg_r=-0.746`
    - `balanced`: `14 trades`, `net_total_r=-9.556`, `net_avg_r=-0.683`
    - `balanced_serial`: `11 trades`, `net_total_r=-7.416`, `net_avg_r=-0.674`
  - Filter effect on the larger sample:
    - `baseline`: `session_filtered_ready=40`, `correlation_filtered_ready=15`
    - `strong_trigger`: `session_filtered_ready=11`, `correlation_filtered_ready=1`
  - Symbol-level detail:
    - `BTCUSDT` remained the weakest major contributor across configs
    - `ETHUSDT` and `BNBUSDT` stayed net negative
    - `SOLUSDT baseline` was the only clear positive pocket (`net_R=1.288`)
- Notes:
  - Larger-sample history still argues that the current long-only translation is not robust enough.
  - Session/correlation filters improve selectivity, but they do not create a positive basket on their own.

### T039

- Timestamp: `2026-04-23 16:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign reset + starting scan`
- Goal: Start a clean realtime paper-trade campaign without mixing in the earlier observation-loss account state.
- Inputs:
  - Command: `POST /api/paper/reset`
  - Live scans:
    - `GET /api/dashboard?symbol=BTCUSDT&interval=15m`
    - `GET /api/dashboard?symbol=ETHUSDT&interval=15m`
    - `GET /api/dashboard?symbol=SOLUSDT&interval=15m`
    - `GET /api/dashboard?symbol=BNBUSDT&interval=15m`
    - `GET /api/replay?symbol=BTCUSDT`
    - `GET /api/replay?symbol=ETHUSDT`
    - `GET /api/replay?symbol=SOLUSDT`
    - `GET /api/replay?symbol=BNBUSDT`
- Result:
  - Paper account was reset to a clean state for the new campaign.
  - Starting live scan:
    - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news=false`
    - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news=true`
    - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news=true`
    - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news=true`
  - Starting replay snapshot:
    - `BTCUSDT`: `ready=9`, `setup=57`, `avg_r=-0.280`, `total_r=-2.522`
    - `ETHUSDT`: `ready=0`, `setup=0`, `avg_r=0.000`, `total_r=0.000`
    - `SOLUSDT`: `ready=2`, `setup=25`, `avg_r=1.210`, `total_r=2.421`
    - `BNBUSDT`: `ready=9`, `setup=112`, `avg_r=0.034`, `total_r=0.305`
- Notes:
  - No live `READY` setup was available at campaign start, so no paper trade was forced.
  - `SOLUSDT` remains the only clearly positive symbol in the current built-in replay snapshot and deserves extra attention in the next tuning cycle.

### T040

- Timestamp: `2026-04-23 16:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Historical sweep (filtered study, 8000 x 15m candles)`
- Goal: Stress the current filtered long-only system on a much larger historical sample before leaning on more realtime paper trades.
- Inputs:
  - Command: `python scripts/strategy_study.py --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT --trigger-limit 8000 --forward-candles 32 --json-out tmp/strategy_study_8000_filters.json`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- Result:
  - No tested configuration was positive on the full basket after fees.
  - Best aggregate configuration:
    - `strong_trigger`: `15 trades`, `net_total_r=-8.124`, `net_avg_r=-0.542`
  - Worse aggregate configurations:
    - `baseline`: `102 trades`, `net_total_r=-39.546`, `net_avg_r=-0.388`
    - `tight_pullback`: `23 trades`, `net_total_r=-16.085`, `net_avg_r=-0.699`
    - `balanced`: `20 trades`, `net_total_r=-11.964`, `net_avg_r=-0.598`
    - `balanced_serial`: `15 trades`, `net_total_r=-9.929`, `net_avg_r=-0.662`
  - Filter effect on the largest sample:
    - `baseline`: `session_filtered_ready=57`, `correlation_filtered_ready=25`
    - `strong_trigger`: `session_filtered_ready=14`, `correlation_filtered_ready=6`
  - Symbol-level observations:
    - `BTCUSDT` stayed heavily negative across every config
    - `ETHUSDT` also stayed negative across every config
    - `SOLUSDT` turned negative on the larger sample despite looking promising on shorter windows
    - `BNBUSDT strong_trigger` was the only small positive pocket (`4 trades`, `net_R=0.184`), but far too small to trust on its own
- Notes:
  - The larger sample confirms that current improvements are still more of a noise filter than a true edge generator.
  - The strategy likely needs stronger context rules or materially different trade management, not just more replay runs.

### T041

- Timestamp: `2026-04-23 16:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime monitor automation`
- Goal: Keep the new realtime paper-trade campaign running without manually polling every few minutes.
- Inputs:
  - Automation: `realtime-paper-test`
  - Cadence: `every 15 minutes`
  - Task: scan `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, log every scan, open at most one observation paper trade when a clean `READY` signal appears
- Result:
  - Heartbeat automation was created and attached to this thread.
  - Future wakeups will continue the realtime campaign in the same log file.
- Notes:
  - The automation is constrained to at most one open observation trade at a time.
  - No trade was forced during setup; entry still requires a live `READY` signal.

### T042

- Timestamp: `2026-04-23 16:49 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #1`
- Goal: Check for the first clean live `READY` setup after starting the reset realtime paper-test campaign.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
- Notes:
  - All four symbols remained outside a clean `READY` state, so no paper trade was opened.
  - The paper account remains clean and flat for the new campaign.
  - A fresh CoinDesk headline (`JPMorgan says persistent security flaws curb DeFi's institutional appeal`) triggered the live news blackout across the basket during this scan.
  - No new paper-trade or replay event needed separate action on this wakeup.

### T043

- Timestamp: `2026-04-23 17:05 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #2`
- Goal: Re-check the basket for the first clean live `READY` setup and keep the reset campaign account flat unless a valid signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
- Notes:
  - The paper account remains flat and fully reset.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - The same live `news blackout` regime is still suppressing the basket, with the DeFi-security CoinDesk headline now about 27 minutes old.
  - `ETHUSDT` and `BNBUSDT` showed stronger recent 15m candle bodies than on the previous scan, but that still did not produce a valid entry.

### T044

- Timestamp: `2026-04-23 17:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #3`
- Goal: Check whether the first post-blackout momentum burst produced any clean live `READY` setup worth opening as an observation trade.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`, `15m trigger=strong`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`, `15m trigger=strong`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=false`, `15m trigger=strong`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`, `15m trigger=strong`
- Notes:
  - The paper account remains fully flat.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan was notable because all four symbols showed strong `15m` momentum candles at the same time, which is consistent with a broad market burst rather than a selective setup.
  - The same CoinDesk DeFi-security blackout headline remained active after roughly 43 minutes and continued to block the full basket.

### T045

- Timestamp: `2026-04-23 17:37 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #4`
- Goal: Check whether the earlier broad momentum burst resolved into any clean live `READY` setup once the next 15m candle closed.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - Compared with the previous scan, the broad 15m momentum burst faded; all four trigger readings fell back below valid momentum-close conditions.
  - The same CoinDesk DeFi-security blackout headline remained active after roughly 59 minutes and still blocked the basket.

### T046

- Timestamp: `2026-04-23 17:53 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #5`
- Goal: Check whether the basket recovered into any clean live `READY` setup once the blackout aged further.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=false`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - The same CoinDesk DeFi-security blackout headline remained active after roughly 75 minutes and still blocked the basket.
  - This scan was weaker than the previous one: several 15m candles had large bodies but closed near their lows, so momentum-close conditions were not satisfied despite strong range expansion.

### T047

- Timestamp: `2026-04-23 18:10 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #6`
- Goal: Check whether the basket becomes tradable again after the news-blackout window expires.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This was the first scan after the CoinDesk blackout cleared; all four symbols passed the `news filter` again.
  - Despite the cleaner context, none of the four symbols printed a valid `15m` momentum close, so the basket stayed non-actionable.

### T048

- Timestamp: `2026-04-23 18:25 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #7`
- Goal: Check whether the basket produces the first clean `READY` setup now that the news blackout is gone.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`, `15m_trigger=true`
  - `SOLUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `ETHUSDT` printed a valid `15m` momentum close on this scan, but that still was not enough to advance the signal beyond `WAIT`, which points to missing higher-timeframe setup quality rather than a trigger problem.
  - The basket stayed tradeless even with the news filter clear, which reinforces that the current bottleneck is now structural setup quality, not event blackout gating.

### T049

- Timestamp: `2026-04-23 18:41 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #8`
- Goal: Check whether the brief `ETHUSDT` trigger improvement from the previous scan develops into any actionable `READY` setup.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - Compared with the previous scan, `ETHUSDT` lost its valid `15m` trigger and the whole basket weakened again.
  - The current blocker remains setup quality on higher timeframes rather than any event or session filter.

### T050

- Timestamp: `2026-04-23 18:58 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #9`
- Goal: Check whether the basket recovers into a usable live setup after the previous all-clear news regime remained in place.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan remained non-actionable even with the news filter clear, because all four symbols failed the `15m` momentum-close condition again.
  - The current blocker is still setup/trigger quality rather than session or event gating.

### T051

- Timestamp: `2026-04-23 19:14 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #10`
- Goal: Check whether the basket finally recovers into any clean `READY` setup while the news regime remains clear.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - The basket stayed non-actionable even with the `news filter` clear, because all four symbols again failed the `15m` momentum-close requirement.
  - Current blocker remains setup/trigger quality rather than any active blackout or session restriction.

### T052

- Timestamp: `2026-04-23 19:30 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #11`
- Goal: Check whether any clean `READY` setup appears while the basket stays in an all-clear news regime.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - The basket remained non-actionable even with the `news filter` clear, because all four symbols again failed either the `15m` momentum-close requirement or the broader structural context.
  - Current blocker remains setup/trigger quality rather than any active blackout or session restriction.

### T053

- Timestamp: `2026-04-23 19:46 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #12`
- Goal: Check whether any clean `READY` setup appears while the news regime stays clear and the account remains flat.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan was weaker than the previous one because `ETHUSDT` and `SOLUSDT` both degraded to `neutral` 4h bias.
  - The current blocker remains structural setup quality and weak `15m` confirmation, not any active blackout or session restriction.

### T054

- Timestamp: `2026-04-23 20:02 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #13`
- Goal: Check whether any clean `READY` setup appears while the basket stays in an all-clear news regime and the account remains flat.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan was marginally better than the previous one because `ETHUSDT` recovered to bullish 4h bias and `BTCUSDT` moved closer to its 1h support zone, but neither symbol produced a valid `15m` momentum close.
  - The current blocker remains setup/trigger quality rather than any active blackout or session restriction.

### T055

- Timestamp: `2026-04-23 20:18 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #14`
- Goal: Check whether any clean `READY` setup appears while the basket remains in an all-clear news regime and the account stays flat.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan was weaker than the previous one because `BTCUSDT` degraded to an almost zero-body `15m` candle and the whole basket again failed the momentum-close requirement.
  - The current blocker remains setup/trigger quality rather than any active blackout or session restriction.

### T056

- Timestamp: `2026-04-23 20:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #15`
- Goal: Check whether any clean `READY` setup appears while the basket remains in an all-clear news regime and the account stays flat.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`, `15m_trigger=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `BNBUSDT` printed a valid `15m` momentum close on this scan, but that still was not enough to advance the signal beyond `WAIT`, which points to missing higher-timeframe setup quality rather than a trigger problem.
  - The current blocker remains setup/trigger quality rather than any active blackout or session restriction.

### T057

- Timestamp: `2026-04-23 20:50 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #16`
- Goal: Check whether any clean `READY` setup appears while the basket remains in an all-clear news regime and the account stays flat.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan stayed non-actionable even with the `news filter` clear, because all four symbols again failed the `15m` momentum-close requirement.
  - Several symbols printed larger candle bodies, but they still closed too low within the range to qualify as valid long triggers.

### T058

- Timestamp: `2026-04-23 21:06 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #17`
- Goal: Check whether any clean `READY` setup appears while the basket remains in an all-clear news regime and the account stays flat.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `news_filter=true`
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan remained non-actionable even with the `news filter` clear, because the whole basket again failed either the `15m` momentum-close requirement or the broader structural setup test.
  - Current blocker remains setup/trigger quality rather than any active blackout or session restriction.

### T059

- Timestamp: `2026-04-23 21:25 Europe/Ljubljana`
- Status: `done`
- Scope: `Manual PDF-faithful campaign review`
- Goal: Re-check the live basket after returning to the PDF, confirm paper-account cleanliness, compare current live setup quality with recent replay expectancy, and decide whether to open a discretionary observation trade.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Endpoint: `GET /api/replay`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before review: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - Live basket:
    - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
    - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
    - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
    - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - Recent replay context:
    - `BTCUSDT`: `ready_signals=9`, `avg_r=-0.2802`, `total_r=-2.5218`
    - `ETHUSDT`: `ready_signals=0`, `avg_r=0.0000`, `total_r=0.0000`
    - `SOLUSDT`: `ready_signals=2`, `avg_r=1.2103`, `total_r=2.4206`
    - `BNBUSDT`: `ready_signals=9`, `avg_r=0.0338`, `total_r=0.3045`
- Decision:
  - No paper trade opened.
- Notes:
  - This review was intentionally stricter after re-reading the PDF: trend, context, timing, and filter alignment all matter, not just a strong `15m` candle.
  - `ETHUSDT` and `BNBUSDT` were the closest live candidates because they had valid `15m` momentum closes, but both still failed the `1h setup` requirement by trading below their support zones.
  - `SOLUSDT` remains the strongest recent replay symbol on the short in-app window, but the live `4h bias` is still neutral, so it did not justify a discretionary long.
  - Current evidence still supports staying flat until a genuinely clean `READY` setup appears.

### T060

- Timestamp: `2026-04-23 21:41 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #18`
- Goal: Inspect the live basket after the PDF-faithful manual review, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan was weaker than `T059`: `ETHUSDT` and `BNBUSDT` both lost the valid `15m` trigger they had earlier, and the basket now fails both the `1h setup` and `15m trigger` layers almost across the board.
  - Current blocker remains setup/trigger quality rather than any active blackout, session restriction, or account-state issue.

### T061

- Timestamp: `2026-04-23 21:57 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #19`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan improved slightly on raw trigger quality: `ETHUSDT` printed a strong `15m` momentum close, and `SOLUSDT` did the same, but both still failed the broader setup context.
  - `ETHUSDT` remains the nearest long candidate at the moment, yet it is still trading below the `1h` support zone, which keeps the setup invalid under the current rules.

### T062

- Timestamp: `2026-04-23 22:13 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #20`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan was materially weaker than `T061`: `BTCUSDT` lost bullish `4h` bias, `ETHUSDT` fell back to neutral and also failed the correlation gate, while `SOLUSDT` degraded further into bearish bias.
  - `BNBUSDT` is now the only symbol left with bullish `4h` context, but it still trades below the `1h` support zone and does not have a valid trigger, so there is still no acceptable long setup.

### T063

- Timestamp: `2026-04-23 22:29 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #21`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan stayed broadly similar to `T062` but with even weaker intraday trigger quality: `ETHUSDT` lost the stronger momentum close from the previous wakeup, while `SOLUSDT` degraded to an almost flat `15m` body.
  - `BNBUSDT` remains the only symbol with bullish `4h` context, but it is still materially below the `1h` support zone and does not have a valid trigger, so there is still no acceptable long setup.

### T064

- Timestamp: `2026-04-23 22:45 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #22`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan improved slightly versus `T063` because `ETHUSDT` recovered bullish `4h` bias and `BNBUSDT` moved much closer to its `1h` support zone, but the basket still lacks a valid trigger/setup combination.
  - `BNBUSDT` is currently the closest live long candidate because it sits only `0.02` below the `1h` support zone, yet it still does not print a valid `15m` momentum close, so the setup remains invalid under the current rules.

### T065

- Timestamp: `2026-04-23 23:01 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #23`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan weakened versus `T064` because the basket is now blocked by an active `news blackout` on top of the already weak technical picture.
  - `BNBUSDT` remains the closest technical long candidate, but it is still below the `1h` support zone, lacks a valid `15m` trigger, and is additionally blocked by the live news filter.

### T066

- Timestamp: `2026-04-23 23:18 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #24`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan stayed broadly similar to `T065`: the active `news blackout` still blocks the basket, and the technical picture remains too weak for any discretionary override.
  - `BNBUSDT` remains the closest technical long candidate, but it is still below the `1h` support zone and its `15m` candle still closes weakly enough to fail the trigger.

### T067

- Timestamp: `2026-04-23 23:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #25`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan improved sharply on raw trigger quality: all four symbols printed valid `15m` momentum closes, but none cleared the full setup stack.
  - `BNBUSDT` became the clearest near-miss because it kept bullish `4h` context, printed a perfect `15m` trigger, and sat only `0.15` below the `1h` support zone, but it still failed the formal setup gate and remained blocked by the active news blackout.

### T068

- Timestamp: `2026-04-23 23:50 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #26`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `1h_setup=true`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This scan improved versus `T067` because `BNBUSDT` reclaimed the `1h` support zone and advanced from `WAIT` to `SETUP`, making it the clearest live candidate so far in the current blackout window.
  - The setup still remains invalid for entry because `BNBUSDT` has not confirmed the `15m` trigger, and the active `news blackout` is still on, so there is no reason to force a paper trade yet.

### T069

- Timestamp: `2026-04-24 00:06 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #27`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `session_filter=false`, `1h_setup=true`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `BNBUSDT` still holds the best live structure and remains at `SETUP`, but it is still missing a confirmed `15m` trigger.
  - This wakeup is additionally blocked by time-of-day: the session gate has now closed for all four symbols, so new long entries are formally disallowed even before considering the still-active news blackout.

### T070

- Timestamp: `2026-04-24 00:22 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #28`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `session_filter=false`, `1h_setup=true`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup improved versus `T069` because the news blackout cleared across the basket, and `BNBUSDT` now holds its `1h` support zone more cleanly while staying at `SETUP`.
  - Even with the news filter clear, the setup is still not actionable because `BNBUSDT` has not confirmed a valid `15m` trigger and the session gate remains closed for all four symbols.

### T071

- Timestamp: `2026-04-24 00:39 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #29`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `session_filter=false`, `1h_setup=true`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup remains formally non-tradable because the session gate is still closed for the whole basket.
  - `BNBUSDT` is still the best-looking candidate and has improved slightly by holding farther above the `1h` support zone, but it still has not confirmed a valid `15m` trigger, so there is still no reason to force a paper trade.

### T072

- Timestamp: `2026-04-24 00:55 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #30`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `session_filter=false`, `1h_setup=true`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T071`: the news filter is clear again, but the session gate remains closed across the basket.
  - `BNBUSDT` remains the clearest live candidate by holding its `1h` setup, yet it still lacks a confirmed `15m` trigger, so there is still no valid reason to open a paper trade.

### T073

- Timestamp: `2026-04-24 01:12 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #31`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened versus `T072` because `BNBUSDT` lost its `SETUP` status and slipped back below the `1h` support zone, leaving the basket without any strong live candidate.
  - The basket remains formally non-tradable overnight because the session gate is still closed across all four symbols.

### T074

- Timestamp: `2026-04-24 01:28 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #32`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=bearish`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed weak overnight: `BNBUSDT` remains the least-bad candidate on higher timeframe bias, but it is still back below the `1h` support zone and the `15m` trigger quality has softened further.
  - The basket remains formally non-tradable because the session gate is still closed across all four symbols.

### T075

- Timestamp: `2026-04-24 01:44 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #33`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `session_filter=false`, `1h_setup=true`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `BNBUSDT` improved slightly versus `T074` by regaining `SETUP` status and sitting just back above the `1h` support zone, so it remains the clearest overnight candidate.
  - Even so, the basket is still formally non-tradable because the session gate remains closed, and the live `15m` trigger quality is effectively absent right now, with multiple symbols printing zero-body or near-zero-body candles.

### T076

- Timestamp: `2026-04-24 02:00 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #34`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened versus `T075` because `BNBUSDT` lost its bullish `4h` bias and dropped out of `SETUP`, so the basket no longer has even a partial lead candidate.
  - `BNBUSDT` still printed a strong `15m` momentum close, but with the `4h` bias now neutral, the `1h` setup broken, and the session gate still closed, there is still no valid reason to open a paper trade.

### T077

- Timestamp: `2026-04-24 02:16 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #35`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened further versus `T076`: all four symbols now sit in the same `WAIT/neutral-or-worse` state, so the basket has no lead candidate at all.
  - `BNBUSDT` degraded again by moving farther below its `1h` support zone while also printing an effectively dead `15m` candle, so there is no reason to override the still-closed session gate.

### T078

- Timestamp: `2026-04-24 02:32 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #36`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T077`: the entire basket remains trapped in the same `WAIT/neutral` overnight regime without any lead candidate.
  - `BNBUSDT` recovered slightly versus the prior scan by moving back above its 1h support reference, but the higher-timeframe bias is still neutral, the 15m trigger is still invalid, and the closed session gate still makes the basket formally non-tradable.

### T079

- Timestamp: `2026-04-24 02:49 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #37`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=setup`, `bias=bullish`, `confidence=85`, `session_filter=false`, `1h_setup=true`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `BNBUSDT` improved again versus `T078` by regaining `SETUP` status and holding well above the `1h` support reference, so it remains the clearest overnight candidate.
  - Even so, the basket is still formally non-tradable because the session gate remains closed and `BNBUSDT` still lacks a confirmed `15m` trigger.
  - Because the overnight 15-minute cadence was no longer adding meaningful new information while session-gated, the heartbeat automation was reduced from every 15 minutes to every 1 hour.

### T080

- Timestamp: `2026-04-24 03:50 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #38`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup improved materially on raw trigger quality because all four symbols printed valid `15m` momentum closes, but none advanced beyond `WAIT`.
  - The reason is structural rather than tactical: the `4h` bias remains neutral across the basket, the `1h` setup is still invalid on all four symbols, and the session gate is still closed, so there is still no valid reason to open a paper trade.

### T081

- Timestamp: `2026-04-24 04:51 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #39`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened again versus `T080`: the stronger `15m` momentum burst from the previous hourly scan faded completely, returning the whole basket to a uniform `WAIT/neutral` state.
  - The basket remains formally non-tradable because the session gate is still closed across all four symbols, and there is currently no lead candidate worth overriding that rule.

### T082

- Timestamp: `2026-04-24 05:53 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #40`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened further versus `T081`: the entire basket remains trapped in `WAIT/neutral`, and `BNBUSDT` has now slipped materially deeper below its `1h` support reference instead of stabilizing.
  - The basket remains formally non-tradable because the session gate is still closed across all four symbols, and there is still no lead candidate worth overriding that rule.

### T083

- Timestamp: `2026-04-24 06:54 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #41`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly similar to `T082`: the basket remains stuck in an overnight `WAIT/neutral` regime with the session gate still closed across all four symbols.
  - `BNBUSDT` printed the strongest raw `15m` trigger on this scan, but it is still much too weak structurally because the `4h` bias remains neutral and price is still materially below the `1h` support reference.

### T084

- Timestamp: `2026-04-24 07:55 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #42`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup improved materially on raw trigger quality because all four symbols printed valid `15m` momentum closes, but the basket still stayed at `WAIT` because the `4h` bias remained neutral and the `1h` setup stayed invalid across the board.
  - The live news filter also flipped back into blackout while the session gate is still closed, so there is still no actionable long setup.
  - Because the active session window is approaching again and the basket just printed stronger short-term momentum, the heartbeat cadence was increased back from `1h` to `15m` to catch any valid setup soon after the session gate reopens.

### T085

- Timestamp: `2026-04-24 08:12 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #43`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened again versus `T084`: the stronger short-term momentum faded and the whole basket returned to a uniform `WAIT/neutral` state.
  - The basket is still formally non-tradable because the session gate remains closed just before the active window opens, and the live news filter is also still blocking all four symbols.

### T086

- Timestamp: `2026-04-24 08:28 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #44`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T085`: the entire basket remains trapped in a uniform `WAIT/neutral` regime without any lead candidate.
  - The basket is still formally non-tradable because the session gate remains closed and the live news filter is also still blocking all four symbols.

### T087

- Timestamp: `2026-04-24 08:44 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #45`
- Goal: Inspect the live basket, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T086`: the basket remains uniformly stuck in a `WAIT/neutral` regime without any lead candidate.
  - The basket is still formally non-tradable because the session gate remains closed, and the live news filter is also still blocking all four symbols.

### T088

- Timestamp: `2026-04-24 09:00 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #46`
- Goal: Inspect the live basket at the start of the allowed session window, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This is the first scan after the session gate reopened, but it still did not produce a usable entry because the whole basket remained stuck at `WAIT/neutral`.
  - The live news filter is also still blocking all four symbols, so even the reopening of the session window did not make the basket actionable.

### T089

- Timestamp: `2026-04-24 09:16 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #47`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T088`: even with the session gate open, the basket remains uniformly stuck at `WAIT/neutral` without any lead candidate.
  - The live news filter is still blocking all four symbols, so the session reopening still has not made the basket actionable.

### T090

- Timestamp: `2026-04-24 09:32 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #48`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T089`: even with the session gate open, the basket remains uniformly stuck at `WAIT/neutral` and structurally weak.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T091

- Timestamp: `2026-04-24 09:48 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #49`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T090`: the basket remains uniformly stuck at `WAIT/neutral` even with the session gate open.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T092

- Timestamp: `2026-04-24 10:04 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #50`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T091`: the basket remains uniformly stuck at `WAIT/neutral` even with the session gate open.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T093

- Timestamp: `2026-04-24 10:20 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #51`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup improved slightly on raw trigger quality versus `T092`: `ETHUSDT` and `BNBUSDT` both printed valid `15m` momentum closes.
  - Even so, the basket remains non-actionable because the broader context is still weak across the board: all four symbols remain on `WAIT`, all four still fail the `1h` setup gate, and none has recovered a bullish `4h` bias strong enough to justify a paper long.

### T094

- Timestamp: `2026-04-24 10:36 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #52`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened again versus `T093`: the brief intraday improvement in raw trigger quality disappeared and the basket returned to a fully uniform `WAIT/neutral` state.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T095

- Timestamp: `2026-04-24 10:52 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #53`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup improved slightly on raw trigger quality versus `T094`: `ETHUSDT` and `BNBUSDT` both printed valid `15m` momentum closes.
  - Even so, the basket remains non-actionable because the broader context is still weak across the board: all four symbols remain on `WAIT`, all four still fail the `1h` setup gate, and none has recovered a bullish `4h` bias strong enough to justify a paper long.
  - The live news filter is also still blocking all four symbols, so there is still no reason to override the flat stance.

### T096

- Timestamp: `2026-04-24 11:08 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #54`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened again versus `T095`: the brief improvement in raw trigger quality disappeared and the basket returned to a fully uniform `WAIT/neutral` state.
  - The live news filter is still blocking all four symbols, and there is currently no lead candidate worth overriding the flat stance.

### T097

- Timestamp: `2026-04-24 11:25 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #55`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T096`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - The situation is slightly cleaner operationally because both the session gate and the live news filter are now open, but the structure is still too weak across the board to justify any paper long.

### T098

- Timestamp: `2026-04-24 11:41 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #56`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup improved slightly on raw trigger quality versus `T097`: `ETHUSDT` and `SOLUSDT` both printed valid `15m` momentum closes.
  - Even so, the basket remains non-actionable because the broader context is still weak across the board: all four symbols remain on `WAIT`, all four still fail the `1h` setup gate, and none has recovered a bullish `4h` bias strong enough to justify a paper long.
  - The live news filter is also still blocking the whole basket, so there is still no reason to override the flat stance.

### T099

- Timestamp: `2026-04-24 11:58 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #57`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup weakened again versus `T098`: the small improvement in raw trigger quality disappeared and the basket returned to a fully uniform `WAIT/neutral` state.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T100

- Timestamp: `2026-04-24 12:14 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #58`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T099`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T101

- Timestamp: `2026-04-24 12:30 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #59`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T100`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T102

- Timestamp: `2026-04-24 12:46 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #60`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T101`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T103

- Timestamp: `2026-04-24 13:02 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #61`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T102`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - `BTCUSDT` improved slightly on raw `15m` candle quality, but the broader context is still too weak across the board because all four symbols continue to fail both the `4h` bias and `1h` setup gates.
  - The live news filter is still blocking all four symbols, so there is still no actionable candidate and no reason to override the flat stance.

### T104

- Timestamp: `2026-04-24 13:18 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #62`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T103`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - The live news filter is clear again, but that still does not help because all four symbols continue to fail both the `4h` bias and `1h` setup gates, leaving no actionable long setup.

### T105

- Timestamp: `2026-04-24 13:34 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #63`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T104`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - ETHUSDT, SOLUSDT, and BNBUSDT all moved a bit closer to their `1h` support references, but none recovered enough structure to clear the setup gate, so there is still no actionable long setup.

### T106

- Timestamp: `2026-04-24 13:50 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #64`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T105`: the basket remains uniformly stuck at `WAIT/neutral` with no lead candidate.
  - `SOLUSDT` was the closest name to its `1h` support reference, but all four symbols still remained below support and none printed a valid `15m` momentum close, so there is still no actionable long setup.

### T107

- Timestamp: `2026-04-24 14:07 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #65`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `SOLUSDT` was the clearest near-miss in this wakeup: price reclaimed the `1h` support area and printed a valid raw `15m` momentum close, but the formal setup gate still remained closed and the broader `4h` bias stayed `neutral`.
  - The rest of the basket remained weak and unchanged, so there is still no actionable long setup and no reason to override the flat stance.

### T108

- Timestamp: `2026-04-24 14:24 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #66`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `SOLUSDT` held slightly above its `1h` support reference, but the raw `15m` trigger that briefly improved in `T107` faded immediately and the broader `4h` bias still stayed `neutral`.
  - The rest of the basket remained weak and unchanged, so there is still no actionable long setup and no reason to override the flat stance.

### T109

- Timestamp: `2026-04-24 14:40 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #67`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `SOLUSDT` remained the closest name to a valid long context by holding just above its `1h` support reference, but it still failed the formal setup gate and did not confirm a valid `15m` trigger.
  - The rest of the basket remained weak and unchanged, so there is still no actionable long setup and no reason to override the flat stance.

### T110

- Timestamp: `2026-04-24 14:56 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #68`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T109`: `SOLUSDT` lost its slight hold above the `1h` support reference and slipped back below it, so the basket no longer has even a marginal near-miss candidate.
  - The rest of the basket remained weak and unchanged, so there is still no actionable long setup and no reason to override the flat stance.

### T111

- Timestamp: `2026-04-24 15:12 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #69`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - `BNBUSDT` was the clearest near-miss in this wakeup: it printed a valid raw `15m` momentum close and came within `0.33` of the `1h` support reference, but the formal setup gate still remained closed and the broader `4h` bias stayed `neutral`.
  - `ETHUSDT` and `SOLUSDT` both reclaimed their immediate `1h` support references, but their candle-close quality still stayed too weak to open a valid long setup.
  - The basket therefore remained non-actionable and there is still no reason to override the flat stance.

### T112

- Timestamp: `2026-04-24 15:28 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #70`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T111`: `BNBUSDT` lost its raw `15m` trigger confirmation, and the basket returned to a fully uniform `WAIT` state.
  - `ETHUSDT` and `SOLUSDT` both sat marginally above their immediate `1h` support references, but the candle-close quality remained too weak and the broader `4h` bias stayed `neutral`, so there is still no actionable long setup.

### T113

- Timestamp: `2026-04-24 15:44 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #71`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T112`: the basket remained uniformly stuck at `WAIT` with no actionable lead candidate.
  - `SOLUSDT` was nominally the closest name to reclaiming its `1h` support reference, but it still sat slightly below it and failed the `15m` trigger gate, while `BTCUSDT` printed an almost dead `15m` candle body and added no usable momentum context.

### T114

- Timestamp: `2026-04-24 16:00 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #72`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T113`: the basket stayed uniformly at `WAIT`, and all four symbols printed very weak `15m` candle-closes with heavy bodies finishing near the bottom of their ranges.
  - `BTCUSDT`, `SOLUSDT`, and `BNBUSDT` all slipped materially farther below their `1h` support references, so there is no usable lead candidate and no reason to override the flat stance.

### T115

- Timestamp: `2026-04-24 16:16 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #73`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T114`: the basket remained uniformly stuck at `WAIT` with no actionable lead candidate.
  - `BTCUSDT`, `SOLUSDT`, and `BNBUSDT` all stayed materially below their `1h` support references, while `ETHUSDT` remained correlation-blocked and still below support, so there is still no reason to override the flat stance.

### T116

- Timestamp: `2026-04-24 16:32 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #74`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T115`: the entire basket stayed at `WAIT` while all four symbols drifted farther below their `1h` support references.
  - `BNBUSDT` printed the strongest raw close-location reading of the basket, but it still failed the trigger test because price did not clear the previous high and the broader setup remained invalid, so there is still no reason to override the flat stance.

### T117

- Timestamp: `2026-04-24 16:48 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #75`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T116`: the basket stayed uniformly at `WAIT`, and all four symbols closed their latest `15m` candles essentially at the bottom of the range.
  - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, and `BNBUSDT` all remained below their `1h` support references, with `ETHUSDT` still correlation-blocked as well, so there is still no actionable lead candidate and no reason to override the flat stance.

### T118

- Timestamp: `2026-04-24 17:04 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #76`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed effectively unchanged versus `T117`: the basket remained uniformly at `WAIT`, and all four symbols again printed very weak `15m` closes near the bottom of their ranges.
  - `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` all remained materially below their `1h` support references, while `BNBUSDT` came closest but still stayed just below support and printed a dead-on-arrival trigger candle, so there is still no actionable lead candidate and no reason to override the flat stance.

### T119

- Timestamp: `2026-04-24 17:20 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #77`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed broadly unchanged versus `T118`: the basket remained uniformly at `WAIT` and none of the four symbols recovered a usable setup.
  - `BTCUSDT`, `SOLUSDT`, and `BNBUSDT` all remained below their `1h` support references, while `ETHUSDT` stayed correlation-blocked and also below support; the latest `15m` candles were effectively dead across the basket, so there is still no actionable lead candidate and no reason to override the flat stance.

### T120

- Timestamp: `2026-04-24 17:36 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #78`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable, but `BNBUSDT` became the clearest near-miss by reclaiming its `1h` support reference by `0.10`; it still failed the `15m` trigger gate and the broader `4h` bias remained `neutral`.
  - `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` all remained below their `1h` support references, with `ETHUSDT` still correlation-blocked as well, so there is still no actionable lead candidate and no reason to override the flat stance.

### T121

- Timestamp: `2026-04-24 17:52 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #79`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable, but `BNBUSDT` remained the clearest near-miss by holding `1.54` above its `1h` support reference; it still failed the `15m` trigger gate and the broader `4h` bias remained `neutral`.
  - `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` all remained below their `1h` support references, with `ETHUSDT` still correlation-blocked as well, so there is still no actionable lead candidate and no reason to override the flat stance.

### T122

- Timestamp: `2026-04-24 18:08 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #80`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable, with `BNBUSDT` again the clearest near-miss by holding `1.27` above its `1h` support reference; it still failed the `15m` trigger gate and the broader `4h` bias remained `neutral`.
  - `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` all remained below their `1h` support references, with `ETHUSDT` still correlation-blocked as well, so there is still no actionable lead candidate and no reason to override the flat stance.

### T123

- Timestamp: `2026-04-24 18:24 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #81`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable, with `BNBUSDT` again the clearest near-miss by holding `0.17` above its `1h` support reference; it still failed the `15m` trigger gate and the broader `4h` bias remained `neutral`.
  - `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` all remained below their `1h` support references, with `ETHUSDT` still correlation-blocked as well, so there is still no actionable lead candidate and no reason to override the flat stance.

### T124

- Timestamp: `2026-04-24 18:40 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #82`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T123`: the whole basket stayed at `WAIT`, all four symbols failed both the `1h` setup and `15m` trigger gates, and a fresh `news blackout` reactivated across the entire basket.
  - `BNBUSDT` lost its slight hold above the `1h` support reference and slipped back below it, so there is again no usable lead candidate and no reason to override the flat stance.

### T125

- Timestamp: `2026-04-24 18:56 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #83`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable and broadly unchanged versus `T124`: the whole basket remained at `WAIT`, all four symbols still failed both the `1h` setup and `15m` trigger gates, and the `news blackout` remained active across the entire basket.
  - `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, and `BNBUSDT` all remained below their `1h` support references, so there is still no usable lead candidate and no reason to override the flat stance.

### T126

- Timestamp: `2026-04-24 19:12 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #84`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable under the still-active `news blackout`, although `SOLUSDT` printed a valid raw `15m` momentum close and `BNBUSDT` held `0.42` above its `1h` support reference.
  - Neither near-miss cleared the full setup stack: `SOLUSDT` still sat below `1h` support, `BNBUSDT` still failed the `15m` trigger gate, and the broader `4h` bias remained `neutral`, so there is still no reason to override the flat stance.

### T127

- Timestamp: `2026-04-24 19:28 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #85`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable and broadly unchanged versus `T126`: the still-active `news blackout` kept blocking the full basket while all four symbols remained at `WAIT`.
  - `BNBUSDT` slipped back below its `1h` support reference, `SOLUSDT` lost the previous raw trigger improvement, and `ETHUSDT` remained correlation-blocked, so there is still no usable lead candidate and no reason to override the flat stance.

### T128

- Timestamp: `2026-04-24 19:44 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #86`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable and broadly unchanged versus `T127`: the still-active `news blackout` kept the full basket blocked while all four symbols remained at `WAIT`.
  - `BTCUSDT` and `ETHUSDT` printed stronger raw close-location readings, but neither cleared the prior-high requirement and both still sat below `1h` support, so there is still no usable lead candidate and no reason to override the flat stance.

### T129

- Timestamp: `2026-04-24 20:00 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #87`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=false`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=false`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable and broadly unchanged versus `T128`: the still-active `news blackout` kept the full basket blocked while all four symbols remained at `WAIT`.
  - `ETHUSDT` was the closest name to reclaiming its updated `1h` support reference, but it still sat below support and remained correlation-blocked, while `BNBUSDT` drifted materially below its new support reference, so there is still no usable lead candidate and no reason to override the flat stance.

### T130

- Timestamp: `2026-04-24 20:16 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #88`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable even after the `news blackout` cleared: the whole basket remained at `WAIT` and all four symbols still failed both the `1h` setup and `15m` trigger gates.
  - `BTCUSDT`, `SOLUSDT`, and `BNBUSDT` all slipped materially farther below their updated `1h` support references, while `ETHUSDT` remained correlation-blocked and still below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T131

- Timestamp: `2026-04-24 20:32 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #89`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable even after the `news blackout` cleared again: the whole basket remained at `WAIT` and all four symbols still failed both the `1h` setup and `15m` trigger gates.
  - `BNBUSDT` showed the strongest raw trigger improvement of the basket by closing above the previous high, but it still sat materially below `1h` support and the broader `4h` bias remained `neutral`, so there is still no usable lead candidate and no reason to override the flat stance.

### T132

- Timestamp: `2026-04-24 20:48 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #90`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable even after the `news blackout` cleared again: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `BNBUSDT` became the clearest near-miss by printing a valid raw `15m` momentum close, but it still sat materially below its updated `1h` support reference and the broader `4h` bias remained `neutral`, so there is still no usable lead candidate and no reason to override the flat stance.

### T133

- Timestamp: `2026-04-24 21:04 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #91`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `ETHUSDT` came closest to reclaiming its `1h` support reference, sitting only `0.61` below it, but it remained correlation-blocked and still lacked a valid `15m` trigger; the other three symbols stayed materially below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T134

- Timestamp: `2026-04-24 21:20 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #92`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `ETHUSDT` remained the closest name to reclaiming its `1h` support reference, sitting only `0.42` below it, but it remained correlation-blocked and still lacked a valid `15m` trigger; the other three symbols stayed materially below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T135

- Timestamp: `2026-04-24 21:36 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #93`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `ETHUSDT` remained the closest name to reclaiming its `1h` support reference, but it still sat `1.75` below support, remained correlation-blocked, and lacked a valid `15m` trigger; the other three symbols stayed materially below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T136

- Timestamp: `2026-04-24 21:52 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #94`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `ETHUSDT` again came closest to reclaiming its `1h` support reference, but it still sat `2.68` below support, remained correlation-blocked, and lacked a valid `15m` trigger; the other three symbols stayed materially below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T137

- Timestamp: `2026-04-24 22:08 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #95`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `ETHUSDT` again came closest to reclaiming its `1h` support reference, but it still sat `4.03` below support, remained correlation-blocked, and lacked a valid `15m` trigger; the other three symbols stayed materially below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T138

- Timestamp: `2026-04-24 22:24 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #96`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - It was weaker than `T137` on raw candle quality: all four names printed heavy `15m` candles that closed near the bottom of their ranges while also remaining below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T139

- Timestamp: `2026-04-24 22:40 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #97`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was technically stronger than `T138`: `ETHUSDT`, `SOLUSDT`, and `BNBUSDT` all printed valid raw `15m` momentum closes, and `BNBUSDT` improved to a `bullish` bias with `confidence=60`.
  - Even so, the whole basket remained non-actionable because all four symbols still failed the `1h` setup gate; `ETHUSDT` also remained correlation-blocked, and `BNBUSDT` still sat `2.75` below its support reference, so there is still no reason to override the flat stance.

### T140

- Timestamp: `2026-04-24 22:56 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #98`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was technically stronger than `T139`: `BTCUSDT` and `ETHUSDT` both printed exceptionally strong raw `15m` momentum closes, while `BNBUSDT` retained a `bullish` bias with `confidence=60`.
  - Even so, the basket remained non-actionable because all four symbols still failed the `1h` setup gate; `ETHUSDT` also remained correlation-blocked, and `BNBUSDT` still sat materially below its support reference, so there is still no reason to override the flat stance.

### T141

- Timestamp: `2026-04-24 23:12 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #99`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was weaker than `T140`: the prior raw `15m` momentum improvement disappeared and the whole basket reverted to a uniform `WAIT` state.
  - `ETHUSDT` and `SOLUSDT` both briefly held just above their `1h` support references, but neither produced a valid `15m` trigger and `ETHUSDT` remained correlation-blocked; `BNBUSDT` kept a `bullish` bias but still sat materially below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T142

- Timestamp: `2026-04-24 23:28 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #100`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - `ETHUSDT` again came closest to reclaiming its `1h` support reference, but it still sat `5.55` below support, remained correlation-blocked, and lacked a valid `15m` trigger; the other three symbols also stayed below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T143

- Timestamp: `2026-04-24 23:44 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #101`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=true`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed non-actionable with the `news blackout` still clear: the whole basket remained at `WAIT` and all four symbols still failed the `1h` setup gate.
  - Raw candle shape became unusual across the basket, with several `15m` candles closing at the top of their ranges despite failing the prior-high rule; even so, every symbol remained below support and there is still no usable lead candidate or reason to override the flat stance.

### T144

- Timestamp: `2026-04-25 00:00 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #102`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup was structurally weaker than `T143` because the session gate closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - All four symbols also remained below their `1h` support references, with `ETHUSDT` still correlation-blocked, so there is still no usable lead candidate and no reason to override the flat stance.

### T145

- Timestamp: `2026-04-25 00:16 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #103`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - `BNBUSDT` retained a `bullish` bias with `confidence=60`, but it still sat materially below support and lacked a valid `15m` trigger; the other three symbols also remained below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T146

- Timestamp: `2026-04-25 00:32 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #104`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - It was weaker than `T145`: `BNBUSDT` lost its earlier bullish bias and the whole basket reverted to a uniform `WAIT/neutral` overnight state while all four symbols remained below their `1h` support references.

### T147

- Timestamp: `2026-04-25 00:48 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #105`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - It was weaker than `T146`: all four symbols slipped even farther below their `1h` support references overnight, with `BTCUSDT`, `ETHUSDT`, and `BNBUSDT` all printing especially poor trigger quality on the latest `15m` candles.

### T148

- Timestamp: `2026-04-25 01:04 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #106`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - `ETHUSDT` was the clearest overnight near-miss by printing a valid raw `15m` momentum close, but it still sat `18.95` below its `1h` support reference and remained correlation-blocked, while the rest of the basket stayed weak and below support.

### T149

- Timestamp: `2026-04-25 01:20 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #107`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - It was weaker than `T148`: `ETHUSDT` lost the prior raw `15m` trigger improvement, `BNBUSDT` remained neutral, and all four symbols stayed materially below their `1h` support references overnight.

### T150

- Timestamp: `2026-04-25 01:36 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #108`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=true`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - `ETHUSDT` regained a valid raw `15m` momentum close, but it still sat `16.52` below its `1h` support reference and remained correlation-blocked; the rest of the basket stayed below support and also lacked valid trigger confirmation.

### T151

- Timestamp: `2026-04-25 01:52 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #109`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - It was weaker than `T150`: `ETHUSDT` lost the prior raw `15m` trigger improvement, and all four symbols remained materially below their `1h` support references overnight.

### T152

- Timestamp: `2026-04-25 02:08 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #110`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=false`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - `BNBUSDT` regained a `bullish` bias with `confidence=60`, but it still sat materially below its `1h` support reference and lacked a valid `15m` trigger; the other three symbols also remained below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T153

- Timestamp: `2026-04-25 02:24 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #111`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=true`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=bullish`, `confidence=60`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - `BNBUSDT` kept a `bullish` bias with `confidence=60`, but it slipped even farther below its `1h` support reference and still lacked a valid `15m` trigger; the rest of the basket also stayed below support, so there is still no usable lead candidate and no reason to override the flat stance.

### T154

- Timestamp: `2026-04-25 02:40 Europe/Ljubljana`
- Status: `done`
- Scope: `Realtime campaign heartbeat scan #112`
- Goal: Inspect the live basket after the session window reopened, confirm paper-account cleanliness, and open at most one observation trade only if a clean `READY` signal appears.
- Inputs:
  - Endpoint: `GET /api/dashboard`
  - Symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
  - Account state before scan: `0 positions`, `0 orders`, `0 trades`, `cash=10000.0000`, `realized_pnl=0.0000`
- Result:
  - `BTCUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `ETHUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `correlation_filter=true`, `news_filter=true`
  - `SOLUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
  - `BNBUSDT`: `stage=wait`, `bias=neutral`, `confidence=25`, `session_filter=false`, `1h_setup=false`, `15m_trigger=false`, `news_filter=true`
- Decision:
  - No paper trade opened.
- Notes:
  - The paper account remains fully flat and clean.
  - No symbol reached a clean `READY` state, so no observation trade was opened.
  - This wakeup stayed structurally non-tradable because the session gate remained closed for the full basket, making new entries formally disallowed even before considering setup quality.
  - It was weaker than `T153`: `BNBUSDT` lost the prior bullish bias again, and all four symbols remained materially below their `1h` support references overnight.

### Research campaign 2026-04-26 00:40 Srednjeevropski poletni čas  

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_research_harness.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Top candidate: `v2_reclaim`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Promoted strategies: `none`

### Research campaign 2026-04-26 00:40 Srednjeevropski poletni čas  

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_research_harness_all_candidates.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `16`
- Top candidate: `v2_reclaim`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Promoted strategies: `none`


### Realtime paper heartbeat 2026-04-25T23:25:06Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `orders=0`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness process is still active; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-25T23:41:09Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `orders=0`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness progressed to `v2_reclaim_strong_trigger`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-25T23:57:37Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `orders=0`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness progressed to `v2_reclaim_serial`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T00:13:32Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `orders=0`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness progressed to `v2_reclaim_partial_no_be`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T00:29:31Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `orders=0`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness progressed to `v2_reclaim_time_stop_16`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T00:46:02Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness is still running and has progressed to `v2_reclaim_no_be_trail`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T01:02:32Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness is still running and has progressed to `v2_reclaim_btc_bullish`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T01:18:33Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness is still running and has progressed to `v2_reclaim_atr_expansion`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T01:34:33Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness is still running and has progressed to `v2_reclaim_overlap_only`; no final full-run artifact has been written yet.

### Realtime paper heartbeat 2026-04-26T01:50:33Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and the session gate was closed.
- Research note: full research harness is still running and has progressed to `opening_session_breakout`; no final full-run artifact has been written yet.

### Research campaign 2026-04-26T02:02:18Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\research_run_20260426_040218.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, AXSUSDT, TRUMPUSDT, USD1USDT, APEUSDT, DOGEUSDT, XRPUSDT, HYPERUSDT, BNBUSDT, API3USDT, ZBTUSDT, ZECUSDT, TRXUSDT, ORCAUSDT, ADAUSDT, PEPEUSDT, SANDUSDT, MOVRUSDT`
- Candidates tested: `18`
- Top candidate: `v2_reclaim_overlap_only`
- Top OOS: `trades=16`, `net_total_r=-2.9538`, `net_avg_r=-0.1846`, `pf=0.664`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, symbol_concentration>0.4`
- Promoted strategies: `none`


### Realtime paper heartbeat 2026-04-26T02:06:33Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research result: full run completed and wrote `tmp/research_runs/research_run_20260426_040218.json`; `0` candidates passed promotion gates.
- Best candidate by harness ranking: `v2_reclaim_overlap_only`, `out_of_sample_trades=16`, `net_total_r=-2.9538`, `net_avg_r=-0.1846`, `profit_factor=0.664`, `holdout_net_r=-2.3581`, `folds_positive=1`.
- Automation update: `realtime-paper-test` now blocks new paper entries unless a strategy is explicitly promoted after passing campaign gates.

### Realtime paper heartbeat 2026-04-26T02:24:33Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is no longer running.

### Realtime paper heartbeat 2026-04-26T02:41:34Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T02:58:34Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T03:15:34Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T03:32:35Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T03:49:35Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T04:06:35Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T04:23:35Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T04:40:36Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T04:57:36Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T05:14:36Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T05:31:36Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T05:48:37Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T06:05:37Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T06:22:37Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.

### Realtime paper heartbeat 2026-04-26T06:39:38Z

- Status: `done`
- Scope: `realtime-paper-test`
- Account: `cash=10000.00`, `positions=0`, `open_orders=0`, `equity=10000.00`
- BTCUSDT: `stage=wait`, `bias=bearish`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- ETHUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=false`, `news=true`, `risk_plan=false`
- SOLUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- BNBUSDT: `stage=wait`, `bias=neutral`, `confidence=15`, `trend=false`, `setup=false`, `reclaim=false`, `trigger=false`, `session=false`, `correlation=true`, `news=true`, `risk_plan=false`
- Decision: no paper trade opened; no symbol had a clean `READY` signal and no strategy is promoted.
- Research note: no new research artifact after `tmp/research_runs/research_run_20260426_040218.json`; full research process is not running.
- Automation note: changed `realtime-paper-test` from frequent guard checks to one daily guard scan because no strategy is promoted and intraday paper entries are blocked.

### Research campaign 2026-04-26T09:52:44Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_research_harness_strict_workers.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=10000000.0`
- Top candidate: `v2_reclaim_loose`
- Top OOS: `trades=3`, `net_total_r=-3.8257`, `net_avg_r=-1.2752`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, symbol_concentration>0.4, single_trade_concentration>0.25`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-26T09:54:19Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_research_harness_strict_core_workers.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_loose`
- Top OOS: `trades=3`, `net_total_r=-3.8257`, `net_avg_r=-1.2752`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, symbol_concentration>0.4, single_trade_concentration>0.25`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research harness implementation 2026-04-26T09:56:47Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Changes: stricter mature/core universe selection, non-standard/stable/leveraged/meme/event symbol rejection, `--workers` parallel candidate evaluation, faster closed-candle prefix lookup, and JSON/log diagnostics.
- Smoke check: `python scripts/research_harness.py --smoke --workers 2 --json-out tmp\research_runs\smoke_research_harness_strict_core_workers.json` passed.
- Top-20 sanity check: `python scripts\research_harness.py --trigger-limit 1000 --universe-limit 20 --max-candidates 1 --workers 2 --no-log --json-out tmp\research_runs\sanity_research_harness_strict_core_top20.json` passed.
- Strict sanity universe: `BTCUSDT, ETHUSDT, SOLUSDT, AXSUSDT, XRPUSDT, BNBUSDT, RAYUSDT, ZECUSDT, TONUSDT, TRXUSDT, INJUSDT, ADAUSDT, SUIUSDT, AAVEUSDT, SANDUSDT, LINKUSDT, AVAXUSDT, ALGOUSDT, LTCUSDT, GALAUSDT`.
- Verification: `python -m py_compile scripts\strategy_study.py scripts\research_harness.py scripts\test_research_harness.py`, `python scripts\test_research_harness.py`, and `cargo check` passed.

### Research campaign 2026-04-26T13:02:29Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\research_run_20260426_150229.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, AXSUSDT, BNBUSDT, XRPUSDT, RAYUSDT, ZECUSDT, TONUSDT, TRXUSDT, INJUSDT, ADAUSDT, SUIUSDT, AAVEUSDT, LINKUSDT, SANDUSDT, AVAXUSDT, ALGOUSDT, LTCUSDT, NEARUSDT`
- Candidates tested: `18`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_overlap_only`
- Top OOS: `trades=22`, `net_total_r=0.6812`, `net_avg_r=0.031`, `pf=1.098`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, symbol_concentration>0.4`
- Top gate failure counts: `net_avg_r<0.1=18, profit_factor<1.25=18, holdout_net_total_r<=0=18, holdout_net_avg_r<0.05=18, folds_positive<4=18`
- Promoted strategies: `none`


### Research campaign 2026-04-26T18:43:35Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_overlap_smoke_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `22`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_loose`
- Top OOS: `trades=3`, `net_total_r=-3.8257`, `net_avg_r=-1.2752`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, symbol_concentration>0.4, single_trade_concentration>0.25`
- Top gate failure counts: `not_full_12000_candle_walk_forward=22, executed_trades<80=22, net_avg_r<0.1=22, profit_factor<1.25=22, holdout_net_total_r<=0=22`
- Promoted strategies: `none`


### Research campaign 2026-04-26T19:44:56Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_overlap_family_smoke_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_overlap_fee_ok`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-26T20:18:14Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_overlap_family_full_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, RAYUSDT, LDOUSDT, ZECUSDT, AXSUSDT, TRXUSDT, INJUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, SUIUSDT, LINKUSDT, XLMUSDT, LTCUSDT, NEARUSDT`
- Candidates tested: `8`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_overlap_time_stop_fee_ok`
- Top OOS: `trades=13`, `net_total_r=4.6063`, `net_avg_r=0.3543`, `pf=2.1797`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, symbol_concentration>0.4`
- Top gate failure counts: `executed_trades<80=8, holdout_net_total_r<=0=8, holdout_net_avg_r<0.05=8, folds_positive<4=8, symbol_concentration>0.4=8`
- Promoted strategies: `none`


### Research campaign 2026-04-26T20:31:39Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_widening_smoke_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_overlap_time_stop_no_btc`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-26T21:14:39Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_widening_full_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, RAYUSDT, LDOUSDT, ZECUSDT, AXSUSDT, TRXUSDT, INJUSDT, AAVEUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT`
- Candidates tested: `8`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_overlap_ny_time_stop_loose_fee_no_btc`
- Top OOS: `trades=37`, `net_total_r=11.1742`, `net_avg_r=0.302`, `pf=2.1054`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=8, folds_positive<4=8, symbol_concentration>0.4=4, single_trade_concentration>0.25=2, net_avg_r<0.1=1`
- Promoted strategies: `none`


### Research campaign 2026-04-26T21:18:43Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_scale_smoke_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_active_time_stop_loose_fee_no_btc`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-26T21:50:05Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_scale_full_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, AAVEUSDT, ADAUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, NEARUSDT, LTCUSDT`
- Candidates tested: `8`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_active_time_stop_no_corr_no_btc`
- Top OOS: `trades=65`, `net_total_r=11.2022`, `net_avg_r=0.1723`, `pf=1.4482`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `folds_positive<4=8, executed_trades<80=6, net_avg_r<0.1=3, profit_factor<1.25=3, max_drawdown_r>10.0=2`
- Promoted strategies: `none`


### Research campaign 2026-04-26T22:22:32Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_scale_top3_universe30_20260426.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `3`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_active_time_stop_no_corr_no_btc`
- Top OOS: `trades=81`, `net_total_r=9.7162`, `net_avg_r=0.12`, `pf=1.2917`
- Top gate status: `fail`
- Top gate failures: `folds_positive<4`
- Top gate failure counts: `folds_positive<4=3, executed_trades<80=1, net_avg_r<0.1=1, profit_factor<1.25=1`
- Promoted strategies: `none`


### Research campaign 2026-04-26T23:19:48Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_refinement_smoke_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_active_no_corr_vol_lt90`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-26T23:51:06Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\focused_refinement_full_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, INJUSDT, TRXUSDT, AXSUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, NEARUSDT, XLMUSDT, LTCUSDT, HBARUSDT, ALGOUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `8`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `v2_reclaim_active_no_corr_ex_worst6`
- Top OOS: `trades=68`, `net_total_r=22.5475`, `net_avg_r=0.3316`, `pf=2.1846`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=8, folds_positive<4=8, holdout_net_avg_r<0.05=2, holdout_net_total_r<=0=1`
- Promoted strategies: `none`


### Research campaign 2026-04-27T00:57:15Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\absurd_candle_smoke_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `breakout_pullback_active`
- Top OOS: `trades=24`, `net_total_r=-16.3353`, `net_avg_r=-0.6806`, `pf=0.1281`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0, symbol_concentration>0.4, single_trade_concentration>0.25`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-27T01:27:55Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\absurd_candle_full_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, AXSUSDT, LINKUSDT, SUIUSDT, NEARUSDT, LTCUSDT, XLMUSDT, HBARUSDT, ALGOUSDT, APTUSDT`
- Candidates tested: `8`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `crash_rebound_active`
- Top OOS: `trades=45`, `net_total_r=-9.1335`, `net_avg_r=-0.203`, `pf=0.4672`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `net_avg_r<0.1=8, profit_factor<1.25=8, holdout_net_total_r<=0=8, holdout_net_avg_r<0.05=8, folds_positive<4=8`
- Promoted strategies: `none`



### Derivatives diagnostics 2026-04-27T08:29:04Z

- Status: `done`
- Artifact: `tmp\research_runs\derivatives_profile_20260427.json`
- Source artifact: `tmp\research_runs\focused_scale_top3_universe30_20260426.json`
- Trade diagnostics: `tmp\research_runs\near_miss_full_trade_diagnostics_20260427_010625.json`
- Symbols profiled: `24`
- Funding rows: `9451`
- Open-interest rows: `11500`
- Enriched trades: `81`
- Best funding bucket by avg R: `-1..0bp` with `trades=17`, `net_avg_r=0.4784`, `pf=2.8872`
- Promoted strategies: `none`
### Research campaign 2026-04-27T09:16:09Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\derivatives_filter_core_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `3`
- Top candidate: `v2_reclaim_active_no_corr_funding_not_panic`
- Top OOS: `trades=61`, `net_total_r=11.9304`, `net_avg_r=0.1956`, `pf=1.491`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=3, folds_positive<4=3`
- Promoted strategies: `none`


### Research campaign 2026-04-27T09:29:45Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\derivatives_filter_secondary_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `3`
- Top candidate: `v2_reclaim_active_no_corr_funding_neg_to_pos1`
- Top OOS: `trades=61`, `net_total_r=11.9304`, `net_avg_r=0.1956`, `pf=1.491`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=3, folds_positive<4=3, net_avg_r<0.1=1, profit_factor<1.25=1, holdout_net_avg_r<0.05=1`
- Promoted strategies: `none`



### Derivatives diagnostics 2026-04-27T09:46:43Z

- Status: `done`
- Artifact: `tmp\research_runs\derivatives_metrics_profile_20260427.json`
- Source artifact: `tmp\research_runs\focused_scale_top3_universe30_20260426.json`
- Trade diagnostics: `tmp\research_runs\near_miss_full_trade_diagnostics_20260427_010625.json`
- Symbols profiled: `24`
- Funding rows: `9451`
- Open-interest rows: `11500`
- Metrics rows: `28512`
- Enriched trades: `81`
- Best funding bucket by avg R: `-1..0bp` with `trades=17`, `net_avg_r=0.4784`, `pf=2.8872`
- Promoted strategies: `none`
### Research campaign 2026-04-27T11:18:16Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\metrics_filter_top12_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT`
- Candidates tested: `4`
- Top candidate: `v2_reclaim_active_base_funding_taker_buy`
- Top OOS: `trades=40`, `net_total_r=13.7946`, `net_avg_r=0.3449`, `pf=2.1448`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=4, folds_positive<4=4, symbol_concentration>0.4=1`
- Promoted strategies: `none`


### Research campaign 2026-04-27T11:49:25Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\metrics_filter_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `4`
- Top candidate: `v2_reclaim_active_strict_funding_taker_buy`
- Top OOS: `trades=39`, `net_total_r=12.4466`, `net_avg_r=0.3191`, `pf=1.9865`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `folds_positive<4=4, executed_trades<80=2, net_avg_r<0.1=2, profit_factor<1.25=2, holdout_net_avg_r<0.05=2`
- Promoted strategies: `none`


### Research campaign 2026-04-27T11:54:31Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\metrics_filter_overlap_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `2`
- Top candidate: `v2_reclaim_overlap_strict_funding_taker_buy`
- Top OOS: `trades=13`, `net_total_r=9.2738`, `net_avg_r=0.7134`, `pf=6.9706`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=2, folds_positive<4=2`
- Promoted strategies: `none`


### Research campaign 2026-04-27T12:16:26Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\broad_derivatives_entry_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `5`
- Top candidate: `htf_continuation_london_overlap_funding_taker`
- Top OOS: `trades=575`, `net_total_r=-15.1989`, `net_avg_r=-0.0264`, `pf=0.9268`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `net_avg_r<0.1=5, profit_factor<1.25=5, holdout_net_avg_r<0.05=5, folds_positive<4=5, max_drawdown_r>10.0=5`
- Promoted strategies: `none`


### Research campaign 2026-04-27T12:25:41Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\broad_derivatives_refined_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `6`
- Top candidate: `htf_continuation_london_funding_taker`
- Top OOS: `trades=333`, `net_total_r=12.729`, `net_avg_r=0.0382`, `pf=1.1192`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `folds_positive<4=6, executed_trades<80=5, symbol_concentration>0.4=3, net_avg_r<0.1=2, profit_factor<1.25=2`
- Promoted strategies: `none`


### Research campaign 2026-04-27T12:29:26Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\broad_derivatives_oi_sweep_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `5`
- Top candidate: `htf_london_funding_taker_oi_max0`
- Top OOS: `trades=76`, `net_total_r=11.5411`, `net_avg_r=0.1519`, `pf=1.4318`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `folds_positive<4=5, executed_trades<80=4, max_drawdown_r>10.0=4, net_avg_r<0.1=2, profit_factor<1.25=2`
- Promoted strategies: `none`


### Fold diagnostics 2026-04-27T12:45:00Z

- Status: `done`
- Scope: `htf-london-oi-bottleneck`
- Artifact: `tmp\research_runs\fold_diagnostics_htf_london_oi_neg10_pos1_20260427.json`
- Candidate: `htf_london_funding_taker_oi_neg10_pos1`
- OOS: `trades=105`, `net_total_r=11.3384`, `net_avg_r=0.108`, `pf=1.3296`
- Holdout: `trades=72`, `net_total_r=14.6863`, `net_avg_r=0.204`
- Validation folds with trades: `fold3=+0.7239R`, `fold4=-2.5843R`, `fold5=-1.4875R`; folds `1` and `2` had no trades.
- Main finding: simple filters can improve trade quality but cannot satisfy the `4 of 5` positive-fold gate because fold coverage is missing.
- Baseline artifact: `tmp\research_runs\fold_diagnostics_htf_baseline_20260427.json`
- Baseline finding: ungated HTF continuation has fold-2 trades, but is strongly negative overall; fold 2 is mostly a funding-panic regime and the apparent New York panic workaround fails in holdout.
- Promoted strategies: `none`


### Research campaign 2026-04-27T20:27:32Z

- Status: `done`
- Scope: `coverage-first-scan`
- Artifacts: `tmp\research_runs\coverage_scan_trend_reclaim_full24_20260427.json`, `tmp\research_runs\coverage_scan_breakout_full24_20260427.json`, `tmp\research_runs\coverage_scan_reversal_session_full24_20260427.json`
- Candidates tested: `14`
- Main result: broad entries generally had fold coverage, but were negative across the basket.
- Least-bad coverage branch: `coverage_v2_moderate_active_time16`
- OOS: `trades=94`, `net_total_r=2.5867`, `net_avg_r=0.0275`, `pf=1.0595`, `max_drawdown_r=8.3483`
- Fold coverage: `5 of 5` folds had trades, but only `2 of 5` folds were net positive.
- Promoted strategies: `none`


### Research campaign 2026-04-27T20:27:32Z

- Status: `done`
- Scope: `coverage-refinement`
- Diagnostic artifact: `tmp\research_runs\coverage_diagnostics_v2_moderate_20260427.json`
- Refinement artifact: `tmp\research_runs\coverage_refinement_universe30_20260427.json`
- Strict universe size reached: `29` symbols
- Main result: removing or reducing New York exposure improved the moderate `v2_reclaim` branch, but made it too sparse and still fold-unstable.
- Top candidate: `coverage_v2_moderate_10_16_funding_m2_p1`
- Top OOS: `trades=44`, `net_total_r=9.1401`, `net_avg_r=0.2077`, `pf=1.5468`, `max_drawdown_r=2.9884`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Promoted strategies: `none`


### Research campaign 2026-04-27T21:05:00Z

- Status: `done`
- Scope: `coverage-short-trend`
- Artifact: `tmp\research_runs\coverage_short_trend_universe30_20260427.json`
- Candidates tested: `5`
- Main result: short-side trend mirrors had strong coverage, but were negative overall and failed holdout.
- Top candidate: `coverage_short_donchian80_active_time16`
- Top OOS: `trades=2850`, `net_total_r=-194.1106`, `net_avg_r=-0.0681`, `pf=0.7701`
- Fold note: short trend helped fold `1`, but still lost fold `2`, fold `5`, and holdout.
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Promoted strategies: `none`

### Research campaign 2026-04-27T17:33:57Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\coverage_scan_trend_reclaim_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `5`
- Top candidate: `coverage_v2_moderate_active_time16`
- Top OOS: `trades=94`, `net_total_r=2.5867`, `net_avg_r=0.0275`, `pf=1.0595`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `net_avg_r<0.1=5, profit_factor<1.25=5, folds_positive<4=5, holdout_net_avg_r<0.05=4, max_drawdown_r>10.0=4`
- Promoted strategies: `none`


### Research campaign 2026-04-27T17:41:27Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\coverage_scan_breakout_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `5`
- Top candidate: `coverage_donchian80_active_time16`
- Top OOS: `trades=1617`, `net_total_r=-83.8259`, `net_avg_r=-0.0518`, `pf=0.7989`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `net_avg_r<0.1=5, profit_factor<1.25=5, holdout_net_total_r<=0=5, holdout_net_avg_r<0.05=5, folds_positive<4=5`
- Promoted strategies: `none`


### Research campaign 2026-04-27T17:46:54Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\coverage_scan_reversal_session_full24_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, LDOUSDT, RAYUSDT, ZECUSDT, AXSUSDT, INJUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, SUIUSDT, XLMUSDT, LTCUSDT, NEARUSDT, ALGOUSDT, HBARUSDT, APTUSDT, SANDUSDT`
- Candidates tested: `4`
- Top candidate: `coverage_crash_rebound_loose_active`
- Top OOS: `trades=291`, `net_total_r=-62.8361`, `net_avg_r=-0.2159`, `pf=0.5245`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `net_avg_r<0.1=4, profit_factor<1.25=4, holdout_net_total_r<=0=4, holdout_net_avg_r<0.05=4, folds_positive<4=4`
- Promoted strategies: `none`


### Research campaign 2026-04-27T18:27:32Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\coverage_refinement_universe30_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TONUSDT, SUIUSDT, LDOUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, NEARUSDT, XLMUSDT, AXSUSDT, INJUSDT, HBARUSDT, UNIUSDT, DASHUSDT, APTUSDT, RAYUSDT, DOTUSDT, RUNEUSDT, BCHUSDT, ALGOUSDT, FILUSDT`
- Candidates tested: `5`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `coverage_v2_moderate_10_16_funding_m2_p1`
- Top OOS: `trades=44`, `net_total_r=9.1401`, `net_avg_r=0.2077`, `pf=1.5468`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=5, folds_positive<4=5, net_avg_r<0.1=2, profit_factor<1.25=2, holdout_net_total_r<=0=2`
- Promoted strategies: `none`


### Research campaign 2026-04-27T18:46:47Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\coverage_short_trend_universe30_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TONUSDT, SUIUSDT, TRXUSDT, LDOUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, NEARUSDT, XLMUSDT, AXSUSDT, INJUSDT, HBARUSDT, UNIUSDT, DASHUSDT, APTUSDT, RAYUSDT, DOTUSDT, BCHUSDT, RUNEUSDT, ALGOUSDT, FILUSDT`
- Candidates tested: `5`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `coverage_short_donchian80_active_time16`
- Top OOS: `trades=2850`, `net_total_r=-194.1106`, `net_avg_r=-0.0681`, `pf=0.7701`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `net_avg_r<0.1=5, profit_factor<1.25=5, holdout_net_total_r<=0=5, holdout_net_avg_r<0.05=5, folds_positive<4=5`
- Promoted strategies: `none`

### Research campaign 2026-04-27T19:21:57Z

- Status: `done`
- Scope: `fold-regime-diagnostics`
- Artifact: `tmp\research_runs\fold_regime_diagnostics_20260427.json`
- Main result: fold `2` is a broad risk-off regime, not just a weak candidate pocket.
- Fold 2 market: `BTC=-13.7453%`, basket median `=-14.9692%`, symbols positive/negative `0/29`, BTC max drawdown `=-23.9004%`.
- Fold 2 derivatives context: median funding `=-0.1407bps`, funding panic share `=2.0877%`, median 24h OI value change `=-1.3229%`, taker buy pressure share `=49.3288%`.
- Session note: fold 2 BTC London/overlap was slightly positive, while New York and off-hours carried the main downside.
- Promoted strategies: `none`

### Research campaign 2026-04-27T19:21:57Z

- Status: `done`
- Scope: `fold2-risk-off-short`
- Artifact: `tmp\research_runs\fold2_risk_off_short_universe30_20260427.json`
- Candidates tested: `8`
- Universe: strict Binance spot `30` symbols.
- Main result: risk-off short entries targeting New York/off-hours with BTC-down and OI-cooling gates failed; the answer is not simple directional shorting.
- Top candidate: `fold2_short_donchian80_offhours_oi_cooling`
- Top OOS: `trades=359`, `net_total_r=-16.5786`, `net_avg_r=-0.0462`, `pf=0.7353`, `max_drawdown_r=26.4022`
- Fold note: top variant still lost fold `2` (`trades=92`, `net_total_r=-12.4828`); `fold2_short_donchian80_ny_sell_pressure` nearly flattened fold `2` (`-0.0698R`) but failed badly OOS and holdout.
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Promoted strategies: `none`


### Research campaign 2026-04-27T19:21:26Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\fold2_risk_off_short_universe30_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TONUSDT, SUIUSDT, TRXUSDT, ADAUSDT, LDOUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, NEARUSDT, AXSUSDT, XLMUSDT, INJUSDT, HBARUSDT, UNIUSDT, DASHUSDT, APTUSDT, RAYUSDT, DOTUSDT, BCHUSDT, RUNEUSDT, ALGOUSDT, FILUSDT, RENDERUSDT`
- Candidates tested: `8`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `fold2_short_donchian80_offhours_oi_cooling`
- Top OOS: `trades=359`, `net_total_r=-16.5786`, `net_avg_r=-0.0462`, `pf=0.7353`
- Top gate status: `fail`
- Top gate failures: `net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4, max_drawdown_r>10.0`
- Top gate failure counts: `net_avg_r<0.1=8, profit_factor<1.25=8, holdout_net_total_r<=0=8, holdout_net_avg_r<0.05=8, folds_positive<4=8`
- Promoted strategies: `none`


### Research campaign 2026-04-27T20:18:59Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_ai_scorecard_v2.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_v2_base_score7`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-27T20:19:19Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_risk_off_london_relief.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `risk_off_london_relief_base`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-27T21:08:16Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\next_research_batch_universe12_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TONUSDT, SUIUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, LDOUSDT`
- Candidates tested: `13`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_v2_base_score7`
- Top OOS: `trades=49`, `net_total_r=15.6721`, `net_avg_r=0.3198`, `pf=1.9884`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80`
- Top gate failure counts: `holdout_net_total_r<=0=10, holdout_net_avg_r<0.05=10, folds_positive<4=9, executed_trades<80=8, net_avg_r<0.1=8`
- Promoted strategies: `none`


### Research campaign 2026-04-27T22:31:05Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\ai_scorecard_v2_top2_universe30_20260427.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TONUSDT, TRXUSDT, SUIUSDT, ADAUSDT, AAVEUSDT, LDOUSDT, AVAXUSDT, LINKUSDT, LTCUSDT, NEARUSDT, XLMUSDT, AXSUSDT, INJUSDT, UNIUSDT, HBARUSDT, APTUSDT, DASHUSDT, RAYUSDT, DOTUSDT, BCHUSDT, ALGOUSDT, RUNEUSDT, FILUSDT`
- Candidates tested: `2`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_v2_base_score7`
- Top OOS: `trades=82`, `net_total_r=13.8474`, `net_avg_r=0.1689`, `pf=1.384`
- Top gate status: `pass`
- Top gate failures: `none`
- Top gate failure counts: `net_avg_r<0.1=1, profit_factor<1.25=1, folds_positive<4=1`
- Promoted strategies: `ai_score_v2_base_score7`

### Paper approval 2026-04-28

- Approved strategy: `ai_score_v2_base_score7`
- Mode: `manual gated paper trading`
- Runtime change: `SignalAssistant` now uses the approved scorecard as the active paper gate and can prefill paper orders only when all gates pass.
- Execution boundary: no auto execution, no live funds, and no private exchange API usage.

### Auto-paper approval 2026-04-28

- Approved strategy: `ai_score_v2_base_score7`
- Mode: `guarded automatic paper trading`
- Runtime change: auto-paper worker can place local paper market buys when the approved gate passes.
- Guardrails: one global auto slot, no BTC entries, no duplicate `strategy + symbol + signal_close_time`, max 3 auto entries per UTC day, 2% daily realized-loss kill switch, attached stop-loss / TP1, local SQLite ledger only.
- Execution boundary: no live funds and no private exchange API usage.

### Forward paper analytics 2026-04-28

- Tool: `scripts/forward_paper_report.py`
- Runtime change: auto-paper now records rejected technical-ready signals as `rejected` decisions and stores entry price, stop, TP, quantity, risk amount, and linked trade id for entered decisions.
- Report command: `python scripts\forward_paper_report.py --markdown-out tmp\forward_paper_report_latest.md --json-out tmp\forward_paper_report_latest.json`
- Current report state at implementation: no auto-paper decisions or trades logged yet because the market was still `WAIT`.

### Runtime/harness parity 2026-04-28

- Tool: `scripts/runtime_harness_parity.py`
- Scope: compares live `SignalAssistant` technical stage, AI score, and risk-plan availability against independent Python evaluation of `ai_score_v2_base_score7`.
- Initial check: `ETHUSDT,SOLUSDT` both passed parity with `technical_stage=wait`, `ai_score=0`, and no paper risk plan.
- Caveat: runtime news blackout is a live-only gate, so risk-plan mismatches can be legitimate when news blocks an otherwise passing technical/score setup.


### Research campaign 2026-04-28T09:19:52Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\ai_scorecard_v2_confirm_universe30_20260428.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, TONUSDT, ZECUSDT, TRXUSDT, SUIUSDT, ADAUSDT, AAVEUSDT, LINKUSDT, AXSUSDT, AVAXUSDT, LTCUSDT, APTUSDT, NEARUSDT, LDOUSDT, XLMUSDT, HBARUSDT, ARBUSDT, UNIUSDT, INJUSDT, DOTUSDT, BCHUSDT`
- Candidates tested: `1`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_v2_base_score7`
- Top OOS: `trades=83`, `net_total_r=13.838`, `net_avg_r=0.1667`, `pf=1.3837`
- Top gate status: `pass`
- Top gate failures: `none`
- Promoted strategies: `ai_score_v2_base_score7`


### Research campaign 2026-04-28T11:26:53Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_ai_scorecard_v2_ablation.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `13`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_v2_ablation_control_score7`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=13, executed_trades<80=13, net_avg_r<0.1=13, profit_factor<1.25=13, holdout_net_total_r<=0=13`
- Promoted strategies: `none`

### Research handoff 2026-04-28

- Status: `interrupted`
- Scope: `ai_scorecard_v2_ablation_full_run`
- Completed before interruption: ablation implementation, tests, docs, and smoke run.
- Completed artifact: `tmp\research_runs\smoke_ai_scorecard_v2_ablation.json`
- Missing artifact: `tmp\research_runs\ai_scorecard_v2_ablation_universe30_20260428.json`
- Reason: the full 30-symbol ablation pass was force-stopped before completion.
- Handoff file: `docs\research-handoff-2026-04-28.md`
- Next command: `python scripts\research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 4 --json-out tmp\research_runs\ai_scorecard_v2_ablation_universe30_20260428.json`

### Research campaign 2026-04-28T15:25:25Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\ai_scorecard_v2_ablation_universe30_20260428.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, TONUSDT, ZECUSDT, TRXUSDT, SUIUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, AXSUSDT, LTCUSDT, APTUSDT, LDOUSDT, NEARUSDT, XLMUSDT, RAYUSDT, UNIUSDT, ARBUSDT, HBARUSDT, DOTUSDT`
- Candidates tested: `13`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_v2_ablate_oi`
- Top OOS: `trades=86`, `net_total_r=17.739`, `net_avg_r=0.2063`, `pf=1.4703`
- Top gate status: `pass`
- Top gate failures: `none`
- Top gate failure counts: `executed_trades<80=10, folds_positive<4=8, net_avg_r<0.1=1, profit_factor<1.25=1`
- Promoted strategies: `ai_score_v2_ablate_oi`

Interpretation:

- The OI ablation was the only ablation variant to pass the full harness gates: `86` OOS trades, `17.739R` net, `0.2063R` average, `pf=1.4703`, `max_drawdown=6.0666R`, holdout `7.9801R`, holdout average `0.1773R`, `4/5` positive folds, symbol concentration `15.36%`, and single-trade concentration `2.64%`.
- The control remained strong but failed the trade-count gate with `77` trades, so the OI component appears to be over-filtering or adding noise in this run.
- This does not change the active runtime strategy. `ai_score_v2_base_score7` remains the only approved gated paper strategy unless `ai_score_v2_ablate_oi` is confirmed in a focused run and explicitly approved.


### Research campaign 2026-04-28T15:46:09Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\ai_scorecard_v2_ablate_oi_confirm_universe30_20260428.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT, TONUSDT, ZECUSDT, TRXUSDT, SUIUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LINKUSDT, AXSUSDT, LTCUSDT, APTUSDT, LDOUSDT, NEARUSDT, XLMUSDT, RAYUSDT, UNIUSDT, ARBUSDT, HBARUSDT, DOTUSDT`
- Candidates tested: `1`
- Top candidate: `ai_score_v2_ablate_oi`
- Top OOS: `trades=86`, `net_total_r=17.739`, `net_avg_r=0.2063`, `pf=1.4703`
- Top gate status: `pass`
- Top gate failures: `none`
- Promoted strategies: `ai_score_v2_ablate_oi`

Interpretation:

- Focused confirmation reproduced the ablation pass exactly on the explicit 24-symbol universe: `86` OOS trades, `17.739R` net, `0.2063R` average, `pf=1.4703`, `max_drawdown=6.0666R`, holdout `7.9801R`, holdout average `0.1773R`, `4/5` positive folds, symbol concentration `15.36%`, and single-trade concentration `2.64%`.
- `ai_score_v2_ablate_oi` is now a confirmed promotion-gate pass in the research harness. It should be added only as a paper-only secondary bot with the existing guardrails, not as live execution.

### Secondary paper bot implementation 2026-04-28

- Status: `implemented`
- Strategy: `ai_score_v2_ablate_oi`
- Scope: secondary guarded paper bot beside primary `ai_score_v2_base_score7`
- Runtime behavior: evaluates both paper strategies from the same market/context snapshot; auto-paper still uses one shared global slot, daily caps, idempotency by `strategy_version + symbol + signal_close_time`, local SQLite fills, attached stop-loss / TP1, and no live exchange execution.
- Difference from primary: secondary ignores the OI-change score component to match the confirmed harness candidate.
- UI/API: dashboard now returns `secondary_signal_assistants` and displays the secondary paper bot state for the selected symbol.
- Reporting: forward paper report now includes strategy counts and strategy versions for decisions/trades.
- Parity: `scripts\runtime_harness_parity.py` accepts `--strategy ai_score_v2_ablate_oi`.

### Predictive meta-model diagnostic 2026-04-29

- Status: `done`
- Scope: `event_dataset_latest_diagnostic`
- Artifacts: `tmp\research_runs\event_dataset_latest.json`, `tmp\research_runs\predictive_meta_model_event_dataset_latest.json`
- Dataset: `524` events, `87840` metric rows, `24` symbols, `3` source candidates
- Baseline event surface: `trades=524`, `net_total_r=-0.7055`, `net_avg_r=-0.0013`, `pf=0.9972`, `max_drawdown=46.6536R`
- Best blocked CV filter: `blocked_cv_keep_0.25` with `trades=136`, `net_total_r=10.6911`, `net_avg_r=0.0786`, `pf=1.1694`, `max_drawdown=14.0524R`
- Strongest diagnostic rules:
  - `rule_global_account_lte_1.20`: `trades=109`, `net_total_r=27.3078`, `net_avg_r=0.2505`, `pf=1.6025`, `max_drawdown=8.7569R`
  - `rule_funding_not_panic_and_taker_buy`: `trades=242`, `net_total_r=47.4988`, `net_avg_r=0.1963`, `pf=1.4896`, `max_drawdown=14.4312R`
  - `rule_taker_buy_sell_ge_1.25`: `trades=286`, `net_total_r=35.7041`, `net_avg_r=0.1248`, `pf=1.2983`, `max_drawdown=15.8406R`

Interpretation:

- The pooled event surface remains weak without filtering, so the model does not justify a runtime or paper-trading change.
- The global-account rule is the most interesting diagnostic because it clears the aggregate avg-R, PF, trade-count, drawdown, symbol concentration, and single-trade concentration thresholds, but it is not a promotion-protocol run and has sparse/unstable chronological segments, including no segment-04 trades and a weak segment-12.
- The funding-not-panic plus taker-buy rule has the strongest raw net, but drawdown remains above the promotion limit and late segments are unstable.
- Next bounded research step: convert these diagnostics into a normal harness candidate family around global-account bias <= `1.20`, taker-buy pressure >= `1.25`, funding-not-panic, and combinations/session gates, then require the full promotion gates before any paper bot change.
- Runtime status unchanged: `ai_score_v2_base_score7` remains primary and `ai_score_v2_ablate_oi` remains secondary, both paper-only.

### Event rule filter family implementation 2026-04-29

- Status: `running`
- Scope: `event_rule_filters_harness_family`
- Family: `event_rule_filters`
- Candidate count: `14`
- Source: predictive meta-model diagnostics from `tmp\research_runs\predictive_meta_model_event_dataset_latest.json`
- Filters tested: global account long/short <= `1.20`, taker buy/sell >= `1.25`, funding >= `-0.9999 bps`, combinations, `10-16 UTC` dampeners, London/overlap dampener, and base/moderate/no-correlation v2 reclaim variants.
- Runtime impact: none. This is harness-only research; active paper setup remains `ai_score_v2_base_score7` primary and `ai_score_v2_ablate_oi` secondary.
- Validation so far: `python -m py_compile ...`, `python scripts\test_research_harness.py`, and smoke run `tmp\research_runs\smoke_event_rule_filters_all.json` passed.
- Background command: `python scripts\research_harness.py --candidate-family event_rule_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\event_rule_filters_universe30_20260429.json`
- Background PID: `31856`
- Logs: `tmp\research_runs\event_rule_filters_universe30_20260429.stdout.log`, `tmp\research_runs\event_rule_filters_universe30_20260429.stderr.log`
- Heartbeat: `check-event-rule-filter-run`


### Research campaign 2026-04-29T06:02:11Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_event_rule_filters.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `event_rule_v2_base_global_lte120`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`


### Research campaign 2026-04-29T06:02:34Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_event_rule_filters_all.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `14`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `event_rule_v2_base_global_lte120`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=14, executed_trades<80=14, net_avg_r<0.1=14, profit_factor<1.25=14, holdout_net_total_r<=0=14`
- Promoted strategies: `none`

### Research campaign 2026-04-29T08:44:01Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\event_rule_filters_universe30_20260429.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TRXUSDT, SUIUSDT, ADAUSDT, AAVEUSDT, AVAXUSDT, LTCUSDT, LINKUSDT, XLMUSDT, AXSUSDT, NEARUSDT, APTUSDT, UNIUSDT, ARBUSDT`
- Candidates tested: `14`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `event_rule_v2_base_global_lte120`
- Top OOS: `trades=31`, `net_total_r=15.4676`, `net_avg_r=0.499`, `pf=2.7134`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4, symbol_concentration>0.4`
- Top gate failure counts: `folds_positive<4=13, executed_trades<80=12, symbol_concentration>0.4=10, holdout_net_avg_r<0.05=4, holdout_net_total_r<=0=3`
- Promoted strategies: `none`
Interpretation:

- No `event_rule_filters` candidate passed the promotion gates, so there is no paper-bot or runtime change.
- The cleanest result was `event_rule_v2_base_global_lte120`: `31` OOS trades, `15.4676R` net, `0.499R` average, `pf=2.7134`, `max_drawdown=2.3784R`, and holdout `9.2679R`. It failed because it was too sparse, had only `3/5` positive folds, and symbol concentration was too high at `52.11%`.
- `event_rule_v2_base_funding_taker` was the closest coverage candidate with `76` trades, `9.2051R` net, `0.1211R` average, `pf=1.3122`, `max_drawdown=4.0306R`, and `4/5` positive folds, but holdout was slightly negative (`-0.0948R`) and trade count was still below `80`.
- `event_rule_v2_base_taker_ge125` reached `87` trades but failed quality gates (`0.0688R` average, `pf=1.1656`, holdout average `0.0447R`, and `3/5` positive folds).
- The diagnostic filters improved trade quality but remain either too sparse/concentrated or too weak when broadened. Treat global-account bias <= `1.20` as a useful scorecard feature, not a standalone strategy promotion.

### AI scorecard global sweep implementation 2026-04-29

- Status: `running`
- Scope: `ai_scorecard_v2_global_sweep`
- Candidate count: `14`
- Source: `event_rule_filters` showed global-account bias improves quality but is too sparse as a standalone rule.
- Filters tested: score threshold `6`/`7`, global account long/short caps `1.20`, `1.35`, and `1.50`, OI ablation, and top-trader-position cap `1.60`.
- Runtime impact: none. This is harness-only research; active paper setup remains `ai_score_v2_base_score7` primary and `ai_score_v2_ablate_oi` secondary.
- Validation so far: `python -m py_compile ...`, `python scripts\test_research_harness.py`, and smoke run `tmp\research_runs\smoke_ai_scorecard_v2_global_sweep.json` passed.
- Background command: `python scripts\research_harness.py --candidate-family ai_scorecard_v2_global_sweep --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\ai_scorecard_v2_global_sweep_universe30_20260429.json`
- Background PID: `40976`
- Logs: `tmp\research_runs\ai_scorecard_v2_global_sweep_universe30_20260429.stdout.log`, `tmp\research_runs\ai_scorecard_v2_global_sweep_universe30_20260429.stderr.log`
- Heartbeat: `check-scorecard-global-sweep`

### Runtime telemetry archive implementation 2026-04-29

- Status: `implemented`
- Scope: `runtime-data-infrastructure`
- Runtime impact: analysis-only collection; no paper strategy change and no live exchange execution
- SQLite tables added: `telemetry_market_tickers`, `telemetry_candles`, `telemetry_funding_rates`, `telemetry_futures_metric_rows`, `telemetry_signal_evaluations`
- Default cadence: `RUNTIME_TELEMETRY_INTERVAL_SECONDS=900`
- Default candle archive: `1m`, `15m`, `1h`, `4h` with `RUNTIME_TELEMETRY_CANDLE_LIMIT=240`
- Signal archive: persists `SignalAssistant` snapshots from dashboard and auto-paper evaluations, including stage, technical stage, AI score, failed checks, checklist JSON, warnings, tags, and risk-plan fields when present
- Purpose: preserve enough runtime market and scorecard context for future forward-analysis without relying only on disposable `tmp` research caches


### Research campaign 2026-04-29T08:50:50Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_ai_scorecard_v2_global_sweep.json`
- Universe: `BTCUSDT, ETHUSDT, TONUSDT`
- Candidates tested: `14`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_global_base_s6_g120`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=14, executed_trades<80=14, net_avg_r<0.1=14, profit_factor<1.25=14, holdout_net_total_r<=0=14`
- Promoted strategies: `none`

### Research campaign 2026-04-29T10:17:30Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\ai_scorecard_v2_global_sweep_universe30_20260429.json`
- Universe: `BTCUSDT, ETHUSDT, TONUSDT, SOLUSDT, XRPUSDT, BNBUSDT, ZECUSDT, TRXUSDT, ADAUSDT, AAVEUSDT, SUIUSDT, XLMUSDT, AVAXUSDT, APTUSDT, LTCUSDT, LINKUSDT, AXSUSDT, NEARUSDT, UNIUSDT`
- Candidates tested: `14`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `ai_score_global_oi_s7_g150_toppos160`
- Top OOS: `trades=26`, `net_total_r=20.1227`, `net_avg_r=0.7739`, `pf=6.5461`
- Top gate status: `fail`
- Top gate failures: `executed_trades<80, folds_positive<4`
- Top gate failure counts: `executed_trades<80=14, folds_positive<4=14, symbol_concentration>0.4=5`
- Promoted strategies: `none`

Interpretation:

- No `ai_scorecard_v2_global_sweep` candidate passed the promotion gates, so there is no paper-bot or runtime change.
- The best candidate, `ai_score_global_oi_s7_g150_toppos160`, had excellent quality but only `26` OOS trades: `20.1227R` net, `0.7739R` average, `pf=6.5461`, `max_drawdown=1.3108R`, holdout `8.5304R`, and `3/5` positive folds.
- The broader best score-6 branch, `ai_score_global_oi_s6_g150`, reached only `39` trades with `14.445R` net, `0.3704R` average, `pf=2.0779`, `max_drawdown=5.0478R`, holdout `7.5347R`, and `3/5` positive folds.
- Global-account and top-position caps are useful quality filters, but in this sweep they removed too much coverage and left fold gaps. Treat them as research diagnostics, not a promotion candidate.

### Runtime telemetry report implementation 2026-04-29

- Status: `implemented`
- Scope: `runtime-forward-diagnostics`
- Script: `scripts\runtime_telemetry_report.py`
- Test: `scripts\test_runtime_telemetry_report.py`
- Outputs: `tmp\runtime_telemetry_report_latest.md`, `tmp\runtime_telemetry_report_latest.json`
- Purpose: summarize runtime telemetry coverage, market breadth, futures data freshness, `SignalAssistant` stages, failed gates, blocked READY setups, auto-paper decisions, and paper trade outcomes.

### Public news/event diagnostics implementation 2026-04-29

- Status: `implemented`
- Scope: `news-aware-research-infrastructure`
- Runtime impact: none; active paper setup remains `ai_score_v2_base_score7` primary and `ai_score_v2_ablate_oi` secondary
- SQLite table added: `telemetry_news_events`
- Scripts: `scripts\news_event_collector.py`, `scripts\news_event_impact_dataset.py`
- Tests: `scripts\test_news_event_collector.py`, `scripts\test_news_event_impact_dataset.py`
- Latest collection output: `tmp\news_event_collection_latest.md`, `tmp\news_event_collection_latest.json`
- Latest impact output: `tmp\news_event_impact_latest.md`, `tmp\news_event_impact_latest.json`
- First collection: `145` public RSS events, with `regulatory=63`, `general_news=53`, `macro_policy=11`, `fund_flow=8`, `security_incident=6`, `protocol_upgrade=2`, `market_structure=1`, and `token_unlock=1`
- First impact pass: `211` event-symbol rows. The only positive 60-minute bucket in the small sample was `macro_policy` (`16` samples, `+0.198%` average, `68.75%` positive). Generic, regulatory, security, and fund-flow buckets were weak/noisy. This is hypothesis generation only and does not justify paper promotion.

### Reboot-safe research data service 2026-04-30

- Status: `implemented`
- Scope: `reboot-safe-research-foundation`
- Runtime impact: none; active paper setup remains `ai_score_v2_base_score7` primary and `ai_score_v2_ablate_oi` secondary
- Compose service: `news-events`
- Service script: `scripts\news_event_service.py`
- Default cadence: `NEWS_EVENT_INTERVAL_SECONDS=900`
- Default RSS limit: `NEWS_EVENT_COLLECTOR_LIMIT_PER_SOURCE=50`
- Default impact lookback: `NEWS_EVENT_IMPACT_SINCE_HOURS=168`
- Cycle commands: public RSS collector, news-event impact dataset, runtime telemetry report
- Boundary: research-only; no `/api/paper/*` calls, no forced trades, no candidate promotion
- Next planned research layer: market-memory dataset, then harness-only higher-coverage candidates, then promotion only if gates pass and user explicitly approves.

### Market-memory dataset implementation 2026-04-30

- Status: `implemented`
- Scope: `market-memory-research-diagnostics`
- Runtime impact: none; active paper setup remains `ai_score_v2_base_score7` primary and `ai_score_v2_ablate_oi` secondary
- Script: `scripts\market_memory_dataset.py`
- Test: `scripts\test_market_memory_dataset.py`
- Outputs: `tmp\market_memory_latest.md`, `tmp\market_memory_latest.json`
- Sidecar refresh: `scripts\news_event_service.py` now refreshes market memory each cycle
- Feature surface: BTC cycle/halving phase, session/day/month, BTC regime, 1h/4h returns, futures bias, OI change, market-wide and symbol-specific news proximity, signal context, paper-decision context, and forward returns
- Boundary: diagnostic dataset only; no candidate promotion and no paper strategy change
- SQLite compatibility note: runtime DB journal mode now uses `DELETE` instead of WAL so the Rust app and Python sidecar can share the Docker Desktop/Windows bind-mounted database.

### Market-memory harness candidate implementation 2026-04-30

- Status: `implemented`
- Scope: `market_memory_filters`
- Candidate count: `14`
- Runtime impact: none; active paper setup remains `ai_score_v2_base_score7` primary and `ai_score_v2_ablate_oi` secondary
- Research intent: convert the diagnostic market-memory surface into bounded harness candidates before considering any runtime or paper-bot change
- Filters tested: BTC 24h neutral return band, active/London/New York sessions, basket breadth `30%` to `70%`, global-account long/short cap `1.20`, funding-not-panic, taker pressure >= `1.10`, score thresholds `5`/`6`/`7`, and OI-ablation variants
- Boundary: harness-only; no candidate can be paper traded unless it later passes the full promotion gates and the user explicitly approves promotion
- Smoke command: `python scripts\research_harness.py --smoke --candidate-family market_memory_filters --workers 2 --json-out tmp\research_runs\smoke_market_memory_filters.json`
- Full command: `python scripts\research_harness.py --candidate-family market_memory_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp\research_runs\market_memory_filters_universe30_20260430.json`

### Research campaign 2026-04-30T11:39:41Z

- Status: `done`
- Scope: `4-week-profitability-campaign`
- Artifact: `tmp\research_runs\smoke_market_memory_filters.json`
- Universe: `BTCUSDT, ETHUSDT, SOLUSDT`
- Candidates tested: `6`
- Universe filter: `profile=strict`, `min_quote_volume=5000000.0`
- Top candidate: `memory_v2_base_neutral_s5`
- Top OOS: `trades=0`, `net_total_r=0`, `net_avg_r=0.0`, `pf=0.0`
- Top gate status: `fail`
- Top gate failures: `not_full_12000_candle_walk_forward, executed_trades<80, net_avg_r<0.1, profit_factor<1.25, holdout_net_total_r<=0, holdout_net_avg_r<0.05, folds_positive<4`
- Top gate failure counts: `not_full_12000_candle_walk_forward=6, executed_trades<80=6, net_avg_r<0.1=6, profit_factor<1.25=6, holdout_net_total_r<=0=6`
- Promoted strategies: `none`
