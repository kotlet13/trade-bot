# Pregled in roadmap

## Trenutno stanje

Projekt je danes lokalni `paper-trading MVP`:

- frontend in backend teceta kot ena lokalna spletna aplikacija
- market data prihaja iz javnega Binance feeda
- orderji se izvajajo samo kot paper simulacija
- stanje racuna, pozicij, orderjev in trade loga je lokalno v SQLite
- ni live executiona, ni account linking-a in ni private secret managementa

To pomeni, da je trenutni cilj projekta ucenje workflowa, validacija UI-ja in priprava execution meje za naslednje faze.

## Cilj projekta

Zgraditi dovolj zanesljiv trading workflow, da lahko:

1. spremljata trg in rocno testirata ideje v paper nacinu
2. dodata testnet execution brez posega v osebna live sredstva
3. sele nato preideta na majhen live budget z jasno izolacijo sredstev in odgovornosti

## Faze dostave

### Faza 0: Dokumentiran paper MVP

Cilj:

- uskladiti dokumentacijo z realnim stanjem repozitorija
- definirati varnostna pravila pred prvo exchange integracijo
- postaviti osnovni collaboration workflow

Exit kriteriji:

- `README` in `docs/` opisujejo dejansko stanje aplikacije
- jasno je zapisano, da je sistem paper-only
- dogovorjena je live funds politika in odgovornost za kljuce

### Faza 1: Stabilen paper workflow

Cilj:

- utrditi uporabnost trenutnega paper flowa
- zapreti osnovne funkcionalne luknje pred testnet integracijo

Predlagane naloge:

- preverjanje edge case-ov pri paper orderjih in triggerjih
- boljse validacije in napake v UI-ju
- osnovni export ali pregled zgodovine tradeov
- bolj jasen reset in state inspection flow
- validacija `signal assistant` modula v paper nacinu
  - `v2_reclaim_strategy` pravila: `WAIT -> STALK -> SETUP -> READY`
  - `4h` trend, zaprt `1h` reclaim in zaprt `15m` trigger po reclaimu
  - session / correlation / news gate pravila
  - rocna primerjava signalov z dejanskim price actionom
- validacija replay/backtest porocila
  - ali replay pravilno odseva signal pravila
  - ali session in correlation gate zmanjsata slabse tehnicne ready signale
  - ali so rezultati dovolj stabilni za naslednji tuning korak

Exit kriteriji:

- vsakodneven paper workflow je predvidljiv
- dokumentirano je, kako reproducirati stanje in napake
- ni odprtih kriticnih nejasnosti v runtime konfiguraciji
- signal assistant ne oddaja orderjev sam in ne maskira operativnih tveganj
- replay obstaja kot iterativno orodje za tuning, ne kot dokaz live edge-a
- `news blackout` ostaja live-only, dokler ni zgodovinskega event feeda za reproducibilen replay

### Faza 2: Binance spot testnet

Cilj:

- vpeljati prvi pravi exchange adapter brez live kapitala

Obseg:

- testnet API kljuci
- locen execution sloj za oddajo orderjev
- izbira `paper` ali `testnet` nacina na nivoju konfiguracije
- osnovni logging in audit trail za API klice

Exit kriteriji:

- mozna je oddaja in preklic testnet orderjev
- secret handling ni vezan na repo
- testnet execution ne vpliva na paper stanje

### Faza 3: Small live

Cilj:

- omejen live rollout z majhnim bot budgetom

Obvezni pogoji pred vklopom:

- potrjeno, da Binance racun podpira `sub-account`, ali pa obstaja drug realno locen account scope
- live sredstva niso pomesana z osebnimi sredstvi, ki niso namenjena botu
- withdrawal permission ostane izklopljen
- ena oseba ostane custodian racuna in API kljucev
- obstaja interni ledger za evidenco vlozkov obeh partnerjev

Exit kriteriji:

- live rollout uporablja locen budget
- obstaja postopek za zaustavitev tradinga
- oba razumeta mejo med exchange wallet separation in internim ownership ledgerjem

## Odlocitev o denarnicah in racunih

Privzeta pot za live fazo je:

1. `sub-account`, ce ga dejanski Binance racun podpira
2. ce ne, ostaneta na testnetu ali odpreta locen racun za bot
3. ne uporabljata glavnega osebnega trading balance-a kot fallback

`Funding Wallet` ni dovolj za zahtevano izolacijo bota, ker ostaja znotraj istega account scope-a. Uporaben je lahko za interne transfere, ni pa privzeta varnostna meja za bot kapital.

## Sprejemni scenariji za dokumentacijo

Dokumentacija mora omogociti tri jasne walkthrough scenarije:

1. svezi lokalni setup in prvi zagon paper MVP-ja
2. dnevna uporaba paper trading workflowa
3. priprava na testnet onboarding brez dotika live sredstev

## Reference

- Binance sub-account: <https://www.binance.com/en/skills/detail/binance/sub-account>
- Binance assets, funding wallet in transferji: <https://www.binance.com/en/skills/detail/binance/assets>
- Binance spot skill, ki navaja podporo za testnet: <https://www.binance.com/zh-CN/skills/detail/binance/spot>
