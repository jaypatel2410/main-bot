# -*- coding: utf-8 -*-
"""Kestrel - Time & Sales for the chart that is open (display only: no strategy, order or signal uses it).

The prints come from the stock's tick-by-tick feed when it has a slot (core/data/tickfeed.py - the SAME feed the bot
reads; Time & Sales never asks IB for a second one). The open chart is the last in line for a slot: watchlist stocks
first, then the chart. Without a slot the panel shows IB's normal trade ticks (summarised) until a slot frees up.

Screen speed: from 09:00 ET every print is sent as it arrives (the window is redrawn every ~30 ms with all prints since
the last draw); before 09:00 the panel is drawn 4 times a second so the premarket long keeps the PC's time.
"""
import datetime as _dt
import json
import threading
import time

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    _ET = None

FAST_FROM_S = 9 * 3600                              # every print from 09:00 ET
SLOW_EVERY = 0.25                                   # before that: 4 draws a second
MAX_PENDING = 5000                                  # a burst bigger than this between two draws keeps the newest


class Tape:
    def __init__(self, log=None):
        self.log = log or (lambda *a, **k: None)
        self.lock = threading.Lock()
        self.on = False                  # the panel is open
        self.sym = ""
        self.mode = ""                   # "live" (every print) / "q" (4 a second) / "sum" (IB summarised)
        self.src = None                  # the ticker the prints come from
        self.quote = None                # the chart's ticker (bid / ask for the colours)
        self.mult = 1.0                  # summarised sizes may come in lots of 100
        self.pend = []
        self.reset_msg = None
        self.last_drain = 0.0
        self.last_key = None

    # ---- the panel (any thread) ----
    def set_on(self, on):
        self.on = bool(on)
        if not self.on:
            with self.lock:
                self.pend = []

    def fast(self):
        return self.on and self.mode == "live"

    # ---- once a second from the bot loop (IB thread), after the tick-by-tick slots were decided ----
    def refresh(self, be, slots):
        st = getattr(be, "state", None)
        sym = st.sym if (self.on and st is not None and getattr(st, "subscribed", False)) else ""
        src, mode = None, ""
        if sym:
            sub = None
            for key in (("S", sym), ("L", sym)):
                if slots is not None and key in slots.subs:
                    sub = slots.subs[key]
                    break
            if sub is not None:
                src = sub[1]
                n = be.now_et()
                mode = "live" if n.hour * 3600 + n.minute * 60 >= FAST_FROM_S else "q"
            else:
                src, mode = st.ticker, "sum"
                try:
                    self.mult = float(be._vol_mult() or 1.0)
                except Exception:
                    self.mult = 1.0
        self.quote = getattr(st, "ticker", None) if sym else None
        key = (sym, id(src) if src is not None else 0, mode)
        if key == self.last_key:
            return
        self.last_key = key
        if src is not self.src:
            self._hook(src)
        self.sym, self.mode = sym, mode
        with self.lock:
            self.pend = []
            self.reset_msg = {"sym": sym, "mode": mode}

    def _hook(self, src):
        if self.src is not None:
            try:
                self.src.updateEvent -= self._on_update
            except Exception:
                pass
        self.src = src
        if src is not None:
            try:
                src.updateEvent += self._on_update
            except Exception:
                self.src = None

    # ---- every IB batch of the source ticker (IB thread) ----
    def _on_update(self, tk):
        if not self.on or tk is not self.src:
            return
        try:
            q = self.quote if self.quote is not None else tk
            bid = _num(getattr(tk, "bid", None)) or _num(getattr(q, "bid", None))
            ask = _num(getattr(tk, "ask", None)) or _num(getattr(q, "ask", None))
            out = []
            if self.mode in ("live", "q"):
                for t in (getattr(tk, "tickByTicks", None) or ()):
                    px = _num(getattr(t, "price", None))
                    sz = _num(getattr(t, "size", None))
                    if not px or not sz:
                        continue
                    out.append((_tod(getattr(t, "time", None)), px, sz, _side(px, bid, ask), _ex(getattr(t, "exchange", ""))))
            else:
                for t in (getattr(tk, "ticks", None) or ()):
                    if getattr(t, "tickType", None) not in (4, 68):
                        continue
                    px = _num(getattr(t, "price", None))
                    sz = _num(getattr(t, "size", None)) or _num(getattr(tk, "lastSize", None))
                    if not px or not sz:
                        continue
                    out.append((_tod(getattr(t, "time", None)), px, sz * self.mult, _side(px, bid, ask), ""))
            if out:
                with self.lock:
                    self.pend.extend(out)
                    if len(self.pend) > MAX_PENDING:
                        self.pend = self.pend[-MAX_PENDING:]
        except Exception:
            self.log("time and sales: print not read", "warn")

    # ---- the UI bridge thread, every draw ----
    def drain_js(self):
        if not self.on:
            return ""
        now = time.monotonic()
        with self.lock:
            reset, self.reset_msg = self.reset_msg, None
            if self.mode != "live" and now - self.last_drain < SLOW_EVERY and reset is None:
                return ""
            pend, self.pend = self.pend, []
        self.last_drain = now
        js = ""
        if reset is not None:
            js += f"App.tsReset({json.dumps(reset)});"
        if pend:
            rows = [[round(t, 3), p, int(s), sd, ex] for t, p, s, sd, ex in pend]
            js += f"App.tsPush({json.dumps(rows, separators=(',', ':'))});"
        return js


_EX = {"NASDAQ": "Q", "ISLAND": "Q", "ARCA": "P", "NYSE": "N", "BATS": "Z", "BYX": "Y", "EDGX": "K", "EDGEA": "J",
       "IEX": "V", "FINRA": "D", "ADF": "D", "DARK": "D", "AMEX": "A", "MEMX": "U", "PEARL": "H", "BEX": "B", "PSX": "X",
       "CHX": "M", "LTSE": "L", "NYSENAT": "C", "IBKRATS": "D"}


def _ex(name):
    """The exchange as its one-letter tape code (Q Nasdaq, P Arca, K EDGX, Z BATS, D off-exchange ...)."""
    s = str(name or "").upper().strip()
    return _EX.get(s, s[:1])


def _num(v):
    try:
        x = float(v)
        return x if x == x and x > 0 else None
    except (TypeError, ValueError):
        return None


def _side(px, bid, ask):
    if ask and px >= ask - 1e-9:
        return 1
    if bid and px <= bid + 1e-9:
        return -1
    return 0


def _tod(t):
    """ET seconds of the day (with milliseconds)."""
    try:
        if isinstance(t, _dt.datetime):
            if t.tzinfo is None:
                t = t.replace(tzinfo=_dt.timezone.utc)
            e = t.astimezone(_ET) if _ET is not None else t
            return e.hour * 3600 + e.minute * 60 + e.second + e.microsecond / 1e6
    except Exception:
        pass
    e = _dt.datetime.now(_ET) if _ET is not None else _dt.datetime.now()
    return e.hour * 3600 + e.minute * 60 + e.second + e.microsecond / 1e6
