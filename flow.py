"""EDGEHOG Flow Intelligence – előre rögzített protokoll szerinti éjszakai mérés (2026-11-04).

Kérdés: a Jupiter Predicten át érkező forgalom után a Polymarket-középár kevésbé mozdul-e a kereskedő
javára, mint az ugyanazon a piacon, ugyanabba az irányba, hasonló méretben kötött más Polymarket
taker-kötések után? (alacsonyabb relatív adverse-selection kockázat)

Minták (ebben a sorrendben fut, menet közben ment, újraindítva folytatja):
  S2  forrásszint: a Jupiter továbbító tárcájának ÖSSZES Polymarket taker-kötése
      2026-11-01 00:00 – 2026-11-04 00:00 UTC (data-api v2, user=router). Tárcától független.
  S1L toplista + átlagcsoport élő kötései (output/fills_clv.csv), Polymarket-párral és késleltetéssel.
  S1P ugyanezek meccs előtti kötései (alacsony prioritás; ha nem fut le, nem baj).

Mérés kötésenként: közép = utolsó vételi és eladási taker-kötés átlaga az előző 5 percben;
markout = a kötött oldal középárának változása 1/5/15 perc alatt (sz.pont és relatív).
Kontroll: más tárcák (nem a router) azonos irányú, 0,5–2× méretű taker-kötései ugyanazon a piacon,
ablakok: ±10 mp, ±60 mp (FŐ), ±30 perc, és csak-előtte (−60..0 mp). Többlet = Jupiter − kontroll-átlag.

Futtatás:  python flow.py            (gyűjtés + jelentés; több óra)
           python flow.py --report   (csak jelentés a már mentett sorokból)
Kimenet:   output/flow_rows.csv (soronként egy kötés, mérhetetlenek is, okkal), output/flow_report.txt
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

import score

API = "https://data-api.polymarket.com/v2/trades"
GAMMA = "https://gamma-api.polymarket.com/markets"
ROUTER = "0x5b6331e7ff0831a3fe2ed12004747db1a9c911a4"
S2_START = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
S2_END = int(datetime(2026, 11, 4, tzinfo=timezone.utc).timestamp())
HORIZ = (("1m", 60), ("5m", 300), ("15m", 900))
WINDOWS = (("w10", -10, 10), ("w60", -60, 60), ("w1800", -1800, 1800), ("b60", -60, 0))
PRIMARY = ("S2", "live", "5m", "w60")
MAX_PAGES = 25
RAW = Path("data/raw")
OUT = Path("output")
ROWS = OUT / "flow_rows.csv"
DONE = OUT / "flow_done.json"
S = requests.Session()
S.headers["User-Agent"] = "edgehog-flow/0.1"
_last = [0.0]
DIAG = Counter()


# ------------------------------------------------------------------ util
def keep_awake():
    """Windows: amíg fut, ne aludjon el a gép (a folyamat végén magától megszűnik)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    except Exception:
        pass


def call(url, params):
    wait = 0.15 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for i in range(5):
        try:
            r = S.get(url, params=params, timeout=40)
        except requests.RequestException as e:
            DIAG[f"hálózat: {type(e).__name__}"] += 1
            time.sleep(5 * (i + 1))
            continue
        _last[0] = time.time()
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, 3 * 2 ** i))
            continue
        return r
    return None


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def rows_of(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get("data"), list):
        return d["data"]
    return None


def norm(tr):
    g = lambda *ks: next((tr[k] for k in ks if k in tr and tr[k] is not None), None)
    return {"price": fnum(g("price")), "size": fnum(g("size")), "t": fnum(g("timestamp")),
            "side": str(g("side") or "").upper(), "asset": str(g("token_id", "asset", "asset_id") or ""),
            "tx": g("transaction_hash", "transactionHash"),
            "w": str(g("proxy_wallet", "proxyWallet") or "").lower(),
            "cid": g("condition_id", "conditionId"), "oi": g("outcome_index", "outcomeIndex")}


def paged(params, stop=None):
    """v2 lapozás; stop(rows_so_far) -> True esetén megáll. Vissza: (sorok, teljes?)"""
    out, cursor = [], None
    for _ in range(MAX_PAGES):
        p = dict(params, **({"cursor": cursor} if cursor else {}))
        r = call(API, p)
        if r is None or not r.ok:
            DIAG[f"v2 HTTP {getattr(r, 'status_code', '-')}: {getattr(r, 'text', '')[:80]!r}"] += 1
            return None, False
        d = r.json()
        rs = rows_of(d)
        if rs is None:
            DIAG["v2 ismeretlen válasz"] += 1
            return None, False
        out += [norm(x) for x in rs]
        cursor = (d.get("pagination") or {}).get("next_cursor") if isinstance(d, dict) else None
        if not cursor:
            return out, True
        if stop and stop(out):
            return out, True
    return out, False


# ------------------------------------------------------------ market data
def market_meta(cid: str):
    """gamma piacadat (tokenek, kezdési idő) conditionId alapján, gyorsítótárral."""
    path = RAW / f"poly_cond_{cid[:18]}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    m = None
    for extra in ({}, {"closed": "true"}):
        r = call(GAMMA, {"condition_ids": cid, **extra})
        if r is not None and r.ok:
            d = r.json()
            lst = d if isinstance(d, list) else (d.get("data") or d.get("markets") or [])
            if lst:
                m = lst[0]
                break
    if m:
        path.write_text(json.dumps(m), encoding="utf-8")
    return m


def tokens(m):
    t = (m or {}).get("clobTokenIds")
    if isinstance(t, str):
        try:
            t = json.loads(t)
        except ValueError:
            return None
    return t


def ts_iso(v):
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    if len(s) > 3 and s[-3] in "+-" and s[-2:].isdigit():
        s += ":00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def market_points(cid: str, yes_token: str, other_token: str, t_min: float):
    """A piac taker-kötései YES-térben, időrendben, t_min-ig visszalapozva."""
    raw, complete = paged({"condition": cid, "limit": 1000, "filter_type": "TOKENS", "filter_amount": 1},
                          stop=lambda rs: any(x["t"] and x["t"] <= t_min for x in rs[-1000:]))
    if raw is None:
        return None, "letöltési hiba"
    oldest = min((x["t"] for x in raw if x["t"]), default=None)
    pts = []
    for x in raw:
        if x["price"] is None or x["size"] is None or x["t"] is None:
            continue
        sd = 1 if x["side"] == "BUY" else -1
        if x["asset"] == yes_token:
            d, y = sd, x["price"]
        elif x["asset"] == other_token:
            d, y = -sd, 1 - x["price"]
        else:
            continue
        pts.append((x["t"], d, y, x["size"], x["tx"], x["w"] == ROUTER))
    pts.sort(key=lambda q: q[0])
    reason = None
    if oldest is not None and oldest > t_min and not complete:
        reason = "lapozási korlát"
    return pts, reason


# ------------------------------------------------------------- measures
def mid_at(pts, ts, tau, exclude_tx=None, window=300):
    lb = ls = None
    i = bisect.bisect_right(ts, tau) - 1
    while i >= 0 and ts[i] > tau - window and (lb is None or ls is None):
        q = pts[i]
        if not (exclude_tx and q[4] == exclude_tx):
            if q[1] == 1 and lb is None:
                lb = q[2]
            elif q[1] == -1 and ls is None:
                ls = q[2]
        i -= 1
    return (lb + ls) / 2 if lb is not None and ls is not None else None


def side(v, d):
    return v if d == 1 else 1 - v


def markout(pts, ts, t0, d, tx):
    m0 = mid_at(pts, ts, t0 - 1, tx)
    if m0 is None or not (0.02 <= side(m0, d) <= 0.98):
        return None, None
    s0 = side(m0, d)
    out = {}
    for name, h in HORIZ:
        mh = mid_at(pts, ts, t0 + h)
        out[name] = None if mh is None else (side(mh, d) - s0, side(mh, d) / s0 - 1)
    return s0, out


def measure(pts, ts, t0, d, n, tx):
    """Egy Jupiter-kötés: saját markout + kontrollok ablakonként. Vissza: dict vagy (None, ok)."""
    s0, mk = markout(pts, ts, t0, d, tx)
    if s0 is None:
        return None, "nincs közép a kötés előtt"
    row = {"side_mid0": s0}
    for name, _ in HORIZ:
        v = mk.get(name)
        row[f"jup_pp_{name}"] = v[0] if v else None
        row[f"jup_rel_{name}"] = v[1] if v else None
    lo, hi = bisect.bisect_left(ts, t0 - 1800), bisect.bisect_right(ts, t0 + 1800)
    ctrl = []
    for q in pts[lo:hi]:
        if q[5] or q[1] != d or q[4] == tx or not (0.5 * n <= q[3] <= 2 * n):
            continue
        _, pm = markout(pts, ts, q[0], d, q[4])
        if pm:
            ctrl.append((q[0] - t0, pm))
    for wname, a, b in WINDOWS:
        cs = [pm for dt, pm in ctrl if a <= dt <= b]
        row[f"ctrl_n_{wname}"] = len(cs)
        for name, _ in HORIZ:
            vals = [pm[name][0] for pm in cs if pm.get(name)]
            c = sum(vals) / len(vals) if vals else None
            j = row[f"jup_pp_{name}"]
            row[f"exc_pp_{wname}_{name}"] = (j - c) if j is not None and c is not None else None
    hour = [q for q in pts[bisect.bisect_left(ts, t0 - 1800):bisect.bisect_right(ts, t0 + 1800)]]
    row["trades_per_hour"] = len(hour)
    return row, None


# ------------------------------------------------------------- storage
FIELDS = (["sample", "owner", "group", "market", "cid", "t0", "d", "n", "phase", "matched",
           "lat_jup", "lat_pm", "measurable", "reason", "side_price", "side_mid0", "trades_per_hour"]
          + [f"jup_{k}_{h}" for h, _ in HORIZ for k in ("pp", "rel")]
          + [f"ctrl_n_{w}" for w, _, _ in WINDOWS]
          + [f"exc_pp_{w}_{h}" for w, _, _ in WINDOWS for h, _ in HORIZ])


def writer():
    new = not ROWS.exists()
    fh = ROWS.open("a", newline="", encoding="utf-8")
    cw = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
    if new:
        cw.writeheader()
    return fh, cw


def load_done():
    try:
        return set(json.loads(DONE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def save_done(done):
    DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")


# ------------------------------------------------------------ samples
def run_s2(done, cw, fh):
    key = "S2"
    print("S2: a router tárca kötései 11-01..11-04 UTC …", flush=True)
    path = RAW / f"router_trades_{S2_START}_{S2_END}.json"
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        rows, complete = paged({"user": ROUTER, "start": S2_START, "end": S2_END, "limit": 1000})
        if rows is None:
            print("  S2: a router lekérdezése nem sikerült, kihagyom", flush=True)
            return
        if not complete:
            DIAG["S2: router lapozási korlát"] += 1
        path.write_text(json.dumps(rows), encoding="utf-8")
    # egy Jupiter-kötés több PM-sorra bomolhat: tranzakció + token + oldal szerint összevonva
    agg = {}
    for x in rows:
        if x["price"] is None or x["size"] is None or not x["cid"]:
            continue
        k = (x["tx"], x["asset"], x["side"])
        a = agg.setdefault(k, {"cid": x["cid"], "asset": x["asset"], "side": x["side"], "t": x["t"],
                               "sz": 0.0, "px": 0.0, "tx": x["tx"]})
        a["sz"] += x["size"]
        a["px"] += x["price"] * x["size"]
        a["t"] = min(a["t"], x["t"])
    by_c = defaultdict(list)
    for a in agg.values():
        a["px"] /= a["sz"]
        by_c[a["cid"]].append(a)
    print(f"  S2: {len(rows)} sor → {len(agg)} kötés, {len(by_c)} piac", flush=True)
    for i, (cid, items) in enumerate(sorted(by_c.items()), 1):
        if f"{key}:{cid}" in done:
            continue
        m = market_meta(cid)
        toks = tokens(m)
        start = ts_iso((m or {}).get("gameStartTime")) or ts_iso((m or {}).get("eventStartTime"))
        out = []
        if not toks or len(toks) != 2:
            for a in items:
                out.append({"sample": key, "cid": cid, "t0": a["t"], "n": a["sz"], "measurable": 0,
                            "reason": "nincs piacadat / nem kétkimenetes", "side_price": a["px"]})
        else:
            pts, why = market_points(cid, toks[0], toks[1], min(a["t"] for a in items) - 2400)
            ts = [q[0] for q in pts] if pts else []
            for a in items:
                if a["asset"] not in toks:
                    out.append({"sample": key, "cid": cid, "t0": a["t"], "n": a["sz"], "measurable": 0,
                                "reason": "ismeretlen token", "side_price": a["px"]})
                    continue
                d = (1 if a["side"] == "BUY" else -1) * (1 if a["asset"] == toks[0] else -1)
                phase = "unknown" if not start else ("live" if a["t"] >= start else "pre")
                base = {"sample": key, "cid": cid, "market": (m or {}).get("slug", ""), "t0": a["t"], "d": d,
                        "n": a["sz"], "phase": phase, "matched": 1, "side_price": a["px"]}
                if not pts or why:
                    out.append({**base, "measurable": 0, "reason": why or "letöltési hiba"})
                    continue
                r, bad = measure(pts, ts, a["t"], d, a["sz"], a["tx"])
                out.append({**base, **(r or {}), "measurable": int(r is not None), "reason": bad or ""})
        cw.writerows(out)
        fh.flush()
        done.add(f"{key}:{cid}")
        if i % 25 == 0:
            save_done(done)
            print(f"  S2: {i}/{len(by_c)} piac", flush=True)
    save_done(done)


def jupiter_latency():
    """(owner, market, fill ts) -> (megbízás létrehozása ts) a mentett Jupiter-történetből."""
    created, out = {}, {}
    for p in RAW.glob("hist_*_20261104.json"):
        try:
            evs = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for e in evs:
            if e.get("eventType") == "order_created" and e.get("orderPubkey"):
                created[e["orderPubkey"]] = fnum(e.get("timestamp"))
        for e in evs:
            if e.get("eventType") == "order_filled" and e.get("orderPubkey") in created:
                out[(e.get("ownerPubkey"), e.get("marketId"), fnum(e.get("timestamp")))] = created[e["orderPubkey"]]
    return out


def run_s1(done, cw, fh, live: bool):
    key = "S1L" if live else "S1P"
    lat = jupiter_latency()
    fills = []
    with (OUT / "fills_clv.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p, n, t = fnum(r["price"]), fnum(r["n"]), fnum(r["t"])
            if not r["market"].startswith("POLY-") or not (p and n and t) or n < 10:
                continue
            if (r["inplay"] == "True") != live:
                continue
            fills.append(r)
    by_m = defaultdict(list)
    for r in fills:
        by_m[r["market"]].append(r)
    print(f"{key}: {len(fills)} kötés, {len(by_m)} piac", flush=True)
    for i, (mk, fs) in enumerate(sorted(by_m.items()), 1):
        if f"{key}:{mk}" in done:
            continue
        parts = mk.split("-")
        gid, idx = parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        try:
            m = json.loads((RAW / f"poly_market_{gid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = None
        toks, cid = tokens(m), (m or {}).get("conditionId")
        out = []
        if not toks or not cid or len(toks) != 2 or idx > 1:
            for r in fs:
                out.append({"sample": key, "owner": r["owner"], "group": r["group"], "market": mk,
                            "t0": r["t"], "n": r["n"], "measurable": 0, "reason": "nincs piacadat / nem kétkimenetes"})
        else:
            pts, why = market_points(cid, toks[idx], toks[1 - idx], min(float(r["t"]) for r in fs) - 2400)
            ts = [q[0] for q in pts] if pts else []
            for r in fs:
                t, n = float(r["t"]), float(r["n"])
                buy, yes = r["buy"] == "True", r["yes"] == "True"
                d = 1 if buy == yes else -1
                sp = float(r["price"]) if buy else 1 - float(r["price"])
                base = {"sample": key, "owner": r["owner"], "group": r["group"], "market": mk, "cid": cid,
                        "d": d, "n": n, "phase": "live" if live else "pre", "side_price": sp}
                c = lat.get((r["owner"], mk, t))
                if not pts or why:
                    out.append({**base, "t0": t, "measurable": 0, "reason": why or "letöltési hiba",
                                "lat_jup": (t - c) if c else None})
                    continue
                own = [q for q in pts if q[5] and q[1] == d and t - 90 <= q[0] <= t + 30]
                tx_sz = defaultdict(float)
                for q in own:
                    tx_sz[q[4]] += q[3]
                mt = min((q for q in own if abs(tx_sz[q[4]] - n) / n <= 0.03),
                         key=lambda q: abs(q[0] - t), default=None)
                t0 = mt[0] if mt else t
                res, bad = measure(pts, ts, t0, d, n, mt[4] if mt else None)
                out.append({**base, **(res or {}), "t0": t0, "matched": int(mt is not None),
                            "measurable": int(res is not None), "reason": bad or "",
                            "lat_jup": (t - c) if c else None, "lat_pm": (t0 - c) if c and mt else None})
        cw.writerows(out)
        fh.flush()
        done.add(f"{key}:{mk}")
        if i % 25 == 0:
            save_done(done)
            print(f"  {key}: {i}/{len(by_m)} piac", flush=True)
    save_done(done)


# ------------------------------------------------------------- report
def report():
    rows = []
    with ROWS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    lines = []

    def say(s=""):
        print(s, flush=True)
        lines.append(s)

    def st(rs, col, cluster="cid", scale=100):
        it = [(fnum(r[col]), 1.0, r[cluster] or r["market"]) for r in rs if fnum(r.get(col)) is not None]
        n, G, m, se, _ = score.cstats(it)
        if n < 5:
            return f"– (n={n})"
        med = statistics.median(v for v, _, _ in it)
        return f"{m * scale:+.2f} ±{se * scale:.2f} (medián {med * scale:+.2f}; n={n}, piac={G})"

    say("EDGEHOG Flow Intelligence – előre rögzített protokoll (2026-11-04)")
    say("Statisztikai becslés nyilvános adatokból, nem minősítés. Egység: százalékpont, a kereskedő javára pozitív.")
    say("Többlet = a Jupiter-kötés utáni középár-mozgás − a hasonló, más Polymarket-kötések utáni mozgás átlaga.\n")
    smp, ph, h, w = PRIMARY
    prim = [r for r in rows if r["sample"] == smp and r["phase"] == ph and r["measurable"] == "1"]
    say(f"FŐ MÉRŐSZÁM ({smp}, {ph}, {h}, kontroll ±60 mp): többlet {st(prim, f'exc_pp_{w}_{h}')}")
    say("  (negatív = a Jupiter-forgalom kevésbé informált a kontrollnál = alacsonyabb relatív adverse selection)\n")

    say("MÁSODLAGOS – minta × fázis × horizont × kontrollablak (többlet, sz.pont)")
    for s in ("S2", "S1L", "S1P"):
        for phase in (("live", "pre", "unknown") if s == "S2" else (("live",) if s == "S1L" else ("pre",))):
            rs = [r for r in rows if r["sample"] == s and r["phase"] == phase and r["measurable"] == "1"]
            if not rs:
                continue
            say(f"\n  {s}, {phase} ({len(rs)} mérhető kötés)")
            for hname, _ in HORIZ:
                say(f"    {hname:>4} Jupiter saját mozgás: {st(rs, f'jup_pp_{hname}')}")
                for wname, _, _ in WINDOWS:
                    say(f"         többlet {wname:<6} {st(rs, f'exc_pp_{wname}_{hname}')}")
    s1 = [r for r in rows if r["sample"] == "S1L" and r["measurable"] == "1"]
    if s1:
        say(f"\nS1L, tárcánként csoportosított hibahatárral (5m, ±60 mp): {st(s1, 'exc_pp_w60_5m', cluster='owner')}")
        say("\nKÉSLELTETÉS (S1L): megbízás létrehozása → Polymarket-végrehajtás, és a többlet (5m, ±60 mp)")
        lats = sorted(fnum(r["lat_pm"]) for r in s1 if fnum(r.get("lat_pm")) is not None)
        if lats:
            q = lambda x: lats[min(len(lats) - 1, int(x * len(lats)))]
            say(f"  késés: medián {q(.5):.1f} mp, 10%: {q(.1):.1f}, 90%: {q(.9):.1f} (n={len(lats)})")
        for lo, hi in ((0, 5), (5, 10), (10, 20), (20, 1e9)):
            b = [r for r in s1 if fnum(r.get("lat_pm")) is not None and lo <= fnum(r["lat_pm"]) < hi]
            say(f"  {lo:>2}–{'' if hi > 1e8 else hi:<3} mp: többlet {st(b, 'exc_pp_w60_5m')}, "
                f"saját mozgás {st(b, 'jup_pp_5m')}")
    say("\nMÉRHETŐ vs. NEM MÉRHETŐ")
    for s in ("S2", "S1L", "S1P"):
        rs = [r for r in rows if r["sample"] == s]
        if not rs:
            continue
        ok = [r for r in rs if r["measurable"] == "1"]
        bad = [r for r in rs if r["measurable"] != "1"]
        reasons = Counter(r["reason"] for r in bad)
        med = lambda xs, c: statistics.median([fnum(x[c]) for x in xs if fnum(x.get(c)) is not None] or [float("nan")])
        noctrl = sum(1 for r in ok if not fnum(r.get("ctrl_n_w60")))
        say(f"  {s}: {len(ok)} mérhető / {len(rs)} ({len(ok) / len(rs):.0%}); ebből kontroll nélkül ±60 mp-ben: {noctrl}")
        say(f"     nem mérhető okok: " + ", ".join(f"{k}: {v}" for k, v in reasons.most_common()))
        say(f"     medián ár (kötött oldal): mérhető {med(ok, 'side_price'):.2f}, nem mérhető {med(bad, 'side_price'):.2f}; "
            f"medián méret: {med(ok, 'n'):.0f} vs {med(bad, 'n'):.0f}; kötés/óra a piacon (mérhetők): {med(ok, 'trades_per_hour'):.0f}")
    say("\nDiagnosztika: " + "; ".join(f"{k}: {v}" for k, v in DIAG.most_common(8)))
    (OUT / "flow_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--skip", nargs="*", default=[], help="kihagyandó minták: S2 S1L S1P")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if not a.report:
        keep_awake()
        done = load_done()
        fh, cw = writer()
        t0 = time.time()
        try:
            if "S2" not in a.skip:
                run_s2(done, cw, fh)
            if "S1L" not in a.skip:
                run_s1(done, cw, fh, live=True)
            if "S1P" not in a.skip:
                run_s1(done, cw, fh, live=False)
        finally:
            fh.close()
            save_done(done)
        print(f"Gyűjtés kész: {(time.time() - t0) / 3600:.1f} óra", flush=True)
    report()


if __name__ == "__main__":
    main()
