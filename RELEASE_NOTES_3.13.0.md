# Kestrel 3.13.0 - Jay-read 2 (2026-11-01)

**Paper-trade first.** Live trading stays locked (`ALLOW_LIVE_TRADING = False` in `core\settings.py`; the `.env` file cannot switch it on).

## What changed

**New short strategy: Jay-read 2** (`backtest\jay_read_2\jay_read_2_short.py`)
- Shorts the first failed bounce near the top. It is the research engine `run_day()` from `jay_read_2_research.py`, ported one closed 1-minute candle at a time.
- It has the same API as the Jay-read short, so it uses the existing ShortBook and the existing order and safety code. No new order paths.
- **Two rule sets**, chosen by the 09:30 open vs the prior close:
  - **Gapper** (open +30%+): the GAP2 settings.
  - **Spiker** (under +30%): the SPK2 settings. The flush low must reach VWAP.
- **Entry rules:**
  - stock up 200%+ (high of day, premarket included), with $20M+ traded;
  - regular-hours high 10–180 minutes old;
  - flush 25–60% under that high;
  - the first bounce takes back 40–85% of the flush, with no new high (at most +1%);
  - trigger: a red candle, or an upper wick ≥50% of the range, within 6 candles of the bounce high;
  - the trigger closes within 6% of the bounce high and 5%+ over VWAP;
  - short at the next candle's open.
- **Limits:** signals 09:35–15:00, one short per high, max 2 trades per stock per day, done for the stock after a stop-out, skip after 8 halt jumps.
- **Exits:**
  - stop = high of day (premarket included) +5%;
  - lock: after a 25% fade, the stop moves to entry +5%;
  - cover at 15:55.
- **Settings:** all in one `SETTINGS` dict at the top of the file. The GAPPER and SPIKER sets are shown in full and can be edited.

**Bot**
- **Trading mode:** a new "Jay-read 2 short" row (menu → Trading mode, and the Bot center).
- **Defaults:**
  - Jay-read 2: **Trading**.
  - Jay-read v1.2: **Off**, but still selectable. If you switch both on, they share one short per stock.
  - Max squeeze: **Off**.
  - Modes saved before 3.13 do not switch v1.2 back on.
- **Labels:** the log and Discord show "JR2 gapper" or "JR2 spiker"; the journal codes are `JR2_G` and `JR2_S`.
  - The signal message gives the read: high, flush, first bounce, VWAP, and the stop at high of day +5%.
  - The status line, the scanner chips and the signal panel show Jay-read 2's rules.
- **Sizing:** unchanged. 20% of the 09:00 equity, max $50k, through the same entry, stop, lock and halt code.
- **`JR_EOD_COVER_TIME = "15:55"`** (was `None`): the bot now covers Jay-read 2 shorts at the 15:55 open, as the backtest does. Set it back to `None` to close them yourself after the 15:50 alert.
- **Settings added to `core\settings.py`:** `JAY_READ_2 = True`, `JR2_ALERT_ONLY = False`, `JR_V12_DEFAULT_MODE = "off"`.
- **Version:** `APP_VERSION` is now 3.13.0.

**Backtests**
- **Backtest tab:**
  - New runs: **Jay-read 2 short** and **Momentum long + Jay-read 2 (live bot)**.
  - The old runs are renamed **Jay-read short v1.2** and **Momentum long + Jay-read v1.2**.
  - Saved results reset once (the shared backtester changed), so the first run of each strategy is a full run.
- **Bulk runner:** `python lh_combined_bulk_runner.py --short jr2 --squeeze off` runs Jay-read 2 with the momentum long.
- **Shared backtester:** `lh_combined_backtester.py` gained `SHORT_STRATEGY = "jay_read_2"`.

**Not changed:** `jay_read_short.py` (v1.2), `lh_long_premarket.py`, `max_squeeze_short.py` (its ShortBook is reused as it is).

## Tests (all passed)

| Test | Result |
|---|---|
| Equivalence, Apr–Oct (883 ticker-days in the main vault) | research 93 = backtest-mode class 93 = live order flow through the ShortBook 93. Same ticker, day, entry minute, entry price, exit and reason |
| Equivalence, Jan–Oct (+214 of the 300 Jan–Mar days, from an older vault copy) | **gappers 88 trades, 68% win, PF 2.71, $96,984; spikers 20 trades, 70% win, PF 1.72, $16,903**. All 108 identical in all three paths |
| Backtest tab, Jay-read 2 (Apr–Oct) | the same 93 trades as the research (entries, exits, reasons) |
| Combined with the momentum long, Jan–Oct (1,097 days) | **384 trades, 55.7% win, flat PF 2.57**. The ~21 missing to ~405 are longs on the 86 Jan–Mar days not in that copy |
| Combined, Apr–Oct (your main vault) | 322 trades (229 long, 93 short), 56.2% win, flat PF 2.75 |
| Regression: Momentum long + Jay-read v1.2 (Apr–Oct) | identical to your 10-31 run: 425 trades, the same entries and returns |
| `tests\test_safety_313.py` | 17/17: live lock, LIVE account blocked, environment variable can't unlock, no broker code in the strategy files, defaults, one short per stock, no secrets in `.env.example` |

Run the full Jan–Oct equivalence on your PC, with the bot open or closed (it only reads the vault):
`python backtest\jay_read_2\jay_read_2_equivalence_test.py "C:\Users\jayku\OneDrive\Desktop\test vs code\test vs code\ib_data_vault\market_data_vault.db"`
It reads the moved Jan–Mar days from `market_data_vault_ARCHIVE.db`. Expected: 88 gapper + 20 spiker trades, PASS.

## Security
- `.env.example` now ships with empty credentials.
- The old copy held real-looking TradeZero keys, an account ID and the Discord webhook. If that file was ever pushed or shared, rotate the TradeZero API key and recreate the Discord webhook.

---

# 3.13.1 (2026-11-01)

- **Dashboard** (formerly the Backtest tab):
  - Shows strategy names only: no file names, no "Your strategies" header, no descriptions.
  - The vault location moved to Settings → Keys and Discord → Data vault.
- **Settings:** the subtitles and descriptions are gone, and no file names are shown.
- **Delete a run:** each run in Past runs has a **Delete** button. Click it twice and that run's folder is removed from the bot folder. A run that is still going can't be deleted.
- **$0.50 short filter in the backtests,** matching the live short scanner (`SHORT_SCAN_MIN_PRICE = 0.50`): a short signal under $0.50 is skipped.
  - Applies to `lh_combined_backtester.py` (`MIN_SHORT_PRICE`), which the Dashboard and the bulk runner use, and to `jay_read_short_backtest.py`.
  - The live strategy files are unchanged.
  - Effect on the 1,097-day test: Jay-read 2 unchanged (108); Jay-read v1.2 236 → 234.

---

# New look (2026-11-03)

Styling only: no trading, order, strategy or backtest code changed.
- Deep slate theme with an indigo accent; emerald / rose for wins and losses; glass panels on every screen.
- Settings menu with icons; switch rows with the switch on the right; trading mode buttons green (Trading), amber (Alert only), grey (Off).
- Connection pill glows green when connected; positions panel tabs; journal calendar tinted green / red.
- Saved colors that were an earlier default switch to the new look; Colors -> Reset to default restores it.
