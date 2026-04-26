# Arhitektura in operativa

## Komponente sistema

Trenutna aplikacija ima stiri osnovne dele:

- Rust backend v `src/main.rs`
- static frontend v `static/`
- SQLite baza v `data/tradebot.db`
- Docker runtime preko `Dockerfile` in `docker-compose.yml`

## Runtime flow

Zagon poteka takole:

1. aplikacija prebere environment konfiguracijo
2. inicializira mapo `DATA_DIR` in odpre SQLite bazo
3. backend izpostavi HTTP API na `APP_PORT`, privzeto `3000`
4. frontend se servira iz `static/`
5. UI ob osvezevanju klice backend, backend pa uporablja javne Binance endpointe za tickerje, cene in candles
6. paper orderji in pozicije se obdelujejo lokalno v SQLite bazi

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
    - `4h` trend bias
  - `v2_reclaim_strategy` state machine: `WAIT -> STALK -> SETUP -> READY`
  - `STALK`: zaprt `1h` close je znotraj `0.5 ATR` od supporta, vendar se ni reclaim-a
  - `SETUP`: zaprt `1h` close reclaim-a support
  - `READY`: po `1h` reclaim-u se zapre se veljaven `15m` momentum trigger
  - `session` gate (`07:00-22:00 UTC`)
  - `correlation` gate proti `BTCUSDT`
  - `news blackout` gate prek javnih `BEA`, `Fed`, `SEC` in `CoinDesk` virov
  - predlagan risk plan za paper long setup

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

Operativna posledica:

- stanje aplikacije je vezano na lokalni disk masina/container para
- backup in prenos stanja sta za zdaj rocna
- ni multi-user concurrency modela

## Konfiguracija in deployment

Privzeta konfiguracija:

- `APP_HOST=0.0.0.0`
- `APP_PORT=3000`
- `DATA_DIR=/data`
- `WATCHLIST=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT`
- `STARTING_CASH=10000`
- `PAPER_FEE_BPS=10`
- `DEFAULT_INTERVAL=1m`

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
