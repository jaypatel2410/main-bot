# Backtests (inside the main bot)

The main bot's **Backtest tab** (flask icon in the left rail, or F8) runs every strategy here on the IB data vault
(`market_data_vault.db`). The run is a separate process, so live trading is not slowed. Nothing here connects to IB
Gateway or TradeZero.

| Folder | Strategy | Code it runs (main bot folder) |
|---|---|---|
| `jay_read_2/` | **Jay-read 2 short (3.13.0, live)** | `jay_read_2_short.py` through `_shared/lh_combined_backtester.py` (SHORT_STRATEGY = "jay_read_2"); `jay_read_2_research.py` = the research engine; `jay_read_2_equivalence_test.py` checks both make the same trades |
| `combined_jr2_long/` | Momentum long + Jay-read 2 (the live bot) | the same, long on |
| `jay_read_short/` | Jay-read short v1.2 (off live) | `jay_read_short.py` (+ `jay_read_short_backtest.py`), run through `_shared/lh_combined_backtester.py` (shorts on, long off) |
| `max_squeeze_short/` | Max squeeze short | `max_squeeze_short.py` (same run as live: one position per stock), its trades only |
| `premarket_long/` | Premarket long | `lh_long_premarket.py` (live); the backtest uses the long engine in `_shared/lh_combined_backtester.py` (shorts off) |
| `_shared/` | shared by all | `lh_combined_backtester.py`, `lh_combined_bulk_runner.py`, `lh_vault_bars.py` |
| `settings.json` | the vault path and the last run settings | |

The strategy files live ONLY here: the live bot (main.py) loads them from these folders too, and a backtest uses the
SAME files the bot trades with (no copies), so the test and the live bot cannot
drift apart.

## What each strategy folder holds

- `runs/<YYYYmmdd-HHMMSS>/` - one folder per run: `job.json` (settings + the day list), `progress.json`,
  `trades.csv`, `summary.json`.
- `notes.json` - your verdict and notes per ticker-day (kept across runs; shown on every run of that day).

## Adding your own strategy

Make a folder `backtest/<name>/` with a `strategy.py`:

```python
NAME = "My gap fade"          # shown in the Backtest tab
SIDE = "Short"                # or "Long"

def run_day(ticker, day, df1, prior_close, cfg):
    """df1 = that day's 1-minute bars (columns time [ET], open, high, low, close, volume), prior_close = float,
    cfg = the run settings (cfg["locate"], cfg["slip"] in %). Return a list of trades:"""
    return [{"entry": 5.10, "exit": 4.20, "stop": 5.60, "entry_hms": "10:31:00", "exit_hms": "15:55:00",
             "ret_pct": 14.2,          # % return after YOUR costs (locate + slippage)
             "result": "EOD", "setup": "open fade", "note": "why"}]
```

Restart the Backtest tab (open it again) and the strategy shows under "Your strategies".
