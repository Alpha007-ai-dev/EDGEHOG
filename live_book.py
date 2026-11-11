"""EDGEHOG élő árfolyamkönyv-ellenőrzés (2026-11-11).

Kérdés: a Jupiter /orderbook ugyanazt a könyvet mutatja-e, mint a Polymarket CLOB, és mennyibe kerülne
most egy $50 / $250 / $1000-os vétel a költségmotor szerint.
Piacok: a gyűjtő legfrissebb napi fájljából az utolsó 30 percben kötött Jupiter-piacok (max. 12).
Kimenet: output/live_book.txt (riport), data/live/<időbélyeg>/*.json (nyers válaszok).
Futtatás: python live_book.py   (kulcs: .jupkey vagy JUPITER_API_KEY)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

JUP = "https://api.jup.ag/prediction/v1"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
OUT = Path("output")
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
RAW = Path("data/live") / STAMP
S = requests.Session()
S.headers["User-Agent"] = "edgehog-live/0.1"
LINES: list[str] = []
STATS = {"markets": 0, "identical": 0, "levels": 0, "same": 0}


def say(s=""):
    print(s, flush=True)
    LINES.append(s)


def key() -> str:
    k = os.environ.get("JUPITER_API_KEY") or (Path(".jupkey").read_text(encoding="utf-8").strip()
                                              if Path(".jupkey").exists() else "")
    if not k:
        sys.exit("Nincs Jupiter-kulcs (.jupkey)")
    return k


def get(url, params=None, headers=None):
    for i in range(3):
        try:
            r = S.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 * (i + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    return None


def save(name, data):
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def fee(p: float) -> float:                      # Jupiter díj / kontraktus, 2026-10-27 óta (mért)
    return 0.0181 * p + 0.052 * p * (1 - p)


def to_price(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x > 100:          # mikro-dollár
        x /= 1e6
    elif x > 1:          # cent
        x /= 100
    return x


def levels(raw) -> list[tuple[float, float]]:
    out = []
    for l in raw or []:
        if isinstance(l, dict):
            p = to_price(l.get("price") or l.get("p") or l.get("priceUsd"))
            s = l.get("size") or l.get("quantity") or l.get("contracts") or l.get("amount") or l.get("s")
        elif isinstance(l, (list, tuple)) and len(l) >= 2:
            p, s = to_price(l[0]), l[1]
        else:
            continue
        try:
            s = float(s)
        except (TypeError, ValueError):
            continue
        if p is not None and 0 < p < 1 and s > 0:
            out.append((p, s))
    return out


def jup_book(jb):
    """Jupiter /orderbook (Kalshi-formátum): yes_dollars = YES vételi ajánlatok, no_dollars = NO vételi ajánlatok.
    Egy NO-vétel p áron = YES-eladás 1−p áron, ezért a YES eladási oldala: (1−p, méret)."""
    bids = [(round(float(p), 4), float(s)) for p, s in jb.get("yes_dollars") or []]
    asks = [(round(1 - float(p), 4), float(s)) for p, s in jb.get("no_dollars") or []]
    return bids, asks


def mirror(a, b):
    """Hány szint egyezik árban és méretben (0,01 kontraktus pontossággal)."""
    da = {round(p, 4): s for p, s in a}
    db = {round(p, 4): s for p, s in b}
    same = sum(1 for p in da if p in db and abs(da[p] - db[p]) < 0.01)
    return same, len(da), len(db)


def walk(asks, usd):
    """Vétel $usd értékben a könyv eladási oldalán: (kontraktus, átlagár, kitöltetlen $)."""
    left, n, cost = usd, 0.0, 0.0
    for p, s in sorted(asks):
        take = min(s, left / p)
        n += take
        cost += take * p
        left -= take * p
        if left <= 1e-9:
            break
    return n, (cost / n if n else None), max(left, 0)


def recent_markets(limit=12, window=1800):
    files = sorted(Path("data/trades").glob("trades_*.jsonl"))
    rows = []
    for f in files[-2:]:
        for line in f.open(encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if not rows:
        return []
    t_last = max(r.get("timestamp", 0) for r in rows)
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: -r.get("timestamp", 0)):
        mk = r.get("marketId", "")
        if r.get("timestamp", 0) < t_last - window:
            break
        if mk.startswith("POLY-") and mk not in seen:
            seen.add(mk)
            out.append((mk, r.get("eventTitle", ""), r.get("marketTitle", "")))
        if len(out) >= limit:
            break
    return out


def main():
    k = key()
    hdr = {"x-api-key": k}
    mk_list = recent_markets()
    say(f"EDGEHOG élő könyv-ellenőrzés – {STAMP}")
    say(f"Piacok (az utolsó 30 percben kötöttek a Jupiteren): {len(mk_list)}\n")
    for mk, ev, title in mk_list:
        parts = mk.split("-")
        gid, idx = parts[1], (int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0)
        say(f"== {mk}  {ev} – {title}")
        g = get(f"{GAMMA}/markets/{gid}")
        try:
            meta = g.json() if g is not None else {}
        except ValueError:
            meta = {}
        toks = meta.get("clobTokenIds")
        toks = json.loads(toks) if isinstance(toks, str) else toks
        if not toks or idx >= len(toks):
            say("   Polymarket: nincs token")
            continue

        def poly():
            pb = get(f"{CLOB}/book", {"token_id": toks[idx]})
            try:
                return pb.json() if pb is not None else {}
            except ValueError:
                return {}

        # Polymarket – Jupiter – Polymarket közvetlenül egymás után: a Jupiter-könyvet a hozzá
        # időben közelebbi / jobban egyező Polymarket-pillanatképpel vetjük össze
        before = poly()
        r = get(f"{JUP}/orderbook/{mk}", headers=hdr)
        after = poly()
        if r is None:
            say("   Jupiter /orderbook: hálózati hiba")
            continue
        try:
            jb = r.json()
        except ValueError:
            jb = {"_text": r.text[:3000]}
        save(f"jup_orderbook_{mk}.json", {"status": r.status_code, "body": jb})
        save(f"poly_book_{mk}.json", {"before": before, "after": after})
        rm = get(f"{JUP}/markets/{mk}", headers=hdr)
        if rm is not None:
            try:
                save(f"jup_market_{mk}.json", {"status": rm.status_code, "body": rm.json()})
            except ValueError:
                pass
        if r.status_code != 200:
            say(f"   Jupiter /orderbook: HTTP {r.status_code}")
        jbids, jasks = jup_book(jb) if r.status_code == 200 and isinstance(jb, dict) else ([], [])

        def score(bk):
            return mirror(jbids, levels(bk.get("bids")))[0] + mirror(jasks, levels(bk.get("asks")))[0]

        book = before if score(before) >= score(after) else after
        bids, asks = levels(book.get("bids")), levels(book.get("asks"))
        if jbids or jasks:
            sb, nb, _ = mirror(jbids, bids)
            sa, na, _ = mirror(jasks, asks)
            STATS["levels"] += nb + na
            STATS["same"] += sb + sa
            STATS["markets"] += 1
            STATS["identical"] += (sb == nb == len(bids)) and (sa == na == len(asks))
            say(f"   Jupiter vs Polymarket könyv: vételi oldal {sb}/{nb} szint azonos, eladási oldal {sa}/{na} szint azonos")
        if not bids or not asks:
            say("   Polymarket könyv üres")
            continue
        bb, ba = max(p for p, _ in bids), min(p for p, _ in asks)
        mid = (bb + ba) / 2
        say(f"   Polymarket: legjobb {bb:.3f} / {ba:.3f}, közép {mid:.3f}, spread {100 * (ba - bb):.1f} c")
        for usd in (50, 250, 1000):
            n, avg, left = walk(asks, usd)
            if not n:
                continue
            f = n * fee(avg)
            cost = n * (avg - mid) + f
            say(f"   YES vétel ${usd:>4}: {n:7.1f} kontr., átl. {avg:.3f}, spread+csúszás ${n * (avg - mid):6.2f}, "
                f"díj ${f:5.2f}, összesen {100 * cost / (n * mid):5.2f}%" + (f"  (kitöltetlen ${left:.0f})" if left > 1 else ""))
        say()
    if STATS["markets"]:
        say(f"ÖSSZESEN: {STATS['identical']}/{STATS['markets']} piacon szintről szintre azonos a két könyv; "
            f"{STATS['same']}/{STATS['levels']} szint egyezik árban és méretben.")
    OUT.mkdir(exist_ok=True)
    (OUT / "live_book.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    say(f"Nyers válaszok: {RAW}")
    say("KESZ")


if __name__ == "__main__":
    main()
