# LH Short Bot - folder layout (3.13.0, 2026-11-01)

Start the bot with **`main.py`** (or the old `lh_short_bot_app.py`, which starts `main.py`). Keep this layout together.

```
main bot version 3.12\
  main.py                     start file: sets up the import paths, runs core\ in order, builds the window, main()
  lh_short_bot_app.py         old start file - only starts main.py
  .env / .env.example         credentials (.env is never shared and never pushed to git)
  .gitignore                  what git leaves out (.env, logs, caches, backtest runs, vault files)
  build_bot_exe.bat           builds LHShortBot.exe (bundles core\ and ui\)
  build_installer.bat, LHShortBot.iss
  GIT_SETUP.md                how to push this folder to GitHub
  core\
    settings.py               THE SETTINGS - edit values here
    strategy_v16.py           the parked v16 bounce-zone + vacuum short
    bot\                      the auto-trading Bot class, split by job (one class, code unchanged)
      bot_core.py             class Bot: start, the 1-second loop, watchlist, strategy reads, vault feed hook
      orders.py               entries, covers, locates, order tracking, orders panel
      stops_halts.py          stop guard, your own stops, halts and the reopen logic
      sizing.py               the 09:00 sizing base, position size
      reconcile.py            TradeZero connection, reconciliation, restart rebuild, journal, state file
      status.py               log, Discord messages, end-of-day summary, heartbeat, goodbye
    data\
      IB.py                   market data: IB Gateway, scanner, chart data, candle cache
      helpers.py              .env, strategy selection, chart rows, settings file, alerts, journal, UI bridge
      vault_feed.py           the daily vault feed (monitored tickers -> the data vault the next day)
    broker\Tradezero.py       orders, positions, locates, fill history (TradeZero REST)
    notify\lh_discord.py      Discord messages and chart pictures
    window\jsapi.py           what the app window calls
    backtest_engine\lh_backtest.py   the Backtest tab's engine (separate process)
  ui\
    app.html, app.css         the window's screens and look
    js\01_boot.js ... 13_hotkeys.js  the window's code, one file per area (joined in order into one script)
  RELEASE_NOTES_3.13.0.md     what changed in 3.13.0 (Jay-read 2)
  tests\test_safety_313.py   safety checks (live lock, defaults, one short per stock, no secrets in .env.example)
  backtest\                   the strategies (the live bot loads them from here) + their backtests
    jay_read_2\               3.13.0 THE LIVE SHORT: jay_read_2_short.py (SETTINGS at the top: gapper / spiker sets),
                              jay_read_2_research.py (the research engine), jay_read_2_equivalence_test.py, runs\, notes.json
    combined_jr2_long\        Backtest tab: momentum long + Jay-read 2 (= the live bot)
    jay_read_short\           Jay-read v1.2 (off by default, still selectable): jay_read_short.py, jay_read_short_backtest.py
    max_squeeze_short\        max_squeeze_short.py, runs\, notes.json
    premarket_long\           lh_long_premarket.py, runs\, notes.json
    _shared\                  lh_combined_backtester.py, lh_combined_bulk_runner.py, lh_vault_bars.py
```

How it fits together:
- `core\settings.py`, `strategy_v16.py`, `data\helpers.py`, the six `bot\` files and `window\jsapi.py` run inside
  `main.py`'s own namespace, in that order, exactly as when it was one file. The Bot class is `bot_core.py`'s
  `class Bot` built from five parts (status, orders, stops_halts, sizing, reconcile). Every method is byte-for-byte the
  same code (checked: 176 methods identical, the same names and settings, the same window page).
- `IB.py`, `Tradezero.py`, `lh_discord.py`, `vault_feed.py`, `lh_backtest.py` are ordinary modules (their folders are
  on the import path).
- `ui\js\*.js` are joined in file order into the window's one script (checked: identical to the old app.js).
- An error message names the real file and line, e.g. `core\bot\stops_halts.py, line 212`.

Old files no longer used (delete them): `core\bot.py`, `core\helpers.py`, `core\jsapi.py`, `core\IB.py`,
`core\Tradezero.py`, `core\lh_discord.py`, `core\lh_backtest.py`, `core\vault_feed.py`, `ui\app.js`.

## Daily vault feed (core\data\vault_feed.py)

The bot keeps its own list of the ticker-days it monitored (`vault_queue.json` in the app data folder, separate from
the watchlist and favorites): every watchlist / scanner / manually added symbol, each day, and the premarket-long
tickers that actually traded (those also get 10-second bars). The list goes to Discord at 20:00 ET and every time the
bot stops. When the bot runs on a LATER day it fetches those days into `market_data_vault.db` in a separate process
(read-only IB client 82), then removes the day from the list. The vault path is the one set in the Backtest tab.
