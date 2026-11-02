"""
JAY-READ 2 SHORT - the first failed bounce near the top, gapper + spiker rules           (strategy module, v2.0, 2026-11-01)
=====================================================================================================================

From Jay's 241-trade review (2026-11-01). Research: claude/jay_read_2_strategy_2026-11-01.md and
claude/code/jay_read_2/jay_read_2_research.py (run_day). This file is that run_day() logic, one CLOSED 1-minute candle at a
time, with the same API as jay_read_short.JayReadShort so the bot, the ShortBook and the backtesters use it unchanged.

Which rule set: the 09:30 open vs the prior close.  >= GAP_SPLIT_PCT (30%) = GAPPER, under it = SPIKER.

  1  the stock is up MIN_UP_PCT (200%)+ (high of day incl. premarket vs the prior close), MIN_DOLLAR_VOL ($20M)+ traded
     from 04:00, fewer than MAX_HALT_JUMPS (8) regular-hours halts that reopened 5%+ away
  2  the regular-hours high is AGE_MIN..AGE_MAX (10-180) minutes old
  3  flush: the lowest low since that high is CRACK_MIN..CRACK_MAX (25-60)% under it
     SPIKER only: that low reached VWAP or went under it (FLUSH_VW = 0); a spiker that never lost VWAP squeezes back
  4  the FIRST bounce takes back R_MIN..R_MAX (40-85%) of the flush and makes no new high (at most DT_PCT = +1% over it)
  5  trigger: a red candle, or an upper wick >= WICK (50%) of its range, within FRESH (6) candles of the bounce high,
     closing within UNDER_PCT (6)% of the bounce high and V_MIN_PCT (5)%+ over VWAP
  6  short the next candle's open. Signals on candles closing SIGNAL_START..SIGNAL_END (09:35-15:00). One short per
     regular-hours high (ONE_PER_HIGH). Max MAX_TRADES_PER_DAY (2) per stock; done for the stock after a stop-out.
  7  stop = high of day (incl. premarket) + STOP_PCT (5)%. Lock: after a LOCK_AFTER_PCT (25)% fade from the entry the stop
     moves to entry +5% (LOCK_STOP_PCT = -5). Cover at EOD_COVER_TIME (15:55).

Backtest (IB vault 2026-01-02..2026-10-23, 1,183 ticker-days, $10k a trade, 3% locate, 0.1% slippage a fill):
  gappers 88 trades, 68% win, PF 2.71 (Jul-Oct frozen: 37 trades, 65%, PF 2.63)
  spikers 20 trades, 70% win, PF 1.72 (few trades - paper first)

API (same as JayReadShort):
    backtest:  s = JayRead2Short("WETO", prior_close=3.61); events = s.on_bar(t, o, h, l, c, v) for every closed candle
               from 04:00 ET; trades = s.finish()
    live bot:  s = JayRead2Short("WETO", 3.61, simulate_fills=False); s.warmup(candles); on_bar() -> SIGNAL ->
               entry_allowed() -> entry_filled() -> STOP_MOVED (lock) / COVER_ALL (EOD) -> cover_filled()
    book:      make_book(symbol, prior_close, parts) - the ShortBook of max_squeeze_short.py (one short per stock at a
               time, a stop-out of one ends the stock for all) holding Jay-read 2 and any other short strategy.
"""
__version__ = "2.0"

import math
from datetime import datetime

import numpy as np

import jay_read_short as JR                          # used unchanged: the trade (ShortTrade) and helpers

# =====================================================================================================================
# SETTINGS - everything in one place. The GAPPER and SPIKER sets are the backtested GAP2 / SPK2 values; change them only
# after re-running the research / the Backtest tab.
# =====================================================================================================================
SETTINGS = {
    "GAP_SPLIT_PCT": 30.0,         # 09:30 open vs prior close: >= this % = GAPPER rules, under = SPIKER rules

    "GAPPER": {                    # GAP2
        "MIN_UP_PCT": 200.0,       # high of day (incl. premarket) vs prior close, %
        "MIN_DOLLAR_VOL": 20e6,    # $ traded (from 04:00) before the signal
        "AGE_MIN": 10,             # minutes since the regular-hours high: at least ...
        "AGE_MAX": 180,            # ... and at most
        "CRACK_MIN": 25.0,         # flush: lowest low since the high vs the high, % (at least ...)
        "CRACK_MAX": 60.0,         # ... at most
        "FLUSH_VW": None,          # the flush low within this % over VWAP (None = no condition, 0 = at / under VWAP)
        "R_MIN": 0.40,             # the bounce takes back at least this share of the flush ...
        "R_MAX": 0.85,             # ... and at most this share
        "DT_PCT": 1.0,             # bounce high at most this % over the regular-hours high
        "FRESH": 6,                # trigger candle within this many candles of the bounce high
        "UNDER_PCT": 6.0,          # trigger close within this % under the bounce high
        "WICK": 0.5,               # trigger = red candle, or upper wick >= this share of the candle's range
        "V_MIN_PCT": 5.0,          # trigger close at least this % over VWAP
        "SIGNAL_START": "09:35",   # signals on candles closing from ...
        "SIGNAL_END": "15:00",     # ... to (inclusive)
        "STOP": "hod",             # "hod" = high of day incl. premarket, "rh" = regular-hours high, "bh" = bounce high
        "STOP_PCT": 5.0,           # stop = that high + this %
        "MAX_STOP_PCT": None,      # skip the entry when the stop is more than this % over it (None = no limit)
    },
    "SPIKER": {                    # SPK2 - the same, except the flush must reach VWAP
        "MIN_UP_PCT": 200.0,
        "MIN_DOLLAR_VOL": 20e6,
        "AGE_MIN": 10,
        "AGE_MAX": 180,
        "CRACK_MIN": 25.0,
        "CRACK_MAX": 60.0,
        "FLUSH_VW": 0.0,
        "R_MIN": 0.40,
        "R_MAX": 0.85,
        "DT_PCT": 1.0,
        "FRESH": 6,
        "UNDER_PCT": 6.0,
        "WICK": 0.5,
        "V_MIN_PCT": 5.0,
        "SIGNAL_START": "09:35",
        "SIGNAL_END": "15:00",
        "STOP": "hod",
        "STOP_PCT": 5.0,
        "MAX_STOP_PCT": None,
    },

    # the trade - same for both
    "ONE_PER_HIGH": True,          # one short per regular-hours high (no second / third bounce of the same high)
    "MAX_TRADES_PER_DAY": 2,       # per stock per day
    "STOP_FOR_DAY_AFTER_STOP": True,  # done for the stock after a stop-out (a lock exit or EOD is not a stop-out)
    "MAX_HALT_JUMPS": 8,           # skip the stock once it has this many regular-hours halts that reopened 5%+ away
    "HALT_GAP_MIN": 5,             # minutes between candles that count as a halt
    "LOCK_AFTER_PCT": 25.0,        # once a candle trades this % under the entry ...
    "LOCK_STOP_PCT": -5.0,         # ... the stop moves to this % under the entry (negative = over it: -5 = entry +5%)
    "EOD_COVER_TIME": "15:55",     # cover what is open at this candle's open
    "LAST_ENTRY_TIME": "15:30",    # live: an entry order still unfilled is given up after this time
    "LOCATE_FEE_PCT": 3.0,         # backtest: % of the entry value, paid win or lose
    "SLIPPAGE_PCT": 0.10,          # backtest: per fill (entry and cover)
    "POSITION_USD": 10_000.0,      # backtest: size per trade (the Backtest tab sizes like the live bot)
}

CODE = "JR2"
SETUP_GAP, SETUP_SPK = "jr2_gap", "jr2_spk"
SETUP_NAMES = {SETUP_GAP: "JR2 gapper", SETUP_SPK: "JR2 spiker"}
SETUP_CODES = {SETUP_GAP: "JR2_G", SETUP_SPK: "JR2_S"}
RTH_START, RTH_END, DATA_START = 570, 960, 240        # 09:30, 16:00, 04:00 (minutes after midnight ET)

# Flat names the bot's screens read (the GAPPER values; both sets share them today)
_G = SETTINGS["GAPPER"]
MIN_UP_PCT = _G["MIN_UP_PCT"]
MIN_DOLLAR_VOL = _G["MIN_DOLLAR_VOL"]
HOD_MIN_AGE_MIN = _G["AGE_MIN"]
MIN_CRACK_PCT = _G["CRACK_MIN"]
SIGNAL_START, SIGNAL_END = _G["SIGNAL_START"], _G["SIGNAL_END"]
HOD_STOP_PCT = _G["STOP_PCT"]
MAX_HALT_JUMPS = SETTINGS["MAX_HALT_JUMPS"]
MAX_TRADES_PER_DAY = SETTINGS["MAX_TRADES_PER_DAY"]
LOCK_AFTER_PCT = SETTINGS["LOCK_AFTER_PCT"]
LOCK_STOP_PCT = SETTINGS["LOCK_STOP_PCT"]
EOD_COVER_TIME = SETTINGS["EOD_COVER_TIME"]
LAST_ENTRY_TIME = SETTINGS["LAST_ENTRY_TIME"]
LOCATE_FEE_PCT = SETTINGS["LOCATE_FEE_PCT"]
SLIPPAGE_PCT = SETTINGS["SLIPPAGE_PCT"]
lock_text = JR.lock_text
_min = JR._min


def settings(**overrides):
    """A flat copy of SETTINGS for one strategy object (GAPPER / SPIKER stay nested), with overrides, e.g.
    settings(LOCATE_FEE_PCT=3.0) or settings(GAPPER={**SETTINGS['GAPPER'], 'STOP_PCT': 8}). It also carries the names
    jay_read_short.ShortTrade and the bot read (CODE, EOD_COVER_TIME, ...)."""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in SETTINGS.items()}
    cfg.update(CODE=CODE, MIN_UP_PCT=MIN_UP_PCT, MIN_DOLLAR_VOL=MIN_DOLLAR_VOL, HOD_MIN_AGE_MIN=HOD_MIN_AGE_MIN,
               MIN_CRACK_PCT=MIN_CRACK_PCT, SIGNAL_START=SIGNAL_START, SIGNAL_END=SIGNAL_END, HOD_STOP_PCT=HOD_STOP_PCT)
    for k, v in overrides.items():
        if k not in cfg:
            raise KeyError(f"unknown setting {k}")
        cfg[k] = dict(v) if isinstance(v, dict) else v
    return cfg


class _Grow(JR._Grow):
    pass


# =====================================================================================================================
# THE READER - run_day() step 3 ("read at the close"), one closed candle at a time
# =====================================================================================================================
class JR2Reader:
    """Closed 1-min candles with trades (volume > 0) from 04:00 to 16:00 ET. Keeps the day's arrays, VWAP, $ traded, high
    of day, the regular-hours high and the halt count. signal(k, used) evaluates the rules on candle k."""

    def __init__(self, prior_close, cfg=None):
        self.cfg = cfg or settings()
        self.pc = float(prior_close)
        self.o, self.h, self.l, self.c, self.v = (_Grow() for _ in range(5))
        self.m, self.t, self.vw = [], [], []
        self._hod = []                       # high of day (incl. premarket) after each candle
        self._pv = self._vv = 0.0
        self.dollar = 0.0
        self.hod = -math.inf
        self.halt_jumps = 0
        self.i0 = None                       # first regular-hours candle
        self.rh, self.k_rh = -math.inf, -1   # regular-hours high
        self.gap = None                      # 09:30 open vs prior close, %
        self.P = None                        # the rule set of the day (GAPPER / SPIKER), fixed at the first RTH candle
        self.kind = ""

    def add_bar(self, t, minute, o, h, l, c, v):
        """Append one candle (the bars the research reads: 04:00-16:00, volume > 0). Returns its index or None."""
        minute = int(minute)
        if not v or v <= 0 or minute < DATA_START or minute >= RTH_END:
            return None
        k = len(self.o)
        for arr, x in ((self.o, o), (self.h, h), (self.l, l), (self.c, c), (self.v, v)):
            arr.append(float(x))
        self.m.append(minute); self.t.append(t)
        tp = (float(h) + float(l) + float(c)) / 3
        self._pv += tp * float(v); self._vv += float(v)
        self.vw.append(self._pv / self._vv)
        self.dollar += tp * float(v)
        self.hod = max(self.hod, float(h))
        self._hod.append(self.hod)
        if self.i0 is None and minute >= RTH_START:
            self.i0 = k
            self.gap = (float(o) / self.pc - 1) * 100 if self.pc else 0.0
            gapper = self.gap >= self.cfg["GAP_SPLIT_PCT"]
            self.P = self.cfg["GAPPER"] if gapper else self.cfg["SPIKER"]
            self.kind = "gapper" if gapper else "spiker"
        if self.i0 is not None and k >= self.i0:
            if k > self.i0 and minute - self.m[k - 1] >= self.cfg["HALT_GAP_MIN"] and abs(o / self.c[k - 1] - 1) >= 0.05:
                self.halt_jumps += 1
            if h > self.rh:
                self.rh, self.k_rh = float(h), k
        return k

    # ---- the rules (run_day step 3, after the gate)
    def _base(self, k):
        """Rules 1-3 on candle k: (P, age, klo, L, crack) or None."""
        P, cf = self.P, self.cfg
        if P is None or self.i0 is None or k < self.i0 + 2:
            return None
        if self._hod[k] / self.pc - 1 < P["MIN_UP_PCT"] / 100 or self._dollar_at(k) < P["MIN_DOLLAR_VOL"]:
            return None
        if cf["MAX_HALT_JUMPS"] is not None and self._halts_at(k) >= cf["MAX_HALT_JUMPS"]:
            return None
        rh, krh = self._rh_at(k)
        age = self.m[k] - self.m[krh]
        if age < P["AGE_MIN"] or age > P["AGE_MAX"] or krh >= k - 1:
            return None
        l = self.l
        klo = krh + int(np.argmin(l[krh:k + 1]))
        L = l[klo]
        crack = 1 - L / rh
        if crack < P["CRACK_MIN"] / 100 or crack > P["CRACK_MAX"] / 100 or klo >= k:
            return None
        if P["FLUSH_VW"] is not None and L > self.vw[klo] * (1 + P["FLUSH_VW"] / 100):
            return None
        return P, rh, krh, age, klo, L, crack

    # the reader is fed candle by candle and signal() is called on the newest one, so "at k" = now
    def _dollar_at(self, k):
        return self.dollar

    def _halts_at(self, k):
        return self.halt_jumps

    def _rh_at(self, k):
        return self.rh, self.k_rh

    def _context(self, k):
        """For the bot's status line / pre-locate: (RH, k_rh, LO, k_lo) once rules 1-3 hold (momentum broke), else None."""
        try:
            b = self._base(k)
        except Exception:
            return None
        if b is None:
            return None
        P, rh, krh, age, klo, L, crack = b
        return rh, krh, L, klo

    def signal(self, k, used):
        """Rules 1-5 on the newest candle k. used = the strategy's {(k_rh, k_low)} already signalled. Returns the signal
        dict (not yet marked used) or None."""
        P = self.P
        if P is None or not (_min(P["SIGNAL_START"]) <= self.m[k] <= _min(P["SIGNAL_END"])):
            return None
        b = self._base(k)
        if b is None:
            return None
        P, rh, krh, age, klo, L, crack = b
        h, o, c, vw = self.h, self.o, self.c, self.vw
        kbh = klo + 1 + int(np.argmax(h[klo + 1:k + 1]))
        BH = h[kbh]
        r = (BH - L) / (rh - L)
        if r < P["R_MIN"] or r > P["R_MAX"] or BH > rh * (1 + P["DT_PCT"] / 100):
            return None
        if k - kbh > P["FRESH"] or (krh, klo) in used or (self.cfg["ONE_PER_HIGH"] and any(u[0] == krh for u in used)):
            return None
        rng = h[k] - self.l[k]
        if not (c[k] < o[k] or (rng > 0 and h[k] - c[k] >= P["WICK"] * rng)):
            return None
        if c[k] < BH * (1 - P["UNDER_PCT"] / 100) or c[k] < vw[k] * (1 + P["V_MIN_PCT"] / 100):
            return None
        hod = self._hod[k]
        if P["STOP"] == "rh":
            stop = rh * (1 + P["STOP_PCT"] / 100)
        elif P["STOP"] == "hod":
            stop = hod * (1 + P["STOP_PCT"] / 100)
        else:
            stop = BH * (1 + P["STOP_PCT"] / 100)
        setup = SETUP_GAP if self.kind == "gapper" else SETUP_SPK
        t = self.t
        return dict(k=k, time=t[k], close=c[k], setup=setup, kind=f"{self.kind} (open {self.gap:+.0f}%)",
                    up=hod / self.pc - 1, gap=self.gap, rth_high=rh, rth_high_time=t[krh], hod=hod,
                    crack_low=L, crack_low_time=t[klo], crack=crack, ref=rh, ref_time=t[krh], low=L, low_time=t[klo],
                    bounce_high=BH, bounce_high_time=t[kbh], drop=crack, bounce=BH / L - 1, retrace=r,
                    reclaim=(c[k] - L) / (rh - L), vwap=vw[k], vs_vwap=c[k] / vw[k] - 1, dollar=self.dollar,
                    hod_age_min=int(age), k_rh=krh, k_crack=klo, k_ref=krh, k_low=klo, k_bh=kbh, stop=stop,
                    stop_basis=P["STOP"], stop_pct=P["STOP_PCT"], max_stop_pct=P["MAX_STOP_PCT"])


# =====================================================================================================================
# THE TRADE - jay_read_short.ShortTrade (same fills, lock and EOD as the research), with Jay-read 2's summary
# =====================================================================================================================
class JR2Trade(JR.ShortTrade):
    def summary(self, symbol, day):
        s = self.signal
        hm = JR._hm
        return dict(ticker=symbol, date=day, strategy=CODE, setup=s["setup"], kind=s["kind"], gap=s["gap"],
                    signal_time=hm(s["time"]), entry_time=hm(self.t0), entry=self.entry, stop=self.stop0,
                    stop_pct=self.stop0 / self.entry - 1,
                    exit_time=hm(self.t_end) if self.t_end is not None else "", exit_price=self.legs[-1][1] if self.legs else None,
                    exit_reason=self.reason, lock_time=hm(self.lock_time) if self.lock_time is not None else "",
                    ret=self.ret, pnl=self.ret * self.cfg["POSITION_USD"], mfe=1 - self.lo / self.entry,
                    mae=self.hi / self.entry - 1, up=s["up"], rth_high=s["rth_high"], rth_high_time=hm(s["rth_high_time"]),
                    crack_low=s["crack_low"], crack=s["crack"], bounce_high=s["bounce_high"],
                    bounce_high_time=hm(s["bounce_high_time"]), retrace=s["retrace"], vs_vwap=s["vs_vwap"],
                    hod_age_min=s["hod_age_min"], dollar_vol=s["dollar"], k_signal=s["k"], k_entry=self.k0, k_exit=self.k_end)


# =====================================================================================================================
# THE STRATEGY - one object per symbol per day (run_day steps 1, 2, 3 in that order on every candle)
# =====================================================================================================================
class JayRead2Short:
    """Same API as jay_read_short.JayReadShort (see that class): on_bar / finish (backtest), warmup / entry_allowed /
    entry_filled / entry_cancelled / cover_filled (live); .pos .pending .awaiting .trades .signals .done .reader .cfg."""

    def __init__(self, symbol, prior_close, cfg=None, simulate_fills=True, **overrides):
        self.cfg = settings(**overrides) if cfg is None else {**cfg, **overrides}
        self.symbol, self.pc = symbol, float(prior_close)
        self.simulate = simulate_fills
        self.reader = JR2Reader(prior_close, self.cfg)
        self.trades, self.signals = [], []
        self.pos = None
        self.pending = None
        self.awaiting = None
        self.done = False
        self.used = set()                    # (k_rh, k_low) signalled today (kept when the reader is rebuilt)
        self._stop_rh = None
        self._busy_until = -1                # the ShortBook reads these two (another strategy's blocking)
        self._busy_minute = -1
        self._eod = _min(self.cfg["EOD_COVER_TIME"])

    def new_reader(self):
        return JR2Reader(self.pc, self.cfg)

    # ---- gate: run_day's "pos / pend / done / max trades" check before the read
    def _free(self):
        return (self.pos is None and self.pending is None and self.awaiting is None and not self.done
                and len(self.trades) < self.cfg["MAX_TRADES_PER_DAY"])

    def _read(self, k):
        if k is None or not self._free():
            return None
        sig = self.reader.signal(k, self.used)
        if sig is not None:
            self.used.add((sig["k_rh"], sig["k_low"]))
            self.signals.append(sig)
        return sig

    def on_bar(self, t, o, h, l, c, v, minute=None):
        if not v or v <= 0:
            return []
        if minute is None:
            minute = t.hour * 60 + t.minute
        if minute < DATA_START or minute >= RTH_END:
            return []
        if not self.simulate:
            return self._on_bar_live(t, o, h, l, c, v, minute)
        ev = []
        k = len(self.reader.o)
        if self.pending is not None:                                 # 1 the entry fills at this candle's open
            s, self.pending = self.pending, None
            e = o * (1 - self.cfg["SLIPPAGE_PCT"] / 100)
            ms = s.get("max_stop_pct")
            if e >= s["stop"]:
                ev.append(dict(type="SKIP", time=t, reason="opened at/over the stop", signal=s))
            elif self._eod is not None and minute >= self._eod:
                ev.append(dict(type="SKIP", time=t, reason="entry candle at/after the EOD cover", signal=s))
            elif ms is not None and s["stop"] / e - 1 > ms / 100:
                ev.append(dict(type="SKIP", time=t, reason=f"stop more than {ms:g}% away", signal=s))
            else:
                self.pos = JR2Trade(s, k, t, e, s["stop"], self.cfg)
                self.trades.append(self.pos)
                ev.append(dict(type="SHORT", time=t, price=e, stop=s["stop"], signal=s))
        if self.pos is not None:                                     # 2 manage the open trade with this candle
            ev += self.pos.on_bar(k, t, minute, o, h, l, c)
            if self.pos.closed:
                self._busy_until = k
                if self.cfg["STOP_FOR_DAY_AFTER_STOP"] and self.pos.reason == "STOP":
                    self.done, self._stop_rh = True, self.pos.signal["rth_high"]
                self.pos = None
        k2 = self.reader.add_bar(t, minute, o, h, l, c, v)           # 3 read the chart at the close
        sig = self._read(k2)
        if sig is not None:
            self.pending = sig
            ev.append(dict(type="SIGNAL", time=t, close=c, stop=sig["stop"], signal=sig))
        return ev

    def _on_bar_live(self, t, o, h, l, c, v, minute):
        ev = []
        p = self.pos
        if p is not None:
            if self._eod is not None and minute >= self._eod - 1:     # the 15:54 candle closed: cover at 15:55
                ev.append(dict(type="COVER_ALL", time=t, reason="EOD", fraction=p.open_w))
            else:
                p.hi, p.lo = max(p.hi, h), min(p.lo, l)
                ev += p.check_lock(l, t)                             # the bot replaces its stop order
        k = self.reader.add_bar(t, minute, o, h, l, c, v)
        sig = self._read(k)
        if sig is not None:
            self.awaiting = sig
            ev.append(dict(type="SIGNAL", time=t, close=c, stop=sig["stop"], signal=sig))
        return ev

    def warmup(self, candles):
        """Symbol added after 04:00 / app restarted: read the day so far without trading. A first bounce that already
        signalled before counts as used (one short per high)."""
        n = 0
        for t, o, h, l, c, v in candles:
            k = self.reader.add_bar(t, t.hour * 60 + t.minute, o, h, l, c, v)
            if k is None:
                continue
            n += 1
            sig = self.reader.signal(k, self.used)
            if sig is not None:
                self.used.add((sig["k_rh"], sig["k_low"]))
        return n

    def entry_allowed(self, price, t):
        s = self.awaiting
        if s is None:
            return False, "no signal waiting"
        if self._eod is not None and t.hour * 60 + t.minute >= self._eod:
            return False, "at/after the EOD cover time"
        if price >= s["stop"]:
            return False, "price at/over the stop"
        ms = s.get("max_stop_pct")
        if ms is not None and s["stop"] / price - 1 > ms / 100:
            return False, f"stop more than {ms:g}% away"
        return True, ""

    def entry_filled(self, price, t):
        s, self.awaiting = self.awaiting, None
        if s is None:
            raise RuntimeError("entry_filled() without a SIGNAL waiting")
        self.pos = JR2Trade(s, len(self.reader.o), t, float(price), s["stop"], self.cfg)
        self.trades.append(self.pos)
        return dict(stop=s["stop"], orders=[dict(type="STOP", side="BUY_TO_COVER", fraction=1.0, price=s["stop"])],
                    lock_trigger=self.pos.lock_trigger, lock_stop=self.pos.lock_stop,
                    warning="filled at/over the stop: cover now" if price >= s["stop"] else "")

    def entry_cancelled(self):
        self.awaiting = None

    def cover_filled(self, fraction, price, reason, t):
        p = self.pos
        if p is None:
            raise RuntimeError("cover_filled() without an open position")
        if reason in ("STOP", "LOCK"):
            reason = "LOCK" if p.locked else "STOP"
        out = [p._cover(min(fraction, p.open_w), float(price), reason, len(self.reader.o), t)]
        if p.closed:
            self._busy_minute = t.hour * 60 + t.minute
            if self.cfg["STOP_FOR_DAY_AFTER_STOP"] and reason == "STOP":
                self.done, self._stop_rh = True, p.signal["rth_high"]
            self.pos = None
        return out

    def finish(self):
        """End of the data: a trade still open is covered at the last close (the research's EOD)."""
        if self.pos is not None and not self.pos.closed:
            k = len(self.reader.o) - 1
            self.pos.force_close(k, self.reader.t[k], self.reader.c[k], "EOD")
            self.pos = None
        return [tr.summary(self.symbol, JR._day(tr.t0)) for tr in self.trades if tr.closed]


# =====================================================================================================================
# THE BOOK - the existing ShortBook (max_squeeze_short.py), holding any short strategies of one stock
# =====================================================================================================================
_BOOK_CLS = None


def _book_cls():
    global _BOOK_CLS
    if _BOOK_CLS is None:
        import max_squeeze_short as SQ

        class StrategyBook(SQ.ShortBook):
            """ShortBook with a free list of parts (Jay-read 2, Jay-read v1.2, max squeeze). One position per stock, a
            stop-out of one ends the stock for all, the first part goes first on the same candle - ShortBook's own code."""

            def __init__(self, symbol, prior_close, parts, done_after_stop=True):
                self.symbol, self.pc = symbol, float(prior_close)
                self.done_after_stop = done_after_stop
                self.parts = list(parts)
                self.jr = self.parts[0]                  # the reader / cfg the bot shows
                self.jr2 = next((p for p in self.parts if isinstance(p, JayRead2Short)), None)
                self.jr1 = next((p for p in self.parts if type(p).__name__ == "JayReadShort"), None)
                self.sq = next((p for p in self.parts if p.cfg.get("CODE") == "SQ"), None)

            def part(self, setup):
                if str(setup or "").startswith("jr2") and self.jr2 is not None:
                    return self.jr2
                if setup == "squeeze" and self.sq is not None:
                    return self.sq
                return self.jr1 or self.jr

            def rebuild(self, rows):
                for p in self.parts:
                    p.reader = p.new_reader() if hasattr(p, "new_reader") else JR.JayReader(p.pc, p.cfg)
                    for t, o, h, l, c, v in rows:
                        p.reader.add_bar(t, t.hour * 60 + t.minute, o, h, l, c, v)

        _BOOK_CLS = StrategyBook
    return _BOOK_CLS


def make_book(symbol, prior_close, parts):
    """parts = strategy objects for this stock (JayRead2Short first). One part = that strategy alone (same thing)."""
    return _book_cls()(symbol, prior_close, parts)
