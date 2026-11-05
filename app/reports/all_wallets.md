# EDGEHOG végrehajtási riport – összes vizsgált tárca

Statisztikai becslés nyilvános adatokból. A költség EGY belépés költsége a kötés előtti Polymarket-középárhoz képest
(spread + csúszás együtt, mert a kötés pillanatáról nincs könyv-pillanatkép), plusz a Jupiter díja. Nem oda-vissza költség.

| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a | 5 perces markout |
|---|---:|---:|---:|---:|---:|---:|---:|
| mind | 10487 | $1,443,281 | $29,132 | $37,544 | **$66,676** | 4.62% | −$2,202 |
| élő | 8727 | $1,130,172 | $25,308 | $30,329 | **$55,637** | 4.92% | −$6,430 |
| meccs előtt | 1760 | $313,109 | $3,825 | $7,214 | **$11,039** | 3.53% | $4,228 |

**Ár szerint** (a kötött oldal középára):

| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a | 5 perces markout |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.0–0.2 | 1926 | $49,776 | $2,254 | $3,588 | **$5,842** | 11.74% | −$3,957 |
| 0.2–0.4 | 2765 | $179,432 | $6,777 | $8,188 | **$14,965** | 8.34% | $416 |
| 0.4–0.6 | 2932 | $432,410 | $10,956 | $13,657 | **$24,613** | 5.69% | −$727 |
| 0.6–0.8 | 1820 | $445,942 | $6,727 | $9,187 | **$15,914** | 3.57% | −$598 |
| 0.8–1.0 | 1044 | $335,722 | $2,418 | $2,924 | **$5,342** | 1.59% | $2,663 |

Végrehajtási idő (Jupiter-megbízás → Polymarket-kötés), medián: 5 mp.

**Tárcák közötti eloszlás** (legalább 10 mérhető kötés, 102 tárca): a forgalom %-ában fizetett költség
10%: 2.00%, medián: 4.26%, 90%: 7.00%.

_Forrás: 10487 mérhető kötés a 2026-11-04-i probe-ból (flow.py S1L/S1P), Polymarket-középár a saját kötéslistájából._
