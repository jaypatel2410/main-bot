# -*- coding: utf-8 -*-
"""Kestrel 3.15 - the price line on each Scanner card (display only: no strategy, order or signal uses it).

Today's 1-minute candles are asked from IB ONCE per scanner stock (one request every REQ_GAP_SEC at most, in the
background, after the stock first shows up), then the line is carried on from the scanner's own live quote: a new point
each minute, the last point follows the price, VWAP grows with the volume traded since. The page gets at most
MAX_PTS points per stock, and a stock's line is sent again at most every SEND_GAP_SEC.
"""
import asyncio
import logging
import math
import time

log = logging.getLogger("lh_app")

REQ_GAP_SEC = 4.0          # IB history pacing: at most one of these requests every 4 s
MAX_PTS = 120              # points per line sent to the page
SEND_GAP_SEC = 5.0         # a stock's line goes to the page at most this often
DAY_START_MIN = 4 * 60     # 04:00 ET
RTH_START_MIN = 9 * 60 + 30
RETRY_SEC = 120            # a failed request is tried again after this


class Sparks:
    def __init__(self, be, app):
        self.be, self.app = be, app
        self.rows = {}         # sym -> {"m": [], "c": [], "w": [], "pv", "vv", "hod", "day", "vref", "sent", "key"}
        self.q = []
        self.failed = {}
        self.task = None
        self.last_req = 0.0

    # ---- asked by the scanner loop (IB event-loop thread) ----
    def want(self, sym, contract):
        if contract is None or sym in self.rows or sym in self.q:
            return
        if time.monotonic() - self.failed.get(sym, -1e9) < RETRY_SEC:
            return
        self.q.append((sym, contract))
        if self.task is None or self.task.done():
            self.task = self.be.loop.create_task(self._run())

    def forget(self, keep):
        for s in [s for s in self.rows if s not in keep]:
            self.rows.pop(s, None)
        self.q = [x for x in self.q if x[0] in keep]

    async def _run(self):
        while self.q and not self.be.closing:
            wait = REQ_GAP_SEC - (time.monotonic() - self.last_req)
            if wait > 0:
                await asyncio.sleep(wait)
            if not self.q:
                break
            sym, contract = self.q.pop(0)
            if sym in self.rows:
                continue
            self.last_req = time.monotonic()
            try:
                await self._fetch(sym, contract)
            except Exception as exc:
                self.failed[sym] = time.monotonic()
                log.info("scanner card line %s: %r", sym, exc)

    async def _fetch(self, sym, contract):
        ib = self.be.ib
        if ib is None or not ib.isConnected():
            raise RuntimeError("IB not connected")
        bars = await asyncio.wait_for(ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr="1 D", barSizeSetting="1 min", whatToShow="TRADES", useRTH=False,
            formatDate=2), 45)
        app = self.app
        today = app.ctime(self.be.now_et()) // 86400
        st = {"m": [], "c": [], "w": [], "pv": 0.0, "vv": 0.0, "hod": None, "day": today, "vref": None, "sent": 0.0,
              "key": None}
        for b in bars or []:
            t = app.ctime(b.date)
            if t // 86400 != today:
                continue
            m = (t % 86400) // 60
            if m < DAY_START_MIN:
                continue
            o, h, l, c, v = app.bar_ohlcv(b)
            if not c:
                continue
            if v and v > 0:
                st["pv"] += (h + l + c) / 3.0 * v
                st["vv"] += v
            st["hod"] = max(st["hod"] or h, h)
            st["m"].append(int(m))
            st["c"].append(float(c))
            st["w"].append(st["pv"] / st["vv"] if st["vv"] > 0 else None)
        self.rows[sym] = st

    # ---- the scanner push: carry the line on with the live quote; returns the line for the page (or None) ----
    def line(self, sym, last, vol, force=False):
        st = self.rows.get(sym)
        if st is None:
            return None
        now = self.be.now_et()
        if self.app.ctime(now) // 86400 != st["day"]:
            self.rows.pop(sym, None)                     # a new day: asked again
            return None
        m = now.hour * 60 + now.minute
        if last and m >= DAY_START_MIN:
            if vol is not None:
                if st["vref"] is not None and vol > st["vref"]:
                    st["pv"] += last * (vol - st["vref"])
                    st["vv"] += vol - st["vref"]
                st["vref"] = vol if st["vref"] is None or vol > st["vref"] else st["vref"]
            w = st["pv"] / st["vv"] if st["vv"] > 0 else None
            if st["m"] and st["m"][-1] == m:
                st["c"][-1], st["w"][-1] = float(last), w
            elif not st["m"] or m > st["m"][-1]:
                st["m"].append(m)
                st["c"].append(float(last))
                st["w"].append(w)
            st["hod"] = max(st["hod"] or last, last)
        n = len(st["c"])
        if not n:
            return None
        mono = time.monotonic()
        key = (n, round(st["c"][-1], 4))
        if not force and (key == st["key"] or mono - st["sent"] < SEND_GAP_SEC):
            return None
        st["key"], st["sent"] = key, mono
        k = max(1, math.ceil(n / MAX_PTS))
        idx = list(range(0, n, k))
        if idx[-1] != n - 1:
            idx.append(n - 1)
        hi_i = max(range(n), key=lambda i: st["c"][i])
        if hi_i not in idx:
            idx = sorted(set(idx) | {hi_i})
        m0, m1 = st["m"][0], max(st["m"][-1], st["m"][0] + 1)
        f = self.app._f
        return {"m0": m0, "m1": m1, "x": [round((st["m"][i] - m0) / (m1 - m0), 4) for i in idx],
                "p": [f(st["c"][i]) for i in idx], "w": [f(st["w"][i]) if st["w"][i] else None for i in idx],
                "hod": f(st["hod"]), "x930": round((RTH_START_MIN - m0) / (m1 - m0), 4) if m0 < RTH_START_MIN < m1 else None}
