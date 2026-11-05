"""EDGEHOG probe: are Jupiter Predict's top traders skilled, or just lucky?

Jupiter's leaderboards rank by P&L, volume and win rate. Over a few weeks those
mostly measure luck. A sharper measure of skill is the closing-line value (CLV)
of every fill: did the trader buy below the price the market later settled on
before the outcome was known?

    buy at p, later reference price q (same side):   CLV = q / p - 1

(a sell is treated as buying the other side at 1 - p). Reference prices:
  close   the last market price before the game starts (sports markets on
          Polymarket carry gameStartTime); the classic CLV
  1h, 24h the market price 1 and 24 hours after the fill ("markout"), used for
          every market type; skipped when that moment is past the close

Per wallet: amount-weighted mean CLV with its standard error, next to the
wallet's leaderboard P&L. Verdict: "ügyes" (CLV clearly above 0), "szerencsés"
(P&L positive but CLV clearly below 0), otherwise "nem eldönthető".

Data: Jupiter Prediction API (fills, leaderboard; needs the key in .jupkey) and
the public Polymarket / Kalshi price histories. Everything raw is cached in
data/, so a second run is fast and the results can be re-cut without new calls.

Short markouts (m0, 1m, 5m, 15m) on minute prices around each fill measure live
(in-play) trades too: m0 is the premium paid at the moment of the fill (spread,
fees, delay), 5m whether the market moved the trader's way within five minutes.
A baseline of ordinary wallets from Jupiter's global trade feed shows whether the
leaderboard trades any better than everyone else.

Run:  python probe.py            (top 100 weekly + monthly P&L + 60 ordinary wallets, 300 fills each)
      python probe.py --wallets 30 --fills 150 --baseline 30     (a quicker look)
      python probe.py --day 20261104     (re-cut a saved day from data/raw, no new wallet calls)

2026-11-04 rework: probe.py only collects. Per fill it writes the raw later YES
prices (q_close ... q_15m), Jupiter's fee and the price swing around the fill to
output/fills_clv.csv, the wallet list to output/wallet_meta.csv, then calls
score.py, which does all the statistics (labels, clustered error bars,
absolute and net CLV, pre-match / live / overall scores). Ordinary wallets
come from the collector's trade files (data/trades, see collect.py) when there
are enough, otherwise from the live trade feed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

JUP = "https://api.jup.ag/prediction/v1"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
KEY_FILE = Path(".jupkey")
DATA = Path("data")
RAW = DATA / "raw"
OUT = Path("output")
S = requests.Session()
S.headers["User-Agent"] = "edgehog-probe/0.1"
_last: dict[str, float] = {}
GAP = {"jup": 0.25, "poly": 0.12, "kalshi": 0.12}      # polite pauses between calls (s)


# ------------------------------------------------------------------ http
def get(url: str, params=None, host="jup", headers=None, tries=4):
    wait = GAP[host] - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    for i in range(tries):
        try:
            r = S.get(url, params=params, headers=headers, timeout=40)
        except requests.RequestException as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))
            continue
        _last[host] = time.time()
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(30, 3 * 2 ** i))
            continue
        return r
    return r


DAY = datetime.now(timezone.utc).strftime("%Y%m%d")   # snapshot day of leaderboards / histories
OFFLINE_DAY = False                                    # --day given for a past day: don't refetch


def cached(name: str, fn, dated: bool = False):
    """JSON cache under data/raw (finished markets never change).
    dated=True: a per-day snapshot; when re-cutting a past day it is never refetched."""
    path = RAW / name
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    if dated and OFFLINE_DAY:
        return None
    data = fn()
    if data is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return data


def jup(path: str, params=None):
    r = get(f"{JUP}{path}", params, "jup", {"x-api-key": KEY})
    if r.status_code in (401, 403):
        sys.exit(f"Jupiter: a kulcs nem jó ({r.status_code}). Nézd meg a .jupkey fájlt.")
    r.raise_for_status()
    return r.json()


def micro(v) -> float | None:
    try:
        return float(v) / 1e6
    except (TypeError, ValueError):
        return None


def ts(v) -> float | None:
    """Unix seconds from seconds, milliseconds or an ISO string."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace(".", "", 1).isdigit()):
        x = float(v)
        return x / 1000 if x > 1e11 else x
    s = str(v).strip().replace("Z", "+00:00")
    if len(s) > 3 and s[-3] in "+-" and s[-2:].isdigit():   # "...+00" -> "...+00:00"
        s += ":00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- wallets
def leaderboard(period: str, n: int) -> list[dict]:
    d = cached(f"lb_{period}_{DAY}.json",
               lambda: jup("/leaderboards", {"period": period, "metric": "pnl", "limit": min(n, 100)}), dated=True)
    if d is None and OFFLINE_DAY:
        sys.exit(f"Nincs mentett toplista erre a napra: data/raw/lb_{period}_{DAY}.json")
    rows = (d or {}).get("data") or []
    for r in rows:
        r["_period"] = period
    return rows[:n]


def fills(owner: str, limit: int) -> list[dict]:
    """The wallet's filled orders, newest first (cached per day)."""
    def load():
        out, start = [], 0
        while len(out) < limit * 3:                   # history also holds non-fill events
            d = jup("/history", {"ownerPubkey": owner, "start": start, "end": start + 100})
            rows = d.get("data") or []
            out += rows
            pg = d.get("pagination") or {}
            if not rows or not pg.get("hasNext"):
                break
            start += len(rows)
        return out
    def safe_load():
        try:
            return load()
        except Exception as e:                       # one broken wallet must not stop the run
            print(f"     kihagyva: a /history hibát adott ({type(e).__name__}: {e})", flush=True)
            return None                              # None: nem kerül a gyorsítótárba
    rows = cached(f"hist_{owner}_{DAY}.json", safe_load, dated=True) or []
    fl = [r for r in rows if str(r.get("eventType", "")).lower() == "order_filled"
          and (micro(r.get("avgFillPriceUsd")) or 0) > 0]
    return fl[:limit]


# ------------------------------------------------------------- price paths
def provider(market_id: str) -> tuple[str, str]:
    p, _, rest = str(market_id).partition("-")
    return p.upper(), rest


def poly_path(mid: str, ev: dict):
    """(times, YES prices, start/close time) for a Polymarket market id."""
    # Jupiter splits a two-outcome Polymarket market into POLY-<id>-0 and POLY-<id>-1:
    # the suffix is the outcome, and that outcome's token is the "YES" of the Jupiter market
    parts = mid.split("-")
    idx = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    meta = None
    for cand in dict.fromkeys((mid, parts[0])):
        meta = cached(f"poly_market_{cand}.json", lambda c=cand: (lambda r: r.json() if r.ok else None)(
            get(f"{GAMMA}/markets/{c}", host="poly")))
        if meta:
            mid = cand
            break
    if not meta:
        return None
    toks = meta.get("clobTokenIds")
    if isinstance(toks, str):
        try:
            toks = json.loads(toks)
        except ValueError:
            toks = None
    if not toks:
        return None
    if idx >= len(toks):
        return None
    yes = toks[idx]
    start = ts(meta.get("gameStartTime")) or ts(meta.get("eventStartTime"))
    close = ts(meta.get("closedTime")) or ts(meta.get("endDate"))
    t0 = ts(meta.get("startDate")) or (close - 60 * 86400 if close else time.time() - 60 * 86400)
    t1 = int(min(close or time.time(), time.time()))      # int: the chunk loop must reach it

    def load():
        pts, a = [], int(t0)
        while a < t1:                                  # the endpoint wants bounded ranges
            b = int(min(t1, a + 14 * 86400))
            r = get(f"{CLOB}/prices-history", {"market": yes, "startTs": a, "endTs": b, "fidelity": 10}, "poly")
            if r.ok:
                pts += r.json().get("history") or []
            a = b
        return pts
    hist = cached(f"poly_hist_{mid}.json" if idx == 0 else f"poly_hist_{mid}_{idx}.json", load) or []
    if not hist:
        return None
    t = [float(h["t"]) for h in hist]
    p = [float(h["p"]) for h in hist]
    return t, p, start, close, meta, yes


def kalshi_path(ticker: str, ev: dict):
    m = cached(f"kalshi_market_{ticker}.json", lambda: (lambda r: r.json() if r.ok else None)(
        get(f"{KALSHI}/markets/{ticker}", host="kalshi")))
    m = (m or {}).get("market") or m
    if not m or not m.get("event_ticker"):
        return None
    e = cached(f"kalshi_event_{m['event_ticker']}.json", lambda: (lambda r: r.json() if r.ok else None)(
        get(f"{KALSHI}/events/{m['event_ticker']}", host="kalshi")))
    series = ((e or {}).get("event") or {}).get("series_ticker") or str(m["event_ticker"]).split("-")[0]
    close = ts(m.get("close_time"))
    start = None                                      # Kalshi has no reliable kick-off field
    t0 = ts(m.get("open_time")) or (close - 60 * 86400 if close else time.time() - 60 * 86400)
    t1 = int(min(close or time.time(), time.time()))      # int: the chunk loop must reach it

    def load():
        out, a = [], int(t0)
        while a < t1:
            b = int(min(t1, a + 4 * 86400))
            r = get(f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks",
                    {"start_ts": a, "end_ts": b, "period_interval": 60}, "kalshi")
            if r.ok:
                out += r.json().get("candlesticks") or []
            a = b
        return out
    cs = cached(f"kalshi_hist_{ticker}.json", load) or []
    t, p = [], []
    for c in cs:
        bid, ask = (c.get("yes_bid") or {}).get("close"), (c.get("yes_ask") or {}).get("close")
        px = (bid + ask) / 2 if bid is not None and ask is not None and ask > bid else (c.get("price") or {}).get("close")
        if px is not None and c.get("end_period_ts"):
            t.append(float(c["end_period_ts"]))
            p.append(float(px) / 100)
    return (t, p, start, close, m) if t else None


def fine_path(yes: str, times: list[float], close: float | None):
    """Minute prices around the fills (windows of 10 min before to 20 min after, merged).
    Used for the short markouts that also work for live (in-play) trades."""
    end_cap = int(min(close or time.time(), time.time()))
    wins = []
    for t in sorted(times):
        a, b = int(t - 600) // 600 * 600, int(t + 1200) // 600 * 600 + 600
        b = min(b, end_cap)
        if b <= a:
            continue
        if wins and a <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], b)
        else:
            wins.append([a, b])
    t_all, p_all = [], []
    for a, b in wins:
        def load(a=a, b=b):
            pts, x = [], a
            while x < b:
                y = min(b, x + 86400)
                r = get(f"{CLOB}/prices-history", {"market": yes, "startTs": x, "endTs": y, "fidelity": 1}, "poly")
                if r.ok:
                    pts += r.json().get("history") or []
                x = y
            return pts
        for h in cached(f"poly_fine_{yes[-12:]}_{a}_{b}.json", load) or []:
            t_all.append(float(h["t"]))
            p_all.append(float(h["p"]))
    if not t_all:
        return None
    order = sorted(range(len(t_all)), key=t_all.__getitem__)
    return [t_all[i] for i in order], [p_all[i] for i in order]


def price_at(path, when: float, max_gap: float = 6 * 3600) -> float | None:
    """Last known YES price at or before `when` (None if no point within max_gap)."""
    t, p = path[0], path[1]
    lo, hi = 0, len(t) - 1
    if not t or when < t[0]:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if t[mid] <= when:
            lo = mid
        else:
            hi = mid - 1
    return p[lo] if when - t[lo] <= max_gap else None


# -------------------------------------------------------------------- CLV
def fill_fields(f: dict):
    price = micro(f.get("avgFillPriceUsd"))
    n = f.get("filledContractsDecimal") or f.get("contractsDecimal")
    if n is None:
        n = micro(f.get("filledContracts") or f.get("filledContractsMicro"))
    try:
        n = float(n)
    except (TypeError, ValueError):
        n = None
    return price, n, bool(f.get("isBuy")), bool(f.get("isYes")), ts(f.get("timestamp")), micro(f.get("feeUsd"))


def swing_around(fine, t: float, before: float = 120, after: float = 300) -> float | None:
    """Largest YES-price range in the minute prices from 2 min before to 5 min after a fill:
    a big value means an event (goal, red card, break) happened right around the trade."""
    if not fine:
        return None
    p0 = price_at(fine, t - before, max_gap=180)      # the level going into the window
    pts = [p for tt, p in zip(fine[0], fine[1]) if t - before <= tt <= t + after]
    if p0 is not None:
        pts.append(p0)
    if len(pts) < 2:
        return None
    return max(pts) - min(pts)


# -------------------------------------------------------------------- main
SHORT = (("m0", 0), ("1m", 60), ("5m", 300), ("15m", 900))   # markouts on minute prices
LONG = ("close", "1h", "24h")
SPORTS = {"sports", "esports"}
TRADES = DATA / "trades"                                 # the collector's files (collect.py)


def collector_wallets() -> list[str]:
    """Distinct wallets in the collector's trade files, in first-seen order."""
    seen = {}
    for p in sorted(TRADES.glob("trades_*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                o = json.loads(line).get("ownerPubkey")
            except ValueError:
                continue
            if o:
                seen.setdefault(o, None)
    return list(seen)


def baseline_wallets(exclude: set, n: int) -> list[str]:
    """Ordinary traders, not on the leaderboards: a seeded random sample of the collector's
    wallets when it has enough, otherwise the newest wallets of Jupiter's global trade feed.
    The chosen list is saved per day, so a re-cut uses the same wallets."""
    def pick():
        pool = [w for w in collector_wallets() if w not in exclude]
        if len(pool) >= n:
            print(f"Átlagcsoport: {n} véletlen tárca a gyűjtő {len(pool)} tárcájából")
            return random.Random(int(DAY)).sample(pool, n)
        seen = []
        for start in range(0, 2000, 100):
            try:
                d = jup("/trades", {"start": start, "end": start + 100})
            except Exception:
                break
            rows = d.get("data") or []
            added = [r["ownerPubkey"] for r in rows if r.get("ownerPubkey")
                     and r["ownerPubkey"] not in exclude and r["ownerPubkey"] not in seen]
            seen += list(dict.fromkeys(added))
            if len(seen) >= n or not rows or not added and start > 0:
                break
        print(f"Átlagcsoport: {min(n, len(seen))} tárca az élő kötésfolyamból "
              f"(a gyűjtőben még csak {len(pool)} van)")
        return seen[:n]
    return (cached(f"baseline_{DAY}_{n}.json", pick, dated=True) or [])[:n]


def main():
    global KEY, DAY, OFFLINE_DAY
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallets", type=int, default=100, help="ennyi tárca toplistánként (max 100)")
    ap.add_argument("--fills", type=int, default=300, help="tárcánként legfeljebb ennyi kötés")
    ap.add_argument("--baseline", type=int, default=60, help="ennyi átlagos tárca (összevetéshez)")
    ap.add_argument("--periods", nargs="+", default=["weekly", "monthly"])
    ap.add_argument("--day", default=None, help="mentett nap újravágása (ÉÉÉÉHHNN), új tárcahívás nélkül")
    a = ap.parse_args()
    if a.day and a.day != DAY:
        DAY, OFFLINE_DAY = a.day, True
    KEY = os.environ.get("JUPITER_API_KEY", "").strip()
    if not KEY and KEY_FILE.exists():
        KEY = KEY_FILE.read_text(encoding="utf-8").strip()
    if not KEY:
        sys.exit("Nincs Jupiter API-kulcs: állítsd be a JUPITER_API_KEY környezeti változót, vagy tedd a .jupkey fájlba.")
    OUT.mkdir(exist_ok=True)

    wallets = {}
    for per in a.periods:
        for r in leaderboard(per, a.wallets):
            w = wallets.setdefault(r["ownerPubkey"], {"owner": r["ownerPubkey"], "periods": [], "group": "toplista"})
            w["periods"].append(per)
            w[f"pnl_{per}"] = micro(r.get("realizedPnlUsd"))
            w[f"winrate_{per}"] = r.get("winRatePct")
    n_top = len(wallets)
    for o in baseline_wallets(set(wallets), a.baseline):
        wallets[o] = {"owner": o, "periods": [], "group": "átlag"}
    print(f"Tárcák: {n_top} toplistás ({', '.join(a.periods)}, P&L szerint) + {len(wallets) - n_top} "
          f"átlagos; nap: {DAY}{' (mentett adatból)' if OFFLINE_DAY else ''}")

    # pass 1: fills + 10-minute price paths (close, 1h, 24h)
    paths, unknown, rows = {}, {}, []
    for i, w in enumerate(wallets.values(), 1):
        print(f"  {i}/{len(wallets)} [{w['group']}] {w['owner'][:6]}… kötések", flush=True)
        for f in fills(w["owner"], a.fills):
            mid = f.get("marketId")
            price, n, is_buy, is_yes, t, fee = fill_fields(f)
            if not mid or price is None or t is None:
                continue
            if mid not in paths:
                prov, rest = provider(mid)
                try:
                    paths[mid] = poly_path(rest, f) if prov == "POLY" else kalshi_path(rest, f) \
                        if prov in ("KALSHI", "KX", "KAL") else None
                except Exception as e:                      # one bad market must not stop the run
                    paths[mid] = None
                    unknown[mid] = f"hiba: {type(e).__name__}"
                if paths[mid] is None and mid not in unknown:
                    unknown[mid] = prov
            path = paths[mid]
            if not path:
                continue
            ev = f.get("eventMetadata") or {}
            cat = str(ev.get("category") or "").lower()
            # kick-off: Polymarket's gameStartTime, else Jupiter's beginAt for sports events
            start = path[2] or (ts(ev.get("beginAt")) if cat in SPORTS else None)
            close = path[3]
            end = min(x for x in (start, close) if x) if (start or close) else None
            rec = {"owner": w["owner"], "group": w["group"], "market": mid, "event": f.get("eventId") or "",
                   "category": cat, "t": t, "price": price, "n": n or 0, "amount": price * (n or 0),
                   "fee": fee, "buy": is_buy, "yes": is_yes, "inplay": bool(start and t >= start)}
            # close = just before kick-off; only where the kick-off is known (otherwise the
            # last price before the close already reflects the result)
            for label, when in (("close", start and start - 60), ("1h", t + 3600), ("24h", t + 86400)):
                if when is None or (end and when > end) or when < t:
                    rec[f"q_{label}"] = None
                    continue
                rec[f"q_{label}"] = price_at(path, when)
            rows.append(rec)
        print(f"     eddig {len(rows)} kötés, {len(paths)} piac", flush=True)

    # pass 2: minute prices around every fill -> short markouts (also for live trades) + swing
    by_mkt = {}
    for r in rows:
        by_mkt.setdefault(r["market"], []).append(r)
    print(f"\nPercenkénti árak a kötések körül: {len(by_mkt)} piac…", flush=True)
    for k, (mid, rs) in enumerate(by_mkt.items(), 1):
        path = paths.get(mid)
        fine = None
        if path and len(path) > 5:
            try:
                fine = fine_path(path[5], [r["t"] for r in rs], path[3])
            except Exception:
                fine = None
        for r in rs:
            for label, dt in SHORT:
                r[f"q_{label}"] = price_at(fine, r["t"] + dt, max_gap=180) if fine else None
            r["swing"] = swing_around(fine, r["t"])
        if k % 100 == 0:
            print(f"     {k}/{len(by_mkt)}", flush=True)

    import csv
    cols = ["owner", "group", "market", "event", "category", "t", "price", "n", "amount", "fee",
            "buy", "yes", "inplay", "swing"] + [f"q_{h}" for h in ("close", "1h", "24h", "m0", "1m", "5m", "15m")]
    with (OUT / "fills_clv.csv").open("w", newline="", encoding="utf-8") as fh:
        cw = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)
    with (OUT / "wallet_meta.csv").open("w", newline="", encoding="utf-8") as fh:
        keys = ["owner", "group", "pnl", "pnl_weekly", "pnl_monthly", "winrate_weekly", "winrate_monthly", "periods"]
        cw = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        cw.writeheader()
        for w in wallets.values():
            pnl = w.get("pnl_monthly") if w.get("pnl_monthly") is not None else w.get("pnl_weekly")
            cw.writerow({**w, "pnl": pnl, "periods": " ".join(w["periods"])})
    print(f"\nPiacok: {len(paths)}, ebből ár nélkül {len(unknown)}; kötések: {len(rows)} "
          f"(élő: {sum(r['inplay'] for r in rows)})\n")

    import score
    score.main([])


KEY = ""
if __name__ == "__main__":
    main()
