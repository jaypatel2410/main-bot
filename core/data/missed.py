# -*- coding: utf-8 -*-
"""Kestrel 3.15 - the missed-trade log (Journal > Missed).

Every strategy signal the bot did not take is recorded with its reason, then followed on the live candles with that
strategy's own exit rules until the would-have exit happens:

    shorts (Jay-read 2, Jay-read v1.2, max squeeze)  the signal's stop; the lock (once a candle trades LOCK_AFTER_PCT
                     under the entry the stop moves to the entry -LOCK_STOP_PCT); the cover at EOD_COVER_TIME (15:55) -
                     the same rules as the alert-only trade and the backtest. Would-have P&L after a 3% locate.
    premarket long   a copy of the strategy's own engine (stop, half at the target, trail, time stop), fed the same
                     10-second candles and ticks as the real one; the 09:00 flatten sells what is left.

Sizing = the live sizing of that moment (20% of the 09:00 base; shorts max $50k, longs max $10k). A record whose stock
leaves the screen before the exit is closed at the last price seen at 16:00 ("end of day"); one still open when the app
restarts is kept as "not followed (app restarted)".
"""
import calendar
import copy
import re
import threading
import time
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    ET = None

LOCATE_PCT = 3.0                                    # would-have short P&L: locate cost as % of the entry value
CATS = [("Under the price minimum", re.compile(r"signal price .* under \$", re.I)),
        ("Locate over 5%", re.compile(r"(above|over) the .*cap|% \(|\d+(\.\d+)?% \((single|re-usable)", re.I)),
        ("No locate", re.compile(r"locate", re.I)),
        ("Buying power", re.compile(r"buying power|equity|size too small", re.I)),
        ("Halted at signal", re.compile(r"halt", re.I)),
        ("Max trades reached", re.compile(r"trades today|trades reached|max(imum)? trades|trades per|positions open|loss limit", re.I)),
        ("Paused", re.compile(r"paus", re.I)),
        ("Alert only", re.compile(r"alert", re.I)),
        ("Auto-trade off", re.compile(r"auto[- ]?trade", re.I))]


def category(why):
    for name, rx in CATS:
        if rx.search(why or ""):
            return name
    return "Other"


def _now_et():
    return datetime.now(ET) if ET else datetime.now()


def chart_t(real):
    """A real epoch -> chart time (ET wall clock as a UTC epoch, what the charts and the short side use)."""
    d = datetime.fromtimestamp(real, ET) if ET else datetime.fromtimestamp(real)
    return calendar.timegm(d.timetuple())


def _utc(t):
    return datetime.fromtimestamp(int(t), timezone.utc)


class Missed:
    def __init__(self, db, log=None, on_change=None):
        self.db = db
        self.log = log
        self.on_change = on_change or (lambda rec: None)
        self.lock = threading.Lock()
        self.open = []                               # followers: {"rec", "kind", ...}
        self.last_px = {}                            # sym -> last price seen (the end-of-day close)
        today = _now_et().strftime("%Y-%m-%d")
        for r in db.rows("SELECT * FROM missed WHERE state='open'"):     # followed by an earlier run: cannot go on
            r.update(state="lost", exit_why="not followed (app restarted)", updated=_now_et().strftime("%H:%M:%S"))
            if r["day"] != today:
                r["exit_why"] = "not followed (app closed)"
            db.put("missed", r)

    # ------------------------------------------------------------------ recording
    def _rec(self, sym, strat, setup, side, px, stop, qty, why, t):
        """t = chart time (ET wall clock as a UTC epoch)."""
        d = _utc(t)
        return {"id": f"{sym}-{int(t)}-{setup}", "day": d.strftime("%Y-%m-%d"), "t": int(t), "sym": sym, "strat": strat,
                "setup": setup, "side": side, "px": float(px), "stop": float(stop) if stop else None, "qty": int(max(qty, 0)),
                "reason": str(why or "")[:240], "cat": category(why), "state": "open", "exit_px": None, "exit_t": None,
                "exit_why": "", "move": None, "pnl": None, "locate": None, "updated": d.strftime("%H:%M:%S")}

    def short(self, sym, strat, setup, px, stop, qty, why, t, cfg, eod_min=955):
        """A short signal not taken. cfg: LOCK_AFTER_PCT / LOCK_STOP_PCT of that strategy; eod_min: the cover minute."""
        rec = self._rec(sym, strat, setup, "Short", px, stop, qty, why, t)
        lk = cfg.get("LOCK_STOP_PCT") if cfg else None
        f = {"rec": rec, "kind": "short", "stop": float(stop), "entry": float(px), "locked": False,
             "lock_trig": float(px) * (1 - float(cfg.get("LOCK_AFTER_PCT", 0) or 0) / 100.0) if cfg and lk is not None else None,
             "lock_stop": float(px) * (1 - float(lk) / 100.0) if lk is not None else None, "eod": eod_min,
             "from": int(t) // 60 * 60 + 60}            # candles after the signal's
        self._add(f)
        return rec

    def long(self, sym, strat, eng, sig, px, shares, why, t, flatten_s):
        """A premarket-long signal not taken: a copy of its engine holds the would-be position."""
        rec = self._rec(sym, strat, sig.get("strategy", strat), "Long", px, sig.get("stop"), shares, why, chart_t(t))
        try:                                              # (t here = the real epoch: the long engine's own clock)
            shadow = copy.deepcopy(eng)
            shadow.open_position(sig, float(px), int(shares), float(t))
        except Exception as exc:                       # cannot follow: keep the record, mark it
            rec.update(state="lost", exit_why=f"not followed ({exc.__class__.__name__})")
            self.db.put("missed", rec)
            self.on_change(rec)
            return rec
        self._add({"rec": rec, "kind": "long", "eng": shadow, "flatten": flatten_s})
        return rec

    def _add(self, f):
        with self.lock:
            if any(o["rec"]["id"] == f["rec"]["id"] for o in self.open):
                return
            self.open.append(f)
        self.db.put("missed", f["rec"])
        self.on_change(f["rec"])

    # ------------------------------------------------------------------ following
    def _done(self, f, px, why, t):
        """t = chart time."""
        rec = f["rec"]
        qty = rec["qty"]
        if rec["side"] == "Short":
            gross = (rec["px"] - px) * qty
            loc = rec["px"] * qty * LOCATE_PCT / 100.0
            rec.update(pnl=round(gross - loc, 2), locate=round(loc, 2))
        else:
            legs = [g for g in f["eng"].day.legs if g.get("entry_t") == f["eng"].day.legs[-1].get("entry_t")] if f["eng"].day.legs else []
            rec.update(pnl=round(sum(g["pnl"] for g in legs), 2) if legs else round((px - rec["px"]) * qty, 2), locate=0.0)
        rec.update(state="done", exit_px=float(px), exit_t=int(t), exit_why=why, move=round((px / rec["px"] - 1) * 100, 2),
                   updated=_utc(t).strftime("%H:%M:%S"))
        with self.lock:
            if f in self.open:
                self.open.remove(f)
        self.db.put("missed", rec)
        self.on_change(rec)

    def short_bar(self, sym, t, o, h, l, c):
        """A closed 1-minute candle of a watched stock. t = the candle's start (naive ET wall-clock datetime)."""
        ts = calendar.timegm(t.timetuple())
        self.last_px[sym] = c
        m = t.hour * 60 + t.minute if hasattr(t, "hour") else None
        for f in [x for x in self.open if x["kind"] == "short" and x["rec"]["sym"] == sym]:
            if ts < f["from"]:
                continue
            if m is not None and f["eod"] and m >= f["eod"]:
                self._done(f, o, "15:55 cover", ts)
            elif o >= f["stop"]:
                self._done(f, o, "lock stop" if f["locked"] else "stop", ts)
            elif h >= f["stop"]:
                self._done(f, f["stop"], "lock stop" if f["locked"] else "stop", ts)
            elif f["lock_trig"] is not None and not f["locked"] and l <= f["lock_trig"]:
                f["stop"], f["locked"] = f["lock_stop"], True    # from the next candle on (as the engine does)

    def long_bar(self, sym, bar):
        self.last_px[sym] = bar.c
        for f in [x for x in self.open if x["kind"] == "long" and x["rec"]["sym"] == sym]:
            eng = f["eng"]
            if self._flatten(f, bar.t, bar.c):
                continue
            try:
                evs = eng.on_bar_10s(bar)
            except Exception:
                continue
            for ev in evs:
                if ev.get("type") == "exit" and eng.day.pos is not None:
                    p = eng.day.pos
                    px = p.stop if "STOP" in ev["reason"] else bar.c
                    self._leg(f, ev["shares"], px, ev["reason"], bar.t)

    def long_price(self, sym, price, now):
        self.last_px[sym] = price
        for f in [x for x in self.open if x["kind"] == "long" and x["rec"]["sym"] == sym]:
            eng = f["eng"]
            if self._flatten(f, now, price):
                continue
            try:
                eng.on_tick_high(price)
                req = eng.exit_on_price(price, now)
            except Exception:
                continue
            if req:
                self._leg(f, req[1], price, req[0], now)

    def _leg(self, f, shares, px, reason, t):
        eng = f["eng"]
        eng.close_leg(shares, px, reason, t)
        if eng.day.pos is None:
            self._done(f, px, {"STOP OUT": "stop", "TRAILING STOP OUT": "trail", "TIME STOP (DEAD MONEY)": "time stop",
                               "PARTIAL SCALE OUT": "target"}.get(reason, reason.lower()), chart_t(t))

    def _flatten(self, f, t, px):
        d = datetime.fromtimestamp(t, ET) if ET else datetime.fromtimestamp(t)
        if d.hour * 3600 + d.minute * 60 + d.second >= f["flatten"] and f["eng"].day.pos is not None:
            self._leg(f, f["eng"].day.pos.shares, px, "09:00 flatten", t)
            return True
        return False

    def drop(self, rid):
        """The signal was taken after all (the locate search found shares): no missed trade."""
        with self.lock:
            self.open = [f for f in self.open if f["rec"]["id"] != rid]
        self.db.delete("missed", rid)

    def end_of_day(self):
        """16:00: a follower still open (its stock left the screen) is closed at the last price seen."""
        now = time.time()
        for f in list(self.open):
            px = self.last_px.get(f["rec"]["sym"])
            if px:
                if f["kind"] == "long" and f["eng"].day.pos is not None:
                    self._leg(f, f["eng"].day.pos.shares, px, "end of day", now)
                else:
                    self._done(f, px, "end of day", chart_t(now))

    # ------------------------------------------------------------------ the Journal
    def list(self, start_day, end_day=None):
        args = [start_day] + ([end_day] if end_day else [])
        return self.db.rows("SELECT * FROM missed WHERE day>=?" + (" AND day<=?" if end_day else "") + " ORDER BY day DESC, t DESC", args)

    def summary(self, day):
        rows = self.list(day, day)
        done = [r for r in rows if r["pnl"] is not None]
        return {"n": len(rows), "pnl": round(sum(r["pnl"] for r in done), 2), "wins": sum(1 for r in done if r["pnl"] > 0),
                "done": len(done)}
