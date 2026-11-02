#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COMBINED BULK RUNNER 3.10.0 -  premarket long (05:00-09:00) + intraday shorts (Jay-read + max squeeze), ONE account
===============================================================================================================
Runs every ticker-day stored in your IB data vault (default - no Excel file needed), or every Ticker/Date
row of a list file, through the strategies of lh_combined_backtester.py (the same folder) and writes one master
Excel report. The engines are imported from that file and used exactly as they are: the premarket long engine and
the intraday shorts of LH Short Bot 3.9.0 - the Jay-read short v1.2 (jay_read_short.py) + the max squeeze short
(max_squeeze_short.py), one short per stock at a time ("v16" = the parked bounce-zone + vacuum short of 3.6.4).
This file holds no trading logic. Put lh_combined_backtester.py, jay_read_short.py, max_squeeze_short.py and
lh_vault_bars.py in the same folder.

THE ACCOUNT (the same rules as the live bot)
  - one balance for both sides, compounding, STARTING_BALANCE to begin with
  - every long  = 20% of the balance, max $10,000      (premarket: thin candles, keep the losses small)
  - every short = 20% of the balance, max $50,000      (intraday: millions of shares trade)
  - each trade is sized when it is entered, from the balance of the trades already closed, in time order across
    all tickers and both sides (the morning longs are in the balance before the 09:30 shorts)
  The same days are also run as a LONG-ONLY and a SHORT-ONLY account (each from STARTING_BALANCE), so the Summary
  shows what combining the two adds.

THE REPORT
  Summary       settings + combined / long only / short only: trades, win rate, net P&L, final balance, drawdown
  Ticker P&L    one row per list row: long trades + P&L, short trades + P&L, the COMBINED P&L of that ticker-day,
                the account balance at the end of that day, why the long did / did not trade, chart link
  By Ticker     the same per symbol over all its dates
  Trades        every trade in time order: side, setup, entry, shares, position $, exits, result, P&L, balance
  By Month      long / short / combined P&L per month
  Equity        end-of-day balance: combined, long only, short only (+ line chart)
  Days          data source and status of every day (vault status, missing days, errors)

DATA (3.8.1: the IB data vault - this runner never connects to IB Gateway)
  1-minute bars + prior close from market_data_vault.db (VAULT_DB below, else the combined file's; --vault).
  10-second premarket bars for the long: the vault's when it has them (LONG_BARS = "vault"), else 10-second candles
  rebuilt from the 1-minute bars ("rebuilt" in the Long Candles column). LONG_BARS = "rebuild" always rebuilds.
  A list row not in the vault (or stored there as no_data / no_contract / error) is skipped - nothing is downloaded -
  and written to OUTPUT_FOLDER/missing_from_vault.xlsx (Ticker, Date, Vault status). Add them, then run again:
      python ib_data_vault.py --list "<OUTPUT_FOLDER>/missing_from_vault.xlsx"
  BARS_FOLDER: read <TICKER>_<DATE>_bars.csv files from a folder instead of the vault (one-off files).

Requirements:  pip install pandas numpy plotly openpyxl          (no IB API package needed)
Run:           python lh_combined_bulk_runner.py                      (every day in the vault)
               python lh_combined_bulk_runner.py --from 2025-01-01 --to 2025-12-31
               python lh_combined_bulk_runner.py --list my_list.xlsx  (only the rows of a list)
               python lh_combined_bulk_runner.py --short jr2 --squeeze off   (3.13.0: Jay-read 2 + the momentum long)
               [--vault PATH] to point at the vault without editing VAULT_DB
"""

# =============================================================================
# SETTINGS
# =============================================================================
EXCEL_FILE = None                            # None = run EVERY ticker-day stored in the vault (status ok), no Excel needed.
                                             # Or a list file (Ticker + Date columns) to run only those rows (--list)
COMBINED_FILE = "lh_combined_backtester.py"  # the combined strategy file (same folder)
START_DATE = None                            # optional lower limit, e.g. "2025-01-01" (None = from the first day)
END_DATE = None                              # optional upper limit, e.g. "2026-12-31"

VAULT_DB = None                              # None = VAULT_DB of the combined file; else the FULL PATH of the vault,
                                             # e.g. r"C:\...\ib_data_vault\market_data_vault.db"  (--vault)
BARS_FOLDER = None                           # optional: a folder of <TICKER>_<DATE>_bars.csv (+ _10s.csv) files to read
                                             # INSTEAD of the vault (one-off files). None = the vault

OUTPUT_FOLDER = "lh combined bulk backtest"
OUTPUT_EXCEL = "premarket long + short combined backtest.xlsx"
SAVE_CHARTS = "trades"                       # "trades" = days with trades, "all" = every day, "none"

# Account and data overrides - None = the value at the top of the combined file
STARTING_BALANCE = None                      # combined file: 10,000
LONG_ACCOUNT_PCT = None                      # combined file: 20 (% of the balance per long)
LONG_MAX_POSITION_USD = None                 # combined file: 10,000
SHORT_ACCOUNT_PCT = None                     # combined file: 20 (% of the balance per short)
SHORT_MAX_POSITION_USD = None                # combined file: 50,000
LONG_DAILY_LOSS_PCT_OF_POSITION = None       # combined file: 50 (no new longs after a loss of 50% of the long position)
LONG_ENABLED = None                          # combined file: True
SHORT_ENABLED = None                         # combined file: True
LONG_BARS = None                             # combined file: "vault" (the vault's 10-second bars, else rebuilt) - or "rebuild"
SHORT_STRATEGY = None                        # combined file: "jay_read" - or "jay_read_2" (3.13.0, Jay-read 2, --short jr2)
                                             # - or "v16" (the parked bounce-zone + vacuum)
SQUEEZE_ENABLED = None                       # combined file: True = the max squeeze short next to the Jay-read short
MAX_RISK_PER_TRADE_USD = None                # combined file: None = no $ risk cap on Jay-read shorts (the app: None too)

# =============================================================================
# CODE
# =============================================================================
import importlib.util
import os
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd


def load_combined(path):
    for p in (path, os.path.join(os.path.dirname(os.path.abspath(__file__)), path)):
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("lh_combined", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            print(f"Combined strategy file: {os.path.abspath(p)}")
            return mod
    sys.exit(f"Combined strategy file not found: {path}  (set COMBINED_FILE at the top)")


cb = load_combined(COMBINED_FILE)
for _k in ("STARTING_BALANCE", "LONG_ACCOUNT_PCT", "LONG_MAX_POSITION_USD", "SHORT_ACCOUNT_PCT", "SHORT_MAX_POSITION_USD",
           "LONG_DAILY_LOSS_PCT_OF_POSITION",
           "LONG_ENABLED", "SHORT_ENABLED", "LONG_BARS", "SHORT_STRATEGY", "SQUEEZE_ENABLED", "MAX_RISK_PER_TRADE_USD"):
    if globals()[_k] is not None:
        setattr(cb, _k, globals()[_k])
cb.OPEN_BROWSER = False

CHART_DIR = os.path.join(OUTPUT_FOLDER, "charts")
L, S = cb.LONG_SIDE, cb.SHORT_SIDE


# -----------------------------------------------------------------------------
# Input list
# -----------------------------------------------------------------------------
def in_range(d):
    ok = d <= date.today()
    if START_DATE:
        ok &= d >= datetime.strptime(START_DATE, "%Y-%m-%d").date()
    if END_DATE:
        ok &= d <= datetime.strptime(END_DATE, "%Y-%m-%d").date()
    return ok


def vault_targets(vault):
    """Every ticker-day the vault has 1-minute bars for (status ok), in date order - the default (EXCEL_FILE = None)."""
    idx = vault.index()
    total = len(idx)
    ok = idx[idx["status_1m"] == "ok"]
    out = pd.DataFrame({"Ticker": ok["ticker"].astype(str).str.upper().str.strip(),
                        "Date": pd.to_datetime(ok["day"]).dt.date})
    out = out[out["Date"].map(in_range)].drop_duplicates().sort_values(["Date", "Ticker"]).reset_index(drop=True)
    print(f"Vault ticker-days: {total}  |  with 1-minute bars: {len(ok)}  |  in range {START_DATE or 'first day'} to "
          f"{END_DATE or 'today'}: {len(out)}" + (f"  ({out['Date'].min()} to {out['Date'].max()})" if len(out) else ""))
    return out


def read_targets(path):
    raw = pd.read_excel(path) if str(path).lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
    cols = {str(c).strip().lower(): c for c in raw.columns}
    tcol = cols.get("ticker") or cols.get("symbol")
    dcol = cols.get("date")
    if tcol is None or dcol is None:
        sys.exit(f"{path} needs a 'Ticker' column and a 'Date' column. Found: {list(raw.columns)}")
    out = pd.DataFrame({"Ticker": raw[tcol].astype(str).str.upper().str.strip(),
                        "Date": pd.to_datetime(raw[dcol], errors="coerce").dt.date})
    total = len(out)
    bad = out["Date"].isna() | out["Ticker"].isin(["", "NAN", "NONE"])
    out = out[~bad]
    out = out[out["Date"].map(in_range)].drop_duplicates().sort_values(["Date", "Ticker"]).reset_index(drop=True)
    print(f"List rows: {total}  |  invalid: {int(bad.sum())}  |  in range {START_DATE or 'first day'} to "
          f"{END_DATE or 'today'}: {len(out)}")
    return out


# -----------------------------------------------------------------------------
# Report helpers
# -----------------------------------------------------------------------------
def end_of_day_ts(d):
    nxt = datetime(d.year, d.month, d.day, tzinfo=cb.ET_ZONE) + timedelta(days=1)
    return int(nxt.timestamp())


def balances_by_day(curve, days, start):
    """End-of-day balance for each date (the last exit booked before midnight ET)."""
    out, k, bal = {}, 0, start
    curve = sorted(curve)
    for d in sorted(days):
        end = end_of_day_ts(d)
        while k < len(curve) and curve[k][0] < end:
            bal = curve[k][1]
            k += 1
        out[d] = bal
    return out


def side_stats(trades, side):
    tr = [t for t in trades if t["side"] == side]
    return len(tr), sum(1 for t in tr if t.get("pnl", 0) > 0), sum(t.get("pnl", 0.0) for t in tr)


def ticker_rows(runs, eod):
    rows = []
    for r in runs:
        nl, wl, pl = side_stats(r.trades, L)
        ns, ws, ps = side_stats(r.trades, S)
        bt = r.bt
        chart = os.path.join("charts", f"{r.ticker}_{r.day}_combined.html")
        rows.append({"Date": str(r.day), "Ticker": r.ticker, "Prev Close": r.data["pc"],
                     "Gap % at Open": round(bt.gap_pct, 1) if bt is not None and bt.gap_pct == bt.gap_pct else None,
                     "Long Trades": nl, "Long Wins": wl, "Long PnL ($)": round(pl, 2),
                     "Short Trades": ns, "Short Wins": ws, "Short PnL ($)": round(ps, 2),
                     "Combined PnL ($)": round(pl + ps, 2),
                     "Account Balance End of Day ($)": round(eod.get(r.day, 0.0), 2),
                     "Long Note": r.long_note(), "Long Candles": r.data["src10"], "1-min Bars": r.data["src1"],
                     "Chart": chart if os.path.exists(os.path.join(OUTPUT_FOLDER, chart)) else ""})
    return pd.DataFrame(rows)


def by_ticker(tp):
    if not len(tp):
        return tp
    g = tp.groupby("Ticker")
    out = pd.DataFrame({"Days": g.size(), "Long Trades": g["Long Trades"].sum(), "Long PnL ($)": g["Long PnL ($)"].sum(),
                        "Short Trades": g["Short Trades"].sum(), "Short PnL ($)": g["Short PnL ($)"].sum(),
                        "Combined PnL ($)": g["Combined PnL ($)"].sum(), "Best Day ($)": g["Combined PnL ($)"].max(),
                        "Worst Day ($)": g["Combined PnL ($)"].min()}).reset_index()
    return out.sort_values("Combined PnL ($)", ascending=False).round(2).reset_index(drop=True)


def by_month(trades, eod):
    rows = {}
    for t in trades:
        m = t["date"][:7]
        r = rows.setdefault(m, {"Month": m, "Long Trades": 0, "Long PnL ($)": 0.0, "Short Trades": 0, "Short PnL ($)": 0.0})
        k = "Long" if t["side"] == L else "Short"
        r[f"{k} Trades"] += 1
        r[f"{k} PnL ($)"] += t.get("pnl", 0.0)
    out = pd.DataFrame(sorted(rows.values(), key=lambda x: x["Month"]))
    if len(out):
        out["Combined PnL ($)"] = out["Long PnL ($)"] + out["Short PnL ($)"]
        month_end = {}
        for d, b in sorted(eod.items()):
            month_end[str(d)[:7]] = b
        out["Balance End of Month ($)"] = out["Month"].map(month_end)
    return out.round(2)


def short_text():
    if not cb.SHORT_ENABLED:
        return "OFF"
    if str(cb.SHORT_STRATEGY).lower() == "v16":
        return (f"ON: v16 bounce-zone + vacuum (parked strategy), gap {cb.MIN_GAP_PCT:g}%+, entries "
                f"{min(cb.ENTRY_START, cb.VAC_ENTRY_START)}-{cb.LAST_ENTRY_TIME}, hold to {cb.EOD_COVER_TIME} or the stop, "
                f"{cb.LOCATE_FEE_PCT:g}% locate + {cb.SLIPPAGE_PCT:g}% slippage per fill; vacuum gap "
                f"{'required' if cb.VAC_REQUIRE_GAP else 'NOT required'}, day volume "
                f"{'required' if cb.VAC_USE_MIN_VOLUME else 'NOT required'}")
    cap = f"${cb.MAX_RISK_PER_TRADE_USD:,.0f} max risk a short" if cb.MAX_RISK_PER_TRADE_USD else "no $ risk cap"
    if str(cb.SHORT_STRATEGY).lower() in ("jay_read_2", "jr2"):    # 3.13.0
        J2 = cb.jay_read_2_module()
        g = J2.SETTINGS["GAPPER"]
        txt = (f"ON: Jay-read 2 ({J2.__file__}): gapper (open {J2.SETTINGS['GAP_SPLIT_PCT']:g}%+) / spiker (flush to VWAP) "
               f"rules; up {g['MIN_UP_PCT']:g}%+, ${g['MIN_DOLLAR_VOL'] / 1e6:g}M traded, high {g['AGE_MIN']}-{g['AGE_MAX']} min old, "
               f"flush {g['CRACK_MIN']:g}-{g['CRACK_MAX']:g}%, first bounce {g['R_MIN'] * 100:.0f}-{g['R_MAX'] * 100:.0f}% of it, "
               f"signals {g['SIGNAL_START']}-{g['SIGNAL_END']}, one short per high; stop = high of day +{g['STOP_PCT']:g}%, "
               f"after a {J2.LOCK_AFTER_PCT:g}% fade the stop goes to {J2.lock_text(J2.LOCK_STOP_PCT)}, cover {J2.EOD_COVER_TIME}")
        if cb.SQUEEZE_ENABLED:
            txt += " | + max squeeze short (one short per stock at a time)"
        return txt + f"; {cb.LOCATE_FEE_PCT:g}% locate + {cb.SLIPPAGE_PCT:g}% slippage per fill; {cap}"
    JR = cb.jay_read_module()
    lock = ("no lock" if JR.LOCK_STOP_PCT is None else
            f"after a {JR.LOCK_AFTER_PCT:g}% fade the stop goes to {JR.lock_text(JR.LOCK_STOP_PCT)}")
    txt = (f"ON: Jay-read short ({JR.__file__}): up {JR.MIN_UP_PCT:g}%+, ${JR.MIN_DOLLAR_VOL / 1e6:g}M traded, "
           f"high {JR.HOD_MIN_AGE_MIN}+ min old, cracked {JR.MIN_CRACK_PCT:g}%+; entry A rollover / B overhead high, signals "
           f"{JR.SIGNAL_START}-{JR.SIGNAL_END}; stop = regular-hours high +{JR.HOD_STOP_PCT:g}%, {lock}, cover "
           f"{JR.EOD_COVER_TIME}")
    if cb.SQUEEZE_ENABLED:
        SQ = cb.squeeze_module()
        txt += (f" | + max squeeze short ({SQ.__file__}): up {SQ.MIN_UP_PCT:g}%+, squeezed {SQ.SQUEEZE_PCT:g}%+ over the "
                f"last swing high, red candle at the top, signals {SQ.SIGNAL_START}-{SQ.SIGNAL_END}, stop = top "
                f"+{SQ.STOP_OVER_TOP_PCT:g}%, no lock, cover {SQ.EOD_COVER_TIME}; one short per stock at a time"
                + (", a stop-out ends the stock for both" if SQ.BOOK_DONE_AFTER_STOP else ""))
    return txt + f"; {cb.LOCATE_FEE_PCT:g}% locate + {cb.SLIPPAGE_PCT:g}% slippage per fill; {cap}"


def summary_frame(acc, n_days, n_ok, n_err, src10, skipped=(), vault=None, missing=(), miss_path=None):
    rows = [("Strategy file", os.path.abspath(COMBINED_FILE)),
            ("Premarket long", f"{'ON' if cb.LONG_ENABLED else 'OFF'}: +{cb.LONG_MIN_GAP_PCT * 100:.0f}% from the prior close, "
                               f"${cb.LONG_MIN_ENTRY_PRICE:.2f}+, momentum chase on 10-second candles, entries "
                               f"{cb.LONG_SESSION_START}-{cb.LONG_SESSION_END} in the first {cb.LONG_FRESH_ENTRY_SEC // 60} min "
                               f"after the cross, max {cb.LONG_MAX_TRADES_PER_SYMBOL} trades per stock, half at "
                               f"{cb.LONG_TARGET_MULT:g}R, trail, {cb.LONG_MAX_HOLD_MIN_WITHOUT_PROFIT}-min time stop, "
                               f"{cb.LONG_SLIPPAGE_PCT * 100:g}% slippage per fill"),
            ("Short", short_text()),
            ("Account", f"start ${cb.STARTING_BALANCE:,.0f}, one balance, compounding; long {cb.LONG_ACCOUNT_PCT:g}% "
                        f"(max ${cb.LONG_MAX_POSITION_USD:,.0f}), short {cb.SHORT_ACCOUNT_PCT:g}% (max ${cb.SHORT_MAX_POSITION_USD:,.0f})"),
            ("Long loss limits", f"stop {cb.LONG_MIN_RISK_PCT * 100:g}-{cb.LONG_MAX_RISK_PCT * 100:g}% under the entry, "
                                 f"{cb.LONG_MAX_LOSS_PER_STOCK_PCT:g}% of the position per stock per day"),
            ("Long daily stop", f"no new longs once the day's long losses reach {cb.LONG_DAILY_LOSS_PCT_OF_POSITION:g}% of "
                                f"the long position size at the start of the day: {len(skipped)} long trade(s) not taken"
                                + (" - " + "; ".join(f"{t['date']} {t['ticker']}" for t in skipped[:20]) if skipped else "")),
            ("Ticker-days", f"list {os.path.abspath(EXCEL_FILE)}" if EXCEL_FILE else "every ticker-day in the vault"),
            ("Date range", f"{START_DATE or 'first day'} to {END_DATE or 'today'}"),
            ("Bars", f"vault {vault.path}" if vault is not None else f"CSV folder {os.path.abspath(BARS_FOLDER or '.')}"),
            ("Days in list / processed / missing / errors", f"{n_days} / {n_ok} / {len(missing)} / {n_err}"),
            ("Missing days list", miss_path or "-"),
            ("Long candles", ", ".join(f"{k}: {v}" for k, v in src10.items()) or "-")]
    for name, s in acc.items():
        pf = "inf" if s["pf"] == float("inf") else round(s["pf"], 2)
        rows += [(f"{name}: trades / wins / win rate", f"{s['trades']} / {s['wins']} / {s['win_rate']:.0f}%"),
                 (f"{name}: net P&L ($)", round(s["net"], 2)),
                 (f"{name}: final balance ($)", round(s["final"], 2)),
                 (f"{name}: return %", round(s["net"] / cb.STARTING_BALANCE * 100.0, 1)),
                 (f"{name}: max drawdown %", round(s["max_dd"], 2)),
                 (f"{name}: profit factor ($)", pf),
                 (f"{name}: avg win / avg loss ($)", f"{s['avg_win']:,.0f} / {s['avg_loss']:,.0f}")]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def format_workbook(path):
    try:
        from openpyxl import load_workbook
        from openpyxl.chart import LineChart, Reference
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return
    wb = load_workbook(path)
    head = PatternFill("solid", fgColor="1F2937")
    green, red = Font(color="0B8043"), Font(color="C62828")
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head
            c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[1].height = 32
        hdr = {c.value: c.column_letter for c in ws[1]}
        for name, letter in hdr.items():
            name = str(name or "")
            ws.column_dimensions[letter].width = (60 if name in ("Value", "Long Note", "Exits", "Note") else
                                                  22 if name in ("Metric", "Result", "Long Candles", "Setup") else
                                                  14 if "$" in name else 11)
            if "$" in name:
                for row in ws.iter_rows(min_row=2, min_col=ws[f"{letter}1"].column, max_col=ws[f"{letter}1"].column):
                    for c in row:
                        if isinstance(c.value, (int, float)):
                            c.number_format = '#,##0.00;[Red]-#,##0.00'
                            if "PnL" in name and c.value:
                                c.font = green if c.value > 0 else red
        if ws.title == "Summary":
            ws.column_dimensions["A"].width = 42
            ws.column_dimensions["B"].width = 110
        if ws.title == "Ticker P&L" and "Chart" in hdr:
            for row in range(2, ws.max_row + 1):
                c = ws[f"{hdr['Chart']}{row}"]
                if c.value:
                    c.hyperlink = c.value
                    c.value = "open"
                    c.font = Font(color="0563C1", underline="single")
    if "Equity" in wb.sheetnames:
        ws = wb["Equity"]
        if ws.max_row > 2:
            ch = LineChart()
            ch.title = "Account balance (end of day)"
            ch.y_axis.title = "$"
            ch.height, ch.width = 11, 26
            ch.add_data(Reference(ws, min_col=2, max_col=ws.max_column, min_row=1, max_row=ws.max_row), titles_from_data=True)
            ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row))
            ws.add_chart(ch, "F2")
    order = [x for x in ("Summary", "Ticker P&L", "By Ticker", "Trades", "By Month", "Equity", "Days") if x in wb.sheetnames]
    wb._sheets = [wb[x] for x in order] + [w for w in wb._sheets if w.title not in order]
    wb.active = 0
    for w in wb.worksheets:
        w.sheet_view.tabSelected = w.title == "Summary"
    wb.save(path)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def csv_files(tk, day):
    """BARS_FOLDER mode: (1-minute file, 10-second file or None) for one day, or (None, None)."""
    p1 = os.path.join(BARS_FOLDER, f"{tk}_{day}_bars.csv")
    p10 = os.path.join(BARS_FOLDER, f"{tk}_{day}_10s.csv")
    if not os.path.exists(p1):
        return None, None
    use10 = os.path.exists(p10) and str(cb.LONG_BARS).lower() != "rebuild"
    return p1, (p10 if use10 else None)


def main():
    os.makedirs(CHART_DIR, exist_ok=True)
    vault = None
    if BARS_FOLDER:
        print(f"Bars from the CSV folder {os.path.abspath(BARS_FOLDER)} (BARS_FOLDER set - the vault is not used)")
        if not EXCEL_FILE:
            sys.exit("BARS_FOLDER needs a list: set EXCEL_FILE (or --list)")
    else:
        try:
            vault = cb.open_vault(VAULT_DB or cb.VAULT_DB)
        except RuntimeError as exc:
            sys.exit(str(exc))
        print(f"Bars from the vault: {vault.path}")
    targets = read_targets(EXCEL_FILE) if EXCEL_FILE else vault_targets(vault)
    if targets.empty:
        print("Nothing to run.")
        return
    if cb.LONG_ENABLED:
        print("Long candles: " + ("10-second candles rebuilt from the 1-minute bars (LONG_BARS = rebuild)"
                                  if str(cb.LONG_BARS).lower() == "rebuild" else
                                  "the vault's 10-second bars where stored, else rebuilt from the 1-minute bars"))
    missing = cb.vault_bars().Missing()
    runs, day_rows = [], []
    t0 = time.time()
    try:
        for i, row in targets.iterrows():
            tk, day = row["Ticker"], row["Date"]
            tag = f"[{i + 1}/{len(targets)}] {tk:<6} {day}"
            try:
                if BARS_FOLDER:
                    p1, p10 = csv_files(tk, day)
                    if p1 is None:
                        raise cb.MissingFromVault("no CSV file in BARS_FOLDER")
                    r = cb.run_day(tk, day, csv_1m=p1, csv_10s=p10)
                else:
                    r = cb.run_day(tk, day, vault=vault)
                runs.append(r)
                nl, ns = len(r.side(L)), len(r.side(S))
                day_rows.append({"Date": str(day), "Ticker": tk, "Status": "ok", "1-min Bars": r.data["src1"],
                                 "Long Candles": r.data["src10"], "Long Trades": nl, "Short Trades": ns,
                                 "Long Note": r.long_note(), "Detail": ""})
                print(f"{tag}  long {nl} / short {ns} trade(s)   ({r.data['src1']}; long: {r.data['src10'] or '-'})")
            except cb.MissingFromVault as exc:
                missing.add(tk, day, str(exc))
                day_rows.append({"Date": str(day), "Ticker": tk, "Status": "missing from vault" if not BARS_FOLDER
                                 else "missing", "1-min Bars": "", "Long Candles": "", "Long Trades": 0, "Short Trades": 0,
                                 "Long Note": "", "Detail": str(exc)})
                print(f"{tag}  missing: {exc}")
            except (Exception, SystemExit) as exc:
                msg = str(exc).strip() or exc.__class__.__name__
                day_rows.append({"Date": str(day), "Ticker": tk, "Status": "error", "1-min Bars": "", "Long Candles": "",
                                 "Long Trades": 0, "Short Trades": 0, "Long Note": "", "Detail": msg})
                print(f"{tag}  skipped: {msg}")
    except KeyboardInterrupt:
        print("\nStopped by user - writing the report for the days finished so far.")
    print(f"\nProcessed {len(day_rows)} day(s) in {time.time() - t0:.1f}s")
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    miss_path = missing.write(OUTPUT_FOLDER, "missing_from_vault.xlsx" if not BARS_FOLDER else "missing_bars.xlsx")

    trades = [t for r in runs for t in r.trades]
    cb.simulate(trades)                                            # the combined account (writes P&L on every trade)
    every = list(trades)                                           # incl. longs the daily stop skipped (stats re-run it)
    skipped = cb.drop_skipped(trades, runs)
    names = [("Combined", (L, S))] + ([("Long only", (L,)), ("Short only", (S,))] if cb.LONG_ENABLED and cb.SHORT_ENABLED else [])
    acc = {n: cb.account_stats(every, sides) for n, sides in names}
    days = sorted({r.day for r in runs})
    eod = {n: balances_by_day(a["curve"], days, cb.STARTING_BALANCE) for n, a in acc.items()}

    if SAVE_CHARTS != "none":
        for r in runs:
            if SAVE_CHARTS == "all" or r.trades:
                cb.build_combined_chart(r, os.path.join(CHART_DIR, f"{r.ticker}_{r.day}_combined.html"))

    src10 = pd.Series([r.data["src10"].split(" (")[0] for r in runs if r.data["src10"]]).value_counts().to_dict()
    n_err = sum(1 for d in day_rows if d["Status"] == "error")
    tp = ticker_rows(runs, eod["Combined"])
    equity = pd.DataFrame({"Date": [str(d) for d in days], **{f"{n} ($)": [round(eod[n][d], 2) for d in days] for n in eod}})
    path = os.path.join(OUTPUT_FOLDER, OUTPUT_EXCEL)
    with pd.ExcelWriter(path) as xw:
        summary_frame(acc, len(targets), len(runs), n_err, src10, skipped, vault, missing, miss_path).to_excel(
            xw, sheet_name="Summary", index=False)
        tp.to_excel(xw, sheet_name="Ticker P&L", index=False)
        by_ticker(tp).to_excel(xw, sheet_name="By Ticker", index=False)
        cb.trades_frame(trades).to_excel(xw, sheet_name="Trades", index=False)
        by_month(trades, eod["Combined"]).to_excel(xw, sheet_name="By Month", index=False)
        equity.to_excel(xw, sheet_name="Equity", index=False)
        pd.DataFrame(day_rows).to_excel(xw, sheet_name="Days", index=False)
    format_workbook(path)

    cb.print_accounts(every)
    cb.print_skipped(skipped)
    if len(tp):
        top = tp.sort_values("Combined PnL ($)", ascending=False)
        print("\nBest ticker-days (combined P&L):")
        for _, x in top.head(5).iterrows():
            print(f"  {x['Date']} {x['Ticker']:<6} long {x['Long PnL ($)']:>+10,.0f}  short {x['Short PnL ($)']:>+10,.0f}  "
                  f"combined {x['Combined PnL ($)']:>+10,.0f}")
        print("Worst ticker-days:")
        for _, x in top.tail(5).iloc[::-1].iterrows():
            print(f"  {x['Date']} {x['Ticker']:<6} long {x['Long PnL ($)']:>+10,.0f}  short {x['Short PnL ($)']:>+10,.0f}  "
                  f"combined {x['Combined PnL ($)']:>+10,.0f}")
    missing.print_summary(miss_path)
    print(f"\nReport saved to: {os.path.abspath(path)}")


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="Combined long + short bulk backtest from the IB data vault.")
    _ap.add_argument("--vault", default=None, help="market_data_vault.db (default: VAULT_DB here / in the combined file)")
    _ap.add_argument("--list", default=None, help="Ticker/Date list (default: EXCEL_FILE; None = every day in the vault)")
    _ap.add_argument("--from", dest="d0", default=None, help="first date YYYY-MM-DD (default: START_DATE)")
    _ap.add_argument("--to", dest="d1", default=None, help="last date YYYY-MM-DD (default: END_DATE)")
    _ap.add_argument("--short", default=None, choices=["jr2", "jr", "v16"],
                     help="short strategy: jr2 = Jay-read 2 (3.13.0), jr = Jay-read v1.2, v16 = parked (default: the setting)")
    _ap.add_argument("--squeeze", default=None, choices=["on", "off"], help="max squeeze short next to it (default: the setting)")
    _a = _ap.parse_args()
    if _a.short:
        SHORT_STRATEGY = cb.SHORT_STRATEGY = {"jr2": "jay_read_2", "jr": "jay_read", "v16": "v16"}[_a.short]
    if _a.squeeze:
        SQUEEZE_ENABLED = cb.SQUEEZE_ENABLED = _a.squeeze == "on"
    EXCEL_FILE = _a.list or EXCEL_FILE
    START_DATE = _a.d0 or START_DATE
    END_DATE = _a.d1 or END_DATE
    VAULT_DB = _a.vault or VAULT_DB
    main()
