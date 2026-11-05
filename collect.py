"""EDGEHOG gyűjtő: a Jupiter Predict globális kötésfolyamának mentése (2 percenként fut).

A /trades csak a legutóbbi ~20 kötést adja (lapozás nélkül; 2026-11-04-én ez ~9 percnyi
forgalom volt), ezért kell sűrűn futnia. Ha egy futás egyetlen már mentett kötést sem lát,
lehetett hézag: ezt a napló jelzi (HÉZAG?).

Minden futás lekéri a /trades legfrissebb oldalait, amíg már látott kötéshez nem ér,
és az újakat hozzáírja a data/trades/trades_ÉÉÉÉHHNN.jsonl fájlhoz (UTC nap, soronként
egy kötés, ahogy az API adja, plusz a lekérés ideje: _fetched).
Erre épül: nagy véletlen átlagcsoport (probe.py --baseline 300) és az időbeli ellenőrzés.

Napló: output/collector.log (soronként egy futás). Ablak nélkül fut (pythonw), a
Windows ütemezett feladat indítja: install_collector.bat.

Kézi próba:  python collect.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)                                   # az ütemező máshonnan indítja

import requests                                  # noqa: E402

JUP = "https://api.jup.ag/prediction/v1"
TRADES = HERE / "data" / "trades"
STATE = TRADES / "seen.json"                     # a legutóbb látott kötések kulcsai
LOCK = TRADES / ".lock"
LOG = HERE / "output" / "collector.log"
PAGE = 100
MAX_PAGES = 5                                    # a feed jelenleg nem lapoz; tartalék
KEEP_KEYS = 30000


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if sys.stdout:
        try:
            print(line)
        except Exception:
            pass


def key(r: dict) -> str:
    """Stabil azonosító egy kötéshez (az API mezőitől függően)."""
    for k in ("id", "tradeId", "fillId"):
        if r.get(k) not in (None, ""):
            return f"{k}:{r[k]}"
    parts = [str(r.get(k, "")) for k in ("signature", "orderPubkey", "ownerPubkey", "marketId",
                                         "timestamp", "isBuy", "isYes", "avgFillPriceUsd",
                                         "filledContracts", "contracts", "amountUsd", "priceUsd")]
    if any(parts[:2]):
        return "sig:" + "|".join(parts)
    return "h:" + hashlib.sha1(json.dumps(r, sort_keys=True).encode()).hexdigest()


def fetch(api_key: str, start: int) -> list[dict]:
    for i in range(4):
        try:
            r = requests.get(f"{JUP}/trades", params={"start": start, "end": start + PAGE},
                             headers={"x-api-key": api_key, "User-Agent": "edgehog-collector/0.1"},
                             timeout=40)
        except requests.RequestException:
            time.sleep(3 * (i + 1))
            continue
        if r.status_code in (401, 403):
            raise SystemExit(f"Jupiter: a kulcs nem jó ({r.status_code})")
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(30, 3 * 2 ** i))
            continue
        r.raise_for_status()
        return r.json().get("data") or []
    raise RuntimeError("a /trades többszöri próbára sem válaszolt")


def main():
    TRADES.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 15 * 60:
        log("előző futás még tart, kihagyom")
        return
    LOCK.write_text(str(os.getpid()))
    try:
        api_key = os.environ.get("JUPITER_API_KEY", "").strip() or \
            (HERE / ".jupkey").read_text(encoding="utf-8").strip()
        try:
            seen = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = []
        seen_set = set(seen)
        first_run = not seen
        now = datetime.now(timezone.utc)
        new, pages, caught_up, overlap = [], 0, False, False
        for pages in range(1, MAX_PAGES + 1):
            rows = fetch(api_key, (pages - 1) * PAGE)
            if not rows:
                caught_up = True
                break
            fresh = [r for r in rows if key(r) not in seen_set]
            overlap = overlap or len(fresh) < len(rows)
            for r in fresh:
                seen_set.add(key(r))
            new += fresh
            if len(fresh) < len(rows) or first_run and pages >= 5:
                caught_up = True                 # elértük a már mentett részt
                break
            time.sleep(0.3)
        if new:
            out = TRADES / f"trades_{now:%Y%m%d}.jsonl"
            stamp = now.isoformat(timespec="seconds")
            with out.open("a", encoding="utf-8") as fh:
                for r in reversed(new):          # régebbi előre
                    fh.write(json.dumps({**r, "_fetched": stamp}, ensure_ascii=False) + "\n")
        seen = (seen + [key(r) for r in reversed(new)])[-KEEP_KEYS:]
        STATE.write_text(json.dumps(seen), encoding="utf-8")
        owners = len({r.get("ownerPubkey") for r in new if r.get("ownerPubkey")})
        warn = ""
        if not first_run and not overlap:
            warn = "  HÉZAG? egyetlen korábbi kötést sem láttam újra, a két futás között kimaradhatott forgalom"
        elif not caught_up:
            warn = f"  FIGYELEM: {MAX_PAGES} oldal után sem értem utol"
        span = [r.get("timestamp") for r in new if isinstance(r.get("timestamp"), (int, float))]
        if span:
            warn = f", időtáv: {(max(span) - min(span)) / 60:.1f} perc" + warn
        log(f"új kötés: {len(new)}, tárca: {owners}, oldal: {pages}{warn}")
    except SystemExit as e:
        log(f"HIBA: {e}")
    except Exception as e:
        log(f"HIBA: {type(e).__name__}: {e}")
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
