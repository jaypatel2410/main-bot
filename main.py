#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LH SHORT BOT 3.12.0  -  Jay-read + max squeeze short auto-trader + premarket long
            (IB Gateway data, TradeZero orders, Discord notifications)
==================================================================================
3.12.1 (2026-10-30): SETTINGS SCREEN + JOURNAL FROM TRADEZERO
  - One Settings screen (gear, bottom left of the rail; F6): Trading (auto-trade, ext hours, sound, strategy modes),
    Signals, Skipped signals, Bot log, Hotkeys, Keys and Discord, Connection. The side menu (kebab) is gone.
  - Journal: TradeZero's fill history first (live accounts); the bot's journal files when TradeZero returns nothing
    (paper accounts always). Strategy labels come from the bot's journal; trades it never booked show as Manual / other.
  - Restart rebuild writes entry / exit times in New York time (was UTC).
  - 3.13 Backtest tab (rail flask icon, F8): runs Jay-read short / max squeeze short / premarket long (and your own
    backtest/<folder>/strategy.py) on the IB data vault in a separate process; results, breakdowns, equity, every
    trade's chart with entry / cover / stop, your verdict and notes per chart (backtest/<folder>/notes.json).
  - Scanner: after 16:00 also IB's after-hours gainers; double click a row = chart, single click = details.
  - Favorites (heart next to the ticker, rail button above Chart, F7): a permanent list you add to and remove from.
  - Right click on the chart: alert price above / below that price - fires once, Discord. Alerts are deleted when
    the app closes (and none are loaded at start). Alerts on any symbol now
    get their own live quote while they wait.
3.12.0 (2026-10-29): HALTS, THE STOP AT TRADEZERO, TRADEZERO AS THE TRUTH, 09:00 SIZING, SPLIT INTO FILES (the AZTR fixes)
  - Files: main.py (this file: settings, the bot, the window), IB.py (market data), Tradezero.py (orders, positions,
    locates), lh_discord.py (Discord), + jay_read_short.py, max_squeeze_short.py, lh_long_premarket.py. Start main.py
    (lh_short_bot_app.py still works: it starts main.py).
  - The stop goes to TradeZero the moment the short fills. A rejected / dropped stop is NEVER a reason to cover: the
    short is guarded - placed again every STOP_RETRY_SEC, "STOP NOT PLACED" pinged every minute until it is there,
    covered at market only if the price trades over the stop.
  - Halts: time (with seconds), direction, price; nothing is sent while halted (prices shown in a halt are ignored);
    from the halt + 5 min the reopen is checked every second and on every tick: opens over the stop -> market cover at
    once (the first thing sent, its own warm TradeZero line); under it -> the stop is at TradeZero. Repeated halts too.
  - TradeZero decides: your own stop is followed (the bot cancels its own - never two stops), a short you closed at
    TradeZero is booked at your fill price (also from "Covering..." - never stuck), no close alerts for closed shorts,
    a cover that fails keeps trying (waits for the reopen in a halt). A start rebuilds today from TradeZero's orders.
  - Sizing: the equity at 09:00 is the base; every short is 20% of it (also while others are open); re-set at each close.
  - The premarket long sells robustly (lh_long_premarket 1.9): floor under the last trade, bid sanity, no sell in a
    halt, a collar instead of a plain market order from 09:30.
3.11.0 (2026-10-25): ONE .env FILE, FAST HISTORY, SIGNALS ON OLDER DAYS, TRADING-PLATFORM SCREENS
  - Every credential in ONE file: .env next to the app (TradeZero keys / account / route, Discord webhook / ping, IB
    Gateway host / port / client id, the vault path). Created on the first start with what was already saved (the Keys
    dialog's tradezero.json / discord.json are copied in); the Keys dialog writes to it. .env.example = the template.
    Live trading still needs ALLOW_LIVE_TRADING = True in this file - the .env file cannot turn it on.
  - Fast history: 1-minute candles of finished days are kept in bar_cache.db (app data folder) and also read from your
    IB data vault (VAULT_DB), so a chart opens and older days load from disk; the next older days are fetched in the
    background before you scroll to them; IB requests 1 s apart (was a fixed 3 s).
  - Older days loaded by scrolling show the strategies' short / cover triangles (Jay-read + max squeeze, the backtest
    view) - display only, never an order.
  - Workspace: watchlist on the left, chart on the right; timeframe drop-down; ticker only (no company name); price
    alerts (Alt + click on the chart, Alerts tab, sound + Discord).
  - New screens (left rail): Scanner (live top gainers with what each strategy still needs), Journal (today / week /
    month / all: totals, P&L calendar, equity, per strategy, trades, CSV), Bot center (strategy cards with the mode
    switch, events, connections and speed, pause new entries), Hotkeys (order keys off by default, changeable).
3.10.1 (2026-10-25): start-up fix - the window no longer freezes 5-10 s ("not responding") at start: the page API object
  kept the window in a public attribute, so pywebview walked the window's native objects (the "Error while processing
  window.native..." lines in the log). Nothing else changed.
3.10.0 (2026-10-24): EVERYTHING TRADES, TRADING MODE IN THE APP, NEW DISCORD, LONG STOP +1%, PLATFORM LOOK, CHART HISTORY
  - Ships with every strategy trading (ALERT_ONLY = False, SQUEEZE_ALERT_ONLY = False, premarket long on). Each
    strategy has a trading mode in the app (menu -> Trading mode: Trading / Alert only / Off), saved in settings.json -
    no rebuild. The constants only give the start-up default.
  - Discord: a tag line above every title, posted as Shorts / Longs / System, no footer, no account number anywhere,
    @everyone only when you must act. New: IB Gateway disconnected / still down 5 min / back, IBKR link lost / back,
    TradeZero not answering / back / login failed, status every 30 min, day closed (shorts + longs), app closing.
  - Premarket long (lh_long_premarket.py 1.8): the hard stop sells at stop +1%; stop sales logged with the slippage.
  - The app: Webull-style chart (black, ext-hours band, no halt lines, the high as a small label, no HOD line, no
    skipped dots), trades as triangles at the exact fill price, Equity / BP / Day P&L / Unrealized in the top bar,
    the switches + trading modes + panels + connection in one menu, Positions tab, no footer, no account id.
  - Scroll left / zoom out on the open chart loads older candles (5 days of 1-minute, or 2 years of daily) from IB.
3.9.0 (2026-10-22): MAX SQUEEZE SHORT, LOCK TO ENTRY +5%, LOCATE SEARCH + LOCATE WINDOW, CLOSE PROMPT
  - Jay-read short v1.2 (jay_read_short.py): after a 25% fade the stop moves to the entry +5% (v1.1: 10% under the
    entry). A stop you changed - at TradeZero or with the app's stop box - is never moved by the bot, the lock included.
  - Max squeeze short (max_squeeze_short.py next to this file; SQUEEZE_SHORT = True, trading: SQUEEZE_ALERT_ONLY =
    False): a stock up 30%+ squeezes 50%+ over the last swing high it broke (where the average short went in); short the
    first red candle at the top, stop = the top +20%, no lock. It runs with the Jay-read short on the same stock: ONE
    short per stock at a time (the first signal wins) and a stop-out of either ends the stock for the day.
    Backtest (584 days, $10k a trade): both 98 trades, 71% win, +$120,316 (Jay-read v1.2 alone 92, 71%, +$94,065).
  - The bot's locates: never more than MAX_LOCATE_PCT (5%) of the price per share. No offer within it or no shares:
    it keeps searching - at most one request every LOCATE_RETRY_SEC (30 s), a LOCATE_PAUSE_SEC (2 min) break after
    every LOCATE_HUNT_SEC (3 min) of searching. After a signal it keeps searching and shorts once located, unless the
    price falls LOCATE_GIVE_UP_DROP_PCT (10%) under the signal close, reaches the stop or the entry window ends.
  - Locate window (orders panel -> Locates): symbol + shares -> TradeZero's offers (pre-borrow / re-usable and
    single-use: $ per share, total, % of the price) -> Buy. No price cap for your own locates. Today's locates are kept
    in locates_today.json (app data folder) until the day ends; the bot uses located shares first.
  - Closing the app while a position is open asks first: Yes = cancel the stops and close every position at market;
    No = leave the stops at TradeZero, keep the positions, close the app; Cancel = keep the app open.
  - Status bar: the strategies that run (it showed the parked v16 engine's name).
3.8.0 (2026-10-16): SAFETY + BACKTEST RULES
  - TradeZero is the truth. Every order whose answer is an error (any HTTP code - 16 Oct: LRHC buy answered 404 and
    filled) is looked up by its id before the bot believes it. The premarket long (lh_long_premarket.py 1.7) reads
    TradeZero's positions every 2 s while it holds or may hold shares: shares it did not know are taken over with a stop
    within ~4 s and sold like any long; shares gone at TradeZero are booked; stops are checked on the clock as well;
    sells retry through errors; the 09:00 flatten sells longs it never knew. The short bot compares positions every
    5 s: a short of the bot it does not hold (an entry answered with an error that filled) is taken over with a stop.
  - Like the backtest: no 5% daily account-loss stop on the short (MAX_DAILY_LOSS_PCT = None - a bad long morning no
    longer blocks the shorts), MAX_BOT_TRADES_PER_DAY 20 (was 8). The long keeps its own daily stop (50% of the long
    position); its 12.5% max loss per trade is removed (it never cut a trade).
  - Locates: shares already located in the account (by you or the bot) are used first - no new locate when they cover
    LOCATE_USE_EXISTING_MIN_PCT (50%) of the size; otherwise only the missing shares are located.
  - Discord / log texts never show the TradeZero account id.
3.7.2 (2026-10-16): NO RISK CAP ON THE SHORT - every Jay-read short is the full ACCOUNT_PCT (20%) of equity, max
  MAX_POSITION_USD ($50,000), as in the backtest's $298,787 run (MAX_RISK_PER_TRADE_USD = None). The 12.5% max-loss
  rule of 3.7.1 is withdrawn (3.7.2 = the 3.7.0 code with the cap off). The premarket long is unchanged: 20% of equity,
  max $10,000, its own 12.5% loss limit (never binds: its stop is at most 10%).
3.7.0 (2026-10-16): THE SHORT SIDE IS THE JAY-READ SHORT v1.1 (SHORT_STRATEGY = "jay_read", the default)
  jay_read_short.py (next to this file, used unchanged) reads every closed 1-minute candle of every watchlist symbol:
  stock up 150%+ with $20M+ traded, regular-hours high 10+ min old, cracked 20%+ (momentum broken), then
    A ROLLOVER        the bounce under the nearest overhead high rolls over near its top (red candle, 3%+ over VWAP)
    B OVERHEAD HIGH   the bounce comes up into a lower high it already failed at and is rejected there (from 10:00)
  Signals 09:35-15:00. Short = marketable limit right after the signal candle (the backtest: next open). Stop = the
  regular-hours high +3%; after a 25% fade the stop moves to 10% under the entry (the lock); done for the day after a
  stop; one short per stock, max 2 a day. Backtest (584 days): 96 trades, 75% win, +$86,306 at $10k a trade.
  ALERT_ONLY = True (default): every signal and its read goes to Discord, no short orders.
  MAX_RISK_PER_TRADE_USD: optional $ cap - shares cut so (stop - entry) x shares stays under it. None = off (3.7.2).
  JR_EOD_COVER_TIME: "15:55" = the bot covers Jay-read shorts at the 15:55 open (the backtest rule); None = off (the
  15:50 / 15:59 alerts, you close them). The auto short-scanner puts stocks up 100%+ on the watchlist (SHORT_SCANNER).

PARKED IN 3.7.0 (kept in this file, switch back with SHORT_STRATEGY = "v16" = exactly the 3.6.4 behaviour):
  S-01  v16 bounce-zone + vacuum short - the embedded Backtest engine, the bounce-zone limit, the vacuum trap, the
        pre-locate at VWAP +20%, every v16 setting below. Items 1-4 of the 3.6.4 description below describe it.
  Not in the app (research, see the project's PATTERN_REGISTRY): backside short, HCB, Patterns A / B, W20.

3.6.4 DESCRIPTION (the parked v16 short; the orders panel, Discord, safety and the premarket long are unchanged):
Desktop app (Windows). You type the tickers the bot should watch. For every
watchlist symbol it streams 1-minute candles from IB Gateway, runs the v16
strategy (bounce-zone + vacuum, one position at a time) on the closed candles
and trades it at TradeZero:

  1. PRE-LOCATE   the stock trades PRELOCATE_VWAP_PCT (20%) above VWAP = a
                  setup is forming: the bot asks TradeZero for a locate right
                  then (not when the signal fires). One locate per symbol per
                  day, re-used for every trade. Cap: MAX_LOCATE_PCT (5%) of
                  VWAP +20%. Single-use shares are reported but only bought
                  when a setup actually fires (still within the cap).
  2. VACUUM       high 15%+ above VWAP on dying volume, then a candle closes
                  5% under that peak: marketable short limit right away,
                  stop at the peak +3%. v16 rules: fills only until 11:00,
                  the peak candle must be a volume climax (1.5x its 15-candle
                  average), and after a vacuum stop-out the next vacuum needs
                  a peak 20%+ above the stopped one (staircase rule).
                  LIVE ONLY: no 50% gap and no 10M day-volume requirement for
                  the vacuum (VAC_REQUIRE_GAP / VAC_USE_MIN_VOLUME = False);
                  the backtester keeps both on.
     BOUNCE-ZONE  gap 50%+, top, dip 20%+, bounce into the 12-10% zone under
                  the top: resting short limit 12% under the top, stop top +3%.
                  Whichever comes first trades; the other waits for the stop.
  3. STOP         placed the moment the short fills (at least
                  MIN_STOP_ABOVE_FILL_PCT above the fill). Change the stop at
                  TradeZero (or with the Stop button) any time: the bot follows
                  your stop. If it fills, the strategy keeps running.
  4. NO COVER AT THE CLOSE  urgent Discord message (with chart) at 15:50 and
                  15:59 for every open short - you close them.
  5. ORDERS PANEL under the chart (v3.3): pending and filled orders side by
                  side, live from TradeZero. Click a price to change it, Cancel
                  (two clicks) to cancel. Cancel a bot entry = that trade is
                  skipped and the bot looks for the next setup; cancel a bot
                  stop or cover = you take that short over (no stop).

  6. PREMARKET LONG (v3.6) - lh_long_premarket.py, the second file next to this one, runs inside this app
                  05:00-09:00 ET on weekdays with the same IB Gateway connection, TradeZero account and Discord:
                  IBKR scanner for +30% movers ($0.50+), momentum chase on 10-second bars in the first 20 minutes
                  after the +30% cross, max 3 trades per stock (the rules of your premarket long backtest).
                  Size 20% of the account equity (compounding), max $10,000 per long; stop 1-10% under the entry,
                  a stock is done after losing 25% of the position ($500 on a $10,000 account) - it grows with it.
                  Surge candle: RVOL 1.5+, close in the top 40% of its range (3.6.3). Daily stop (3.6.4): no new
                  longs once today's long loss reaches 50% of the long position size ($1,000 on a $2,000 position,
                  $5,000 at the $10,000 cap). A buy is skipped when the ask is more than 10% over the trigger.
  7. LOOK (v3.6.4) - black window, white up / red down candles, VWAP + volume on the chart.
                  Buy at the ask, sell at the bid, everything sold from 09:00. Its trades are in the Orders panel ->
                  "Premarket long" tab (active / closed, ON-OFF switch). The short bot never shorts a symbol
                  while the long still holds it. Settings: top of lh_long_premarket.py.

  Discord    Every step goes to your Discord channel (webhook): start-up test
             message, ticker added, setups, locate request + offers + totals,
             orders, fills, stops, your stop changes, covers, exits, 15:50
             alert, daily summary, connection problems. v3.4: every symbol
             message carries the "stock flow" picture - a clean line chart
             with VWAP, the high of day, the lower highs, where the price is
             now and the plan (short level, stop, T1 / T2 supports, the
             expected path) - plus the 1-minute candle chart.
  Strategy   The Backtest engine and every strategy parameter below are a
             verbatim copy of lh_short_backtester.py v16.
  Data       IB Gateway (TradeZero's API has no market data).
  Orders     TradeZero Developer API (https://webapi.tradezero.com). Paper
             accounts: auto-trade turns on by itself. LIVE accounts are locked
             until ALLOW_LIVE_TRADING = True.
  Safety     Flatten all, per-symbol Cover / Stop buttons, daily trade and loss
             limits, trade journal bot_trades.csv in the app data folder.
  Network    One kept-open connection to TradeZero per worker (no new TLS
             handshake every second), automatic retries, and an order whose
             answer was lost is looked up by its id - never sent twice.

Run:     python main.py        (with its core/ and ui/ folders and backtest/ - see README_FILES.md;
                               the SETTINGS are in core/settings.py)
Needs:   pip install pywebview ib_async pandas numpy tzdata matplotlib
"""

# =============================================================================
# 3.12.1: the code is organised in folders - core/ (settings, bot/, data/, broker/, notify/, window/, backtest_engine/)
# and ui/ (the app window: app.html, app.css, js/*.js). The core/*.py parts below run in THIS file's namespace, in this order, so every
# name works exactly as when main.py was one file. IB.py, Tradezero.py, lh_discord.py and lh_backtest.py are normal
# modules in core/.
# =============================================================================
import os as _os
import sys as _sys

_SRC_DIR = getattr(_sys, "_MEIPASS", None) or _os.path.dirname(_os.path.abspath(__file__))
_CORE_DIR = _os.path.join(_SRC_DIR, "core")
_UI_DIR = _os.path.join(_SRC_DIR, "ui")
for _sub in ("", "data", "broker", "notify", "backtest_engine", "window", "bot"):   # 3.12.1: core/ sub-folders
    _p = _os.path.join(_CORE_DIR, _sub) if _sub else _CORE_DIR
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


def _part(name):
    """Run core/<name> in this module's namespace (tracebacks show core/<name> and its line)."""
    path = _os.path.join(_CORE_DIR, name)
    with open(path, encoding="utf-8") as fh:
        exec(compile(fh.read(), path, "exec"), globals())


def _ui(name):
    with open(_os.path.join(_UI_DIR, name), encoding="utf-8") as fh:
        return fh.read()


_part("settings.py")

# =============================================================================
# IMPORTS
# =============================================================================
import asyncio
import calendar
import io
import json
import logging
import math
import os
import re
import sqlite3
import sys
import threading
import time
import http.client
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date as ddate, datetime, time as dtime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import numpy as np
import pandas as pd

try:
    from ib_async import IB, Stock, ScannerSubscription, TagValue
except ImportError:  # older installs
    try:
        from ib_insync import IB, Stock, ScannerSubscription, TagValue
    except ImportError:
        IB = Stock = ScannerSubscription = TagValue = None
try:                                     # 3.11: cached candles are put back into IB's candle list as IB bar objects
    from ib_async import BarData as _IBBar
except ImportError:
    try:
        from ib_insync import BarData as _IBBar
    except ImportError:
        _IBBar = None

# 3.12.1: the strategy files live in backtest/<strategy>/ (one folder each; the bot and the Backtest tab use the same
# files). The folders go first on the import path; a copy left next to main.py is no longer used.
_APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
for _sub in ("_shared", "premarket_long", "max_squeeze_short", "jay_read_short", "jay_read_2"):   # 3.13: + jay_read_2
    _sp = os.path.join(_APP_DIR, "backtest", _sub)
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)

try:                                     # v3.5: the premarket long module (lh_long_premarket.py next to this file)
    import lh_long_premarket as LP
    LP_IMPORT_ERROR = ""
except Exception as _lp_exc:             # missing / broken: the short bot runs without it (reported in the bot log)
    LP = None
    LP_IMPORT_ERROR = f"{_lp_exc.__class__.__name__}: {_lp_exc}"

try:                                     # v3.7: the Jay-read short (jay_read_short.py next to this file, used unchanged)
    import jay_read_short as JR
    JR_IMPORT_ERROR = ""
except Exception as _jr_exc:             # missing / broken: no Jay-read shorts (reported at start-up); "v16" still works
    JR = None
    JR_IMPORT_ERROR = f"{_jr_exc.__class__.__name__}: {_jr_exc}"

try:                                     # 3.13.0: Jay-read 2 (backtest/jay_read_2/jay_read_2_short.py)
    if JAY_READ_2:
        import jay_read_2_short as JR2
        JR2_IMPORT_ERROR = ""
    else:
        JR2, JR2_IMPORT_ERROR = None, "switched off (JAY_READ_2 = False)"
except Exception as _jr2_exc:            # missing / broken: no Jay-read 2 shorts (reported at start-up)
    JR2 = None
    JR2_IMPORT_ERROR = f"{_jr2_exc.__class__.__name__}: {_jr2_exc}"

SQ, SQ_IMPORT_ERROR = None, "not used live (SQUEEZE_SHORT = False)"   # 3.12.2: backtest only
try:                                     # 3.9.0: the max squeeze short (max_squeeze_short.py next to this file)
    if SQUEEZE_SHORT:
        import max_squeeze_short as SQ
        SQ_IMPORT_ERROR = ""
except Exception as _sq_exc:             # missing / broken: the Jay-read short runs alone (reported at start-up)
    SQ = None
    SQ_IMPORT_ERROR = f"{_sq_exc.__class__.__name__}: {_sq_exc}"

# 3.12: the code lives in separate files next to this one (main.py binds itself first: they read the settings
# below as app.NAME). IB.py = market data (IB Gateway), Tradezero.py = orders / positions / locates,
# lh_discord.py = Discord messages + chart pictures. jay_read_short.py, max_squeeze_short.py, lh_long_premarket.py =
# the strategies.


class _HostRef:
    """This file as the other files see it (app.NAME = NAME here) - only used when this file was loaded without being
    registered as a module (a test loading it by path); normally it is the module itself."""
    __slots__ = ("_g",)

    def __init__(self, g):
        object.__setattr__(self, "_g", g)

    def __getattr__(self, name):
        try:
            return self._g[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self._g[name] = value


_me = sys.modules.get(__name__)
HOST = _me if _me is not None and vars(_me) is globals() else _HostRef(globals())
sys.modules["lh_host"] = HOST
import Tradezero as _tz_mod  # noqa: E402
_tz_mod.app = HOST
from Tradezero import (  # noqa: E402,F401
    DONE_STATES, LOCATE_TYPES, OPEN_STATES, TZClient, TZError, _NetFail, _fnum, _olimit, _oside, _ostop, _otype,
    _tick_px, _tz_time, px_round, tz_load_keys, tz_save_keys)
import lh_discord as _dc_mod  # noqa: E402
_dc_mod.app = HOST
from lh_discord import (  # noqa: E402,F401
    COLORS, Discord, FLOW_BG, FLOW_DIM, FLOW_FG, FLOW_PRICE, FLOW_SETUP, FLOW_SHORT, FLOW_STOP, FLOW_TGT,
    FLOW_VWAP, _EMOJI_RE, _flow_pivots, _fpx, _queue, _render_flow, _spread_labels, _uuid, chart_rows_today,
    dc_style, discord_load, discord_save, discord_url_ok, render_chart_png, render_flow_png)
import IB as _ib_mod  # noqa: E402
_ib_mod.app = HOST
from IB import (  # noqa: E402,F401
    Backend, BarCache, CACHE_MAX_DAYS, CACHE_SCHEMA, SESSION_START_SEC, SymState, _wd, candle_tuples,
    chart_to_utc, ib_bar, pick_details, prior_closes, prior_for, rows_from_tuples)

_part("strategy_v16.py")
_part("data/helpers.py")
for _bp in ("status.py", "orders.py", "stops_halts.py", "sizing.py", "reconcile.py", "checks.py", "bot_core.py"):
    _part("bot/" + _bp)                          # the Bot class: 5 parts (mixins) + bot_core.py (class Bot)
_part("window/jsapi.py")

# -----------------------------------------------------------------------------
# Page (ui/app.html + ui/app.css + ui/app.js)
# -----------------------------------------------------------------------------
_JS_FILES = ('01_boot.js', '02_chart.js', '03_trading_orders.js', '04_app_shell.js', '05_alerts_screens.js', '06_colors.js', '07_favorites.js', '08_backtest.js', '09_chart_alerts_settings.js', '09b_chart_notes.js', '10_scanner.js', '11_journal.js', '12_bot_center.js', '12b_notes_ib.js', '13_hotkeys.js')   # ui/js/*, joined in this order into one script
HTML = _ui("app.html").replace("__APP_CSS__", _ui("app.css").rstrip("\n")).replace(
    "__APP_JS__", "".join(_ui("js/" + _f) for _f in _JS_FILES).rstrip("\n"))



def build_html(lib_js):
    if lib_js:
        script = "<script>" + lib_js.replace("</script", "<\\/script") + "</script>"
    else:
        base = f"lightweight-charts@{LWC_VERSION}/dist/lightweight-charts.standalone.production.js"
        script = ('<script src="https://cdn.jsdelivr.net/npm/' + base + '" onerror="(function(){var s=document.createElement(\'script\');'
                  's.src=\'https://unpkg.com/' + base + '\';s.onload=function(){window.__bootChart&&window.__bootChart();};'
                  'document.head.appendChild(s);})()" onload="window.__bootChart&&window.__bootChart()"></script>')
    return (HTML.replace("__LWC_SCRIPT__", script).replace("__UP__", CANDLE_UP_COLOR)
            .replace("__DOWN__", CANDLE_DOWN_COLOR).replace("__VWAP__", VWAP_COLOR)
            .replace("__GRID__", "true" if CHART_GRID else "false"))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    global STRAT, STRATEGY_SOURCE
    import multiprocessing as _mp
    _mp.freeze_support()                         # 3.13: the Backtest tab runs in its own process (also in the .exe)
    if sys.stdout is None:                      # windowed .exe has no console
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    _setup_logging()
    try:                                           # 3.11: one .env file for every credential
        moved = env_migrate()
        env_apply()
        es = env_status()
        log.info(".env: %s - set: %s%s", es["file"], ", ".join(es["set"]) or "nothing",
                 f" (copied in from the old key files: {', '.join(moved)})" if moved else "")
    except Exception:
        log.exception(".env")
    STRAT, STRATEGY_SOURCE = _select_strategy()
    if jr_mode():
        STRATEGY_SOURCE = jr_source()
    _init_constants()
    log.info("%s %s starting - strategies: %s (%s) - IB %s:%s", APP_NAME, APP_VERSION, strategy_label(), STRATEGY_SOURCE,
             IB_HOST, IB_PORT)
    try:
        import webview
    except ImportError:
        print("pywebview is not installed. Run:  pip install pywebview")
        sys.exit(1)

    settings = Settings()
    html = build_html(load_chart_lib())
    bridge = UiBridge()
    backend = Backend(bridge, settings)
    api = JsApi(backend, settings)
    window = webview.create_window(f"{APP_NAME} {APP_VERSION}", html=html, js_api=api, width=1500, height=920,
                                   min_size=(1000, 620), background_color="#000000")
    bridge.window = window
    api._window = window
    window.events.loaded += bridge.on_loaded

    def on_closing(*_):
        """3.9.0: a position is open - ask first (Yes / No / Cancel on the page); returning False keeps the window."""
        if api._exit_ok["v"]:
            return True
        try:
            b = backend.bot
            opens = b.open_positions() if b is not None else []
        except Exception:
            opens = []
        if not opens:
            return True
        bridge.call("askClose", {"items": opens})
        return False

    window.events.closing += on_closing

    def on_closed(*_):
        bridge.close()
        threading.Thread(target=backend.stop, daemon=True).start()

    window.events.closed += on_closed

    def started():
        threading.Thread(target=bridge.run, name="ui-bridge", daemon=True).start()
        backend.start()

    webview.start(started, debug=DEBUG_DEVTOOLS)
    bridge.close()
    backend.stop()
    log.info("closed")
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
