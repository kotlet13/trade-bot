# Trade Bot Starter

Lokalna spletna aplikacija za spremljanje javnih Binance market podatkov in rocni paper trading.

Ta repozitorij je trenutno `paper-trading MVP`:

- uporablja javni Binance market feed
- hrani stanje lokalno v SQLite bazi `data/tradebot.db`
- nima private API kljucev
- nima live executiona na borzi

## Quick start

Zagon:

```bash
docker compose up --build
```

Odpri:

`http://localhost:8081`

Za zagon v ozadju:

```bash
docker compose up -d --build
```

Container ima nastavljen `restart: unless-stopped`, zato se po ponovnem zagonu Docker engine-a znova zazene, dokler ga ne ustavis z `docker compose stop` ali `docker compose down`.

Compose zazene tudi `news-events` research sidecar. Ta vsakih 15 minut osvezi public RSS event archive in lokalne diagnosticne reporte, vendar ne klice trading API-jev in ne oddaja paper orderjev.

## Kaj zna danes

- watchlist za strict promoted-research universe, vkljucno z `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `XRPUSDT`, `BNBUSDT`
- candle chart na intervalih `1m`, `5m`, `15m`, `1h`, `4h`
- signal assistant za izbran simbol:
    - `4h` trend filter
    - active gated paper strategies: primary `ai_score_v2_base_score7`, secondary `ai_score_v2_ablate_oi`
    - base reclaim state machine: `WAIT -> STALK -> SETUP -> READY`
    - `STALK`: cena je blizu `1h` supporta, vendar se ni zaprt reclaim
    - `SETUP`: zadnja zaprta `1h` svecka reclaim-a support
    - `READY`: sele po `1h` reclaimu pride se zaprt `15m` momentum trigger
  - `session` gate za nove entryje (`07:00-22:00 UTC`)
  - `ai_score_v2` paper gate s funding, futures positioning, fee-drag, volume, ATR, BTC, basket breadth in relative-strength preverjanji
  - BTC correlation diagnostika proti `BTCUSDT`
  - `news blackout` gate prek javnih `BEA`, `Fed`, `SEC` in `CoinDesk` virov brez prijave
  - predlagan `entry / stop / TP1 / TP2 / qty` za rocni paper workflow brez auto executiona
- replay/backtest za signal assistant:
    - pregled zadnjih `15m` signalov za izbran simbol
  - session in BTC correlation gate v replay porocilu
  - v2 reclaim replay uporablja samo zaprte `4h`, `1h` in `15m` svecke, zato 15m trigger ne more prehiteti 1h reclaim-a
  - TP1 win rate, `avg R`, `total R`
  - recent replay primeri z outcome in trajanje setupa
- rocni `market` in `limit` paper orderji
- stop-loss in take-profit na long paper entryjih
- guarded auto-paper worker: privzeto izklopljen, ena globalna auto pozicija naenkrat, najvec 3 auto entryji na UTC dan, 2% dnevni realized-loss kill switch
    - oba paper bota uporabljata isti lokalni SQLite paper executor in isti globalni slot
    - duplicate same-symbol/same-signal entries across primary and secondary are blocked unless explicitly enabled
- virtualni cash, pozicije, odprti orderji in PnL
- trade log z notes in lokalno persistenco v SQLite
- runtime telemetry archive v SQLite: recent tickerji, `1m/15m/1h/4h` svecke, USD-M funding, futures positioning metric rows, in `SignalAssistant` scorecard snapshots
- public news/event archive v SQLite za raziskovalne diagnostike, brez vpliva na aktivne paper gate-e

## Kaj se ne dela se

- live Binance execution
- uporaba private API kljucev
- testnet integracija
- vec-uporabniski access model
- partner-level capital ledger v sami aplikaciji
- live/testnet auto execution iz signal assistant modula
- robusten event-driven backtest engine z exchange fill modelom
- zgodovinski `news` replay ali economic-calendar feed z event revision logiko

## HTTP surface

Trenutni backend endpointi:

- `GET /health`
- `GET /api/dashboard`
  - vrne tudi `signal_assistant` in `secondary_signal_assistants` za izbrani simbol
- `GET /api/replay`
  - vrne zgodovinski replay signal assistant logike za izbrani simbol
- `POST /api/paper/orders`
- `POST /api/paper/orders/:id/cancel`
- `POST /api/paper/reset`

## Konfiguracija

Okoljske spremenljivke:

- `APP_HOST=0.0.0.0`
- `APP_PORT=3000`
- `DATA_DIR=/data`
- `WATCHLIST=<promoted universe; glej docker-compose.yml za privzeti polni seznam>`
- `STARTING_CASH=10000`
- `PAPER_FEE_BPS=10`
- `DEFAULT_INTERVAL=1m`
- `AUTO_PAPER_TRADING=false` by default in Compose; set `true` only when intentionally enabling guarded local paper entries
- `AUTO_PAPER_INTERVAL_SECONDS=60`
- `AUTO_PAPER_MAX_OPEN_SLOTS=1`
- `AUTO_PAPER_ALLOW_MULTI_STRATEGY_SAME_SIGNAL=false`
- `AUTO_PAPER_MAX_DAILY_ENTRIES=3`
- `AUTO_PAPER_MAX_DAILY_LOSS_PERCENT=2`
- `RUNTIME_TELEMETRY_ENABLED=true`
- `RUNTIME_TELEMETRY_INTERVAL_SECONDS=900`
- `RUNTIME_TELEMETRY_CANDLE_LIMIT=240`
- `RUNTIME_TELEMETRY_FUTURES_ENABLED=true`
- `RUNTIME_TELEMETRY_SIGNAL_EVALUATIONS=true`
- `NEWS_EVENT_INTERVAL_SECONDS=900`
- `NEWS_EVENT_COLLECTOR_LIMIT_PER_SOURCE=50`
- `NEWS_EVENT_IMPACT_SINCE_HOURS=168`
- `NEWS_EVENT_MARKET_MEMORY_SINCE_HOURS=168`

Docker Compose mapira `8081:3000`, zato je aplikacija lokalno dosegljiva na `http://localhost:8081`.

Forward paper report:

```bash
python scripts/forward_paper_report.py --markdown-out tmp/forward_paper_report_latest.md --json-out tmp/forward_paper_report_latest.json
```

Daily paper diagnostics:

```bash
python scripts/daily_paper_diagnostics.py
```

This orchestrates the forward paper report, runtime telemetry report, runtime/harness parity for both active strategies, and the optional market-memory report when the DB has the required telemetry. It is read-only and does not call `/api/paper/*`.

Runtime telemetry report:

```bash
python scripts/runtime_telemetry_report.py --markdown-out tmp/runtime_telemetry_report_latest.md --json-out tmp/runtime_telemetry_report_latest.json
```

News/event diagnostics:

```bash
python scripts/news_event_collector.py --markdown-out tmp/news_event_collection_latest.md --json-out tmp/news_event_collection_latest.json
python scripts/news_event_impact_dataset.py --markdown-out tmp/news_event_impact_latest.md --json-out tmp/news_event_impact_latest.json
python scripts/market_memory_dataset.py --markdown-out tmp/market_memory_latest.md --json-out tmp/market_memory_latest.json
```

The `news-events` sidecar runs these diagnostics automatically. Manual runs are useful for spot checks. The collector uses public RSS sources and a deterministic classifier to store news/event rows in `telemetry_news_events`. The impact dataset joins those rows to archived telemetry candles. The market-memory dataset adds BTC regime, session/calendar, futures bias, market-wide and symbol-specific news proximity, signal, and paper-decision context. These commands are research-only and do not alter active paper strategies.

Future research sequence:

1. collect durable market/news telemetry
2. build market-memory features from collected data
3. test higher-coverage candidates in the harness
4. promote nothing unless all gates pass and the user explicitly approves paper trading

Market-memory harness research:

```bash
python scripts/research_harness.py --smoke --candidate-family market_memory_filters --workers 2 --json-out tmp/research_runs/smoke_market_memory_filters.json
python scripts/research_harness.py --candidate-family market_memory_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp/research_runs/market_memory_filters_universe30_latest.json
```

The `market_memory_filters` family is harness-only. It converts the diagnostic market-memory layer into bounded candidates around BTC 24h regime, London/New York sessions, basket breadth, derivatives positioning, funding/taker pressure, and scorecard/OI-ablation variants. It does not change active paper strategies.

Regime-abstention and relative-strength research:

```bash
python scripts/research_harness.py --candidate-family regime_abstention_filters --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp/research_runs/regime_abstention_filters_universe30_latest.json
python scripts/research_harness.py --candidate-family relative_strength_refinement --trigger-limit 12000 --universe-limit 30 --workers 2 --json-out tmp/research_runs/relative_strength_refinement_universe30_latest.json
```

These families are harness-only. Backtests are hypothesis filters, not proof. Forward-paper results are the main evidence before any testnet discussion, and no strategy promotion is allowed without promotion gates plus explicit user approval.

Strict fill research mode:

```bash
python scripts/research_harness.py --smoke --strict-fills --candidate-family runtime_exit_parity --workers 2 --json-out tmp/research_runs/smoke_runtime_exit_strict_fills.json
```

`--strict-fills` adds conservative research-only entry, stop, and take-profit slippage/touch assumptions. `--no-slippage` preserves legacy fill behavior.

Runtime/harness parity check:

```bash
python scripts/runtime_harness_parity.py --strategy ai_score_v2_base_score7 --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp/runtime_harness_parity_base_latest.md --json-out tmp/runtime_harness_parity_base_latest.json
python scripts/runtime_harness_parity.py --strategy ai_score_v2_ablate_oi --symbols ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT --markdown-out tmp/runtime_harness_parity_oi_latest.md --json-out tmp/runtime_harness_parity_oi_latest.json
```

Scorecard ablation research:

```bash
python scripts/research_harness.py --smoke --candidate-family ai_scorecard_v2_ablation --max-candidates 99 --workers 2 --json-out tmp/research_runs/smoke_ai_scorecard_v2_ablation.json
python scripts/research_harness.py --candidate-family ai_scorecard_v2_ablation --trigger-limit 12000 --universe-limit 30 --workers 4 --json-out tmp/research_runs/ai_scorecard_v2_ablation_latest.json
```

## Dokumentacija

Podrobnejsa dokumentacija je v `docs/`:

- [Pregled in roadmap](docs/overview-roadmap.md)
- [Active paper strategy](docs/active-strategy.md)
- [Arhitektura in operativa](docs/architecture-ops.md)
- [Sodelovanje in capital ledger](docs/collaboration-capital.md)
