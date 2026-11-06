# -*- coding: utf-8 -*-
"""LH Short Bot 3.15 - float (reference data only; market data stays on IB) for the top-bar chip and the scanner column.

    Alpha Vantage   company overview -> SharesFloat. Free key (ALPHAVANTAGE_API_KEY in .env), 25 calls a day: used for
                    the stock on the chart first; every answer is cached CACHE_DAYS days.
    SEC EDGAR       the company's last reported shares outstanding (dei EntityCommonStockSharesOutstanding) - no key
                    (SEC_CONTACT_EMAIL in .env, as for the news). Shown as "O/S", with its date.

Free float data can be old for small caps after an offering or a reverse split: the value always carries its age.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime

AV_URL = "https://www.alphavantage.co/query"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{:010d}/dei/EntityCommonStockSharesOutstanding.json"
CACHE_DAYS = 5
MISS_DAYS = 2                                        # nothing found: asked again after this


class Floats:
    DAILY = 25

    def __init__(self, env_get, data_dir, on_update=None, log=None):
        self.env_get = env_get
        self.path = os.path.join(data_dir, "float_cache.json")
        self.on_update = on_update or (lambda sym, v: None)
        self.log = log
        self.lock = threading.Lock()
        self.q, self.qset = [], set()
        self.wake = threading.Event()
        self.ciks, self.ciks_at = {}, 0.0
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("rows", {})
        self.data.setdefault("av", {"day": "", "n": 0})
        threading.Thread(target=self._loop, name="floats", daemon=True).start()

    # ------------------------------------------------------------------ what the app asks
    def key(self):
        return (self.env_get("ALPHAVANTAGE_API_KEY", "") or "").strip()

    def lookups_left(self):
        if not self.key():
            return None
        av = self.data["av"]
        return self.DAILY - (av["n"] if av.get("day") == str(date.today()) else 0)

    def peek(self, sym, want=True, priority=False):
        """The cached value now ({v, kind, src, asof, age} or None); want = fetch it in the background when missing / old."""
        sym = str(sym or "").upper()
        r = self.data["rows"].get(sym)
        fresh = r is not None and (time.time() - r.get("at", 0)) < (CACHE_DAYS if r.get("v") else MISS_DAYS) * 86400
        if want and not fresh:
            self._ask(sym, priority)
        if not r or not r.get("v"):
            return None
        return dict(r, age=self._age(r))

    def _age(self, r):
        try:
            d = datetime.strptime(r.get("asof") or "", "%Y-%m-%d").date()
            return (date.today() - d).days
        except ValueError:
            return int((time.time() - r.get("at", time.time())) // 86400)

    def _ask(self, sym, priority):
        with self.lock:
            if sym in self.qset:
                if priority:                             # the chart opened it: to the front, Alpha Vantage allowed
                    self.q = [(sym, True)] + [x for x in self.q if x[0] != sym]
                return
            self.qset.add(sym)
            if priority:
                self.q.insert(0, (sym, True))
            else:
                self.q.append((sym, False))
        self.wake.set()

    # ------------------------------------------------------------------ fetching
    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh)
        os.replace(tmp, self.path)

    def _get(self, url, headers=None, timeout=12):
        rq = urllib.request.Request(url, headers=headers or {"User-Agent": "LH Short Bot"})
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _av(self, sym):
        av = self.data["av"]
        if av.get("day") != str(date.today()):
            av.update(day=str(date.today()), n=0)
        av["n"] += 1
        d = self._get(f"{AV_URL}?{urllib.parse.urlencode({'function': 'OVERVIEW', 'symbol': sym, 'apikey': self.key()})}")
        if "Note" in d or "Information" in d:               # the daily / per-minute limit
            av["n"] = self.DAILY
            return None
        for k, kind in (("SharesFloat", "float"), ("SharesOutstanding", "O/S")):
            try:
                v = float(d.get(k) or 0)
            except ValueError:
                v = 0
            if v > 0:
                return {"v": v, "kind": kind, "src": "Alpha Vantage", "asof": str(date.today())}
        return None

    def _sec(self, sym):
        mail = (self.env_get("SEC_CONTACT_EMAIL", "") or "").strip()
        if "@" not in mail:
            return None
        ua = {"User-Agent": f"LH Short Bot {mail}", "Accept-Encoding": "identity"}
        if not self.ciks or time.time() - self.ciks_at > 12 * 3600:
            data = self._get(SEC_TICKERS, ua, 20)
            self.ciks = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}
            self.ciks_at = time.time()
        cik = self.ciks.get(sym) or self.ciks.get(sym.replace(".", "-"))
        if cik is None:
            return None
        d = self._get(SEC_CONCEPT.format(cik), ua)
        pts = [p for p in ((d.get("units") or {}).get("shares") or []) if p.get("val")]
        if not pts:
            return None
        p = max(pts, key=lambda x: (x.get("end") or "", x.get("filed") or ""))
        return {"v": float(p["val"]), "kind": "O/S", "src": "SEC", "asof": p.get("end") or p.get("filed") or ""}

    def _loop(self):
        while True:
            self.wake.wait(30)
            self.wake.clear()
            while True:
                with self.lock:
                    if not self.q:
                        break
                    sym, pri = self.q.pop(0)
                    self.qset.discard(sym)
                got = None
                try:                                     # Alpha Vantage for the chart's stock (and while plenty is left)
                    left = self.lookups_left()
                    if left and (pri or left > 10):
                        got = self._av(sym)
                        time.sleep(1.2)                  # the free key: 1 call a second at most
                    if got is None:
                        got = self._sec(sym)
                        time.sleep(0.15)
                except Exception as exc:
                    if self.log is not None:
                        self.log.warning("float %s: %r", sym, exc)
                row = dict(got or {"v": None}, at=time.time())
                with self.lock:
                    self.data["rows"][sym] = row
                    try:
                        self._save()
                    except OSError:
                        pass
                if got:
                    try:
                        self.on_update(sym, dict(row, age=self._age(row)))
                    except Exception:
                        pass
