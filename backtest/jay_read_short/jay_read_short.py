"""
JAY-READ SHORT - the backside read from Jay's notes on the 151 combined-bot trades       (strategy module, v1.2, 2026-10-22)
=====================================================================================================================

Built from Jay's trade-by-trade review (2026-10-15), not from the three parked patterns (bounce-zone, vacuum, backside).
Only closed 1-minute candles are used (no lookahead). Every rule is one of his notes:

  Jay's note                                                  the rule
  "not a trade, still front side / still going up"            the regular-hours high is HOD_MIN_AGE_MIN+ minutes old
  "momentum broken: it cracked / faded 20-30%"                the price has dropped MIN_CRACK_PCT+ from the regular-hours high
  "it cracked to VWAP" / "holding strong, not even fading"    that crack came within CRACK_NEAR_VWAP_PCT of VWAP (or under it)
  "short the bounce at the overhead high / lower high"        two entries, one position per stock:
                                                              A ROLLOVER - the bounce comes back RETRACE_MIN+ of the drop
                                                              under the nearest overhead high and rolls over: the first red
                                                              candle within FRESH_TOP_MIN minutes of the bounce high, still
                                                              within MAX_UNDER_BOUNCE_HIGH_PCT of it
                                                              B OVERHEAD HIGH (v1.1, from the 'it would be a trade at X'
                                                              notes) - the bounce comes up INTO a lower high the stock
                                                              already failed at (LEVEL_* settings) and the candle that
                                                              touches it closes under it, red or with its top half rejected
  "it took support and squeezed / stepping back up"           the bounce has taken back at most MAX_RECLAIM of the whole crack
                                                              (a bounce that reclaims more is strength, not a lower high)
  "not too low / not at VWAP support"                         the signal close is MIN_OVER_VWAP_PCT+ over VWAP
  "just halts, no pattern" / "halting up = strength"          MIN_DOLLAR_VOL traded before the signal, fewer than
                                                              MAX_HALT_JUMPS halts with a 5%+ jump; no halt that reopened
                                                              higher during the bounce
  "stop above the intraday high, not premarket"               stop = regular-hours high + HOD_STOP_PCT
  "hold full to EOD" / "move the stop once it fades 20-30%"   no half cover; after a LOCK_AFTER_PCT fade the stop moves to
                                                              LOCK_STOP_PCT under the entry (v1.2: -5 = 5% OVER the entry,
                                                              room for the afternoon chop); the rest is covered at EOD
  "stop trading it once it squeezes"                          after a stop-out the stock is done for the day
  "if the first trade is open, no need for this one"          one position per stock; a re-entry only after the first closed

Backtest (584 cached ticker-days 2026-04-01..2026-10-05, $10,000 a trade, 3% locate, 0.1% slippage a fill, cover 15:55):
  v1.2 (lock to entry +5%): 92 trades, 71% win, +$94,065.
  v1.1 (A + B, lock to -10%): 96 trades, 75% win (Apr-Jun 76% / Jul-Oct 74%), +$86,306, without the best 5 +$57,628.
  v1.0 (A only, LEVEL_SHORT=False): 77 trades, 75% win, +$77,553.   In-sample: the rules come from Jay's notes on these
  same days. See JAY_READ_SHORT_README.md.

How to use it (same API as backside_short.py):
    backtest:  s = JayReadShort("WETO", prior_close=3.61)
               for every CLOSED 1-min candle from 04:00 ET: events = s.on_bar(time, open, high, low, close, volume)
               trades = s.finish()
    live bot:  s = JayReadShort("WETO", prior_close=3.61, simulate_fills=False)
               s.warmup(todays_candles_so_far); on_bar() on every closed candle -> SIGNAL -> entry_allowed() -> send the
               short -> entry_filled() returns the stop order -> on_bar() keeps returning STOP_MOVED (lock) / COVER_ALL (EOD)
               -> cover_filled() on every cover.
"""
__version__ = "1.2"

import math
from datetime import datetime

import numpy as np

# =====================================================================================================================
# SETTINGS (the backtested values; change them only after re-running jay_read_short_backtest.py)
# =====================================================================================================================
MIN_UP_PCT = 150.0                 # stock up at least this % (high of day incl. premarket vs prior close)
MIN_DOLLAR_VOL = 20_000_000        # $ traded (from 04:00) before the signal: no thin halt games
HOD_MIN_AGE_MIN = 10               # the regular-hours high is at least this many minutes old (not the front side)
MIN_CRACK_PCT = 20.0               # lowest low since the regular-hours high is at least this % under it (momentum broken)
CRACK_NEAR_VWAP_PCT = 10.0         # that low came within this % over VWAP (or under it): it really cracked
SWING_PCT = 8.0                    # zigzag reversal that confirms a swing high (the 'overhead highs')
MIN_DROP_PCT = 12.0                # overhead high -> drop low at least this %
MIN_BOUNCE_PCT = 8.0               # drop low -> bounce high at least this %
RETRACE_MIN = 0.40                 # the bounce comes back at least this share of the drop under the overhead high
MAX_RECLAIM = 0.50                 # ... but the signal close has taken back at most this share of the whole crack
FRESH_TOP_MIN = 5                  # the red candle comes within this many minutes of the bounce high
MAX_UNDER_BOUNCE_HIGH_PCT = 6.0    # and closes within this % of the bounce high (short near the top, not too low)
MIN_OVER_VWAP_PCT = 3.0            # the signal close is at least this % over VWAP (not at VWAP support)
HALT_GAP_MIN = 5                   # regular-hours gap between candles with trades that counts as a halt (minutes)
MAX_HALT_JUMPS = 8                 # skip the stock once it has this many halts with a 5%+ jump (a halt game, no chart)

# entry B - "short it at the overhead high": the bounce comes up INTO a lower high the stock already failed at
LEVEL_SHORT = True                 # False = rollover entry only (v1.0)
LEVEL_SWING_PCT = 5.0              # zigzag reversal that marks the levels (swing highs since the open)
LEVEL_UNDER_HIGH_PCT = 10.0        # the level is a lower high: at least this % under the regular-hours high
LEVEL_ZONE_UNDER_PCT = 3.0         # the candle's high reaches within this % under the level ...
LEVEL_ZONE_OVER_PCT = 2.0          # ... or at most this % over it, and the candle closes under the level
LEVEL_MIN_DROP_PCT = 12.0          # level -> low of the pullback at least this %
LEVEL_MIN_BOUNCE_PCT = 8.0         # low -> this candle's high at least this %
LEVEL_MIN_OVER_VWAP_PCT = 5.0      # the signal close is at least this % over VWAP
LEVEL_SIGNAL_START = "10:00"       # level entries from this time (the open is too fast for a level read)

SIGNAL_START = "09:35"             # signals on candles closing from ...
SIGNAL_END = "15:00"               # ... to this time (ET)
ENTRY_START = "09:30"              # the entry candle (next open) must be in this window
LAST_ENTRY_TIME = "15:30"

HOD_STOP_PCT = 3.0                 # stop = regular-hours high x (1 + this %)
LOCK_AFTER_PCT = 25.0              # once a candle trades this % under the entry ...
LOCK_STOP_PCT = -5.0               # ... the stop moves to this % UNDER the entry; negative = OVER the entry. v1.2: -5 =
                                   # entry +5% (v1.1: 10 = entry -10%). None = off: hold the original stop
EOD_COVER_TIME = "15:55"           # cover what is open at this candle's open (None = no EOD cover)

MAX_TRADES_PER_DAY = 2             # per stock per day
STOP_FOR_DAY_AFTER_STOP = True     # after a stop-out (not a lock exit) leave the stock for the day ...
REENTRY_AFTER_NEW_HIGH = False     # ... unless (True) it squeezed to a NEW regular-hours high and that new high sets up again
POSITION_USD = 10_000.0            # backtest size per trade
LOCATE_FEE_PCT = 3.0               # % of the entry value, paid win or lose
SLIPPAGE_PCT = 0.10                # per fill (entry and cover)

RTH_START = "09:30"
RTH_END = "16:00"


def settings(**overrides):
    """The module settings as a dict (upper-case names), with overrides, e.g. settings(LOCK_STOP_PCT=None)."""
    g = globals()
    cfg = {k: g[k] for k in g if k.isupper() and not k.startswith("_")}
    for k, v in overrides.items():
        if k not in cfg:
            raise KeyError(f"unknown setting {k}")
        cfg[k] = v
    return cfg


def lock_text(pct):
    """'10% under the entry' / '5% over the entry' for LOCK_STOP_PCT."""
    if pct is None:
        return "off"
    return f"{abs(pct):g}% {'under' if pct >= 0 else 'over'} the entry"


def _min(hhmm):
    return None if hhmm is None else int(hhmm[:2]) * 60 + int(hhmm[3:5])


class _Grow:
    """A float array that grows (fast slicing for argmin / argmax)."""

    def __init__(self, cap=1024):
        self.a = np.empty(cap); self.n = 0

    def append(self, x):
        if self.n == len(self.a):
            self.a = np.concatenate([self.a, np.empty(len(self.a))])
        self.a[self.n] = x; self.n += 1

    def __getitem__(self, i):
        return self.a[:self.n][i]

    def __len__(self):
        return self.n


# =====================================================================================================================
# THE READER: structure + signal, one closed candle at a time
# =====================================================================================================================
class JayReader:
    """Feeds on closed 1-min candles that had trades (volume > 0), from 04:00 ET. add_bar() returns a signal dict on the
    candle that triggers it, else None."""

    def __init__(self, prior_close, cfg=None):
        self.cfg = cfg or settings()
        self.pc = float(prior_close)
        self.o, self.h, self.l, self.c, self.v = (_Grow() for _ in range(5))
        self.m, self.t, self.vw = [], [], []
        self._pv = self._vv = 0.0
        self.dollar = 0.0
        self.halt_jumps = 0                  # regular-hours halts (gap >= HALT_GAP_MIN) that reopened 5%+ away
        self.hod = -math.inf                 # high of day incl. premarket
        self.i0 = None                       # first regular-hours candle
        self.rh, self.k_rh = -math.inf, -1   # regular-hours high
        self._zz = None
        self.swings = []                     # confirmed swing highs (price, k of the high, k confirmed)
        self._used = set()                   # (overhead-high k, drop-low k): one signal per bounce
        self._zz5 = None
        self.levels = []                     # confirmed swing highs of the LEVEL_SWING_PCT zigzag
        self._used_lv = set()                # (level k, low k): one level signal per bounce
        c = self.cfg
        self._R = c["SWING_PCT"] / 100
        self._R5 = c["LEVEL_SWING_PCT"] / 100
        self._s0, self._s1 = _min(c["SIGNAL_START"]), _min(c["SIGNAL_END"])
        self._lv0 = _min(c["LEVEL_SIGNAL_START"])
        self._r0, self._r1 = _min(c["RTH_START"]), _min(c["RTH_END"])

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
        elif self.i0 is not None and k > self.i0 and minute - self.m[k - 1] >= self.cfg["HALT_GAP_MIN"] \
                and abs(o / self.c[k - 1] - 1) >= 0.05:
            self.halt_jumps += 1
        if self.i0 is not None and h > self.rh:
            self.rh, self.k_rh = float(h), k
        self._zz = self._zigzag(self._zz, self._R, self.swings, k, h, l)
        self._zz5 = self._zigzag(self._zz5, self._R5, self.levels, k, h, l)
        ctx = self._context(k)
        if ctx is None:
            return None
        a = self._rollover(k, *ctx) if self._s0 <= self.m[k] <= self._s1 else None
        b = self._level(k, *ctx) if self.cfg["LEVEL_SHORT"] and self._lv0 <= self.m[k] <= self._s1 else None
        return a or b                        # both reads run every candle; the rollover goes first on a tie

    @staticmethod
    def _zigzag(state, R, out, k, h, l):
        up, ext, ext_k = state if state is not None else (True, h, 0)
        if up:
            if h > ext:
                ext, ext_k = h, k
            elif l <= ext * (1 - R):
                out.append((ext, ext_k, k)); up, ext, ext_k = False, l, k
        else:
            if l < ext:
                ext, ext_k = l, k
            elif h >= ext * (1 + R):
                up, ext, ext_k = True, h, k
        return (up, ext, ext_k)

    def _context(self, k):
        """What both reads need: the stock qualifies, the high is not fresh, momentum broke. None = no read here."""
        cf, m = self.cfg, self.m
        if self.i0 is None or k < self.i0 + 2:
            return None
        if self.hod / self.pc - 1 < cf["MIN_UP_PCT"] / 100 or self.dollar < cf["MIN_DOLLAR_VOL"]:
            return None
        if cf["MAX_HALT_JUMPS"] is not None and self.halt_jumps >= cf["MAX_HALT_JUMPS"]:
            return None                                              # halt game
        RH, k_rh = self.rh, self.k_rh
        if m[k] - m[k_rh] < cf["HOD_MIN_AGE_MIN"] or k_rh >= k - 1:
            return None                                              # front side: the high is too fresh
        l = self.l
        k_lo = k_rh + int(np.argmin(l[k_rh:k + 1])); LO = l[k_lo]
        if 1 - LO / RH < cf["MIN_CRACK_PCT"] / 100:
            return None                                              # momentum not broken yet
        return RH, k_rh, LO, k_lo

    def _up_halt(self, a, b):
        m, o, c = self.m, self.o, self.c
        return any(m[q] - m[q - 1] >= self.cfg["HALT_GAP_MIN"] and o[q] > c[q - 1] for q in range(a + 1, b + 1))

    def _rollover(self, k, RH, k_rh, LO, k_lo):
        """Entry A: the bounce under the nearest overhead high rolls over near its top."""
        cf, m = self.cfg, self.m
        o, h, l, c, vw = self.o, self.h, self.l, self.c, self.vw
        if LO > vw[k_lo] * (1 + cf["CRACK_NEAR_VWAP_PCT"] / 100):
            return None                                              # it never came back to VWAP: still strong
        piv = [(RH, k_rh)] + [(p, kp) for p, kp, kc in self.swings if kc <= k and kp > k_rh]
        found = None
        for p, kp in reversed(piv):                                  # nearest overhead high still above the bounce
            if kp >= k - 1:
                continue
            L_k = kp + int(np.argmin(l[kp:k + 1])); L = l[L_k]
            if L_k >= k:
                continue
            BH_k = L_k + int(np.argmax(h[L_k:k + 1])); BH = h[BH_k]
            if BH < p:
                found = (p, kp, L, L_k, BH, BH_k)
                break
        if found is None:
            return None
        REF, k_ref, L, L_k, BH, BH_k = found
        if (k_ref, L_k) in self._used or BH_k >= k:
            return None
        drop, bounce, retr = 1 - L / REF, BH / L - 1, (BH - L) / (REF - L)
        if drop < cf["MIN_DROP_PCT"] / 100 or bounce < cf["MIN_BOUNCE_PCT"] / 100 or retr < cf["RETRACE_MIN"]:
            return None
        reclaim = (c[k] - LO) / (RH - LO)
        if reclaim > cf["MAX_RECLAIM"]:
            return None                                              # the bounce took back too much: strength
        if not (c[k] < o[k] and m[k] - m[BH_k] <= cf["FRESH_TOP_MIN"]
                and c[k] >= BH * (1 - cf["MAX_UNDER_BOUNCE_HIGH_PCT"] / 100)):
            return None                                              # no rollover near the top of the bounce
        if c[k] < vw[k] * (1 + cf["MIN_OVER_VWAP_PCT"] / 100):
            return None                                              # too low / at VWAP support
        if self._up_halt(L_k, k):
            return None                                              # halted up during the bounce
        self._used.add((k_ref, L_k))
        lh_n = sum(1 for p, kp in piv if kp <= k_ref)
        tests = sum(1 for p, kp in piv if kp < L_k and abs(p / BH - 1) <= 0.04)
        kind = "double top / level" if tests >= 1 else ("first lower high" if lh_n == 1 else "later lower high")
        return dict(k=k, time=self.t[k], close=c[k], up=self.hod / self.pc - 1, rth_high=RH, rth_high_time=self.t[k_rh],
                    crack_low=LO, crack_low_time=self.t[k_lo], crack=1 - LO / RH, ref=REF, ref_time=self.t[k_ref], low=L,
                    low_time=self.t[L_k], bounce_high=BH, bounce_high_time=self.t[BH_k], drop=drop, bounce=bounce,
                    retrace=retr, reclaim=reclaim, vwap=vw[k], vs_vwap=c[k] / vw[k] - 1, dollar=self.dollar,
                    hod_age_min=m[k] - m[k_rh], kind=kind, setup="rollover", k_rh=k_rh, k_crack=k_lo, k_ref=k_ref, k_low=L_k,
                    k_bh=BH_k, stop=RH * (1 + cf["HOD_STOP_PCT"] / 100))

    def _level(self, k, RH, k_rh, LO, k_lo):
        """Entry B: the bounce comes up into a lower high (a level it already failed at) and the candle that touches it
        closes under it, red or with the upper half of the candle rejected."""
        cf, m = self.cfg, self.m
        o, h, l, c, vw = self.o, self.h, self.l, self.c, self.vw
        rng = h[k] - l[k]
        if not (c[k] < o[k] or (rng > 0 and h[k] - c[k] >= 0.5 * rng)):
            return None
        if c[k] < vw[k] * (1 + cf["LEVEL_MIN_OVER_VWAP_PCT"] / 100):
            return None
        zu, zo = cf["LEVEL_ZONE_UNDER_PCT"] / 100, cf["LEVEL_ZONE_OVER_PCT"] / 100
        cap = RH * (1 - cf["LEVEL_UNDER_HIGH_PCT"] / 100)
        lv_list = [(RH, k_rh)] + [(p, kp) for p, kp, kc in self.levels if kc <= k - 1 and kp >= self.i0 and kp != k_rh]
        for lv, kp in sorted(lv_list):
            if kp >= k - 1 or lv > cap + 1e-12:
                continue
            if not (lv * (1 - zu) <= h[k] <= lv * (1 + zo) and c[k] < lv):
                continue
            L_k = kp + int(np.argmin(l[kp:k + 1])); L = l[L_k]
            if L_k >= k or 1 - L / lv < cf["LEVEL_MIN_DROP_PCT"] / 100 or h[k] / L - 1 < cf["LEVEL_MIN_BOUNCE_PCT"] / 100:
                continue
            if h[L_k:k].max() > lv * (1 + zo):
                continue                                             # this bounce already went through the level
            if (kp, L_k) in self._used_lv or self._up_halt(L_k, k):
                continue
            self._used_lv.add((kp, L_k))
            return dict(k=k, time=self.t[k], close=c[k], up=self.hod / self.pc - 1, rth_high=RH, rth_high_time=self.t[k_rh],
                        crack_low=LO, crack_low_time=self.t[k_lo], crack=1 - LO / RH, ref=lv, ref_time=self.t[kp], low=L,
                        low_time=self.t[L_k], bounce_high=h[k], bounce_high_time=self.t[k], drop=1 - L / lv,
                        bounce=h[k] / L - 1, retrace=(h[k] - L) / (lv - L), reclaim=(c[k] - LO) / (RH - LO), vwap=vw[k],
                        vs_vwap=c[k] / vw[k] - 1, dollar=self.dollar, hod_age_min=m[k] - m[k_rh],
                        kind="overhead-high rejection", setup="level", k_rh=k_rh, k_crack=k_lo, k_ref=kp, k_low=L_k, k_bh=k,
                        stop=RH * (1 + cf["HOD_STOP_PCT"] / 100))
        return None


# =====================================================================================================================
# THE TRADE: entry, stop, lock, EOD (fill rules of the research harness)
# =====================================================================================================================
class ShortTrade:
    """A candle that OPENS at/over the stop fills at its open, otherwise a high touching the stop fills at the stop. The
    lock is checked after the stop on the same candle and applies from the next candle. Every fill pays SLIPPAGE_PCT."""

    def __init__(self, signal, k0, t0, entry, stop, cfg):
        self.cfg, self.signal = cfg, signal
        self.k0, self.t0, self.entry, self.stop0 = k0, t0, entry, stop
        self.stop = stop
        self.locked = False
        lk = cfg["LOCK_STOP_PCT"]
        self.lock_trigger = entry * (1 - cfg["LOCK_AFTER_PCT"] / 100) if lk is not None else None
        self.lock_stop = entry * (1 - lk / 100) if lk is not None else None
        self.legs = []
        self.open_w = 1.0
        self.closed = False
        self.k_end, self.t_end = None, None
        self.lo, self.hi = entry, entry
        self.lock_time = None
        self._eod = _min(cfg["EOD_COVER_TIME"])

    def _cover(self, w, px, why, k, t):
        self.legs.append((w, px, why, t)); self.open_w -= w
        if self.open_w <= 1e-9:
            self.closed, self.k_end, self.t_end = True, k, t
        return dict(type="COVER", fraction=w, price=px, reason=why, time=t)

    def check_lock(self, l, t):
        if self.lock_trigger is not None and not self.locked and l <= self.lock_trigger:
            self.locked, self.lock_time = True, t
            self.stop = min(self.stop, self.lock_stop)      # the lock never moves a stop UP
            return [dict(type="STOP_MOVED", stop=self.stop, time=t,
                         reason=f"faded {self.cfg['LOCK_AFTER_PCT']:.0f}% -> stop to {lock_text(self.cfg['LOCK_STOP_PCT'])}")]
        return []

    def on_bar(self, k, t, minute, o, h, l, c):
        if self.closed:
            return []
        why = "LOCK" if self.locked else "STOP"
        if self._eod is not None and minute >= self._eod:
            return [self._cover(self.open_w, o, "EOD", k, t)]
        if k > self.k0 and o >= self.stop:
            return [self._cover(self.open_w, o, why, k, t)]
        if h >= self.stop:
            return [self._cover(self.open_w, self.stop, why, k, t)]
        self.hi, self.lo = max(self.hi, h), min(self.lo, l)
        return self.check_lock(l, t)

    def force_close(self, k, t, px, why="END"):
        return [self._cover(self.open_w, px, why, k, t)] if not self.closed else []

    @property
    def ret(self):
        s = self.cfg["SLIPPAGE_PCT"] / 100
        return sum(w * (self.entry - x * (1 + s)) / self.entry for w, x, _, _ in self.legs) - self.cfg["LOCATE_FEE_PCT"] / 100

    @property
    def reason(self):
        return self.legs[-1][2] if self.legs else ""

    def summary(self, symbol, day):
        s = self.signal
        return dict(ticker=symbol, date=day, signal_time=_hm(s["time"]), entry_time=_hm(self.t0), entry=self.entry,
                    stop=self.stop0, stop_pct=self.stop0 / self.entry - 1,
                    exit_time=_hm(self.t_end) if self.t_end is not None else "", exit_price=self.legs[-1][1] if self.legs else None,
                    exit_reason=self.reason, lock_time=_hm(self.lock_time) if self.lock_time is not None else "",
                    ret=self.ret, pnl=self.ret * self.cfg["POSITION_USD"], mfe=1 - self.lo / self.entry, mae=self.hi / self.entry - 1,
                    setup=s["setup"], kind=s["kind"], up=s["up"], rth_high=s["rth_high"], rth_high_time=_hm(s["rth_high_time"]),
                    crack_low=s["crack_low"], crack=s["crack"], ref=s["ref"], ref_time=_hm(s["ref_time"]), low=s["low"],
                    low_time=_hm(s["low_time"]), bounce_high=s["bounce_high"], bounce_high_time=_hm(s["bounce_high_time"]),
                    drop=s["drop"], bounce=s["bounce"], retrace=s["retrace"], reclaim=s["reclaim"], vs_vwap=s["vs_vwap"],
                    hod_age_min=s["hod_age_min"], dollar_vol=s["dollar"], k_signal=s["k"], k_entry=self.k0, k_exit=self.k_end,
                    k_rh=s["k_rh"], k_crack=s["k_crack"], k_ref=s["k_ref"], k_low=s["k_low"], k_bh=s["k_bh"])


def _hm(t):
    if t is None:
        return ""
    if isinstance(t, str):
        return t[-8:-3] if len(t) >= 8 and t[-3] == ":" and t[-6] == ":" else t
    return t.strftime("%H:%M")


def _day(t):
    return t.strftime("%Y-%m-%d") if isinstance(t, datetime) else str(t)[:10]


# =====================================================================================================================
# THE STRATEGY: one object per symbol per day
# =====================================================================================================================
class JayReadShort:
    """One object per symbol per day. Feed every CLOSED 1-min candle from 04:00 ET with on_bar(); candles without volume
    are ignored (a halted minute has no candle).

    simulate_fills=True (backtest): on_bar() also fills the entry at the next open and the exits from the candles.
      Events: SIGNAL / SHORT / COVER (reason STOP / LOCK / EOD) / STOP_MOVED (the lock) / SKIP (with the reason).

    simulate_fills=False (live bot): on_bar() reads the chart and, while a position is open, watches the lock and EOD.
      It returns SIGNAL (short now, stop attached), STOP_MOVED (replace the stop order) and COVER_ALL (EOD). The bot reports:
        entry_allowed(price, t) -> (ok, reason)      check before sending the short
        entry_filled(price, t)  -> orders to place   a STOP (buy to cover) for all shares
        entry_cancelled()                            the short was not sent / not filled
        cover_filled(fraction, price, reason, t)     STOP / LOCK / EOD / MANUAL
      warmup(candles) feeds past candles without trading when a symbol is added after 04:00."""

    def __init__(self, symbol, prior_close, cfg=None, simulate_fills=True, **overrides):
        self.cfg = settings(**overrides) if cfg is None else {**cfg, **overrides}
        self.symbol, self.pc = symbol, float(prior_close)
        self.simulate = simulate_fills
        self.reader = JayReader(prior_close, self.cfg)
        self.trades, self.signals = [], []
        self.pos = None
        self.pending = None
        self.awaiting = None
        self.done = False
        self._stop_rh = None                 # regular-hours high of the trade that was stopped out
        self._busy_until = -1
        self._busy_minute = -1
        self._e0, self._e1 = _min(self.cfg["ENTRY_START"]), _min(self.cfg["LAST_ENTRY_TIME"])
        self._eod = _min(self.cfg["EOD_COVER_TIME"])

    def _gate(self, busy, sig=None):
        if self.pos is not None or self.awaiting is not None or busy:
            return "already in a trade on this stock"
        if len(self.trades) >= self.cfg["MAX_TRADES_PER_DAY"]:
            return "done for the day"
        if self.done:
            if not (self.cfg["REENTRY_AFTER_NEW_HIGH"] and sig is not None and self._stop_rh is not None
                    and sig["rth_high"] > self._stop_rh * 1.0001):
                return "done for the day (stopped out)"
            self.done = False
        return ""

    def on_bar(self, t, o, h, l, c, v, minute=None):
        if not v or v <= 0:
            return []
        if minute is None:
            minute = t.hour * 60 + t.minute
        if not self.simulate:
            return self._on_bar_live(t, o, h, l, c, v, minute)
        ev = []
        k = len(self.reader.o)
        if self.pending is not None:                                 # 1 the entry fills at this candle's open
            s, self.pending = self.pending, None
            e = o * (1 - self.cfg["SLIPPAGE_PCT"] / 100)
            if not (self._e0 <= minute <= self._e1):
                ev.append(dict(type="SKIP", time=t, reason="entry candle outside the entry window", signal=s))
            elif e >= s["stop"]:
                ev.append(dict(type="SKIP", time=t, reason="opened at/over the stop", signal=s))
            else:
                self.pos = ShortTrade(s, k, t, e, s["stop"], self.cfg)
                self.trades.append(self.pos)
                ev.append(dict(type="SHORT", time=t, price=e, stop=s["stop"], signal=s))
        if self.pos is not None:                                     # 2 manage the open trade with this candle
            ev += self.pos.on_bar(k, t, minute, o, h, l, c)
            if self.pos.closed:
                self._busy_until = k
                if self.cfg["STOP_FOR_DAY_AFTER_STOP"] and self.pos.reason == "STOP":
                    self.done, self._stop_rh = True, self.pos.signal["rth_high"]
                self.pos = None
        sig = self.reader.add_bar(t, minute, o, h, l, c, v)          # 3 read the chart at the close
        if sig is not None:
            self.signals.append(sig)
            why = self._gate(k <= self._busy_until, sig)
            if why:
                ev.append(dict(type="SKIP", time=t, reason=why, signal=sig))
            else:
                self.pending = sig
                ev.append(dict(type="SIGNAL", time=t, close=c, stop=sig["stop"], signal=sig))
        return ev

    def _on_bar_live(self, t, o, h, l, c, v, minute):
        ev = []
        p = self.pos
        if p is not None:
            if self._eod is not None and minute >= self._eod - 1:
                ev.append(dict(type="COVER_ALL", time=t, reason="EOD", fraction=p.open_w))
            else:
                p.hi, p.lo = max(p.hi, h), min(p.lo, l)
                ev += p.check_lock(l, t)                             # the bot replaces its stop order
        sig = self.reader.add_bar(t, minute, o, h, l, c, v)
        if sig is not None:
            self.signals.append(sig)
            why = self._gate(minute <= self._busy_minute, sig)
            if why:
                ev.append(dict(type="SKIP", time=t, reason=why, signal=sig))
            else:
                self.awaiting = sig
                ev.append(dict(type="SIGNAL", time=t, close=c, stop=sig["stop"], signal=sig))
        return ev

    def warmup(self, candles):
        n = 0
        for t, o, h, l, c, v in candles:
            if v and v > 0:
                self.reader.add_bar(t, t.hour * 60 + t.minute, o, h, l, c, v); n += 1
        return n

    def entry_allowed(self, price, t):
        if self.awaiting is None:
            return False, "no signal waiting"
        m = t.hour * 60 + t.minute
        if not (self._e0 <= m <= self._e1):
            return False, "outside the entry window"
        if price >= self.awaiting["stop"]:
            return False, "price at/over the stop"
        return True, ""

    def entry_filled(self, price, t):
        s, self.awaiting = self.awaiting, None
        if s is None:
            raise RuntimeError("entry_filled() without a SIGNAL waiting")
        self.pos = ShortTrade(s, len(self.reader.o), t, float(price), s["stop"], self.cfg)
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
        if self.pos is not None and not self.pos.closed:
            k = len(self.reader.o) - 1
            self.pos.force_close(k, self.reader.t[k], self.reader.c[k], "END")
            self.pos = None
        return [tr.summary(self.symbol, _day(tr.t0)) for tr in self.trades if tr.closed]
