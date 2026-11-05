"""EDGEHOG pontozás: kötésenkénti adatokból tárcánkénti előny-becslés hibahatárral.

Bemenet:  output/fills_clv.csv   (a probe.py írja; a régi formátumot is érti)
          output/wallet_meta.csv (tárca, csoport, toplista-P&L; a probe.py írja)
Kimenet:  output/wallets.csv, output/report.txt

Offline fut, hálózat nélkül: a mérés újravágható új adatgyűjtés nélkül.

Módszer (röviden, a részletek a jelentés végén):
  * CLV ugyanarra az oldalra: vétel p áron, később q ér  ->  relatív q/p - 1,
    abszolút q - p (százalékpont). Eladás = a másik oldal vétele 1 - p áron.
  * Bruttó = a kötési áron (Jupiter díja nélkül) = információs előny.
    Nettó = a Jupiter díjával terhelt áron (p + díj/szerződés) = megéri-e a kereskedőnek.
  * Három pontszám, mindegyik saját hibahatárral:
      meccs előtti (nem élő kötések): referencia = kezdés előtti utolsó ár, ha nincs: 24h, ha az sincs: 1h
      élő (meccs közbeni kötések):   referencia = ár 5 perccel később; az esemény körüli
                                      kötések (nagy ugrás az árban) kimaradnak; csak előzetes jelzés
      általános:                      a kettő együtt
  * Hibahatár piaconként csoportosítva (cluster-robust SE): egy piac kötései nem függetlenek.
  * Címke a bruttó relatív CLV-ből, 2 hibahatárnál: pozitív / negatív mért előny / nem eldönthető.
    A tárca fő címkéje a meccs előtti pontszámból jön; élőben nincs végleges ítélet.
    A toplista-nyereség külön dimenzió, a címkébe nem számít bele.

Futtatás:  python score.py                    (a probe.py a végén magától meghívja)
           python score.py --swing 0.15 --bootstrap 500
"""
from __future__ import annotations

import argparse
import csv
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("output")
FELIRAT = "Statisztikai becslés nyilvános adatokból, nem minősítés."
Z = 2.0             # ennyi hibahatár kell a címkéhez (~95%)
MIN_N, MIN_G = 10, 10  # címkéhez legalább ennyi kötés és ennyi különböző piac (kevés piacnál a csoportos hibahatár alábecsül)
HORIZONS = ("close", "1h", "24h", "m0", "1m", "5m", "15m")
SCORES = (("pre", "meccs előtti"), ("live", "élő"), ("all", "általános"))
NAN = float("nan")


# ----------------------------------------------------------------- input
def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def fbool(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "yes")


def load_fills(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        cols = set(rd.fieldnames or [])
        new = "q_5m" in cols                      # új formátum: nyers YES-árak; régi: CLV-értékek
        rows = []
        for r in rd:
            price, n = fnum(r.get("price")), fnum(r.get("n")) or 0.0
            if price is None or n <= 0:
                continue
            buy, yes = fbool(r.get("buy")), fbool(r.get("yes"))
            sp = price if buy else 1 - price      # a megvett oldal ára
            f = {"owner": r["owner"], "group": r.get("group", ""), "market": r.get("market", ""),
                 "t": fnum(r.get("t")), "p": sp, "n": n, "inplay": fbool(r.get("inplay")),
                 "fee": fnum(r.get("fee")), "swing": fnum(r.get("swing")),
                 "category": r.get("category", ""), "q": {}}
            for h in HORIZONS:
                if new:
                    qy = fnum(r.get(f"q_{h}"))
                    if qy is None:
                        continue
                    v = qy if yes else 1 - qy     # a kötött oldal későbbi értéke
                    f["q"][h] = v if buy else 1 - v
                else:
                    c = fnum(r.get(h))
                    if c is not None:
                        f["q"][h] = sp * (1 + c)  # a régi CLV visszaszámolása árrá
            rows.append(f)
    return rows


def load_meta(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["owner"]: r for r in csv.DictReader(fh)}


# ------------------------------------------------------------ measures
def values(f: dict, h: str) -> dict | None:
    """Egy kötés négy mérőszáma egy referencia-időpontra, súlyokkal."""
    q, p = f["q"].get(h), f["p"]
    if q is None or not (0.01 <= p <= 0.99) or not (0 <= q <= 1):
        return None
    fpc = (f["fee"] / f["n"]) if f["fee"] is not None else None   # díj szerződésenként
    out = {"rel": (q / p - 1, p * f["n"]), "pp": (q - p, f["n"])}
    if fpc is not None:
        pe = p + fpc
        out["net"] = (q / pe - 1, pe * f["n"])
        out["net_pp"] = (q - pe, f["n"])
    return out


def pre_ref(f: dict) -> str | None:
    for h in ("close", "24h", "1h"):
        if h in f["q"]:
            return h
    return None


def is_event(f: dict, swing: float) -> bool:
    return f["inplay"] and f["swing"] is not None and f["swing"] >= swing


def score_items(fills: list[dict], which: str, swing: float) -> list[tuple[dict, str]]:
    """(kötés, referencia) párok egy pontszámhoz."""
    out = []
    for f in fills:
        if not f["inplay"] and which in ("pre", "all"):
            h = pre_ref(f)
            if h:
                out.append((f, h))
        elif f["inplay"] and which in ("live", "all") and not is_event(f, swing):
            if "5m" in f["q"]:
                out.append((f, "5m"))
    return out


# --------------------------------------------------------------- stats
def cstats(items: list[tuple[float, float, str]]):
    """Súlyozott átlag piaconként csoportosított hibahatárral.
    items: (érték, súly, piac). Vissza: (n, piacok száma, átlag, cluster SE, naiv SE)."""
    items = [(v, w, g) for v, w, g in items if v is not None and w and w > 0]
    n = len(items)
    G = len({g for _, _, g in items})
    if n == 0:
        return 0, 0, NAN, NAN, NAN
    W = sum(w for _, w, _ in items)
    m = sum(v * w for v, w, _ in items) / W
    if n < 2 or G < 2:
        return n, G, m, NAN, NAN
    sg = defaultdict(float)
    for v, w, g in items:
        sg[g] += w * (v - m)
    se_c = math.sqrt(G / (G - 1) * sum(s * s for s in sg.values())) / W
    # ugyanez a képlet úgy, mintha minden kötés független volna (összevetésnek)
    se_n = math.sqrt(n / (n - 1) * sum((w * (v - m)) ** 2 for v, w, _ in items)) / W
    return n, G, m, se_c, se_n


def bootstrap_se(items, reps: int, seed: int = 7) -> float:
    """Piacok újramintavételezése (ellenőrzésnek a cluster SE mellé)."""
    by = defaultdict(list)
    for v, w, g in items:
        if v is not None and w and w > 0:
            by[g].append((v, w))
    keys = list(by)
    if len(keys) < 2:
        return NAN
    sums = {g: (sum(v * w for v, w in by[g]), sum(w for _, w in by[g])) for g in keys}
    rnd, ms = random.Random(seed), []
    for _ in range(reps):
        num = den = 0.0
        for g in rnd.choices(keys, k=len(keys)):
            a, b = sums[g]
            num, den = num + a, den + b
        ms.append(num / den)
    mu = sum(ms) / len(ms)
    return math.sqrt(sum((x - mu) ** 2 for x in ms) / (len(ms) - 1))


def measure(pairs: list[tuple[dict, str]], key: str):
    items = []
    for f, h in pairs:
        v = values(f, h)
        if v and key in v:
            items.append((v[key][0], v[key][1], f["market"]))
    return items


def label(n, G, m, se) -> str:
    if n < MIN_N or G < MIN_G or math.isnan(se) or math.isnan(m):
        return "kevés adat"
    if m - Z * se > 0:
        return "pozitív mért előny"
    if m + Z * se < 0:
        return "negatív mért előny"
    return "nem eldönthető"


# ---------------------------------------------------------------- main
def pct(x, signed=True):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:+.2%}" if signed else f"{x:.2%}"


def pp(x, signed=True):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x * 100:+.2f}" if signed else f"{x * 100:.2f}"


def corr(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None
           and not math.isnan(x) and not math.isnan(y)]
    if len(pts) < 3:
        return NAN, len(pts)
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in pts))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in pts))
    return (sxy / (sx * sy) if sx and sy else NAN), len(pts)


def main(argv=None):
    global Z
    ap = argparse.ArgumentParser()
    ap.add_argument("--fills", default=str(OUT / "fills_clv.csv"))
    ap.add_argument("--meta", default=str(OUT / "wallet_meta.csv"))
    ap.add_argument("--swing", type=float, default=0.10,
                    help="élő kötés 'esemény körüli', ha a YES-ár ennyit mozdult (-2..+5 perc)")
    ap.add_argument("--z", type=float, default=Z)
    ap.add_argument("--bootstrap", type=int, default=0, help="csoportszinten bootstrap-ellenőrzés (ismétlésszám)")
    a = ap.parse_args(argv)
    Z = a.z
    fills = load_fills(Path(a.fills))
    meta = load_meta(Path(a.meta))
    has_fee = any(f["fee"] is not None for f in fills)
    has_swing = any(f["swing"] is not None for f in fills)
    lines: list[str] = []

    def say(s=""):
        print(s)
        lines.append(s)

    by_owner = defaultdict(list)
    for f in fills:
        by_owner[f["owner"]].append(f)
    owners = list(dict.fromkeys(list(meta) + list(by_owner)))

    # ------------------------------------------------ per wallet
    res = []
    for o in owners:
        mine = by_owner.get(o, [])
        m = meta.get(o, {})
        row = {"owner": o, "group": m.get("group") or (mine[0]["group"] if mine else ""),
               "pnl": fnum(m.get("pnl")), "pnl_weekly": fnum(m.get("pnl_weekly")),
               "pnl_monthly": fnum(m.get("pnl_monthly")), "winrate_weekly": m.get("winrate_weekly"),
               "winrate_monthly": m.get("winrate_monthly"), "fills": len(mine),
               "inplay_share": (sum(f["inplay"] for f in mine) / len(mine)) if mine else NAN,
               "event_share": (sum(is_event(f, a.swing) for f in mine) / max(1, sum(f["inplay"] for f in mine)))
               if mine and has_swing else NAN}
        for s, _ in SCORES:
            pairs = score_items(mine, s, a.swing)
            n, G, mu, se, _ = cstats(measure(pairs, "rel"))
            _, _, mpp, sepp, _ = cstats(measure(pairs, "pp"))
            _, _, mnet, senet, _ = cstats(measure(pairs, "net"))
            lab = label(n, G, mu, se)
            if s == "live" and lab in ("pozitív mért előny", "negatív mért előny"):
                lab += " (előzetes)"
            row.update({f"n_{s}": n, f"piac_{s}": G, f"clv_{s}": mu, f"se_{s}": se,
                        f"pp_{s}": mpp, f"se_pp_{s}": sepp, f"net_{s}": mnet, f"se_net_{s}": senet,
                        f"címke_{s}": lab})
        if row["címke_pre"] != "kevés adat":
            row["címke"], row["címke_alap"] = row["címke_pre"], "meccs előtti CLV"
        else:
            row["címke"] = "nem eldönthető" if row["n_live"] else "kevés adat"
            row["címke_alap"] = (f"kevés meccs előtti kötés; élő jelzés: {row['címke_live']}"
                                 if row["n_live"] else "kevés kötés")
        row["felirat"] = FELIRAT
        res.append(row)
    res.sort(key=lambda r: (r["group"] != "toplista", -(r["pnl"] or 0)))

    keys = ["owner", "group", "címke", "címke_alap", "pnl", "pnl_weekly", "pnl_monthly",
            "winrate_weekly", "winrate_monthly", "fills", "inplay_share", "event_share"]
    for s, _ in SCORES:
        keys += [f"{k}_{s}" for k in ("címke", "n", "piac", "clv", "se", "pp", "se_pp", "net", "se_net")]
    keys.append("felirat")
    OUT.mkdir(exist_ok=True)
    with (OUT / "wallets.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        cw = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(res)

    # ------------------------------------------------ report
    groups = [g for g in ("toplista", "átlag") if any(f["group"] == g for f in fills)]
    groups += sorted({f["group"] for f in fills} - set(groups))
    say("EDGEHOG – előny-mérés")
    say(FELIRAT)
    say(f"Kötések: {len(fills)} (élő: {sum(f['inplay'] for f in fills)}), tárcák: {len(owners)}, "
        f"piacok: {len({f['market'] for f in fills})}")
    if not has_fee:
        say("FIGYELEM: a bemenetben nincs díj-oszlop (régi formátum) -> nettó CLV nem számolható.")
    if not has_swing:
        say("FIGYELEM: a bemenetben nincs ármozgás-oszlop (régi formátum) -> élőben az esemény "
            "körüli kötések nincsenek kiszűrve.")
    elif any(f["inplay"] for f in fills):
        ev = sum(is_event(f, a.swing) for f in fills)
        say(f"Esemény körüli élő kötések (YES-ár ≥ {a.swing:.0%} mozgás -2..+5 percben): {ev} "
            f"({ev / max(1, sum(f['inplay'] for f in fills)):.0%} az élőkből) – az élő pontszámból kimaradnak.")

    say("\nCSOPORTOK – CLV, hibahatár piaconként csoportosítva (zárójelben: ha minden kötés független volna)")
    say(f"  {'':<22}{'kötés':>7}{'piac':>6}  {'relatív bruttó':>24}  {'abszolút (sz.pont)':>18}  {'relatív nettó':>18}")
    for g in groups:
        gf = [f for f in fills if f["group"] == g]
        for s, name in SCORES:
            pairs = score_items(gf, s, a.swing)
            rel = measure(pairs, "rel")
            n, G, m, se, se_n = cstats(rel)
            _, _, mpp, sepp, _ = cstats(measure(pairs, "pp"))
            _, _, mn, sen, _ = cstats(measure(pairs, "net"))
            extra = ""
            if a.bootstrap:
                extra = f"   bootstrap ±{pct(bootstrap_se(rel, a.bootstrap), False)}"
            say(f"  {g + ', ' + name:<22}{n:>7}{G:>6}  {pct(m):>8} ±{pct(se, False):<6}({pct(se_n, False)})"
                f"  {pp(mpp):>8} ±{pp(sepp, False):<7}  {pct(mn):>8} ±{pct(sen, False):<7}{extra}")

    say("\nRÖVID ÁRMOZGÁS (relatív bruttó CLV, csoportosított hibahatár; m0 = felár a kötés pillanatában)")
    say(f"  {'':<26}" + "".join(f"{h:>18}" for h in ("m0", "1m", "5m", "15m", "close")))
    for g in groups:
        for name, cond in ((("élő, esemény nélkül" if has_swing else "élő"),
                            lambda f: f["inplay"] and not is_event(f, a.swing)),
                           ("élő, esemény körül", lambda f: is_event(f, a.swing)),
                           ("meccs előtt", lambda f: not f["inplay"])):
            gf = [f for f in fills if f["group"] == g and cond(f)]
            if not gf:
                continue
            cells = []
            for h in ("m0", "1m", "5m", "15m", "close"):
                n, G, m, se, _ = cstats(measure([(f, h) for f in gf], "rel"))
                cells.append(f"{pct(m)} ±{pct(se, False)}" if n >= 20 and not math.isnan(se) else f"– (n={n})")
            say(f"  {g + ', ' + name:<26}" + "".join(f"{c:>18}" for c in cells))

    if has_fee:
        say("\nJUPITER DÍJ (kimérve a kötésekből)")
        fee_f = [f for f in fills if f["fee"] is not None]
        tot_fee = sum(f["fee"] for f in fee_f)
        tot_amt = sum(f["p"] * f["n"] for f in fee_f)
        say(f"  összesen {tot_fee:,.0f} $ díj {tot_amt:,.0f} $ forgalomra = {tot_fee / tot_amt:.2%} "
            f"({len(fee_f)} kötés)")
        ks = sorted(f["fee"] / (f["n"] * f["p"] * (1 - f["p"])) for f in fee_f
                    if 0.02 < f["p"] < 0.98 and f["n"] > 0)
        if ks:
            q = lambda x: ks[min(len(ks) - 1, int(x * len(ks)))]
            say(f"  díj ≈ k · szerződés · p · (1 − p); k mediánja {q(0.5):.3f} "
                f"(10%: {q(0.1):.3f}, 90%: {q(0.9):.3f}); díj nélküli kötés: "
                f"{sum(1 for f in fee_f if f['fee'] == 0)}")
        for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1)):
            b = [f for f in fee_f if lo <= f["p"] < hi]
            if b:
                say(f"  ár {lo:.1f}–{hi:.1f}: díj a forgalom {sum(f['fee'] for f in b) / sum(f['p'] * f['n'] for f in b):.2%}-a"
                    f" ({len(b)} kötés)")

    say("\nCÍMKÉK (fő címke = meccs előtti pontszám; élőben csak előzetes jelzés)")
    for g in groups:
        rs = [r for r in res if r["group"] == g]
        say(f"  {g}: " + ", ".join(f"{k}: {v}" for k, v in Counter(r["címke"] for r in rs).most_common()))
        for s, name in SCORES:
            say(f"     {name:<13} " + ", ".join(f"{k}: {v}" for k, v in
                                               Counter(r[f'címke_{s}'] for r in rs).most_common()))
    decided = sum(1 for r in res if r["címke_pre"] != "kevés adat")
    say(f"  Véletlenül várható téves címke {Z:g} hibahatárnál: kb. {decided * 0.023:.1f} pozitív és "
        f"{decided * 0.023:.1f} negatív a {decided} eldönthető tárcából (ha senkinek nincs előnye).")

    top = [r for r in res if r["group"] == "toplista"]
    for s, name in SCORES:
        c, n = corr([r["pnl"] for r in top], [r[f"clv_{s}"] for r in top])
        if not math.isnan(c):
            say(f"  Toplista: P&L és {name} CLV korrelációja: {c:+.2f} ({n} tárca)")

    say(f"\n{'tárca':<10}{'P&L $':>9}{'élő':>6}{'előtt db/piac':>14}{'előtti CLV':>18}{'sz.pont':>8}"
        f"{'nettó':>9}{'élő CLV':>18}   címke")
    for r in top[:40]:
        say(f"{r['owner'][:8]:<10}{(r['pnl'] or 0):>9,.0f}{r['inplay_share']:>6.0%}"
            f"{str(r['n_pre']) + '/' + str(r['piac_pre']):>14}"
            f"{pct(r['clv_pre']) + ' ±' + pct(r['se_pre'], False):>18}{pp(r['pp_pre']):>8}{pct(r['net_pre']):>9}"
            f"{pct(r['clv_live']) + ' ±' + pct(r['se_live'], False):>18}   {r['címke']}")
    pos = [r for r in res if r["címke"] == "pozitív mért előny"]
    if pos:
        say("\nPozitív mért előny (meccs előtti):")
        for r in pos:
            say(f"  {r['owner']} [{r['group']}] CLV {pct(r['clv_pre'])} ± {pct(r['se_pre'], False)} "
                f"({r['n_pre']} kötés, {r['piac_pre']} piac), nettó {pct(r['net_pre'])}, P&L {r['pnl'] or 0:,.0f} $")

    say("\nMÓDSZER: CLV = q/p − 1 a kötött oldalra (eladás = a másik oldal vétele 1 − p áron), "
        "összegsúlyozva; abszolút = q − p szerződéssúlyozva. Bruttó: a Jupiter kötési ára (díj nélkül); "
        "nettó: p + díj/szerződés. Hibahatár: cluster-robust SE piaconként. "
        f"Címke: |CLV| > {Z:g} hibahatár, legalább {MIN_N} kötés és {MIN_G} piac. "
        "Élő referencia: ár 5 perc múlva, esemény körüli kötések nélkül; élőben nincs végleges ítélet.")
    say(f"Részletek: {OUT / 'wallets.csv'}")
    (OUT / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
