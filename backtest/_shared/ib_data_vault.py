"""
IB data vault  -  v1.2 (2026-10-20)

Pulls the bars our backtests need from IB Gateway for every ticker + date in a list, and keeps them in ONE local
file, so a backtest never has to download the same day twice and old days stay available after IB stops serving
them (delistings, reverse splits, IB's look-back limits).

What is stored per ticker-day (the same requests as lh_combined_backtester.py):
  - 1-minute TRADES bars, 04:00-20:00 ET (useRTH=False)            -> short side, VWAP, everything intraday
  - daily TRADES bars, 15 days back (useRTH=True)                    -> prior close (+ prior-day volume)
  - 10-second TRADES bars, 04:00-09:00 ET (useRTH=False)            -> premarket long (optional, --no-10s)
    ONLY for days inside the last 6 months + 10 days (counted back from the day you run it). IB does not serve
    10-second bars older than about 6 months, so older days are not requested: they get their 1-minute bars
    (the short side) and are marked "too_old" for 10-second. The window moves with the run date.

  - v1.2: long DAILY history per ticker (--daily-history 2Y): daily TRADES bars, regular hours, ending on the
    ticker's latest list date and reaching N years before its earliest list date. Needed for "resistance holding"
    (earlier runs' highs and their volume). Stored in its own table (daily_hist) with one consistent split basis per
    ticker; a ticker is only re-requested when the list asks for dates outside what is stored.

Files (next to this script unless --db / --index say otherwise):
  market_data_vault.db          SQLite: all bars + the day index. The single source of truth.
  market_data_vault_index.xlsx  readable record: one row per ticker-day with status, bar counts, prior close,
                                fetch time. Rewritten at the end of every run (open it any time).

Re-running is incremental: a ticker-day already in the vault is NOT fetched again. Only new ticker-days, and the
parts that are missing (e.g. the 10-second bars of a day that only has 1-minute bars), are requested. Days where IB
returned nothing are recorded as "no_data" and skipped next time (use --retry to try them again).

Usage
  pip install ib_async pandas openpyxl          (ib_insync also works)

  # fetch everything in the list that is not in the vault yet (IB Gateway live 4001 / paper 4002)
  python ib_data_vault.py --list my_gappers.xlsx

  # load the CSV caches you already have (no IB needed): <TICKER>_<YYYY-MM-DD>_bars.csv and _10s.csv
  python ib_data_vault.py --import-csv data/bars

  # write CSVs in the backtesters' cache format (for --bars / cache_dirs), only for the days in a list (or all)
  python ib_data_vault.py --export bars_cache --list my_gappers.xlsx
  python ib_data_vault.py --export bars_cache

  # daily history for resistance tests (one request per ticker, only the 1-day bars; no 1-min / 10-s fetching)
  python ib_data_vault.py --list my_gappers.xlsx --daily-history 2Y
  python ib_data_vault.py --export-daily daily_history.csv [--list my_gappers.xlsx]

  # what is in the vault
  python ib_data_vault.py --status

In Python (any backtester):
  from ib_data_vault import Vault
  v = Vault("market_data_vault.db")
  df1, prior_close, df10 = v.load_day("XRPN", "2026-10-02")    # tz-aware ET times; df10 None if not stored
  v.has_day("XRPN", "2026-10-02")

List file: .xlsx / .csv with a ticker column (Ticker / Symbol) and a date column (Date / Day). Extra columns are
ignored. Read-only connection to IB: this script never places orders.
"""
import argparse
import os
import sqlite3
import sys
import time as _time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- settings
IB_HOST = "127.0.0.1"
IB_PORT = 4001                 # IB Gateway live = 4001, paper = 4002
IB_CLIENT_ID = 81              # any id not used by the bot (the bot / backtester use their own)
EXCHANGE = "SMART"
CURRENCY = "USD"
FETCH_10S = True               # premarket 10-second bars for the long side
TEN_SEC_END = "09:00"          # 10-second bars 04:00 -> this time
TEN_SEC_MONTHS = 6             # 10-second bars only for days within this many months before today ...
TEN_SEC_EXTRA_DAYS = 10        # ... plus this many days (older days: 1-minute bars only)
IB_SMALL_BAR_GAP_SEC = 10.5    # IB pacing for bars <= 30 s: 60 requests / 10 min -> one every 10.5 s
IB_REQUEST_GAP_SEC = 0.5       # small pause between the other requests
REQUEST_TIMEOUT_SEC = 60
ET = "America/New_York"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "market_data_vault.db")
DEFAULT_INDEX = os.path.join(HERE, "market_data_vault_index.xlsx")

SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    ticker TEXT NOT NULL, day TEXT NOT NULL,
    status_1m TEXT, status_10s TEXT,          -- ok / no_data / error / no_contract / (NULL = not tried)
    prior_close REAL, prior_volume REAL,
    n_1m INTEGER DEFAULT 0, n_10s INTEGER DEFAULT 0,
    first_bar TEXT, last_bar TEXT,
    day_high REAL, day_volume REAL,
    source TEXT, fetched_at TEXT, note TEXT,
    PRIMARY KEY (ticker, day));
CREATE TABLE IF NOT EXISTS bars_1m (
    ticker TEXT NOT NULL, day TEXT NOT NULL, t TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, day, t));
CREATE TABLE IF NOT EXISTS bars_10s (
    ticker TEXT NOT NULL, day TEXT NOT NULL, t TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, day, t));
CREATE TABLE IF NOT EXISTS daily (
    ticker TEXT NOT NULL, day TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, day));
CREATE TABLE IF NOT EXISTS daily_hist (
    ticker TEXT NOT NULL, day TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, day));
CREATE TABLE IF NOT EXISTS daily_hist_cover (
    ticker TEXT PRIMARY KEY, status TEXT,           -- ok / no_data / no_contract / error
    want_start TEXT, want_end TEXT,                 -- the span asked for
    first_day TEXT, last_day TEXT, n INTEGER,       -- what IB returned
    fetched_at TEXT, note TEXT);
"""


# ----------------------------------------------------------------------------- the vault (SQLite)
class Vault:
    def __init__(self, path=DEFAULT_DB):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.commit()

    def _commit(self, day=None, hist=None):
        """Commit locally, then (3.14) push what changed to Turso. The local file is a replica; if the push fails the
        data is still here and `python turso_vault.py upload` sends whatever Turso is missing."""
        self.db.commit()
        try:
            for p in (os.path.join(HERE, "..", "main bot version 3.12", "core", "data"), os.path.join(HERE, "..", "core", "data")):
                if os.path.isdir(p) and p not in sys.path:
                    sys.path.append(p)
            import turso_vault as TV
            if day is not None:
                TV.push_day(self.db, day[0], str(day[1]))
            if hist is not None:
                TV.push_hist(self.db, hist)
        except ImportError:
            pass
        except Exception as exc:
            print(f"  (Turso: not pushed - {exc})")

    # --- what is there
    def day_row(self, ticker, day):
        cur = self.db.execute("SELECT * FROM days WHERE ticker=? AND day=?", (ticker, str(day)))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    def has_day(self, ticker, day, need_10s=False):
        r = self.day_row(ticker, day)
        if not r or r["status_1m"] != "ok":
            return False
        return (not need_10s) or r["status_10s"] in ("ok", "no_data", "too_old")

    def index(self):
        return pd.read_sql_query("SELECT * FROM days ORDER BY day, ticker", self.db)

    # --- write
    def _put_bars(self, table, ticker, day, df):
        self.db.execute(f"DELETE FROM {table} WHERE ticker=? AND day=?", (ticker, str(day)))
        if df is None or df.empty:
            return
        rows = [(ticker, str(day), ts.strftime("%Y-%m-%d %H:%M:%S"), float(o), float(h), float(l), float(c), float(v))
                for ts, o, h, l, c, v in zip(df["time"], df["open"], df["high"], df["low"], df["close"], df["volume"])]
        self.db.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?)", rows)

    def _upsert_day(self, ticker, day, **kw):
        r = self.day_row(ticker, day)
        if r is None:
            self.db.execute("INSERT INTO days (ticker, day) VALUES (?, ?)", (ticker, str(day)))
        if kw:
            sets = ", ".join(f"{k}=?" for k in kw)
            self.db.execute(f"UPDATE days SET {sets} WHERE ticker=? AND day=?", (*kw.values(), ticker, str(day)))

    def save_1m(self, ticker, day, df, prior_close, daily=None, source="IB", note=""):
        day = str(day)
        self._put_bars("bars_1m", ticker, day, df)
        prior_volume = None
        if daily is not None and not daily.empty:
            for r in daily.itertuples():
                self.db.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?)",
                                (ticker, r.day, r.open, r.high, r.low, r.close, r.volume))
            before = daily[daily["day"] < day]
            if not before.empty:
                prior_volume = float(before["volume"].iloc[-1])
        ok = df is not None and not df.empty
        self._upsert_day(ticker, day, status_1m="ok" if ok else "no_data", prior_close=prior_close,
                         prior_volume=prior_volume, n_1m=len(df) if ok else 0,
                         first_bar=df["time"].iloc[0].strftime("%H:%M") if ok else None,
                         last_bar=df["time"].iloc[-1].strftime("%H:%M") if ok else None,
                         day_high=float(df["high"].max()) if ok else None,
                         day_volume=float(df["volume"].sum()) if ok else None,
                         source=source, fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note=note)
        self._commit(day=(ticker, day))

    def save_10s(self, ticker, day, df, note=""):
        ok = df is not None and not df.empty
        self._put_bars("bars_10s", ticker, day, df if ok else None)
        self._upsert_day(ticker, day, status_10s="ok" if ok else "no_data", n_10s=len(df) if ok else 0,
                         note=note or None)
        self._commit(day=(ticker, day))

    def mark_10s_old(self, ticker, day):
        """No 10-second request: the day is older than IB's 10-second history."""
        r = self.day_row(ticker, day) or {}
        if r.get("status_10s") not in ("ok", "no_data"):
            self._upsert_day(ticker, day, status_10s="too_old", n_10s=0)
            self._commit(day=(ticker, day))

    # --- daily history (v1.2)
    def daily_cover(self, ticker):
        cur = self.db.execute("SELECT * FROM daily_hist_cover WHERE ticker=?", (ticker,))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None

    def save_daily_hist(self, ticker, df, want_start, want_end, status="ok", note=""):
        """Replace the ticker's whole daily history (one fetch = one consistent split-adjustment basis)."""
        self.db.execute("DELETE FROM daily_hist WHERE ticker=?", (ticker,))
        ok = df is not None and not df.empty
        if ok:
            self.db.executemany("INSERT OR REPLACE INTO daily_hist VALUES (?,?,?,?,?,?,?)",
                                [(ticker, r.day, float(r.open), float(r.high), float(r.low), float(r.close),
                                  float(r.volume)) for r in df.itertuples()])
        self.db.execute("INSERT OR REPLACE INTO daily_hist_cover VALUES (?,?,?,?,?,?,?,?,?)",
                        (ticker, status if ok or status != "ok" else "no_data", str(want_start), str(want_end),
                         df["day"].min() if ok else None, df["day"].max() if ok else None, len(df) if ok else 0,
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note[:200]))
        self._commit(hist=ticker)

    def load_daily(self, ticker, start=None, end=None):
        """Daily history of a ticker (day as YYYY-MM-DD strings), optionally limited to [start, end]."""
        q, prm = "SELECT day, open, high, low, close, volume FROM daily_hist WHERE ticker=?", [ticker]
        if start:
            q += " AND day>=?"; prm.append(str(start))
        if end:
            q += " AND day<=?"; prm.append(str(end))
        return pd.read_sql_query(q + " ORDER BY day", self.db, params=prm)

    def export_daily(self, path, tickers=None):
        df = pd.read_sql_query("SELECT * FROM daily_hist ORDER BY ticker, day", self.db)
        if tickers is not None:
            df = df[df.ticker.isin(set(tickers))]
        df.rename(columns={"day": "date"}).to_csv(path, index=False)
        return df.ticker.nunique(), len(df)

    def mark(self, ticker, day, part, status, note):
        self._upsert_day(ticker, day, **{f"status_{part}": status}, note=note[:200],
                         fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._commit(day=(ticker, day))

    # --- read
    def _bars(self, table, ticker, day):
        df = pd.read_sql_query(f"SELECT t AS time, open, high, low, close, volume FROM {table} "
                               f"WHERE ticker=? AND day=? ORDER BY t", self.db, params=(ticker, str(day)))
        if df.empty:
            return None
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(ET)
        return df

    def load_day(self, ticker, day):
        """(1-minute bars, prior close, 10-second bars or None). Times are tz-aware ET."""
        r = self.day_row(ticker, day) or {}
        return self._bars("bars_1m", ticker, day), r.get("prior_close"), self._bars("bars_10s", ticker, day)

    def export_csv(self, out_dir, pairs=None):
        """Write <TICKER>_<DAY>_bars.csv (+ _10s.csv) - the format of the kit and lh_combined_backtester.py."""
        os.makedirs(out_dir, exist_ok=True)
        idx = self.index()
        idx = idx[idx["status_1m"] == "ok"]
        if pairs is not None:
            want = set(pairs)
            idx = idx[[(t, d) in want for t, d in zip(idx["ticker"], idx["day"])]]
        n = 0
        for r in idx.itertuples():
            df1, pc, df10 = self.load_day(r.ticker, r.day)
            out = df1.copy()
            out["time"] = out["time"].dt.tz_localize(None)
            if pc is not None:
                out["prior_close"] = pc
            out.to_csv(os.path.join(out_dir, f"{r.ticker}_{r.day}_bars.csv"), index=False)
            if df10 is not None:
                o10 = df10.copy()
                o10["time"] = o10["time"].dt.tz_localize(None)
                o10.to_csv(os.path.join(out_dir, f"{r.ticker}_{r.day}_10s.csv"), index=False)
            n += 1
        return n

    def write_index_xlsx(self, path):
        idx = self.index()
        cols = ["ticker", "day", "status_1m", "n_1m", "first_bar", "last_bar", "prior_close", "day_high",
                "day_volume", "prior_volume", "status_10s", "n_10s", "source", "fetched_at", "note"]
        idx = idx[cols].rename(columns={"day": "date"})
        idx["up_%"] = ((idx["day_high"] / idx["prior_close"] - 1) * 100).round(1)
        summary = pd.DataFrame({
            "item": ["ticker-days", "1-min ok", "1-min no data", "1-min errors / no contract", "10-sec ok",
                     "10-sec no data", "10-sec too old (not requested)", "first date", "last date", "vault file", "updated"],
            "value": [len(idx), (idx.status_1m == "ok").sum(), (idx.status_1m == "no_data").sum(),
                      idx.status_1m.isin(["error", "no_contract"]).sum(), (idx.status_10s == "ok").sum(),
                      (idx.status_10s == "no_data").sum(), (idx.status_10s == "too_old").sum(), idx["date"].min() if len(idx) else "",
                      idx["date"].max() if len(idx) else "", os.path.basename(self.path),
                      datetime.now().strftime("%Y-%m-%d %H:%M")]})
        tmp = path + ".tmp.xlsx"
        with pd.ExcelWriter(tmp, engine="openpyxl") as xw:
            summary.to_excel(xw, sheet_name="Summary", index=False)
            idx.to_excel(xw, sheet_name="Index", index=False)
            cov = pd.read_sql_query("SELECT * FROM daily_hist_cover ORDER BY ticker", self.db)
            if len(cov):
                cov.to_excel(xw, sheet_name="Daily history", index=False)
                xw.sheets["Daily history"].freeze_panes = "B2"
                for col, w in zip("ABCDEFGHI", (9, 10, 11, 11, 11, 11, 7, 19, 40)):
                    xw.sheets["Daily history"].column_dimensions[col].width = w
            ws = xw.sheets["Index"]
            ws.freeze_panes = "C2"
            ws.auto_filter.ref = ws.dimensions
            for col, w in zip("ABCDEFGHIJKLMNOP", (9, 11, 10, 7, 9, 9, 11, 10, 14, 14, 10, 7, 9, 19, 40, 8)):
                ws.column_dimensions[col].width = w
            xw.sheets["Summary"].column_dimensions["A"].width = 28
            xw.sheets["Summary"].column_dimensions["B"].width = 26
        try:
            os.replace(tmp, path)
        except PermissionError:          # the index is open in Excel
            alt = path.replace(".xlsx", f"_{datetime.now():%H%M%S}.xlsx")
            os.replace(tmp, alt)
            print(f"  {os.path.basename(path)} is open in Excel - index written to {alt}")
            return alt
        return path


# ----------------------------------------------------------------------------- IB
def _ib_api():
    try:
        from ib_async import IB, Stock, util
    except ImportError:
        try:
            from ib_insync import IB, Stock, util
        except ImportError:
            sys.exit("Install the IB API wrapper first:  pip install ib_async")
    return IB, Stock, util


class IBFetcher:
    """Read-only IB Gateway connection with the backtesters' requests."""

    def __init__(self, host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID):
        IB, self.Stock, self.util = _ib_api()
        self.ib = IB()
        self.ib.RequestTimeout = REQUEST_TIMEOUT_SEC
        self.ib.connect(host, port, clientId=client_id, readonly=True, timeout=20)
        self.contracts = {}
        self.last_small = 0.0
        print(f"Connected to IB Gateway {host}:{port} (read-only)")

    def contract(self, ticker):
        if ticker not in self.contracts:
            q = [c for c in (self.ib.qualifyContracts(self.Stock(ticker, EXCHANGE, CURRENCY)) or []) if c]
            self.contracts[ticker] = q[0] if q else None
        return self.contracts[ticker]

    def _df(self, bars):
        df = self.util.df(bars)
        df["time"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(ET)
        return df[["time", "open", "high", "low", "close", "volume"]]

    def _req(self, contract, end, dur, size, rth, fmt=2):
        _time.sleep(IB_REQUEST_GAP_SEC)
        return self.ib.reqHistoricalData(contract, endDateTime=end, durationStr=dur, barSizeSetting=size,
                                         whatToShow="TRADES", useRTH=rth, formatDate=fmt)

    def bars_1m(self, contract, day):
        bars = self._req(contract, f"{day:%Y%m%d} 20:00:00 US/Eastern", "1 D", "1 min", False)
        return clean(self._df(bars), day) if bars else None

    def daily(self, contract, day):
        bars = self._req(contract, f"{day:%Y%m%d} 23:59:00 US/Eastern", "15 D", "1 day", True, fmt=1)
        rows = []
        for b in bars or []:
            bd = b.date.date() if isinstance(b.date, datetime) else b.date
            if isinstance(bd, str):
                bd = datetime.strptime(bd[:8], "%Y%m%d").date()
            rows.append({"day": str(bd), "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                         "volume": b.volume})
        return pd.DataFrame(rows)

    def daily_hist(self, contract, end_day, years):
        """Daily TRADES bars, regular hours, `years` years ending on end_day."""
        bars = self._req(contract, f"{end_day:%Y%m%d} 23:59:00 US/Eastern", f"{years} Y", "1 day", True, fmt=1)
        rows = []
        for b in bars or []:
            bd = b.date.date() if isinstance(b.date, datetime) else b.date
            if isinstance(bd, str):
                bd = datetime.strptime(bd[:8], "%Y%m%d").date()
            rows.append({"day": str(bd), "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                         "volume": b.volume})
        return pd.DataFrame(rows)

    def bars_10s(self, contract, day):
        frames = []
        for dur, end in (("1 D", TEN_SEC_END), ("14400 S", TEN_SEC_END), ("3600 S", "05:00")):
            if frames and dur != "3600 S":
                continue
            wait = self.last_small + IB_SMALL_BAR_GAP_SEC - _time.time()
            if wait > 0:
                _time.sleep(wait)
            self.last_small = _time.time()
            part = self.ib.reqHistoricalData(contract, endDateTime=f"{day:%Y%m%d} {end}:00 US/Eastern",
                                             durationStr=dur, barSizeSetting="10 secs", whatToShow="TRADES",
                                             useRTH=False, formatDate=2)
            if part:
                frames.append(self._df(part))
                if dur == "1 D":
                    break
        if not frames:
            return None
        df = pd.concat(frames)
        return clean(df, day, before=TEN_SEC_END)

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()


def clean(df, day, before=None):
    """Same cleaning as the backtesters: that ET day only, sorted, no duplicates, numbers only."""
    df = df[df["time"].dt.date == day].copy()
    if before is not None:
        df = df[df["time"].dt.strftime("%H:%M") < before]
    df = df.sort_values("time").drop_duplicates("time")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).clip(lower=0)
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------- list / import
def read_list(path):
    raw = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
    cols = {c.strip().lower(): c for c in raw.columns}
    tc = next((cols[c] for c in ("ticker", "symbol", "tickers", "symbols") if c in cols), None)
    dc = next((cols[c] for c in ("date", "day", "trade date", "trade_date") if c in cols), None)
    if tc is None or dc is None:
        sys.exit(f"{path}: needs a Ticker/Symbol column and a Date/Day column (found {list(raw.columns)})")
    out = []
    for t, d in zip(raw[tc], raw[dc]):
        if pd.isna(t) or pd.isna(d):
            continue
        out.append((str(t).strip().upper(), pd.to_datetime(d).date()))
    return sorted(set(out), key=lambda x: (x[1], x[0]))


def import_csv_dir(vault, folder):
    """Load existing cache CSVs (<TICKER>_<YYYY-MM-DD>_bars.csv, optional _10s.csv) without IB."""
    n1 = n10 = 0
    for name in sorted(os.listdir(folder)):
        if not name.endswith("_bars.csv"):
            continue
        tk, ds = name[:-len("_bars.csv")].rsplit("_", 1)
        if vault.has_day(tk, ds):
            continue
        day = datetime.strptime(ds, "%Y-%m-%d").date()
        df1, pc = read_cache_csv(os.path.join(folder, name))
        vault.save_1m(tk, ds, clean(df1, day), pc, source="csv import")
        n1 += 1
        p10 = os.path.join(folder, f"{tk}_{ds}_10s.csv")
        if os.path.exists(p10):
            df10, _ = read_cache_csv(p10)
            vault.save_10s(tk, ds, clean(df10, day, before=TEN_SEC_END))
            n10 += 1
    return n1, n10


def read_cache_csv(path):
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]
    ts = pd.to_datetime(raw["time"])
    raw["time"] = ts.dt.tz_localize(ET) if ts.dt.tz is None else ts.dt.tz_convert(ET)
    pc = float(raw["prior_close"].dropna().iloc[0]) if "prior_close" in raw and raw["prior_close"].notna().any() else None
    return raw[["time", "open", "high", "low", "close", "volume"]], pc


# ----------------------------------------------------------------------------- the fetch run
def ten_sec_cutoff(today=None):
    """Oldest day that still gets 10-second bars: today - TEN_SEC_MONTHS months - TEN_SEC_EXTRA_DAYS days."""
    today = today or date.today()
    return (pd.Timestamp(today) - pd.DateOffset(months=TEN_SEC_MONTHS) - pd.Timedelta(days=TEN_SEC_EXTRA_DAYS)).date()


def fetch_list(vault, jobs, ib_factory, need_10s=True, retry=False, today=None):
    """Fetch what is missing for each (ticker, day). Returns counts."""
    cutoff = ten_sec_cutoff(today)
    if need_10s:
        print(f"10-second bars: only days from {cutoff} on ({TEN_SEC_MONTHS} months + {TEN_SEC_EXTRA_DAYS} days "
              f"back); older days get 1-minute bars only")
    todo = []
    old = 0
    for tk, day in jobs:
        r = vault.day_row(tk, day) or {}
        s1, s10 = r.get("status_1m"), r.get("status_10s")
        want1 = s1 != "ok" and (s1 is None or retry or s1 == "error")
        want10 = need_10s and (s1 == "ok" or want1) and s10 not in ("ok", "too_old") and (s10 is None or retry or s10 == "error")
        if want10 and day < cutoff:
            want10 = False
            old += 1
            if s1 == "ok":
                vault.mark_10s_old(tk, day)          # 1-minute already stored: nothing to request
        if day.weekday() >= 5:
            if s1 is None:
                vault.mark(tk, day, "1m", "no_data", "weekend")
            continue
        if want1 or want10:
            todo.append((tk, day, want1, want10))
    have = len(jobs) - len(todo)
    print(f"{len(jobs)} ticker-days in the list: {have} already in the vault (or weekend), {len(todo)} to fetch"
          + (f"; {old} older than {cutoff}: 1-minute only" if old else ""))
    if not todo:
        return {"listed": len(jobs), "fetched": 0, "skipped": have, "failed": 0}
    ib = ib_factory()
    done = failed = 0
    t0 = _time.time()
    try:
        for k, (tk, day, want1, want10) in enumerate(todo, 1):
            tag = f"[{k}/{len(todo)}] {tk} {day}"
            phase = "1m" if want1 else "10s"
            try:
                c = ib.contract(tk)
                if c is None:
                    vault.mark(tk, day, "1m", "no_contract", "IB could not qualify the symbol (delisted / renamed?)")
                    print(f"{tag}: no contract")
                    failed += 1
                    continue
                if want1:
                    df1 = ib.bars_1m(c, day)
                    daily = ib.daily(c, day)
                    before = daily[daily["day"] < str(day)] if not daily.empty else daily
                    pc = float(before["close"].iloc[-1]) if not before.empty else None
                    vault.save_1m(tk, day, df1, pc, daily=daily, source="IB",
                                  note="" if df1 is not None and not df1.empty else "IB returned no 1-minute bars")
                    ok1 = df1 is not None and not df1.empty
                else:
                    ok1 = True
                msg = f"1m {'ok' if ok1 else 'no data'}" if want1 else "1m in vault"
                if need_10s and not want10 and ok1 and day < cutoff:
                    vault.mark_10s_old(tk, day)
                if want10 and ok1:
                    phase = "10s"
                    df10 = ib.bars_10s(c, day)
                    vault.save_10s(tk, day, df10)
                    msg += f", 10s {len(df10) if df10 is not None else 'no data'}"
                done += 1
                eta = (_time.time() - t0) / k * (len(todo) - k)
                print(f"{tag}: {msg}   (eta {eta / 60:.0f} min)")
            except KeyboardInterrupt:
                print("\nStopped by you. Everything fetched so far is saved; run again to continue.")
                raise
            except Exception as exc:  # noqa: BLE001
                failed += 1
                vault.mark(tk, day, phase, "error", str(exc))
                print(f"{tag}: error {str(exc)[:100]}")
    finally:
        ib.disconnect()
    return {"listed": len(jobs), "fetched": done, "skipped": have, "failed": failed}


def parse_years(text):
    t = str(text).strip().upper().replace(" ", "")
    if t.endswith("Y"):
        t = t[:-1]
    n = int(t)
    if n < 1 or n > 20:
        raise ValueError("--daily-history takes 1Y to 20Y")
    return n


def fetch_daily_history(vault, jobs, ib_factory, years=2, retry=False):
    """One request per ticker: daily bars from (earliest list date - years) to the latest list date.
    Skipped when the stored history already covers that span (or IB had nothing, unless retry)."""
    span = {}
    for tk, day in jobs:
        a, b = span.get(tk, (day, day))
        span[tk] = (min(a, day), max(b, day))
    todo = []
    for tk, (a, b) in sorted(span.items()):
        start = (pd.Timestamp(a) - pd.DateOffset(years=years)).date()
        cov = vault.daily_cover(tk)
        if cov and cov["status"] == "ok" and cov["want_start"] <= str(start) and cov["want_end"] >= str(b):
            continue
        if cov and cov["status"] in ("no_data", "no_contract") and not retry and cov["want_start"] <= str(start) \
                and cov["want_end"] >= str(b):
            continue
        if cov and cov["status"] == "ok":                    # widen to what is stored + what is asked
            start = min(start, date.fromisoformat(cov["want_start"]))
            b = max(b, date.fromisoformat(cov["want_end"]))
        todo.append((tk, start, b))
    print(f"daily history ({years}Y before each ticker's first list date): {len(span)} tickers, "
          f"{len(span) - len(todo)} already covered, {len(todo)} to fetch")
    if not todo:
        return {"tickers": len(span), "fetched": 0, "failed": 0}
    ib = ib_factory()
    done = failed = 0
    try:
        for k, (tk, start, end) in enumerate(todo, 1):
            yrs = max(1, int(np.ceil((end - start).days / 365.25)))
            try:
                c = ib.contract(tk)
                if c is None:
                    vault.save_daily_hist(tk, None, start, end, status="no_contract",
                                          note="IB could not qualify the symbol (delisted / renamed?)")
                    failed += 1
                    print(f"[{k}/{len(todo)}] {tk}: no contract")
                    continue
                df = ib.daily_hist(c, end, yrs)
                if df is not None and not df.empty:
                    df = df[(df["day"] >= str(start)) & (df["day"] <= str(end))]
                vault.save_daily_hist(tk, df, start, end, status="ok",
                                      note="" if df is not None and not df.empty else "IB returned no daily bars")
                done += 1
                print(f"[{k}/{len(todo)}] {tk}: {0 if df is None else len(df)} daily bars {start} -> {end}")
            except KeyboardInterrupt:
                print("\nStopped by you. Everything fetched so far is saved; run again to continue.")
                raise
            except Exception as exc:  # noqa: BLE001
                failed += 1
                vault.save_daily_hist(tk, None, start, end, status="error", note=str(exc))
                print(f"[{k}/{len(todo)}] {tk}: error {str(exc)[:100]}")
    finally:
        ib.disconnect()
    return {"tickers": len(span), "fetched": done, "failed": failed}


def main():
    ap = argparse.ArgumentParser(description="Fetch IB bars once, keep them forever (one SQLite file + an Excel index).")
    ap.add_argument("--list", help="ticker/date list (.xlsx/.csv)")
    ap.add_argument("--db", default=DEFAULT_DB, help="vault file (default market_data_vault.db next to this script)")
    ap.add_argument("--index", default=DEFAULT_INDEX, help="Excel index file to write")
    ap.add_argument("--no-10s", action="store_true", help="skip the premarket 10-second bars")
    ap.add_argument("--retry", action="store_true", help="also re-try days stored as no_data / no_contract")
    ap.add_argument("--from", dest="date_from", help="only list days on/after YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", help="only list days on/before YYYY-MM-DD")
    ap.add_argument("--import-csv", help="folder of existing <TICKER>_<DATE>_bars.csv files to load (no IB)")
    ap.add_argument("--export", help="write cache CSVs to this folder (the list's days, or all days)")
    ap.add_argument("--status", action="store_true", help="print what is in the vault")
    ap.add_argument("--daily-history", metavar="NY", help="fetch N years of daily bars per ticker in --list (e.g. 2Y); "
                    "only the daily history is fetched in this run")
    ap.add_argument("--export-daily", metavar="CSV", help="write the stored daily history to one CSV (the list's tickers, or all)")
    ap.add_argument("--port", type=int, default=IB_PORT)
    ap.add_argument("--client-id", type=int, default=IB_CLIENT_ID)
    a = ap.parse_args()

    vault = Vault(a.db)
    print(f"vault file: {os.path.abspath(a.db)}")
    jobs = read_list(a.list) if a.list else None
    if jobs is not None:
        if a.date_from:
            jobs = [j for j in jobs if j[1] >= date.fromisoformat(a.date_from)]
        if a.date_to:
            jobs = [j for j in jobs if j[1] <= date.fromisoformat(a.date_to)]

    if a.import_csv:
        n1, n10 = import_csv_dir(vault, a.import_csv)
        print(f"imported {n1} ticker-days of 1-minute bars ({n10} with 10-second bars) from {a.import_csv}")
    if a.daily_history:
        if jobs is None:
            sys.exit("--daily-history needs --list")
        res = fetch_daily_history(vault, jobs, lambda: IBFetcher(port=a.port, client_id=a.client_id),
                                  years=parse_years(a.daily_history), retry=a.retry)
        print(f"done: {res['fetched']} tickers fetched, {res['failed']} failed")
    if a.export_daily:
        nt, nr = vault.export_daily(a.export_daily, [t for t, _ in jobs] if jobs is not None else None)
        print(f"exported daily history: {nt} tickers, {nr} rows -> {a.export_daily}")
    if jobs is not None and not a.export and not a.daily_history and not a.export_daily:
        res = fetch_list(vault, jobs, lambda: IBFetcher(port=a.port, client_id=a.client_id),
                         need_10s=FETCH_10S and not a.no_10s, retry=a.retry)
        print(f"done: {res['fetched']} fetched, {res['skipped']} already in the vault, {res['failed']} failed")
    if a.export:
        pairs = [(t, str(d)) for t, d in jobs] if jobs is not None else None
        n = vault.export_csv(a.export, pairs)
        print(f"exported {n} ticker-days to {a.export}")
    idx = vault.index()
    if a.status or jobs is not None or a.import_csv:
        ndh = vault.db.execute("SELECT COUNT(*), COUNT(DISTINCT ticker) FROM daily_hist").fetchone()
        print(f"vault: {len(idx)} ticker-days, 1-min ok {(idx.status_1m == 'ok').sum()}, "
              f"10-sec ok {(idx.status_10s == 'ok').sum()}, daily history {ndh[1]} tickers / {ndh[0]} bars, "
              f"file {os.path.getsize(a.db) / 1e6:.1f} MB")
    if jobs is not None or a.import_csv or a.status:
        print("index:", vault.write_index_xlsx(a.index))


if __name__ == "__main__":
    main()