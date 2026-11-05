"""EDGEHOG: CLV a középárhoz mérve, a saját árhatás leválasztásával.

A kötési árhoz mért CLV keveri a kereskedő előnyét és a kötés költségét (spread). Itt:
  * közép-CLV: a kötés előtti középárhoz mérjük a későbbi középárat (spread nélkül).
  * placebo: ugyanazon a piacon, ugyanabba az irányba, hasonló méretben (0,5–2×), ±30 percen belül
    kötött többi Polymarket taker-kötés ugyanígy mért ármozgása. A mechanikus árhatás mindkettőben
    benne van, így  többlet = Jupiter-kötés − placebo  az "átlagos hasonló kötésnél" jobb vagy
    rosszabb irányválasztás.

Két rész:
  A) meccs előtti kötések, mind (letöltés nélkül): meccs előtt a perces ár (m0) ≈ közép
     (verify_premium: +0,03 sz.pont eltérés), ezért közép-CLV = q / m0 − 1 a kötött oldalra.
  B) minta (élő + meccs előtti) a Polymarket valódi kötéseiből: közép 1, 5, 15 perccel később,
     plusz a placebo. Élőben ez az egyetlen megbízható mérés (a perces ár ott késik).

Közép = az utolsó vételi és eladási taker-kötés átlaga az adott pillanat előtti 5 percben.
Minden szám a kereskedő szemszögéből, relatív (CLV-egység, összegsúlyozva), piaconként
csoportosított hibahatárral. A Jupiter-díj és a spread NINCS benne (az a költség-oldal).

Futtatás: python midclv.py [--sample 1000]   (B rész ~45–60 perc; a letöltés gyorsítótárazott)
Kimenet:  output/midclv_report.txt, output/midclv_fills.csv
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

import score
import verify_premium as vp

OUT = Path("output")
ROUTER = "0x5b6331e7ff0831a3fe2ed12004747db1a9c911a4"   # a Jupiter továbbító tárcája a Polymarketen
HORIZ = (("1m", 60), ("5m", 300), ("15m", 900))
fnum = vp.fnum


def mid_at(pts, ts, tau, exclude_tx=None, window=300):
    """Közép tau-nál: az utolsó vételi és eladási taker-kötés átlaga (tau-window, tau].
    pts időrendben, ts = [q["t"] for q in pts] (bináris kereséshez)."""
    lb = ls = None
    i = bisect.bisect_right(ts, tau) - 1
    while i >= 0 and ts[i] > tau - window and (lb is None or ls is None):
        q = pts[i]
        if not (exclude_tx and q["tx"] == exclude_tx):
            if q["d"] == 1 and lb is None:
                lb = q
            elif q["d"] == -1 and ls is None:
                ls = q
        i -= 1
    if lb and ls:
        return (lb["y"] + ls["y"]) / 2
    return None


def side(v, d):
    return v if d == 1 else 1 - v


def rel_markout(pts, ts, t0, d, exclude_tx):
    m0 = mid_at(pts, ts, t0 - 1, exclude_tx)
    if m0 is None or not (0.02 <= side(m0, d) <= 0.98):
        return None, {}
    out = {}
    for name, h in HORIZ:
        mh = mid_at(pts, ts, t0 + h, None)
        out[name] = None if mh is None else side(mh, d) / side(m0, d) - 1
    return m0, out


def part_a(say):
    """Meccs előtti kötések, mind: közép-CLV a perces árhoz (m0) mérve."""
    fills = score.load_fills(OUT / "fills_clv.csv")
    for f in fills:                                  # a kötött oldal középára a kötéskor
        if "m0" in f["q"]:
            f["mid0"] = f["q"]["m0"]
    say("A) MECCS ELŐTTI KÖTÉSEK, MIND – CLV a kötéskori középárhoz (perces ár) mérve")
    say(f"  {'':<14}{'kötés':>7}{'piac':>6}   {'kötési árhoz (régi)':>22}   {'középárhoz':>20}   {'különbség = spread':>20}")
    for g in ("toplista", "átlag"):
        it_old, it_mid = [], []
        for f in fills:
            if f["group"] != g or f["inplay"] or "mid0" not in f:
                continue
            h = score.pre_ref(f)
            if not h:
                continue
            q, p, m = f["q"][h], f["p"], f["mid0"]
            if not (0.02 <= m <= 0.98 and 0.01 <= p <= 0.99):
                continue
            it_old.append((q / p - 1, p * f["n"], f["market"]))
            it_mid.append((q / m - 1, m * f["n"], f["market"]))
        n, G, mo, so, _ = score.cstats(it_old)
        _, _, mm, sm, _ = score.cstats(it_mid)
        say(f"  {g:<14}{n:>7}{G:>6}   {score.pct(mo):>10} ±{score.pct(so, False):<9}"
            f"   {score.pct(mm):>9} ±{score.pct(sm, False):<8}   {score.pct(mm - mo):>12}")


def part_b(say, sample_n, seed):
    fills = []
    with (OUT / "fills_clv.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            p, n, t = fnum(r["price"]), fnum(r["n"]), fnum(r["t"])
            if r["market"].startswith("POLY-") and p and n and t and 0.03 <= p <= 0.97 and n >= 10:
                fills.append(r)
    rnd = random.Random(seed)
    by_m = defaultdict(list)
    for f in fills:
        by_m[f["market"]].append(f)
    sample = []
    for kind, share in (("True", 0.6), ("False", 0.4)):
        mk = [m for m, fs in by_m.items() if any(f["inplay"] == kind for f in fs)]
        rnd.shuffle(mk)
        got = 0
        for m in mk:
            fs = [f for f in by_m[m] if f["inplay"] == kind]
            take = rnd.sample(fs, min(3, len(fs)))
            sample += take
            got += len(take)
            if got >= sample_n * share:
                break
    sample.sort(key=lambda f: f["market"])
    print(f"B) minta: {len(sample)} kötés ({sum(f['inplay'] == 'True' for f in sample)} élő), "
          f"{len({f['market'] for f in sample})} piac", flush=True)

    rows, cache = [], {}
    for i, f in enumerate(sample, 1):
        parts = f["market"].split("-")
        gid, idx = parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        m = vp.meta(gid)
        toks = vp.tokens(m) if m else None
        cid = (m or {}).get("conditionId")
        if not toks or not cid or len(toks) != 2 or idx >= 2:
            vp.DIAG["nincs piacadat / nem kétkimenetes"] += 1
            continue
        if f["market"] not in cache:
            t_min = min(float(x["t"]) for x in sample if x["market"] == f["market"]) - 2400
            raw = vp.market_trades(cid, t_min) or []
            pts = []
            for tr in raw:
                px, sz, ts_ = fnum(tr.get("price")), fnum(tr.get("size")), fnum(tr.get("timestamp"))
                if px is None or sz is None or ts_ is None:
                    continue
                sd = 1 if str(tr.get("side")).upper() == "BUY" else -1
                a = str(tr.get("asset"))
                if a == toks[idx]:
                    dd, yy = sd, px
                elif a == toks[1 - idx]:
                    dd, yy = -sd, 1 - px
                else:
                    continue
                pts.append({"t": ts_, "d": dd, "y": yy, "sz": sz, "tx": tr.get("transactionHash"),
                            "w": str(tr.get("proxyWallet") or "").lower()})
            pts.sort(key=lambda q: q["t"])
            cache = {f["market"]: (pts, [q["t"] for q in pts])}                   # csak az aktuális piacot tartjuk memóriában
        pts, ts = cache[f["market"]]
        if not pts:
            continue
        t, n = float(f["t"]), float(f["n"])
        buy, yes = f["buy"] == "True", f["yes"] == "True"
        d = 1 if buy == yes else -1
        # a Jupiter-kötés Polymarket-párja (router tárca, azonos irány, méret ±3%, -90..+30 s)
        own = [q for q in pts if q["w"] == ROUTER and q["d"] == d and t - 90 <= q["t"] <= t + 30]
        tx_sz = defaultdict(float)
        for q in own:
            tx_sz[q["tx"]] += q["sz"]
        match = min((q for q in own if abs(tx_sz[q["tx"]] - n) / n <= 0.03),
                    key=lambda q: abs(q["t"] - t), default=None)
        t0 = match["t"] if match else t
        tx = match["tx"] if match else None
        m0, mk = rel_markout(pts, ts, t0, d, tx)
        if m0 is None:
            vp.DIAG["nincs közép a kötés előtt"] += 1
            continue
        # placebo: más tárcák hasonló kötései ugyanígy
        plac = {name: [] for name, _ in HORIZ}
        lo, hi = bisect.bisect_left(ts, t0 - 1800), bisect.bisect_right(ts, t0 + 1800)
        for q in pts[lo:hi]:
            if q["w"] == ROUTER or q["d"] != d or q["tx"] == tx:
                continue
            if not (0.5 * n <= q["sz"] <= 2 * n):
                continue
            _, pm = rel_markout(pts, ts, q["t"], d, q["tx"])
            for name, _ in HORIZ:
                if pm.get(name) is not None:
                    plac[name].append(pm[name])
        row = {"owner": f["owner"], "group": f["group"], "market": f["market"], "inplay": f["inplay"],
               "t": t, "d": d, "n": n, "matched": bool(match), "mid0": m0, "w": side(m0, d) * n}
        for name, _ in HORIZ:
            row[f"mid_{name}"] = mk.get(name)
            pl = plac[name]
            row[f"plac_{name}"] = sum(pl) / len(pl) if pl else None
            row[f"plac_n_{name}"] = len(pl)
            row[f"excess_{name}"] = (mk[name] - row[f"plac_{name}"]) if mk.get(name) is not None and pl else None
        rows.append(row)
        if i % 50 == 0:
            print(f"  {i}/{len(sample)} kötés, eddig mérve: {len(rows)}", flush=True)

    with (OUT / "midclv_fills.csv").open("w", newline="", encoding="utf-8") as fh:
        cw = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["owner"])
        cw.writeheader()
        cw.writerows(rows)

    say("\nB) MINTA a Polymarket valódi kötéseiből – közép-CLV (relatív, összegsúlyozva, ± piaconként)")
    say(f"   mérve: {len(rows)} kötés, Polymarket-pár: {sum(r['matched'] for r in rows)}")
    for g in ("toplista", "átlag"):
        for kind, label in (("False", "meccs előtt"), ("True", "élő")):
            rs = [r for r in rows if r["group"] == g and r["inplay"] == kind]
            if not rs:
                continue
            say(f"\n  {g}, {label} ({len(rs)} kötés)")
            for name, _ in HORIZ:
                cells = []
                for key in ("mid", "plac", "excess"):
                    it = [(r[f"{key}_{name}"], r["w"], r["market"]) for r in rs if r[f"{key}_{name}"] is not None]
                    n, G, mu, se, _ = score.cstats(it)
                    cells.append(f"{score.pct(mu):>8} ±{score.pct(se, False):<7}(n={n})")
                say(f"    {name:>4}:  Jupiter-kötés {cells[0]}   hasonló PM-kötések {cells[1]}   többlet {cells[2]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--only-a", action="store_true", help="csak az A rész (letöltés nélkül)")
    a = ap.parse_args()
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    say("EDGEHOG – CLV a középárhoz (spread nélkül), saját árhatás nélkül")
    say("Statisztikai becslés nyilvános adatokból, nem minősítés.\n")
    part_a(say)
    (OUT / "midclv_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not a.only_a:
        part_b(say, a.sample, a.seed)
        say("\nDiagnosztika: " + "; ".join(f"{k}: {v}" for k, v in vp.DIAG.most_common(6)))
        say("\nOlvasat: 'többlet' > 0 = a Jupiter-kötés jobb irányba ment, mint az átlagos hasonló méretű"
            " Polymarket-kötés ugyanott (a mechanikus árhatás mindkettőben benne van).")
    (OUT / "midclv_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
