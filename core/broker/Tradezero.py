#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TradeZero - the broker side of Kestrel 3.12: the REST client (orders, positions, account, locates; one
keep-alive connection per thread, network retries that never double an order, the urgent no-wait path for a halt
reopen), the keys from the .env file, and the order-field helpers (status sets, prices, sides, times).
Part of Kestrel - keep it next to main.py. Names written app.X live in main.py (the settings at its top).
"""
import sys
import logging
import calendar
import http.client
import json
import math
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

app = sys.modules["lh_host"]                     # main.py (it binds itself before importing this file)
log = logging.getLogger("lh_app")


# -----------------------------------------------------------------------------
# TradeZero REST client (orders, positions, account, locates). TradeZero has no
# market data - candles and prices come from IB Gateway.
# Docs: https://developer.tradezero.com/docs/documentation
# -----------------------------------------------------------------------------
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class TZError(Exception):
    """status 0 = no HTTP answer (network). sent=False: the request certainly never reached TradeZero (failed while
    connecting) - safe to send again; sent=True: it may have arrived (look the order up by its id before re-sending)."""

    def __init__(self, status, text, path="", sent=True):
        super().__init__(f"HTTP {status} {path}: {text}")
        self.status, self.text, self.path, self.sent = status, text, path, sent
class _NetFail(Exception):
    def __init__(self, exc, sent, reused):
        super().__init__(str(exc))
        self.exc, self.sent, self.reused = exc, sent, reused
        self.text = f"{exc.__class__.__name__}: {exc}" if str(exc) else exc.__class__.__name__
def tz_load_keys():
    """3.11: the keys come from the .env file next to the app (the only place once it exists - the start-up copies the
    old tradezero.json in). Without a .env file: tradezero.json (app data folder / next to the app), then the
    environment, then the settings at the top of this file."""
    cfg = {"api_key_id": app.TZ_API_KEY_ID, "api_secret": app.TZ_API_SECRET, "account_id": app.TZ_ACCOUNT_ID, "route": app.TZ_ROUTE}
    env_id, env_sec = os.environ.get("TZ_API_KEY_ID", ""), os.environ.get("TZ_API_SECRET_KEY", "") or \
        os.environ.get("TZ_API_SECRET", "")
    if env_id and env_sec:
        cfg["api_key_id"], cfg["api_secret"] = env_id, env_sec
    have_env = os.path.isfile(app.env_path())
    for path in (() if have_env else (os.path.join(app._base_dir(), "tradezero.json"), os.path.join(app.DATA_DIR, "tradezero.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for k in cfg:
                if str(data.get(k, "") or "").strip():
                    cfg[k] = str(data[k]).strip()
            cfg["file"] = path
        except (OSError, ValueError):
            pass
    env = app.env_read() if have_env else {}
    for ck, ek in (("api_key_id", "TZ_API_KEY_ID"), ("api_secret", "TZ_API_SECRET"), ("account_id", "TZ_ACCOUNT_ID"),
                   ("route", "TZ_ROUTE")):
        if env.get(ek):
            cfg[ck] = env[ek].strip()
    if have_env:
        cfg["file"] = app.env_path()
    return cfg
def tz_save_keys(key_id, secret, account_id=""):
    """3.11: the Keys dialog writes to the .env file (an empty secret keeps the saved one)."""
    up = {"TZ_ACCOUNT_ID": (account_id or "").strip()}
    if key_id:
        up["TZ_API_KEY_ID"] = key_id.strip()
    if secret:
        up["TZ_API_SECRET"] = secret.strip()
    return app.env_write(up)
class TZClient:
    """Blocking calls - the bot runs them in worker threads.
    v3.3: every thread keeps ONE open (keep-alive) HTTPS connection to TradeZero and re-uses it, instead of a new
    TLS handshake for every call (the old 'HTTP 0 ... handshake operation timed out' errors). Network failures are
    retried: reads and cancels up to 3 times; a new order only when it certainly never left this PC (failed while
    connecting) - otherwise the bot looks the order up by its id first, so a network blip can never double an order."""
    IDLE_MAX = 25.0          # s: a connection idle longer than this is re-opened (servers drop idle keep-alives)
    POST_IDLE_MAX = 8.0      # s: an order goes out on a connection used within this time, else on a fresh one
    NET_TRIES = 3            # attempts per call on network errors

    def __init__(self, key_id, secret, base=None, timeout=10, connect_timeout=6):
        self.key_id, self.secret = key_id, secret
        self.base = (base or app.TZ_BASE_URL).rstrip("/")
        u = urllib.parse.urlsplit(self.base)
        self.https = u.scheme == "https"
        self.host, self.port = u.hostname, u.port or (443 if self.https else 80)
        self.prefix = u.path.rstrip("/")
        self.timeout, self.connect_timeout = timeout, connect_timeout
        self.lock = threading.Lock()
        self.last_call = 0.0
        self.local = threading.local()
        self.conns = set()
        self.conns_lock = threading.Lock()
        self.ssl_ctx = ssl.create_default_context() if self.https else None
        self.proxy = self._find_proxy()
        self.net_fail = 0                                # calls in a row that got no answer at all (after retries)
        self.stats = {"calls": 0, "connects": 0, "net_retries": 0}

    def _find_proxy(self):
        """A system / environment HTTPS proxy, like urllib uses (None on almost every trading PC)."""
        if not self.https:
            return None
        try:
            if urllib.request.proxy_bypass(self.host):
                return None
            p = urllib.request.getproxies().get("https")
        except Exception:
            return None
        if not p:
            return None
        pu = urllib.parse.urlsplit(p if "://" in p else "http://" + p)
        hdr = {}
        if pu.username:
            import base64
            tok = base64.b64encode(f"{urllib.parse.unquote(pu.username)}:{urllib.parse.unquote(pu.password or '')}".encode()).decode()
            hdr["Proxy-Authorization"] = "Basic " + tok
        return (pu.hostname, pu.port or 8080, hdr)

    # ---- connections (one per thread, re-used) ----
    def _drop(self):
        c = getattr(self.local, "conn", None)
        self.local.conn = None
        if c is not None:
            with self.conns_lock:
                self.conns.discard(c)
            try:
                c.close()
            except Exception:
                pass

    def close(self):
        """Close every open connection (keys changed / app closing)."""
        with self.conns_lock:
            cs, self.conns = list(self.conns), set()
        for c in cs:
            try:
                c.close()
            except Exception:
                pass

    def _conn(self, max_idle):
        c = getattr(self.local, "conn", None)
        if c is not None and (c.sock is None or time.monotonic() - getattr(self.local, "used", 0.0) > max_idle):
            self._drop()
            c = None
        if c is None:
            if self.https and self.proxy:
                ph, pp, hdr = self.proxy
                c = http.client.HTTPSConnection(ph, pp, timeout=self.connect_timeout, context=self.ssl_ctx)
                c.set_tunnel(self.host, self.port, headers=hdr or None)
            elif self.https:
                c = http.client.HTTPSConnection(self.host, self.port, timeout=self.connect_timeout, context=self.ssl_ctx)
            else:
                c = http.client.HTTPConnection(self.host, self.port, timeout=self.connect_timeout)
            self.local.conn = c
            with self.conns_lock:
                self.conns.add(c)
        return c

    def _once(self, method, path, data, headers):
        c = self._conn(self.POST_IDLE_MAX if method == "POST" else self.IDLE_MAX)
        reused = c.sock is not None
        sent = False
        try:
            if c.sock is None:                           # TCP + TLS handshake: nothing has been sent yet
                c.connect()
                c.sock.settimeout(self.timeout)
                self.stats["connects"] += 1
            sent = True
            c.request(method, self.prefix + path, body=data, headers=headers)
            resp = c.getresponse()
            raw = resp.read()
        except Exception as exc:
            self._drop()
            raise _NetFail(exc, sent, reused)
        if resp.will_close:
            self._drop()
        else:
            self.local.used = time.monotonic()
        return resp.status, resp.reason, raw

    def _req(self, method, path, body=None, ok404=False):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", "TZ-API-KEY-ID": self.key_id, "TZ-API-SECRET-KEY": self.secret,
                   "Connection": "keep-alive"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        safe = method in ("GET", "DELETE")               # reading / cancelling twice does no harm
        n429 = nnet = 0
        had_net = False
        while True:
            with self.lock:                              # gentle pacing: max ~10 calls / second
                wait = 0.1 - (time.monotonic() - self.last_call)
                if wait > 0 and not getattr(self.local, "no_pace", False):     # 3.12: a reopen order never waits
                    time.sleep(wait)
                self.last_call = time.monotonic()
            self.stats["calls"] += 1
            t_call = time.monotonic()
            try:
                status, reason, raw = self._once(method, path, data, headers)
                self.last_ms = int((time.monotonic() - t_call) * 1000)    # 3.11: the bot center shows it
            except _NetFail as nf:
                nnet += 1
                stale = nf.reused and nnet == 1          # an idle keep-alive the server had closed: retry at once
                if (safe or not nf.sent) and nnet < self.NET_TRIES:
                    had_net = True
                    self.stats["net_retries"] += 1
                    time.sleep(0.05 if stale else 0.4 * nnet)
                    continue
                self.net_fail += 1
                raise TZError(0, nf.text, path, sent=nf.sent)
            self.net_fail = 0
            text = raw.decode("utf-8", "replace")
            if status == 429 and n429 < 2:               # rate limited: back off and retry
                n429 += 1
                time.sleep(1.0 + n429)
                continue
            if 200 <= status < 300:
                if not text.strip():
                    return {}
                try:
                    return json.loads(text)
                except ValueError:
                    return {"raw": text}
            if status == 404 and ok404:
                return None
            if method == "DELETE" and had_net and status in (400, 404, 409, 422):
                return {}                                # the first cancel got through before the network dropped
            raise TZError(status, text[:300] or reason, path)

    # ---- account ----
    def accounts(self):
        r = self._req("GET", "/v1/api/accounts")
        return (r or {}).get("accounts", []) if isinstance(r, dict) else (r or [])

    def account(self, acc):
        return self._req("GET", f"/v1/api/account/{acc}")

    def pnl(self, acc):
        return self._req("GET", f"/v1/api/accounts/{acc}/pnl")

    def positions(self, acc):
        r = self._req("GET", f"/v1/api/accounts/{acc}/positions")
        if isinstance(r, dict):
            for k in ("positions", "openPositions", "data"):
                if isinstance(r.get(k), list):
                    return r[k]
            return []
        return r or []

    # ---- orders ----
    def orders(self, acc):
        r = self._req("GET", f"/v1/api/accounts/{acc}/orders")
        if isinstance(r, dict):
            for k in ("orders", "data"):
                if isinstance(r.get(k), list):
                    return r[k]
            return []
        return r or []

    def history(self, acc, start_date, days=30, symbol=None, max_rows=5000):
        """3.13: TradeZero's fills from start_date on (one row per execution: symbol, side Buy/Sell, qty, price,
        netProceeds, tradeDate, execTime). Live accounts only - paper accounts always return none. Read-only.
        Rate limit: 1 request a second per key, so pages are 1.05 s apart."""
        rows, off = [], 0
        days = max(1, min(365, int(days)))
        while True:
            q = f"?numberOfDays={days}&offset={off}&limit=100"
            if symbol:
                q += "&symbol=" + urllib.parse.quote(str(symbol))
            r = self._req("GET", f"/v1/api/accounts/{acc}/orders-with-pagination/start-date/{start_date}{q}", ok404=True)
            page = r.get("tradingHistory") if isinstance(r, dict) else None
            if not page:
                break
            rows += [x for x in page if isinstance(x, dict) and not x.get("canceled")]
            tot = int(_num((r.get("pagination") or {}).get("totalRecords")) or 0) if isinstance(r, dict) else 0
            off += len(page)
            if off >= tot or len(page) < 100 or off >= max_rows:
                break
            time.sleep(1.05)
        return rows

    def order(self, acc, coid):
        r = self._req("GET", f"/v1/api/accounts/{acc}/order/{coid}", ok404=True)
        if r is None:                                       # R118 with a route can rename the id ("...INVALID")
            for o in self.orders(acc):
                if str(o.get("clientOrderId", "")).startswith(coid):
                    return o
        return r

    def place(self, acc, symbol, side, open_close, order_type, qty, tif="Day", limit=None, stop=None, coid=None, route=None):
        body = {"securityType": "Stock", "symbol": symbol, "side": side, "openClose": open_close,
                "orderType": order_type, "orderQuantity": int(qty), "timeInForce": tif}
        if limit is not None:
            body["limitPrice"] = limit
        if stop is not None:
            body["stopPrice"] = stop
        if coid:
            body["clientOrderId"] = coid
        if route:
            body["route"] = route
        return self._req("POST", f"/v1/api/accounts/{acc}/order", body)

    def place_urgent(self, acc, symbol, side, open_close, order_type, qty, tif="Day", limit=None, stop=None, coid=None,
                     route=None):
        """3.12: a halt-reopen order (market cover / the stop): no pacing wait. The bot sends it on its own thread whose
        keep-alive connection it keeps warm during the halt, so it goes out the moment the stock trades again."""
        self.local.no_pace = True
        try:
            return self.place(acc, symbol, side, open_close, order_type, qty, tif, limit=limit, stop=stop, coid=coid,
                              route=route)
        finally:
            self.local.no_pace = False

    def cancel(self, acc, coid):
        return self._req("DELETE", f"/v1/api/accounts/{acc}/orders/{coid}", ok404=True)

    def is_etb(self, acc, symbol):
        r = self._req("GET", f"/v1/api/accounts/{acc}/is-easy-to-borrow/symbol/{symbol}")
        return bool((r or {}).get("isEasyToBorrow"))

    # ---- locates ----
    def locate_quote(self, acc, symbol, qty, qid):
        return self._req("POST", "/v1/api/accounts/locates/quote",
                         {"account": acc, "symbol": symbol, "quantity": int(qty), "quoteReqID": qid})

    def locate_history(self, acc):
        r = self._req("GET", f"/v1/api/accounts/{acc}/locates/history")
        return (r or {}).get("locateHistory", []) if isinstance(r, dict) else (r or [])

    def locate_accept(self, acc, qid):
        return self._req("POST", "/v1/api/accounts/locates/accept", {"accountId": acc, "quoteReqID": qid})

    def locate_inventory(self, acc):
        r = self._req("GET", f"/v1/api/accounts/{acc}/locates/inventory")
        return (r or {}).get("locateInventory", []) if isinstance(r, dict) else (r or [])

    def locate_sell(self, acc, symbol, qty, locate_type, qid):
        return self._req("POST", "/v1/api/accounts/locates/sell",
                         {"account": acc, "symbol": symbol, "quantity": int(qty), "locateType": locate_type, "quoteReqID": qid})

    def locate_cancel(self, acc, qid):
        return self._req("DELETE", f"/v1/api/accounts/locates/cancel/accounts/{acc}/quoteReqID/{qid}")
# -----------------------------------------------------------------------------
# AUTO-TRADING BOT (v3.5: + the premarket long module (lh_long_premarket.py) 05:00-09:00 in the same app;
#                   v3.4: bounce-zone + vacuum short with the v16 vacuum rules, Discord notifications,
#                   orders panel under the chart: pending / filled orders, cancel and change the price,
#                   v3.4: the "stock flow" picture - the plan drawn on a clean line chart - on every symbol message)
#   watchlist symbols you type in -> IB 1-min candles -> the v16 engine on the closed candles every minute
#   -> TradeZero: pre-locate when the stock is stretched 20%+ above VWAP (once a day, re-used all day),
#      bounce-zone short = resting limit 12% under the top; vacuum short = marketable limit at the signal,
#      a stop right after every fill, your own stop changes followed, no automatic cover at the close
#      (urgent Discord alert at 15:50 instead) - everything reported to Discord with 1-minute chart images.
# -----------------------------------------------------------------------------
LOCATE_TYPES = {1: "Locate", 2: "Locate", 3: "PreBorrow", 4: "SingleUse"}
DONE_STATES = ("Filled", "Canceled", "Rejected", "DoneForDay", "Expired")
OPEN_STATES = ("New", "PendingNew", "PartiallyFilled")
def px_round(p, up):
    """TradeZero price increments: $0.0001 under $1, $0.01 from $1."""
    step = 0.0001 if p < 1.0 else 0.01
    n = p / step
    n = math.ceil(n - 1e-7) if up else math.floor(n + 1e-7)
    return round(n * step, 4 if p < 1.0 else 2)
def _fnum(x, default=0.0):
    try:
        x = float(x)
        return default if x != x else x
    except (TypeError, ValueError):
        return default
def _tick_px(p):
    """Nearest valid TradeZero price ($0.0001 under $1, $0.01 from $1)."""
    step = 0.0001 if p < 1.0 else 0.01
    return round(round(p / step) * step, 4 if p < 1.0 else 2)
def _tz_time(v):
    """A TradeZero time field -> (UTC epoch seconds or None, naive epoch or None when it has no time zone)."""
    if v is None or v == "":
        return None, None
    if isinstance(v, (int, float)):
        x = float(v)
        return (x / 1000.0 if x > 1e11 else x), None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$", str(v).strip())
    if not m:
        return None, None
    try:
        naive = calendar.timegm(datetime.strptime(m.group(1) + " " + m.group(2), "%Y-%m-%d %H:%M:%S").timetuple())
    except ValueError:
        return None, None
    z = m.group(3)
    if not z:
        return None, naive
    off = 0 if z == "Z" else (1 if z[0] == "+" else -1) * (int(z[1:3]) * 60 + int(z[-2:])) * 60
    return naive - off, None
def _otype(o):
    t = str(o.get("orderType") or "").replace("_", "").replace(" ", "").lower()
    return {"limit": "Limit", "market": "Market", "stop": "Stop", "stoplimit": "StopLimit", "stopmarket": "Stop"}.get(
        t, str(o.get("orderType") or "?"))
def _olimit(o):
    return _fnum(o.get("limitPrice", o.get("priceLimit")), 0.0)
def _ostop(o):
    return _fnum(o.get("priceStop", o.get("stopPrice")), 0.0)
def _oside(o):
    """(label, css class): Short / Cover / Buy / Sell."""
    sd, oc = str(o.get("side") or "").lower(), str(o.get("openClose") or "").lower()
    if "short" in sd:
        return "Short", "sell"
    if "cover" in sd:
        return "Cover", "buy"
    if sd.startswith("sell"):
        return ("Short", "sell") if oc == "open" else ("Sell", "sell")
    if sd.startswith("buy"):
        return ("Cover", "buy") if oc == "close" else ("Buy", "buy")
    return str(o.get("side") or "?"), ""
