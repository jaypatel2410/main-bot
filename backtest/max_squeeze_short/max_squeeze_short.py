"""
MAX SQUEEZE SHORT - Steven Dux's "max squeeze %" setup as a rule                        (strategy module, v1.0, 2026-10-22)
=====================================================================================================================

From Dux's monthly statistics reports: a stock squeezes ~50-60% above the level where the "average short seller" went
in (the last swing high it broke through); short the first red candle up there. Only closed 1-minute candles are used
(no lookahead):

  1. the stock is up MIN_UP_PCT+ on the day (high of day incl. premarket vs the prior close)
  2. the "average short" level = the last confirmed swing high (a high followed by a SWING_PCT pullback) that the high
     of day has broken through
  3. the squeeze top since that level was confirmed is SQUEEZE_PCT+ above it
  4. a RED candle closes within NEAR_TOP_PCT of the top while its high reached within half of that -> short the next open
     (signals SIGNAL_START-SIGNAL_END, at most MAX_SIGNALS_PER_DAY signals and MAX_TRADES_PER_DAY trade a stock a day)
  5. stop = the top + STOP_OVER_TOP_PCT; no lock; covered at EOD_COVER_TIME (15:55)

Fills, costs and the live API are the Jay-read short's (jay_read_short.py ShortTrade / JayReadShort): entry at the next
open -0.1%, a candle opening at/over the stop covers at its open, else a high touching it covers at the stop, +0.1% on the
cover, 3% locate.

Backtest (584 research ticker-days 2026-04-01..2026-10-05, $10,000 a trade): 16 trades, 75% win, +$36,707, PF 4.2, median
stop 28% over the entry - the same trades as the research harness (dux_patterns.squeeze, S=0.50, stop +20%). In-sample and
a small sample: see claude/dux_setups_584_days_2026-10-20.md.

ShortBook (bottom of this file) runs the Jay-read short and this one on the same stock with ONE position at a time: the
first signal wins (same candle: the Jay-read short first), and a stop-out of either ends the stock for the day for both
(BOOK_DONE_AFTER_STOP). It has the JayReadShort API, so the bot and the backtesters use it in place of a JayReadShort.
Backtest of the book (584 days, $10,000 a trade): 98 trades, 71% win, +$120,316, PF 3.2 (Jay-read v1.2 alone: 92 trades,
71% win, +$94,065; each keeping only its own after-stop rule: 102 trades, 70% win, +$111,022).
"""
__version__ = "1.0"

import math

import numpy as np

import jay_read_short as JR

# =====================================================================================================================
# SETTINGS (the backtested values)
# =====================================================================================================================
MIN_UP_PCT = 30.0                  # stock up at least this % (high of day incl. premarket vs prior close)
SWING_PCT = 10.0                   # a swing high is confirmed by a pullback of this % under it
SQUEEZE_PCT = 50.0                 # the squeeze top is at least this % above the "average short" level
NEAR_TOP_PCT = 8.0                 # the red candle closes within this % of the top (its high within half of it)
STOP_OVER_TOP_PCT = 20.0           # stop = the top x (1 + this %)

SIGNAL_START = "09:30"             # signals on candles closing from ...
SIGNAL_END = "15:00"               # ... to this time (ET)
ENTRY_START = "09:30"              # the entry candle (next open) must be in this window
LAST_ENTRY_TIME = "15:30"
MAX_SIGNALS_PER_DAY = 2            # per stock (the research: the first 2 signals of the day)
MAX_TRADES_PER_DAY = 1             # per stock
STOP_FOR_DAY_AFTER_STOP = True
REENTRY_AFTER_NEW_HIGH = False

LOCK_AFTER_PCT = 25.0              # (no lock: LOCK_STOP_PCT = None - hold the original stop, as backtested)
LOCK_STOP_PCT = None
EOD_COVER_TIME = "15:55"           # cover what is open at this candle's open (None = no EOD cover)

POSITION_USD = 10_000.0            # backtest size per trade
LOCATE_FEE_PCT = 3.0               # % of the entry value, paid win or lose
SLIPPAGE_PCT = 0.10                # per fill (entry and cover)
RTH_START = "09:30"
RTH_END = "16:00"

BOOK_DONE_AFTER_STOP = True       # ShortBook: a stop-out of EITHER short ends the stock for both today ("stop trading it
                                   # once it squeezes"); False = each short keeps only its own after-stop rule

SETUP = "squeeze"
NAME = "Max squeeze short"
CODE = "SQ"


def settings(**overrides):
    """The module settings as a dict (upper-case names), with overrides."""
    g = globals()
    cfg = {k: g[k] for k in g if k.isupper() and not k.startswith("_")}
    for k, v in overrides.items():
        if k not in cfg:
            raise KeyError(f"unknown setting {k}")
        cfg[k] = v
    return cfg


# =====================================================================================================================
# THE READER: one closed candle at a time
# =====================================================================================================================
class SqueezeReader:
    """Feeds on closed 1-min candles that had trades (volume > 0), from 04:00 ET. add_bar() returns a signal dict on the
    candle that triggers it, else None."""

    def __init__(self, prior_close, cfg=None):
        self.cfg = cfg or settings()
        c = self.cfg
        self.pc = float(prior_close)
        self.o, self.h, self.l, self.c, self.v = (JR._Grow() for _ in range(5))
        self.m, self.t, self.vw = [], [], []
        self._pv = self._vv = 0.0
        self.dollar = 0.0
        self.hod = -math.inf
        self.i0 = None
        self.swings = []                     # (k of the high, k confirmed, price)
        self._hi, self._ihi = -1.0, -1
        self.n_sig = 0
        self._zz = c["SWING_PCT"] / 100
        self._s0, self._s1 = JR._min(c["SIGNAL_START"]), JR._min(c["SIGNAL_END"])
        self._r0 = JR._min(c["RTH_START"])

    def add_bar(self, t, minute, o, h, l, c, v):
        k = len(self.o)
        for arr, x in ((self.o, o), (self.h, h), (self.l, l), (self.c, c), (self.v, v)):
            arr.append(float(x))
        self.m.append(int(minute)); self.t.append(t)
        tp = (h + l + c) / 3
        self._pv += tp * v; self._vv += v
        self.vw.append(self._pv / self._vv)
        self.dollar += tp * v
        self.hod = max(self.hod, float(h))
        if self.i0 is None and minute >= self._r0:
            self.i0 = k
        if h > self._hi:                                             # swing highs (confirmed by a SWING_PCT pullback)
            self._hi, self._ihi = float(h), k
        elif l <= self._hi * (1 - self._zz):
            self.swings.append((self._ihi, k, self._hi))
            self._hi, self._ihi = float(h), k
        return self._signal(k)

    def state(self):
        """Where the read is now: (level, k level confirmed, top, k top) of the current squeeze, or None."""
        k = len(self.o) - 1
        if k < 0:
            return None
        cand = [x for x in self.swings if x[1] < k and self.hod > x[2]]
        if not cand:
            return None
        ih, ic, lvl = cand[-1]
        seg = self.h[ic:k + 1]
        kt = ic + int(np.argmax(seg))
        return lvl, ic, float(seg.max()), kt

    def _signal(self, k):
        cf = self.cfg
        if self.n_sig >= cf["MAX_SIGNALS_PER_DAY"]:
            return None
        o, h, l, c, m = self.o, self.h, self.l, self.c, self.m
        if not (self._s0 <= m[k] <= self._s1) or c[k] >= o[k] or self.hod / self.pc - 1 < cf["MIN_UP_PCT"] / 100:
            return None
        cand = [x for x in self.swings if x[1] < k and self.hod > x[2]]
        if not cand:
            return None
        k_lvl, k_conf, lvl = cand[-1]
        seg = h[k_conf:k + 1]
        k_top = k_conf + int(np.argmax(seg)); top = float(seg.max())
        if top < lvl * (1 + cf["SQUEEZE_PCT"] / 100):
            return None
        near = cf["NEAR_TOP_PCT"] / 100
        if not (c[k] >= top * (1 - near) and h[k] >= top * (1 - near / 2)):
            return None
        self.n_sig += 1
        stop = top * (1 + cf["STOP_OVER_TOP_PCT"] / 100)
        vw = self.vw[k]
        return dict(k=k, time=self.t[k], close=c[k], up=self.hod / self.pc - 1, setup=SETUP, kind="max squeeze top",
                    squeeze=top / lvl - 1, top=top, top_time=self.t[k_top], level=lvl, level_time=self.t[k_lvl],
                    stop=stop, vwap=vw, vs_vwap=c[k] / vw - 1, dollar=self.dollar,
                    # the Jay-read signal keys (the bot / backtest reports read them): top = the high to beat
                    rth_high=top, rth_high_time=self.t[k_top], crack_low=l[k_conf], crack_low_time=self.t[k_conf],
                    crack=1 - l[k_conf] / lvl, ref=lvl, ref_time=self.t[k_lvl], low=l[k_conf], low_time=self.t[k_conf],
                    bounce_high=top, bounce_high_time=self.t[k_top], drop=1 - l[k_conf] / lvl, bounce=top / lvl - 1,
                    retrace=0.0, reclaim=0.0, hod_age_min=m[k] - m[k_top],
                    k_rh=k_top, k_crack=k_conf, k_ref=k_lvl, k_low=k_conf, k_bh=k_top)


# =====================================================================================================================
# THE STRATEGY: the Jay-read short's trade engine and live API with the squeeze reader
# =====================================================================================================================
class MaxSqueezeShort(JR.JayReadShort):
    """Same API as JayReadShort (backtest: on_bar / finish; live: SIGNAL -> entry_allowed / entry_filled / cover_filled)."""

    def __init__(self, symbol, prior_close, cfg=None, simulate_fills=True, **overrides):
        self.cfg = settings(**overrides) if cfg is None else {**cfg, **overrides}
        self.symbol, self.pc = symbol, float(prior_close)
        self.simulate = simulate_fills
        self.reader = SqueezeReader(prior_close, self.cfg)
        self.trades, self.signals = [], []
        self.pos = None
        self.pending = None
        self.awaiting = None
        self.done = False
        self._stop_rh = None
        self._busy_until = -1
        self._busy_minute = -1
        self._e0, self._e1 = JR._min(self.cfg["ENTRY_START"]), JR._min(self.cfg["LAST_ENTRY_TIME"])
        self._eod = JR._min(self.cfg["EOD_COVER_TIME"])

    def new_reader(self):
        r = SqueezeReader(self.pc, self.cfg)
        r.n_sig = self.reader.n_sig                  # a rebuilt read keeps today's signal count
        return r


# =====================================================================================================================
# THE BOOK: Jay-read + max squeeze on one stock, one position at a time
# =====================================================================================================================
class ShortBook:
    """Both shorts on one stock. One position at a time: a strategy's SIGNAL while the other one has a signal waiting, a
    position, or closed one on this very candle is skipped. Same candle: the Jay-read short goes first. The Jay-read short
    and the max squeeze short keep their own rules (trades a day, done after a stop).

    It has the JayReadShort API: on_bar / finish (backtest), warmup / entry_allowed / entry_filled / entry_cancelled /
    cover_filled (live), .pos / .awaiting / .trades / .signals / .done / .reader (the Jay-read read) / .cfg (Jay-read)."""

    def __init__(self, symbol, prior_close, jr_cfg=None, sq_cfg=None, simulate_fills=True, squeeze=True):
        self.symbol, self.pc = symbol, float(prior_close)
        self.done_after_stop = (sq_cfg or settings()).get("BOOK_DONE_AFTER_STOP", True)
        self.jr = JR.JayReadShort(symbol, prior_close, cfg=jr_cfg, simulate_fills=simulate_fills)
        self.sq = MaxSqueezeShort(symbol, prior_close, cfg=sq_cfg, simulate_fills=simulate_fills) if squeeze else None
        self.parts = [self.jr] + ([self.sq] if self.sq is not None else [])

    # ---- what the bot reads
    @property
    def reader(self):
        return self.jr.reader

    @reader.setter
    def reader(self, r):
        self.jr.reader = r

    @property
    def cfg(self):
        return self.jr.cfg

    @property
    def pos(self):
        return next((p.pos for p in self.parts if p.pos is not None), None)

    @property
    def awaiting(self):
        return next((p.awaiting for p in self.parts if p.awaiting is not None), None)

    @awaiting.setter
    def awaiting(self, sig):
        """The bot hands a signal back (an entry that filled late): it goes to the strategy of its setup."""
        if sig is None:
            for p in self.parts:
                p.awaiting = None
        else:
            self.part(sig.get("setup")).awaiting = sig

    @property
    def trades(self):
        return sorted([t for p in self.parts for t in p.trades], key=lambda t: (str(t.t0), t.k0))

    @property
    def signals(self):
        return [s for p in self.parts for s in p.signals]

    @staticmethod
    def finished(p):
        return p.done or len(p.trades) >= p.cfg["MAX_TRADES_PER_DAY"]

    @property
    def done(self):
        """Every strategy is done for the day on this stock."""
        return all(self.finished(p) for p in self.parts)

    @done.setter
    def done(self, v):
        for p in self.parts:
            p.done = bool(v)

    def part(self, setup):
        return self.sq if setup == SETUP and self.sq is not None else self.jr

    def _owner(self):
        return next((p for p in self.parts if p.pos is not None or p.awaiting is not None), None)

    # ---- the candles
    @staticmethod
    def _busy(p):
        return p.pos is not None or p.pending is not None or p.awaiting is not None

    def _sync_done(self):
        """A stop-out of one short ends the stock for the other one too (BOOK_DONE_AFTER_STOP)."""
        if not self.done_after_stop:
            return
        hit = next((p for p in self.parts if p.done and p._stop_rh is not None), None)
        if hit is not None:
            for p in self.parts:
                if not p.done:
                    p.done, p._stop_rh = True, hit._stop_rh

    def _blocks(self, q, k, minute):
        """q holds / waits on this stock, or closed a trade on this very candle (as one strategy blocks its own)."""
        if self._busy(q):
            return True
        return q._busy_until >= k if q.simulate else q._busy_minute >= minute

    def on_bar(self, t, o, h, l, c, v, minute=None):
        if not v or v <= 0:
            return []
        if minute is None:
            minute = t.hour * 60 + t.minute
        out = []
        for p in self.parts:
            k = len(p.reader.o)                        # this candle's index (every read gets the same candles)
            ev = p.on_bar(t, o, h, l, c, v, minute)
            self._sync_done()
            for e in ev:
                if e["type"] == "SIGNAL" and any(self._blocks(q, k, minute) for q in self.parts if q is not p):
                    p.pending = None
                    p.awaiting = None
                    e = dict(e, type="SKIP", reason="the other short strategy is in a trade on this stock")
                out.append(dict(e, strategy=p.cfg.get("CODE", "JR")))
        return out

    def warmup(self, candles):
        n = 0
        for p in self.parts:
            n = p.warmup(candles)
        return n

    def rebuild(self, rows):
        """IB revised a candle already read: rebuild every read from rows [(t, o, h, l, c, v)] (trades are kept)."""
        self.jr.reader = JR.JayReader(self.pc, self.jr.cfg)
        if self.sq is not None:
            self.sq.reader = self.sq.new_reader()
        for p in self.parts:
            for t, o, h, l, c, v in rows:
                p.reader.add_bar(t, t.hour * 60 + t.minute, o, h, l, c, v)

    # ---- live
    def entry_allowed(self, price, t):
        p = self._owner()
        return p.entry_allowed(price, t) if p is not None else (False, "no signal waiting")

    def entry_filled(self, price, t):
        p = next((q for q in self.parts if q.awaiting is not None), None)
        if p is None:
            raise RuntimeError("entry_filled() without a SIGNAL waiting")
        return p.entry_filled(price, t)

    def entry_cancelled(self):
        for p in self.parts:
            p.entry_cancelled()

    def cover_filled(self, fraction, price, reason, t):
        p = next((q for q in self.parts if q.pos is not None), None)
        if p is None:
            raise RuntimeError("cover_filled() without an open position")
        out = p.cover_filled(fraction, price, reason, t)
        self._sync_done()
        return out

    def finish(self):
        out = []
        for p in self.parts:
            out += p.finish()
        return sorted(out, key=lambda r: (r["date"], r["entry_time"]))
