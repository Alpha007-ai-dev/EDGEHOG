"""EDGEHOG: végrehajtási költség egy nagy, VÉLETLEN Jupiter Predict-mintán (2026-11-10).

Kérdés: a toplistán mért ~4,6% / belépés költség (középárhoz képest) igaz-e a Jupiter Predict
kereskedőinek egészére is?

Minta: 300 véletlen tárca (seed 11) a gyűjtő (collect.py) által nov. 4–10. között látott 861 tárcából.
Tárcánként a legutóbbi legfeljebb 150 kötés, ebből a 2026-11-01 utániak, Polymarket-piacokon.
Kötésenként: a Polymarket-középár közvetlenül a kötés előtt (utolsó vételi és eladási taker-kötés
átlaga, 5 percen belül – ugyanaz, mint flow.py), a kötött oldal ára, a Jupiter-díj (feeUsd).
Költség = kontraktus × (ár − közép) + díj.  EGY belépés költsége, nem oda-vissza.

Futtatás:  python cost_sample.py           (folytatható; kimenet: output/cost_rows.csv, output/cost_report.txt)
           python cost_sample.py --report  (csak jelentés)
"""
from __future__ import annotations

import csv
import json
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import flow
import probe
import score

OUT = Path("output")
RAW = Path("data/raw")
ROWS = OUT / "cost_rows.csv"
DONE = OUT / "cost_done.json"
SINCE = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
N_WALLETS, PER_WALLET, SEED = 300, 150, 11
FIELDS = ["owner", "market", "t", "phase", "n", "side_price", "side_mid0", "fee", "cost_price", "matched",
          "jup_pp_5m", "measurable", "reason", "on_leaderboard"]


def key():
    k = os.environ.get("JUPITER_API_KEY", "").strip()
    if not k and Path(".jupkey").exists():
        k = Path(".jupkey").read_text(encoding="utf-8").strip()
    if not k:
        sys.exit("Nincs Jupiter API-kulcs (JUPITER_API_KEY vagy .jupkey).")
    return k


def gamma_meta(gid: str):
    p = RAW / f"poly_market_{gid}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    r = flow.call(f"https://gamma-api.polymarket.com/markets/{gid}", {})
    if r is None or not r.ok:
        return None
    m = r.json()
    p.write_text(json.dumps(m), encoding="utf-8")
    return m


def leaderboard_wallets():
    s = set()
    for p in RAW.glob("lb_*_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            for r in d.get("data") or []:
                s.add(r.get("ownerPubkey"))
        except (ValueError, AttributeError):
            pass
    return s


def collect():
    flow.keep_awake()
    probe.KEY = key()
    pool = probe.collector_wallets()
    rnd = random.Random(SEED)
    wallets = rnd.sample(pool, min(N_WALLETS, len(pool)))
    lb = leaderboard_wallets()
    print(f"Minta: {len(wallets)} véletlen tárca a gyűjtő {len(pool)} tárcájából "
          f"(ebből toplistás: {sum(w in lb for w in wallets)})", flush=True)
    # 1) kötések tárcánként
    fills_by_m = defaultdict(list)
    for i, w in enumerate(wallets, 1):
        for f in probe.fills(w, PER_WALLET):
            mid = f.get("marketId") or ""
            price, n, buy, yes, t, fee = probe.fill_fields(f)
            if not mid.startswith("POLY-") or price is None or not n or t is None or t < SINCE:
                continue
            fills_by_m[mid].append({"owner": w, "t": t, "price": price, "n": n, "buy": buy, "yes": yes,
                                    "fee": fee or 0.0, "lb": w in lb})
        if i % 25 == 0:
            print(f"  kötéstörténet: {i}/{len(wallets)} tárca, eddig {sum(map(len, fills_by_m.values()))} kötés, "
                  f"{len(fills_by_m)} piac", flush=True)
    print(f"Kötések: {sum(map(len, fills_by_m.values()))}, piacok: {len(fills_by_m)}", flush=True)
    # 2) középár piaconként (folytatható)
    try:
        done = set(json.loads(DONE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        done = set()
    new = not ROWS.exists()
    fh = ROWS.open("a", newline="", encoding="utf-8")
    cw = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        cw.writeheader()
    for k, (mk, fs) in enumerate(sorted(fills_by_m.items()), 1):
        if mk in done:
            continue
        parts = mk.split("-")
        gid, idx = parts[1], (int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0)
        m = gamma_meta(gid)
        toks, cid = flow.tokens(m), (m or {}).get("conditionId")
        start = flow.ts_iso((m or {}).get("gameStartTime"))
        out = []
        base = lambda f: {"owner": f["owner"], "market": mk, "t": f["t"], "n": f["n"], "fee": f["fee"],
                          "on_leaderboard": int(f["lb"]),
                          "phase": "unknown" if not start else ("live" if f["t"] >= start else "pre")}
        if not toks or not cid or len(toks) != 2 or idx > 1:
            out = [{**base(f), "measurable": 0, "reason": "nincs piacadat / nem kétkimenetes"} for f in fs]
        else:
            pts, why = flow.market_points(cid, toks[idx], toks[1 - idx], min(f["t"] for f in fs) - 400)
            ts = [q[0] for q in pts] if pts else []
            for f in fs:
                d = 1 if f["buy"] == f["yes"] else -1
                sp = f["price"] if f["buy"] else 1 - f["price"]
                row = {**base(f), "side_price": sp}
                if not pts or why:
                    out.append({**row, "measurable": 0, "reason": why or "letöltési hiba"})
                    continue
                own = [q for q in pts if q[5] and q[1] == d and f["t"] - 90 <= q[0] <= f["t"] + 30]
                tx_sz = defaultdict(float)
                for q in own:
                    tx_sz[q[4]] += q[3]
                mt = min((q for q in own if abs(tx_sz[q[4]] - f["n"]) / f["n"] <= 0.03),
                         key=lambda q: abs(q[0] - f["t"]), default=None)
                t0 = mt[0] if mt else f["t"]
                s0, mkout = flow.markout(pts, ts, t0, d, mt[4] if mt else None)
                if s0 is None:
                    out.append({**row, "measurable": 0, "reason": "nincs közép a kötés előtt"})
                    continue
                v5 = mkout.get("5m")
                out.append({**row, "side_mid0": s0, "cost_price": f["n"] * (sp - s0), "matched": int(mt is not None),
                            "jup_pp_5m": v5[0] if v5 else None, "measurable": 1, "reason": ""})
        cw.writerows(out)
        fh.flush()
        done.add(mk)
        if k % 25 == 0:
            DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
            print(f"  középár: {k}/{len(fills_by_m)} piac", flush=True)
    fh.close()
    DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")


def report():
    rows = list(csv.DictReader(ROWS.open(encoding="utf-8")))
    f = lambda r, c: float(r[c]) if r.get(c) not in (None, "", "None") else None
    ok = [r for r in rows if r["measurable"] == "1"]
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    def block(label, rs):
        if not rs:
            return f"| {label} | 0 | | | | | |"
        nv = sum(f(r, "n") * f(r, "side_mid0") for r in rs)
        pc = sum(f(r, "cost_price") for r in rs)
        fe = sum(f(r, "fee") for r in rs)
        return (f"| {label} | {len(rs):,} | ${nv:,.0f} | ${pc:,.0f} | ${fe:,.0f} | **${pc + fe:,.0f}** | "
                f"{(pc + fe) / nv:.2%} |")

    say("# EDGEHOG – végrehajtási költség 300 véletlen Jupiter Predict-tárcán")
    say("Statisztikai becslés nyilvános adatokból. EGY belépés költsége a kötés előtti Polymarket-középárhoz képest "
        "(spread + csúszás együtt) + Jupiter-díj; nem oda-vissza.\n")
    say(f"Kötések: {len(rows):,}, ebből mérhető {len(ok):,} ({len(ok) / max(1, len(rows)):.0%}); "
        f"tárcák mérhető kötéssel: {len({r['owner'] for r in ok})}\n")
    say("| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a |")
    say("|---|---:|---:|---:|---:|---:|---:|")
    say(block("mind", ok))
    say(block("élő", [r for r in ok if r["phase"] == "live"]))
    say(block("meccs előtt", [r for r in ok if r["phase"] == "pre"]))
    say(block("nem sport / ismeretlen kezdés", [r for r in ok if r["phase"] == "unknown"]))
    say(block("toplistás tárcák", [r for r in ok if r["on_leaderboard"] == "1"]))
    say(block("nem toplistás tárcák", [r for r in ok if r["on_leaderboard"] != "1"]))
    say("\n**Ár szerint** (a kötött oldal középára):\n")
    say("| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a |")
    say("|---|---:|---:|---:|---:|---:|---:|")
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        say(block(f"{lo:.1f}–{min(hi, 1):.1f}", [r for r in ok if lo <= f(r, "side_mid0") < hi]))
    # tárcánkénti eloszlás + hibahatár (piaconként csoportosítva) a kötésenkénti relatív költségre
    by_w = defaultdict(list)
    for r in ok:
        by_w[r["owner"]].append(r)
    shares = sorted((sum(f(r, "cost_price") + f(r, "fee") for r in rs) / sum(f(r, "n") * f(r, "side_mid0") for r in rs))
                    for rs in by_w.values() if len(rs) >= 5)
    if shares:
        q = lambda p: shares[min(len(shares) - 1, int(p * len(shares)))]
        say(f"\nTárcánként (legalább 5 mérhető kötés, {len(shares)} tárca): medián {q(.5):.2%}, "
            f"10%: {q(.1):.2%}, 25%: {q(.25):.2%}, 75%: {q(.75):.2%}, 90%: {q(.9):.2%}")
    it = [((f(r, "cost_price") + f(r, "fee")) / (f(r, "n") * f(r, "side_mid0")), f(r, "n") * f(r, "side_mid0"), r["market"])
          for r in ok if f(r, "n") * f(r, "side_mid0") > 0]
    n, G, m, se, _ = score.cstats(it)
    say(f"Összegsúlyozott költség hibahatárral (piaconként csoportosítva): {m:.2%} ± {se:.2%} (n={n}, piac={G})")
    mk = [(f(r, "jup_pp_5m"), 1.0, r["market"]) for r in ok if f(r, "jup_pp_5m") is not None]
    n2, G2, m2, se2, _ = score.cstats(mk)
    say(f"5 perces középár-mozgás a kereskedő javára: {m2 * 100:+.2f} ± {se2 * 100:.2f} sz.pont (n={n2})")
    reasons = Counter(r["reason"] for r in rows if r["measurable"] != "1")
    say("\nNem mérhető okok: " + ", ".join(f"{k}: {v}" for k, v in reasons.most_common()))
    say("Összevetés: a toplistás mintán (nov. 4.) 4,62% volt, 102 tárca, 10 487 kötés.")
    (OUT / "cost_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--report" not in sys.argv:
        collect()
    report()
