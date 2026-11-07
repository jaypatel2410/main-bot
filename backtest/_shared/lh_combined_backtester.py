#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LH COMBINED BACKTESTER 3.10.0 -  premarket long (05:00-09:00)  +  intraday shorts (Jay-read + max squeeze), ONE account
====================================================================================================================
One file, every strategy of Kestrel 3.10.0, with the same logic as the live bot (bars from the IB data vault, no
IB Gateway code in this file):

  3.10.0: the long's hard stop sells at stop +1% (LONG_STOP_EARLY_PCT = 1.0), as the live bot (lh_long_premarket.py 1.8).

  PREMARKET LONG   the lh_long_premarket.py 1.6 engine, i.e. the rules of your premarket long backtest: a stock up
                   +30% from the prior close (price $0.50+), momentum chase on 10-second candles (surge candle RVOL
                   1.5+, close in the top 40% of its range), entries only in the first 20 minutes after the +30%
                   cross, max 3 trades per stock, half sold at 2R (3R strong), the rest trails, 5-minute time stop,
                   everything closed by 09:00.
                   Size: LONG_ACCOUNT_PCT (20%) of the balance, never more than LONG_MAX_POSITION_USD ($10,000).
                   Stop 1-10% under the entry; a stock is done once it lost 25% of the position that day. Daily stop: no new longs once
                   the day's long losses reach 50% of the long position size at the start of the day ($1,000 on a
                   $2,000 position, $5,000 at the $10,000 cap).
  INTRADAY SHORT   SHORT_STRATEGY picks the engine (the same setting as the app):
                   "jay_read" (default)  Jay-read short v1.2 = jay_read_short.py from the same folder, used
                       unchanged: stocks up 150%+ with $20M traded, regular-hours high 10+ min old, cracked 20%+;
                       entry A rollover / entry B overhead high; stop = regular-hours high +3%; after a 25% fade the
                       stop goes to entry +5% (v1.2, the lock); done for the day after a stop, cover 15:55.
                     + SQUEEZE_ENABLED (3.9.0): the max squeeze short = max_squeeze_short.py (same folder) on the same
                       stock: up 30%+, squeezed 50%+ over the last swing high it broke, red candle at the top; stop = the
                       top +20%, no lock, cover 15:55. ONE position per stock (the first signal wins) and a stop-out of
                       either short ends the stock for the day - max_squeeze_short.ShortBook, the live bot's code.
                       3% locate + 0.1% slippage a fill.
                   "v16"  the parked bounce-zone + vacuum short = the lh_short_backtester.py v16 engine below, line for
                       line (1-minute candles, 3% locate fee on every short, held to 15:55 or the stop). No logic changed.
                   Size: SHORT_ACCOUNT_PCT (20%) of the balance, never more than SHORT_MAX_POSITION_USD ($50,000);
                   no risk cap (3.7.2, like the app); optional MAX_RISK_PER_TRADE_USD $ cap (None = off).
  ONE ACCOUNT      both sides trade the same balance and compound together: the morning's long P&L is in the
                   balance before the 09:30 shorts. Every trade is sized when it is entered, from the balance of the
                   trades already closed (STARTING_BALANCE to begin with).

The engines are used unchanged: the v16 short engine below is lh_short_backtester.py v16 line for line, the Jay-read
short is imported from jay_read_short.py (put it next to this file), the long engine is lh_long_premarket.py 1.6 (its
settings carry a LONG_ prefix here because both files use some of the same names). The bulk runner
(lh_combined_bulk_runner.py) imports this file and uses these exact engines.

Checked on the 584 cached days (2026-04-01 to 2026-10-05, LONG_BARS = "rebuild"):
  jay_read + squeeze (3.9.0)  shorts $10k a trade: 98 trades, 71% win, +$120,316 | combined account: see CHANGES_3.9.0.md
  jay_read v1.2 alone         92 trades, 71% win, +$94,065       (SQUEEZE_ENABLED = False)
  jay_read v1.1 (3.8.x)       96 trades, 75% win, +$86,306 | combined account: 222 trades, 66% win, $10k -> $298,787
  v16       live settings (VAC_REQUIRE_GAP / VAC_USE_MIN_VOLUME = False): 94 trades, +$61,596 | backtester settings: 63

DATA (3.8.1: the IB data vault - this file never connects to IB Gateway):
  short  1-minute bars 04:00-20:00 + the prior close, from market_data_vault.db (VAULT_DB / --vault)
  long   the vault's 10-second premarket bars when it has them (LONG_BARS = "vault"); days without them (older than
         the 10-second window, or not fetched yet) use 10-second candles rebuilt from the 1-minute bars, noted
         "rebuilt". LONG_BARS = "rebuild" always rebuilds (the verified numbers below).
  A ticker-day not in the vault (or stored there as no_data / no_contract / error) is skipped and written to
  OUTPUT_DIR/missing_from_vault.xlsx. Fetching is the vault's job:  python ib_data_vault.py --list <list.xlsx>
  One-off files: CSV_PATH (+ CSV_10S_PATH) runs one day from CSV instead of the vault.
  The vault is read through lh_vault_bars.py (keep it next to this file); ib_data_vault.py stays in the vault folder.

Requirements:  pip install pandas numpy plotly                (no IB API package needed)
Run:           python lh_combined_backtester.py [--vault PATH]  (TICKER / DATE below, or a BATCH of days)
Output:        combined_backtests/<TICKER>_<DATE>_combined.html   (chart: long buys / sells + shorts, trade table)
               combined_backtests/<TICKER>_<DATE>_combined_trades.csv
               combined_backtests/missing_from_vault.xlsx        (only when a day was not in the vault)
"""

# =============================================================================
# HARD-CODED INPUTS
# =============================================================================
TICKER = "XRPN"
DATE = "2026-10-02"                # YYYY-MM-DD, the trading day (ET)

# Optional: several days in one go, e.g. BATCH = [("XRPN", "2026-10-02"), ("AMOD", "2026-10-02")]. The account
# carries over from one day to the next, in date order.
BATCH = []

# --- Data: the IB data vault (this file never downloads) ---------------------
VAULT_DB = r"market_data_vault.db" # FULL PATH of your vault, e.g. r"C:\...\ib_data_vault\market_data_vault.db" (--vault).
                                   # A bare name is looked up next to this file, then in the current folder.
                                   # Days not in the vault are skipped and listed in OUTPUT_DIR/missing_from_vault.xlsx:
                                   # python ib_data_vault.py --list missing_from_vault.xlsx  adds them.
CSV_PATH = ""                      # one-off csv mode (one day): 1-minute bars (time,open,high,low,close,volume[,prior_close])
CSV_10S_PATH = ""                  # csv mode, optional: 10-second bars for the long (empty = rebuilt from the 1-minute bars)
LONG_BARS = "vault"                # "vault" = the vault's real 10-second bars when it has them, else rebuilt (noted "rebuilt")
                                   # "rebuild" = always rebuilt from the 1-minute bars (the verified numbers below)
PRIOR_CLOSE_OVERRIDE = None        # set a float to force the prior close

# =============================================================================
# ACCOUNT - one balance for both sides, compounding (the live bot does the same with your TradeZero equity)
# =============================================================================
STARTING_BALANCE = 10_000.0
LONG_ENABLED = True                # the premarket long (05:00-09:00)
SHORT_ENABLED = True               # the intraday short (the engine SHORT_STRATEGY picks)
SHORT_STRATEGY = "jay_read"        # "jay_read" = Jay-read short v1.2 (jay_read_short.py, same folder) - the default
                                   # "jay_read_2" = 3.13.0 Jay-read 2 (backtest/jay_read_2/jay_read_2_short.py)
                                   # "v16"      = the parked bounce-zone + vacuum short (Kestrel 3.6.4)
JAY_READ_FILE = "jay_read_short.py"  # the Jay-read module (looked up next to this file, then in the current folder)
SQUEEZE_ENABLED = True             # 3.9.0: the max squeeze short next to the Jay-read short (one position per stock)
MIN_SHORT_PRICE = 1.00             # 3.15: no short signal under this price - as the live bot (SHORT_MIN_PRICE): TradeZero
                                   # rejects shorts under $1 (3.13.1: was 0.50, the live short scanner's minimum)
SQUEEZE_FILE = "max_squeeze_short.py"  # the max squeeze module (next to this file, then in the current folder)
MAX_RISK_PER_TRADE_USD = None      # Jay-read shorts: shares cut so (stop - entry) x shares <= this $ (the app's setting,
                                   # None there too since 3.7.2).
                                   # None = off (the verified numbers above are without a cap)
LONG_ACCOUNT_PCT = 20.0            # each long = this % of the balance ...
LONG_MAX_POSITION_USD = 10_000.0   # ... but never more than this (premarket candles are thin: keep the losses small)
SHORT_ACCOUNT_PCT = 20.0           # each short = this % of the balance ...
SHORT_MAX_POSITION_USD = 50_000.0  # ... but never more than this (intraday gappers trade millions of shares)
LONG_DAILY_LOSS_PCT_OF_POSITION = 50.0  # no new longs once the day's realized long loss reaches this % of the long
                                   # position size at the start of the day (the live bot's daily stop: $1,000 on a $2,000
                                   # position, $5,000 at the $10,000 cap). 0 = off

# =============================================================================
# SHORT STRATEGY PARAMETERS  (lh_short_backtester.py v16 - unchanged)
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
VAC_REQUIRE_GAP = True             # only on days that opened MIN_GAP_PCT+ above the prior close (same as the bounce)
VAC_USE_MIN_VOLUME = True          # wait for MIN_DAY_VOLUME shares like the bounce
VAC_MAX_TRADES_PER_DAY = 3
VAC_STAND_DOWN_AFTER_DIP = True    # once the top dipped MIN_DIP_PCT it is a bounce setup: clear the vacuum trap until a new high

# Liquidity and costs
MIN_DAY_VOLUME = 10_000_000        # shares traded today (premarket included) before the first short; 0 = off
LOCATE_FEE_PCT = 3.0               # locate cost per short, % of the entry value (paid win or lose); 0 = ignore fees
SLIPPAGE_PCT = 0.10                # per fill
RISK_PER_TRADE_USD = 100.0         # the engine's own share count (not used: the ACCOUNT above sizes every short)

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
# PREMARKET LONG STRATEGY PARAMETERS  (lh_long_premarket.py 1.6 - unchanged, LONG_ prefix)
# =============================================================================
LONG_DATA_START = "04:00"          # today's candles from here feed VWAP / EMA / RVOL / the 10-minute velocity look-back
LONG_SESSION_START = "05:00"       # discovery + entries only in this window (ET), like the backtest
LONG_SESSION_END = "09:00"
LONG_MIN_GAP_PCT = 0.30            # discovery / watch threshold: prior close +30%
LONG_MIN_ENTRY_PRICE = 0.50
LONG_MAX_ENTRY_PRICE = 25.00
LONG_FRESH_ENTRY_SEC = 1200        # entries only in the first 20 minutes after discovery
LONG_WARMUP_ROWS = 20              # the day's first 20 ten-second candles are history only (the backtest's range(20, ...))
LONG_MAX_EXT_FROM_OPEN = 3.00      # no entry more than 300% above the 05:00 open (first 10-s candle of the window)

LONG_EMA_PERIOD = 9
LONG_MACRO_EMA_PERIOD = 54
LONG_SLOPE_LOOKBACK = 12           # EMA-54 slope = EMA54 now - EMA54 12 minutes ago
LONG_RVOL_LEN = 10                 # RVOL = this minute's volume / average of the previous (up to) 10 minutes
                                   # (no earlier minute or no volume before = 999, like the backtest)

LONG_MOM_SURGE_PCT = 0.03          # momentum chase: 1-min candle at least +3% open -> close
LONG_MOM_RVOL = 1.5                # ... with RVOL at least this (1.4 and your backtest: 2.0)
LONG_MOM_MIN_VOLUME = 20_000       # ... with at least this many shares in that minute
LONG_MOM_STRONG_CLOSE = 0.40       # ... closing in the top 40% of its range (1.4 and your backtest: 0.25)

LONG_BULL_FLAG_ENABLED = False     # v1.2: momentum chase only (the backtest). True = the 1.1 bull flag as well

LONG_FLAG_LOOKBACK = 5             # bull flag: peak inside the last 5 completed minutes (lagged one minute)
LONG_FLAG_POLE_BACK = 2            # pole starts 2 minutes before the peak
LONG_FLAG_MIN_VELOCITY = 0.01
LONG_FLAG_MAX_DROP = 0.15          # flag may pull back at most 15% from the peak
LONG_FLAG_RVOL = 1.5
LONG_FLAG_WHEN_MOMENTUM_PENDING = False  # False = exactly your backtest (elif); True = also check the flag

LONG_VELOCITY_LOOKBACK_ROWS = 60   # "10 minutes before discovery" = 60 ten-second candles back (the backtest's rows)
LONG_VELOCITY_MAX_GAIN = 0.15      # up <= 15% back then = vertical surge -> momentum chase armed
LONG_SCANNER_DELAY_SEC = 30        # no entry in the first 30 s after discovery
LONG_BACKSIDE_LOCK_PCT = 0.20      # close 20% under the session high = backside: no entries until a new high

LONG_MIN_RISK_PCT = 0.01
LONG_MAX_RISK_PCT = 0.10
LONG_TARGET_MULT = 2.0
LONG_TARGET_MULT_STRONG = 3.0
LONG_STRONG_RVOL = 5.0
LONG_MAX_HOLD_MIN_WITHOUT_PROFIT = 5
LONG_TRAIL_WINDOW = (70, 20)       # trail = lowest low of the 10-s candles that started 70..20 s before the
                                   # current candle (= the old rolling(6).min().shift(1) on the previous candle)

LONG_MAX_TRADES_PER_SYMBOL = 3
LONG_MAX_CONSECUTIVE_LOSSES = 3
# Size: LONG_ACCOUNT_PCT of the balance, max LONG_MAX_POSITION_USD (ACCOUNT section above). The per-stock loss limit
# is % of that position: $10,000 balance -> $2,000 position -> $500 per stock; at the $10,000 maximum -> $2,500.
# 3.8.0: no max loss per trade (the 12.5% rule is removed - the stop is at most LONG_MAX_RISK_PCT = 10%; it never cut
# a trade, the results are the same).
LONG_MAX_LOSS_PER_STOCK_PCT = 25.0 # % of the position: the stock is done for the day once its losses today reach this
LONG_REPLAY_EQUITY = 10_000.0      # the engine's default equity (the combined account re-sizes every long)
LONG_TICK = 0.01
LONG_SLIPPAGE_PCT = 0.005          # 0.5% against you on every long fill (your long backtest)
LONG_STOP_EARLY_PCT = 1.0           # 3.10: the hard stop sells when the price trades this % ABOVE the stop (stop x 1.01) - a
                                   # fast premarket fade slipped 3.5% under the stop (BIRD 23 Oct: stop 3.10, sold 2.99).
                                   # Hard stop only (before the half is sold); the trail is unchanged. 0 = at the stop.
                                   # Backtest (584 days, long-only account): $101,769 vs $102,972 at the stop (5 more
                                   # stop-outs, every stop sale 1% better).

# Output
OUTPUT_DIR = "combined_backtests"
OPEN_BROWSER = True
SHOW_SKIPPED = True                # plot skipped short signals as grey x with the reason
PLOT_FROM = "04:00"                # chart window
PLOT_TO = "16:30"

# =============================================================================
# CODE
# =============================================================================
# ----------------------------------------------------------------------------- short engine
# lh_short_backtester.py v16 - verbatim
import math
import os
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import date as ddate, datetime, time as dtime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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



# =============================================================================
# PREMARKET LONG ENGINE - lh_long_premarket.py 1.6, verbatim (settings / Position / ET renamed, see the top)
# =============================================================================
from collections import deque
from datetime import timezone

try:
    from zoneinfo import ZoneInfo
    ET_ZONE = ZoneInfo("America/New_York")
except Exception:                                   # no tz database: pytz ships with pandas
    import pytz
    ET_ZONE = pytz.timezone("America/New_York")

# Result labels (same text as the old script, plus the 09:30 close)
STOP_OUT = "STOP OUT"
BREAKEVEN_OUT = "BREAKEVEN OUT"
TIME_STOP = "TIME STOP (DEAD MONEY)"
PARTIAL = "PARTIAL SCALE OUT"
TRAIL_OUT = "TRAILING STOP OUT"
OPEN_FLAT = "MARKET OPEN FLAT"
MOMENTUM = "1m MOMENTUM CHASE"
BULL_FLAG = "1m BULL FLAG"

NAN = float("nan")


def isnan(x):
    return x is None or x != x


def hms_secs(s):
    p = [int(x) for x in str(s).split(":")]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


SESSION_START_S = hms_secs(LONG_SESSION_START)
SESSION_END_S = hms_secs(LONG_SESSION_END)


def et_dt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(ET_ZONE)


def et_secs(ts):
    d = et_dt(ts)
    return d.hour * 3600 + d.minute * 60 + d.second


def et_hms(ts):
    return et_dt(ts).strftime("%H:%M:%S")


def in_session(ts):
    return SESSION_START_S <= et_secs(ts) < SESSION_END_S


def day_start_ts(ts, hhmm=LONG_DATA_START):
    """Epoch of hhmm ET on the ET calendar day of ts."""
    d = et_dt(ts)
    s = hms_secs(hhmm)
    start = d.replace(hour=s // 3600, minute=s % 3600 // 60, second=0, microsecond=0)
    return int(start.timestamp())


def position_usd(equity):
    """$ size of one long: LONG_ACCOUNT_PCT of the equity, at most LONG_MAX_POSITION_USD."""
    eq = equity if equity and equity > 0 else LONG_REPLAY_EQUITY
    return min(eq * LONG_ACCOUNT_PCT / 100.0, LONG_MAX_POSITION_USD)


def stock_loss_limit(equity):
    """$ a stock may lose today before it is done: LONG_MAX_LOSS_PER_STOCK_PCT of the position (LONG_ACCOUNT_PCT of the
    equity, max LONG_MAX_POSITION_USD). $10,000 -> $2,000 position -> $500; $50,000+ -> $10,000 -> $2,500."""
    return position_usd(equity) * LONG_MAX_LOSS_PER_STOCK_PCT / 100.0


def clamp_risk(entry, stop):
    return max(entry * LONG_MIN_RISK_PCT, min(entry * LONG_MAX_RISK_PCT, entry - stop))


# =============================================================================
# DATA OBJECTS
# =============================================================================
class Bar:
    """t = start of the candle, epoch seconds (UTC)."""
    __slots__ = ("t", "o", "h", "l", "c", "v")

    def __init__(self, t, o, h, l, c, v):
        self.t, self.o, self.h, self.l, self.c, self.v = int(t), float(o), float(h), float(l), float(c), float(v)

    def __repr__(self):
        return f"Bar({et_hms(self.t)} o{self.o:.4g} h{self.h:.4g} l{self.l:.4g} c{self.c:.4g} v{self.v:.0f})"


class MinuteState:
    """Macro values of one completed 1-minute candle; used during the FOLLOWING minute (for_t)."""
    __slots__ = ("bar_t", "for_t", "close", "ema9", "slope", "vwap", "rvol", "mom_trigger", "mom_stop",
                 "flag_trigger", "flag_low", "flag_drop", "flag_velocity")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k, NAN))


class LongPosition:
    def __init__(self, strategy, entry, stop, target, risk, shares, t):
        self.strategy = strategy
        self.entry, self.stop, self.target, self.risk = entry, stop, target, risk
        self.initial = self.shares = int(shares)
        self.t = t                          # fill time
        self.bar_t = int(t) // 10 * 10      # start of the 10-s candle it filled in
        self.partial = False
        self.trailing = 0.0
        self.trail_bar_t = 0                # start of the 10-s candle the half was sold in (live trail check after it)
        self.realized = 0.0


class DayState:
    """Everything about one symbol that must survive a re-subscribe on the same day."""

    def __init__(self, sym):
        self.sym = sym
        self.discovered_t = None
        self.velocity_gain = None
        self.momentum_allowed = False
        self.session_high = 0.0
        self.backside_locked = False
        self.trades_taken = 0
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.halted = False
        self.halt_reason = ""
        self.pos = None
        self.no_entry_before = 0
        self.legs = []
        self.loss_limit = stock_loss_limit(LONG_REPLAY_EQUITY)   # $ per stock today (set from the equity at each entry)

    def check_halts(self):
        if self.halted:
            return True
        if self.daily_pnl <= -self.loss_limit:
            self.halted, self.halt_reason = True, f"loss limit ${self.loss_limit:,.0f} for this stock"
        elif self.trades_taken >= LONG_MAX_TRADES_PER_SYMBOL and self.pos is None:
            self.halted, self.halt_reason = True, f"{LONG_MAX_TRADES_PER_SYMBOL} trades"
        return self.halted


# =============================================================================
# ENGINE
# =============================================================================
class LongEngine:
    def __init__(self, sym, prior_close, day=None):
        self.sym = sym
        self.pc = float(prior_close)
        self.alert = self.pc * (1.0 + LONG_MIN_GAP_PCT)
        self.day = day or DayState(sym)
        self.b1 = []                      # completed 1-minute candles (today from 04:00)
        self.vwap_hist = []               # VWAP after each 1-minute candle (charts)
        self.b10 = deque(maxlen=480)      # completed 10-second candles (look-backs)
        self.cur = None                   # 1-minute candle being built from 10-second candles
        self.ema9 = NAN
        self.macro = NAN
        self.macro_hist = deque(maxlen=LONG_SLOPE_LOOKBACK + 1)
        self.cpv = 0.0
        self.cv = 0.0
        self.ms = None                    # MinuteState of the last completed minute
        self.session_open = NAN           # open of the first 10-s candle of the entry window (05:00)
        self.rows = 0                     # live: 10-s candles (with trades) seen today, from 04:00
        self.equity = LONG_REPLAY_EQUITY       # replay sizing (live uses the TradeZero equity)
        self.last_bar_t = 0               # start of the last 10-s candle processed
        self.last_close = NAN
        self.pm_high = 0.0
        self.pm_volume = 0.0
        self.a9 = 2.0 / (LONG_EMA_PERIOD + 1)
        self.am = 2.0 / (LONG_MACRO_EMA_PERIOD + 1)

    # ---------------------------------------------------------------- 1-minute macro logic
    def _add_1m(self, bar):
        i = len(self.b1)
        self.b1.append(bar)
        self.ema9 = bar.c if isnan(self.ema9) else self.ema9 + self.a9 * (bar.c - self.ema9)
        self.macro = bar.c if isnan(self.macro) else self.macro + self.am * (bar.c - self.macro)
        self.macro_hist.append(self.macro)
        slope = self.macro_hist[-1] - self.macro_hist[0] if len(self.macro_hist) == LONG_SLOPE_LOOKBACK + 1 else NAN
        self.cpv += bar.c * bar.v
        self.cv += bar.v
        vwap = self.cpv / self.cv if self.cv > 0 else NAN
        self.vwap_hist.append(vwap)
        rvol = 999.0                                     # backtest: rolling(10, min_periods=1) of the earlier minutes
        if i >= 1:
            prev = self.b1[max(0, i - LONG_RVOL_LEN):i]
            avg = sum(b.v for b in prev) / len(prev)
            rvol = bar.v / avg if avg > 0 else 999.0
        ms = MinuteState(bar_t=bar.t, for_t=bar.t + 60, close=bar.c, ema9=self.ema9, slope=slope, vwap=vwap, rvol=rvol)
        # momentum chase (this minute): +3% green, RVOL LONG_MOM_RVOL+, 20k+ shares, close in the top LONG_MOM_STRONG_CLOSE of the range
        rng = bar.h - bar.l
        strong = rng > 0 and (bar.h - bar.c) / rng <= LONG_MOM_STRONG_CLOSE
        if (bar.o > 0 and (bar.c - bar.o) / bar.o >= LONG_MOM_SURGE_PCT and rvol >= LONG_MOM_RVOL and bar.v >= LONG_MOM_MIN_VOLUME
                and strong):
            ms.mom_trigger, ms.mom_stop = bar.h + LONG_TICK, bar.l - LONG_TICK
        # bull flag (window = the 5 minutes BEFORE this one) - off in v1.2
        if LONG_BULL_FLAG_ENABLED and i >= LONG_FLAG_LOOKBACK:
            w = self.b1[i - LONG_FLAG_LOOKBACK:i]
            highs = [b.h for b in w]
            peak = max(highs)
            rel = highs.index(peak)
            since = (LONG_FLAG_LOOKBACK - 1) - rel
            if 1 <= since <= LONG_FLAG_LOOKBACK - 1:
                pole_open = self.b1[max(0, (i - LONG_FLAG_LOOKBACK) + rel - LONG_FLAG_POLE_BACK)].o
                vel = (w[rel].c - pole_open) / pole_open if pole_open > 0 else NAN
                if not isnan(vel) and vel >= LONG_FLAG_MIN_VELOCITY:
                    f_low = min(b.l for b in w[rel + 1:])
                    ms.flag_velocity = vel
                    ms.flag_drop = (peak - f_low) / peak
                    ms.flag_trigger = peak + LONG_TICK
                    ms.flag_low = f_low
        self.ms = ms

    def _roll_minute(self, t):
        """A candle of a later minute arrived: the minute being built is complete."""
        if self.cur is not None and self.cur.t < t // 60 * 60:
            done, self.cur = self.cur, None
            self._add_1m(done)

    def close_minute(self, minute_t):
        """Live: the clock passed the end of minute_t (its last 5-s bar arrived) - finalize it now."""
        if self.cur is not None and self.cur.t <= minute_t:
            done, self.cur = self.cur, None
            self._add_1m(done)

    def roll_clock(self, now, grace=3.0):
        """Live fallback when the minute's last bars had no trades."""
        if self.cur is not None and now >= self.cur.t + 60 + grace:
            done, self.cur = self.cur, None
            self._add_1m(done)

    def _push_10s(self, bar):
        self.b10.append(bar)
        self.last_bar_t = bar.t
        self.last_close = bar.c
        self.pm_high = max(self.pm_high, bar.h)
        self.pm_volume += bar.v
        m = bar.t // 60 * 60
        if self.cur is None:
            self.cur = Bar(m, bar.o, bar.h, bar.l, bar.c, bar.v)
        else:
            c = self.cur
            c.h, c.l, c.c, c.v = max(c.h, bar.h), min(c.l, bar.l), bar.c, c.v + bar.v

    # ---------------------------------------------------------------- day logic
    def _price_before(self, t):
        """Open of the latest candle that started at or before t (10-s first, then 1-min, then the earliest)."""
        best = None
        for b in self.b10:
            if b.t <= t:
                best = b
            else:
                break
        if best is not None:
            return best.o
        for b in self.b1:
            if b.t <= t:
                best = b
            else:
                break
        if best is not None:
            return best.o
        first = self.b10[0] if self.b10 else (self.b1[0] if self.b1 else None)
        return first.o if first is not None else NAN

    def _velocity_ref(self, t):
        """Open of the 10-s candle 60 candles (with trades) before t, like the backtest's df.iloc[i - 60]; the first
        candle of the day when there are fewer. Without enough 10-s history: the 1-minute candles before it."""
        rows = [b for b in self.b10 if b.t < t]
        if len(rows) >= LONG_VELOCITY_LOOKBACK_ROWS:
            return rows[-LONG_VELOCITY_LOOKBACK_ROWS].o
        first10 = rows[0].t if rows else t
        mins = [b for b in self.b1 if b.t < first10 // 60 * 60]
        if mins:
            k = -(-(LONG_VELOCITY_LOOKBACK_ROWS - len(rows)) // 6)
            return mins[max(0, len(mins) - k)].o
        return rows[0].o if rows else NAN

    def _set_velocity(self, t):
        d = self.day
        then = self._velocity_ref(t)
        d.velocity_gain = (then - self.pc) / self.pc if not isnan(then) and self.pc > 0 else NAN
        d.momentum_allowed = not isnan(d.velocity_gain) and d.velocity_gain <= LONG_VELOCITY_MAX_GAIN

    def _discover(self, t):
        d = self.day
        d.discovered_t = t
        self._set_velocity(t)
        return {"type": "discovered", "t": t, "velocity_gain": d.velocity_gain, "momentum": d.momentum_allowed}

    def _session_update(self, high, close):
        d = self.day
        if high >= d.session_high:
            d.backside_locked = False
            d.session_high = high
        if d.session_high > 0 and d.pos is None and not d.backside_locked:
            if (d.session_high - close) / d.session_high >= LONG_BACKSIDE_LOCK_PCT:
                d.backside_locked = True

    def on_tick_high(self, price):
        """Live: a trade at/above the session high lifts the backside lock the moment it prints (the old script
        did it with the candle's high, then filled at that candle's open - a price live trading cannot get)."""
        d = self.day
        if d.discovered_t is not None and price >= d.session_high > 0:
            d.session_high = price
            d.backside_locked = False

    def _trail_level(self, t_cur):
        lo, hi = t_cur - LONG_TRAIL_WINDOW[0], t_cur - LONG_TRAIL_WINDOW[1]
        lows = [b.l for b in self.b10 if lo <= b.t <= hi]
        return min(lows) - LONG_TICK if lows else NAN

    def _update_trail(self, t_cur):
        p = self.day.pos
        lvl = self._trail_level(t_cur)
        if p is not None and not isnan(lvl):
            p.trailing = max(p.trailing, lvl)

    # ---------------------------------------------------------------- entries
    def entry_signal(self, high, open_px, now):
        """Shared by live (high = open = the trade price) and replay (the 10-s candle). None = no entry."""
        d = self.day
        if d.check_halts() or d.pos is not None or d.discovered_t is None:
            return None
        if now - d.discovered_t < LONG_SCANNER_DELAY_SEC or d.backside_locked or not in_session(now):
            return None
        if now - d.discovered_t > LONG_FRESH_ENTRY_SEC:
            return None                                   # only in the first 20 minutes after discovery
        if now < d.no_entry_before:
            return None
        ms = self.ms
        if ms is None or ms.for_t != int(now) // 60 * 60:
            return None                                   # previous minute had no trades (old script: NaN)
        if isnan(ms.vwap) or ms.close < ms.vwap:
            return None
        trigger = stop = None
        name = ""
        mom_pending = d.momentum_allowed and not isnan(ms.mom_trigger)
        if mom_pending and high >= ms.mom_trigger:
            trigger, stop, name = ms.mom_trigger, ms.mom_stop, MOMENTUM
        if trigger is None and LONG_BULL_FLAG_ENABLED and (not mom_pending or LONG_FLAG_WHEN_MOMENTUM_PENDING):
            if (not isnan(ms.flag_trigger) and ms.flag_drop <= LONG_FLAG_MAX_DROP and not isnan(ms.slope) and ms.slope > 0
                    and not isnan(ms.rvol) and ms.rvol >= LONG_FLAG_RVOL and high >= ms.flag_trigger):
                trigger, stop, name = ms.flag_trigger, ms.flag_low - LONG_TICK, BULL_FLAG
        if trigger is None or not (LONG_MIN_ENTRY_PRICE <= trigger <= LONG_MAX_ENTRY_PRICE):
            return None
        if trigger < self.pc * (1.0 + LONG_MIN_GAP_PCT):
            return None                                   # the trigger itself must be +30% up
        if self.too_extended(max(trigger, open_px) * (1 + LONG_SLIPPAGE_PCT)):
            return None
        mult = LONG_TARGET_MULT_STRONG if (not isnan(ms.rvol) and ms.rvol >= LONG_STRONG_RVOL and ms.close > ms.ema9) else LONG_TARGET_MULT
        return {"strategy": name, "trigger": trigger, "stop": stop, "mult": mult, "ref": max(trigger, open_px),
                "key": (name, ms.bar_t), "rvol": ms.rvol, "vwap": ms.vwap, "minute": ms.for_t}

    def too_extended(self, price):
        """More than LONG_MAX_EXT_FROM_OPEN (300%) above the open of the entry window = no entry."""
        so = self.session_open
        return not isnan(so) and so > 0 and (price - so) / so > LONG_MAX_EXT_FROM_OPEN

    @staticmethod
    def size_for(sig, price, equity):
        """LONG_ACCOUNT_PCT of the account equity (compounding), max LONG_MAX_POSITION_USD. Even share count; under 2
        shares = no trade. (3.8.0: no cut for the stop distance - the stop is at most LONG_MAX_RISK_PCT.)"""
        if price <= 0 or not equity or equity <= 0:
            return 0
        return max(0, int(position_usd(equity) / price) // 2 * 2)

    def open_position(self, sig, avg, shares, t):
        risk = clamp_risk(avg, sig["stop"])
        p = LongPosition(sig["strategy"], avg, avg - risk, avg + risk * sig["mult"], risk, shares, t)
        self.day.pos = p
        self.day.trades_taken += 1
        return p

    # ---------------------------------------------------------------- exits
    def close_leg(self, shares, price, reason, t):
        """Book an exit of `shares` at `price`. Returns the leg (dict)."""
        d, p = self.day, self.day.pos
        shares = int(min(shares, p.shares))
        pnl = (price - p.entry) * shares
        d.daily_pnl += pnl
        p.realized += pnl
        p.shares -= shares
        closed = p.shares <= 0
        if reason == PARTIAL and not p.partial:
            p.partial = True
            d.consecutive_losses = 0
            p.trailing = p.entry
            p.trail_bar_t = int(t) // 10 * 10
        elif reason == STOP_OUT and closed:              # one stop-out per trade, even if it filled in pieces
            d.consecutive_losses += 1
            if d.consecutive_losses >= LONG_MAX_CONSECUTIVE_LOSSES:
                d.halted, d.halt_reason = True, f"{LONG_MAX_CONSECUTIVE_LOSSES} stop-outs in a row"
        leg = {"sym": self.sym, "strategy": p.strategy, "entry_t": p.t, "entry": p.entry, "exit_t": t, "exit": price,
               "shares": shares, "reason": reason, "pnl": pnl, "trade_pnl": p.realized, "closed": closed,
               "stop": p.stop, "target": p.target, "risk": p.risk, "left": max(p.shares, 0), "initial": p.initial}
        d.legs.append(leg)
        if closed:
            d.pos = None
            d.no_entry_before = int(t) // 10 * 10 + 10
        return leg

    def partial_qty(self):
        p = self.day.pos
        if p is None:
            return 0
        q = p.initial // 2
        return min(q, p.shares - 1) if p.shares > 1 else 0

    def exit_on_price(self, price, now):
        """Live tick check -> (reason, shares) or None."""
        p = self.day.pos
        if p is None or p.shares <= 0:
            return None
        if not p.partial and price <= p.stop * (1 + LONG_STOP_EARLY_PCT / 100.0):
            return STOP_OUT, p.shares                    # after the half is sold the trail (from breakeven) decides
        if not p.partial:
            if price >= p.target:
                q = self.partial_qty()
                return (PARTIAL, q) if q > 0 else (PARTIAL, p.shares)
        elif p.trailing > 0 and price <= p.trailing:
            return TRAIL_OUT, p.shares
        return None

    # ---------------------------------------------------------------- live 10-second candle
    def on_bar_10s(self, bar):
        """Live / seeding: a 10-second candle COMPLETED. Returns events, incl. exit requests decided on the
        candle (time stop, stop / trail touched by the candle's low as a backup to the ticks)."""
        self._roll_minute(bar.t)
        warm = self.rows >= LONG_WARMUP_ROWS                  # the backtest skips the day's first 20 ten-second candles
        self.rows += 1
        if warm and isnan(self.session_open) and in_session(bar.t):
            self.session_open = bar.o
        events = []
        d = self.day
        d.check_halts()
        if d.discovered_t is None:
            if warm and in_session(bar.t) and bar.h >= self.alert:
                events.append(self._discover(bar.t))
        else:
            self._session_update(bar.h, bar.c)
            p = d.pos
            if p is not None and p.shares > 0 and bar.t >= p.bar_t:
                # the candle the buy filled in: its low may be from BEFORE the fill, so only the ticks after the fill
                # count for the stop there (exit_on_price); from the next candle on, the candle's low is a backup
                if not p.partial and bar.l <= p.stop * (1 + LONG_STOP_EARLY_PCT / 100.0) and bar.t > p.bar_t:
                    events.append({"type": "exit", "reason": STOP_OUT, "shares": p.shares})
                elif (bar.t - p.bar_t >= LONG_MAX_HOLD_MIN_WITHOUT_PROFIT * 60 and not p.partial
                      and bar.h < p.entry + p.risk):
                    events.append({"type": "exit", "reason": TIME_STOP, "shares": p.shares})
                elif p.partial and p.trailing > 0 and bar.l <= p.trailing and bar.t > p.trail_bar_t:
                    events.append({"type": "exit", "reason": TRAIL_OUT, "shares": p.shares})
        self._push_10s(bar)
        if d.pos is not None and d.pos.partial:
            self._update_trail(bar.t + 10)               # trail for the NEXT candle
        if bar.t % 60 == 50:
            self.close_minute(bar.t // 60 * 60)
        return events

    def seed(self, bars1m, bars10, now):
        """Rebuild today's state from history: 1-minute candles up to 2 minutes ago, then the 10-second
        candles after that (they also fill the look-back history). The day's counters are kept.
        Like the backtest, the first LONG_WARMUP_ROWS 10-second candles of the day (with trades, from 04:00) are history
        only: no discovery and no 05:00 open from them."""
        d = self.day
        d.session_high, d.backside_locked = 0.0, False
        cut = int(now) // 60 * 60 - 60
        start = day_start_ts(now)
        h10 = [b for b in bars10 if start <= b.t < cut]             # 10-s history before the cut
        first_min = (h10[0].t // 60 * 60) if h10 else cut
        n_pre = len([b for b in bars1m if start <= b.t < min(first_min, cut)])   # minutes before the 10-s history
        by_min = {}
        for k, x in enumerate(h10):
            by_min.setdefault(x.t // 60 * 60, []).append((n_pre + k, x))    # (row of the day, candle)
        disc_min = None if d.discovered_t is None else d.discovered_t // 60 * 60
        seed_disc = False
        n_min = 0
        for b in bars1m:
            if b.t < start or b.t >= cut:
                continue
            disc_t = None
            if b.t < first_min:                          # before the 10-s history: rows counted 1 per minute
                if n_min >= LONG_WARMUP_ROWS and in_session(b.t):
                    if isnan(self.session_open):
                        self.session_open = b.o
                    if b.h >= self.alert:
                        disc_t = b.t
                n_min += 1
            else:                                        # the minute's 10-s candles decide (exact rows)
                for row, x in by_min.get(b.t, []):
                    if row >= LONG_WARMUP_ROWS and in_session(x.t):
                        if isnan(self.session_open):
                            self.session_open = x.o
                        if disc_t is None and x.h >= self.alert:
                            disc_t = x.t
            self._add_1m(b)
            self.pm_high = max(self.pm_high, b.h)
            self.pm_volume += b.v
            self.last_close = b.c
            if d.discovered_t is None:
                if disc_t is not None:
                    self._discover(disc_t)
                    disc_min, seed_disc = b.t, True
            elif b.t > disc_min:
                self._session_update(b.h, b.c)
        for b in h10:
            self.b10.append(b)                           # look-back history only (minute already counted)
        self.rows = n_pre + len(h10)
        if seed_disc:                                    # velocity again, now with the 10-s candles before it
            self._set_velocity(d.discovered_t)
        for b in bars10:
            if b.t < cut:
                continue
            if b.t + 10 > now:
                break                                    # the candle still forming
            self.on_bar_10s(b)
        self.last_bar_t = max(self.last_bar_t, self.b10[-1].t if self.b10 else 0)

    # ---------------------------------------------------------------- replay (backtest semantics)
    def replay_bar(self, bar, slip=LONG_SLIPPAGE_PCT, logic=True):
        """One 10-second candle exactly like the old process_backtest loop."""
        self._roll_minute(bar.t)
        legs = []
        if logic:
            legs = self._candle(bar, slip)
        self._push_10s(bar)
        return legs

    def _candle(self, bar, slip):
        d, t = self.day, bar.t
        valid = in_session(t)
        if valid and isnan(self.session_open):
            self.session_open = bar.o
        if d.halted:
            return []
        if d.check_halts():
            return []
        if d.discovered_t is None and valid:
            if bar.h >= self.alert:
                self._discover(t)
                return []
        if d.discovered_t is None:
            return []
        synced = t - d.discovered_t >= LONG_SCANNER_DELAY_SEC
        self._session_update(bar.h, bar.c)
        p = d.pos
        if p is not None:
            trig = p.stop * (1 + LONG_STOP_EARLY_PCT / 100.0)
            if not p.partial and bar.l <= trig:
                return [self.close_leg(p.shares, min(trig, bar.o) * (1 - slip), STOP_OUT, t)]
            if t - p.bar_t >= LONG_MAX_HOLD_MIN_WITHOUT_PROFIT * 60 and not p.partial and bar.h < p.entry + p.risk:
                return [self.close_leg(p.shares, bar.o * (1 - slip), TIME_STOP, t)]
            if not p.partial:
                if bar.h >= p.target:
                    return [self.close_leg(p.initial // 2, p.target * (1 - slip), PARTIAL, t)]
            else:
                self._update_trail(t)
                if bar.l <= p.trailing:
                    return [self.close_leg(p.shares, min(p.trailing, bar.o) * (1 - slip), TRAIL_OUT, t)]
            return []
        if valid and synced and not d.backside_locked:
            sig = self.entry_signal(bar.h, bar.o, t)
            if sig:
                price = max(sig["trigger"], bar.o) * (1 + slip)
                shares = self.size_for(sig, price, self.equity)
                d.loss_limit = stock_loss_limit(self.equity)
                if shares >= 2:
                    self.open_position(sig, price, shares, t)
                    d.pos.bar_t = t
        return []


def replay_day(sym, prior_close, bars10, slip=LONG_SLIPPAGE_PCT, warmup=LONG_WARMUP_ROWS, equity=None):
    """Run a whole premarket through the engine. Returns (legs, engine). Anything open at the end is closed
    at the last candle's close (the live bot sells from 09:00). equity = account size for the 20%."""
    eng = LongEngine(sym, prior_close)
    if equity:
        eng.equity = float(equity)
    legs = []
    for k, b in enumerate(bars10):
        legs += eng.replay_bar(b, slip, logic=k >= warmup)
    p = eng.day.pos
    if p is not None and p.shares > 0 and bars10:
        last = bars10[-1]
        legs.append(eng.close_leg(p.shares, last.c * (1 - slip), OPEN_FLAT, last.t + 10))
    return legs, eng


def legs_table(legs):
    rows = []
    for g in legs:
        rows.append({"Ticker": g["sym"], "Setup": g["strategy"], "Entry Time": et_hms(g["entry_t"]),
                     "Entry Price": round(g["entry"], 4), "Exit Time": et_hms(g["exit_t"]),
                     "Exit Price": round(g["exit"], 4), "Shares": g["shares"], "Result": g["reason"],
                     "Net PnL ($)": round(g["pnl"], 2)})
    return rows



# =============================================================================
# COMBINED BACKTEST: data, account, report, chart (no strategy logic below this line)
# =============================================================================
LONG_SIDE, SHORT_SIDE = "LONG", "SHORT"


def read_bars_csv(path):
    """time,open,high,low,close,volume[,prior_close] (time in ET) -> (df with tz-aware ET time, prior close)."""
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]
    tcol = next((c for c in ("time", "datetime", "date", "timestamp") if c in raw.columns), None)
    if tcol is None:
        raise RuntimeError(f"{path}: needs a time column (time/datetime/date/timestamp)")
    ts = pd.to_datetime(raw[tcol])
    ts = ts.dt.tz_localize(ET) if ts.dt.tz is None else ts.dt.tz_convert(ET)
    raw["time"] = ts
    pc = None
    if "prior_close" in raw.columns and raw["prior_close"].notna().any():
        pc = float(raw["prior_close"].dropna().iloc[0])
    return raw[["time", "open", "high", "low", "close", "volume"]], pc


def clean_bars(df, day, before=None):
    """The short backtester's cleaning: that ET day only, sorted, no duplicates, numbers only."""
    df = df[df["time"].dt.date == day].copy()
    if before is not None:
        df = df[df["time"].dt.time < before]
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).clip(lower=0)
    return df.reset_index(drop=True)


def bars10_from_df(df10):
    return [Bar(int(r.time.timestamp()), r.open, r.high, r.low, r.close, r.volume) for r in df10.itertuples()]


def rebuild_10s(df1):
    """10-second candles from the 1-minute bars before 09:00 (minutes with trades): each minute goes
    open -> low -> high -> close (green) or open -> high -> low -> close (red) in six 10-second steps."""
    end = _t(LONG_SESSION_END)
    out = []
    for r in df1.itertuples():
        if r.time.time() >= end or not r.volume > 0:
            continue
        o, h, l, c, v = float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)
        way = [o, l, l, h, h, c, c] if c >= o else [o, h, h, l, l, c, c]
        t0 = int(r.time.timestamp())
        for k in range(6):
            a, b = way[k], way[k + 1]
            out.append(Bar(t0 + 10 * k, a, max(a, b), min(a, b), b, v / 6.0))
    return out


class MissingFromVault(RuntimeError):
    """The ticker-day is not in the vault (or stored there as no_data / no_contract / error): skipped, not downloaded."""


def open_vault(path=None):
    """The IB data vault (VAULT_DB, read through lh_vault_bars.py next to this file)."""
    return vault_bars().open_vault(path or VAULT_DB, near=__file__)


def vault_bars():
    """lh_vault_bars.py (next to this file): how the backtesters read the vault."""
    mod = sys.modules.get("lh_vault_bars")
    if mod is None:
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, "lh_vault_bars.py"), "lh_vault_bars.py"):
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location("lh_vault_bars", p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["lh_vault_bars"] = mod
                spec.loader.exec_module(mod)
                break
        else:
            raise RuntimeError(f"lh_vault_bars.py not found - keep it next to {os.path.basename(__file__)}")
    return mod


def load_day(ticker, day, vault=None, need_10s=True, csv_1m=None, csv_10s=None):
    """Bars for one ticker-day.
    1-minute (+ prior close): the csv_1m file (one-off csv mode), else the vault. Not in the vault (or stored as
    no_data / no_contract / error) -> MissingFromVault: the day is skipped, nothing is downloaded.
    10-second (long): the csv_10s file, else the vault's 10-second bars (LONG_BARS = "vault"); "rebuild", or no
    10-second bars in the vault for that day = rebuilt from the 1-minute bars (noted "rebuilt" in src10).
    Returns dict(df1, pc, bars10, src1, src10, rebuilt)."""
    df10 = None
    row = {}
    if csv_1m:
        df1, pc = read_bars_csv(csv_1m)
        src1 = "csv"
        if csv_10s:
            df10, _ = read_bars_csv(csv_10s)
    else:
        if vault is None:
            raise RuntimeError("no vault and no CSV_PATH: set VAULT_DB (or CSV_PATH for one day from a file)")
        df1, pc, df10, row, why = vault_bars().load(vault, ticker, day)
        if df1 is None:
            raise MissingFromVault(why)
        src1 = "vault"
    df1 = clean_bars(df1, day)
    if df1.empty:
        raise RuntimeError(f"No bars for {ticker} on {day}")
    if PRIOR_CLOSE_OVERRIDE is not None:
        pc = float(PRIOR_CLOSE_OVERRIDE)

    bars10, src10, rebuilt = [], "", False
    if need_10s:
        mode = str(LONG_BARS).lower()
        use10 = df10 is not None and (csv_1m or mode != "rebuild")      # a CSV_10S_PATH file is always used
        if use10:
            df10 = clean_bars(df10, day, before=_t(LONG_SESSION_END))
        if use10 and not df10.empty:
            bars10 = bars10_from_df(df10)
            src10 = "csv 10 s" if csv_1m else "vault 10 s"
        else:
            bars10, rebuilt = rebuild_10s(df1), True
            why = ("LONG_BARS = rebuild" if mode == "rebuild" else "no 10-second CSV" if csv_1m
                   else vault_bars().ten_sec_note(row))
            src10 = f"rebuilt from 1 min ({why})"
    return {"df1": df1, "pc": pc, "bars10": bars10, "src1": src1, "src10": src10, "rebuilt": rebuilt}


# -----------------------------------------------------------------------------
# One ticker-day through both engines -> trades (sized later by the account)
# -----------------------------------------------------------------------------
def run_long(ticker, prior_close, bars10):
    """The long engine over the premarket. The engine sizes at the LONG_MAX_POSITION_USD reference only to make its
    per-stock decisions (loss limits are % of the position); the account re-sizes every trade from the balance."""
    if not (LONG_ENABLED and bars10 and prior_close):
        return [], None
    ref_equity = LONG_MAX_POSITION_USD * 100.0 / LONG_ACCOUNT_PCT
    return replay_day(ticker, prior_close, bars10, equity=ref_equity)


def long_trades(ticker, day, legs):
    out = []
    for g in legs:
        if not out or g["entry_t"] != out[-1]["entry_ts"]:
            out.append({"side": LONG_SIDE, "ticker": ticker, "date": str(day), "setup": g["strategy"],
                        "entry_ts": int(g["entry_t"]), "entry": float(g["entry"]), "stop": float(g["stop"]),
                        "target": float(g["target"]), "risk_ps": float(g["risk"]), "legs": [], "note": ""})
        out[-1]["legs"].append({"ts": int(g["exit_t"]), "px": float(g["exit"]), "frac": g["shares"] / g["initial"],
                                "reason": g["reason"]})
    for n, tr in enumerate(out, 1):
        tr["n"] = n
        tr["ret_pct"] = sum(lg["frac"] * (lg["px"] / tr["entry"] - 1.0) for lg in tr["legs"]) * 100.0
        tr["R"] = tr["ret_pct"] / 100.0 * tr["entry"] / tr["risk_ps"] if tr["risk_ps"] > 0 else 0.0
        half = any(lg["reason"] == PARTIAL for lg in tr["legs"][:-1])
        tr["result"] = tr["legs"][-1]["reason"] + (" (half at target)" if half else "")
        tr["risk_pct"] = tr["risk_ps"] / tr["entry"] * 100.0
    return out


def short_trades(ticker, day, bt):
    out = []
    for tr in bt.trades if bt is not None else []:
        out.append({"side": SHORT_SIDE, "ticker": ticker, "date": str(day), "setup": tr["setup"], "n": tr["n"],
                    "entry_ts": int(tr["entry_time"].timestamp()), "entry": float(tr["entry"]), "stop": float(tr["stop"]),
                    "risk_pct": float(tr["risk_pct"]), "ret_pct": float(tr["pnl_pct_net"]), "R": float(tr["R_net"]),
                    "fee_pct": float(tr["fee_pct"]), "result": tr["exit_reason"], "note": tr["note"],
                    "legs": [{"ts": int(tr["exit_time"].timestamp()), "px": float(tr["exit"]), "frac": 1.0,
                              "reason": tr["exit_reason"]}]})
    return out


# -----------------------------------------------------------------------------
# Jay-read short v1.2 + max squeeze short (SHORT_STRATEGY = "jay_read"): jay_read_short.py / max_squeeze_short.py,
# used unchanged (max_squeeze_short.ShortBook runs both on one stock, one position at a time - as the live bot)
# -----------------------------------------------------------------------------
_JR = None
_SQ = None
JR_SETUP = {"rollover": "Jay-read A rollover", "level": "Jay-read B overhead high", "squeeze": "Max squeeze short",
            "jr2_gap": "JR2 gapper", "jr2_spk": "JR2 spiker"}
JAY_READ_2_FILE = "jay_read_2_short.py"  # 3.13.0: looked up next to this file, in ../jay_read_2/, then the current folder
_JR2 = None


def jay_read_2_module():
    """3.13.0: jay_read_2_short.py (after jay_read_short). Loaded once."""
    global _JR2
    if _JR2 is None:
        jay_read_module()
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, JAY_READ_2_FILE), os.path.join(here, "..", "jay_read_2", JAY_READ_2_FILE),
                  JAY_READ_2_FILE):
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location("jay_read_2_short", p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules.setdefault("jay_read_2_short", mod)
                spec.loader.exec_module(mod)
                _JR2 = mod
                break
        else:
            raise RuntimeError(f"SHORT_STRATEGY = 'jay_read_2' needs {JAY_READ_2_FILE} (backtest/jay_read_2/)")
    return _JR2
JR_EXIT = {"STOP": "Stop", "LOCK": "Lock", "EOD": "EOD", "END": "EOD"}


def jay_read_module():
    """jay_read_short.py from the folder of this file (or the current folder). Loaded once."""
    global _JR
    if _JR is None:
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, JAY_READ_FILE), JAY_READ_FILE):
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location("jay_read_short", p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules.setdefault("jay_read_short", mod)
                spec.loader.exec_module(mod)
                _JR = mod
                break
        else:
            raise RuntimeError(f"SHORT_STRATEGY = 'jay_read' needs {JAY_READ_FILE} next to {os.path.basename(__file__)}")
    return _JR


def squeeze_module():
    """max_squeeze_short.py from the folder of this file (or the current folder). Loaded once (after jay_read_short)."""
    global _SQ
    if _SQ is None:
        jay_read_module()
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        for p in (os.path.join(here, SQUEEZE_FILE), SQUEEZE_FILE):
            if os.path.exists(p):
                spec = importlib.util.spec_from_file_location("max_squeeze_short", p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules.setdefault("max_squeeze_short", mod)
                spec.loader.exec_module(mod)
                _SQ = mod
                break
        else:
            raise RuntimeError(f"SQUEEZE_ENABLED = True needs {SQUEEZE_FILE} next to {os.path.basename(__file__)}")
    return _SQ


def run_jay_read(ticker, df1, prior_close):
    """The intraday shorts of one stock (backtest mode: the entry fills at the next open, the exits from the candles),
    fed with every closed 1-minute candle of the day: a ShortBook (Jay-read + max squeeze, one position at a time) when
    SQUEEZE_ENABLED, else one JayReadShort. Locate fee and slippage = this file's LOCATE_FEE_PCT / SLIPPAGE_PCT."""
    JR = jay_read_module()
    if str(SHORT_STRATEGY).lower() in ("jay_read_2", "jr2"):      # 3.13.0: Jay-read 2 (+ the squeeze when enabled)
        J2 = jay_read_2_module()
        parts = [J2.JayRead2Short(ticker, prior_close, LOCATE_FEE_PCT=LOCATE_FEE_PCT, SLIPPAGE_PCT=SLIPPAGE_PCT)]
        if SQUEEZE_ENABLED:
            SQ = squeeze_module()
            parts.append(SQ.MaxSqueezeShort(ticker, prior_close,
                                            cfg=SQ.settings(LOCATE_FEE_PCT=LOCATE_FEE_PCT, SLIPPAGE_PCT=SLIPPAGE_PCT)))
        s = J2.make_book(ticker, prior_close, parts) if len(parts) > 1 else parts[0]
    elif SQUEEZE_ENABLED:
        SQ = squeeze_module()
        s = SQ.ShortBook(ticker, prior_close, jr_cfg=JR.settings(LOCATE_FEE_PCT=LOCATE_FEE_PCT, SLIPPAGE_PCT=SLIPPAGE_PCT),
                         sq_cfg=SQ.settings(LOCATE_FEE_PCT=LOCATE_FEE_PCT, SLIPPAGE_PCT=SLIPPAGE_PCT))
    else:
        s = JR.JayReadShort(ticker, prior_close, LOCATE_FEE_PCT=LOCATE_FEE_PCT, SLIPPAGE_PCT=SLIPPAGE_PCT)
    for r in df1.itertuples():
        skip_cheap_signals(s, s.on_bar(r.time, r.open, r.high, r.low, r.close, r.volume), MIN_SHORT_PRICE)
    s.finish()
    return s


def skip_cheap_signals(s, events, min_px):
    """3.13.1: the live scanner only adds stocks at $0.50+ (SHORT_SCAN_MIN_PRICE): a short signal under min_px is not
    taken (the waiting entry is dropped before the next candle)."""
    for e in events:
        if e.get("type") == "SIGNAL" and min_px and float(e.get("close") or 0) < min_px:
            p = s.part(e["signal"].get("setup")) if hasattr(s, "part") else s
            p.pending = None
            p.awaiting = None


def jay_read_trades(ticker, day, s):
    out = []
    for n, t in enumerate(s.trades if s is not None else [], 1):
        if not t.closed:
            continue
        sig, risk = t.signal, t.stop0 - t.entry
        ret = t.ret
        reason = JR_EXIT.get(t.reason, t.reason)
        if sig["setup"] == "squeeze":
            note = (f"Max squeeze short: stock +{sig['up'] * 100:.0f}%, squeezed +{sig['squeeze'] * 100:.0f}% from the "
                    f"{sig['level']:.4g} swing high to {sig['top']:.4g}, red candle at the top, stop = top +"
                    f"{t.cfg['STOP_OVER_TOP_PCT']:g}%, {sig['vs_vwap'] * 100:+.0f}% vs VWAP")
        else:
            note = (f"{JR_SETUP.get(sig['setup'], sig['setup'])} ({sig['kind']}): high {sig['rth_high']:.4g}, crack "
                    f"-{sig['crack'] * 100:.0f}% to {sig['crack_low']:.4g}, {'level' if sig['setup'] == 'level' else 'overhead high'} "
                    f"{sig['ref']:.4g}, bounce {sig['bounce_high']:.4g}, {sig['vs_vwap'] * 100:+.0f}% vs VWAP"
                    + (f", lock at {t.lock_time:%H:%M}" if t.lock_time is not None else ""))
        out.append({"side": SHORT_SIDE, "ticker": ticker, "date": str(day), "setup": JR_SETUP.get(sig["setup"], sig["setup"]),
                    "n": n, "jr": True, "entry_ts": int(t.t0.timestamp()), "entry": float(t.entry), "stop": float(t.stop0),
                    "risk_pct": risk / t.entry * 100.0, "ret_pct": ret * 100.0, "R": ret * t.entry / risk if risk > 0 else 0.0,
                    "fee_pct": float(t.cfg["LOCATE_FEE_PCT"]), "result": reason, "note": note, "sig": sig,
                    "lock_ts": int(t.lock_time.timestamp()) if t.lock_time is not None else None,
                    "lock_stop": t.lock_stop,
                    "legs": [{"ts": int(t.t_end.timestamp()), "px": float(t.legs[-1][1]), "frac": 1.0, "reason": reason}]})
    return out


class DayRun:
    """Everything about one ticker-day: bars, the short engine (Jay-read or v16 Backtest), the long engine, the trades."""

    def __init__(self, ticker, day, data):
        self.ticker, self.day, self.data = ticker, day, data
        self.bt = None                  # v16 Backtest (SHORT_STRATEGY = "v16")
        self.jr = None                  # ShortBook / JayReadShort (SHORT_STRATEGY = "jay_read")
        self.legs, self.eng = [], None
        short = []
        if SHORT_ENABLED and str(SHORT_STRATEGY).lower() == "v16":
            self.bt = Backtest(ticker, day, data["df1"], data["pc"]).run()
            short = short_trades(ticker, day, self.bt)
        elif SHORT_ENABLED and data["pc"]:
            self.jr = run_jay_read(ticker, data["df1"], data["pc"])
            short = jay_read_trades(ticker, day, self.jr)
        if LONG_ENABLED:
            self.legs, self.eng = run_long(ticker, data["pc"], data["bars10"])
        self.trades = long_trades(ticker, day, self.legs) + short

    def side(self, s):
        return [t for t in self.trades if t["side"] == s]

    def pnl(self, s=None):
        return sum(t.get("pnl", 0.0) for t in self.trades if s is None or t["side"] == s)

    def long_note(self):
        """Why the long did / did not trade (for the report)."""
        if not LONG_ENABLED:
            return "long off"
        if not self.data["pc"]:
            return "no prior close"
        if not self.data["bars10"]:
            return "no premarket bars"
        eng = self.eng
        if eng is None:
            return "long not run"
        d = eng.day
        if d.discovered_t is None:
            return f"never +{LONG_MIN_GAP_PCT * 100:.0f}% ({eng.alert:.4g}) between {LONG_SESSION_START} and {LONG_SESSION_END}"
        vel = "" if isnan(d.velocity_gain) else f"{d.velocity_gain * 100:+.0f}% 10 min before"
        how = "momentum chase armed" if d.momentum_allowed else "slow grind - no momentum chase"
        return f"+{LONG_MIN_GAP_PCT * 100:.0f}% at {et_hms(d.discovered_t)} ({vel}): {how}"


def run_day(ticker, day, vault=None, csv_1m=None, csv_10s=None):
    data = load_day(ticker, day, vault=vault, need_10s=LONG_ENABLED, csv_1m=csv_1m, csv_10s=csv_10s)
    return DayRun(ticker, day, data)


# -----------------------------------------------------------------------------
# The account: one balance, both sides, compounding, in time order
# -----------------------------------------------------------------------------
def position_size(side, balance):
    if side == LONG_SIDE:
        return min(balance * LONG_ACCOUNT_PCT / 100.0, LONG_MAX_POSITION_USD)
    return min(balance * SHORT_ACCOUNT_PCT / 100.0, SHORT_MAX_POSITION_USD)


def long_daily_loss_limit(account):
    """$ of realized long loss in a day after which no new longs are opened (the live bot's daily stop):
    LONG_DAILY_LOSS_PCT_OF_POSITION of the long position size at the start of the day (LONG_ACCOUNT_PCT of the
    start-of-day balance, max LONG_MAX_POSITION_USD).  $10,000 -> $1,000;  $50,000 and more -> $5,000.  0 = no limit."""
    if not account or account <= 0:
        return 0.0
    return position_size(LONG_SIDE, account) * LONG_DAILY_LOSS_PCT_OF_POSITION / 100.0


def simulate(trades, start=None, sides=(LONG_SIDE, SHORT_SIDE), write=True):
    """Size and book every trade on one balance. A trade is sized when it is entered, from the balance of the
    exits booked before that moment (20% of it, capped per side); each exit (the long's half and the rest) is
    booked at its own time. write=True stores shares / position / pnl / balance on the trades.
    Long daily stop (like the live bot): a long entered after the day's realized long loss reached
    long_daily_loss_limit(start-of-day balance) is not taken - marked trade["skipped"] (see drop_skipped).
    Returns (final balance, max drawdown %, [(ts, balance)] after every exit)."""
    bal = peak = STARTING_BALANCE if start is None else float(start)
    ev = []
    for k, tr in enumerate(trades):
        if tr["side"] not in sides:
            continue
        ev.append((tr["entry_ts"], 1, k, -1))
        for j, lg in enumerate(tr["legs"]):          # an exit in the entry's own candle is booked after that entry
            ev.append((max(lg["ts"], tr["entry_ts"]), 0 if lg["ts"] > tr["entry_ts"] else 2, k, j))
    ev.sort()                                         # same second: other trades' exits, then entries, then same-candle exits
    book, curve, mdd = {}, [], 0.0
    sod, long_day, skipped = {}, {}, {}
    for ts, kind, k, j in ev:
        tr = trades[k]
        day = tr["date"]
        if day not in sod:
            sod[day] = bal                            # start-of-day balance: before the day's first entry / exit
        if kind == 1:
            if tr["side"] == LONG_SIDE:
                lim = long_daily_loss_limit(sod[day])
                if lim > 0 and long_day.get(day, 0.0) <= -lim:
                    skipped[k] = (f"long daily loss limit {_usd(lim, False)} reached (long today "
                                  f"{_usd(long_day[day])}) - not taken")
                    continue
            pos = position_size(tr["side"], bal)
            sh = int(pos / tr["entry"]) if tr["entry"] > 0 else 0
            if tr["side"] == LONG_SIDE:
                sh = sh // 2 * 2
            elif tr.get("jr") and MAX_RISK_PER_TRADE_USD and tr["stop"] > tr["entry"]:
                sh = min(sh, int(MAX_RISK_PER_TRADE_USD / (tr["stop"] - tr["entry"])))   # the app's $ risk cap
            book[k] = {"shares": sh, "position": sh * tr["entry"], "bal_before": bal, "pnl": 0.0, "left": sh}
            continue
        if k in skipped:
            continue
        b, lg = book[k], tr["legs"][j]
        last = j == len(tr["legs"]) - 1
        q = b["left"] if last else min(b["left"], int(round(lg["frac"] * b["shares"])))
        b["left"] -= q
        if tr["side"] == LONG_SIDE:
            pnl = q * (lg["px"] - tr["entry"])
        else:
            pnl = q * tr["entry"] * tr["ret_pct"] / 100.0      # net of the locate fee and slippage
        b["pnl"] += pnl
        bal += pnl
        if tr["side"] == LONG_SIDE:
            long_day[day] = long_day.get(day, 0.0) + pnl
        if last:
            b["bal_after"] = bal
        peak = max(peak, bal)
        mdd = min(mdd, (bal - peak) / peak * 100.0 if peak > 0 else 0.0)
        curve.append((ts, bal))
    if write:
        for k, b in book.items():
            trades[k].update(shares=b["shares"], position=b["position"], pnl=b["pnl"], bal_before=b["bal_before"],
                             bal_after=b.get("bal_after", b["bal_before"] + b["pnl"]))
        for k, why in skipped.items():
            trades[k].update(skipped=why, shares=0, position=0.0, pnl=0.0)
    return bal, mdd, curve


def drop_skipped(trades, runs=()):
    """Take the longs the daily stop skipped (simulate marks them) out of the trade lists. Returns them."""
    out = [t for t in trades if t.get("skipped")]
    if out:
        trades[:] = [t for t in trades if not t.get("skipped")]
        for r in runs:
            r.trades = [t for t in r.trades if not t.get("skipped")]
    return out


def print_skipped(skipped):
    if skipped:
        print(f"\nLong daily stop: {len(skipped)} long trade(s) not taken")
        for t in sorted(skipped, key=lambda x: x["entry_ts"]):
            print(f"  {t['date']} {t['ticker']:<6} {_et(t['entry_ts'])}  {t['skipped']}")


def account_stats(trades, sides):
    """Stats of one account run (simulate(..., write=False) on its own) - for the long-only / short-only comparison."""
    tr = [dict(t) for t in trades if t["side"] in sides]
    final, mdd, curve = simulate(tr, sides=sides)
    tr = [t for t in tr if not t.get("skipped")]
    pnls = [t["pnl"] for t in tr]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return {"trades": len(tr), "wins": len(wins), "win_rate": len(wins) / len(tr) * 100.0 if tr else 0.0,
            "net": final - STARTING_BALANCE, "final": final, "max_dd": mdd,
            "pf": (sum(wins) / -sum(losses)) if losses else (float("inf") if wins else 0.0),
            "avg_win": sum(wins) / len(wins) if wins else 0.0, "avg_loss": sum(losses) / len(losses) if losses else 0.0,
            "curve": curve, "list": tr}


# -----------------------------------------------------------------------------
# Text report
# -----------------------------------------------------------------------------
def _et(ts, fmt="%H:%M:%S"):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(ET_ZONE).strftime(fmt)


def _usd(x, sign=True):
    return (("+" if x > 0 else "-" if x < 0 else "") if sign else ("-" if x < 0 else "")) + f"${abs(x):,.0f}"


def print_day(r):
    bt, d = r.bt, r.data
    gap = (f"gap at the open {bt.gap_pct:+.0f}%" if bt is not None and bt.gap_pct == bt.gap_pct else "gap n/a")
    if bt is None and d["pc"]:
        rth = d["df1"][(d["df1"]["time"].dt.time >= _t(RTH_START)) & (d["df1"]["volume"] > 0)]
        if len(rth):
            gap = f"gap at the open {(rth['open'].iloc[0] / d['pc'] - 1) * 100:+.0f}%"
    print("\n" + "=" * 100)
    print(f"{r.ticker}  {r.day}   prior close {d['pc'] if d['pc'] else 'n/a'}   {gap}   "
          f"1-min bars: {d['src1']}   long candles: {d['src10'] or '-'} ({len(d['bars10']):,})")
    print("=" * 100)
    if LONG_ENABLED:
        print(f"PREMARKET LONG {LONG_SESSION_START}-{LONG_SESSION_END}   {r.long_note()}")
        for t in r.side(LONG_SIDE):
            print(f"  L{t['n']} {t['setup']}  {_et(t['entry_ts'])} BUY {t.get('shares', 0):,} @ {t['entry']:.4g}"
                  f" ({_usd(t.get('position', 0), False)})  stop {t['stop']:.4g} ({t['risk_pct']:.1f}%)  target {t['target']:.4g}")
            legs = "   ".join(f"{_et(lg['ts'])} sold {lg['frac'] * 100:.0f}% @ {lg['px']:.4g} ({lg['reason']})" for lg in t["legs"])
            print(f"       {legs}")
            print(f"       {t['ret_pct']:+.1f}%  {t['R']:+.2f}R   P&L {_usd(t.get('pnl', 0))}   balance {_usd(t.get('bal_after', 0), False)}")
        if not r.side(LONG_SIDE):
            print("  no long trade")
    if SHORT_ENABLED and r.jr is not None:
        JR = jay_read_module()
        rd = r.jr.reader
        up = rd.hod / rd.pc * 100.0 - 100.0 if rd.pc else float("nan")
        print(f"JAY-READ SHORT {JR.SIGNAL_START}-{JR.SIGNAL_END} signals (entry B from {JR.LEVEL_SIGNAL_START})   "
              f"stock {up:+.0f}% (needs +{JR.MIN_UP_PCT:g}%), ${rd.dollar / 1e6:,.0f}M traded (needs "
              f"${JR.MIN_DOLLAR_VOL / 1e6:g}M), {len(r.jr.signals)} signal(s)")
        if SQUEEZE_ENABLED:
            SQ = squeeze_module()
            print(f"MAX SQUEEZE SHORT {SQ.SIGNAL_START}-{SQ.SIGNAL_END} signals   stock needs +{SQ.MIN_UP_PCT:g}%, a "
                  f"+{SQ.SQUEEZE_PCT:g}% squeeze over the last swing high; one short per stock at a time")
        for t in r.side(SHORT_SIDE):
            lg = t["legs"][0]
            print(f"  S{t['n']} {t['setup']}  {_et(t['entry_ts'], '%H:%M')} SHORT {t.get('shares', 0):,} @ {t['entry']:.4g}"
                  f" ({_usd(t.get('position', 0), False)})  stop {t['stop']:.4g} ({t['risk_pct']:.1f}%)  ->  "
                  f"{t['result']} {_et(lg['ts'], '%H:%M')} @ {lg['px']:.4g}   {t['R']:+.2f}R net ({t['ret_pct']:+.1f}% after the "
                  f"{t['fee_pct']:g}% locate)   P&L {_usd(t.get('pnl', 0))}   balance {_usd(t.get('bal_after', 0), False)}")
            print(f"       {t['note']}")
        if not r.side(SHORT_SIDE):
            print("  no short trade")
    if SHORT_ENABLED and bt is not None:
        print(f"SHORT {min(ENTRY_START, VAC_ENTRY_START)}-{LAST_ENTRY_TIME}   "
              + ("setup day" if bt.gap_ok else f"gap < {MIN_GAP_PCT:g}% at the open - "
                 + ("not a setup day" if VAC_REQUIRE_GAP else "no bounce short (vacuum allowed)")))
        for t in r.side(SHORT_SIDE):
            lg = t["legs"][0]
            print(f"  S{t['n']} {t['setup']}  {_et(t['entry_ts'], '%H:%M')} SHORT {t.get('shares', 0):,} @ {t['entry']:.4g}"
                  f" ({_usd(t.get('position', 0), False)})  stop {t['stop']:.4g} ({t['risk_pct']:.1f}%)  ->  "
                  f"{t['result']} {_et(lg['ts'], '%H:%M')} @ {lg['px']:.4g}   {t['R']:+.2f}R net ({t['ret_pct']:+.1f}% after the "
                  f"{t['fee_pct']:g}% locate)   P&L {_usd(t.get('pnl', 0))}   balance {_usd(t.get('bal_after', 0), False)}")
        if not r.side(SHORT_SIDE):
            print("  no short trade")
        if bt.skipped and SHOW_SKIPPED:
            for s in bt.skipped[:8]:
                print(f"    skipped {s['time']:%H:%M} @ {s['price']:.4g}  {s['reason']}")
            if len(bt.skipped) > 8:
                print(f"    ... {len(bt.skipped) - 8} more skipped signals (on the chart)")
    print(f"DAY   long {_usd(r.pnl(LONG_SIDE))}   short {_usd(r.pnl(SHORT_SIDE))}   combined {_usd(r.pnl())}")


def print_accounts(trades):
    rows = [("Combined", (LONG_SIDE, SHORT_SIDE))]
    if LONG_ENABLED and SHORT_ENABLED:
        rows += [("Long only", (LONG_SIDE,)), ("Short only", (SHORT_SIDE,))]
    print("\n" + "#" * 100)
    print(f"ACCOUNT  start {_usd(STARTING_BALANCE, False)}, compounding.  Long {LONG_ACCOUNT_PCT:g}% of the balance (max "
          f"{_usd(LONG_MAX_POSITION_USD, False)}),  short {SHORT_ACCOUNT_PCT:g}% (max {_usd(SHORT_MAX_POSITION_USD, False)})")
    print(f"  {'':<12}{'trades':>7}{'wins':>6}{'win %':>7}{'net P&L':>13}{'final':>13}{'max DD':>9}{'PF $':>7}")
    out = {}
    for name, sides in rows:
        s = account_stats(trades, sides)
        out[name] = s
        pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
        print(f"  {name:<12}{s['trades']:>7}{s['wins']:>6}{s['win_rate']:>6.0f}%{_usd(s['net']):>13}"
              f"{_usd(s['final'], False):>13}{s['max_dd']:>8.1f}%{pf:>7}")
    print("#" * 100)
    return out


def trades_frame(trades):
    rows = []
    for t in sorted(trades, key=lambda x: x["entry_ts"]):
        lg = t["legs"][-1]
        rows.append({"Date": t["date"], "Ticker": t["ticker"], "Side": t["side"], "Setup": t["setup"], "#": t["n"],
                     "Entry Time": _et(t["entry_ts"]), "Entry": round(t["entry"], 4), "Stop": round(t["stop"], 4),
                     "Risk %": round(t["risk_pct"], 2), "Shares": t.get("shares", 0),
                     "Position ($)": round(t.get("position", 0.0), 2),
                     "Exits": "  ".join(f"{_et(x['ts'])} {x['frac'] * 100:.0f}% @ {x['px']:.4g}" for x in t["legs"]),
                     "Exit Time": _et(lg["ts"]), "Avg Exit": round(sum(x["frac"] * x["px"] for x in t["legs"]), 4),
                     "Result": t["result"], "Return % (net)": round(t["ret_pct"], 3), "R (net)": round(t["R"], 3),
                     "PnL ($)": round(t.get("pnl", 0.0), 2), "Balance Before ($)": round(t.get("bal_before", 0.0), 2),
                     "Balance After ($)": round(t.get("bal_after", 0.0), 2), "Note": t.get("note", "")})
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# Chart: 1-minute candles, the premarket long (buys / sells) and the shorts, one table
# -----------------------------------------------------------------------------
def _ts_naive(ts):
    return pd.Timestamp(ts, unit="s", tz="UTC").tz_convert(ET).tz_localize(None)


def build_combined_chart(r, out_path, include_plotlyjs="cdn"):
    bt = r.bt
    d = r.data["df1"].copy()
    d["t"] = d["time"].dt.tz_localize(None)
    tx = d["t"]
    if bt is not None:
        vwap = bt.vwap
    else:
        tp = (d["high"] + d["low"] + d["close"]) / 3.0
        vwap = (tp * d["volume"]).cumsum() / d["volume"].cumsum().replace(0, np.nan)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=False, vertical_spacing=0.04, row_heights=[0.62, 0.14, 0.24],
                        specs=[[{"type": "xy"}], [{"type": "xy"}], [{"type": "table"}]])
    fig.add_trace(go.Candlestick(x=tx, open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="1m",
                                 increasing_line_color="#d9d9d9", increasing_fillcolor="#d9d9d9",
                                 decreasing_line_color="#e0413a", decreasing_fillcolor="#e0413a", showlegend=False),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=tx, y=vwap, name="VWAP", line=dict(color="#f0a020", width=1.6)), row=1, col=1)
    vcol = np.where(d["close"] >= d["open"], "#8c8c8c", "#a8322d")
    fig.add_trace(go.Bar(x=tx, y=d["volume"], marker_color=vcol, name="Volume", showlegend=False), row=2, col=1)

    day_str = str(r.day)
    ts_ = lambda hm: pd.Timestamp(f"{day_str} {hm}")
    for row in (1, 2):
        fig.add_vrect(x0=tx.iloc[0], x1=ts_(RTH_START), fillcolor="#555", opacity=0.18, line_width=0, row=row, col=1)
        if tx.iloc[-1] > ts_(RTH_END):
            fig.add_vrect(x0=ts_(RTH_END), x1=tx.iloc[-1], fillcolor="#555", opacity=0.18, line_width=0, row=row, col=1)
    if LONG_ENABLED:
        fig.add_vrect(x0=ts_(LONG_SESSION_START), x1=ts_(LONG_SESSION_END), fillcolor="#00c853", opacity=0.06,
                      line_width=0, row=1, col=1, annotation_text="premarket long", annotation_position="top left",
                      annotation_font=dict(size=10, color="#69f0ae"))
    if SHORT_ENABLED:
        if r.jr is not None:
            JR = jay_read_module()
            s0, s1 = JR.SIGNAL_START, JR.LAST_ENTRY_TIME
        else:
            s0, s1 = min(ENTRY_START, VAC_ENTRY_START), LAST_ENTRY_TIME
        fig.add_vrect(x0=ts_(s0), x1=ts_(s1), fillcolor="#2962ff",
                      opacity=0.06, line_width=0, row=1, col=1, annotation_text="short entries",
                      annotation_position="top left", annotation_font=dict(size=10, color="#82b1ff"))

    def seg(x0, x1, y, color, dash, width=1.1):
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y, y], mode="lines", line=dict(color=color, width=width, dash=dash),
                                 showlegend=False, hoverinfo="skip"), row=1, col=1)

    def mark(x, y, symbol, color, text, pos, hover, size=14, tcolor=None):
        fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers+text",
                                 marker=dict(symbol=symbol, size=size, color=color, line=dict(color="black", width=1)),
                                 text=[text], textposition=pos, textfont=dict(color=tcolor or color, size=10),
                                 hovertext=[hover], hoverinfo="text", showlegend=False), row=1, col=1)

    if bt is not None:
        if bt.prior_close:
            fig.add_hline(y=bt.prior_close, line=dict(color="#6b6b6b", width=1, dash="dot"), row=1, col=1,
                          annotation_text=f"Prior close {bt.prior_close:.2f}", annotation_position="top left",
                          annotation_font=dict(size=10, color="#6b6b6b"))
        fig.add_hline(y=bt.hod, line=dict(color="#9aa0a6", width=1, dash="dot"), row=1, col=1,
                      annotation_text=f"HOD {bt.hod:.2f}", annotation_position="top left",
                      annotation_font=dict(size=10, color="#9aa0a6"))
    if r.eng is not None:
        seg(ts_(LONG_SESSION_START), ts_(LONG_SESSION_END), r.eng.alert, "#ffd600", "dot", 1)
        fig.add_annotation(x=ts_(LONG_SESSION_START), y=r.eng.alert, text=f"+{LONG_MIN_GAP_PCT * 100:.0f}% {r.eng.alert:.2f}",
                           showarrow=False, xanchor="left", yanchor="bottom", font=dict(size=10, color="#ffd600"), row=1, col=1)

    # premarket long: buy, half, exit
    for t in r.side(LONG_SIDE):
        e = _ts_naive(t["entry_ts"])
        x_end = _ts_naive(t["legs"][-1]["ts"])
        seg(e, x_end, t["stop"], "#ff5c5c", "dash")
        seg(e, x_end, t["target"], "#00e676", "dot")
        mark(e, t["entry"], "triangle-up", "#00e676", f"L{t['n']} BUY", "bottom center",
             f"L{t['n']} {t['setup']}<br>Buy {t.get('shares', 0):,} @ {t['entry']:.4g} (${t.get('position', 0):,.0f})"
             f"<br>Stop {t['stop']:.4g} ({t['risk_pct']:.1f}%)  Target {t['target']:.4g}", 15, "#69f0ae")
        for k, lg in enumerate(t["legs"]):
            xt = _ts_naive(lg["ts"])
            final = k == len(t["legs"]) - 1
            if not final:
                mark(xt, lg["px"], "circle", "#4fc3f7", "half", "top center",
                     f"L{t['n']} half sold @ {lg['px']:.4g} ({lg['reason']})", 11)
            else:
                col = "#00e676" if t.get("pnl", 0) > 0 else "#ff5252"
                mark(xt, lg["px"], "triangle-down", col, f"L{t['n']} {_usd(t.get('pnl', 0))}", "top center",
                     f"L{t['n']} sold @ {lg['px']:.4g} ({t['result']})<br>{t['ret_pct']:+.1f}%  {t['R']:+.2f}R  "
                     f"P&L {_usd(t.get('pnl', 0))}", 14)

    # Jay-read shorts: the read (regular-hours high, crack low, overhead high / level, bounce high), entry, stop, lock, exit
    if r.jr is not None:
        if r.data["pc"]:
            fig.add_hline(y=r.data["pc"], line=dict(color="#6b6b6b", width=1, dash="dot"), row=1, col=1,
                          annotation_text=f"Prior close {r.data['pc']:.2f}", annotation_position="top left",
                          annotation_font=dict(size=10, color="#6b6b6b"))
        nt = lambda x: x.tz_localize(None) if getattr(x, "tzinfo", None) is not None else x
        for t in r.side(SHORT_SIDE):
            g = t["sig"]
            e, x_end = _ts_naive(t["entry_ts"]), _ts_naive(t["legs"][0]["ts"])
            if g["setup"] == "squeeze":                  # max squeeze: the swing high it broke and the squeeze top
                seg(nt(g["level_time"]), x_end, g["level"], "#3b82f6", "dot", 1)
                mark(nt(g["level_time"]), g["level"], "circle-open", "#3b82f6", "swing high", "top center",
                     f"Last swing high it broke (the average short) {g['level']:.4g}", 12)
                mark(nt(g["top_time"]), g["top"], "diamond", "#ffd23f", f"top +{g['squeeze'] * 100:.0f}%", "top center",
                     f"Squeeze top {g['top']:.4g} (+{g['squeeze'] * 100:.0f}% over the swing high)", 10)
                seg(e, x_end, t["stop"], "#ff5c5c", "dash", 1.2)
                mark(e, t["entry"], "triangle-down", "#e040fb", f"S{t['n']} squeeze", "top center",
                     f"S{t['n']} {t['setup']}<br>{t['note']}<br>Short {t.get('shares', 0):,} @ {t['entry']:.4g} "
                     f"(${t.get('position', 0):,.0f})  Stop {t['stop']:.4g}  Risk {t['risk_pct']:.1f}%", 15)
                ec = {"Stop": "#ff5c5c", "EOD": "#bbbbbb"}.get(t["result"], "#cccccc")
                mark(x_end, t["legs"][0]["px"], "triangle-up", ec, f"{t['result']} {t['R']:+.2f}R {_usd(t.get('pnl', 0))}",
                     "bottom center", f"Cover @ {t['legs'][0]['px']:.4g} ({t['result']})<br>{t['R']:+.2f}R net of the "
                     f"locate, {t['ret_pct']:+.1f}%  P&L {_usd(t.get('pnl', 0))}")
                continue
            seg(nt(g["rth_high_time"]), x_end, g["rth_high"], "#9aa0a6", "dot", 1)
            mark(nt(g["rth_high_time"]), g["rth_high"], "circle-open", "#3b82f6", "RTH high", "top center",
                 f"Regular-hours high {g['rth_high']:.4g}")
            mark(nt(g["crack_low_time"]), g["crack_low"], "triangle-up", "#22d3ee", f"crack -{g['crack'] * 100:.0f}%",
                 "bottom center", f"Crack low {g['crack_low']:.4g} ({g['crack'] * 100:.0f}% under the high)", 11)
            mark(nt(g["ref_time"]), g["ref"], "circle-open", "#3b82f6",
                 "level" if g["setup"] == "level" else "overhead high", "top center", f"{g['ref']:.4g}", 12)
            mark(nt(g["bounce_high_time"]), g["bounce_high"], "diamond", "#ffd23f", "bounce high", "top center",
                 f"Bounce high {g['bounce_high']:.4g}", 10)
            seg(e, x_end, t["stop"], "#ff5c5c", "dash", 1.2)
            if t.get("lock_ts"):
                seg(_ts_naive(t["lock_ts"]), x_end, t["lock_stop"], "#22d3ee", "dash", 1.1)
            mark(e, t["entry"], "triangle-down", "#e040fb", f"S{t['n']} {t['setup'].replace('Jay-read ', '')}", "top center",
                 f"S{t['n']} {t['setup']}<br>{t['note']}<br>Short {t.get('shares', 0):,} @ {t['entry']:.4g} "
                 f"(${t.get('position', 0):,.0f})  Stop {t['stop']:.4g}  Risk {t['risk_pct']:.1f}%", 15)
            ec = {"Stop": "#ff5c5c", "EOD": "#bbbbbb", "Lock": "#22d3ee"}.get(t["result"], "#cccccc")
            mark(x_end, t["legs"][0]["px"], "triangle-up", ec, f"{t['result']} {t['R']:+.2f}R {_usd(t.get('pnl', 0))}",
                 "bottom center", f"Cover @ {t['legs'][0]['px']:.4g} ({t['result']})<br>{t['R']:+.2f}R net of the locate, "
                 f"{t['ret_pct']:+.1f}%  P&L {_usd(t.get('pnl', 0))}")
        taken = {id(t["sig"]) for t in r.side(SHORT_SIDE)}
        sk = [s for s in r.jr.signals if id(s) not in taken]
        if SHOW_SKIPPED and sk:
            fig.add_trace(go.Scatter(x=[nt(s["time"]) for s in sk], y=[s["close"] for s in sk], mode="markers",
                                     marker=dict(symbol="x", size=8, color="#8a8a8a"), name="Short signal not taken",
                                     hovertext=[f"{JR_SETUP.get(s['setup'], s['setup'])} signal (in a trade / done for the day)"
                                                for s in sk], hoverinfo="text"), row=1, col=1)

    # v16 shorts (same drawing as the short backtester)
    for t in (r.side(SHORT_SIDE) if bt is not None else []):
        src = next(x for x in bt.trades if x["n"] == t["n"])
        e, x_end = _ts_naive(t["entry_ts"]), _ts_naive(t["legs"][0]["ts"])
        top_t = bt.df["time"].iloc[src["top_idx"]].tz_localize(None)
        seg(e, x_end, t["stop"], "#ff5c5c", "dash", 1.2)
        if t["setup"] == VAC_SETUP:
            mark(top_t, src["top"], "circle-open", "#e040fb", f"peak +{src['zone_vs_vwap_pct']:.0f}% vs VWAP", "top center",
                 f"Vacuum peak {src['top']:.3f}")
            scol = "#e040fb"
        else:
            fig.add_trace(go.Scatter(x=[top_t, x_end, x_end, top_t, top_t],
                                     y=[src["zone_lo"], src["zone_lo"], src["zone_hi"], src["zone_hi"], src["zone_lo"]],
                                     mode="lines", fill="toself", fillcolor="rgba(206,147,216,0.18)", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip"), row=1, col=1)
            mark(top_t, src["top"], "circle-open", "#f5f5f5", "top", "top center", f"Top {src['top']:.3f}", 13)
            scol = "#ff3b30"
        mark(e, t["entry"], "triangle-down", scol, f"S{t['n']} {t['setup']}", "top center",
             f"S{t['n']} {t['setup']}<br>{t['note']}<br>Short {t.get('shares', 0):,} @ {t['entry']:.4g} "
             f"(${t.get('position', 0):,.0f})  Stop {t['stop']:.4g}  Risk {t['risk_pct']:.1f}%", 15)
        ec = {"Stop": "#ff5c5c", "EOD": "#bbbbbb", "VWAP": "#f0a020"}.get(t["result"].replace(" (gap)", ""), "#cccccc")
        mark(x_end, t["legs"][0]["px"], "triangle-up", ec, f"{t['result']} {t['R']:+.2f}R {_usd(t.get('pnl', 0))}",
             "bottom center", f"Cover @ {t['legs'][0]['px']:.4g} ({t['result']})<br>{t['R']:+.2f}R net of the locate, "
             f"{t['ret_pct']:+.1f}%  P&L {_usd(t.get('pnl', 0))}")
    if SHOW_SKIPPED and bt is not None and bt.skipped:
        fig.add_trace(go.Scatter(x=[s["time"].tz_localize(None) for s in bt.skipped], y=[s["price"] for s in bt.skipped],
                                 mode="markers", marker=dict(symbol="x", size=8, color="#8a8a8a"), name="Skipped short signal",
                                 hovertext=[f"SKIP {s['setup']}: {s['reason']}" for s in bt.skipped], hoverinfo="text"),
                      row=1, col=1)

    tf = trades_frame(r.trades)
    if len(tf):
        cols = ["Side", "#", "Setup", "Entry Time", "Entry", "Shares", "Position ($)", "Stop", "Exits", "Result",
                "Return % (net)", "R (net)", "PnL ($)", "Balance After ($)"]
        vals = [tf[c].tolist() for c in cols]
        vals[cols.index("PnL ($)")] = [_usd(x) for x in tf["PnL ($)"]]
        vals[cols.index("Position ($)")] = [f"{x:,.0f}" for x in tf["Position ($)"]]
        vals[cols.index("Balance After ($)")] = [f"{x:,.0f}" for x in tf["Balance After ($)"]]
        vals[cols.index("Return % (net)")] = [f"{x:+.1f}%" for x in tf["Return % (net)"]]
        vals[cols.index("R (net)")] = [f"{x:+.2f}" for x in tf["R (net)"]]
    else:
        cols, vals = ["Result"], [[f"No trades - long: {r.long_note()}"]]
    fig.add_trace(go.Table(header=dict(values=cols, fill_color="#262626", font=dict(color="white", size=11), align="left"),
                           cells=dict(values=vals, fill_color="#141414", font=dict(color="#e6e6e6", size=11), align="left")),
                  row=3, col=1)
    nl, ns = len(r.side(LONG_SIDE)), len(r.side(SHORT_SIDE))
    bal0 = min(r.trades, key=lambda t: t["entry_ts"]).get("bal_before") if r.trades else None
    bal1 = max(r.trades, key=lambda t: t["legs"][-1]["ts"]).get("bal_after") if r.trades else None
    title = (f"{r.ticker}  {r.day}  |  premarket long: {nl} trade(s) {_usd(r.pnl(LONG_SIDE))}  |  short: {ns} trade(s) "
             f"{_usd(r.pnl(SHORT_SIDE))}  |  day {_usd(r.pnl())}"
             + (f"  |  balance {_usd(bal0, False)} -> {_usd(bal1, False)}" if r.trades and bal0 is not None else ""))
    fig.update_layout(template="plotly_dark", title=dict(text=title, font=dict(size=15)), height=1050,
                      xaxis_rangeslider_visible=False, hovermode="closest", margin=dict(l=60, r=30, t=60, b=30),
                      legend=dict(orientation="h", y=1.02, x=1, xanchor="right"))
    x0, x1 = ts_(PLOT_FROM), ts_(PLOT_TO)
    fig.update_xaxes(range=[x0, x1], row=1, col=1)
    fig.update_xaxes(range=[x0, x1], row=2, col=1, matches="x")
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.write_html(out_path, include_plotlyjs=include_plotlyjs)
    return out_path


# -----------------------------------------------------------------------------
# Runner (this file on its own: TICKER / DATE or BATCH)
# -----------------------------------------------------------------------------
def main(vault_db=None):
    jobs = BATCH if BATCH else [(TICKER, DATE)]
    jobs = sorted(((tk.upper().strip(), ds) for tk, ds in jobs), key=lambda j: (j[1], j[0]))
    csv_mode = bool(CSV_PATH)
    if csv_mode and len(jobs) > 1:
        sys.exit("csv mode runs one day (CSV_PATH). Clear CSV_PATH to run a BATCH from the vault, or use the bulk runner.")
    vault = None
    if not csv_mode:
        try:
            vault = open_vault(vault_db)
        except RuntimeError as exc:
            sys.exit(str(exc))
        print(f"Bars from the vault: {vault.path}")
    missing = vault_bars().Missing() if not csv_mode else None
    runs = []
    for tk, ds in jobs:
        day = datetime.strptime(ds, "%Y-%m-%d").date()
        try:
            runs.append(run_day(tk, day, vault=vault, csv_1m=CSV_PATH if csv_mode else None,
                                csv_10s=(CSV_10S_PATH or None) if csv_mode else None))
        except MissingFromVault as exc:
            missing.add(tk, day, str(exc))
            print(f"{tk} {ds}: missing from vault ({exc}) - skipped")
        except (Exception, SystemExit) as exc:
            print(f"{tk} {ds}: {exc}")
    trades = [t for r in runs for t in r.trades]
    simulate(trades)
    every = list(trades)                              # incl. the longs the daily stop skipped (the account stats re-run it)
    skipped = drop_skipped(trades, runs)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for r in runs:
        print_day(r)
        html = os.path.join(OUTPUT_DIR, f"{r.ticker}_{r.day}_combined.html")
        build_combined_chart(r, html)
        if r.trades:
            trades_frame(r.trades).to_csv(os.path.join(OUTPUT_DIR, f"{r.ticker}_{r.day}_combined_trades.csv"), index=False)
        print(f"Chart saved: {os.path.abspath(html)}")
        if OPEN_BROWSER:
            webbrowser.open("file://" + os.path.abspath(html))
    if runs:
        print_accounts(every)
        print_skipped(skipped)
    if missing is not None:
        missing.print_summary(missing.write(OUTPUT_DIR))


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="Combined premarket long + intraday short backtest of TICKER / DATE or BATCH "
                                              "(bars from the IB data vault).")
    _ap.add_argument("--vault", default=None, help="market_data_vault.db (default: VAULT_DB at the top of this file)")
    main(_ap.parse_args().vault)
