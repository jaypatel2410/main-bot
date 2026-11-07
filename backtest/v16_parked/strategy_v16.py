# -*- coding: utf-8 -*-
"""Kestrel - the parked v16 bounce-zone + vacuum short (strategy parameters + engine).
Part of main.py: main.py runs this file in its OWN namespace (same names, same settings), so the code works exactly
as when it was one file. Do not run it on its own - start main.py."""
# =============================================================================
# STRATEGY PARAMETERS  (verbatim copy - lh_short_backtester.py v16: bounce-zone + vacuum)
# =============================================================================
# Session (ET)
RTH_START = "09:30"
RTH_END = "16:00"
ENTRY_START = "09:45"              # no fill before this candle (the open is noise)
LAST_ENTRY_TIME = "11:00"          # no fill after this candle (later bounces lose)
EOD_COVER_TIME = "15:55"           # everything still open is covered at this candle's open
VWAP_INCLUDE_PREMARKET = True      # True matches the charts we reviewed

# Bounce-zone setup
MIN_GAP_PCT = 50.0                 # 09:30 open at least this far above the prior close
MIN_DIP_PCT = 20.0                 # after the top, price must dip at least this far under it
ZONE_FAR_PCT = 12.0                # short limit = this far under the top (bottom of the zone)
ZONE_NEAR_PCT = 10.0               # top of the zone: a candle opening closer to the top than this = bounce went past the zone
STOP_ABOVE_TOP_PCT = 3.0           # stop = top + this %, never moved
MIN_ZONE_ABOVE_VWAP_PCT = 15.0     # the zone must still be this far above VWAP (0 = off)
MAX_TRADES_PER_DAY = 2             # a second trade needs a new top (new high of day) after the first

# Which setups run
BOUNCE_ENABLED = True              # the bounce-zone short (v14)
VACUUM_ENABLED = True              # the intraday vacuum short

# Vacuum short (TradingView "Intraday Vacuum Top: Divergence Trap")
VAC_STRETCH_PCT = 15.0             # candle high at least this % above VWAP
VAC_VOL_LEN = 15                   # rolling volume baseline (candles, incl. the current one)
VAC_VOL_LIMIT = 0.5                # "volume vacuum": candle volume <= this x the baseline
VAC_PULLBACK_PCT = 5.0             # signal: a candle closes this % under the peak since the trap armed
VAC_MAX_OFF_HOD_PCT = 20.0         # ...while the close is still within this % of the high of day
VAC_ENTRY_START = "09:30"          # vacuum fills from this candle...
VAC_LAST_ENTRY_TIME = "11:00"      # ...up to this candle. v15 ran to 15:30: the afternoon signals were runners
                                   # breaking out of a midday base (51 trades, 27% win, -23R on the 584 days)
VAC_STOP_ABOVE_PEAK_PCT = 3.0      # stop = the peak + this %
VAC_MIN_PEAK_VOL_X = 1.5           # the peak candle's volume >= this x its VAC_VOL_LEN-candle average (a buying
                                   # climax at the high). 0 = off. Peaks on ordinary volume = a staircase still climbing
VAC_RETRY_PEAK_PCT = 20.0          # after a vacuum stop-out, the next vacuum needs a peak this % above the stopped trade's
                                   # peak (a new blow-off, not the next stair step). 0 = off
VAC_MAX_LOSSES_PER_DAY = 0         # no more vacuum shorts after this many vacuum stop-outs in a day (0 = off)
VAC_EXIT = "EOD"                   # "EOD" = hold to EOD_COVER_TIME, "VWAP" = cover when price trades back to VWAP
VAC_REQUIRE_GAP = False            # LIVE: off - vacuum also on intraday news squeezes that did not gap 50% (the
                                   # backtester keeps it True). The bounce-zone short still needs MIN_GAP_PCT.
VAC_USE_MIN_VOLUME = False         # LIVE: off - you check the volume yourself when you add a ticker (the backtester
                                   # keeps it True). The bounce-zone short still waits for MIN_DAY_VOLUME.
VAC_MAX_TRADES_PER_DAY = 3
VAC_STAND_DOWN_AFTER_DIP = True    # once the top dipped MIN_DIP_PCT it is a bounce setup: clear the vacuum trap until a new high

# Liquidity and costs
MIN_DAY_VOLUME = 10_000_000        # shares traded today (premarket included) before the first short; 0 = off
LOCATE_FEE_PCT = 3.0               # locate cost per short, % of the entry value (paid win or lose); 0 = ignore fees
SLIPPAGE_PCT = 0.10                # per fill
RISK_PER_TRADE_USD = 100.0         # sizing only, for $ P&L display (shares = $ risk / (stop - entry))

# Halts (LULD volatility halts). The entry is a resting limit order, so a fill is real as soon as
# the stock trades through the limit - also on the reopen candle right after a halt.
HALT_RULES_ENABLED = True          # no fill on a candle where the stock is halted (no trades that minute)
HALT_MIN_MINUTES = 3               # regular-hours minutes in a row with no trades = a halt
HALT_SKIP_REOPEN = False           # True = no fill on the reopen candle either (stricter)
HALT_COOLDOWN_MIN = 0              # no fill until this many minutes after trading resumes (0 = off)
HALT_VOID_MINUTES = 0              # a fill followed by this many no-trade minutes = treated as not filled (0 = off)

# Exits (fixed: hold to the close - kept as settings so the app and reports can read them)
PARTIAL_PCT = 0.0                  # no partial cover
RUNNER_TAKE_T2 = False             # no target exit
SCRATCH_R = 0.2                    # |R| below this counts as a scratch, not a win/loss

# =============================================================================
# STRATEGY ENGINE  (verbatim copy - lh_short_backtester.py v16)
# =============================================================================
ET = "America/New_York"
NAN = float("nan")
SETUP = "BOUNCE_ZONE"
VAC_SETUP = "VACUUM"


def _t(s):
    hh, mm = s.split(":")
    return dtime(int(hh), int(mm))


def _add_minutes(tt, minutes):
    total = tt.hour * 60 + tt.minute + minutes
    return dtime(total // 60, total % 60)


@dataclass
class Signal:
    setup: str
    stop: float
    key: tuple
    ref_idx: int = -1
    note: str = ""
    trigger: float = NAN               # resting short limit (bottom of the zone)


@dataclass
class Position:
    setup: str
    signal_idx: int
    entry_idx: int
    entry: float
    stop: float
    shares: int
    ref_idx: int
    note: str
    info: dict = field(default_factory=dict)
    stop_kind: str = "Stop"
    mfe_r: float = 0.0
    mae_r: float = 0.0
    stop_path: list = field(default_factory=list)
    traded_after: bool = False         # a trade printed after the entry candle (not filled into a halt)
    attempt: int = 1


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _minutes(tt):
    return tt.hour * 60 + tt.minute


# -----------------------------------------------------------------------------
# Backtest engine
# -----------------------------------------------------------------------------
class Backtest:
    """Bounce-zone short, bar by bar, no lookahead.
    The short limit for candle t+1 is decided at the close of candle t with data up to t only."""

    def __init__(self, ticker, day, df, prior_close):
        self.ticker, self.day = ticker, day
        self.df = df.reset_index(drop=True)
        d = self.df
        self.o = d["open"].to_numpy(float)
        self.h = d["high"].to_numpy(float)
        self.l = d["low"].to_numpy(float)
        self.c = d["close"].to_numpy(float)
        self.v = d["volume"].to_numpy(float)
        self.tod = np.array([x.time() for x in d["time"]])
        self.n = len(d)
        self.prior_close = prior_close

        self.rth = (self.tod >= _t(RTH_START)) & (self.tod < _t(RTH_END))
        self.rth0 = int(np.argmax(self.rth)) if self.rth.any() else None
        pm = self.tod < _t(RTH_START)
        self.pm_high = float(self.h[pm].max()) if pm.any() else NAN
        self.pm_low = float(self.l[pm].min()) if pm.any() else NAN

        self._indicators()
        self._halt_minutes()
        self.cumvol = np.cumsum(self.v)              # shares traded today up to and including each candle
        hit = np.nonzero(self.cumvol >= MIN_DAY_VOLUME)[0] if MIN_DAY_VOLUME > 0 else np.array([0])
        self.vol_ok_idx = int(hit[0]) if len(hit) else -1

        # gap at the open (known from the 09:30 candle on)
        self.open_px = float(self.o[self.rth0]) if self.rth0 is not None else NAN
        self.gap_pct = ((self.open_px / prior_close - 1.0) * 100.0
                        if prior_close and self.rth0 is not None else NAN)
        self.gap_ok = bool(self.gap_pct == self.gap_pct and self.gap_pct >= MIN_GAP_PCT)

        # state
        self.hod, self.hod_idx = -math.inf, -1
        self.dipped = False
        self.dip_low, self.dip_idx = math.inf, -1
        self.top_used = False                        # this top's setup is used up (trade taken or a filtered touch)
        self.pos = None
        self.pending = None                          # the armed short limit for the next candle (app: "armed")
        self.setup_info = {}
        self.trades = []
        self.skipped = []
        self.ntr = 0
        self.halt_reopen_min = None
        self.halts = []
        self._logged = set()
        self.block_reason = ""                       # why the limit is not armed right now
        self.block_consumes = False                  # True = a touch of the zone while blocked uses up the top

        self.entry_start_t = _t(ENTRY_START)
        self.last_entry_t = _t(LAST_ENTRY_TIME)
        self.rth_start_t = _t(RTH_START)
        self.rth_end_t = _t(RTH_END)
        self.eod_t = _t(EOD_COVER_TIME)

        # vacuum short state
        self.vol_ma = pd.Series(self.v).rolling(int(VAC_VOL_LEN), min_periods=int(VAC_VOL_LEN)).mean().to_numpy()
        self.vac_armed = False
        self.vac_peak, self.vac_peak_idx, self.vac_arm_idx = 0.0, -1, -1
        self.vac_pending = None                      # vacuum short for the next candle's open
        self.vac_ntr = 0
        self.vac_start_t = _t(VAC_ENTRY_START)
        self.vac_last_t = _t(VAC_LAST_ENTRY_TIME)

    # ---------------- indicators ----------------
    def _indicators(self):
        tp = (self.h + self.l + self.c) / 3.0
        mask = np.ones(self.n, bool) if VWAP_INCLUDE_PREMARKET else self.rth.copy()
        if not VWAP_INCLUDE_PREMARKET and self.rth0 is not None:
            mask[self.rth0:] = True
        pv = np.cumsum(np.where(mask, tp * self.v, 0.0))
        vv = np.cumsum(np.where(mask, self.v, 0.0))
        with np.errstate(invalid="ignore", divide="ignore"):
            self.vwap = np.where(vv > 0, pv / vv, np.nan)

    def _halt_minutes(self):
        """notrade_before[i] = regular-hours minutes in a row with no trades right before bar i
        (missing bars + zero-volume bars). Uses only bars before i."""
        self.mins = np.array([x.hour * 60 + x.minute for x in self.tod])
        self.notrade_before = np.zeros(self.n, dtype=int)
        r0 = _minutes(_t(RTH_START))
        r1 = _minutes(_t(RTH_END))
        run = 0
        for i in range(1, self.n):
            a, b = self.mins[i - 1], self.mins[i]
            missing = max(0, min(b, r1) - max(a + 1, r0))          # missing regular-hours minutes in between
            if self.rth[i - 1] and self.v[i - 1] <= 0:
                run += 1 + missing
            else:
                run = missing
            self.notrade_before[i] = run

    def halt_block(self, t):
        """True when a short cannot be filled at bar t because of a halt."""
        if not HALT_RULES_ENABLED or not self.rth[t]:
            return False
        if self.v[t] <= 0:
            return True                              # halted: nothing traded this minute
        if HALT_SKIP_REOPEN and self.notrade_before[t] >= HALT_MIN_MINUTES:
            return True                              # the reopen candle
        return (HALT_COOLDOWN_MIN > 0 and self.halt_reopen_min is not None
                and self.mins[t] - self.halt_reopen_min < HALT_COOLDOWN_MIN)

    # ---------------- levels of the current top ----------------
    def zone(self):
        """(limit price = bottom of the zone, top of the zone, stop) for the current top."""
        top = self.hod
        return (top * (1 - ZONE_FAR_PCT / 100.0), top * (1 - ZONE_NEAR_PCT / 100.0),
                top * (1 + STOP_ABOVE_TOP_PCT / 100.0))

    def log_skip(self, t, reason, price=None, once=None):
        if once is not None:
            if once in self._logged:
                return
            self._logged.add(once)
        self.skipped.append({"idx": t, "time": self.df["time"].iloc[t], "setup": SETUP,
                             "price": float(self.c[t] if price is None else price), "reason": reason})

    # ---------------- the setup ----------------
    def _arm(self, t):
        """At the close of candle t: rest a short limit for candle t+1 when everything lines up."""
        self.pending = None
        self.block_reason, self.block_consumes = "", False
        nxt = _add_minutes(self.tod[t], 1) if self.tod[t] < dtime(23, 59) else self.tod[t]   # the order rests for the next minute
        if (not BOUNCE_ENABLED or self.pos is not None or not self.dipped or self.top_used
                or not (self.rth_start_t <= nxt < self.rth_end_t) or self.ntr >= MAX_TRADES_PER_DAY):
            if self.ntr >= MAX_TRADES_PER_DAY:
                self.block_reason = f"max {MAX_TRADES_PER_DAY} trades a day"
            return
        zl, zh, stop = self.zone()
        if t < self.rth0:                            # arming for the 09:30 candle: the gap is not known yet
            self.block_reason = (f"before {ENTRY_START} - the open is noise" if nxt < self.entry_start_t
                                 else "the open candle - the gap is not known before it prints")
            self.block_consumes = True
            return
        if not self.gap_ok:
            self.block_reason = ("no prior close - gap unknown" if self.gap_pct != self.gap_pct
                                 else f"gap only {self.gap_pct:+.0f}% at the open (< {MIN_GAP_PCT:g}%)")
            return
        if MIN_DAY_VOLUME > 0 and self.cumvol[t] < MIN_DAY_VOLUME:
            self.block_reason = f"day volume {self.cumvol[t] / 1e6:.1f}M < {MIN_DAY_VOLUME / 1e6:g}M so far"
            return
        if nxt > self.last_entry_t:
            self.block_reason = f"after {LAST_ENTRY_TIME} - no new entries"
            return
        vw = self.vwap[t]
        ext = (zl / vw - 1.0) * 100.0 if vw == vw and vw > 0 else NAN
        if nxt < self.entry_start_t:
            self.block_reason = f"before {ENTRY_START} - the open is noise"
            self.block_consumes = True
            return
        if MIN_ZONE_ABOVE_VWAP_PCT > 0 and not (ext >= MIN_ZONE_ABOVE_VWAP_PCT):
            self.block_reason = f"zone only {ext:.0f}% above VWAP (< {MIN_ZONE_ABOVE_VWAP_PCT:g}%) - VWAP support right under it"
            self.block_consumes = True
            return
        top_i = self.hod_idx
        dip_pct = (1 - self.dip_low / self.hod) * 100.0
        note = (f"Top {self.hod:.3f} -> dip {dip_pct:.0f}% to {self.dip_low:.3f} -> bounce into "
                f"{zl:.3f}-{zh:.3f} ({ZONE_FAR_PCT:g}-{ZONE_NEAR_PCT:g}% under the top), zone {ext:.0f}% above VWAP")
        key = (SETUP, top_i, self.dip_idx)
        sig = Signal(SETUP, stop, key, ref_idx=top_i, note=note, trigger=zl)
        self.setup_info[key] = {"top": self.hod}
        self.pending = {"sig": sig, "trigger": zl, "zone_hi": zh, "idx": t, "top": self.hod, "top_idx": top_i,
                        "dip_low": self.dip_low, "dip_idx": self.dip_idx, "dip_pct": dip_pct,
                        "vwap": float(vw), "ext": ext}

    def _try_fill(self, t):
        """Candle t against the limit armed at the close of t-1."""
        p = self.pending
        self.pending = None
        if p is None or self.h[t] < p["trigger"]:
            return
        if not (self.entry_start_t <= self.tod[t] <= self.last_entry_t):
            return                                   # the next candle came late (no trades for a while): outside the window
        if self.halt_block(t):
            self.log_skip(t, "stock halted - entry cancelled", p["trigger"])
            return
        if self.o[t] > p["zone_hi"]:
            gap = (1 - self.o[t] / p["top"]) * 100.0
            self.log_skip(t, f"bounce opened {gap:.1f}% under the top - past the zone, needs a new dip", self.o[t])
            self.dipped, self.dip_low, self.dip_idx = False, math.inf, -1
            return
        px = p["trigger"] if self.o[t] <= p["trigger"] else self.o[t]
        fill = px * (1 - SLIPPAGE_PCT / 100.0)
        sig = p["sig"]
        stop = sig.stop
        if fill >= stop:
            return
        shares = max(1, int(RISK_PER_TRADE_USD // (stop - fill)))
        self.ntr += 1
        self.top_used = True
        info = {k: p[k] for k in ("top", "top_idx", "dip_low", "dip_idx", "dip_pct", "vwap", "ext", "trigger", "zone_hi")}
        self.pos = Position(sig.setup, p["idx"], t, fill, stop, shares, sig.ref_idx, sig.note, info=info, attempt=self.ntr)
        self.pos.stop_path.append((t, stop))

    def _touch_without_order(self, t):
        """The bounce reached the zone on candle t but no limit was resting (a filter failed at t-1)."""
        if not BOUNCE_ENABLED or self.pos is not None or not self.dipped or self.top_used or self.vac_pending is not None:
            return
        zl, zh, _ = self.zone()
        if self.h[t] < zl or not self.rth[t] or self.l[t] < self.dip_low:
            return
        if self.o[t] > zh:
            self.dipped, self.dip_low, self.dip_idx = False, math.inf, -1   # went past the zone: needs a new dip
            return
        reason = self.block_reason or "not armed"
        in_window = self.rth_start_t <= self.tod[t] <= self.last_entry_t
        if self.block_consumes and in_window:
            self.top_used = True                     # this top's bounce came and went: wait for a new high of day
            self.log_skip(t, reason + " - top used up", zl)
        else:
            self.log_skip(t, reason, zl, once=(reason.split(" ")[0], self.hod_idx))

    # ---------------- vacuum short ----------------
    def _vac_update(self, t):
        """At the close of candle t: the vacuum trap (same math as the TradingView indicator)."""
        if not VACUUM_ENABLED or not self.rth[t]:
            return
        if VAC_STAND_DOWN_AFTER_DIP and self.dipped:
            self.vac_armed, self.vac_peak, self.vac_peak_idx = False, 0.0, -1     # bounce territory: no vacuum on this top
            return
        vw, ma = self.vwap[t], self.vol_ma[t]
        if not (ma == ma) or not (vw == vw) or vw <= 0:
            return
        stretched = (self.h[t] - vw) / vw * 100.0 >= VAC_STRETCH_PCT
        dead = self.v[t] <= ma * VAC_VOL_LIMIT
        if stretched and dead and not self.vac_armed:
            self.vac_armed, self.vac_arm_idx = True, t
        if not self.vac_armed:
            return
        if self.h[t] > self.vac_peak:
            self.vac_peak, self.vac_peak_idx = self.h[t], t
        trigger = self.vac_peak * (1 - VAC_PULLBACK_PCT / 100.0)
        near_hod = self.c[t] >= self.hod * (1 - VAC_MAX_OFF_HOD_PCT / 100.0)
        if not (self.c[t] < trigger and near_hod):
            return
        peak, peak_i = self.vac_peak, self.vac_peak_idx
        self.vac_armed, self.vac_peak, self.vac_peak_idx = False, 0.0, -1         # the trap resets after a signal
        nxt = _add_minutes(self.tod[t], 1) if self.tod[t] < dtime(23, 59) else self.tod[t]
        ext = (peak / self.vwap[peak_i] - 1.0) * 100.0 if self.vwap[peak_i] > 0 else NAN
        vac_stops = [x for x in self.trades if x["setup"] == VAC_SETUP and x["exit_reason"].startswith("Stop")]
        why = ""
        if self.pos is not None:
            why = f"{self.pos.setup} short already open"
        elif VAC_REQUIRE_GAP and not self.gap_ok:
            why = (f"gap only {self.gap_pct:+.0f}% at the open (< {MIN_GAP_PCT:g}%)" if self.gap_pct == self.gap_pct
                   else "gap unknown")
        elif VAC_USE_MIN_VOLUME and MIN_DAY_VOLUME > 0 and self.cumvol[t] < MIN_DAY_VOLUME:
            why = f"day volume {self.cumvol[t] / 1e6:.1f}M < {MIN_DAY_VOLUME / 1e6:g}M"
        elif not (self.vac_start_t <= nxt <= self.vac_last_t):
            why = f"outside {VAC_ENTRY_START}-{VAC_LAST_ENTRY_TIME}"
        elif self.vac_ntr >= VAC_MAX_TRADES_PER_DAY:
            why = f"max {VAC_MAX_TRADES_PER_DAY} vacuum trades a day"
        elif VAC_MIN_PEAK_VOL_X > 0 and not (self.v[peak_i] >= VAC_MIN_PEAK_VOL_X * self.vol_ma[peak_i] > 0):
            pv = self.v[peak_i] / self.vol_ma[peak_i] if self.vol_ma[peak_i] > 0 else 0.0
            why = (f"no volume climax at the peak ({pv:.1f}x its {VAC_VOL_LEN}-candle average, need "
                   f"{VAC_MIN_PEAK_VOL_X:g}x) - the run is still climbing")
        elif VAC_RETRY_PEAK_PCT > 0 and vac_stops and peak < vac_stops[-1]["top"] * (1 + VAC_RETRY_PEAK_PCT / 100.0):
            why = (f"staircase: peak {peak:.3f} is only {(peak / vac_stops[-1]['top'] - 1) * 100:+.0f}% over the stopped "
                   f"vacuum peak {vac_stops[-1]['top']:.3f} (need +{VAC_RETRY_PEAK_PCT:g}%)")
        elif VAC_MAX_LOSSES_PER_DAY > 0 and len(vac_stops) >= VAC_MAX_LOSSES_PER_DAY:
            why = f"{VAC_MAX_LOSSES_PER_DAY} vacuum stop-out(s) today - vacuum done for the day"
        stop = peak * (1 + VAC_STOP_ABOVE_PEAK_PCT / 100.0)
        if why:
            self.skipped.append({"idx": t, "time": self.df["time"].iloc[t], "setup": VAC_SETUP,
                                 "price": float(self.c[t]), "reason": "vacuum signal - " + why})
            return
        note = (f"Peak {peak:.3f} ({ext:.0f}% over VWAP) on dying volume -> close {self.c[t]:.3f} is "
                f"{(1 - self.c[t] / peak) * 100:.1f}% under the peak -> short the next open")
        sig = Signal(VAC_SETUP, stop, (VAC_SETUP, peak_i, t), ref_idx=peak_i, note=note, trigger=trigger)
        self.vac_pending = {"sig": sig, "idx": t, "peak": peak, "peak_idx": peak_i, "trigger": trigger,
                            "vwap": float(self.vwap[t]), "ext": ext, "arm_idx": self.vac_arm_idx}
        self.pending = None                          # vacuum comes first at the next open

    def _vac_fill(self, t):
        """Candle t: the vacuum short decided at the close before fills at this open (or the reopen after a halt)."""
        p = self.vac_pending
        if self.tod[t] > self.vac_last_t:
            self.vac_pending = None
            return
        if HALT_RULES_ENABLED and self.v[t] <= 0:
            return                                   # halted: the order waits for the reopen
        self.vac_pending = None
        fill = self.o[t] * (1 - SLIPPAGE_PCT / 100.0)
        stop = p["sig"].stop
        if fill >= stop:
            self.log_skip(t, "vacuum: opened above the stop", self.o[t])
            return
        self.pending = None
        shares = max(1, int(RISK_PER_TRADE_USD // (stop - fill)))
        self.vac_ntr += 1
        info = {"top": p["peak"], "top_idx": p["peak_idx"], "dip_low": NAN, "dip_idx": p["idx"], "dip_pct": NAN,
                "vwap": p["vwap"], "ext": p["ext"], "trigger": p["trigger"], "zone_hi": NAN}
        sig = p["sig"]
        self.pos = Position(VAC_SETUP, p["idx"], t, fill, stop, shares, sig.ref_idx, sig.note, info=info,
                            attempt=self.vac_ntr)
        self.pos.stop_path.append((t, stop))

    # ---------------- trades ----------------
    def _close(self, t, px, reason):
        pos = self.pos
        risk = pos.stop_path[0][1] - pos.entry
        pnl = pos.shares * (pos.entry - px)
        r = pnl / (risk * pos.shares) if risk > 0 else 0.0
        fee_usd = pos.entry * pos.shares * LOCATE_FEE_PCT / 100.0     # the locate is paid on every short
        r_net = (pnl - fee_usd) / (risk * pos.shares) if risk > 0 else 0.0
        pos.stop_path.append((t, pos.stop))
        info = pos.info
        self.trades.append({
            "n": len(self.trades) + 1, "setup": pos.setup, "note": pos.note,
            "signal_time": self.df["time"].iloc[pos.signal_idx],
            "entry_idx": pos.entry_idx, "entry_time": self.df["time"].iloc[pos.entry_idx],
            "entry": pos.entry, "stop": pos.stop_path[0][1],
            "t1": info["dip_low"] if pos.setup != VAC_SETUP else info["vwap"],
            "t1_kind": "DIP LOW" if pos.setup != VAC_SETUP else "VWAP", "t2": info["vwap"],
            "risk_pct": risk / pos.entry * 100.0, "shares": pos.shares,
            "partial_idx": -1, "partial_px": NAN,
            "exit_idx": t, "exit_time": self.df["time"].iloc[t], "exit": px, "exit_reason": reason,
            "R": r, "pnl_usd": pnl, "pnl_pct": pnl / (pos.entry * pos.shares) * 100.0,
            "mfe_R": pos.mfe_r, "mae_R": pos.mae_r, "ref_idx": pos.ref_idx,
            "leg": pos.attempt - 1, "attempt": pos.attempt, "grade": "", "supply": NAN,
            "top": info["top"], "top_idx": info["top_idx"], "dip_low": info["dip_low"], "dip_idx": info["dip_idx"],
            "dip_pct": info["dip_pct"], "zone_lo": info["trigger"], "zone_hi": info["zone_hi"],
            "vwap_signal": info["vwap"], "zone_vs_vwap_pct": info["ext"], "gap_pct": self.gap_pct,
            "fee_pct": LOCATE_FEE_PCT, "fee_usd": fee_usd, "R_net": r_net,
            "pnl_pct_net": (pnl - fee_usd) / (pos.entry * pos.shares) * 100.0,
            "day_vol_entry": float(self.cumvol[pos.signal_idx]),
            "stop_path": list(pos.stop_path),
        })
        self.pos = None

    def _manage(self, t):
        pos = self.pos
        o, h, l = self.o[t], self.h[t], self.l[t]
        slip_up = 1 + SLIPPAGE_PCT / 100.0
        risk = pos.stop_path[0][1] - pos.entry
        if t > pos.entry_idx and self.tod[t] >= self.eod_t:
            self._close(t, o * slip_up, "EOD")
            return
        if t > pos.entry_idx:                        # the entry candle's low may print before the fill
            pos.mfe_r = max(pos.mfe_r, (pos.entry - l) / risk)
        pos.mae_r = max(pos.mae_r, (h - pos.entry) / risk)
        if t > pos.entry_idx and o >= pos.stop:
            self._close(t, o * slip_up, pos.stop_kind + " (gap)")
            return
        if h >= pos.stop:
            self._close(t, pos.stop * slip_up, pos.stop_kind)
            return
        if pos.setup == VAC_SETUP and VAC_EXIT.upper() == "VWAP" and t > pos.entry_idx:
            tgt = self.vwap[t - 1]                   # VWAP known at the close before
            if tgt == tgt and self.l[t] <= tgt < pos.entry:
                self._close(t, min(o, tgt) * slip_up, "VWAP")

    def _update_top(self, t):
        if self.h[t] > self.hod:
            self.hod, self.hod_idx = self.h[t], t
            self.dipped, self.dip_low, self.dip_idx = False, math.inf, -1
            self.top_used = False                    # a new high of day = a new top
        if not self.dipped and self.l[t] <= self.hod * (1 - MIN_DIP_PCT / 100.0):
            self.dipped = True
            if self.rth[t] and not self.gap_ok:
                self.log_skip(t, ("no prior close - gap unknown" if self.gap_pct != self.gap_pct
                                  else f"gap only {self.gap_pct:+.0f}% at the open (< {MIN_GAP_PCT:g}%) - not a setup day"),
                              once=("gap",))
        if self.dipped and self.l[t] < self.dip_low:
            self.dip_low, self.dip_idx = self.l[t], t

    # ---------------- main loop ----------------
    def run(self):
        if self.rth0 is None:
            print("No regular-hours bars in data.")
            return self
        last_rth = int(np.where(self.rth)[0][-1])
        for t in range(self.n):
            if self.rth[t]:
                if HALT_RULES_ENABLED and self.v[t] > 0 and self.notrade_before[t] >= HALT_MIN_MINUTES:
                    self.halt_reopen_min = int(self.mins[t])     # trading resumed after a halt
                    self.halts.append(t)
                if (HALT_RULES_ENABLED and HALT_VOID_MINUTES > 0 and self.pos is not None
                        and not self.pos.traded_after and t > self.pos.entry_idx):
                    quiet = self.notrade_before[t] + (1 if self.v[t] <= 0 else 0)
                    if quiet >= HALT_VOID_MINUTES:
                        if self.pos.setup == VAC_SETUP:
                            self.vac_ntr -= 1
                        else:
                            self.ntr -= 1
                        self.pos = None                          # filled into a halt = no real position
                        self.log_skip(t, "halted right after the entry - no position")
                    elif self.v[t] > 0:
                        self.pos.traded_after = True
                if self.vac_pending is not None and self.pos is None:
                    self._vac_fill(t)                    # vacuum short at this open (decided at the close before)
                if self.pending is not None and self.pos is None:
                    self._try_fill(t)
                else:
                    self.pending = None
                    self._touch_without_order(t)
                if self.pos is not None:
                    self._manage(t)
            else:
                self.pending = None
            self._update_top(t)
            self._vac_update(t)
            if self.pos is None and self.vac_pending is None:
                self._arm(t)                         # at the end of the data this is the limit resting for the next minute
        if self.pos is not None:
            self._close(last_rth, self.c[last_rth] * (1 + SLIPPAGE_PCT / 100.0), "EOD")
            self.pending = None
        self.vac_pending = None
        return self
