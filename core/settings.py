# -*- coding: utf-8 -*-
"""LH Short Bot - the settings (edit these values; they used to be at the top of main.py).
Part of main.py: main.py runs this file in its OWN namespace (same names, same settings), so the code works exactly
as when it was one file. Do not run it on its own - start main.py."""
# =============================================================================
# APP SETTINGS
# =============================================================================
IB_HOST = "127.0.0.1"
IB_PORT = 4001                     # IB Gateway live = 4001, paper = 4002  (TWS: 7496 live / 7497 paper)
IB_CLIENT_ID = 101                 # moves to the next free id automatically if this one is taken
MARKET_DATA_TYPE = 1               # 1 = live streaming (needs your IBKR data subscription), 3 = delayed

HISTORY_DURATION = "5 D"           # 1-minute history loaded per symbol (5 trading days = one week)
DAILY_HISTORY = "2 Y"              # daily candles loaded when you switch to the D timeframe
HISTORY_MORE_1M = "5 D"            # 3.10: scrolling left (or zooming out) past the oldest candle loads this much older
HISTORY_MORE_DAILY = "2 Y"         # 1-minute history (1D chart: this much older daily history) - only for the chart that
HISTORY_MORE_MIN_GAP_SEC = 1.0     # is open, never for the watchlist / the bot. At most one IB request every this many s
HISTORY_MAX_1M_BARS = 150_000      # (3.11: 1 s, was 3 s - IB allows 60 requests / 10 min). The page keeps at most this
                                   # many 1-minute candles (~6 months)
BAR_CACHE = True                   # 3.11: finished days' 1-minute candles kept in bar_cache.db (app data folder) - charts
                                   # open and older days load from disk; only today (and missing days) come from IB
HISTORY_PREFETCH = True            # 3.11: the next older days of the open chart are fetched in the background (to the
                                   # cache) before you scroll to them
FAST_OPEN = True                   # 3.11: opening a chart asks IB only for today when the cache already has the earlier
                                   # days of the week (False = always the full HISTORY_DURATION from IB)
VAULT_DB = ""                      # 3.11: your IB data vault (market_data_vault.db) - read only, used before IB for
                                   # older days. "" = not used. Set it in .env (VAULT_DB=C:\...\market_data_vault.db)
OLDER_DAY_SIGNALS = True           # 3.11: older days loaded by scrolling show the strategies' triangles (display only)
SCAN_SCREEN_ROWS = 30              # 3.11 Scanner screen: IBKR top % gainers shown (live quotes only while it is open)
SCAN_SCREEN_EVERY_SEC = 15         # ... the scan is repeated this often; the quotes stream in between
# 3.11: the backtest the Journal / Bot center compare with (584 research days 2026-04-01 to 2026-10-05, combined account,
# LONG_BARS = "rebuild": 224 trades, 63% win, $410,857 from $10,000)
BT_REF = {"jr2": {"n": 108, "win": 69}, "jr": {"n": 83, "win": 70}, "sq": {"n": 15, "win": 80}, "long": {"n": 126, "win": 57}}
DEFAULT_TIMEFRAME = "1"            # "1", "2", "5", "15", "30" minutes or "D" (your last choice is remembered)
DEFAULT_SYMBOL = ""                # symbol opened at start-up ("" = the last symbol you viewed)

# TradeZero (orders, locates, positions). 3.11: the keys live in the .env file next to the app (TZ_API_KEY_ID,
# TZ_API_SECRET, TZ_ACCOUNT_ID, TZ_ROUTE) - menu -> Keys and Discord writes them there too.
TZ_BASE_URL = "https://webapi.tradezero.com"
TZ_API_KEY_ID = ""                 # leave empty - use the .env file
TZ_API_SECRET = ""
TZ_ACCOUNT_ID = ""                 # "" = the first account the keys can see
TZ_ROUTE = ""                      # "" = TradeZero's default route (paper: PAPER). Live example: "SMART"
ALLOW_LIVE_TRADING = False         # SAFETY: must be True before the bot sends orders on a LIVE account
AUTO_TRADE_ON_START = False        # LIVE account: auto-trade switch at start-up (the switch in the app is the real control)
AUTO_TRADE_ON_START_PAPER = True   # PAPER account: auto-trade turns ON by itself once TradeZero connects

# Bot sizing and limits
ACCOUNT_PCT = 20.0                 # position size = this % of account equity (your Excel snowball method)
MAX_POSITION_USD = 50_000          # never more than this $ per short
MAX_LOCATE_PCT = 5.0               # locate must cost at most this % of the entry price per share (pre-locate: of VWAP +20%)
LOCATE_ON_PAPER = False            # paper accounts have no locate inventory - shorts are placed without a locate
LOCATE_USE_EXISTING_MIN_PCT = 50.0  # 3.8.0: shares ALREADY located in the account (by you in ZeroPro / the web, or by
                                   # the bot earlier today) are always used first. If they cover at least this % of
                                   # the short's size, the bot shorts just those shares and buys NO new locate (pre-
                                   # locate and entry); below it, it locates only the missing shares.
                                   # 100 = always top up to the full size; 0 = never buy when any located shares exist
MAX_BOT_TRADES_PER_DAY = 20        # all symbols together (3.8.0: was 8 - the backtest has no such cap; 20 never binds)
MAX_DAILY_LOSS_PCT = None          # 3.8.0: None = off, like the backtest - the short keeps trading after a bad long
                                   # morning (the long has its own daily stop). A number = no new shorts once the day's
                                   # account P&L reaches -this % of start-of-day equity
MAX_WATCHLIST = 15                 # symbols the bot can watch at once
TICK_BY_TICK_MAX = 5               # 3.12.2: stocks that get IB tick-by-tick (every trade) - positions first, then live
                                   # short setups, the premarket-long list, your own adds (0 = off)
ORDER_POLL_SEC = 1.0               # order status polling while an entry / cover order is working
STOP_POLL_SEC = 2.0                # how often the stop order is checked (your stop changes at TradeZero are picked up)
ORDERS_POLL_SEC = 2.0              # orders panel under the chart: TradeZero's order list is read this often
POS_CHECK_SEC = 5                  # 3.8.0: TradeZero's positions are compared with the bot this often (was 10)
UNKNOWN_SHORT_CONFIRM_SEC = 4      # 3.8.0: a short of the bot it does not hold (an entry answered with an error that
                                   # filled) must show on 2 checks this far apart before the bot takes it over
TZ_NET_ALERT_AFTER = 3             # calls in a row with no answer from TradeZero (each already retried) before Discord
                                   # is told - a single network blip is only written to the bot log

# Short strategy (3.7.0). The v16 bounce-zone + vacuum short is PARKED, not deleted: "v16" restores 3.6.4 exactly.
SHORT_STRATEGY = "jay_read"        # "jay_read" = Jay-read short v1.2 (jay_read_short.py next to this file)
                                   # "v16"      = the parked bounce-zone + vacuum short (LH Short Bot 3.6.4)
JAY_READ_FILE = "jay_read_short.py"  # the module file next to this one (imported as jay_read_short - keep the name)
JAY_READ_2 = True                  # 3.13.0: Jay-read 2 (backtest/jay_read_2/jay_read_2_short.py) - the first failed bounce
                                   # near the top, gapper / spiker rules. Its settings: SETTINGS at the top of that file
JR2_ALERT_ONLY = False             # 3.13.0: start-up default of Jay-read 2's trading mode: False = Trading, True = Alert only
JR_V12_DEFAULT_MODE = "off"        # 3.13.0: start-up default of the old Jay-read v1.2 short: "off" / "alert" / "trading"
                                   # (still selectable in the app: menu -> Trading mode). Both on = one short per stock
ALERT_ONLY = False                 # 3.10: the START-UP default of the Jay-read short's trading mode (used until you pick a
                                   # mode in the app: menu -> Trading mode, saved in settings.json). True = Alert only
                                   # (signals + "would short here" to Discord, no orders). False = Trading
MAX_RISK_PER_TRADE_USD = None      # 3.7.2: None = no cap - the full 20% of equity (max $50,000) on every Jay-read short,
                                   # as in the backtest ($298,787). A number = shares cut so (stop - entry) x shares <= that
                                   # $ (the stop is the regular-hours high +3%, median 28% over the entry)
JR_EOD_COVER_TIME = "15:55"        # 3.13.0: "15:55" (Jay-read 2's rule). Jay-read + max squeeze shorts: "15:55" = the bot covers at market at the 15:55 open (the
                                   # backtest rule: 66 of 96 trades closed there). None = no automatic cover: the 15:50 /
                                   # 15:59 urgent alerts as before and you close them. The v16 short never auto-covers.
JR_ENTRY_SLIP_PCT = 3.0            # Jay-read entry = marketable limit this % under the last price (fills at the bid)
JR_ENTRY_TIMEOUT_SEC = 20          # cancel the entry if it is not filled within this many seconds
JR_SIGNAL_MAX_AGE_SEC = 90         # a signal older than this when the order would go out (slow locate) is dropped
JR_PRELOCATE = True                # locate as soon as the read says "momentum broke" (150%+, $20M, high 10+ min old,
                                   # cracked 20%+), so the shares are ready before the signal. Never in ALERT_ONLY mode
SQUEEZE_SHORT = False              # 3.12.2: OFF - removed from live trading (Jay, 10-31); still in the Backtest tab. 3.9.0: the max squeeze short (max_squeeze_short.py next to this file) runs next to the
                                   # Jay-read short - one short per stock at a time (the first signal wins), a stop-out of
                                   # either ends the stock for the day. False = the Jay-read short alone
SQUEEZE_ALERT_ONLY = False         # 3.10: the start-up default of the max squeeze short's trading mode (the app's menu ->
                                   # Trading mode rules once you pick one). False = Trading, True = Alert only
SQUEEZE_FILE = "max_squeeze_short.py"  # imported as max_squeeze_short - keep the name

# Auto short-scanner (3.7.0, Jay-read only): IBKR top % gainers -> the short watchlist (no more typing tickers)
SHORT_SCANNER = True               # False = you add the tickers yourself (stocks up 100%+, before the high fades)
SHORT_SCAN_MIN_UP_PCT = 100.0      # add stocks up at least this % from the prior close (Jay-read itself needs 150%)
SHORT_SCAN_MIN_PRICE = 0.50
SHORT_SCAN_START = "07:00"         # scanning window (ET, weekdays)
SHORT_SCAN_END = "15:00"
SHORT_SCAN_INTERVAL_SEC = 30
SHORT_SCAN_DROP_NEXT_DAY = True    # stocks the scanner added are removed the next day (if no order / position is open)

# Locates: ONE locate per symbol per day, bought early and re-used for every trade that day
PRELOCATE_VWAP_PCT = 20.0          # stock this % above VWAP = setup forming: request the locate NOW (price basis VWAP + this %)
PRELOCATE_START = "09:30"          # pre-locates from this time. "08:00" = also premarket (share count then uses the premarket price)
PRELOCATE_ACCEPT_SINGLE_USE = False  # False = single-use shares are reported, bought only when a setup fires (within the cap)
LOCATE_WAIT_SEC = 25               # wait up to this long for TradeZero's offer (an offer expires 30 s after it arrives)
LOCATE_RETRY_SEC = 30              # 3.9.0 locate search (Jay-read / max squeeze): no offer within MAX_LOCATE_PCT or no
                                   # shares -> ask again, at most one request every this many seconds per symbol ...
LOCATE_HUNT_SEC = 180              # ... and after this many seconds of searching a break of ...
LOCATE_PAUSE_SEC = 120             # ... this many seconds, then search again. Before a signal: until located, the stock is
                                   # done for the day or 15:00. After a signal: see LOCATE_GIVE_UP_DROP_PCT
LOCATE_GIVE_UP_DROP_PCT = 10.0     # after a short signal the bot keeps searching and shorts once located; it gives up (no
                                   # short) once the price is this % under the signal candle's close, at the stop, or the
                                   # entry window (15:30) ended
MAX_LOCATE_REQUESTS_PER_SYMBOL = 300  # safety cap: locate requests per symbol per day (3.8: 3 - the search needs more)

# Entries and trade management
VAC_ENTRY_SLIP_PCT = 3.0           # vacuum short = marketable limit this % under the last price (fills at the bid; a
                                   # protection band, not the expected fill)
VAC_ENTRY_TIMEOUT_SEC = 20         # cancel the vacuum short if it is not filled within this many seconds
MIN_STOP_ABOVE_FILL_PCT = 2.0      # the stop is at least this % above the fill price (fill after a fast spike)
REPLACE_REMOVED_STOP = True        # you cancel the stop and place none: urgent alert, then the bot puts its stop back
STOP_GRACE_SEC = 60                # ... after this many seconds
# 3.12 halts and the broker-side stop (the AZTR fix): a halt is NEVER a reason to cover. A stop TradeZero rejects /
# cancels during a halt is put back the instant trading resumes - or the short is covered at market at once when the
# stock reopens over the stop. Prices shown during a halt (indications, e.g. $100 on a $2 stock) are ignored.
HALT_REOPEN_WAIT_SEC = 300         # a halt lasts 5 minutes: from the halt time + this, the reopen is checked every ...
HALT_CHECK_SEC = 1.0               # ... this many seconds (and on every IB tick: the first real trade after the halt decides)
HALT_SANE_X = 4.0                  # a reopen price more than this x over / under the halt price is not believed (fake print)
STOP_RETRY_SEC = 2.0               # a stop TradeZero rejected / cancelled (not you): placed again this often while trading,
STOP_PING_SEC = 60                 # ... and Discord is pinged this often ("STOP NOT PLACED") until it is at TradeZero
COVER_RETRY_SEC = 10.0             # a cover that keeps failing (not halted) is sent again this often (pinged every minute)
SIZE_BASE_TIME = "09:00"           # 3.12 sizing: the account equity at this time (ET) is the base; every short is
                                   # ACCOUNT_PCT of the base - also while other trades are open (their P&L does not change
                                   # it). When a trade closes, the base is re-set (equity after the close)
EOD_AUTO_COVER = False             # False = the bot never covers at the close: urgent Discord alert instead (you close)
EOD_ALERT_TIME = "15:50"           # urgent alert with every open short (again at 15:59 if still open)

# Discord notifications (webhook). Paste the webhook URL in the app: Keys -> Discord (saved in discord.json)
DISCORD_WEBHOOK_URL = ""           # leave empty - use the .env file (DISCORD_WEBHOOK_URL=...)
DISCORD_MENTION = "@everyone"      # added to urgent messages (no stop, 15:50 alert, flatten). "" = no ping, "<@user id>" = you
DISCORD_NAME_SHORTS = "Shorts"     # 3.10: the name each message is posted under - the short side ...
DISCORD_NAME_LONGS = "Longs"       # ... the premarket long ...
DISCORD_NAME_SYSTEM = "System"     # ... and the app (start, connections, status, mode changes, closing)
DISCORD_USERNAME = DISCORD_NAME_SYSTEM
DISCORD_FLOW_IMAGES = False        # 3.10: off - one picture per message (the 1-minute candle chart). True = also the
                                   # "stock flow" picture (price line, VWAP, HOD, lower highs, the plan) as before
DISCORD_CHART_IMAGES = True        # also the 1-minute candle chart (second picture) on setup / locate / trade messages
DISCORD_CHART_MINUTES = 150        # minutes of candles on the chart image (trade charts reach back to the entry)
DISCORD_IMAGE_MIN_GAP_SEC = 20     # at most one picture set per symbol this often (setups, locates, orders, fills, stops,
                                   # covers, exits and alerts always get one)
DISCORD_HEARTBEAT_MIN = 30         # status message every N minutes from 4:00 to 20:00 ET (0 = off)
IB_REPORT_TIMES = ("10:00", "12:00")  # 3.14: the IB portfolio (market value, today's P&L, unrealized - in CAD) to Discord
                                   # at these ET times on weekdays. () = off

# Premarket long (v3.5): lh_long_premarket.py next to this file trades 05:00-09:00 ET inside this app (same IB Gateway,
# TradeZero account and Discord). Its own settings (times, scanner, size, limits) are at the top of that file.
LONG_PREMARKET = True              # False = the premarket long is not started at all. True = it runs; its trading mode
                                   # (Trading / Alert only / Off) is picked in the app: menu -> Trading mode

EXTENDED_HOURS_DEFAULT = True      # show pre/after-market candles (toggle in the app)
SHOW_SKIPPED_DEFAULT = False       # show skipped signals as grey dots (toggle in the app)
SHOW_DAY_LEVELS = False            # True = draw HOD, PM high and prev close lines on the chart
SOUND_ALERTS_DEFAULT = True        # beep on new short signals and covers (toggle in the app)

CANDLE_UP_COLOR = "#e6e8eb"        # v3.6.4: white up / red down on black. TradingView look: "#089981" / "#f23645"
CANDLE_DOWN_COLOR = "#f23645"
VWAP_COLOR = "#ff9800"
CHART_GRID = False                 # True = show grid lines on the chart

FINALIZE_DELAY_SEC = 4             # after a candle closes: wait, re-sync it with IB's final bar, then run the strategy
ENGINE_INTERVAL_SEC = 5            # while a trade is open, re-check stop / targets this often
HEARTBEAT_SEC = 20                 # connection heartbeat
STALE_STREAM_SEC = 75              # re-subscribe if trades print but no candle update arrives for this long
FINALIZE_MIN_GAP_SEC = 20          # at most one candle re-sync request per this many seconds (IB pacing)

USE_EXTERNAL_STRATEGY = False      # True = load lh_short_backtester.py from the app folder instead of the embedded copy
EXTERNAL_STRATEGY_FILE = "lh_short_backtester.py"
LWC_VERSION = "4.2.3"              # TradingView lightweight-charts (downloaded once, then cached)
DEBUG_DEVTOOLS = False             # True = open the browser dev tools (troubleshooting)
