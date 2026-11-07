#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LH LONG PREMARKET 1.9  -  premarket momentum chase on 10-second bars (the rules of your backtest)
=====================================================================================================
1.9 (Kestrel 3.12.0): ROBUST SELLING (no extreme slippage):
  - a sell is never priced more than EXIT_FLOOR_PCT (4%) under the LAST TRADE (a thin / empty book cannot fill it 15%
    down at once); the floor widens EXIT_FLOOR_STEP_PCT every EXIT_FLOOR_STEP_SEC while it does not sell, up to
    EXIT_MAX_DEPTH_PCT - so it always gets out, just not into a hole;
  - a bid more than BID_SANE_PCT under the last trade is not believed (the last trade is the reference then);
  - halted: no sell is sent (TradeZero rejects it); it goes the instant the stock trades again;
  - from 09:30: a marketable limit RTH_SELL_COLLAR_PCT under the bid (deeper each try, re-priced every second) instead of
    a plain market order; a market order only after RTH_SELL_MARKET_AFTER tries.
1.8 (Kestrel 3.10.0):
  - the hard stop sells at stop +1% (STOP_EARLY_PCT = 1.0): a fast premarket fade slipped 3.5% under the stop (BIRD
    23 Oct: stop 3.10, sold 2.99). The trail after the half is unchanged. Every stop sale is logged to
    long_stop_slippage.csv (stop, trigger, fill, slippage) and posted with the slippage.
  - the app's Trading mode: Trading / Alert only (setups posted as "SIGNAL · NOT TRADED", no buys) / Off.
  - Discord: posted as "Longs" with a tag line (LONG WATCH, BOUGHT, HALF SOLD, CLOSED · WIN / STOP, LONGS FLAT · 09:00).
1.7 (Kestrel 3.8.0): SAFETY LAYER after the LRHC long of 16 Oct (TradeZero answered the buy with HTTP 404, the
order filled anyway, the bot never knew and the long ran without a stop until the 09:00 flatten could not sell it):
  - every order whose answer is an error (any HTTP code, or no answer) is looked up at TradeZero by its id before the
    bot believes it - a 404 that filled is tracked like a normal fill;
  - a buy that still cannot be settled is "unknown": the symbol stays streamed, no second buy on it, and
  - the POSITION GUARD reads TradeZero's positions every GUARD_POLL_SEC (2 s) while a long is open or unsettled
    (every 6 s during the session otherwise). Shares the bot did not know in a symbol it bought today are TAKEN OVER
    within ~4 s: the signal's stop / target when the bot has it, else a stop MAX_RISK_PCT (10%) under TradeZero's
    average price - then managed and sold like any long. Shares gone at TradeZero (sold by you, or a sell whose answer
    was lost) are booked closed at the real fill price;
  - stops, targets and trails are also checked on the clock (4x a second), not only when a tick arrives;
  - a sell that errors is retried at once, stepping deeper under the bid each round, until TradeZero shows it flat;
  - the 09:00 flatten takes over any long the bot does not hold yet and sells it (no more "no bid - skipped");
  - a symbol is never dropped from the watchlist while TradeZero shows the bot's shares in it.
  The 12.5%-of-the-position max loss per trade is removed (it never cut a trade: the stop is at most 10%).

Part of Kestrel 3.8.0 (1.6 was in 3.6.4 - 3.7.2). Keep this file NEXT TO main.py (3.12; was kestrel_app.py): the app imports it and runs the
premarket long inside the same window, with the same IB Gateway connection, the same TradeZero account
and the same Discord webhook (Keys button in the app). There is nothing to start separately.

  05:00 ET     IBKR scanner every 10 s: US stocks up 30%+ from the prior close, price $0.50+ (+ the tickers in
               extra_tickers.txt next to the app, if that file exists). A stock is added as soon as its last
               10-second candle CLOSES above +30%: the bot streams its 5-second bars + quotes from IB, rebuilds
               today's 1-minute and 10-second history and runs the strategy below. Stocks that cannot trade any
               more (20-minute window over, or a slow grind = no momentum chase) are not added.
  Entry        buy limit at the ASK (marketable), cancelled if not filled in 5 s. Size: 20% of the account
               equity (compounding), max $10,000 per long. Stop 1%-10% under the entry. A stock is done for the day
               once its losses reach 25% of the position ($500 on a $2,000 position, $2,500 at the $10,000 maximum).
               Daily stop: no new longs once the long bot's realized loss today reaches 50% of the long position
               size at the start of the day ($1,000 on a $2,000 position, $5,000 at the $10,000 cap).
               Chase cap: a buy is skipped when the ask is more than 10% over the trigger (MAX_CHASE_PCT).
  Exits        sell limit at the BID (re-priced every 2 s until filled): stop, half at the target, trailing
               stop, 5-minute time stop - all decided by the strategy engine on live prices.
  09:00 ET     no new entries; every open long is sold (limit at the bid, stepping down until filled - TradeZero
               takes no market orders before 09:30). Anything still unsold is retried every 20 s, at market from
               09:30. While a long is still open the short bot does NOT short that symbol.
  Discord      every stock added (with chart), every entry, half, exit with P&L, the 09:00 flatten and the
               premarket summary - posted as "Kestrel long" in your channel.
  The app      Orders panel -> "Premarket long" tab: active and closed long trades, ON / OFF switch.

FILTERS: none besides the strategy below - no market-cap, no prior-day-volume and no news filter.

STRATEGY = your premarket long backtest (pm_long script, the run with 20k-share surge candles, no news, no filters).
With that backtest's surge candle (RVOL 2, close in the top 25%) this engine gives exactly its 97 trades on the 584 test
days ($10k -> $186,553 with its 40% sizing). 1.5 uses RVOL 1.5 and a close in the top 40% (126 trades on those days).
  Discovery      a 10-second candle trades at/above prior close +30% between 05:00 and 09:00 ET. No entry in the
                 first 30 s after it, and none after the first 20 minutes (FRESH_ENTRY_SEC).
  Velocity       60 ten-second candles (~10 minutes) before discovery the stock was up <= 15%: vertical surge ->
                 momentum chase armed. Otherwise (slow grind, "dead money") the stock is not traded.
  1-min macro    built from the 10-second candles from 04:00: EMA 9, VWAP, RVOL vs the previous (up to) 10 minutes.
                 Every 10-second candle uses the PREVIOUS completed minute.
  Momentum       1-min candle +3% green, RVOL >= 1.5, 20,000+ shares, close in the top 40% of its range
                 ->  buy above its high, stop under its low.
  Filters        1-min close >= VWAP, not 20% off the session high (backside lock; a new high unlocks), trigger
                 itself +30% up, price $0.50-$25.00, at most 300% above the 05:00 open, risk 1%-10% of the entry.
  Size           ACCOUNT_PCT (20%) of the account equity - grows with the account (compounding) - but never more
                 than MAX_POSITION_USD ($10,000) per long (premarket liquidity). Even share count. No cut for the
                 stop distance (1.7): the stop is at most 10% under the entry, so a stop-out costs at most ~10%.
  Target         2R (3R when RVOL >= 5 and the 1-min close is above EMA 9): sell HALF, trail the rest
                 at breakeven, then under the 60-second low.
  Time stop      5 minutes without reaching +1R (before the half is sold) -> out.
  Limits         per symbol: 3 trades; losses reach MAX_LOSS_PER_STOCK_PCT (25%) of the position -> symbol done
                 for the day.  On a $10,000 account: position $2,000, $500 per stock. From $50,000 of equity the
                 position stays at $10,000 ($2,500 per stock).
                 Account (1.6): no new longs once the long bot's realized loss today reaches
                 DAILY_LOSS_PCT_OF_POSITION (50%) of the long position size at the start of the day (start-of-day
                 equity x 20%, max $10,000): $1,000 on a $10,000 account, $2,500 on $25,000, $5,000 from $50,000 on
                 (the position stops growing at $10,000, so does the daily stop).

REPLAY A PAST DAY through the same engine (IB Gateway history, 10-second bars):
      python lh_long_premarket.py SBFM 20261008
      python lh_long_premarket.py SBFM 20261008 --csv sbfm.csv --port 4001 --equity 25000
"""

# =============================================================================
# LIVE SETTINGS (premarket long inside the app)
# =============================================================================
LONG_ON_AT_START = True            # the "Long bot" switch in the app starts ON (your last choice is remembered)
SCAN_START = "05:00"               # scanner + entries from this time (ET)
ENTRY_CUTOFF = "09:00:00"          # no new entries from here
FLATTEN_AT = "09:00:00"            # every open long is sold from here (limit at the bid, stepping down)
RTH_OPEN = "09:30:00"              # TradeZero takes market orders only from the open: unsold longs go at market then
RESIDUAL_RETRY_SEC = 20            # an unsold long after the flatten is tried again this often
RESIDUAL_ALERT_AT = "09:20:00"     # urgent Discord ping if a long is still open at this time

# --- scanner ---
SCAN_INTERVAL_SEC = 10
SCAN_CODE = "TOP_PERC_GAIN"
SCAN_LOCATION = "STK.US.MAJOR"
SCAN_ROWS = 50
SCAN_FILTER_CHANGE = True          # ask IB for change% >= the threshold (the bot re-checks with its own data)
EXTRA_TICKERS_FILE = "extra_tickers.txt"   # optional: one ticker per line, checked with every scan
MAX_WATCHLIST = 8                  # symbols streamed at once (incl. open positions)
DROP_GRACE_SEC = 60                # flat + under the threshold this long = monitoring ends
REJOIN_COOLDOWN_SEC = 120          # a dropped symbol can come back after this
DAY_COOLDOWN_SEC = 6 * 3600        # ... unless it is done for the day (limits, 20-minute window over, no momentum)
NOT_READY_RETRY_SEC = 20           # scanner listed it but the last 10-s candle did not close above +30% yet
SEED_10S_SEC = 14400               # 10-second history loaded when a symbol is added (4 hours, IB's maximum: the
                                   # day's candle count, the 20-minute window and the 10-minute velocity look-back)

# --- orders / account risk (strategy limits are in the STRATEGY PARAMETERS below) ---
MAX_OPEN_POSITIONS = 5
MAX_BOT_TRADES_PER_DAY = 40
DAILY_LOSS_PCT_OF_POSITION = 50.0  # 1.6: no new longs once the long bot's realized loss today reaches this % of the long
                                   # position size at the start of the day (ACCOUNT_PCT of TradeZero's start-of-day
                                   # equity, max MAX_POSITION_USD): $1,000 on $2,000, $5,000 at the $10,000 cap
ENTRY_TIMEOUT_SEC = 5.0            # buy limit at the ask: cancel the rest if not filled in this time
MAX_CHASE_PCT = 10.0               # skip the entry if the ask is more than this % above the trigger (1.6: was 3)
EXIT_REPRICE_SEC = 2.0             # sell limit at the bid: re-priced this often until filled
EXIT_STEP_PCT = 1.0                # each re-price goes this % deeper under the bid
EXIT_MAX_TRIES = 8
ORDER_POLL_SEC = 0.4
EXT_TIF = "Day_Plus"               # TradeZero time-in-force for premarket limit orders
FLATTEN_ALL_ACCOUNT_LONGS = False  # True = at 09:00 also sell longs the bot did not open

# --- 1.7 safety: TradeZero is the truth (positions guard) ---
GUARD_POLL_SEC = 2.0               # read TradeZero's positions this often while a long is open / an order is unsettled
GUARD_IDLE_POLL_SEC = 6.0          # ... and this often during the session otherwise
ADOPT_CONFIRM_SEC = 3.0            # shares the bot did not know must show on 2 reads this far apart before it takes them
                                   # over (TradeZero's list can lag a fill by a second)
GONE_CONFIRM_SEC = 6.0             # shares missing at TradeZero must stay missing this long (3 reads) before the bot
                                   # books them as sold outside the bot
SETTLE_SEC = 6.0                   # after the bot's own buy / sell: no position comparison on that symbol for this long
UNKNOWN_FILL_WATCH_SEC = 180       # a buy answered with an error: TradeZero is checked for its fill this long
ORDER_LOOKUP_TRIES = 3             # an order answered with an error is looked up by its id this many times (0.5/1/1.5 s)
ORDER_LOOKUP_WAIT_SEC = 0.5        # ... waiting this x 1, 2, 3 before each look-up
ORDER_RETRY_PAUSE_SEC = 0.5        # pause before a sell is sent again after an error / a rejection
VERIFY_PRICE_WAIT_SEC = 6.0        # shares gone at TradeZero: wait up to this long for their sell order to show (its
                                   # real fill price) before booking them at the lost sell's limit price
ADOPT_STOP_PCT = 10.0              # a long taken over without its signal: stop this % under TradeZero's average price
GUARD_ALERT_SEC = 30               # positions unreadable this long while a long is open: urgent Discord message
EXIT_MAX_DEPTH_PCT = 15.0          # repeated sell rounds step down to at most this % under the bid (premarket limits)
EXIT_FLOOR_PCT = 4.0               # 1.9: a sell is never priced deeper than this % under the last trade ...
EXIT_FLOOR_STEP_PCT = 3.0          # ... the floor widens this % ...
EXIT_FLOOR_STEP_SEC = 20.0         # ... every this many seconds it does not sell (up to EXIT_MAX_DEPTH_PCT)
BID_SANE_PCT = 15.0                # 1.9: a bid this % or more under the last trade is not believed (last trade used)
RTH_SELL_COLLAR_PCT = 3.0          # 1.9: from 09:30 a sell = limit this % under the bid (+1% deeper each try) ...
RTH_SELL_MARKET_AFTER = 4          # ... and a market order only after this many tries
RTH_REPRICE_SEC = 1.0              # ... re-priced this often
UNSOLD_ALERT_EVERY_SEC = 60        # "could not sell" message at most this often per symbol

# --- Discord (the app's webhook) ---
DISCORD_USERNAME = "Longs"         # 1.8 (app 3.10): the name the long's messages are posted under
DISCORD_CHART_IMAGES = True        # 1-minute chart on spike / entry / exit messages
DISCORD_HEARTBEAT_MIN = 30         # status message every N minutes during the session (0 = off)

STALE_STREAM_SEC = 90              # no 5-second bar for this long = re-subscribe the symbol

# =============================================================================
# STRATEGY ENGINE (the replay below and the live bot both run it)
# v1.5: momentum candle RVOL 1.5 (was 2) and a close in the top 40% of its range (was 25%).
# v1.2: the rules of your premarket long BACKTEST (pm_long script, the run with 20k-share surge candles, no news and no
# market-cap / prior-day-volume filter): +30% discovery 05:00-09:00, $0.50 minimum, momentum chase only, entries in
# the first 20 minutes after discovery, 3 trades per stock, the trigger itself must be +30% up, no entry more than
# 300% above the 05:00 open. Sizing: 20% of the account equity (compounding); loss limits 12.5% of the position per
# trade and 25% per stock (1.3: they grow with the position - $250 / $500 on $2,000).
# Live-only fix (1.1): on_bar_10s does not stop / trail a position out on the low of the 10-s candle it was bought (or
# half-sold) in - that low can be from BEFORE the fill.
# =============================================================================
import math
import sys
from collections import deque
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                                   # no tz database: pytz ships with pandas
    import pytz
    ET = pytz.timezone("America/New_York")

# =============================================================================
# STRATEGY PARAMETERS
# =============================================================================
DATA_START = "04:00"               # today's candles from here feed VWAP / EMA / RVOL / the 10-minute velocity look-back
SESSION_START = "05:00"            # discovery + entries only in this window (ET), like the backtest
SESSION_END = "09:00"
MIN_GAP_PCT = 0.30                 # discovery / watch threshold: prior close +30%
MIN_ENTRY_PRICE = 0.50
MAX_ENTRY_PRICE = 25.00
FRESH_ENTRY_SEC = 1200             # entries only in the first 20 minutes after discovery
WARMUP_ROWS = 20                   # the day's first 20 ten-second candles are history only (the backtest's range(20, ...))
MAX_EXT_FROM_OPEN = 3.00           # no entry more than 300% above the 05:00 open (first 10-s candle of the window)

EMA_PERIOD = 9
MACRO_EMA_PERIOD = 54
SLOPE_LOOKBACK = 12                # EMA-54 slope = EMA54 now - EMA54 12 minutes ago
RVOL_LEN = 10                      # RVOL = this minute's volume / average of the previous (up to) 10 minutes
                                   # (no earlier minute or no volume before = 999, like the backtest)

MOM_SURGE_PCT = 0.03               # momentum chase: 1-min candle at least +3% open -> close
MOM_RVOL = 1.5                     # ... with RVOL at least this (1.4 and your backtest: 2.0)
MOM_MIN_VOLUME = 20_000            # ... with at least this many shares in that minute
MOM_STRONG_CLOSE = 0.40            # ... closing in the top 40% of its range (1.4 and your backtest: 0.25)

BULL_FLAG_ENABLED = False          # v1.2: momentum chase only (the backtest). True = the 1.1 bull flag as well

FLAG_LOOKBACK = 5                  # bull flag: peak inside the last 5 completed minutes (lagged one minute)
FLAG_POLE_BACK = 2                 # pole starts 2 minutes before the peak
FLAG_MIN_VELOCITY = 0.01
FLAG_MAX_DROP = 0.15               # flag may pull back at most 15% from the peak
FLAG_RVOL = 1.5
FLAG_WHEN_MOMENTUM_PENDING = False  # False = exactly your backtest (elif); True = also check the flag

VELOCITY_LOOKBACK_ROWS = 60        # "10 minutes before discovery" = 60 ten-second candles back (the backtest's rows)
VELOCITY_MAX_GAIN = 0.15           # up <= 15% back then = vertical surge -> momentum chase armed
SCANNER_DELAY_SEC = 30             # no entry in the first 30 s after discovery
BACKSIDE_LOCK_PCT = 0.20           # close 20% under the session high = backside: no entries until a new high

MIN_RISK_PCT = 0.01
MAX_RISK_PCT = 0.10
TARGET_MULT = 2.0
TARGET_MULT_STRONG = 3.0
STRONG_RVOL = 5.0
MAX_HOLD_MIN_WITHOUT_PROFIT = 5
TRAIL_WINDOW = (70, 20)            # trail = lowest low of the 10-s candles that started 70..20 s before the
                                   # current candle (= the old rolling(6).min().shift(1) on the previous candle)

MAX_TRADES_PER_SYMBOL = 3
MAX_CONSECUTIVE_LOSSES = 3
# Size (compounding): every long = ACCOUNT_PCT of the account equity (TradeZero, refreshed all the time), so the
# size grows with the account. No fixed $ risk and no fixed $ cap. The loss limits are % of that position, so they
# grow with it:  $10,000 account -> $2,000 position -> $500 per stock;  $40,000 -> $8,000 -> $2,000.
# 1.7: no max loss per trade (the 12.5% rule is removed - the stop is at most MAX_RISK_PCT = 10% under the entry).
# 1.4: never more than MAX_POSITION_USD per long (premarket candles are thin): from $50,000 of equity every long is $10,000.
ACCOUNT_PCT = 20.0                 # % of account equity per long
MAX_POSITION_USD = 10_000.0        # $ cap per long (the short bot's own cap is $50,000 in main.py)
MAX_LOSS_PER_STOCK_PCT = 25.0      # % of the position: the stock is done for the day once its losses today reach this
REPLAY_EQUITY = 10_000.0           # replay only: the account equity the 20% is taken from (--equity in the replay)
TICK = 0.01
SLIPPAGE_PCT = 0.005               # replay only (the live bot gets real fills)
STOP_EARLY_PCT = 1.0                # 3.10: the hard stop sells when the price trades this % ABOVE the stop (stop x 1.01) - a
                                   # fast premarket fade slipped 3.5% under the stop (BIRD 23 Oct: stop 3.10, sold 2.99).
                                   # Hard stop only (before the half is sold); the trail is unchanged. 0 = at the stop.
                                   # Backtest (584 days, long-only account): $101,769 vs $102,972 at the stop (5 more
                                   # stop-outs, every stop sale 1% better).

# Result labels (same text as the old script, plus the 09:30 close)
STOP_OUT = "STOP OUT"
BREAKEVEN_OUT = "BREAKEVEN OUT"
TIME_STOP = "TIME STOP (DEAD MONEY)"
PARTIAL = "PARTIAL SCALE OUT"
TRAIL_OUT = "TRAILING STOP OUT"
OPEN_FLAT = "MARKET OPEN FLAT"
SOLD_OUTSIDE = "SOLD AT TRADEZERO"     # 1.7: shares gone at TradeZero that the bot did not sell (you / a lost answer)
ADOPTED = "TAKEN OVER (TradeZero)"    # 1.7: a long found at TradeZero without its signal
MOMENTUM = "1m MOMENTUM CHASE"
BULL_FLAG = "1m BULL FLAG"

NAN = float("nan")


def isnan(x):
    return x is None or x != x


def hms_secs(s):
    p = [int(x) for x in str(s).split(":")]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


SESSION_START_S = hms_secs(SESSION_START)
SESSION_END_S = hms_secs(SESSION_END)


def et_dt(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(ET)


def et_secs(ts):
    d = et_dt(ts)
    return d.hour * 3600 + d.minute * 60 + d.second


def et_hms(ts):
    return et_dt(ts).strftime("%H:%M:%S")


def in_session(ts):
    return SESSION_START_S <= et_secs(ts) < SESSION_END_S


def day_start_ts(ts, hhmm=DATA_START):
    """Epoch of hhmm ET on the ET calendar day of ts."""
    d = et_dt(ts)
    s = hms_secs(hhmm)
    start = d.replace(hour=s // 3600, minute=s % 3600 // 60, second=0, microsecond=0)
    return int(start.timestamp())


def position_usd(equity):
    """$ size of one long: ACCOUNT_PCT of the equity, at most MAX_POSITION_USD."""
    eq = equity if equity and equity > 0 else REPLAY_EQUITY
    return min(eq * ACCOUNT_PCT / 100.0, MAX_POSITION_USD)


def stock_loss_limit(equity):
    """$ a stock may lose today before it is done for the day: MAX_LOSS_PER_STOCK_PCT of the position (ACCOUNT_PCT of
    the equity, max MAX_POSITION_USD), so it grows with the account. $10,000 -> $2,000 -> $500; $50,000+ -> $2,500."""
    return position_usd(equity) * MAX_LOSS_PER_STOCK_PCT / 100.0


def clamp_risk(entry, stop):
    return max(entry * MIN_RISK_PCT, min(entry * MAX_RISK_PCT, entry - stop))


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


class Position:
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
        self.loss_limit = stock_loss_limit(REPLAY_EQUITY)  # $ per stock today (set from the equity at each entry)

    def check_halts(self):
        if self.halted:
            return True
        if self.daily_pnl <= -self.loss_limit:
            self.halted, self.halt_reason = True, f"loss limit ${self.loss_limit:,.0f} for this stock"
        elif self.trades_taken >= MAX_TRADES_PER_SYMBOL and self.pos is None:
            self.halted, self.halt_reason = True, f"{MAX_TRADES_PER_SYMBOL} trades"
        return self.halted


# =============================================================================
# ENGINE
# =============================================================================
class LongEngine:
    def __init__(self, sym, prior_close, day=None):
        self.sym = sym
        self.pc = float(prior_close)
        self.alert = self.pc * (1.0 + MIN_GAP_PCT)
        self.day = day or DayState(sym)
        self.b1 = []                      # completed 1-minute candles (today from 04:00)
        self.vwap_hist = []               # VWAP after each 1-minute candle (charts)
        self.b10 = deque(maxlen=480)      # completed 10-second candles (look-backs)
        self.cur = None                   # 1-minute candle being built from 10-second candles
        self.ema9 = NAN
        self.macro = NAN
        self.macro_hist = deque(maxlen=SLOPE_LOOKBACK + 1)
        self.cpv = 0.0
        self.cv = 0.0
        self.ms = None                    # MinuteState of the last completed minute
        self.session_open = NAN           # open of the first 10-s candle of the entry window (05:00)
        self.rows = 0                     # live: 10-s candles (with trades) seen today, from 04:00
        self.equity = REPLAY_EQUITY       # replay sizing (live uses the TradeZero equity)
        self.last_bar_t = 0               # start of the last 10-s candle processed
        self.last_close = NAN
        self.pm_high = 0.0
        self.pm_volume = 0.0
        self.a9 = 2.0 / (EMA_PERIOD + 1)
        self.am = 2.0 / (MACRO_EMA_PERIOD + 1)

    # ---------------------------------------------------------------- 1-minute macro logic
    def _add_1m(self, bar):
        i = len(self.b1)
        self.b1.append(bar)
        self.ema9 = bar.c if isnan(self.ema9) else self.ema9 + self.a9 * (bar.c - self.ema9)
        self.macro = bar.c if isnan(self.macro) else self.macro + self.am * (bar.c - self.macro)
        self.macro_hist.append(self.macro)
        slope = self.macro_hist[-1] - self.macro_hist[0] if len(self.macro_hist) == SLOPE_LOOKBACK + 1 else NAN
        self.cpv += bar.c * bar.v
        self.cv += bar.v
        vwap = self.cpv / self.cv if self.cv > 0 else NAN
        self.vwap_hist.append(vwap)
        rvol = 999.0                                     # backtest: rolling(10, min_periods=1) of the earlier minutes
        if i >= 1:
            prev = self.b1[max(0, i - RVOL_LEN):i]
            avg = sum(b.v for b in prev) / len(prev)
            rvol = bar.v / avg if avg > 0 else 999.0
        ms = MinuteState(bar_t=bar.t, for_t=bar.t + 60, close=bar.c, ema9=self.ema9, slope=slope, vwap=vwap, rvol=rvol)
        # momentum chase (this minute): +3% green, RVOL MOM_RVOL+, 20k+ shares, close in the top MOM_STRONG_CLOSE of the range
        rng = bar.h - bar.l
        strong = rng > 0 and (bar.h - bar.c) / rng <= MOM_STRONG_CLOSE
        if (bar.o > 0 and (bar.c - bar.o) / bar.o >= MOM_SURGE_PCT and rvol >= MOM_RVOL and bar.v >= MOM_MIN_VOLUME
                and strong):
            ms.mom_trigger, ms.mom_stop = bar.h + TICK, bar.l - TICK
        # bull flag (window = the 5 minutes BEFORE this one) - off in v1.2
        if BULL_FLAG_ENABLED and i >= FLAG_LOOKBACK:
            w = self.b1[i - FLAG_LOOKBACK:i]
            highs = [b.h for b in w]
            peak = max(highs)
            rel = highs.index(peak)
            since = (FLAG_LOOKBACK - 1) - rel
            if 1 <= since <= FLAG_LOOKBACK - 1:
                pole_open = self.b1[max(0, (i - FLAG_LOOKBACK) + rel - FLAG_POLE_BACK)].o
                vel = (w[rel].c - pole_open) / pole_open if pole_open > 0 else NAN
                if not isnan(vel) and vel >= FLAG_MIN_VELOCITY:
                    f_low = min(b.l for b in w[rel + 1:])
                    ms.flag_velocity = vel
                    ms.flag_drop = (peak - f_low) / peak
                    ms.flag_trigger = peak + TICK
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
        if len(rows) >= VELOCITY_LOOKBACK_ROWS:
            return rows[-VELOCITY_LOOKBACK_ROWS].o
        first10 = rows[0].t if rows else t
        mins = [b for b in self.b1 if b.t < first10 // 60 * 60]
        if mins:
            k = -(-(VELOCITY_LOOKBACK_ROWS - len(rows)) // 6)
            return mins[max(0, len(mins) - k)].o
        return rows[0].o if rows else NAN

    def _set_velocity(self, t):
        d = self.day
        then = self._velocity_ref(t)
        d.velocity_gain = (then - self.pc) / self.pc if not isnan(then) and self.pc > 0 else NAN
        d.momentum_allowed = not isnan(d.velocity_gain) and d.velocity_gain <= VELOCITY_MAX_GAIN

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
            if (d.session_high - close) / d.session_high >= BACKSIDE_LOCK_PCT:
                d.backside_locked = True

    def on_tick_high(self, price):
        """Live: a trade at/above the session high lifts the backside lock the moment it prints (the old script
        did it with the candle's high, then filled at that candle's open - a price live trading cannot get)."""
        d = self.day
        if d.discovered_t is not None and price >= d.session_high > 0:
            d.session_high = price
            d.backside_locked = False

    def _trail_level(self, t_cur):
        lo, hi = t_cur - TRAIL_WINDOW[0], t_cur - TRAIL_WINDOW[1]
        lows = [b.l for b in self.b10 if lo <= b.t <= hi]
        return min(lows) - TICK if lows else NAN

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
        if now - d.discovered_t < SCANNER_DELAY_SEC or d.backside_locked or not in_session(now):
            return None
        if now - d.discovered_t > FRESH_ENTRY_SEC:
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
        if trigger is None and BULL_FLAG_ENABLED and (not mom_pending or FLAG_WHEN_MOMENTUM_PENDING):
            if (not isnan(ms.flag_trigger) and ms.flag_drop <= FLAG_MAX_DROP and not isnan(ms.slope) and ms.slope > 0
                    and not isnan(ms.rvol) and ms.rvol >= FLAG_RVOL and high >= ms.flag_trigger):
                trigger, stop, name = ms.flag_trigger, ms.flag_low - TICK, BULL_FLAG
        if trigger is None or not (MIN_ENTRY_PRICE <= trigger <= MAX_ENTRY_PRICE):
            return None
        if trigger < self.pc * (1.0 + MIN_GAP_PCT):
            return None                                   # the trigger itself must be +30% up
        if self.too_extended(max(trigger, open_px) * (1 + SLIPPAGE_PCT)):
            return None
        mult = TARGET_MULT_STRONG if (not isnan(ms.rvol) and ms.rvol >= STRONG_RVOL and ms.close > ms.ema9) else TARGET_MULT
        return {"strategy": name, "trigger": trigger, "stop": stop, "mult": mult, "ref": max(trigger, open_px),
                "key": (name, ms.bar_t), "rvol": ms.rvol, "vwap": ms.vwap, "minute": ms.for_t}

    def too_extended(self, price):
        """More than MAX_EXT_FROM_OPEN (300%) above the open of the entry window = no entry."""
        so = self.session_open
        return not isnan(so) and so > 0 and (price - so) / so > MAX_EXT_FROM_OPEN

    @staticmethod
    def size_for(sig, price, equity):
        """ACCOUNT_PCT of the account equity (compounding), max MAX_POSITION_USD. Even share count; under 2 shares =
        no trade. (1.7: no cut for the stop distance - the stop is at most MAX_RISK_PCT under the entry.)"""
        if price <= 0 or not equity or equity <= 0:
            return 0
        return max(0, int(position_usd(equity) / price) // 2 * 2)

    def open_position(self, sig, avg, shares, t):
        risk = clamp_risk(avg, sig["stop"])
        p = Position(sig["strategy"], avg, avg - risk, avg + risk * sig["mult"], risk, shares, t)
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
            if d.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                d.halted, d.halt_reason = True, f"{MAX_CONSECUTIVE_LOSSES} stop-outs in a row"
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
        if not p.partial and price <= p.stop * (1 + STOP_EARLY_PCT / 100.0):
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
        warm = self.rows >= WARMUP_ROWS                  # the backtest skips the day's first 20 ten-second candles
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
                if not p.partial and bar.l <= p.stop * (1 + STOP_EARLY_PCT / 100.0) and bar.t > p.bar_t:
                    events.append({"type": "exit", "reason": STOP_OUT, "shares": p.shares})
                elif (bar.t - p.bar_t >= MAX_HOLD_MIN_WITHOUT_PROFIT * 60 and not p.partial
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
        Like the backtest, the first WARMUP_ROWS 10-second candles of the day (with trades, from 04:00) are history
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
                if n_min >= WARMUP_ROWS and in_session(b.t):
                    if isnan(self.session_open):
                        self.session_open = b.o
                    if b.h >= self.alert:
                        disc_t = b.t
                n_min += 1
            else:                                        # the minute's 10-s candles decide (exact rows)
                for row, x in by_min.get(b.t, []):
                    if row >= WARMUP_ROWS and in_session(x.t):
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
    def replay_bar(self, bar, slip=SLIPPAGE_PCT, logic=True):
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
        synced = t - d.discovered_t >= SCANNER_DELAY_SEC
        self._session_update(bar.h, bar.c)
        p = d.pos
        if p is not None:
            trig = p.stop * (1 + STOP_EARLY_PCT / 100.0)
            if not p.partial and bar.l <= trig:
                return [self.close_leg(p.shares, min(trig, bar.o) * (1 - slip), STOP_OUT, t)]
            if t - p.bar_t >= MAX_HOLD_MIN_WITHOUT_PROFIT * 60 and not p.partial and bar.h < p.entry + p.risk:
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


def replay_day(sym, prior_close, bars10, slip=SLIPPAGE_PCT, warmup=WARMUP_ROWS, equity=None):
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
# LIVE MODULE - runs inside Kestrel (shares its IB connection, TradeZero client and Discord)
# Adapted from lh_long_bot.py 1.0: same Feed / Trader / order logic, one asyncio loop with the app.
# =============================================================================
import asyncio
import csv
import io
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from ib_async import Stock, ScannerSubscription, TagValue
except ImportError:
    try:
        from ib_insync import Stock, ScannerSubscription, TagValue
    except ImportError:
        Stock = ScannerSubscription = TagValue = None

log = logging.getLogger("lh_app.long")
_wall = time.time                  # wall clock (the tests replace it)
_mono = time.monotonic

SCAN_START_S = hms_secs(SCAN_START)
CUTOFF_S = hms_secs(ENTRY_CUTOFF)
FLATTEN_S = hms_secs(FLATTEN_AT)
RTH_OPEN_S = hms_secs(RTH_OPEN)
RESIDUAL_ALERT_S = hms_secs(RESIDUAL_ALERT_AT)
DONE_STATES = ("Filled", "Canceled", "Rejected", "DoneForDay", "Expired")




def daily_loss_limit(account):
    """$ of realized long loss today after which no new longs are opened (0 = account unknown, no check):
    DAILY_LOSS_PCT_OF_POSITION of the long position size at the start of the day (ACCOUNT_PCT of the start-of-day
    equity, max MAX_POSITION_USD).  $10,000 -> $2,000 position -> $1,000;  $50,000 and more -> $10,000 -> $5,000."""
    if not account or account <= 0:
        return 0.0
    return position_usd(account) * DAILY_LOSS_PCT_OF_POSITION / 100.0


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


def _fp(x):
    return "-" if x is None or x != x else (f"{x:.4f}" if x < 1 else f"{x:.2f}")


def _money(x):
    return "-" if x is None else ("-" if x < 0 else "") + f"${abs(x):,.2f}"


def _pos(x):
    return x is not None and x == x and x > 0


def _r(x, nd=4):
    return None if x is None or x != x else round(float(x), nd)


def _bars(ib_bars):
    out = []
    for b in ib_bars or []:
        d = b.date
        if not isinstance(d, datetime):
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        v = _fnum(b.volume)
        if v > 0:
            out.append(Bar(int(d.timestamp()), b.open, b.high, b.low, b.close, v))
    return out


# -----------------------------------------------------------------------------
# CHART IMAGE (1-minute candles, VWAP, +30% line, trade levels and marks) - thread-safe (no pyplot)
# -----------------------------------------------------------------------------
def chart_snapshot(eng, minutes=120):
    if eng is None:
        return None
    bars = list(eng.b1)
    vw = list(eng.vwap_hist)
    if eng.cur is not None:
        c = eng.cur
        bars.append(Bar(c.t, c.o, c.h, c.l, c.c, c.v))
        vw.append(vw[-1] if vw else NAN)
    return {"bars": [(b.t, b.o, b.h, b.l, b.c, b.v) for b in bars[-minutes:]], "vwap": vw[-minutes:],
            "alert": eng.alert, "pc": eng.pc}


def render_chart_png(sym, snap, title="", levels=(), marks=()):
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Rectangle
    except Exception:
        return None
    rows = (snap or {}).get("bars") or []
    if len(rows) < 3:
        return None
    BG, GRID, MUTED, TXT = "#0e0f11", "#1b1d21", "#80858e", "#d6d9de"      # 1.6: black, white up / red down
    UP, DN = "#e6e8eb", "#f23645"
    n = len(rows)
    fig = Figure(figsize=(10, 5.6), dpi=100, facecolor=BG)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.05, 0.27, 0.83, 0.62], facecolor=BG)
    axv = fig.add_axes([0.05, 0.07, 0.83, 0.18], facecolor=BG, sharex=ax)
    for a in (ax, axv):
        a.tick_params(colors=MUTED, labelsize=8)
        a.grid(color=GRID, lw=0.6)
        for s in a.spines.values():
            s.set_visible(False)
        a.yaxis.tick_right()
    for lbl in ax.get_xticklabels():
        lbl.set_visible(False)
    lo, hi = min(r[3] for r in rows), max(r[2] for r in rows)
    for k, (t, o, h, l, c, v) in enumerate(rows):
        col = UP if c >= o else DN
        ax.plot([k, k], [l, h], color=col, lw=1, zorder=2)
        ax.add_patch(Rectangle((k - 0.32, min(o, c)), 0.64, max(abs(c - o), (hi - lo) * 0.002), color=col, zorder=3))
        axv.bar(k, v, color=col, alpha=0.4 if c >= o else 0.6, width=0.7)
    vw = [x if x == x else None for x in snap["vwap"]]
    xs = [k for k, x in enumerate(vw) if x is not None]
    if xs:
        ax.plot(xs, [vw[k] for k in xs], color="#ff9800", lw=1.2, zorder=4)
        ax.text(n + 0.6, vw[xs[-1]], "VWAP", color="#ff9800", fontsize=8, va="center")
    lv_all = [{"price": snap["alert"], "color": "#ffd600", "style": "dot", "title": f"+{MIN_GAP_PCT * 100:g}%"}] + list(levels or [])
    for lv in lv_all:
        p = lv.get("price")
        if not _pos(p):
            continue
        if lo - (hi - lo) * 0.6 <= p <= hi + (hi - lo) * 0.6:
            lo, hi = min(lo, p), max(hi, p)
            ax.axhline(p, color=lv["color"], lw=1, ls={"dash": "--", "dot": ":"}.get(lv.get("style"), "-"), zorder=1)
            ax.text(n + 0.6, p, f"{lv.get('title', '')} {_fp(p)}", color=lv["color"], fontsize=8, va="center", zorder=4,
                    bbox={"facecolor": BG, "edgecolor": "none", "pad": 1.5})
    times = [r[0] for r in rows]
    for m in marks or []:
        if not _pos(m.get("price")):
            continue
        tm = int(m["t"]) // 60 * 60
        k = min(range(n), key=lambda j: abs(times[j] - tm))
        up = m.get("up", True)
        ax.scatter([k], [m["price"]], marker="^" if up else "v", s=110, color=m.get("color", TXT), zorder=6)
        ax.annotate(m.get("text", ""), (k, m["price"]), textcoords="offset points", xytext=(0, -16 if up else 10),
                    ha="center", color=m.get("color", TXT), fontsize=8, fontweight="bold")
    pad = (hi - lo) * 0.08 or hi * 0.02
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-1, n + 9)
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    axv.set_xticks(ticks)
    axv.set_xticklabels([et_dt(times[k]).strftime("%H:%M") for k in ticks])
    title = re.sub("[\u2600-\u27bf\ufe0f\U0001f000-\U0001faff]", "", title or "").strip()   # no emoji in the font
    fig.text(0.05, 0.93, f"{sym}  {title}".replace("$", r"\$"), color=TXT, fontsize=12, fontweight="bold")
    fig.text(0.88, 0.93, f"prior close {_fp(snap['pc'])}  |  1-min ET  |  premarket long", color=MUTED, fontsize=8,
             ha="right")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    return buf.getvalue()


# -----------------------------------------------------------------------------
# 5-SECOND REAL-TIME BARS -> COMPLETED 10-SECOND CANDLES  (verbatim)
# -----------------------------------------------------------------------------
class Feed:
    def __init__(self, on_bar10, on_minute_closed):
        self.on_bar10, self.on_minute_closed = on_bar10, on_minute_closed
        self.bucket = None               # [t, o, h, l, c, v] of the 10-s candle being built
        self.last_t = 0
        self.min_bucket = 0              # 10-s candles at or before this were loaded from history

    def push(self, t, o, h, l, c, v):
        if t <= self.last_t:
            return
        self.last_t = t
        b = t - t % 10
        if self.bucket is not None and self.bucket[0] != b:
            self._emit()
        if b > self.min_bucket and v > 0 and h > 0:
            if self.bucket is None:
                self.bucket = [b, o, h, l, c, v]
            else:
                bk = self.bucket
                bk[2], bk[3], bk[4], bk[5] = max(bk[2], h), min(bk[3], l), c, bk[5] + v
        if t % 10 == 5:
            self._emit()                  # second half of the 10 seconds arrived: candle complete
        if t % 60 == 55:
            self.on_minute_closed(t - 55)  # the minute's last 5 seconds arrived (even with no trades)

    def _emit(self):
        bk, self.bucket = self.bucket, None
        if bk is not None and bk[5] > 0:
            self.on_bar10(Bar(*bk))


# -----------------------------------------------------------------------------
# ONE SYMBOL: data subscription + strategy engine + its orders
# -----------------------------------------------------------------------------
class Trader:
    def __init__(self, bot, sym, contract, pc, day):
        self.bot, self.sym, self.contract, self.pc, self.day = bot, sym, contract, pc, day
        self.eng = None
        self.feed = None
        self.rtb = self.ticker = None
        self.last = self.bid = self.ask = NAN
        self.last_bar_mono = _mono()
        self.seeding = True
        self.buffer = []
        self.task = None
        self.block_key = None
        self.below_since = None
        self.added_t = bot.now()
        self.active = True
        self.halt_sent = False
        self.next_residual = 0.0         # after the 09:00 flatten: next sell try (monotonic)
        self.settle_until = 0.0          # 1.7: after the bot's own fill / sell - no position comparison until then
        self.exit_round = 0              # 1.7: sell rounds that did not sell everything (each one steps deeper)
        self.unsold_alert = 0.0          # 1.7: last "could not sell" message (monotonic)
        self.halted = False              # 1.9: IB says halted (tick 49) - no sell is sent until it trades again
        self.exit_t0 = None              # 1.9: when the current exit started (the floor widens with time)

    # ---------------- subscription ----------------
    async def start(self):
        ib = self.bot.ib
        self.seeding, self.buffer = True, []
        self.feed = Feed(self._on_bar10, self._on_minute_closed)
        self.rtb = ib.reqRealTimeBars(self.contract, 5, "TRADES", False)
        self.rtb.updateEvent += self._on_rtb
        self.ticker = ib.reqMktData(self.contract, "", False, False)
        self.ticker.updateEvent += self._on_tick
        bars1, bars10 = await self.bot.fetch_history(self.contract)
        now = self.bot.now()
        eng = LongEngine(self.sym, self.pc, self.day)
        eng.seed(bars1, bars10, now)
        self.eng = eng
        self.feed.min_bucket = eng.last_bar_t
        for args in self.buffer:                     # 5-s bars that arrived while the history loaded
            self.feed.push(*args)
        self.buffer, self.seeding = [], False
        self.last_bar_mono = _mono()

    def stop(self):
        self.active = False
        ib = self.bot.ib
        try:
            if self.rtb is not None:
                self.rtb.updateEvent -= self._on_rtb
                if ib is not None and ib.isConnected():
                    ib.cancelRealTimeBars(self.rtb)
        except Exception:
            pass
        try:
            if self.ticker is not None:
                self.ticker.updateEvent -= self._on_tick
                if ib is not None and ib.isConnected():
                    ib.cancelMktData(self.contract)
        except Exception:
            pass
        self.rtb = self.ticker = None

    async def restart(self):
        """IB reconnected / stream stalled: re-subscribe and rebuild the indicators (position kept)."""
        self.stop()
        self.active = True
        await self.start()

    # ---------------- market data events ----------------
    def _on_rtb(self, bars, has_new):
        if not has_new or not bars:
            return
        b = bars[-1]
        d = b.time if b.time.tzinfo else b.time.replace(tzinfo=timezone.utc)
        args = (int(d.timestamp()), _fnum(getattr(b, "open_", getattr(b, "open", 0))), _fnum(b.high), _fnum(b.low),
                _fnum(b.close), _fnum(b.volume))
        self.last_bar_mono = _mono()
        if self.seeding:
            self.buffer.append(args)
            return
        try:
            self.feed.push(*args)
        except Exception:
            log.exception("%s feed", self.sym)

    def _on_minute_closed(self, minute_t):
        if self.eng is not None:
            self.eng.close_minute(minute_t)

    def _missed(self):
        """3.15: the bot's missed-trade log (None when the long runs without the app, e.g. the replay)."""
        return getattr(getattr(self.bot, "host", None), "missed", None)

    def _miss(self, sig, why):
        """3.15: a long signal not taken -> the missed-trade log (a copy of this engine follows it to its exit)."""
        m = self._missed()
        if m is None or self.eng is None:
            return
        try:
            px = float(sig["trigger"])
            eq = self.bot.equity() or 0.0
            shares = LongEngine.size_for(sig, px, eq) if eq > 0 else int(MAX_POSITION_USD / px) // 2 * 2
            m.long(self.sym, "Premarket long", self.eng, sig, px, shares, why, self.bot.now(), FLATTEN_S)
        except Exception:
            log.exception("%s missed long", self.sym)

    def _on_bar10(self, bar):
        if self.eng is None:
            return
        m = self._missed()
        if m is not None and not self.seeding:            # 3.15: missed longs follow the same candles
            try:
                m.long_bar(self.sym, bar)
            except Exception:
                log.exception("%s missed long bar", self.sym)
        for ev in self.eng.on_bar_10s(bar):
            if ev["type"] == "exit" and not self.busy() and self.day.pos is not None:
                self._spawn(self._exit(ev["reason"], ev["shares"]))
        self._halt_note()

    def _on_tick(self, tk):
        hv = getattr(tk, "halted", None)
        try:
            self.halted = hv is not None and float(hv) == float(hv) and float(hv) > 0
        except (TypeError, ValueError):
            self.halted = False
        if self.halted:
            return                                       # 1.9: prices during a halt are indications - ignored
        if _pos(tk.bid):
            self.bid = float(tk.bid)
        if _pos(tk.ask):
            self.ask = float(tk.ask)
        if _pos(tk.last):
            self.last = float(tk.last)
            if not self.seeding:
                try:
                    self.on_price(self.last)
                except Exception:
                    log.exception("%s on_price", self.sym)

    # ---------------- decisions ----------------
    def busy(self):
        return self.task is not None and not self.task.done()

    def _spawn(self, coro):
        self.task = asyncio.ensure_future(self._guard(coro))

    async def _guard(self, coro):
        try:
            await coro
        except Exception as exc:
            log.exception("%s order step", self.sym)
            self.bot.notify(f"❌ {self.sym}: order step failed", f"{exc.__class__.__name__}: {exc}", "err")

    def on_price(self, p):
        m = self._missed()
        if m is not None and m.open:                      # 3.15: missed longs follow the ticks too
            try:
                m.long_price(self.sym, p, self.bot.now())
            except Exception:
                log.exception("%s missed long tick", self.sym)
        if not self.active or self.eng is None or self.busy():
            return
        now = self.bot.now()
        self.eng.on_tick_high(p)
        if self.day.pos is not None:
            if self.bot.flattened:
                return                                   # after 09:00 the flatten / residual loop owns the exit
            req = self.eng.exit_on_price(p, now)
            if req:
                self._spawn(self._exit(*req))
            return
        if not self.bot.entries_open():
            return
        sig = self.eng.entry_signal(p, p, now)
        if not sig or sig["key"] == self.block_key:
            return
        why = self.bot.why_no_entry(self.sym)
        if why:
            self.block_key = sig["key"]
            self.bot.log_once((self.sym, sig["key"]), f"{self.sym}: {sig['strategy']} trigger {_fp(sig['trigger'])} - "
                                                      f"not taken ({why})")
            if why != "entries closed":
                self._miss(sig, why)
            return
        self._spawn(self._enter(sig))

    def _halt_note(self):
        d = self.day
        if d.halted and not self.halt_sent:
            self.halt_sent = True
            self.bot.notify(f"⛔ {self.sym}: done for today", f"Strategy limit: {d.halt_reason}. Monitoring ends once flat.",
                            "warn")

    # ---------------- entry: buy limit at the ask ----------------
    async def _enter(self, sig):
        bot = self.bot
        ask = self.ask if _pos(self.ask) else self.last
        key = sig["key"]
        if not _pos(ask):
            self.block_key = key
            return
        if ask > sig["trigger"] * (1 + MAX_CHASE_PCT / 100.0):
            self.block_key = key
            bot.log_once((self.sym, key), f"{self.sym}: {sig['strategy']} trigger {_fp(sig['trigger'])} but ask "
                                          f"{_fp(ask)} is {(ask / sig['trigger'] - 1) * 100:.1f}% above - skipped")
            self._miss(sig, f"ask {(ask / sig['trigger'] - 1) * 100:.1f}% over the trigger (chase cap)")
            return
        eq = bot.equity()
        if eq <= 0:
            self.block_key = key
            bot.log_once((self.sym, key, "eq"), f"{self.sym}: {sig['strategy']} trigger {_fp(sig['trigger'])} - not "
                                                 f"taken (account equity unknown - is TradeZero connected?)")
            self._miss(sig, "account equity unknown")
            return
        shares = LongEngine.size_for(sig, ask, eq)
        self.day.loss_limit = stock_loss_limit(eq)
        bp = bot.buying_power()
        if bp > 0 and shares * ask > bp * 0.95:
            shares = int(bp * 0.95 / ask) // 2 * 2
        if shares < 2:
            self.block_key = key
            self._miss(sig, "buying power too small for 2 shares")
            return
        why = bot.why_no_entry(self.sym)                  # re-checked right before the order (the short side may
        if why:                                           # have changed meanwhile)
            self.block_key = key
            self._miss(sig, why)
            return
        limit = px_round(ask, up=True)
        coid = bot.coid(self.sym, "B")
        risk = clamp_risk(limit, sig["stop"])
        if bot.alert:                                     # 1.8: trading mode "Alert only" - post it, no order
            self.block_key = key
            bot.notify(f"{self.sym} - {sig['strategy']} long  ·  ALERT ONLY",
                       "Why: the premarket long is set to Alert only - no order.\nTurn it on in the app: menu → Trading "
                       "mode → Premarket long → Trading.", "warn", tag="SIGNAL  ·  NOT TRADED",
                       fields=[("Would buy", f"{shares:,} @ {_fp(limit)}", True), ("Stop", _fp(limit - risk), True),
                               ("Target", f"{sig['mult']:g}R", True)], trader=self)
            return
        bot.notify(f"{self.sym} - buying {shares:,} @ {_fp(limit)}",
                   f"Trigger {_fp(sig['trigger'])} hit (last {_fp(self.last)}). Limit at the ask {_fp(limit)}, "
                   f"stop ≈ {_fp(limit - risk)} ({risk / limit * 100:.1f}%), target {sig['mult']:g}R. "
                   f"Size {_money(shares * limit)} ({ACCOUNT_PCT:g}% of equity {_money(eq)}"
                   f"{f', capped at {_money(MAX_POSITION_USD)}' if eq * ACCOUNT_PCT / 100.0 > MAX_POSITION_USD else ''}"
                   f"), loss at the stop ≈ {_money(shares * risk)}. RVOL {sig['rvol']:.1f}, 1-min VWAP {_fp(sig['vwap'])}.",
                   "dim", tag=f"LONG SIGNAL  ·  {sig['strategy']}".upper())
        rec = bot.note_buy(self.sym, coid, sig, shares, limit)       # 1.7: every buy of today is remembered
        try:
            o = await bot.place(self.sym, "Buy", "Open", "Limit", shares, EXT_TIF, limit=limit, coid=coid)
        except bot.TZError as exc:
            self.block_key = key
            bot.buy_unknown(self, rec, exc)                          # 1.7: it may have filled anyway - the guard checks
            return
        if o.get("orderStatus") == "Rejected":
            self.block_key = key
            bot.notify(f"❌ {self.sym}: buy order rejected", str(o.get("text") or ""), "err")
            return
        rec["coid"] = o.get("clientOrderId") or coid
        filled, avg = await self._wait_fill(rec["coid"], o, ENTRY_TIMEOUT_SEC, limit)
        self.settle_until = _mono() + SETTLE_SEC
        rec["state"] = "filled" if filled > 0 else "none"
        if filled <= 0:
            self.block_key = key
            bot.notify(f"⚪ {self.sym}: entry not filled", f"Buy {shares:,} @ {_fp(limit)} cancelled after "
                                                          f"{ENTRY_TIMEOUT_SEC:g}s. Waiting for the next setup.", "dim")
            return
        rec["state"] = "managed"
        pos = self.eng.open_position(sig, avg, filled, bot.now())
        bot.on_entry(self, pos, sig, shares)

    async def _wait_fill(self, coid, o, timeout, ref_px):
        """Poll an order until filled / done or `timeout`, then cancel the rest. Returns (shares, avg price)."""
        bot = self.bot
        deadline = _mono() + timeout
        while True:
            st = str(o.get("orderStatus") or "")
            if st == "Filled" or st in DONE_STATES:
                break
            if _mono() >= deadline:
                try:
                    await bot.tz_call(bot.host.tz.cancel, bot.host.acc, coid)
                except bot.TZError:
                    pass
                o = await bot.wait_done(coid) or o
                break
            await asyncio.sleep(ORDER_POLL_SEC)
            try:
                o = await bot.tz_call(bot.host.tz.order, bot.host.acc, coid) or o
            except bot.TZError:
                pass
        n = int(_fnum(o.get("executed")))
        avg = _fnum(o.get("priceAvg"), 0.0) or ref_px
        return n, avg

    # ---------------- exit: sell limit at the bid (market from the 09:30 open) ----------------
    async def _exit(self, reason, shares, market=False):
        """Sell: limit at the bid, re-priced deeper every EXIT_REPRICE_SEC (market orders from the 09:30 open).
        1.7: an order that errors is looked up / retried at once (never a reason to stop selling); every round that
        does not sell everything starts deeper under the bid (up to EXIT_MAX_DEPTH_PCT)."""
        bot, eng = self.bot, self.eng
        p = self.day.pos
        if p is None or p.shares <= 0:
            return
        want = min(int(shares), p.shares)
        sold, cost, tries = 0, 0.0, 0
        last_text = ""
        market = market and bot.in_rth()                 # TradeZero: no market orders before the open
        max_tries = (RTH_SELL_MARKET_AFTER + 4) if (market or bot.in_rth()) else EXIT_MAX_TRIES
        if self.exit_t0 is None:
            self.exit_t0 = _mono()
        while sold < want and tries < max_tries:
            if self.halted:                              # 1.9: halted - TradeZero takes no sell; wait for trading
                if not getattr(self, "halt_wait_sent", False):
                    self.halt_wait_sent = True
                    bot.notify(f"⏸ {self.sym}: halted - the sell ({reason}) goes the instant it trades again",
                               "Prices shown during the halt are ignored.", "warn", ping=True)
                await asyncio.sleep(0.25)
                if self.day.pos is None or not self.active:
                    break
                continue
            self.halt_wait_sent = False
            tries += 1
            left = want - sold
            coid = bot.coid(self.sym, "S")
            px_sent = self.bid if _pos(self.bid) else self.last
            try:
                ref = self._sell_ref(p)
                rth = bot.in_rth()
                if rth and tries > RTH_SELL_MARKET_AFTER:  # 1.9: the collar did not sell: market now
                    o = await bot.place(self.sym, "Sell", "Close", "Market", left, "Day", coid=coid)
                    timeout = 6.0
                elif rth:                                # 1.9: a marketable limit under the bid, not a market order
                    depth = RTH_SELL_COLLAR_PCT + EXIT_STEP_PCT * (tries - 1)
                    lim = max(px_round(ref * (1 - depth / 100.0), up=False), self._sell_floor(ref))
                    px_sent = lim
                    o = await bot.place(self.sym, "Sell", "Close", "Limit", left, "Day", limit=lim, coid=coid)
                    ref, timeout = lim, RTH_REPRICE_SEC
                else:
                    depth = min(EXIT_STEP_PCT * (tries - 1 + self.exit_round * EXIT_MAX_TRIES), EXIT_MAX_DEPTH_PCT)
                    lim = max(px_round(ref * (1 - depth / 100.0), up=False), self._sell_floor(ref))
                    px_sent = lim
                    o = await bot.place(self.sym, "Sell", "Close", "Limit", left, EXT_TIF, limit=lim, coid=coid)
                    ref, timeout = lim, EXIT_REPRICE_SEC
            except bot.TZError as exc:                   # not sent / no trace of it at TradeZero: try again now
                last_text = bot.clean(str(exc))
                log.warning("%s sell failed: %s", self.sym, last_text)
                want, gone = await self._verify(want, sold, px_sent, reason)
                if gone:
                    break
                await asyncio.sleep(ORDER_RETRY_PAUSE_SEC)
                continue
            if o.get("orderStatus") == "Rejected":
                last_text = str(o.get("text") or "rejected")
                log.warning("%s sell rejected: %s", self.sym, last_text)
                want, gone = await self._verify(want, sold, None, reason)   # 1.7: shares gone at TradeZero?
                if gone:
                    break
                await asyncio.sleep(ORDER_RETRY_PAUSE_SEC)
                continue
            cid = o.get("clientOrderId") or coid
            n, avg = await self._wait_fill(cid, o, timeout, ref)
            if n > 0:
                sold += n
                cost += n * avg
                bot.booked_sells.add(cid)
        self.settle_until = _mono() + SETTLE_SEC
        if sold > 0:
            leg = eng.close_leg(sold, cost / sold, reason, bot.now())
            bot.on_exit(self, leg)
        if sold < want:
            self.exit_round += 1
            if _mono() - self.unsold_alert >= UNSOLD_ALERT_EVERY_SEC:
                self.unsold_alert = _mono()
                bot.notify(f"\U0001F6A8 {self.sym}: could not sell {want - sold:,} shares yet ({reason})",
                           f"{last_text or 'not filled'}. The bot keeps selling" +
                           (" every 20 s (at market from 09:30)." if bot.flattened else
                            " - each round deeper under the bid - until TradeZero shows it flat.") +
                           " Check TradeZero.", "err", ping=True)
        else:
            self.exit_round = 0
            self.exit_t0 = None

    def _sell_ref(self, p):
        """1.9: the price a sell is based on: the bid - unless it is BID_SANE_PCT+ under the last trade (an empty book /
        a fake quote), then the last trade."""
        last = self.last if _pos(self.last) else None
        bid = self.bid if _pos(self.bid) else None
        if bid and (last is None or bid >= last * (1 - BID_SANE_PCT / 100.0)):
            return bid
        return last or bid or p.entry

    def _sell_floor(self, ref):
        """1.9: never priced more than EXIT_FLOOR_PCT under the last trade; the floor widens with time (EXIT_FLOOR_STEP_PCT
        every EXIT_FLOOR_STEP_SEC) up to EXIT_MAX_DEPTH_PCT - it always sells, but never into a hole at once."""
        base = self.last if _pos(self.last) else ref
        t0 = self.exit_t0 if self.exit_t0 is not None else _mono()
        pct = min(EXIT_FLOOR_PCT + EXIT_FLOOR_STEP_PCT * int((_mono() - t0) // EXIT_FLOOR_STEP_SEC), EXIT_MAX_DEPTH_PCT)
        return px_round(base * (1 - pct / 100.0), up=True)

    async def _verify(self, want, sold, px_sent, reason):
        """1.7, inside a sell: a sell errored or was rejected - read TradeZero's position. Shares already gone there (a
        sell of this step whose answer was lost, or sold by you) count for this step and are booked at their real
        fill price (waiting up to VERIFY_PRICE_WAIT_SEC for that order to show; else the lost sell's limit price) -
        never sold twice. Returns (want, True if nothing is left to sell in this step)."""
        bot = self.bot
        p = self.day.pos
        if p is None:
            return want, True
        try:
            pos = await bot.tz_call(bot.host.tz.positions, bot.host.acc)
        except bot.TZError:
            return want, False
        longs = bot._parse_longs(pos)
        bot.tz_longs = longs
        tz_sh = max(0, int(longs.get(self.sym, (0, 0.0))[0]) - bot._base(self.sym))
        expect = p.shares - sold                         # what TradeZero should show if only our fills happened
        if tz_sh >= expect:                              # (a lagging list shows MORE shares - never a false booking)
            return want, False
        gone = expect - tz_sh
        px, src = await bot._outside_sell_price(self.sym, gone)
        for _ in range(int(VERIFY_PRICE_WAIT_SEC / 0.5)):             # its order may show a moment later
            if _pos(px):
                break
            await asyncio.sleep(ORDER_LOOKUP_WAIT_SEC)
            px, src = await bot._outside_sell_price(self.sym, gone)
        if not _pos(px) and px_sent is not None and _pos(px_sent):
            px, src = px_sent, "the limit / bid of the sell whose answer was lost"
        if not _pos(px):
            px = self.bid if _pos(self.bid) else (self.last if _pos(self.last) else p.entry)
            src = "last price - no sell order found"
        if self.day.pos is None:
            return want, True
        gone = min(gone, self.day.pos.shares)
        leg = self.eng.close_leg(gone, px, reason, bot.now())     # booked as this step (half / stop / ...)
        bot.notify(f"⚠ {self.sym}: {gone:,} shares already sold at TradeZero",
                   f"A sell was answered with an error / rejected and TradeZero shows only {tz_sh:,} shares. Booked at "
                   f"{_fp(px)} ({src}) - not sold twice.", "warn", trader=self)
        bot.on_exit(self, leg)
        want = min(want - gone, sold + tz_sh)            # the gone shares count for this step (e.g. the half)
        return want, want <= sold or self.day.pos is None

    def done_reason(self, now):
        """Why this stock cannot be traded any more today ('' = it still can)."""
        d = self.day
        if d.discovered_t is None:
            return ""
        if not (BULL_FLAG_ENABLED or d.momentum_allowed):
            return "slow grind before the +30% cross (no momentum chase)"
        if now - d.discovered_t > FRESH_ENTRY_SEC:
            return f"{FRESH_ENTRY_SEC // 60}-minute entry window over (crossed +{MIN_GAP_PCT * 100:g}% at {et_hms(d.discovered_t)})"
        return ""

    def check_drop(self, now):
        """True = end monitoring: flat, no order step, and under +30% / $0.50 for DROP_GRACE_SEC, or done for today
        (limits hit, the 20-minute entry window over, no momentum chase armed)."""
        if self.day.pos is not None or self.busy() or self.seeding or self.bot.must_watch(self.sym):
            self.below_since = None                      # 1.7: never while TradeZero shows our shares / a buy is unsettled
            return False
        if self.day.halted or not self.bot.enabled or self.done_reason(now):
            return True
        px = self.last if _pos(self.last) else (self.eng.last_close if self.eng else NAN)
        if _pos(px) and px >= self.pc * (1 + MIN_GAP_PCT) and px >= MIN_ENTRY_PRICE:
            self.below_since = None
            return False
        if self.below_since is None:
            self.below_since = now
            return False
        return now - self.below_since >= DROP_GRACE_SEC


# -----------------------------------------------------------------------------
# THE PREMARKET LONG MODULE (one per app)
# -----------------------------------------------------------------------------
class LongModule:
    """host = the app's Bot (TradeZero client + account, Discord, bot log, settings, IB backend).
    tz_error = the app's TZError class (raised by the TradeZero client)."""

    def __init__(self, host, tz_error, data_dir):
        self.host = host
        self.TZError = tz_error
        self.enabled = bool(host.settings.get("long_on", LONG_ON_AT_START))
        self.alert = False              # 1.8: trading mode "Alert only" - setups go to Discord, no buy orders
        lm = host.long_mode() if hasattr(host, "long_mode") else None
        if lm in ("trading", "alert", "off"):           # 1.8 (app 3.10): the app's Trading mode rules ON / OFF
            self.enabled, self.alert = lm != "off", lm == "alert"
        self.tz_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tz-long")
        self.chart_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chart-long")
        self.msg_q = None
        self.traders = {}               # symbols streamed right now
        self.days = {}                  # symbol -> DayState (today), survives drops / re-adds
        self.cooldown = {}
        self.adding = set()
        self.add_sem = None
        self.err_once = set()
        self.logged = set()
        self.seq = 0
        self.trades_today = 0
        self.daily_stop_sent = False    # the "daily loss limit reached" Discord message went out today
        self.entries_closed = True
        self.session_on = False
        self.session_day = None         # the ET date of today's session (started or skipped)
        self.flattened = False          # 09:00 flatten done: the residual loop owns open longs
        self.residual_alerted = False
        self.scanning = False
        self.scan_n = self.scan_hits = self.scan_errors = 0
        self.scan_warned = False
        self.next_scan = 0.0
        self.next_heartbeat = float("inf")
        self.ib_was_up = False
        self.ib_hooked = None
        self.day = None
        self.journal = os.path.join(data_dir, "long_bot_trades.csv")
        self.pc_cache = {}
        self.last_push = ""
        self.closed_rows = []           # closed trades today (UI)
        # 1.7 safety: TradeZero is the truth
        self.contracts = {}             # symbol -> IB contract (to stream a symbol again when a long is found)
        self.buys = {}                  # symbol -> {"base": shares held before the bot's first buy today, "recs": [...]}
        self.pending = {}               # buy order id -> record: answered with an error, fill not known yet
        self.tz_longs = {}              # symbol -> (shares, avg price) at TradeZero, last positions read
        self.tz_ok_mono = _mono()       # last good positions read
        self.next_guard = 0.0
        self.guard_busy = False
        self.mismatch = {}              # symbol -> {"tz", "bot", "first", "n"}: a difference seen, not confirmed yet
        self.booked_sells = set()       # sell order ids whose fills the bot booked itself
        self.guard_alerted = False
        self.blind_alerted = set()      # symbols held at TradeZero the bot cannot get prices for (alerted)
        self.starting = set()           # symbols being streamed again for a found long

    # ---------------- links to the app ----------------
    @property
    def ib(self):
        return self.host.be.ib

    def now(self):
        off = getattr(self.host.be, "clock_offset", None)
        return _wall() + (off.total_seconds() if off is not None else 0.0)

    def et(self, ts=None):
        return et_dt(self.now() if ts is None else ts)

    def secs(self, ts=None):
        return et_secs(self.now() if ts is None else ts)

    def in_rth(self):
        return self.secs() >= RTH_OPEN_S

    def entries_open(self):
        return (self.enabled and self.session_on and not self.entries_closed and not self.flattened
                and SCAN_START_S <= self.secs() < CUTOFF_S)

    def holds(self, sym):
        """The long bot has shares (or an order step) in sym: the short bot must not short it now."""
        tr = self.traders.get(sym)
        return (tr is not None and (tr.day.pos is not None or tr.busy())) or self.must_watch(sym)

    def open_longs(self):
        return [t for t in self.traders.values() if t.day.pos is not None]

    async def tz_call(self, fn, *a, **k):
        return await asyncio.get_running_loop().run_in_executor(self.tz_pool, lambda: fn(*a, **k))

    def tz_ready(self):
        return self.host.tz_ready()

    def live_blocked(self):
        return self.host.live_blocked()

    def buying_power(self):
        info = self.host.acc_info or {}
        return _fnum(info.get("buyingPower", info.get("bp")), 0.0)

    def equity(self):
        """Account equity at TradeZero (the app refreshes it) - the 20% sizing compounds with it."""
        return _fnum((self.host.acc_info or {}).get("equity"), 0.0)

    def account_size(self):
        """The account the daily stop is a % of: TradeZero's start-of-day equity (the current equity if missing)."""
        sod = _fnum((self.host.acc_info or {}).get("sodEquity"), 0.0)
        return sod if sod > 0 else self.equity()

    def daily_loss_limit(self):
        return daily_loss_limit(self.account_size())

    def size_text(self):
        eq = self.equity()
        ls = stock_loss_limit(eq)
        acc = self.account_size()
        return (f"{ACCOUNT_PCT:g}% of equity per long, max {_money(MAX_POSITION_USD)}" +
                (f" (now {_money(position_usd(eq))})" if eq > 0 else "") +
                f", stop {MIN_RISK_PCT * 100:g}-{MAX_RISK_PCT * 100:g}% under the entry, a stock is done after losing "
                f"{MAX_LOSS_PER_STOCK_PCT:g}% of the position" +
                (f" ({_money(ls)})" if eq > 0 else "") + " - it grows with the account. Daily stop: no new longs after "
                f"a loss of {DAILY_LOSS_PCT_OF_POSITION:g}% of the long position size" +
                (f" = {_money(daily_loss_limit(acc))} today" if acc > 0 else "") +
                f". Buys skipped when the ask is more than {MAX_CHASE_PCT:g}% over the trigger")

    def clean(self, text):
        """Message text without the TradeZero account id (error texts carry it in the URL)."""
        text = str(text or "")
        acc = str(getattr(self.host, "acc", "") or "")
        return text.replace(acc, "(account)") if len(acc) >= 4 else text

    def coid(self, sym, tag):
        self.seq = (self.seq + 1) % 1000
        return f"LLB{tag}{re.sub(r'[^A-Z0-9]', '', sym)[:6]}{self.et():%H%M%S}{self.seq:03d}"

    # ---------------- logging / Discord ----------------
    def log_once(self, key, text):
        if key in self.logged:
            return
        self.logged.add(key)
        log.info(text)
        self.host._log("LONG " + text, "info")

    def notify(self, title, text="", kind="info", fields=None, trader=None, levels=None, marks=None, ping=False, tag=None):
        """Bot log + Discord (as "Longs"), in order. trader = attach that symbol's 1-minute chart. tag = the small line
        above the title (1.8 / app 3.10; None = picked from the title)."""
        title, text = self.clean(title), self.clean(text)       # 1.7: no account id in Discord / the log
        fields = [(n, self.clean(v), inl) for n, v, inl in (fields or [])] or None
        k = {"err": "err", "warn": "warn", "buy": "trade", "win": "trade", "loss": "trade", "partial": "trade",
             "trade": "trade"}.get(kind, "info")
        self.host._log(f"LONG {title}" + (f" - {text}" if text and len(text) < 140 else ""), k)
        dc = self.host.dc
        snap = chart_snapshot(trader.eng) if (trader is not None and DISCORD_CHART_IMAGES and dc.on) else None
        item = (title, text, kind, fields, trader.sym if trader else "", snap, levels, marks, ping, tag)
        if self.msg_q is not None:
            self.msg_q.put_nowait(item)
        elif dc.on:
            dc.send(title, text, kind, fields, ping=ping, username=DISCORD_USERNAME, tag=tag)

    async def _msg_worker(self):
        loop = asyncio.get_running_loop()
        while True:
            title, text, kind, fields, sym, snap, levels, marks, ping, tag = await self.msg_q.get()
            img = None
            if snap:
                try:
                    img = await loop.run_in_executor(self.chart_pool, render_chart_png, sym, snap,
                                                     title.split(":", 1)[-1].strip()[:60], levels or [], marks or [])
                except Exception:
                    log.exception("long chart")
            try:
                if self.host.dc.on:
                    self.host.dc.send(title, text, kind, fields, image=img, ping=ping, username=DISCORD_USERNAME, tag=tag)
            except Exception:
                log.exception("long discord")

    # ---------------- TradeZero orders ----------------
    async def place(self, sym, side, oc, typ, qty, tif, limit=None, coid=None):
        """Every order goes out here. If the network drops after the order may have reached TradeZero it is
        looked up by its id - never blindly sent twice (same recipe as the short bot)."""
        if not self.tz_ready():
            raise self.TZError(0, "TradeZero not connected", sent=False)
        if self.live_blocked():
            raise self.TZError(403, "LIVE account - orders blocked (ALLOW_LIVE_TRADING = False)", sent=False)
        h = self.host
        try:
            return await self.tz_call(h.tz.place, h.acc, sym, side, oc, typ, qty, tif, limit=limit,
                                      coid=coid, route=h.route) or {}
        except self.TZError as exc:
            # 1.7: ANY answer that is an error (16 Oct: HTTP 404 on a buy that filled) or no answer at all - the order
            # may be at TradeZero. Look it up by its id before believing the error. Only "never left this PC" is final.
            if not coid or not getattr(exc, "sent", True):
                raise
            for i in range(ORDER_LOOKUP_TRIES):
                await asyncio.sleep(ORDER_LOOKUP_WAIT_SEC * (i + 1))
                try:
                    o = await self.tz_call(h.tz.order, h.acc, coid)
                except self.TZError:
                    continue
                if o:
                    log.warning("%s: order %s is at TradeZero although the answer was '%s' - tracking it",
                                sym, coid, self.clean(str(exc)))
                    self.host._log(f"LONG {sym}: {side.lower()} order {coid} is at TradeZero although TradeZero "
                                   f"answered '{self.clean(str(exc))}' - tracking it", "warn")
                    return o
            raise

    async def wait_done(self, coid, secs=6.0):
        o = None
        for _ in range(max(1, int(secs / 0.4))):
            await asyncio.sleep(0.4)
            try:
                o = await self.tz_call(self.host.tz.order, self.host.acc, coid) or o
            except self.TZError:
                pass
            if (o or {}).get("orderStatus") in DONE_STATES:
                break
        return o

    # ---------------- IB Gateway ----------------
    def _hook_ib(self):
        ib = self.ib
        if ib is None or self.ib_hooked is ib:
            return
        try:
            ib.errorEvent += self._on_error
            ib.disconnectedEvent += self.on_ib_disconnected
            self.ib_hooked = ib
        except Exception:
            log.exception("long: IB events")

    def _on_error(self, *args):
        try:
            code = int(args[1])
        except Exception:
            return
        if code in (1101, 1102) and self.traders:
            for tr in list(self.traders.values()):
                asyncio.ensure_future(self._restart_trader(tr))
        elif code in (420, 10089, 10090, 10167, 10168, 10197, 321, 162) and code not in self.err_once and self.session_on:
            self.err_once.add(code)
            self.notify("⚠ IB market data / scanner problem (premarket long)", f"code {code}: {args[2]}", "warn")

    def on_ib_disconnected(self):
        for tr in self.traders.values():
            tr.seeding = True                            # no decisions on a dead stream

    async def _restart_trader(self, tr):
        try:
            await tr.restart()
        except Exception as exc:
            log.warning("long %s re-subscribe failed: %r - retrying in 15 s", tr.sym, exc)
            tr.seeding, tr.active = False, True
            tr.last_bar_mono = _mono() - STALE_STREAM_SEC + 15
            if tr.day.pos is not None and ("resub", tr.sym) not in self.err_once:
                self.err_once.add(("resub", tr.sym))
                self.notify(f"\U0001F6A8 {tr.sym}: no market data for an OPEN long",
                            f"Re-subscribe failed ({exc.__class__.__name__}). Retrying every 15 s - watch it at TradeZero.",
                            "err", ping=True)

    async def prior_close(self, contract):
        day = self.et().date()
        key = (contract.symbol, day)
        if key in self.pc_cache:
            return self.pc_cache[key]
        bars = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr="10 D", barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
            formatDate=1), 30)
        prev = []
        for b in bars or []:
            d = b.date.date() if isinstance(b.date, datetime) else b.date
            if isinstance(d, str):
                d = datetime.strptime(d[:8], "%Y%m%d").date()
            if d < day:
                prev.append(b)
        pc = _fnum(prev[-1].close) if prev else 0.0
        self.pc_cache[key] = pc
        return pc

    async def fetch_history(self, contract):
        now = self.now()
        secs = int(max(300, now - day_start_ts(now) + 180))
        b1 = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr=f"{secs} S", barSizeSetting="1 min", whatToShow="TRADES",
            useRTH=False, formatDate=2), 45)
        b10 = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr=f"{SEED_10S_SEC} S", barSizeSetting="10 secs", whatToShow="TRADES",
            useRTH=False, formatDate=2), 45)
        return _bars(b1), _bars(b10)

    # ---------------- scanner ----------------
    def extra_tickers(self):
        base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        try:
            with open(os.path.join(base, EXTRA_TICKERS_FILE), encoding="utf-8") as fh:
                return [s.strip().upper() for s in fh.read().replace(",", "\n").splitlines()
                        if re.match(r"^[A-Za-z][A-Za-z.]{0,5}$", s.strip())]
        except OSError:
            return []

    async def scan(self):
        ib = self.ib
        if self.scanning or ib is None or not ib.isConnected() or ScannerSubscription is None:
            return
        self.scanning = True
        try:
            hub = getattr(getattr(self.host, "be", None), "gainers", None)
            if hub is not None and SCAN_CODE == "TOP_PERC_GAIN" and SCAN_LOCATION == "STK.US.MAJOR":
                # app 3.15: the app's ONE shared IB gainers scan (also feeds the Scanner screen and the short scanner);
                # exact: only a list asked with this module's own up % / price (the same stocks as its own request)
                cands, _ = await hub("long", MIN_GAP_PCT * 100 if SCAN_FILTER_CHANGE else 0.0, MIN_ENTRY_PRICE,
                                     SCAN_ROWS, SCAN_INTERVAL_SEC, exact=True, share=True)
                cands = list(cands)
            else:
                sub = ScannerSubscription(instrument="STK", locationCode=SCAN_LOCATION, scanCode=SCAN_CODE,
                                          numberOfRows=SCAN_ROWS, abovePrice=MIN_ENTRY_PRICE)
                flt = [TagValue("changePercAbove", f"{MIN_GAP_PCT * 100:g}")] if SCAN_FILTER_CHANGE else []
                data = await asyncio.wait_for(ib.reqScannerDataAsync(sub, [], flt), 20)
                cands = [d.contractDetails.contract for d in data or []]
            self.scan_errors = 0
            self.scan_n += 1
            self.scan_hits += len(cands)
            cands += [Stock(s, "SMART", "USD") for s in self.extra_tickers()]
            now = self.now()
            for c in cands:
                sym = c.symbol
                if sym in self.traders or sym in self.adding or self.cooldown.get(sym, 0) > now:
                    continue
                if len(self.traders) + len(self.adding) >= MAX_WATCHLIST:
                    break
                self.adding.add(sym)
                asyncio.ensure_future(self.add_symbol(sym, c))
            if (not self.scan_warned and self.scan_hits == 0 and self.secs() >= SCAN_START_S + 1800
                    and self.scan_n >= 60):
                self.scan_warned = True
                self.notify("⚠ IB scanner found nothing for 30 minutes",
                            f"{self.scan_n} scans of {SCAN_CODE} returned no stock up {MIN_GAP_PCT * 100:g}%. If that "
                            f"looks wrong, check your IBKR scanner permissions or put tickers in {EXTRA_TICKERS_FILE}.",
                            "warn")
        except Exception as exc:
            self.scan_errors += 1
            log.warning("long scan failed: %r", exc)
            if self.scan_errors == 6:
                self.notify("⚠ IB scanner failing", f"6 scans in a row failed ({exc.__class__.__name__}: {exc}).", "warn")
        finally:
            self.scanning = False

    async def add_symbol(self, sym, contract):
        tr = None
        try:
            async with self.add_sem:
                if sym in self.traders or not self.entries_open():
                    return
                c = contract
                if not getattr(c, "conId", 0):
                    q = await asyncio.wait_for(self.ib.qualifyContractsAsync(Stock(sym, "SMART", "USD")), 15)
                    if not q:
                        self.cooldown[sym] = self.now() + 3600
                        return
                    c = q[0]
                c.exchange = "SMART"
                self.contracts[sym] = c
                pc = await self.prior_close(c)
                if pc <= 0:
                    self.cooldown[sym] = self.now() + 600
                    return
                day = self.days.get(sym) or DayState(sym)
                if day.halted:
                    self.cooldown[sym] = self.now() + 3600
                    return
                tr = Trader(self, sym, c, pc, day)
                await tr.start()
                px, thr = tr.eng.last_close, pc * (1 + MIN_GAP_PCT)
                if not (_pos(px) and px >= thr and px >= MIN_ENTRY_PRICE):
                    tr.stop()                            # listed, but no 10-s candle has CLOSED above +30% yet
                    self.cooldown[sym] = self.now() + NOT_READY_RETRY_SEC
                    return
                done = tr.done_reason(self.now()) if day.pos is None else ""
                if done:                                 # it cannot trade any more today: not added (bot log only)
                    tr.stop()
                    self.cooldown[sym] = self.now() + DAY_COOLDOWN_SEC
                    self.log_once((sym, "done"), f"{sym} +{(px / pc - 1) * 100:.0f}% not added: {done}")
                    return
                self.days[sym] = day
                self.traders[sym] = tr
                tr = None
                self.on_added(self.traders[sym])
        except Exception as exc:
            log.warning("long add %s failed: %r", sym, exc)
            self.cooldown[sym] = self.now() + 60
            if tr is not None:
                tr.stop()
        finally:
            self.adding.discard(sym)

    def remove_symbol(self, sym, why, quiet=False, cool=None):
        tr = self.traders.pop(sym, None)
        if tr is None:
            return
        tr.stop()
        self.cooldown[sym] = self.now() + (cool or REJOIN_COOLDOWN_SEC)
        if not quiet:
            d = tr.day
            self.notify(f"{sym} - long watch ended", f"{why}. Today: {d.trades_taken} trade(s), "
                                                       f"P&L {_money(d.daily_pnl)}.", "dim")

    # ---------------- risk gates ----------------
    def realized_today(self):
        return sum(d.daily_pnl for d in self.days.values())

    def why_no_entry(self, sym=None):
        if not self.entries_open():
            return "entries closed"
        if not self.tz_ready():
            return "TradeZero not connected"
        if self.live_blocked():
            return "LIVE account - orders blocked"
        if self.trades_today >= MAX_BOT_TRADES_PER_DAY:
            return f"{MAX_BOT_TRADES_PER_DAY} long trades today"
        if sum(1 for t in self.traders.values() if t.day.pos is not None or t.busy()) >= MAX_OPEN_POSITIONS:
            return f"{MAX_OPEN_POSITIONS} positions open"
        if sym and any(r["sym"] == sym for r in self.pending.values()):
            return "an earlier buy of this stock is not settled yet (TradeZero answered with an error)"
        lim = self.daily_loss_limit()
        if lim > 0 and self.realized_today() <= -lim:
            return (f"long daily loss limit {_money(lim)} ({DAILY_LOSS_PCT_OF_POSITION:g}% of the "
                    f"{_money(position_usd(self.account_size()))} position) reached")
        if sym:
            busy = self.host.short_busy(sym)
            if busy:
                return busy
        return ""

    # ---------------- events -> Discord + journal ----------------
    def on_added(self, tr):
        eng, d = tr.eng, tr.day
        px = eng.last_close
        gain = (px / tr.pc - 1) * 100
        disc = et_hms(d.discovered_t) if d.discovered_t else "-"
        vel = "-" if isnan(d.velocity_gain) else f"{d.velocity_gain * 100:+.1f}%"
        armed = ("momentum chase armed" if d.momentum_allowed else
                 ("bull flag only (slow grind)" if BULL_FLAG_ENABLED else "slow grind - no momentum chase"))
        until = et_hms(d.discovered_t + FRESH_ENTRY_SEC) if d.discovered_t else "-"
        self.notify(f"{tr.sym}  +{gain:.0f}%  ·  {_fp(px)}",
                    f"Up {MIN_GAP_PCT * 100:g}%+ from the prior close (crossed at {disc} ET; 10 minutes before: {vel} -> "
                    f"{armed}). Watching for a momentum entry until {until} ET.", "dim", tag="LONG WATCH",
                    fields=[("Long watchlist", ", ".join(sorted(self.traders)) or "-", False)], trader=tr)

    def on_entry(self, tr, pos, sig, wanted):
        self.trades_today += 1
        value = pos.shares * pos.entry
        self.notify(f"{tr.sym} - {pos.shares:,} @ {_fp(pos.entry)}",
                    f"{sig['strategy']}. Half sells at the target, the rest trails. Sells at stop +{STOP_EARLY_PCT:g}% "
                    f"({_fp(pos.stop * (1 + STOP_EARLY_PCT / 100.0))}). Time stop {MAX_HOLD_MIN_WITHOUT_PROFIT} min "
                    f"without +1R.", "buy", tag="BOUGHT",
                    fields=[("Stop", f"{_fp(pos.stop)}\n({-pos.risk / pos.entry * 100:.0f}%)", True),
                            ("Half at", f"{_fp(pos.target)}\n({sig['mult']:g}R)", True),
                            ("Size", f"{_money(value)}\n{ACCOUNT_PCT:g}% of equity"
                             + (f" (wanted {wanted:,})" if wanted != pos.shares else ""), True)],
                    trader=tr,
                    levels=[{"price": pos.entry, "color": "#d1d4dc", "style": "solid", "title": "entry"},
                            {"price": pos.stop, "color": "#f23645", "style": "dash", "title": "stop"},
                            {"price": pos.target, "color": "#089981", "style": "dash", "title": f"{sig['mult']:g}R"}],
                    marks=[{"t": pos.t, "price": pos.entry, "text": "BUY", "color": "#089981", "up": True}])
        self.push(force=True)

    def on_exit(self, tr, leg):
        self._journal(leg)
        part = leg["reason"] == PARTIAL
        win = leg["pnl"] > 0
        marks = [{"t": leg["entry_t"], "price": leg["entry"], "text": "BUY", "color": "#089981", "up": True},
                 {"t": leg["exit_t"], "price": leg["exit"], "text": "SELL", "color": "#f23645" if not win else "#2962FF",
                  "up": False}]
        if leg["closed"]:
            self._closed_row(tr, leg)
        self.push(force=True)
        if part and not leg["closed"]:
            p = tr.day.pos
            self.notify(f"{tr.sym} - {leg['shares']:,} @ {_fp(leg['exit'])}  ·  {_money(leg['pnl'])}",
                        f"The rest ({leg['left']:,}) trails from breakeven {_fp(leg['entry'])}, then under the 60-second "
                        f"low.", "partial", tag="HALF SOLD",
                        fields=[("Leg P&L", _money(leg["pnl"]), True), ("Trade so far", _money(leg["trade_pnl"]), True)],
                        trader=tr, marks=marks,
                        levels=[{"price": p.trailing if p else leg["entry"], "color": "#f23645", "style": "dash",
                                 "title": "trail"}])
            return
        r_mult = leg["trade_pnl"] / (leg["risk"] * leg["initial"]) if leg["risk"] > 0 and leg["initial"] else 0.0
        win = leg["trade_pnl"] > 0
        res = {STOP_OUT: "STOP", TRAIL_OUT: "TRAIL", TIME_STOP: "TIME STOP"}.get(leg["reason"], str(leg["reason"]).upper())
        held = max(0, int(leg["exit_t"] - leg["entry_t"])) // 60
        fl = [("Bought", f"{leg['initial']:,} @ {_fp(leg['entry'])}\n{et_hms(leg['entry_t'])[:5]}", True),
              ("Sold", f"{leg['shares']:,} @ {_fp(leg['exit'])}\n{et_hms(leg['exit_t'])[:5]} {res.lower()}", True),
              ("Held", f"{held} min", True)]
        desc = f"Long today {_money(self.realized_today())}."
        ss = self.stop_slip(leg)
        if ss is not None:                               # 3.10: what the stop sale cost - logged for review
            trig, vs_trig, vs_stop = ss
            desc = (f"Stop {_fp(leg['stop'])}, sell triggered at {_fp(trig)} (+{STOP_EARLY_PCT:g}%), filled "
                    f"{_fp(leg['exit'])}: {vs_stop:+.1f}% vs the stop. " + desc)
            fl[2] = ("Slippage", f"{vs_trig:.1f}% under the trigger\nlogged for review", True)
        self.notify(f"{tr.sym}  {_money(leg['trade_pnl'])}  ·  {r_mult:+.1f}R", desc,
                    "win" if win else "loss", tag="CLOSED  ·  " + ("WIN" if win else res), fields=fl,
                    trader=tr, marks=marks)
        lim = self.daily_loss_limit()
        if lim > 0 and not self.daily_stop_sent and self.realized_today() <= -lim:
            self.daily_stop_sent = True
            acc = self.account_size()
            self.notify("No new longs today",
                        f"Long bot today {_money(self.realized_today())}: the limit is {DAILY_LOSS_PCT_OF_POSITION:g}% of "
                        f"the {_money(position_usd(acc))} long position (start-of-day equity {_money(acc)}) = "
                        f"{_money(lim)}. Open longs keep their stops and exits; the short bot is not affected.", "warn",
                        tag="LONG DAILY STOP")

    def _closed_row(self, tr, leg):
        legs = [g for g in tr.day.legs if g["entry_t"] == leg["entry_t"]]
        sh = sum(g["shares"] for g in legs)
        ex = sum(g["exit"] * g["shares"] for g in legs) / sh if sh else leg["exit"]
        res = leg["reason"] + (" (half at target)" if any(g["reason"] == PARTIAL for g in legs) else "")
        r_mult = leg["trade_pnl"] / (leg["risk"] * leg["initial"]) if leg["risk"] > 0 and leg["initial"] else 0.0
        self.closed_rows.append({"sym": tr.sym, "setup": leg["strategy"], "t": et_hms(leg["entry_t"])[:5],
                                 "tx": et_hms(leg["exit_t"])[:5], "sh": int(leg["initial"]), "entry": _r(leg["entry"]),
                                 "exit": _r(ex), "res": res, "pnl": round(leg["trade_pnl"], 2), "r": round(r_mult, 2)})

    def stop_slip(self, leg):
        """3.10: a hard-stop sale: (trigger, % the fill was under the trigger, % under the stop) - logged and posted."""
        if leg.get("reason") != STOP_OUT or not leg.get("stop") or not leg.get("exit"):
            return None
        trig = leg["stop"] * (1 + STOP_EARLY_PCT / 100.0)
        return trig, (1 - leg["exit"] / trig) * 100.0, (1 - leg["exit"] / leg["stop"]) * 100.0

    def _slip_log(self, leg):
        """3.10: every hard-stop sale -> long_stop_slippage.csv (app data folder): stop, trigger, fill, slippage."""
        ss = self.stop_slip(leg)
        if ss is None:
            return
        trig, vs_trig, vs_stop = ss
        log.info("%s stop sale: stop %.4f trigger %.4f fill %.4f (%.2f%% under the trigger, %.2f%% under the stop)",
                 leg["sym"], leg["stop"], trig, leg["exit"], vs_trig, vs_stop)
        path = os.path.join(os.path.dirname(self.journal), "long_stop_slippage.csv")
        cols = ["date", "time", "symbol", "shares", "entry", "stop", "trigger", "fill", "slip_vs_trigger_pct",
                "slip_vs_stop_pct"]
        row = {"date": str(self.et().date()), "time": et_hms(leg["exit_t"]), "symbol": leg["sym"], "shares": leg["shares"],
               "entry": round(leg["entry"], 4), "stop": round(leg["stop"], 4), "trigger": round(trig, 4),
               "fill": round(leg["exit"], 4), "slip_vs_trigger_pct": round(vs_trig, 2), "slip_vs_stop_pct": round(vs_stop, 2)}
        try:
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                if new:
                    w.writeheader()
                w.writerow(row)
        except OSError:
            log.exception("long stop slippage log")
        try:
            import turso                                   # 3.14: mirrored to Turso
            turso.journal_add("long_stop_slippage.csv", row)
        except Exception:
            pass

    def _journal(self, leg):
        self._slip_log(leg)
        cols = ["date", "symbol", "setup", "result", "shares", "entry_time", "entry", "exit_time", "exit", "pnl",
                "trade_pnl", "stop", "target", "risk_per_share", "account"]
        row = {"date": str(self.et().date()), "symbol": leg["sym"], "setup": leg["strategy"], "result": leg["reason"],
               "shares": leg["shares"], "entry_time": et_hms(leg["entry_t"]), "entry": round(leg["entry"], 4),
               "exit_time": et_hms(leg["exit_t"]), "exit": round(leg["exit"], 4), "pnl": round(leg["pnl"], 2),
               "trade_pnl": round(leg["trade_pnl"], 2) if leg["closed"] else "", "stop": round(leg["stop"], 4),
               "target": round(leg["target"], 4), "risk_per_share": round(leg["risk"], 4), "account": self.host.acc}
        try:
            new = not os.path.exists(self.journal)
            with open(self.journal, "a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                if new:
                    w.writeheader()
                w.writerow(row)
        except OSError:
            log.exception("long journal")
        try:
            import turso                                   # 3.14: mirrored to Turso (the account column is left out)
            turso.journal_add("long_bot_trades.csv", row)
        except Exception:
            pass

    # ---------------- 1.7 safety: TradeZero is the truth ----------------
    def note_buy(self, sym, coid, sig, shares, limit):
        """Every buy the bot sends today is remembered: the symbol is then the bot's for the position guard."""
        b = self.buys.get(sym)
        if b is None:
            b = self.buys[sym] = {"base": int(self.tz_longs.get(sym, (0, 0.0))[0]), "recs": []}
        rec = {"sym": sym, "coid": coid, "sig": dict(sig), "shares": int(shares), "limit": float(limit),
               "t": self.now(), "mono": _mono(), "state": "sent", "err": ""}
        b["recs"].append(rec)
        return rec

    def buy_unknown(self, tr, rec, exc):
        """The buy's answer was an error and the order is not (yet) found by its id: it may still have filled. The
        symbol stays streamed and blocked for new buys; the guard reads TradeZero every GUARD_POLL_SEC."""
        if not getattr(exc, "sent", True):
            rec["state"] = "none"
            self.notify(f"❌ {tr.sym}: buy order not sent", self.clean(str(exc)), "err")
            return
        rec["state"], rec["err"] = "unknown", self.clean(str(exc))
        self.pending[rec["coid"]] = rec
        self.next_guard = 0.0
        risk = clamp_risk(rec["limit"], rec["sig"]["stop"])
        self.notify(f"⚠ {tr.sym}: buy order error - checking TradeZero for a fill",
                    f"TradeZero answered '{rec['err']}' to the buy of {rec['shares']:,} @ {_fp(rec['limit'])}, but such "
                    f"an order can still fill. The bot reads TradeZero's positions every {GUARD_POLL_SEC:g} s and takes "
                    f"over any shares it finds (stop {_fp(rec['limit'] - risk)}). No new buy on {tr.sym} until this is "
                    f"settled.", "warn", trader=tr)

    def _base(self, sym):
        return int((self.buys.get(sym) or {}).get("base", 0))

    def owned(self):
        """Symbols whose longs at TradeZero are the bot's: bought (or tried) today, or held by a trader."""
        out = set(self.buys) | {t.sym for t in self.traders.values() if t.day.pos is not None}
        out |= self._symbols_bought_today()
        if FLATTEN_ALL_ACCOUNT_LONGS and self.flattened:
            out |= set(self.tz_longs)
        out.discard("")
        return out

    def tz_owned_shares(self, sym):
        return max(0, int(self.tz_longs.get(sym, (0, 0.0))[0]) - self._base(sym))

    def must_watch(self, sym):
        """Keep streaming sym (and keep the short bot off it): a buy is unsettled, or TradeZero shows the bot's shares."""
        if any(r["sym"] == sym for r in self.pending.values()):
            return True
        return self.tz_owned_shares(sym) > 0 and sym in self.owned()

    def _hot(self):
        return bool(self.pending or self.open_longs() or any(t.busy() for t in self.traders.values())
                    or any(self.tz_owned_shares(s) > 0 for s in self.owned()))

    def guard(self):
        """Main loop (4x a second): start a TradeZero positions read when one is due - every GUARD_POLL_SEC while a long
        is open / an order is unsettled, every GUARD_IDLE_POLL_SEC during the session (or after a long day) otherwise."""
        if self.guard_busy or not self.tz_ready():
            return
        hot = self._hot()
        if not (hot or self.session_on or self.buys or self.traders or self._symbols_bought_today()):
            return
        mono = _mono()
        if mono < self.next_guard:
            return
        self.next_guard = mono + (GUARD_POLL_SEC if hot else GUARD_IDLE_POLL_SEC)
        self.guard_busy = True
        asyncio.ensure_future(self._guard_run())

    async def _guard_run(self):
        try:
            await self.guard_check()
        except Exception:
            log.exception("long position guard")
        finally:
            self.guard_busy = False

    def _parse_longs(self, pos):
        longs = {}
        for p in pos or []:
            sym = str(p.get("symbol") or "")
            sh = _fnum(p.get("shares"))
            side = str(p.get("side") or "").lower()
            if not sym or sh <= 0 or "short" in side or str(p.get("securityType", "Stock")) != "Stock":
                continue
            longs[sym] = (int(sh), _fnum(p.get("priceAvg"), 0.0) or _fnum(p.get("priceOpen"), 0.0))
        return longs

    async def guard_check(self):
        """One positions read: settle unsettled buys, then compare every symbol of the bot with TradeZero."""
        h = self.host
        mono = _mono()
        try:
            pos = await self.tz_call(h.tz.positions, h.acc)
        except self.TZError as exc:
            if (self.open_longs() or self.pending) and mono - self.tz_ok_mono >= GUARD_ALERT_SEC and not self.guard_alerted:
                self.guard_alerted = True
                held = ", ".join(f"{t.sym} {t.day.pos.shares:,}" for t in self.open_longs()) or "an unsettled buy"
                self.notify("\U0001F6A8 Long bot cannot read TradeZero's positions",
                            f"No good answer for {mono - self.tz_ok_mono:.0f} s ({self.clean(str(exc))}). Held: {held}. "
                            "Stops are still watched on IB prices and sold through TradeZero - check the account.",
                            "err", ping=True)
            return
        if self.guard_alerted:
            self.guard_alerted = False
            self.notify("✅ TradeZero positions readable again", "The long bot compares its positions again.", "ok")
        self.tz_ok_mono = mono
        longs = self._parse_longs(pos)
        self.tz_longs = longs
        await self._settle_pending(mono)
        for sym in sorted(self.owned() | set(self.traders)):
            try:
                await self._compare(sym, longs, mono)
            except Exception:
                log.exception("long guard %s", sym)

    async def _settle_pending(self, mono):
        """Buys answered with an error: look them up until TradeZero shows how they ended."""
        h = self.host
        for coid, rec in list(self.pending.items()):
            try:
                o = await self.tz_call(h.tz.order, h.acc, coid)
            except self.TZError:
                o = None
            age = mono - rec["mono"]
            if o:
                st = str(o.get("orderStatus") or "")
                ex = int(_fnum(o.get("executed")))
                rec["coid"] = str(o.get("clientOrderId") or coid)
                if st not in DONE_STATES:                # still working: cancel it once the entry window is over
                    if age >= ENTRY_TIMEOUT_SEC and not rec.get("cancel_sent"):
                        try:
                            await self.tz_call(h.tz.cancel, h.acc, rec["coid"])
                            rec["cancel_sent"] = True
                        except self.TZError:
                            pass
                    continue
                self.pending.pop(coid, None)
                if ex > 0:
                    rec["state"], rec["avg"], rec["fill_n"] = "filled", _fnum(o.get("priceAvg"), rec["limit"]), ex
                    self.next_guard = 0.0                # take the shares over on the next read
                else:
                    rec["state"] = "none"
                    self.notify(f"⚪ {rec['sym']}: the buy that answered with an error did not fill",
                                f"TradeZero shows it {st.lower()} with nothing filled - nothing to take over.", "dim")
            elif age > UNKNOWN_FILL_WATCH_SEC:
                self.pending.pop(coid, None)
                rec["state"] = "none"
                self.host._log(f"LONG {rec['sym']}: buy {coid} never showed up at TradeZero - settled as not sent", "warn")

    async def _compare(self, sym, longs, mono):
        """TradeZero vs the bot for one symbol. A difference must hold on 2 reads ADOPT_CONFIRM_SEC apart (more shares
        at TradeZero) or 3 reads GONE_CONFIRM_SEC apart (fewer) - TradeZero's list can lag a fill by a second."""
        if sym in self.adding or sym in self.starting:
            return
        tr = self.traders.get(sym)
        if tr is not None and (tr.busy() or mono < tr.settle_until):
            self.mismatch.pop(sym, None)
            return
        tz_sh = max(0, int(longs.get(sym, (0, 0.0))[0]) - self._base(sym))
        bot_sh = tr.day.pos.shares if tr is not None and tr.day.pos is not None else 0
        if tz_sh == bot_sh:
            self.mismatch.pop(sym, None)
            if not tz_sh:
                self.blind_alerted.discard(sym)
            return
        if bot_sh == 0 and sym not in self.owned():
            return
        m = self.mismatch.get(sym)
        if m is None or m["tz"] != tz_sh or m["bot"] != bot_sh:
            self.mismatch[sym] = {"tz": tz_sh, "bot": bot_sh, "first": mono, "n": 1}
            self.next_guard = min(self.next_guard, mono + 1.0)          # confirm soon
            return
        m["n"] += 1
        if tz_sh > bot_sh and (m["n"] < 2 or mono - m["first"] < ADOPT_CONFIRM_SEC):
            self.next_guard = min(self.next_guard, mono + 1.0)
            return
        if tz_sh < bot_sh and (m["n"] < 3 or mono - m["first"] < GONE_CONFIRM_SEC):
            self.next_guard = min(self.next_guard, mono + 1.0)
            return
        self.mismatch.pop(sym, None)
        if tz_sh > bot_sh:
            await self.adopt(sym, tz_sh - bot_sh, longs[sym][1])
        else:
            await self.book_gone(sym, bot_sh - tz_sh)

    def _hint(self, sym):
        """The newest buy of today on sym that may be behind shares the bot does not hold: its signal gives the stop
        and the target of the long taken over."""
        recs = (self.buys.get(sym) or {}).get("recs", [])
        for r in reversed(recs):
            if not r.get("adopted") and r["state"] != "managed" and _mono() - r["mono"] < 3600:
                return r
        return None

    async def _stream_again(self, sym):
        """Stream a symbol again (no +30% / entry-window checks) because TradeZero shows the bot's shares in it."""
        tr = self.traders.get(sym)
        if tr is not None and tr.eng is not None:
            return tr
        ib = self.ib
        if sym in self.starting or ib is None or not ib.isConnected():
            return None
        self.starting.add(sym)
        new = None
        try:
            c = self.contracts.get(sym)
            if c is None:
                q = await asyncio.wait_for(ib.qualifyContractsAsync(Stock(sym, "SMART", "USD")), 15)
                if not q:
                    return None
                c = q[0]
                c.exchange = "SMART"
                self.contracts[sym] = c
            pc = await self.prior_close(c)
            if pc <= 0:
                pc = (self.tz_longs.get(sym, (0, 0.0))[1] or 1.0) / (1 + MIN_GAP_PCT)
            if tr is None:
                day = self.days.get(sym) or DayState(sym)
                new = Trader(self, sym, c, pc, day)
                await new.start()
                self.days[sym], self.traders[sym] = day, new
                tr, new = new, None
            else:
                await tr.restart()
            self.cooldown.pop(sym, None)
            return tr if tr.eng is not None else None
        except Exception as exc:
            log.warning("long: streaming %s again failed: %r", sym, exc)
            if new is not None:
                new.stop()
            return None
        finally:
            self.starting.discard(sym)

    async def adopt(self, sym, extra, avg):
        """Shares at TradeZero the bot did not know (in a symbol it bought today): take them over and manage them like
        any long - the signal's stop / target when the bot has the buy behind them, else ADOPT_STOP_PCT under the
        average price. Returns the trader (None if the symbol cannot be streamed right now)."""
        tr = self.traders.get(sym)
        if tr is None or tr.eng is None:
            tr = await self._stream_again(sym)
            if tr is None:
                if sym not in self.blind_alerted:
                    self.blind_alerted.add(sym)
                    self.notify(f"\U0001F6A8 {sym}: {extra:,} shares LONG at TradeZero - NO STOP",
                                "The bot found shares it did not know but cannot get IB prices for the symbol right now, "
                                "so it cannot watch a stop. It keeps trying every few seconds - sell or stop them at "
                                "TradeZero now.", "err", ping=True)
                return None
        if tr.busy():
            return tr
        hint = self._hint(sym)
        if not avg or avg <= 0:
            avg = (hint or {}).get("avg") or (hint or {}).get("limit") or (tr.last if _pos(tr.last) else 0.0)
        if not avg or avg <= 0:
            return tr                                    # no price yet: the next read tries again
        self.blind_alerted.discard(sym)
        now = self.now()
        p = tr.day.pos
        if p is None:
            if hint is not None:
                sig, t0 = dict(hint["sig"]), hint["t"]
                how = (f"The bot's buy of {et_hms(hint['t'])} ({hint['shares']:,} @ {_fp(hint['limit'])}) "
                       + (f"was answered '{hint['err']}' but filled." if hint.get("err")
                          else "filled without the bot knowing (lost answer / late fill)."))
            else:
                sig = {"strategy": ADOPTED, "stop": avg * (1 - ADOPT_STOP_PCT / 100.0), "mult": TARGET_MULT}
                t0 = now
                how = (f"No buy signal of the bot matches them - managed with a {ADOPT_STOP_PCT:g}% stop under "
                       f"TradeZero's average price.")
            p = tr.eng.open_position(sig, avg, extra, t0)
            self.trades_today += 1
            if hint is not None:
                hint["adopted"], hint["state"] = True, "managed"
                for k, r in list(self.pending.items()):     # settled: these are its shares
                    if r is hint:
                        self.pending.pop(k, None)
            what = f"TAKEN OVER {extra:,} sh @ {_fp(avg)}"
        else:                                            # more shares than the bot knew (a fill it missed)
            p.shares += extra
            p.initial += extra
            p.entry = avg
            how = f"TradeZero shows {extra:,} more shares than the bot held - they are part of the position now."
            what = f"+{extra:,} sh found, now {p.shares:,} @ {_fp(p.entry)}"
        tr.settle_until = _mono() + SETTLE_SEC
        if self.secs() >= FLATTEN_S:                     # after 09:00: the residual loop sells it
            self.flattened = True
            tr.next_residual = 0.0
        self.notify(f"\U0001F6A8 {sym}: LONG AT TRADEZERO {what} - now managed",
                    f"{how} Stop {_fp(p.stop)} ({p.risk / p.entry * 100:.1f}%), target {_fp(p.target)} - half there, "
                    f"the rest trails; time stop {MAX_HOLD_MIN_WITHOUT_PROFIT} min" +
                    (f"; it is sold now (after {FLATTEN_AT[:5]})." if self.flattened else "."),
                    "err", trader=tr, ping=True,
                    levels=[{"price": p.entry, "color": "#d1d4dc", "style": "solid", "title": "entry"},
                            {"price": p.stop, "color": "#f23645", "style": "dash", "title": "stop"},
                            {"price": p.target, "color": "#089981", "style": "dash", "title": "target"}])
        self.push(force=True)
        self.watchdog()                                  # the price may be under the stop already
        return tr

    async def _outside_sell_price(self, sym, n):
        """Average price of the newest sells of sym at TradeZero the bot did not book itself (yours, or a sell whose
        answer was lost)."""
        try:
            orders = await self.tz_call(self.host.tz.orders, self.host.acc)
        except self.TZError:
            return NAN, ""
        fills = []
        for o in orders or []:
            cid = str(o.get("clientOrderId") or "")
            if (str(o.get("symbol") or o.get("tradedSymbol") or "") != sym or str(o.get("side") or "") != "Sell"
                    or str(o.get("openClose") or "Close") == "Open" or cid.startswith("LHB")
                    or cid in self.booked_sells or int(_fnum(o.get("executed"))) <= 0):
                continue
            fills.append((str(o.get("lastUpdated") or o.get("startTime") or ""), cid, int(_fnum(o.get("executed"))),
                          _fnum(o.get("priceAvg"))))
        got, cost, used = 0, 0.0, []
        for _, cid, ex, px in sorted(fills, reverse=True):      # the newest sells first
            if got >= n or px <= 0:
                continue
            q = min(ex, n - got)
            got, cost = got + q, cost + q * px
            used.append(cid)
        self.booked_sells.update(used)
        return (cost / got, "TradeZero fill " + ", ".join(used)) if got else (NAN, "")

    async def book_gone(self, sym, n):
        """Shares the bot holds that TradeZero no longer shows: sold by you, or a sell whose answer was lost. Booked at
        the real fill price of those sells, else at the last price."""
        tr = self.traders.get(sym)
        if tr is None or tr.day.pos is None or tr.busy():
            return
        px, src = await self._outside_sell_price(sym, n)
        if not _pos(px):
            px = tr.bid if _pos(tr.bid) else (tr.last if _pos(tr.last) else tr.day.pos.entry)
            src = "last price - no sell order found"
        if tr.day.pos is None or tr.busy():
            return
        n = min(n, tr.day.pos.shares)
        leg = tr.eng.close_leg(n, px, SOLD_OUTSIDE, self.now())
        left = tr.day.pos.shares if tr.day.pos is not None else 0
        self.notify(f"⚠ {sym}: {n:,} shares sold at TradeZero outside the bot",
                    f"TradeZero shows {left:,} left. Booked at {_fp(px)} ({src}). " +
                    ("The rest stays managed." if left else "Position closed."), "warn", trader=tr)
        self.on_exit(tr, leg)

    def watchdog(self):
        """Stops, targets and trails checked on the clock too (4x a second) with the last price - not only when IB
        sends a tick. After 09:00 the flatten / residual loop owns the exits."""
        if self.flattened:
            return
        now = self.now()
        for tr in list(self.traders.values()):
            p = tr.day.pos
            if p is None or tr.busy() or tr.eng is None or tr.seeding or not tr.active or not _pos(tr.last):
                continue
            req = tr.eng.exit_on_price(tr.last, now)
            if req:
                tr._spawn(tr._exit(*req))

    # ---------------- commands from the app ----------------
    def set_mode(self, m):
        """1.8 (app 3.10): the app's Trading mode - "trading", "alert" (setups to Discord, no buys) or "off". The app
        posts the MODE CHANGED message."""
        if m not in ("trading", "alert", "off"):
            return
        self.enabled, self.alert = m != "off", m == "alert"
        self.push(force=True)

    def set_enabled(self, on):
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        self.host.settings.set("long_on", on)
        if on:
            self.notify("\U0001F7E2 Premarket long ON", f"Scanner and entries {SCAN_START}-{ENTRY_CUTOFF[:5]} ET on weekdays, "
                        f"every long sold from {FLATTEN_AT[:5]}.", "ok")
        else:
            self.notify("⏸ Premarket long OFF", "No new scans or entries. Open longs keep their exits (and are sold "
                        f"at {FLATTEN_AT[:5]}).", "warn")
        self.push(force=True)

    async def sell_now(self, sym):
        tr = self.traders.get(sym)
        if tr is None or tr.day.pos is None:
            return
        for _ in range(40):                              # let a running order step finish first
            if not tr.busy():
                break
            await asyncio.sleep(0.25)
        if tr.day.pos is None:
            return
        self.notify(f"{sym}: sell requested from the app", f"{tr.day.pos.shares:,} shares", "warn", trader=tr)
        tr._spawn(tr._exit(OPEN_FLAT if self.flattened else "SOLD FROM APP", tr.day.pos.shares, market=True))

    async def flatten_all(self, reason="Flatten all"):
        """Flatten button in the app: no new entries today, every open long sold now."""
        self.entries_closed = True
        opens = self.open_longs()
        if not opens:
            return
        self.notify(f"{reason}: selling {len(opens)} long(s) at market", ", ".join(f"{t.sym} {t.day.pos.shares:,}"
                                                                                      for t in opens), "warn",
                    tag="SELLING EVERY LONG")
        running = [t.task for t in self.traders.values() if t.busy()]
        if running:
            await asyncio.wait(running, timeout=10)
        for t in self.open_longs():
            t._spawn(t._exit(OPEN_FLAT, t.day.pos.shares, market=True))
        await asyncio.gather(*(t.task for t in opens if t.task is not None), return_exceptions=True)

    # ---------------- session ----------------
    def reset_day(self):
        for sym, tr in list(self.traders.items()):
            if tr.day.pos is None:
                tr.stop()
                self.traders.pop(sym, None)
        keep = {s: self.days[s] for s in self.traders if s in self.days}
        self.days, self.cooldown, self.logged = keep, {}, set()
        self.adding = set()
        self.trades_today = 0
        self.daily_stop_sent = False
        self.scan_n = self.scan_hits = self.scan_errors = 0
        self.scan_warned = False
        self.err_once = set()
        self.pc_cache = {}
        self.closed_rows = []
        self.flattened = False
        self.residual_alerted = False
        self.buys, self.pending, self.mismatch = {}, {}, {}          # 1.7: a new day of buys to check
        self.booked_sells, self.blind_alerted = set(), set()
        self.next_guard = 0.0

    async def start_session(self):
        self.reset_day()
        self.session_on, self.entries_closed = True, False
        self.session_day = self.et().date()
        self.next_scan = 0.0
        self.next_heartbeat = _mono() + DISCORD_HEARTBEAT_MIN * 60 if DISCORD_HEARTBEAT_MIN else float("inf")
        h = self.host
        why = "" if self.tz_ready() else " - TradeZero NOT connected yet (no orders until it is)"
        if self.live_blocked():
            why = " - LIVE account: orders blocked (ALLOW_LIVE_TRADING = False), setups are only reported"
        self.notify("Premarket long session started" + (" - ALERT ONLY (no buy orders)" if self.alert else "") + why,
                    f"Scanner every {SCAN_INTERVAL_SEC}s: up {MIN_GAP_PCT * 100:g}%+, price ${MIN_ENTRY_PRICE:g}+. "
                    f"{self.size_text()}. No entries after {ENTRY_CUTOFF[:5]}, every long sold from {FLATTEN_AT[:5]}.",
                    "warn" if (why or self.alert) else "dim", tag="LONG SESSION",
                    fields=[("TradeZero", (h.acc_type or "-") if h.acc else "not connected", True),
                            ("Equity", _money(_fnum((h.acc_info or {}).get('equity'))) if h.acc else "-", True)])
        await self.adopt_leftovers()

    async def adopt_leftovers(self):
        """App restarted during the session: a long the bot bought earlier today (its LLB buy is in TradeZero's order
        list) is taken over by the position guard on its next read (1.7: with a stop, not just reported)."""
        self.next_guard = 0.0

    def _symbols_bought_today(self):
        out = {s for s, d in self.days.items() if d.trades_taken > 0}
        for coid, o in (getattr(self.host, "orders_raw", None) or {}).items():
            if str(coid).startswith("LLBB") and _fnum(o.get("executed")) > 0:
                out.add(str(o.get("symbol") or o.get("tradedSymbol") or ""))
        return out

    async def session_tick(self):
        s = self.secs()
        mono = _mono()
        if s >= CUTOFF_S and not self.entries_closed:
            self.entries_closed = True
            if CUTOFF_S < FLATTEN_S:
                self.notify(f"🕘 {ENTRY_CUTOFF[:5]} - no new long entries", f"{len(self.open_longs())} long(s) open, "
                            f"sold from {FLATTEN_AT[:5]}.", "info")
        if self.entries_open() and mono >= self.next_scan:
            self.next_scan = mono + SCAN_INTERVAL_SEC
            asyncio.ensure_future(self.scan())
        await self.housekeeping()

    async def housekeeping(self):
        now = self.now()
        mono = _mono()
        ib = self.ib
        up = ib is not None and ib.isConnected()
        if up and not self.ib_was_up:                    # IB came back: re-subscribe every symbol
            for tr in list(self.traders.values()):
                asyncio.ensure_future(self._restart_trader(tr))
        self.ib_was_up = up
        for sym, tr in list(self.traders.items()):
            if tr.eng is not None and not tr.seeding:
                tr.eng.roll_clock(now)
            if tr.active and not tr.seeding and up and mono - tr.last_bar_mono > STALE_STREAM_SEC:
                tr.last_bar_mono = mono
                log.warning("long %s: no 5-s bar for %ss - re-subscribing", sym, STALE_STREAM_SEC)
                asyncio.ensure_future(self._restart_trader(tr))
            if tr.check_drop(now):
                done = tr.day.halt_reason if tr.day.halted else tr.done_reason(now)
                why = done or ("long bot switched off" if not self.enabled else
                               f"under +{MIN_GAP_PCT * 100:g}% (or ${MIN_ENTRY_PRICE:g}) for {DROP_GRACE_SEC}s")
                self.remove_symbol(sym, why, quiet=self.flattened, cool=DAY_COOLDOWN_SEC if done else None)
        if self.session_on and mono >= self.next_heartbeat:
            self.next_heartbeat = mono + DISCORD_HEARTBEAT_MIN * 60
            self.heartbeat()

    def heartbeat(self):
        lines = []
        for sym, tr in sorted(self.traders.items()):
            px = tr.last if _pos(tr.last) else (tr.eng.last_close if tr.eng is not None else NAN)
            g = (px / tr.pc - 1) * 100 if _pos(px) else 0
            p = tr.day.pos
            if p:
                lines.append(f"**{sym}** {_fp(px)} (+{g:.0f}%) LONG {p.shares:,} @ {_fp(p.entry)}  "
                             f"open {_money((px - p.entry) * p.shares)}")
            else:
                lines.append(f"{sym} {_fp(px)} (+{g:.0f}%) watching" + (" (backside)" if tr.day.backside_locked else ""))
        tzl = [f"{s} {self.tz_owned_shares(s):,}" for s in sorted(self.owned()) if self.tz_owned_shares(s) > 0]
        if tzl or self.pending:
            lines.append("TradeZero shows the bot's longs: " + (", ".join(tzl) or "none") +
                         (f" | {len(self.pending)} buy(s) being checked" if self.pending else ""))
        self.notify("Premarket long status", "\n".join(lines) or "Long watchlist empty.", "dim",
                    fields=[("Long trades", str(self.trades_today), True), ("Realized", _money(self.realized_today()), True),
                            ("Scanner", f"{self.scan_n} scans", True)])

    async def flatten(self):
        """09:00: let running order steps finish, then sell every open long (limit at the bid stepping down - market
        orders only from the 09:30 open)."""
        self.entries_closed = True
        self.flattened = True
        running = [t.task for t in self.traders.values() if t.busy()]
        if running:
            await asyncio.wait(running, timeout=10)
        opens = self.open_longs()
        if opens:
            self.notify(f"🔔 {FLATTEN_AT[:5]} - selling {len(opens)} long(s)",
                        ", ".join(f"{t.sym} {t.day.pos.shares:,}" for t in opens), "warn")
            for t in opens:                              # the flatten owns each symbol's order step: no parallel sell
                t._spawn(t._exit(OPEN_FLAT, t.day.pos.shares, market=True))
            await asyncio.gather(*(t.task for t in opens), return_exceptions=True)
            for t in opens:
                t.next_residual = _mono() + RESIDUAL_RETRY_SEC
        await self.flatten_account_check()

    async def flatten_account_check(self):
        """Safety net after the 09:00 flatten: TradeZero's own position list. Any long of the bot still there - one it
        never knew, or one from before an app restart - is TAKEN OVER (streamed again, so the bot has a bid) and sold
        by the residual loop: limit at the bid stepping down before 09:30, market from the open. (1.6 skipped a
        symbol it no longer streamed and still said "sell orders sent".)"""
        if not self.tz_ready() or self.live_blocked():
            return
        left = []
        for attempt in range(3):
            try:
                pos = await self.tz_call(self.host.tz.positions, self.host.acc)
            except self.TZError as exc:
                log.warning("long positions check failed: %s", exc)
                await asyncio.sleep(3)
                continue
            self.tz_longs = longs = self._parse_longs(pos)
            left = []
            for sym in sorted(self.owned()):
                tr = self.traders.get(sym)
                held = tr.day.pos.shares if tr is not None and tr.day.pos is not None else 0
                extra = max(0, longs.get(sym, (0, 0.0))[0] - self._base(sym)) - held
                if extra > 0:
                    left.append((sym, extra, longs[sym][1]))
            if not left:
                return
            for sym, qty, avg in left:
                tr = self.traders.get(sym)
                if tr is not None and tr.busy():
                    continue
                await self.adopt(sym, qty, avg)          # its own message; the residual loop sells it
            await self.residual()
            await asyncio.sleep(5)
        if left:
            self.notify("\U0001F6A8 Long positions still open at TradeZero after the flatten",
                        ", ".join(f"{s} {q:,} sh" for s, q, _ in left) + ". The bot keeps selling the ones it streams "
                        f"every {RESIDUAL_RETRY_SEC} s (market from 09:30) - check TradeZero.", "err", ping=True)

    async def residual(self):
        """After the flatten: longs that did not sell are tried again every RESIDUAL_RETRY_SEC (market from 09:30)."""
        mono = _mono()
        opens = self.open_longs()
        for t in opens:
            if not t.busy() and mono >= t.next_residual:
                t.next_residual = mono + RESIDUAL_RETRY_SEC
                t._spawn(t._exit(OPEN_FLAT, t.day.pos.shares, market=True))
        if opens and not self.residual_alerted and self.secs() >= RESIDUAL_ALERT_S:
            self.residual_alerted = True
            self.notify("\U0001F6A8 Premarket long still open", ", ".join(f"{t.sym} {t.day.pos.shares:,} sh" for t in opens)
                        + ". Sell it at TradeZero - the short bot will not short these symbols while the long is open.",
                        "err", ping=True)

    async def end_session(self):
        legs = [g for d in self.days.values() for g in d.legs]
        trades = [g for g in legs if g["closed"]]
        wins = sum(1 for g in trades if g["trade_pnl"] > 0)
        total = sum(g["pnl"] for g in legs)
        per = {}
        for g in legs:
            per[g["sym"]] = per.get(g["sym"], 0.0) + g["pnl"]
        body = "\n".join(f"{s}: {_money(v)}" for s, v in sorted(per.items(), key=lambda x: -x[1]))
        opens = self.open_longs()
        if opens:
            body += "\n\nSTILL OPEN: " + ", ".join(f"{t.sym} {t.day.pos.shares:,} sh" for t in opens)
        self.notify(f"Premarket long done for today  ·  {_money(total)}",
                    (body or "No trades today.") + f"\n\n{len(trades)} trade(s), {wins} won." + ("" if opens else " Nothing open."),
                    "err" if opens else "dim", tag=f"LONGS FLAT  ·  {FLATTEN_AT[:5]}" if not opens else "LONGS STILL OPEN",
                    fields=[("Symbols watched", str(len(self.days)), True), ("Scans", str(self.scan_n), True)],
                    ping=bool(opens))
        for sym, tr in list(self.traders.items()):
            if tr.day.pos is None and not tr.busy():
                tr.stop()
                self.traders.pop(sym, None)
        self.session_on = False

    # ---------------- main loop (inside the app's event loop) ----------------
    async def run(self):
        self.msg_q = asyncio.Queue()
        self.add_sem = asyncio.Semaphore(2)
        asyncio.ensure_future(self._msg_worker())
        be = self.host.be
        while be.ib is None and not be.closing:
            await asyncio.sleep(1)
        log.info("premarket long module running (%s-%s ET, %s)", SCAN_START, FLATTEN_AT[:5], "ON" if self.enabled else "OFF")
        next_push = 0.0
        while not be.closing:
            try:
                self._hook_ib()
                await self.step()
            except Exception:
                log.exception("long step")
            if _mono() >= next_push:
                next_push = _mono() + 1.0
                self.push()
            await asyncio.sleep(0.25 if (self.session_on or self.traders) else 1.0)

    async def step(self):
        d = self.et()
        s = d.hour * 3600 + d.minute * 60 + d.second
        weekday = d.weekday() < 5
        if self.day != d.date():
            self.day = d.date()
            if not self.session_on:
                self.reset_day()
        if (self.enabled and weekday and SCAN_START_S <= s < FLATTEN_S and not self.session_on
                and self.session_day != d.date()):
            await self.start_session()
        if self.session_on:
            if s >= FLATTEN_S or not weekday:
                await self.flatten()
                await self.end_session()
            else:
                await self.session_tick()
        elif self.traders:
            if self.flattened:
                await self.residual()
            await self.housekeeping()
        self.watchdog()                                  # 1.7: stops on the clock
        self.guard()                                     # 1.7: TradeZero positions vs the bot

    # ---------------- page (Orders panel -> Premarket long tab) ----------------
    def state(self):
        s = self.secs()
        if not self.enabled:
            st = "off"
        elif self.session_on and not self.entries_closed:
            st = "running"
        elif self.session_on or (self.flattened and self.open_longs()):
            st = "closing"
        elif self.session_day == self.et().date():
            st = "done"
        else:
            st = "waiting"
        act = []
        for t in self.open_longs():
            p = t.day.pos
            last = t.last if _pos(t.last) else (t.eng.last_close if t.eng else NAN)
            stop = p.trailing if p.partial and p.trailing > 0 else p.stop
            act.append({"sym": t.sym, "setup": p.strategy, "t": et_hms(p.t)[:5], "sh": int(p.shares), "init": int(p.initial),
                        "entry": _r(p.entry), "last": _r(last), "stop": _r(stop), "trail": bool(p.partial),
                        "target": _r(p.target), "pnl": round((last - p.entry) * p.shares + p.realized, 2) if _pos(last) else None,
                        "busy": t.busy()})
        cls = list(reversed(self.closed_rows))
        tot = sum(r["pnl"] for r in self.closed_rows)
        win = sum(1 for r in self.closed_rows if r["pnl"] > 0)
        note = ""
        if self.enabled and not self.tz_ready():
            note = "TradeZero not connected"
        elif self.enabled and self.live_blocked():
            note = "LIVE account: orders blocked (ALLOW_LIVE_TRADING = False)"
        if self.enabled and self.alert and not note:
            note = "Alert only - setups go to Discord, no buy orders"
        return {"on": self.enabled, "alert": self.alert, "st": st, "win": f"{SCAN_START}-{FLATTEN_AT[:5]}", "watch": len(self.traders),
                "gap": round(MIN_GAP_PCT * 100),
                "act": act, "cls": cls, "tot": round(tot, 2), "n": len(self.closed_rows), "w": win, "note": note,
                "now": s}

    def push(self, force=False):
        try:
            js = json.dumps(self.state(), separators=(",", ":"))
        except Exception:
            log.exception("long state")
            return
        if js != self.last_push or force:
            self.last_push = js
            self.host.be.bridge.call_raw("setLong", js)

    def goodbye_text(self):
        opens = self.open_longs()
        if not opens:
            return ""
        return ("Premarket LONGS still open (no stop at TradeZero - sell them there): " +
                ", ".join(f"{t.sym} {t.day.pos.shares:,} @ {_fp(t.day.pos.entry)}" for t in opens))


# =============================================================================
# REPLAY A PAST DAY FROM IB GATEWAY:  python lh_long_premarket.py SYMBOL YYYYMMDD [--csv out.csv]
# =============================================================================
def _ib_replay(sym, ymd, csv_path=None, port=4001, client_id=19, equity=REPLAY_EQUITY):
    import asyncio
    try:
        from ib_async import IB, Stock
    except ImportError:
        from ib_insync import IB, Stock

    async def run():
        ib = IB()
        await ib.connectAsync("127.0.0.1", port, clientId=client_id, timeout=15, readonly=True)
        try:
            c = Stock(sym, "SMART", "USD")
            await ib.qualifyContractsAsync(c)
            day = datetime.strptime(ymd, "%Y%m%d").replace(tzinfo=ET)
            daily = await ib.reqHistoricalDataAsync(c, endDateTime=day.astimezone(timezone.utc), durationStr="10 D",
                                                    barSizeSetting="1 day", whatToShow="TRADES", useRTH=True, formatDate=1)
            prev = [b for b in daily if (b.date if not isinstance(b.date, datetime) else b.date.date()) < day.date()]
            if not prev:
                raise SystemExit("no prior daily close")
            pc = float(prev[-1].close)
            bars = {}
            end = day.replace(hour=9, minute=0)
            first = day.replace(hour=4, minute=0)
            while end > first:                       # 30-minute chunks (IB limits 10-second requests)
                chunk = await ib.reqHistoricalDataAsync(c, endDateTime=end.astimezone(timezone.utc), durationStr="1800 S",
                                                        barSizeSetting="10 secs", whatToShow="TRADES", useRTH=False,
                                                        formatDate=2)
                for b in chunk or []:
                    t = int(b.date.timestamp())
                    if int(first.timestamp()) <= t < int(day.replace(hour=9, minute=0).timestamp()) and b.volume > 0:
                        bars[t] = Bar(t, b.open, b.high, b.low, b.close, b.volume)
                end -= timedelta(minutes=30)
                await asyncio.sleep(2.2)              # IB pacing for small bars
            return pc, [bars[k] for k in sorted(bars)]
        finally:
            ib.disconnect()

    pc, bars10 = asyncio.run(run())
    legs, eng = replay_day(sym, pc, bars10, equity=equity)
    d = eng.day
    print(f"\n{sym} {ymd}  prior close {pc:.4g}  ->  alert {eng.alert:.4g}  |  {len(bars10)} ten-second candles  |  "
          f"size {ACCOUNT_PCT:g}% of ${equity:,.0f} (max ${MAX_POSITION_USD:,.0f}), stop 1-10%, "
          f"${stock_loss_limit(equity):,.0f} max loss per stock")
    if d.discovered_t:
        print(f"discovered {et_hms(d.discovered_t)}  10 min earlier {d.velocity_gain * 100:+.1f}%  ->  "
              f"{'momentum chase armed' if d.momentum_allowed else 'slow grind: no momentum chase'}  |  entries until "
              f"{et_hms(d.discovered_t + FRESH_ENTRY_SEC)}")
    rows = legs_table(legs)
    if not rows:
        print("No trades.")
        return
    cols = list(rows[0].keys())
    widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in cols}
    print("  ".join(k.ljust(widths[k]) for k in cols))
    for r in rows:
        print("  ".join(str(r[k]).ljust(widths[k]) for k in cols))
    total = sum(g["pnl"] for g in legs)
    trades = sum(1 for g in legs if g["closed"])
    wins = sum(1 for g in legs if g["closed"] and g["trade_pnl"] > 0)
    print(f"\nTrades {trades}  |  winners {wins}  |  net ${total:,.2f}")
    if csv_path:
        import csv
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"saved {csv_path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        print("usage: python lh_long_premarket.py SYMBOL YYYYMMDD [--csv out.csv] [--port 4001] [--equity 10000]")
        sys.exit(1)
    csv_out = None
    port = 4001
    if "--csv" in sys.argv:
        csv_out = sys.argv[sys.argv.index("--csv") + 1]
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    equity = REPLAY_EQUITY
    if "--equity" in sys.argv:
        equity = float(sys.argv[sys.argv.index("--equity") + 1])
    _ib_replay(args[0].upper(), args[1], csv_out, port=port, equity=equity)
