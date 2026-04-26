# Sodelovanje in capital ledger

## Osnovni model sodelovanja

Projekt razvijata dve osebi, vendar live exchange racun in API kljuce upravlja en custodian.

To pomeni:

- ena oseba drzi Binance racun in odloca o account-level nastavitvah
- druga oseba prispeva razvoj, raziskavo, analitiko in review
- live execution ne sme biti odvisen od nejasne delitve odgovornosti

## Git in branch workflow

Repo trenutno nima inicializiranega `git` metapodatka, zato je prvi korak:

1. inicializacija repozitorija
2. vezava na remote
3. nastavitev glavne veje
4. feature branch workflow za vse vecje spremembe

Priporocen minimalni workflow:

1. odpre se issue ali kratek task zapis
2. sprememba gre na feature branch
3. drugi partner naredi kratek review pred merge
4. merge na glavno vejo se naredi sele po lokalnem preverjanju

Minimalna branch pravila:

- ena tema na branch
- brez direktnega dela na glavni veji za vecje spremembe
- README in `docs/` se posodobi skupaj s spremembo, ce se vedenje sistema spremeni

## Ownership nad kljuci in dovoljenji

Privzeta pravila:

- custodian hrani exchange racun in API kljuce
- kljuci niso nikoli committani v repo
- withdrawal permission ostane izklopljen
- po uvedbi testnet/live faze mora obstajati postopek za rotacijo kljuca

Ce partner, ki ni custodian, potrebuje preverjanje integracije, naj uporablja:

- paper mode
- testnet kljuce
- ali opazovalni dostop do logov in rezultatov

Ne uporablja se:

- osebnega live balance-a glavnega racuna kot razvojnega sandboxa
- deljenja istih mainnet credentialov brez jasnega razloga in postopka

## Locevanje sredstev

Ker eden od vaju ze ima Binance racun z obstojecim zneskom, velja naslednja politika:

- obstojece osebno stanje ni trading budget za bot
- bot budget mora biti posebej dodeljen
- primarna pot je `sub-account`, ce je podprt
- fallback je `testnet` ali locen racun, ne pa uporaba glavnega osebnega walleta

Pomembna meja:

- exchange-level locitev sredstev ne resi sama od sebe delitve lastnistva med partnerjema
- zato je potreben interni capital ledger

## Internal capital ledger

Internal ledger je locena evidenca, ki odgovarja na dve vprasanji:

1. koliko kapitala je prispeval vsak partner
2. kako se PnL in izplacila delijo med partnerjema

Za zacetek je dovolj preprost dogovorjeni zapis, npr. tabela:

| Partner | Vlozek | Delez poola | Opomba |
| --- | ---: | ---: | --- |
| Partner A | 700 EUR | 70% | Custodian racuna |
| Partner B | 300 EUR | 30% | Brez custody pravic |
| Skupaj | 1000 EUR | 100% | Bot budget |

Iz tega sledi:

- ce bot budget zraste na `1200 EUR`, je knjigovodska vrednost deleza Partnerja A `840 EUR`
- knjigovodska vrednost deleza Partnerja B je `360 EUR`
- to je interni poracun, ne nekaj, kar Binance vodi namesto vaju

## Operativna pravila za poracun

Predlagana pravila za prvi interni dogovor:

- vlozki se zapisujejo z datumom in valuto
- vsak dodaten vlozek spremeni deleze samo po izrecnem dogovoru
- izplacila ali dvigi se zapisujejo kot locen ledger event
- realized in unrealized PnL se za interni reporting locujeta

## Sprejemni scenariji

Dokument mora podpreti te primere:

1. nov task v repo pride na feature branch in gre skozi kratek review
2. custodian potrdi, da se za bot ne uporablja obstojeci osebni balance
3. partnerja lahko izracunata interni delez po neenakem vlozku
4. prehod na live se zavrne, ce account scope ni jasno locen
