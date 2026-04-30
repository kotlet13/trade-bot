# Arhitektura in operativa

## Komponente sistema

Trenutna aplikacija ima pet osnovnih delov:

- Rust backend v `src/main.rs`
- static frontend v `static/`
- SQLite baza v `data/tradebot.db`
- Docker runtime preko `Dockerfile` in `docker-compose.yml`
- `news-events` Python sidecar za research-only public RSS event zbiranje

## Runtime flow

Zagon poteka takole:

1. aplikacija prebere environment konfiguracijo
2. inicializira mapo `DATA_DIR` in odpre SQLite bazo
3. backend izpostavi HTTP API na `APP_PORT`, privzeto `3000`
4. frontend se servira iz `static/`
5. UI ob osvezevanju klice backend, backend pa uporablja javne Binance endpointe za tickerje, cene in candles
6. paper orderji in pozicije se obdelujejo lokalno v SQLite bazi
7. runtime telemetry worker nizkofrekvencno arhivira javne market podatke za prihodnjo analizo
8. `news-events` sidecar vsakih `900` sekund osvezi public RSS event archive in lokalne diagnosticne reporte

## Trenutni HTTP API

### `GET /health`

Preprost healthcheck. Vrne `ok`.

### `GET /api/dashboard`

Vrne:

- watchlist
- izbran simbol in interval
- market tickerje
- candle podatke
- paper snapshot racuna, pozicij, orderjev in trade loga
- `signal_assistant` za izbrani simbol
  - primary paper strategy: `ai_score_v2_base_score7`
  - secondary paper strategy: `ai_score_v2_ablate_oi`
  - `4h` trend bias
  - base reclaim state machine: `WAIT -> STALK -> SETUP -> READY`
  - `STALK`: zaprt `1h` close je znotraj `0.5 ATR` od supporta, vendar se ni reclaim-a
  - `SETUP`: zaprt `1h` close reclaim-a support
  - `READY`: po `1h` reclaim-u se zapre se veljaven `15m` momentum trigger
  - `session` gate (`07:00-22:00 UTC`)
  - `ai_score_v2` gate (`score >= 7`) z fee drag, volume, ATR expansion, BTC return, basket breadth, relative strength, funding, OI, taker pressure, global bias, and top-trader position checks
  - secondary bot uporablja enake gate-e, vendar ignorira OI-change score component, ker je `ai_score_v2_ablate_oi` potrdil promotion-gate pass
  - `correlation` proti `BTCUSDT` je runtime diagnostika, ni promoted-entry gate
  - `news blackout` gate prek javnih `BEA`, `Fed`, `SEC` in `CoinDesk` virov
  - predlagan risk plan za rocni paper long setup; auto-paper uporablja isti gate, ce je izrecno vklopljen

Auto-paper worker:

- vklopi ga `AUTO_PAPER_TRADING=true`
- preverja promoted watchlist na `AUTO_PAPER_INTERVAL_SECONDS`
- uporablja `ai_score_v2_base_score7` in `ai_score_v2_ablate_oi` gate kot `SignalAssistant`
- odda samo lokalni paper market buy v SQLite ledger, brez exchange API-ja
- ima en globalni auto slot (`AUTO_PAPER_MAX_OPEN_SLOTS=1`)
- ne ponovi istega `strategy + symbol + signal_close_time` signala zaradi `auto_paper_decisions` idempotency tabele
- dnevni cap: `AUTO_PAPER_MAX_DAILY_ENTRIES`
- kill switch: blokira nove auto entryje, ko dnevni realized PnL pade pod `AUTO_PAPER_MAX_DAILY_LOSS_PERCENT`
- izhodi so se vedno lokalni price-triggerji na attached stop-loss / take-profit

### `GET /api/replay`

Vrne zgodovinski replay za izbrani simbol:

- stevilo `setup` in `ready` signalov
- session in BTC correlation vpliv v replay opombah
- `v2_reclaim_strategy` uporablja samo zaprte svecke, zato replay ne dovoli 15m triggerja pred 1h reclaim-om
- `TP1` win rate
- `average R` in `total R`
- breakdown: `TP2`, `stop loss`, `break-even`, `timeout`
- zadnje replay trade primere

Pomembna meja trenutne verzije:

- replay uporablja svecke in konzervativna pravila intrabar razresitve
- replay zdaj uposteva session in BTC correlation gate
- `news blackout` ostaja live-only, ker javni RSS viri niso zgodovinski replay dataset
- ni exchange-accurate fill simulator
- ni komisijskega/slippage modela za replay

Query parametra:

- `symbol`
- `interval`

### `POST /api/paper/orders`

Odda paper order.

Podprt payload:

- `symbol`
- `side`
- `order_kind`
- `quantity`
- `limit_price`
- `stop_loss`
- `take_profit`
- `note`

### `POST /api/paper/orders/:id/cancel`

Preklice odprt paper order.

### `POST /api/paper/reset`

Resetira paper account, pozicije, odprte orderje in trade log.

## Persistenca

Trenutna persistenca je lokalna:

- SQLite datoteka: `data/tradebot.db`
- volume mapping v Dockerju: `./data:/data`
- runtime nastavitev: `DATA_DIR=/data`

Runtime telemetry archive je locen od paper ledgerja in ne oddaja orderjev. Privzeto je vklopljen z `RUNTIME_TELEMETRY_ENABLED=true` in na vsakih `900` sekund upserta:

- `telemetry_market_tickers`: spot `24hr` snapshot za watchlist
- `telemetry_candles`: recent `1m`, `15m`, `1h`, `4h` svecke, `RUNTIME_TELEMETRY_CANDLE_LIMIT` po requestu
- `telemetry_funding_rates`: USD-M funding rows
- `telemetry_futures_metric_rows`: USD-M 5m open interest, global account long/short, top-position long/short, taker long/short rows
- `telemetry_signal_evaluations`: `SignalAssistant` snapshots, kadar jih runtime ze izracuna za dashboard ali auto-paper cycle
- `telemetry_news_events`: research-only public RSS event classifications for news-impact diagnostics

SQLite uporablja `DELETE` journal mode namesto WAL, da lahko Rust app in Python research sidecar zanesljivo delita isti bind-mounted DB na Docker Desktop/Windows. Skripte in app uporabljajo kratke busy timeoute; to je primerneje za lokalni nizkofrekvencni research workload kot locena baza.

Telemetry porocilo:

```powershell
python scripts\runtime_telemetry_report.py --markdown-out tmp\runtime_telemetry_report_latest.md --json-out tmp\runtime_telemetry_report_latest.json
```

News/event zbiranje in impact diagnostika:

```powershell
python scripts\news_event_collector.py --markdown-out tmp\news_event_collection_latest.md --json-out tmp\news_event_collection_latest.json
python scripts\news_event_impact_dataset.py --markdown-out tmp\news_event_impact_latest.md --json-out tmp\news_event_impact_latest.json
python scripts\market_memory_dataset.py --markdown-out tmp\market_memory_latest.md --json-out tmp\market_memory_latest.json
```

Collector uporablja javne RSS vire in deterministicen classifier. Impact script poveze dogodke z arhiviranimi `15m` sveckami in izracuna forward return po tipu dogodka, sentimentu in simbolu. Market-memory script zdruzi BTC regime, session/calendar, futures bias, market-wide in symbol-specific news proximity, signal, in paper-decision context. To je research-only infrastruktura in ne spreminja runtime paper gate-ov.

`news-events` sidecar:

- uporablja `restart: unless-stopped`, enako kot glavna aplikacija
- deli `./data` in `./tmp` volume z lokalnim repozitorijem
- izvaja `scripts/news_event_service.py`
- osvezuje news/event, market-memory, in telemetry report artefakte pod `tmp/`
- ne klice `/api/paper/*` endpointov in ne oddaja orderjev

Operativna posledica:

- stanje aplikacije je vezano na lokalni disk masina/container para
- backup in prenos stanja sta za zdaj rocna
- ni multi-user concurrency modela
- `tmp/research_cache` in `tmp/derivatives_cache` ostaneta raziskovalna cache-a; durable runtime archive je v `data/tradebot.db`

## Konfiguracija in deployment

Privzeta konfiguracija:

- `APP_HOST=0.0.0.0`
- `APP_PORT=3000`
- `DATA_DIR=/data`
- `WATCHLIST=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT`
- `STARTING_CASH=10000`
- `PAPER_FEE_BPS=10`
- `DEFAULT_INTERVAL=1m`
- `RUNTIME_TELEMETRY_ENABLED=true`
- `RUNTIME_TELEMETRY_INTERVAL_SECONDS=900`
- `RUNTIME_TELEMETRY_CANDLE_LIMIT=240`
- `RUNTIME_TELEMETRY_FUTURES_ENABLED=true`
- `RUNTIME_TELEMETRY_SIGNAL_EVALUATIONS=true`
- `NEWS_EVENT_INTERVAL_SECONDS=900`
- `NEWS_EVENT_COLLECTOR_LIMIT_PER_SOURCE=50`
- `NEWS_EVENT_IMPACT_SINCE_HOURS=168`
- `NEWS_EVENT_MARKET_MEMORY_SINCE_HOURS=168`

Lokalni dostop:

- Docker mapiranje: `8081:3000`
- URL: `http://localhost:8081`

Trenutni deployment model je `local-machine first`. To pomeni:

- aplikacija se za zdaj zaganja lokalno
- ne uvajata se se remote secrets ali managed infrastruktura
- vsak prihodnji prehod na testnet ali live mora najprej urediti secrets in audit meje

## Meje za naslednjo fazo

Pred testnet/live fazo mora arhitektura dobiti naslednje nove meje:

- jasen signal engine lifecycle
  - kdaj je signal samo informativen
  - kdaj lahko preide v semi-auto oddajo paper orderja
- replay/backtest meja
  - locena od live/paper execution logike
  - primerna za iteracijo pravil, ne za dokaz profitabilnosti
- `exchange adapter`, da execution ni vec zmesan s paper logiko
- runtime izbiro nacina: `paper`, `testnet`, kasneje `live`
- secrets handling izven repozitorija
- locen logging za exchange requeste in odgovore
- jasen kill-switch ali blokado tradinga

To so javni vmesniki, ki jih je smiselno uvesti pred prvim live rolloutom:

- konfiguracijski `mode`
- provider-specific secrets za testnet/mainnet
- account-scope policy, ki eksplicitno doloci dovoljeni wallet/account za bot

## Operativna pravila za live sredstva

Pred live rolloutom veljajo ta pravila:

- bot budget mora biti locen od osebnih sredstev, ki niso namenjena botu
- `sub-account` je privzeta resitev, ce jo dejanski Binance account podpira
- `Funding Wallet` ni dovolj mocna varnostna meja za bot sam po sebi
- withdrawal permission mora ostati izklopljen
- ena oseba je custodian racuna in kljucev

## Incident drill scenariji

### Drill 1: rotacija API kljuca

Ko se uvedejo private kljuci:

1. ustavi se oddaja novih orderjev
2. preveri se, ali so odprti orderji se vedno pod nadzorom
3. stari kljuc se deaktivira
4. nov kljuc se vnese v zunanji secrets store, ne v repo
5. healthcheck in testni request potrdita nov dostop
6. sele nato se ponovno dovoli execution

### Drill 2: blokada prehoda na live

Prehod na live se blokira, ce velja katerikoli od pogojev:

- sredstva niso locena od osebnega balance-a
- `sub-account` ni preverjen in ni definiran fallback
- withdrawal permission je vklopljen
- ni evidentiran owner API kljucev
- ni definiran kill-switch postopek

## Sprejemni check za dokument

Preden se dokument smatra za tocnega, preveri:

- endpointi se ujemajo s kodo
- env spremenljivke se ujemajo z `docker-compose.yml` in `Dockerfile`
- runtime port in lokalni URL se ujemata
- dokument nikjer ne implicira, da je live execution ze implementiran
