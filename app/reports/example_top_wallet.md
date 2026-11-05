# EDGEHOG végrehajtási riport – 4Mkq…49JC

Statisztikai becslés nyilvános adatokból. A költség EGY belépés költsége a kötés előtti Polymarket-középárhoz képest
(spread + csúszás együtt, mert a kötés pillanatáról nincs könyv-pillanatkép), plusz a Jupiter díja. Nem oda-vissza költség.

| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a | 5 perces markout |
|---|---:|---:|---:|---:|---:|---:|---:|
| mind | 236 | $156,718 | $6,699 | $5,239 | **$11,938** | 7.62% | $5,156 |
| élő | 219 | $152,197 | $6,671 | $5,072 | **$11,743** | 7.72% | $5,096 |
| meccs előtt | 17 | $4,521 | $28 | $167 | **$195** | 4.31% | $60 |

**Ár szerint** (a kötött oldal középára):

| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a | 5 perces markout |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.0–0.2 | 16 | $2,305 | −$29 | $156 | **$127** | 5.50% | −$564 |
| 0.2–0.4 | 46 | $24,974 | $2,447 | $1,344 | **$3,791** | 15.18% | −$1,972 |
| 0.4–0.6 | 133 | $74,114 | $3,171 | $2,616 | **$5,787** | 7.81% | $4,694 |
| 0.6–0.8 | 28 | $31,680 | $797 | $879 | **$1,676** | 5.29% | $1,276 |
| 0.8–1.0 | 13 | $23,644 | $313 | $244 | **$557** | 2.36% | $1,721 |

Végrehajtási idő (Jupiter-megbízás → Polymarket-kötés), medián: 6 mp.

**A 5 legdrágább kötés** (összes költség):

| idő (UTC) | piac | fázis | kontraktus | ár | közép | spread + csúszás | díj | 5p markout |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 2026-11-02 00:08 | POLY-6517221-1 | élő | 5235 | 0.378 | 0.208 | $890 | $127 | −$887 |
| 2026-09-23 16:35 | POLY-4844431-1 | élő | 4200 | 0.310 | 0.230 | $336 | $45 | $21 |
| 2026-11-02 00:00 | POLY-6517221-1 | élő | 2325 | 0.560 | 0.425 | $314 | $55 | $732 |
| 2026-09-22 06:37 | POLY-4727252-1 | élő | 2730 | 0.547 | 0.440 | $293 | $34 | −$164 |
| 2026-11-02 00:00 | POLY-6517221-1 | élő | 2910 | 0.560 | 0.480 | $233 | $68 | $931 |

_Forrás: 236 mérhető kötés a 2026-11-04-i probe-ból (flow.py S1L/S1P), Polymarket-középár a saját kötéslistájából._
