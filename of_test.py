"""EDGEHOG order-flow teszt élő Polymarket-meccseken (előre rögzített protokoll, 2026-11-05).

H1 – abszorpció: 1 perces gyertya, |delta| >= 2 × a piac átlagos gyertya-forgalma, miközben a középár
     legfeljebb 1 centet mozdul. Kimenet: a középár változása a delta irányában 15 perc alatt (FŐ), 5 perc
     (másodlagos). Pozitív = kitörés az agresszor irányába, negatív = a passzív oldal nyer (visszafordulás).
     Összevetés: „tolás” gyertyák (ugyanakkora |delta|, de az ár > 1 centet mozdul) és minden gyertya.
H2 – esemény előtti jel: ugrás = a középár >= 10 centet mozdul egy gyertyán belül. Az ugrás előtti 3 gyertya
     normalizált deltája az ugrás irányában, kötésszáma és nagy kötései vs. véletlen gyertyák.

Minta: a 11-04-i probe élő kötéseinek piacai közül 300 véletlen (seed 7), a meccs kezdetétől.
Futtatás: python of_test.py     Kimenet: output/of_bars.csv, output/of_report.txt (újraindítva folytatja)
"""
from __future__ import annotations

import csv
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import flow
import score

OUT = Path("output")
RAW = Path("data/raw")
BARS = OUT / "of_bars.csv"
DONE = OUT / "of_done.json"
N_MARKETS = 300
W = 60


def mids_and_bars(pts, start):
    """1 perces gyertyák: vétel, eladás, kötésszám, nagy kötések, gyertya végi közép (utolsó vétel/eladás átlaga)."""
    live = [q for q in pts if q[0] >= start and 0.03 < q[2] < 0.97]
    if len(live) < 100:
        return None
    t0 = live[0][0]
    sizes = sorted(q[3] * q[2] for q in live)
    big_thr = max(500, sizes[int(0.95 * len(sizes))])
    n = int((live[-1][0] - t0) // W) + 1
    bars = [{"buy": 0.0, "sell": 0.0, "n": 0, "big_b": 0, "big_s": 0, "mid": None} for _ in range(n)]
    lb = ls = None
    for t, d, y, s, tx, rt in live:
        b = bars[int((t - t0) // W)]
        b["n"] += 1
        if d > 0:
            b["buy"] += s
            lb = y
            b["big_b"] += s * y >= big_thr
        else:
            b["sell"] += s
            ls = y
            b["big_s"] += s * y >= big_thr
        if lb is not None and ls is not None:
            b["mid"] = (lb + ls) / 2
    last = None
    for b in bars:                                   # üres gyertyánál az előző közép marad
        if b["mid"] is None:
            b["mid"] = last
        last = b["mid"]
    return bars


def analyse(market, bars):
    vols = [b["buy"] + b["sell"] for b in bars if b["n"]]
    if len(vols) < 30:
        return []
    avg_v, avg_n = statistics.mean(vols), statistics.mean([b["n"] for b in bars if b["n"]])
    rows = []
    for i in range(4, len(bars) - 15):
        b, p = bars[i], bars[i - 1]
        if b["mid"] is None or p["mid"] is None or bars[i + 5]["mid"] is None or bars[i + 15]["mid"] is None:
            continue
        delta = b["buy"] - b["sell"]
        nd = delta / avg_v
        sgn = 1 if delta > 0 else -1
        dm = b["mid"] - p["mid"]
        kind = ""
        if abs(nd) >= 2:
            kind = "absorption" if abs(dm) <= 0.0101 else "push"
        jump = abs(dm) >= 0.10
        pre = bars[i - 3:i]
        jsg = 1 if dm > 0 else -1
        rows.append({
            "market": market, "i": i, "nd": round(nd, 3), "dm": round(dm, 4), "kind": kind,
            "f5": round(sgn * (bars[i + 5]["mid"] - b["mid"]), 4),
            "f15": round(sgn * (bars[i + 15]["mid"] - b["mid"]), 4),
            "jump": int(jump),
            "pre_nd_dir": round(sum((x["buy"] - x["sell"]) for x in pre) / avg_v * jsg, 3),
            "pre_n_rel": round(sum(x["n"] for x in pre) / (3 * avg_n), 3),
            "pre_big": sum(x["big_b"] + x["big_s"] for x in pre),
            "pre_big_dir": sum((x["big_b"] - x["big_s"]) * jsg for x in pre),
        })
    return rows


def collect():
    flow.keep_awake()
    fr = list(csv.DictReader((OUT / "flow_rows.csv").open(encoding="utf-8")))
    live_m = sorted({r["market"]: r["cid"] for r in fr if r["sample"] == "S1L" and r["cid"]}.items())
    rnd = random.Random(7)
    sample = rnd.sample(live_m, min(N_MARKETS, len(live_m)))
    try:
        done = set(json.loads(DONE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        done = set()
    new = not BARS.exists()
    fh = BARS.open("a", newline="", encoding="utf-8")
    keys = ["market", "i", "nd", "dm", "kind", "f5", "f15", "jump", "pre_nd_dir", "pre_n_rel", "pre_big", "pre_big_dir"]
    cw = csv.DictWriter(fh, fieldnames=keys)
    if new:
        cw.writeheader()
    print(f"Minta: {len(sample)} piac", flush=True)
    for k, (mk, cid) in enumerate(sample, 1):
        if mk in done:
            continue
        gid = mk.split("-")[1]
        idx = int(mk.split("-")[2]) if mk.count("-") >= 2 and mk.split("-")[2].isdigit() else 0
        try:
            m = json.loads((RAW / f"poly_market_{gid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = None
        toks = flow.tokens(m)
        start = flow.ts_iso((m or {}).get("gameStartTime"))
        if toks and len(toks) == 2 and idx < 2 and start:
            pts, why = flow.market_points(cid, toks[idx], toks[1 - idx], start - 600)
            if pts and not why:
                bars = mids_and_bars(pts, start)
                if bars:
                    cw.writerows(analyse(mk, bars))
                    fh.flush()
            else:
                flow.DIAG[f"piac kihagyva: {why or 'letöltési hiba'}"] += 1
        else:
            flow.DIAG["nincs kezdési idő / token"] += 1
        done.add(mk)
        if k % 10 == 0:
            DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
            print(f"  {k}/{len(sample)} piac", flush=True)
    fh.close()
    DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def report():
    rows = list(csv.DictReader(BARS.open(encoding="utf-8")))
    f = lambda r, c: float(r[c])
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    def st(rs, col):
        it = [(f(r, col), 1.0, r["market"]) for r in rs]
        n, G, m, se, _ = score.cstats(it)
        if n < 5:
            return f"– (n={n})"
        med = statistics.median(v for v, _, _ in it)
        return f"{m * 100:+.2f} ±{se * 100:.2f} sz.pont (medián {med * 100:+.2f}; n={n}, piac={G})"

    say("EDGEHOG order-flow teszt – élő Polymarket-meccsek, 1 perces gyertyák (előre rögzített protokoll)")
    say(f"Gyertyák: {len(rows)}, piacok: {len({r['market'] for r in rows})}\n")
    ab = [r for r in rows if r["kind"] == "absorption"]
    pu = [r for r in rows if r["kind"] == "push"]
    say("H1 – ABSZORPCIÓ (|delta| >= 2× átlag, ár <= 1 cent): mozgás a DELTA irányában")
    say(f"  FŐ: 15 perc: {st(ab, 'f15')}")
    say(f"      5 perc: {st(ab, 'f5')}")
    say(f"  tolás (ugyanekkora delta, ár > 1 cent): 15p {st(pu, 'f15')}; 5p {st(pu, 'f5')}")
    say(f"  minden gyertya (delta irányában):       15p {st(rows, 'f15')}; 5p {st(rows, 'f5')}")
    strong = [r for r in ab if abs(f(r, "nd")) >= 4]
    say(f"  erős abszorpció (|delta| >= 4× átlag):  15p {st(strong, 'f15')}")
    # találati arány: hány abszorpció után ment az ár a delta irányába / ellene / nem mozdult
    for name, rs in (("abszorpció", ab), ("tolás", pu)):
        pos = sum(f(r, "f15") > 0.005 for r in rs)
        neg = sum(f(r, "f15") < -0.005 for r in rs)
        say(f"  {name}: 15 perc múlva a delta irányában {pos}, ellene {neg}, ±0,5 centen belül {len(rs) - pos - neg}")

    say("\nH2 – ESEMÉNY ELŐTTI JEL (ugrás >= 10 cent egy gyertyán belül), az ugrás előtti 3 gyertya")
    jm = [r for r in rows if r["jump"] == "1"]
    ctl = [r for r in rows if r["jump"] != "1"]
    for col, label in (("pre_nd_dir", "normalizált delta az ugrás irányában"),
                       ("pre_n_rel", "kötésszám az átlaghoz képest (1 = átlag)"),
                       ("pre_big_dir", "nagy kötések nettó száma az ugrás irányában")):
        n, G, m, se, _ = score.cstats([(f(r, col), 1.0, r["market"]) for r in jm])
        n2, G2, m2, se2, _ = score.cstats([(f(r, col), 1.0, r["market"]) for r in ctl])
        say(f"  {label}: ugrás előtt {m:+.3f} ±{se:.3f} (n={n}, piac={G}) | többi gyertya {m2:+.3f} ±{se2:.3f}")
    say("\nOlvasat: H1 pozitív = abszorpció után az agresszor irányába tör ki az ár; negatív = a passzív oldal nyer.")
    say("H2: ha az ugrás előtti értékek nem térnek el a többi gyertyától, a kötésfolyam nem jelzi előre az eseményeket.")
    say("Diagnosztika: " + "; ".join(f"{k}: {v}" for k, v in flow.DIAG.most_common(6)))
    (OUT / "of_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--report" not in sys.argv:
        collect()
    report()
