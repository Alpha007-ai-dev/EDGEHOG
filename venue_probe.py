"""EDGEHOG döntő teszt: ugyanarra a sportmeccsre mennyivel olcsóbb az egyik helyszín a másiknál?

Helyszínek (Solanáról elérhetők):
  * Polymarket a Jupiter Predicten át: ár = Polymarket-könyv (a Jupiter nem tesz rá felárat,
    verify_premium.py), díj = a SAJÁT 16 ezer kötésünkből kimért Jupiter-díj az ár függvényében.
  * Kalshi a DFlow-n át: ár = Kalshi-könyv (a DFlow a Kalshi likviditását hozza Solanára),
    díj = Kalshi taker-díj 0,07 · szerződés · p · (1 − p) (felfelé centre kerekítve). A DFlow saját
    díját nem ismerjük → a Kalshi-oldal költsége ALSÓ becslés.

A következő 48 óra kétkimenetes sportmeccseit párosítja (kezdési idő + csapatnevek), és mindkét
kimenetre, 50 / 500 / 2000 dolláros vételre kiszámolja a teljes költséget szerződésenként.

Futtatás:  python venue_probe.py           Kimenet: output/venue_report.txt, output/venue_pairs.csv
"""
from __future__ import annotations

import csv
import difflib
import json
import math
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
DFLOW = "https://dev-prediction-markets-api.dflow.net/api/v1"
OUT = Path("output")
SIZES = (50, 500, 2000)
HORIZON = 48 * 3600
S = requests.Session()
S.headers["User-Agent"] = "edgehog-venue-probe/0.1"
LOG = []
_DIAG_SHOWN = set()


def say(s=""):
    print(s, flush=True)
    LOG.append(str(s))


def get(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (i + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(20, 2 * 2 ** i))
            continue
        time.sleep(0.12)
        return r
    return None


def ts(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e11 else 1)
    s = str(v).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    if len(s) > 3 and s[-3] in "+-" and s[-2:].isdigit():
        s += ":00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    drop = {"the", "fc", "vs", "v", "at", "team", "win", "wins", "will", "beat"}
    return " ".join(w for w in s.split() if w not in drop)


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.95
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb)
    return max(jac, difflib.SequenceMatcher(None, a, b).ratio())


# ------------------------------------------------------------ fee model
def jupiter_fee_table():
    """Jupiter-díj szerződésenként az ár függvényében (vételek, medián, 0,05-ös sávok) a saját adatunkból."""
    bins = defaultdict(list)
    p = OUT / "fills_clv.csv"
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    if r["buy"] != "True" or not r.get("fee"):
                        continue
                    price, n, fee = float(r["price"]), float(r["n"]), float(r["fee"])
                except (ValueError, KeyError):
                    continue
                if n > 0 and 0 < price < 1:
                    bins[min(19, int(price * 20))].append(fee / n)
    table = {b: statistics.median(v) for b, v in bins.items() if len(v) >= 10}
    return table


def jup_fee(table, p):
    b = min(19, max(0, int(p * 20)))
    if b in table:
        return table[b]
    near = sorted(table, key=lambda k: abs(k - b))
    return table[near[0]] if near else 0.02 * p + 0.05 * p * (1 - p) * 0.25


def kalshi_fee(p, contracts, mult=1.0):
    total = math.ceil(0.07 * mult * contracts * p * (1 - p) * 100 - 1e-9) / 100
    return total / contracts if contracts else 0.0


def fill(asks, dollars):
    """Vétel 'dollars' értékben a könyvből: (szerződés, átlagár) vagy None, ha nincs elég."""
    left, n, cost = dollars, 0.0, 0.0
    for price, qty in sorted(asks):
        if price <= 0 or price >= 1:
            continue
        take = min(qty, left / price)
        n += take
        cost += take * price
        left -= take * price
        if left <= 1e-6:
            return n, cost / n
    return None


# ------------------------------------------------------------- Polymarket
PM_TAGS = ["sports", "nba", "nhl", "nfl", "cfb", "ncaab", "cbb", "tennis", "atp", "wta", "esports",
           "mma", "ufc", "boxing", "cricket", "basketball", "hockey", "football", "baseball"]


def _pm_market(m, now, seen, out):
    st = ts(m.get("gameStartTime")) or ts(m.get("eventStartTime"))
    if not st or not (now - 3600 <= st <= now + HORIZON) or m.get("id") in seen:
        return
    if m.get("closed") or (m.get("active") is False):
        return
    smt = str(m.get("sportsMarketType") or "").lower()
    if smt and smt != "moneyline":
        return
    outs, toks = m.get("outcomes"), m.get("clobTokenIds")
    try:
        outs = json.loads(outs) if isinstance(outs, str) else outs
        toks = json.loads(toks) if isinstance(toks, str) else toks
    except ValueError:
        return
    if not outs or not toks or len(outs) != 2 or len(toks) != 2:
        return
    if any(str(o).lower() in ("yes", "no", "draw", "tie", "over", "under") for o in outs):
        return
    seen.add(m.get("id"))
    out.append({"id": m.get("id"), "q": m.get("question"), "start": st, "outcomes": outs, "tokens": toks,
                "slug": m.get("slug")})


def poly_games():
    now, out, seen = time.time(), [], set()
    for tag in PM_TAGS:
        got = 0
        for offset in range(0, 2000, 200):
            r = get(f"{GAMMA}/events", {"tag_slug": tag, "closed": "false", "limit": 200, "offset": offset})
            if r is None or not r.ok:
                break
            evs = r.json()
            evs = evs if isinstance(evs, list) else evs.get("data", [])
            for e in evs:
                for m in e.get("markets") or []:
                    _pm_market(m, now, seen, out)
            got += len(evs)
            if len(evs) < 200:
                break
        if got:
            say(f"  Polymarket tag '{tag}': {got} esemény, eddig {len(out)} meccs (48 órán belül)")
    return out


def poly_asks(token):
    r = get(f"{CLOB}/book", {"token_id": token})
    if r is None or not r.ok:
        if "p_err" not in _DIAG_SHOWN:
            _DIAG_SHOWN.add("p_err")
            say(f"  [diag] Polymarket book hiba: {getattr(r, 'status_code', '-')} {getattr(r, 'text', '')[:200]}")
        return None
    d = r.json()
    if "p_ok" not in _DIAG_SHOWN:
        _DIAG_SHOWN.add("p_ok")
        say(f"  [diag] Polymarket book minta: {json.dumps(d)[:300]}")
    return [(float(a["price"]), float(a["size"])) for a in d.get("asks", [])]


# ------------------------------------------------------------- Kalshi
def kalshi_games():
    r = get(f"{KALSHI}/series", {"category": "Sports"})
    series = []
    if r is not None and r.ok:
        series = [s["ticker"] for s in r.json().get("series", []) if re.search(r"(GAME|MATCH)$", s.get("ticker", ""))]
    if not series:
        series = ["KXNBAGAME", "KXNFLGAME", "KXNHLGAME", "KXNCAAFGAME", "KXNCAAMBGAME", "KXATPMATCH", "KXWTAMATCH"]
    say(f"  Kalshi sorozatok: {len(series)} ({', '.join(series[:12])}{'…' if len(series) > 12 else ''})")
    now, games = time.time(), []
    for st in series:
        cursor = None
        for _ in range(5):
            p = {"series_ticker": st, "status": "open", "with_nested_markets": "true", "limit": 200}
            if cursor:
                p["cursor"] = cursor
            r = get(f"{KALSHI}/events", p)
            if r is None or not r.ok:
                break
            d = r.json()
            for e in d.get("events", []):
                mk = e.get("markets") or []
                if len(mk) != 2:
                    continue
                exp = [ts(m.get("expected_expiration_time")) or ts(m.get("close_time")) for m in mk]
                exp = min(x for x in exp if x) if any(exp) else None
                if not exp or exp < now or exp > now + HORIZON + 12 * 3600:
                    continue
                games.append({"event": e.get("event_ticker"), "title": e.get("title"), "series": st, "exp": exp,
                              "markets": [{"ticker": m.get("ticker"), "name": m.get("yes_sub_title") or m.get("subtitle")
                                           or m.get("title")} for m in mk]})
            cursor = d.get("cursor")
            if not cursor:
                break
    return games



def _lvls(v):
    out = []
    for lvl in v or []:
        try:
            if isinstance(lvl, dict):
                px, q = float(lvl.get("price")), float(lvl.get("quantity") or lvl.get("size") or lvl.get("count"))
            else:
                px, q = float(lvl[0]), float(lvl[1])
        except (TypeError, ValueError, IndexError):
            continue
        out.append((px / 100 if px > 1 else px, q))
    return out


def kalshi_asks(ticker):
    """YES-vételi árak: a NO-oldali vételi ajánlatokból (YES ask = 1 − NO bid)."""
    r = get(f"{KALSHI}/markets/{ticker}/orderbook")
    if r is None or not r.ok:
        if "k_err" not in _DIAG_SHOWN:
            _DIAG_SHOWN.add("k_err")
            say(f"  [diag] Kalshi orderbook hiba: {getattr(r, 'status_code', '-')} {getattr(r, 'text', '')[:200]}")
        return None
    d = r.json() or {}
    if "k_ok" not in _DIAG_SHOWN:
        _DIAG_SHOWN.add("k_ok")
        say(f"  [diag] Kalshi orderbook minta: {json.dumps(d)[:300]}")
    ob = d.get("orderbook") or d.get("orderbook_fp") or d
    no = None
    for k in ("no_dollars", "no", "no_bids"):
        if ob.get(k):
            no = ob[k]
            break
    return [(round(1 - px, 4), q) for px, q in _lvls(no)]


# ------------------------------------------------------------- main
def main():
    OUT.mkdir(exist_ok=True)
    say("EDGEHOG – helyszín-teszt: Polymarket (Jupiteren át) vs. Kalshi (DFlow-n át), azonos meccsek")
    say(f"Idő: {datetime.now():%Y-%m-%d %H:%M}, a következő 48 óra kétkimenetes sportmeccsei\n")
    table = jupiter_fee_table()
    say("Jupiter-díj szerződésenként (saját kötéseinkből, medián): " +
        ", ".join(f"{b / 20:.2f}–{(b + 1) / 20:.2f}: {v * 100:.2f}¢" for b, v in sorted(table.items())[::3]))
    pg = poly_games()
    say(f"Polymarket: {len(pg)} meccs")
    kg = kalshi_games()
    say(f"Kalshi: {len(kg)} meccs")
    # DFlow minta (csak tájékoztatás: van-e saját ára, eltér-e a Kalshitól)
    r = get(f"{DFLOW}/events", {"limit": 2, "withNestedMarkets": "true"}, tries=1)
    say(f"DFlow API minta: {getattr(r, 'status_code', '-')} {(r.text[:300] if r is not None else 'nem elérhető')!r}\n")

    pairs = []
    for m in pg:
        best = None
        for g in kg:
            if not (m["start"] - 3 * 3600 <= g["exp"] <= m["start"] + 12 * 3600):
                continue
            a = [[sim(o, km["name"]) for km in g["markets"]] for o in m["outcomes"]]
            # rövidítés-alapú párosítás (pl. PM slug "nba-lal-bos-2026-11-05" ↔ Kalshi "...-LAL")
            slug_codes = [t for t in str(m.get("slug") or "").lower().split("-") if t.isalpha() and 2 <= len(t) <= 5]
            kc = [str(km["ticker"]).rsplit("-", 1)[-1].lower() for km in g["markets"]]
            if len(slug_codes) >= 3 and all(c in slug_codes[1:] for c in kc):
                pos = [slug_codes[1:].index(c) for c in kc]          # a kód helye a slugban ~ kimenet sorrend
                if sorted(pos) == [0, 1]:
                    for j, pz in enumerate(pos):
                        a[pz][j] = max(a[pz][j], 0.9)
            s1, s2 = a[0][0] + a[1][1], a[0][1] + a[1][0]
            score, perm = (s1, (0, 1)) if s1 >= s2 else (s2, (1, 0))
            if min(a[0][perm[0]], a[1][perm[1]]) < 0.5:
                continue
            if best is None or score > best[0]:
                best = (score, g, perm)
        if best:
            pairs.append((m, best[1], best[2], best[0]))
    say(f"Párosított meccsek: {len(pairs)}")
    for m, g, perm, sc in pairs[:15]:
        say(f"  {str(m['q'])[:55]:<55} ↔ {str(g['title'])[:45]:<45} ({sc / 2:.2f})")

    rows = []
    for m, g, perm, sc in pairs:
        for i in range(2):
            pa = poly_asks(m["tokens"][i])
            km = g["markets"][perm[i]]
            ka = kalshi_asks(km["ticker"])
            for size in SIZES:
                fp = fill(pa, size) if pa else None
                fk = fill(ka, size) if ka else None
                row = {"pm_q": m["q"], "kalshi": km["ticker"], "outcome": m["outcomes"][i], "size": size,
                       "start": datetime.fromtimestamp(m["start"], timezone.utc).isoformat(timespec="minutes")}
                if fp:
                    row["pm_px"] = fp[1]
                    row["pm_all"] = fp[1] + jup_fee(table, fp[1])
                if fk:
                    row["k_px"] = fk[1]
                    row["k_all"] = fk[1] + kalshi_fee(fk[1], fk[0])
                if fp and fk:
                    row["diff_pp"] = (row["pm_all"] - row["k_all"]) * 100     # + = Kalshi olcsóbb
                    row["save_rel"] = abs(row["pm_all"] - row["k_all"]) / max(row["pm_all"], row["k_all"])
                rows.append(row)
    keys = ["start", "pm_q", "kalshi", "outcome", "size", "pm_px", "pm_all", "k_px", "k_all", "diff_pp", "save_rel"]
    with (OUT / "venue_pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        cw = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(rows)

    say("\nEREDMÉNY – teljes költség szerződésenként (ár + díj); különbség = Polymarket/Jupiter − Kalshi")
    for size in SIZES:
        rs = [r for r in rows if r["size"] == size and "diff_pp" in r]
        if not rs:
            say(f"  ${size}: nincs összevethető pár (likviditás hiányzik az egyik oldalon)")
            continue
        d = [r["diff_pp"] for r in rs]
        ad = sorted(abs(x) for x in d)
        say(f"  ${size:>5}: {len(rs)} kimenet; |különbség| medián {statistics.median(ad):.2f} sz.pont, "
            f"75%: {ad[int(.75 * len(ad))]:.2f}, 90%: {ad[int(.9 * len(ad))]:.2f}; "
            f">1 sz.pont: {sum(x > 1 for x in ad) / len(ad):.0%}, >2: {sum(x > 2 for x in ad) / len(ad):.0%}, "
            f">5: {sum(x > 5 for x in ad) / len(ad):.0%}; Kalshi olcsóbb: {sum(x > 0 for x in d) / len(d):.0%}; "
            f"megtakarítás medián {statistics.median(r['save_rel'] for r in rs):.1%}")
        only_pm = sum(1 for r in rows if r["size"] == size and "pm_all" in r and "k_all" not in r)
        only_k = sum(1 for r in rows if r["size"] == size and "k_all" in r and "pm_all" not in r)
        say(f"          csak Polymarketen teljesíthető: {only_pm}, csak Kalshin: {only_k}")
    big = sorted((r for r in rows if r.get("size") == 500 and "diff_pp" in r), key=lambda r: -abs(r["diff_pp"]))[:10]
    if big:
        say("\nLegnagyobb különbségek ($500):")
        for r in big:
            say(f"  {r['outcome'][:28]:<28} PM+Jup {r['pm_all']:.3f}  Kalshi {r['k_all']:.3f}  ({r['diff_pp']:+.1f} sz.pont)  {r['pm_q'][:40]}")
    say("\nMegjegyzés: a Kalshi-oldalon a DFlow saját díja nincs benne (alsó becslés); a Jupiter-díj a saját mérésünk.")
    (OUT / "venue_report.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
