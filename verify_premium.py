"""EDGEHOG ellenőrzés: valódi-e a ~1,3%-os felár a kötés pillanatában (m0)?

A Jupiter Predict a megbízásokat a Polymarketre továbbítja, így minden Jupiter-kötésnek
látszania kell a Polymarket nyilvános kötéslistájában (data-api /trades, másodpercre pontos).
Kötésenként szétválasztjuk:

  1. Jupiter-felár:  a Jupiter kötési ára vs. a hozzá tartozó Polymarket-kötés ára
  2. spread:          a Polymarket-kötés ára vs. a közép (a kötés előtti utolsó vételi és
                      eladási taker-kötés átlaga, ±5 perc) és vs. az előző kötés ára
  3. mérési késés:    a perces árfolyam (m0) vs. ugyanez a közép

Minden szám a kereskedő szemszögéből: pozitív = ennyivel drágábban kötött (százalékpont).
A Jupiter díja (feeUsd) ezen felül jön, külön.

Bemenet: output/fills_clv.csv (probe.py), data/raw/poly_market_*.json (gyorsítótár)
Kimenet: output/premium_report.txt, output/premium_fills.csv
Futtatás: python verify_premium.py [--sample 600]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

DATA_API = "https://data-api.polymarket.com/trades"
RAW = Path("data/raw")
OUT = Path("output")
S = requests.Session()
S.headers["User-Agent"] = "edgehog-verify/0.1"
_last = [0.0]


DIAG = Counter()


def _call(url, params):
    wait = 0.15 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for i in range(4):
        try:
            r = S.get(url, params=params, timeout=40)
        except requests.RequestException as e:
            DIAG[f"hálózati hiba {type(e).__name__}"] += 1
            time.sleep(3 * (i + 1))
            continue
        _last[0] = time.time()
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(30, 3 * 2 ** i))
            continue
        return r
    return None


def _rows(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        x = d.get("data")
        if isinstance(x, list):
            return x
        if isinstance(x, dict):
            for k in ("trades", "items", "rows"):
                if isinstance(x.get(k), list):
                    return x[k]
    return None


def _norm(tr):
    """v1 (camelCase) és v2 (snake_case) mezőnevek egységesítése."""
    g = lambda *ks: next((tr[k] for k in ks if k in tr and tr[k] is not None), None)
    return {"price": g("price"), "size": g("size"), "timestamp": g("timestamp", "ts", "time"),
            "side": g("side"), "asset": g("asset", "asset_id", "token_id", "tokenId"),
            "transactionHash": g("transactionHash", "transaction_hash", "tx_hash"),
            "proxyWallet": g("proxyWallet", "proxy_wallet", "user", "wallet")}


MAX_PAGES = 15


def market_trades(cid: str, t_min: float):
    """A piac Polymarket taker-kötései (v2, legújabbtól visszafelé lapozva t_min-ig).
    v2-ben piacra szűrve nincs időszűrő, ezért lapozunk. Gyorsítótár: data/raw/pm_trades_<cid>.json"""
    path = RAW / f"pm_trades_{cid[:18]}.json"
    if path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("oldest", 1e18) <= t_min or c.get("complete"):
                return c["rows"]
        except ValueError:
            pass
    url = DATA_API.replace("/trades", "/v2/trades")
    out, cursor, complete = [], None, False
    for _ in range(MAX_PAGES):
        p = {"condition": cid, "limit": 1000, "filter_type": "TOKENS", "filter_amount": 5}
        if cursor:
            p["cursor"] = cursor
        r = _call(url, p)
        if r is None:
            DIAG["v2: nincs válasz"] += 1
            return None
        if not r.ok:
            DIAG[f"v2: HTTP {r.status_code} {r.text[:120]!r}"] += 1
            return None
        d = r.json()
        rows = _rows(d)
        if rows is None:
            DIAG[f"v2: ismeretlen válasz {str(d)[:120]!r}"] += 1
            return None
        out += [_norm(x) for x in rows]
        cursor = (d.get("pagination") or {}).get("next_cursor") if isinstance(d, dict) else None
        ts_ = [fnum(x["timestamp"]) for x in out if fnum(x["timestamp"])]
        if not cursor:
            complete = True
            break
        if ts_ and min(ts_) <= t_min:
            break
    else:
        DIAG["v2: lapozási korlát (nem értem vissza a kötésig)"] += 1
    ts_ = [fnum(x["timestamp"]) for x in out if fnum(x["timestamp"])]
    oldest = min(ts_) if ts_ else 1e18
    path.write_text(json.dumps({"oldest": oldest, "complete": complete, "rows": out}), encoding="utf-8")
    if not ts_ or (oldest > t_min and not complete):
        return out if out else None
    DIAG["v2: ok"] += 1
    return out


def meta(gid: str):
    for name in (f"poly_market_{gid}.json",):
        p = RAW / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                return None
    return None


def tokens(m):
    t = m.get("clobTokenIds")
    if isinstance(t, str):
        try:
            t = json.loads(t)
        except ValueError:
            return None
    return t


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def summary(xs, label, unit="sz.pont"):
    xs = [x for x in xs if x is not None]
    if len(xs) < 5:
        return f"  {label:<44} n={len(xs)} (kevés)"
    m = statistics.fmean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    med = statistics.median(xs)
    return (f"  {label:<44} átlag {m * 100:+.2f} ±{se * 100:.2f} {unit}, medián {med * 100:+.2f}, n={len(xs)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()

    fills = []
    with (OUT / "fills_clv.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["market"].startswith("POLY-"):
                continue
            p, n, t = fnum(r["price"]), fnum(r["n"]), fnum(r["t"])
            if p is None or n is None or t is None or not (0.03 <= p <= 0.97) or n < 10:
                continue
            fills.append(r)
    rnd = random.Random(a.seed)
    by_m = defaultdict(list)
    for f in fills:
        by_m[f["market"]].append(f)
    sample = []
    for kind in ("True", "False"):                  # fele élő, fele meccs előtti; piaconként max 3
        mk = [m for m, fs in by_m.items() if any(f["inplay"] == kind for f in fs)]
        rnd.shuffle(mk)
        got = 0
        for m in mk:
            fs = [f for f in by_m[m] if f["inplay"] == kind]
            take = rnd.sample(fs, min(3, len(fs)))
            sample += take
            got += len(take)
            if got >= a.sample // 2:
                break
    sample.sort(key=lambda f: f["market"])
    print(f"Minta: {len(sample)} kötés ({sum(f['inplay'] == 'True' for f in sample)} élő), "
          f"{len({f['market'] for f in sample})} piac, a {len(fills)} kötésből", flush=True)
    rows, wallets = [], Counter()
    for i, f in enumerate(sample, 1):
        parts = f["market"].split("-")
        gid, idx = parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        m = meta(gid)
        toks = tokens(m) if m else None
        cid = (m or {}).get("conditionId")
        if not m:
            DIAG["nincs piac-gyorsítótár"] += 1
            continue
        if not toks or not cid or idx >= len(toks) or len(toks) != 2:
            DIAG["nem kétkimenetes / nincs conditionId"] += 1
            continue
        t, p, n = float(f["t"]), float(f["price"]), float(f["n"])
        buy, yes = f["buy"] == "True", f["yes"] == "True"
        # a kötés a YES-token (toks[idx]) terében: irány d (+1 vétel), ár y
        d = 1 if buy == yes else -1
        y = p if yes else 1 - p
        t_min = min(float(x["t"]) for x in sample if x["market"] == f["market"]) - 300
        trades = market_trades(cid, t_min)
        if trades is None:
            continue
        pts = []
        for tr in trades:
            px, sz, ts_ = fnum(tr.get("price")), fnum(tr.get("size")), fnum(tr.get("timestamp"))
            if px is None or sz is None or ts_ is None:
                continue
            side = 1 if str(tr.get("side")).upper() == "BUY" else -1
            if str(tr.get("asset")) == toks[idx]:
                dd, yy = side, px
            elif str(tr.get("asset")) == toks[1 - idx]:
                dd, yy = -side, 1 - px
            else:
                continue
            pts.append({"t": ts_, "d": dd, "y": yy, "sz": sz, "tx": tr.get("transactionHash"),
                        "w": tr.get("proxyWallet")})
        # 1) a Jupiter-kötés Polymarket-párja: azonos irány, -90..+30 s, tranzakciónként összegzett méret ≈ n
        groups = defaultdict(list)
        for q in pts:
            if q["d"] == d and t - 90 <= q["t"] <= t + 30:
                groups[(q["tx"], q["w"])].append(q)
        match = None
        for (tx, w), qs in groups.items():
            sz = sum(q["sz"] for q in qs)
            if abs(sz - n) / n <= 0.03:
                vw = sum(q["y"] * q["sz"] for q in qs) / sz
                dt = min(abs(q["t"] - t) for q in qs)
                if match is None or dt < match["dt"]:
                    match = {"tx": tx, "w": w, "y": vw, "dt": dt, "t": min(q["t"] for q in qs)}
        if match:
            wallets[match["w"]] += 1
        t_ref = match["t"] if match else t
        before = [q for q in pts if q["t"] < t_ref and (not match or q["tx"] != match["tx"])]
        lb = max((q for q in before if q["d"] == 1), key=lambda q: q["t"], default=None)   # ~ask
        ls = max((q for q in before if q["d"] == -1), key=lambda q: q["t"], default=None)  # ~bid
        last = max(before, key=lambda q: q["t"], default=None)
        mid = (lb["y"] + ls["y"]) / 2 if lb and ls else None
        qm0 = fnum(f.get("q_m0"))
        exec_y = match["y"] if match else None
        side_p = p if buy else 1 - p           # a kereskedő oldalának ára (a relatívhoz)
        rows.append({
            "market": f["market"], "t": t, "inplay": f["inplay"], "group": f["group"], "d": d,
            "jup_y": y, "pm_y": exec_y, "dt": match["dt"] if match else None,
            "pm_wallet": match["w"] if match else None, "mid": mid,
            "spread": (lb["y"] - ls["y"]) if lb and ls else None, "last": last["y"] if last else None,
            "q_m0": qm0, "side_p": side_p,
            "jup_markup": d * (y - exec_y) if exec_y is not None else None,
            "pm_vs_mid": d * (exec_y - mid) if exec_y is not None and mid is not None else None,
            "jup_vs_mid": d * (y - mid) if mid is not None else None,
            "jup_vs_last": d * (y - last["y"]) if last else None,
            "jup_vs_m0": d * (y - qm0) if qm0 is not None else None,
            "m0_vs_mid": d * (qm0 - mid) if qm0 is not None and mid is not None else None,
            "fee_pp": (fnum(f.get("fee")) or 0) / float(f["n"]) if f.get("fee") else None,
        })
        if i % 50 == 0:
            print(f"  {i}/{len(sample)}, eddig párosítva: {sum(r['pm_y'] is not None for r in rows)}", flush=True)

    with (OUT / "premium_fills.csv").open("w", newline="", encoding="utf-8") as fh:
        cw = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["market"], extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)

    lines = []

    def say(s=""):
        print(s)
        lines.append(s)

    say("Diagnosztika: " + "; ".join(f"{k}: {v}" for k, v in DIAG.most_common(8)))
    say("EDGEHOG – felár a kötés pillanatában (pozitív = a kereskedő ennyivel drágábban kötött, százalékpont)")
    say(f"Vizsgált kötés: {len(rows)}, Polymarket-párt találtam: {sum(r['pm_y'] is not None for r in rows)}")
    say("Leggyakoribb Polymarket-tárcák a párokban (a Jupiter továbbító tárcái): " +
        ", ".join(f"{w[:10]}… ({c})" for w, c in wallets.most_common(5)))
    for name, cond in (("összes", lambda r: True), ("meccs előtt", lambda r: r["inplay"] != "True"),
                       ("élő", lambda r: r["inplay"] == "True")):
        rs = [r for r in rows if cond(r)]
        say(f"\n{name.upper()} ({len(rs)} kötés)")
        say(summary([r["jup_markup"] for r in rs], "1. Jupiter ára vs. saját Polymarket-kötése"))
        say(summary([r["pm_vs_mid"] for r in rs], "2. Polymarket-kötés vs. közép (spread)"))
        say(summary([r["jup_vs_mid"] for r in rs], "   Jupiter ára vs. közép (1+2 együtt)"))
        say(summary([r["jup_vs_last"] for r in rs], "   Jupiter ára vs. előző Polymarket-kötés"))
        say(summary([r["jup_vs_m0"] for r in rs], "   Jupiter ára vs. perces ár (a mostani m0)"))
        say(summary([r["m0_vs_mid"] for r in rs], "3. perces ár (m0) vs. közép (mérési hiba)"))
        say(summary([r["spread"] / 2 if r["spread"] is not None else None for r in rs],
                    "   fél spread (utolsó vétel−eladás)/2"))
        say(summary([r["fee_pp"] for r in rs], "   + Jupiter-díj szerződésenként"))
        rel = [r["jup_vs_mid"] / r["side_p"] for r in rs if r["jup_vs_mid"] is not None and r["side_p"]]
        say(summary(rel, "   Jupiter ára vs. közép, relatív (CLV-egység)", unit="%"))
    say("\nKözép = a kötés előtti utolsó vételi és eladási taker-kötés átlaga (5 percen belül) – közelítés.")
    (OUT / "premium_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
