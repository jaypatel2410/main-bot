#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LH VAULT BARS  -  how every LH backtester reads its bars from the IB data vault           (3.8.1, 2026-10-17)
====================================================================================================================
The backtesters never download anything. All bars come from market_data_vault.db, the SQLite file of
ib_data_vault.py (your vault folder). Fetching new days is only the vault's job:

    python ib_data_vault.py --list <list.xlsx>            (IB Gateway on; adds what is missing)

A ticker-day that is not in the vault - or is stored there as no_data / no_contract / error - is skipped by the
backtest and written to missing_from_vault.xlsx (Ticker, Date, Vault status) in the backtest's output folder. Feed that
file straight to the vault:  python ib_data_vault.py --list missing_from_vault.xlsx   (add --retry for no_data /
no_contract days), then run the backtest again.

Used by lh_combined_backtester.py, lh_combined_bulk_runner.py, lh_short_backtester.py, lh_short_bulk_runner.py,
lh_day2_short_backtester.py and jay_read_short_backtest.py. Not used by the live bot.

Where things are looked up:
  VAULT_DB          the full path of market_data_vault.db (each backtester's VAULT_DB setting / --vault). A bare file
                    name is looked up next to the backtester, then in the current folder.
  ib_data_vault.py  next to the .db (the vault folder), then next to the backtester, then the Python path.
"""
import importlib.util
import os
import sys

_OPEN = {}                     # vault path -> Vault (one connection per path for the whole run)
BAD_STATUS = ("no_data", "no_contract", "error")


class VaultError(RuntimeError):
    """The vault file or ib_data_vault.py cannot be found / opened."""


def resolve_db(path, near=None):
    """The vault file as an absolute path. A bare name / relative path: next to `near` (a file or folder), then the
    current folder. Never creates a file: a missing vault is an error, not an empty new vault."""
    if not path:
        raise VaultError("VAULT_DB is not set: put the full path of market_data_vault.db at the top of the backtester "
                         "(VAULT_DB = r\"C:\\...\\market_data_vault.db\") or pass --vault")
    p = os.path.expanduser(str(path))
    tries = [p] if os.path.isabs(p) else []
    if not os.path.isabs(p):
        if near:
            base = near if os.path.isdir(near) else os.path.dirname(os.path.abspath(near))
            tries.append(os.path.join(base, p))
        tries.append(os.path.abspath(p))
    for t in tries:
        if os.path.isfile(t):
            return os.path.abspath(t)
    raise VaultError(f"vault file not found: {path} (looked at {', '.join(tries)}). Set VAULT_DB / --vault to the full path "
                     f"of market_data_vault.db (the vault folder of ib_data_vault.py)")


def _vault_class(db_path, near=None):
    mod = sys.modules.get("ib_data_vault")
    if mod is None:
        dirs = [os.path.dirname(db_path)]
        if near:
            dirs.append(near if os.path.isdir(near) else os.path.dirname(os.path.abspath(near)))
        dirs.append(os.path.dirname(os.path.abspath(__file__)))
        for d in dirs:
            f = os.path.join(d, "ib_data_vault.py")
            if os.path.isfile(f):
                spec = importlib.util.spec_from_file_location("ib_data_vault", f)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["ib_data_vault"] = mod
                spec.loader.exec_module(mod)
                break
        else:
            try:
                import ib_data_vault as mod                         # noqa: F401  (on the Python path)
            except ImportError:
                raise VaultError(f"ib_data_vault.py not found next to the vault ({os.path.dirname(db_path)}) or next to the "
                                 f"backtester - keep ib_data_vault.py in the vault folder") from None
    return mod.Vault


def open_vault(path, near=None):
    """The Vault for this path (opened once per run). `near` = the backtester file, for relative paths."""
    db = resolve_db(path, near)
    if db not in _OPEN:
        try:
            _OPEN[db] = _vault_class(db, near)(db)
        except VaultError:
            raise
        except Exception as exc:
            raise VaultError(f"could not open the vault {db}: {exc}") from None
    return _OPEN[db]


def status(vault, ticker, day):
    """'ok', or why the day cannot be used: 'not in vault' / 'no_data' / 'no_contract' / 'error' (+ the vault's note)."""
    r = vault.day_row(ticker, str(day))
    if not r or not r.get("status_1m"):
        return "not in vault"
    s = r["status_1m"]
    if s == "ok":
        return "ok"
    note = (r.get("note") or "").strip()
    return f"{s} ({note[:80]})" if note else s


def load(vault, ticker, day):
    """(df1, prior_close, df10, day_row, "") for a day stored as ok, else (None, None, None, None, why).
    Times are tz-aware ET; df10 is None when the vault has no 10-second bars for the day. The cleaning is the
    backtester's own (each file cleans the bars exactly as before)."""
    why = status(vault, ticker, day)
    if why != "ok":
        return None, None, None, None, why
    df1, pc, df10 = vault.load_day(ticker, str(day))
    if df1 is None or df1.empty:
        return None, None, None, None, "not in vault (no 1-minute bars stored)"
    return df1, pc, df10, vault.day_row(ticker, str(day)) or {}, ""


def ten_sec_note(row):
    """Why a day has no 10-second bars in the vault (the long then uses 10-second candles rebuilt from 1 minute)."""
    s = (row or {}).get("status_10s")
    return {"too_old": "older than the 10-second window", "no_data": "IB had no 10-second bars",
            "error": "10-second fetch failed in the vault"}.get(s, "no 10-second bars in the vault")


class Missing:
    """The ticker-days a backtest could not get from the vault -> missing_from_vault.xlsx (Ticker, Date, Vault status)."""

    def __init__(self):
        self.rows = []
        self._seen = set()

    def add(self, ticker, day, why):
        key = (str(ticker).upper(), str(day))
        if key not in self._seen:
            self._seen.add(key)
            self.rows.append({"Ticker": key[0], "Date": key[1], "Vault status": why})

    def __len__(self):
        return len(self.rows)

    def write(self, folder, name="missing_from_vault.xlsx"):
        """Writes the file (only when something is missing; an old file from an earlier run is removed). Path or None."""
        path = os.path.join(folder or ".", name)
        if not self.rows:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            return None
        import pandas as pd
        os.makedirs(folder or ".", exist_ok=True)
        df = pd.DataFrame(self.rows).sort_values(["Date", "Ticker"])
        try:
            df.to_excel(path, index=False)
        except PermissionError:                                   # open in Excel
            path = path.replace(".xlsx", "_new.xlsx")
            df.to_excel(path, index=False)
        return os.path.abspath(path)

    def print_summary(self, path, limit=15):
        if not self.rows:
            print("missing from vault: none - every ticker-day was in the vault")
            return
        print(f"\nmissing from vault: {len(self.rows)} ticker-day(s) skipped (nothing was downloaded):")
        for r in self.rows[:limit]:
            print(f"  {r['Date']} {r['Ticker']:<6} {r['Vault status']}")
        if len(self.rows) > limit:
            print(f"  ... and {len(self.rows) - limit} more")
        if path:
            retry = any(not r["Vault status"].startswith("not in vault") for r in self.rows)
            print(f"  list saved: {path}\n  add them:   python ib_data_vault.py --list \"{path}\""
                  + ("   (--retry for the no_data / no_contract days)" if retry else ""))
