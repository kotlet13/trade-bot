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

## Kaj zna danes

- watchlist za `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- candle chart na intervalih `1m`, `5m`, `15m`, `1h`, `4h`
- signal assistant za izbran simbol:
    - `4h` trend filter
    - `v2_reclaim_strategy` state machine: `WAIT -> STALK -> SETUP -> READY`
    - `STALK`: cena je blizu `1h` supporta, vendar se ni zaprt reclaim
    - `SETUP`: zadnja zaprta `1h` svecka reclaim-a support
    - `READY`: sele po `1h` reclaimu pride se zaprt `15m` momentum trigger
  - `session` gate za nove entryje (`07:00-22:00 UTC`)
  - `correlation` gate proti `BTCUSDT`
  - `news blackout` gate prek javnih `BEA`, `Fed`, `SEC` in `CoinDesk` virov brez prijave
  - predlagan `entry / stop / TP1 / TP2 / qty` za paper workflow
- replay/backtest za signal assistant:
    - pregled zadnjih `15m` signalov za izbran simbol
  - session in BTC correlation gate v replay porocilu
  - v2 reclaim replay uporablja samo zaprte `4h`, `1h` in `15m` svecke, zato 15m trigger ne more prehiteti 1h reclaim-a
  - TP1 win rate, `avg R`, `total R`
  - recent replay primeri z outcome in trajanje setupa
- rocni `market` in `limit` paper orderji
- stop-loss in take-profit na long paper entryjih
- virtualni cash, pozicije, odprti orderji in PnL
- trade log z notes in lokalno persistenco v SQLite

## Kaj se ne dela se

- live Binance execution
- uporaba private API kljucev
- testnet integracija
- vec-uporabniski access model
- partner-level capital ledger v sami aplikaciji
- auto execution iz signal assistant modula
- robusten event-driven backtest engine z exchange fill modelom
- zgodovinski `news` replay ali economic-calendar feed z event revision logiko

## HTTP surface

Trenutni backend endpointi:

- `GET /health`
- `GET /api/dashboard`
  - vrne tudi `signal_assistant` za izbrani simbol
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
- `WATCHLIST=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT`
- `STARTING_CASH=10000`
- `PAPER_FEE_BPS=10`
- `DEFAULT_INTERVAL=1m`

Docker Compose mapira `8081:3000`, zato je aplikacija lokalno dosegljiva na `http://localhost:8081`.

## Dokumentacija

Podrobnejsa dokumentacija je v `docs/`:

- [Pregled in roadmap](docs/overview-roadmap.md)
- [Arhitektura in operativa](docs/architecture-ops.md)
- [Sodelovanje in capital ledger](docs/collaboration-capital.md)
