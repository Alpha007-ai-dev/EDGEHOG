"""EDGEHOG Trader Desk – local trade server (2026-11-11).

Serves trade.html on http://127.0.0.1:8787 and relays the Jupiter Prediction API with the key from .jupkey,
so the key never reaches the browser. The user signs every order in their own wallet (Phantom); this server
never holds a private key and cannot move funds.
Safety: buys only, at most MAX_USD per order (default $25, env EDGEHOG_MAX_USD), $5 Jupiter minimum.
Execution reports are saved to output/trades/<time>_<order>.json.

Run: python trade_server.py   (run_trade.bat also opens the browser)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

JUP = "https://api.jup.ag/prediction/v1"
PORT = 8787
MAX_USD = float(os.environ.get("EDGEHOG_MAX_USD", "25"))
ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "output" / "trades"
S = requests.Session()
S.headers["User-Agent"] = "edgehog-trade/0.1"


def key() -> str:
    k = os.environ.get("JUPITER_API_KEY") or ((ROOT / ".jupkey").read_text(encoding="utf-8").strip()
                                              if (ROOT / ".jupkey").exists() else "")
    if not k:
        sys.exit("Nincs Jupiter-kulcs (.jupkey)")
    return k


KEY = key()


def jup(method: str, path: str, params=None, body=None):
    try:
        r = S.request(method, f"{JUP}{path}", params=params, json=body,
                      headers={"x-api-key": KEY}, timeout=30)
    except requests.RequestException as e:
        return 502, {"type": "api_error", "message": f"Jupiter unreachable: {e}"}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"type": "api_error", "message": r.text[:500]}


def recent_markets(limit=40, window=3 * 3600):
    """Markets traded on Jupiter in the last hours, from the collector's daily files."""
    rows = []
    for f in sorted((ROOT / "data" / "trades").glob("trades_*.jsonl"))[-2:]:
        for line in f.open(encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    if not rows:
        return []
    t_last = max(r.get("timestamp", 0) for r in rows)
    agg: dict[str, dict] = {}
    for r in rows:
        mk = r.get("marketId", "")
        if not mk.startswith("POLY-") or r.get("timestamp", 0) < t_last - window:
            continue
        a = agg.setdefault(mk, {"marketId": mk, "event": r.get("eventTitle", ""), "title": r.get("marketTitle", ""),
                                "trades": 0, "usd": 0.0, "last": 0})
        a["trades"] += 1
        a["usd"] += (float(r.get("amountUsd") or 0) / 1e6)
        a["last"] = max(a["last"], r.get("timestamp", 0))
    return sorted(agg.values(), key=lambda a: -a["usd"])[:limit]


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("%s  %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    def send(self, code: int, obj, ctype="application/json"):
        data = obj if isinstance(obj, bytes) else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if p in ("/", "/trade.html"):
            return self.send(200, (ROOT / "trade.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/api/config":
            return self.send(200, {"maxUsd": MAX_USD, "minUsd": 5})
        if p == "/api/recent":
            return self.send(200, recent_markets())
        for prefix, target in (("/api/market/", "/markets/"), ("/api/orderbook/", "/orderbook/"),
                               ("/api/orders/status/", "/orders/status/")):
            if p.startswith(prefix):
                return self.send(*jup("GET", target + p[len(prefix):]))
        if p in ("/api/positions", "/api/history", "/api/trading-status"):
            return self.send(*jup("GET", p[4:], params=q))
        self.send(404, {"message": "not found"})

    def do_POST(self):
        b = self.body()
        if self.path == "/api/orders":
            try:
                usd = float(b.get("depositAmount", 0)) / 1e6
            except (TypeError, ValueError):
                usd = 0
            if b.get("isBuy") is not True:
                return self.send(400, {"message": "This desk only places buys."})
            if not b.get("ownerPubkey") or not b.get("marketId"):
                return self.send(400, {"message": "Connect a wallet and pick a market first."})
            if usd < 5 or usd > MAX_USD:
                return self.send(400, {"message": f"Order size must be between $5 and ${MAX_USD:.0f}."})
            body = {k: b[k] for k in ("ownerPubkey", "marketId", "isYes", "isBuy", "depositAmount", "depositMint") if k in b}
            return self.send(*jup("POST", "/orders", body=body))
        if self.path == "/api/execute":
            body = {k: b[k] for k in ("signedTransaction", "context", "requestId") if k in b}
            return self.send(*jup("POST", "/execute", body=body))
        if self.path == "/api/report":
            REPORTS.mkdir(parents=True, exist_ok=True)
            name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{str(b.get('orderPubkey', 'order'))[:8]}.json"
            (REPORTS / name).write_text(json.dumps(b, indent=1), encoding="utf-8")
            return self.send(200, {"saved": f"output/trades/{name}"})
        self.send(404, {"message": "not found"})


if __name__ == "__main__":
    print(f"EDGEHOG Trader Desk: http://127.0.0.1:{PORT}   (max ${MAX_USD:.0f} / order, buys only)")
    print("Hagyd nyitva ezt az ablakot, amíg kereskedsz. Bezárás: Ctrl+C vagy az ablak bezárása.")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    srv.serve_forever()
