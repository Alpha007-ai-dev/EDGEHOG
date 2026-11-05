# EDGEHOG – átadás új chathez (2026-11-04)

## Cél
Solana Foundation „Perps and Prediction Markets” hackathon, beadás: **2026-12-05**.
Fő díjalap 100 000 $, PREDICT pm-AMM bónusz 1 000 $. Egyedül építem (kevés programozói
tapasztalat), AI-asszisztenssel. Windows otthoni gép, mappa: `C:\dev\edgehog`.

## Az ötlet
A Jupiter Predict (Solana; Polymarket- és Kalshi-piacokat ad tovább) toplistája nyereség,
forgalom és találati arány szerint rangsorol, ezek rövid távon főleg szerencsét mérnek.
EDGEHOG: minden tárca minden kötését a piac későbbi árához méri (CLV / utólagos ármozgás),
és tárcánként hibahatárral mondja meg, van-e mért előnye.
Pozicionálás (ChatGPT-vélemény után): **„információs előny mérése / flow intelligence”**,
nem újabb toplista. Két termék: Explorer (tárcakereső, kereskedőknek) és Flow Intelligence
(kötésenkénti „mennyire informált / mérgező” jelzés árjegyzőknek, API).

## Ami kész
- `probe.py`: Jupiter Prediction API (toplista `/leaderboards`, tárcánkénti `/history`,
  globális `/trades`) + Polymarket gamma (`/markets/{id}`) és CLOB `prices-history`
  (10 perces és 1 perces). Nyers adatok gyorsítótárban: `data/raw/`. Kimenet: `output/`.
- Kulcs: `.jupkey` (gitignore-ban). `run_probe.bat` háttérfuttatáshoz (`output/run.log`).
- Jupiter piacazonosító: `POLY-<gamma id>-<outcome index>`; a végződés a kimenetel
  (a `-1` = a második token a `clobTokenIds`-ben). Ezt a kód kezeli.
- Mérések kötésenként: `close` (sportnál kezdés előtti utolsó ár, gameStartTime alapján),
  `1h`, `24h` (10 perces árak), `m0`, `1m`, `5m`, `15m` (perces árak). CLV = q/p − 1
  ugyanarra az oldalra; eladás = a másik oldal vétele 1 − p áron.

## Eredmény (2026-11-04, 125 toplistás tárca + 12 átlagos, 17 041 kötés, ebből 11 441 élő)
- 0 tárcának bizonyított pozitív előnye, 27-nek bizonyított negatív (a régi „szerencsés”).
  A mérhető toplistások 83%-ának negatív a CLV-je. Nyereség és CLV korrelációja ≈ 0.03.
- Meccs előtt (close): toplista −0.6% ±0.3%, átlag −2.0% ±0.9%.
- Élő kötések, ár 5 perccel később: toplista −6.9% ±3.0%, átlag −2.5% ±3.3%.
- Korlát: az `m0` élőben megbízhatatlan (perces árak késnek); átlagcsoport kicsi.

## Versenytársak
Convexly (Polymarket, lezárt fogadásokból, Brier + Edge Score; saját időbeli teszten
elbukott: 0.111 korreláció), Arkham Prediction Market Elo, találati-arány alapú pontszámok.
Különbség: ármozgásból mérünk (gyorsabb, élőben is), Solana-natív, árjegyzői API.

## A ChatGPT-vélemény alapján elfogadott változtatások (következő lépések)
1. Címkék: „pozitív / negatív mért előny / nem eldönthető”; a nyereség külön dimenzió.
   Minden tárcánál felirat: statisztikai becslés nyilvános adatokból, nem minősítés.
2. Hibahatár piaconként csoportosítva (cluster SE / bootstrap), nem független kötésekként.
   (A mostani kód már standard hibát használ, csak csoportosítás nélkül.)
3. Abszolút CLV (százalékpont) a relatív mellett.
4. Meccs előtti, élő és általános pontszám külön, mindegyik saját hibahatárral.
5. A Jupiter díjának kimérése és levonása (különben minden tárca mesterségesen negatív).
6. Élő kötéseknél esemény körüli (gól, kiállítás) kötések kezelése, élőben még nincs végleges ítélet.
7. Gyűjtő az otthoni gépen: `/trades` 10 percenként (Windows ütemezett feladat) → nagy
   véletlen átlagcsoport (200–500 tárca) + új kötések az időbeli ellenőrzéshez.
8. **Időbeli ellenőrzés (legfontosabb):** a 2026-11-04-i pontszám szerint csoportosított
   tárcák a következő heti kötéseiken is ugyanígy teljesítenek-e. Gördülő, heti.
9. AMM-demó: a korábban megírt pm-AMM-szimulátor ráültetése a valódi kötésfolyamra
   („ha az árjegyző tudta volna, ki informált, ennyivel kevesebbet veszít”) – pm-AMM bónusz.
10. Nyilvános kutatási oldal (módszer, eredmény, korlátok).
11. Kimarad: perp-modul (csak „következő lépés”), token, copy trading.

## Ütemterv
- nov 4–10: módszertan és adatminőség (1–6), gyűjtő indítása (7)
- nov 11–17: Explorer MVP (tárcakereső, grafikonok, címkék, adatminőség, toplista)
- nov 18–24: API (tárca-előny, kötés-mérgezőség prototípus), első időbeli ellenőrzés
- nov 25–30: AMM-integrációs demó (szimuláció)
- dec 1–5: beadás (kutatási oldal, demóvideó, README, ábra)
- nov 24. után nincs új nagy funkció.

## Egyéb
- Kapcsolódó: Footballer26 (`C:\Users\kaczu\Footballer26`) ugyanezt a CLV-módszert használja fogadásokra.
- A Jupiter-kulcs kétszer szerepelt chatben: beadás előtt cserélni.

## 2026-11-04 este – 1–7. pont kész
Fájlok: `probe.py` (csak gyűjt), `score.py` (új, minden statisztika, offline: `run_score.bat`),
`collect.py` + `install_collector.bat` / `uninstall_collector.bat`, `probe_old_20261104.py` (régi).
- 1. Címkék: pozitív / negatív mért előny / nem eldönthető / kevés adat; a P&L nem számít bele.
  `wallets.csv` minden sorában felirat: „Statisztikai becslés nyilvános adatokból, nem minősítés.”
- 2. Hibahatár: cluster-robust SE piaconként (bootstrap-pal ellenőrizve: `score.py --bootstrap 500`).
  Címkéhez ≥10 kötés és ≥10 piac kell. A csoportosítás csoportszinten alig változtat (a legtöbb piacon 1 kötés).
- 3. Abszolút CLV százalékpontban (szerződéssúlyozva) a relatív mellett.
- 4. Három pontszám: meccs előtti (close, ha nincs: 24h, ha nincs: 1h), élő (5m, esemény nélkül), általános.
  Fő címke = meccs előtti; élőben csak „(előzetes)”. Kezdési idő: gameStartTime, ha nincs: Jupiter beginAt.
- 5. **Díj:** `feeUsd` kötésenként; az `avgFillPriceUsd` NEM tartalmazza (a díj a tetejébe jön).
  ≈ k · szerződés · p · (1−p), k mediánja 0,05 (0,03–0,11). Átlag 2,3% a forgalomból, olcsó áraknál 9,6%.
  Tehát a korábbi CLV bruttó volt; a díj NEM magyarázza a negatív eredményt, nettóban rosszabb.
- 6. Esemény: élő kötésnél a YES-ár terjedelme −2..+5 percben (`swing`); ≥10% → kimarad (`--swing`).
  NYITOTT: a medián swing 13 sz.pont (56% kiesik 10%-nál) – gyanúsan sok, valószínűleg a perces
  Polymarket-árak zaja. A toplista élő eredménye küszöbtől függetlenül negatív (−1,8…−2,8%).
- 7. Gyűjtő: ütemezett feladat „EDGEHOG gyujto”, **2 percenként** (nem 10), mert a `/trades` csak a
  legutóbbi ~20 kötést adja lapozás nélkül (~9 perc forgalom). `data/trades/trades_ÉÉÉÉHHNN.jsonl`,
  napló: `output/collector.log` („HÉZAG?” = kimaradhatott forgalom). Csak akkor fut, ha a gép be van kapcsolva.
  A trade-sorban nincs díj és szerződésszám (csak amountUsd, priceUsd), az átlagcsoport tárcáinak forrása.

Eredmény (új mérés, 125 toplistás + 7 átlagos tárca, 16 683 kötés):
- Toplista meccs előtt: bruttó +0,08% ±0,46% (≈0), nettó −1,68% ±0,33%. Élő: bruttó −2,03% ±0,27%.
- Átlag meccs előtt: −2,26% ±0,63% (kicsi csoport!). Toplista meccs előtt jobb az átlagnál.
- Címkék (toplista): 23 negatív, 2 pozitív mért előny, 83 nem eldönthető, 17 kevés adat.
  A 2 pozitív belefér a véletlenbe (~1,6 várható 71 eldönthetőből) – az időbeli ellenőrzés dönti el.
- P&L és CLV korrelációja ≈ 0 (+0,02).
- Az átlagcsoport (7 tárca) túl kicsi: pár nap gyűjtés után `python probe.py --baseline 300`.

## 2026-11-04 este – felár-ellenőrzés (verify_premium.py, run_verify.bat)
600 véletlen Jupiter-kötés párosítva a Polymarket nyilvános kötéseivel (data-api **v2**; a v1 megszűnt,
HTTP 410; v2-ben piacra szűrve nincs időszűrő, csak `user`-rel). Párosítva: 537/600, medián 2 mp eltéréssel.
- **A Jupiter nem tesz felárat:** a Jupiter-ár = a saját Polymarket-kötése (átlag 0,00 sz.pont).
- **A Jupiter továbbító tárcája a Polymarketen: 0x5b6331e7ff0831a3fe2ed12004747db1a9c911a4**
  (529/537 pár). Ezzel `/v2/trades?user=...&start=...` a TELJES Jupiter-forgalmat adja időszűrővel
  (Solana-tárca nélkül) – a 20-kötéses `/trades` korlát megkerülhető aggregált elemzéshez.
- Az m0-ban mért felár = a Polymarket spreadje (taker): átlag ~1,0 sz.pont, medián 0,5 (egy tick).
  Relatív (árral súlyozva): meccs előtt ~1,8%, élőben ~2,5%. Plusz Jupiter-díj: ~2,4% / ~3,1%.
  → Egy Jupiter-kötés teljes költsége a középárhoz képest ≈ 4% meccs előtt, ≈ 5,5% élőben.
- Meccs előtt a perces ár (m0) jó (vs. közép +0,03 sz.pont); élőben késik (+1,6 sz.pont átlag) → élőben
  az m0 nem használható, a közép = szomszédos Polymarket-kötésekből jobb.
- Következmény: a toplista meccs előtti bruttó ~0% CLV-je ≈ +1–2% a középhez képest (irányt jól
  választanak), de ezt elviszi a spread és a díj. Vigyázat: a középhez mért szám a saját árhatást is tartalmazza.

## 2026-11-04 este – közép-CLV és saját árhatás (midclv.py, run_midclv.bat)
- A) Összes meccs előtti kötés, a kötéskori perces árhoz (≈ közép) mérve: toplista +1,42% ±0,55%
  (a kötési árhoz +0,09%; a különbség = spread). Ebben BENNE van a saját árhatás és a hosszú horizont.
- B) 1001 kötéses minta, Polymarket-kötésekből számolt közép + placebo (ugyanott, ugyanabba az irányba,
  0,5–2× méretű más PM taker-kötések, ±30 perc). Mérhető: 674 (327-nél nincs közép: csendes piac).
  * Toplista meccs előtt (122): Jupiter-kötés és placebo is ≈ 0, többlet ≈ 0 (1m/5m/15m) – előny nem látszik.
    → az A) +1,4% valószínűleg nagyrészt árhatás / horizont, nem előny. Nagyobb minta kell.
  * **Toplista élő (517): a Jupiter-kötés rosszabb, mint a hasonló Polymarket taker-kötések.**
    Többlet (sz.pont, átlag ± piaconként, medián): 1m −1,0 ±0,9 (−0,5); 5m −1,4 ±1,2 (−1,0);
    15m −2,6 ±1,1 (−0,6). Relatívban 5m −8,6% ±3,2%. A hasonló PM-kötések +2…+4 sz.pontot nyernek.
    Olvasat: a Jupiteren át érkező élő forgalom kevésbé informált (lassabb), mint a Polymarket saját taker-forgalma
    → árjegyzőnek "jóindulatú" forgalom. Flow Intelligence-állításnak jó, de még csak ~1–2,3 hibahatár.
  * Átlagcsoport: túl kevés (4 + 31 kötés), nem értékelhető; a relatív átlagot az olcsó piacok torzítják
    → riportban abszolút sz.pont és medián is kell.

## ELŐRE RÖGZÍTETT PROTOKOLL – Flow Intelligence (rögzítve 2026-11-04 20:55, a futás előtt; flow.py)
Kérdés: a Jupiteren át érkező forgalom után kevésbé mozdul-e a középár a kereskedő javára, mint hasonló
más Polymarket taker-kötések után? (= alacsonyabb relatív adverse-selection kockázat)
- **Fő mérőszám:** S2 (a Jupiter router tárca ÖSSZES Polymarket taker-kötése, 2026-11-01 00:00 –
  2026-11-04 00:00 UTC), élő fázis, 5 perces többlet százalékpontban, kontroll ±60 mp, átlag piaconként
  csoportosított hibahatárral. Eredmény-szabály: |átlag| > 2 hibahatár → „van különbség”, különben nem eldönthető.
- **Másodlagos:** 1m és 15m; kontrollablak ±10 mp, ±30 perc, csak-előtte (−60..0 mp); medián; relatív;
  S1L (toplista + átlagcsoport élő kötései, tárcánként csoportosítva is); S1P (meccs előtt); S2 meccs előtt.
- **Késleltetés-hipotézis (külön teszt, S1L):** megbízás létrehozása → Polymarket-végrehajtás (mp),
  sávok 0–5 / 5–10 / 10–20 / 20+; várakozás: nagyobb késés → negatívabb többlet. Addig NEM állítjuk, hogy a Jupiter lassú.
- **Kontroll:** ugyanaz a piac, azonos irány (YES-térben), 0,5–2× méret, nem a router tárca, nem ugyanaz a tranzakció.
  Közép = utolsó vételi és eladási taker-kötés átlaga az előző 5 percben (a kötés saját tranzakciója nélkül).
- **Minta és leállás:** a fenti időablak / a 11-04-i probe összes kötése, egyszeri futás; nincs utólagos szűrés vagy
  mintabővítés az eredmény láttán. Mérhetetlen kötések okkal együtt mentve, külön riportban (mérhető vs. nem).
- **Megfogalmazás:** „alacsonyabb relatív adverse-selection kockázat a kontrollhoz képest”, nem „jóindulatú” vagy
  „biztonságos” forgalom. Árjegyzői hasznot csak AMM-szimuláció után állítunk (volumenhatással együtt).

## EREDMÉNY – éjszakai flow-mérés (2026-11-05, flow.py, 4,3 óra; output/flow_report.txt)
**Fő mérőszám (protokoll): S2 élő, 5m, kontroll ±60 mp: többlet +0,34 ±0,19 sz.pont (n=4136, 1560 piac)
→ 1,8 hibahatár < 2 → NEM ELDÖNTHETŐ.** Az előjel ráadásul pozitív: a tegnapi „a Jupiter-forgalom kevésbé
informált” (midclv, 517 kötés, −1,4 ±1,2) NEM ismétlődött meg – az zaj volt. Ezt az állítást elvetjük.
- A többlet előjele a kontrollablaktól függ (S2 élő 5m): ±10 mp −0,49 ±0,12; ±60 mp +0,34 ±0,19;
  ±30 perc +1,05 ±0,28; csak-előtte +0,51 ±0,24. S1L ugyanígy (±10 mp ≈0, ±60 mp +0,42 ±0,10, előtte +1,20).
  → a „többlet vs. hasonló PM-kötések” mérőszám specifikáció-érzékeny, így termék-mérőszámnak most alkalmatlan.
- A Jupiter-forgalom SAJÁT 5 perces középár-markoutja ≈ 0: S2 élő +0,08 ±0,38, S1L élő −0,26 ±0,23,
  S1P +0,13 ±0,21 sz.pont. = Rövid távon nincs kimutatható adverse selection a Jupiter-forgalomban (abszolút mérce).
- A mediánok szinte mind 0: a középár-változás többnyire 0 tick, az átlagot a ritka nagy mozgások adják.
- Késleltetés (S1L): megbízás létrehozása → Polymarket-végrehajtás medián 5 mp (10%: 4, 90%: 7; n=8247).
  Szinte minden kötés 0–10 mp-ben van; a sávok között nincs különbség → a késleltetés-hipotézis nem igazolódott
  (nincs elég szórás a teszthez). „A Jupiter lassú” állítás továbbra sem tehető; a ~5 mp tényként közölhető.
- Mérhető: S2 70%, S1L 85%, S1P 33% (csendes meccs előtti piacok). S2-ben a mérhető és nem mérhető kötések
  ára/mérete hasonló; S1L-ben a nem mérhetők szinte biztos kimenetelű piacok (medián ár 0,01).
- Ami ÁLL (robosztus): toplista-P&L ≠ előny (korr. ≈ 0); költség: spread ~1,8–2,5% + Jupiter-díj ~2,4–3,1%;
  Jupiter ár = Polymarket ár (nincs felár), ~5 mp végrehajtás; Jupiter-forgalom 5m markoutja ≈ 0.

## 2026-11-05 – helyszín-teszt (venue_probe.py, run_venue.bat): Polymarket/Jupiter vs. Kalshi/DFlow
44 párosított meccs (NBA, NHL, tenisz, KBO) a következő 48 órából, $50/500/2000 vétel, ár + díj.
Jupiter-díj (saját mérés) ≈ 0,05·p·(1−p)/szerződés (0,50-nél 1,25¢); Kalshi taker-díj 0,07·p·(1−p) (1,75¢).
- Likvid meccsek (27): az árak szinte azonosak, |különbség| medián 0,5 sz.pont (≈ a díjkülönbség);
  Polymarket+Jupiter olcsóbb az esetek ~80%-ában.
- Ritkás könyvű meccsek (17, főleg kis tenisztornák): nagy különbség (medián 4–12 sz.pont), de ~85%-ban
  szintén a Polymarket+Jupiter az olcsóbb – a különbség a hiányzó Kalshi-likviditásból jön.
- Arbitrázs díjak után: nincs (a két oldal legolcsóbb ára együtt is ≥ 1,008).
- Következtetés: legjobb-ár aggregátor önálló termékként GYENGE (likvid piacon ~0,5 sz.pont, ritkás piacon
  egyirányú: „használd a Jupitert”). Funkcióként / riport-adatként hasznos.
- Korlát: egy pillanatfelvétel; a DFlow API nem volt elérhető, a Kalshi-könyvet használtuk (a DFlow saját
  díja és esetleges saját likviditása nincs benne).

## ÚJ IRÁNY VIZSGÁLATA: order-flow terminál prediction marketekre (2026-11-05)
Egy élő meccs footprintje: a 8. percben abszorpció (90,6k vétel vs 10,1k eladás, ár 0,27–0,30-on áll, két tárca
adja a vétel ~2/3-át), majd kitörés felfelé 0,46-ig; a 28,8. percben 4 mp alatt 0,45 → 0,07 (meccsesemény),
előtte 3 percig semmi szokatlan a kötésekben. 13 piacos gyorsteszt: nincs egyértelmű jel (delta ~1,3 hibahatár).
### ELŐRE RÖGZÍTETT PROTOKOLL (of_test.py, rögzítve a futás előtt)
- Minta: 300 véletlen élő piac (seed 7) a 11-04-i probe élő kötéseinek piacai közül, a meccs kezdetétől, 1 perces gyertyák.
- H1 abszorpció: |delta| ≥ 2× a piac átlagos gyertya-forgalma ÉS a középár ≤ 1 cent mozgás. FŐ mérőszám: a középár
  változása a delta irányában 15 perc alatt, átlag piaconként csoportosított hibahatárral; |átlag| > 2 hibahatár = jel.
  Másodlagos: 5 perc, erős abszorpció (≥4×), „tolás” gyertyák és minden gyertya összevetésnek, találati arány.
- H2 esemény előtti jel: ugrás = ≥ 10 cent egy gyertyán belül; az előtte lévő 3 gyertya normalizált deltája az ugrás
  irányában, kötésszáma, nagy kötései vs. a többi gyertya.
### EREDMÉNY (of_test.py, 169 használható piac, 21 164 egyperces gyertya; 102 piacnál nem volt kezdési idő)
- **H1 abszorpció – FŐ (15 perc, delta irányában): −0,28 ±0,69 sz.pont → NINCS JEL.** Találati arány 274 vs 254 (érmedobás).
  5 perc +0,47 ±0,35; erős abszorpció (≥4×) 15p +0,74 ±0,92; „tolás” 15p +0,98 ±0,85 – egyik sem szignifikáns.
- Minden gyertya: a delta irányában kis folytatás, 5p +0,21 ±0,06 sz.pont (3,5 hibahatár) – valós, de jóval kisebb a
  kötés költségénél (spread ~1 + díj ~1,2 sz.pont) → kereskedési előnyként nem használható.
- **H2: az ugrások (≥10 cent) előtti 3 percben a delta és a nagy kötések iránya nem tér el** a többi gyertyától
  (+0,08 ±0,15 vs +0,03; −0,12 ±0,12 vs +0,04). A kötésszám magasabb (1,19 vs 0,68), de ez irányt nem jelez, és
  részben csak azt tükrözi, hogy ugrás aktív meccsszakaszban történik.
- Következtetés: prediction marketen a nyilvános kötésfolyam nem hordoz kihasználható előrejelzést; az információ a
  meccsből jön. Order-flow terminál „előnyt adó eszközként” nem igazolt; legfeljebb vizualizációként / visszajátszásként.

## DÖNTÉS (2026-11-05 délután): EDGEHOG = Execution Intelligence for Prediction Markets (fődíjra, magas kockázat)
Részletes specifikáció: ChatGPT „végleges termékspecifikáció” (a chatben). Lényeg:
- **Trader Desk (fő):** Market Explorer (Jupiter API), Pre-trade Execution Analyzer (spread / slippage / díj külön,
  100/500/1000 USD), Live Flow Terminal (footprint, tape, delta – leíró, NEM jelzés), Trade Replay, Execution Report,
  wallet + valódi kötés a Jupiter Prediction API-n (POST /orders → aláíratlan tx → aláírás → /execute).
- **LP Desk (PREDICT pm-AMM):** pool explorer, LP-szimulátor (díjbevétel és LVR külön), dinamikus likviditás,
  devneten legalább egy deposit + withdraw.
- Kihagyva: skill score, copy trading, toxicity score, arb bot, delta-jelzés, token, perp-modul.
- Történet: „We tried to find alpha. We couldn't prove it. So we built a tool to measure what traders actually pay.”
- Költség-feliratozás: a 4–5% EGY belépés költsége a középárhoz képest, nem oda-vissza.
- Stack-javaslat: Next.js + TypeScript, Tailwind + shadcn/ui, Lightweight Charts, Solana Wallet Adapter.
### Ellenőrizve (2026-11-05)
- Jupiter Prediction API (béta): /events, /markets, /orderbook/{marketId}, POST /orders (aláíratlan tx), /execute,
  /positions, /history, /trades, /leaderboards, /vault-info, /forecast. https://developers.jup.ag/docs/prediction/index.md
- pm-AMM (Paradigm-modell, Solana): program `GV1FMGHRYBjQLaghE5fnGuYCuCcpdt3GD5xEX3TwN16y` (devnet), utasítások:
  initialize_market, deposit_liquidity, withdraw_liquidity, swap, resolve_market, claim_winnings, claim_lp_residuals;
  SDK: packages/sdk, HACKATHON.md, DEVNET.md (mock USDC faucet). Nincs audit, egykulcsos upgrade → csak devnet.
  Repo: github.com/sparkfun-labs/pm-amm (fork: abelmarnk/pm-amm). Versenytárs ugyanerre: StrikeBook.
### ELSŐ 48 ÓRA: két kockázatmentesítő teszt (spike) építés előtt
1. pm-AMM devneten: SDK telepítés, pool state lekérés, egy deposit + withdraw tesztkulccsal.
2. Jupiter: /orderbook + POST /orders aláíratlan tx felépítése (aláírás nélkül), a válasz ár/díj mezői.

## REPÓ ÉS FEJLESZTŐI KÖRNYEZET (2026-11-05)
- Kód: github.com/Alpha007-ai-dev/EDGEHOG (privát). A nyers adat (`data/`) és az `output/` nincs a repóban; a mérési
  eredmények a `research/` mappában vannak. `of_quick.py` és `footprint_plot.py` gyors vázlatok (beégetett útvonalak).
- Jupiter-kulcs: `JUPITER_API_KEY` környezeti változó (a felhős környezet beállításainál), vagy helyi `.jupkey`. Cserélni kell
  beadás előtt (kétszer szerepelt chatben).
- Felhős környezet hálózata (claude.ai/code → felhő ikon → fogaskerék → Network access: Custom + csomagkezelők):
  api.jup.ag, gamma-api.polymarket.com, clob.polymarket.com, data-api.polymarket.com, api.elections.kalshi.com,
  api.devnet.solana.com. Csak új munkamenetre érvényes.
- Az otthoni gépen (C:\dev\edgehog) továbbra is fut a `collect.py` ütemezett feladat („EDGEHOG gyujto”, 2 percenként).
- KÖVETKEZŐ LÉPÉS új munkamenetben: hozzáférés-ellenőrzés, majd a két spike (pm-AMM devnet deposit/withdraw;
  Jupiter /orderbook + POST /orders aláíratlan tx).

## 2026-11-05 este – offline elkészült (app/, research/)
- `app/lib/execution.ts` – költségmotor: középár, spread, csúszás (könyvbejárás), díj (mért tábla / dokumentált képlet /
  pontos Jupiter-ajánlat), USD-ben, átfedés nélkül; kötés utáni költség és markout. Tesztek: `cd app && npm test` (Node ≥ 22.18).
- `app/lib/pmamm.ts` – pm-AMM LP-szimulátor (dinamikus L0·√(T−t) és statikus): visszaadott likviditás, LVR, díj,
  készlet-ármozgás külön, elszámolási azonosság tesztelve; a Monte Carlo tesztek visszaadják a tanulmányt (E[W_T]≈W0/2,
  egyenletes LVR). `scripts/lp_sim.ts` valódi Polymarket-ártörténeten fut.
- `app/scripts/report_offline.ts` – végrehajtási riport a kutatási adatból; `app/reports/`: 102 tárca, 10 487 kötés,
  $1,44M középáron, $66 676 költség (4,62%); a toplista #1 236 kötésén $11 938 (7,6%), havi toplista-P&L $8 773 (más időablak).
- `app/scripts/preview.ts` – élő 100/500/1000 USD költségsor egy Jupiter-piacra (Polymarket-könyvből) + nyers Jupiter
  `/orderbook` válasz. MÉG NEM FUTOTT ÉLESBEN.
- `app/prototype/index.html` – kattintható prototípus (5 nézet; a Pre-trade nézet MINTA-könyvvel). Publikálva privát
  artifactként is.
- `research/FINDINGS.md` – angol kutatási összefoglaló; `research/x_thread_draft.md` – X-szál vázlat (átnézésre).
### KÖVETKEZŐ LÉPÉS (új munkamenet, hálózattal)
1. Hozzáférés-ellenőrzés (Jupiter, Polymarket, Kalshi, devnet, npm), `cd app && npm test`.
2. `npm run preview -- POLY-<id>-<0|1>` élő piacon; a Jupiter `/orderbook` és `POST /orders` válasz mezőinek feltérképezése,
   a díj összevetése a mért táblával.
3. pm-AMM devnet spike: SDK, pool state, deposit + withdraw tesztkulccsal; a szimulátor számainak összevetése az SDK-val.
4. Ha mindkét spike működik: Next.js-váz (specifikáció szerinti stack), a prototípus nézetei valódi adatra kötve.
