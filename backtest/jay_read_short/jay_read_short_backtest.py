"""
JAY-READ SHORT + MAX SQUEEZE SHORT - bulk backtester (the bot's intraday shorts)           (v1.2, 2026-10-22)
====================================================================================================================
Runs the intraday shorts of LH Short Bot 3.9.0 on a list of ticker-days (a gapper sheet: .xlsx or .csv with a ticker
column and a date column) using 1-minute bars from the IB data vault (market_data_vault.db), or from a folder of CSV
files (--bars, one-off files): the Jay-read short (jay_read_short.py v1.2) and the max squeeze short
(max_squeeze_short.py) together, one short per stock at a time - max_squeeze_short.ShortBook, the bot's own code.
No IB Gateway code - fetching is the vault's job (python ib_data_vault.py --list <list.xlsx>).

    python3 jay_read_short_backtest.py --list my_gappers.xlsx --vault "C:/.../ib_data_vault/market_data_vault.db"
    python3 jay_read_short_backtest.py --list my_gappers.xlsx                    # VAULT_DB below
    python3 jay_read_short_backtest.py --list ../data/list584.xlsx --bars ../data/bars   # CSV folder instead of the vault
    python3 jay_read_short_backtest.py ... --charts 0          # 0 = no charts (default: one PNG per trade)
    python3 jay_read_short_backtest.py ... --no-squeeze        # the Jay-read short alone
    python3 jay_read_short_backtest.py ... --squeeze-only      # the max squeeze short alone
    python3 jay_read_short_backtest.py ... --no-lock           # Jay-read: hold the original stop to EOD (no lock)

584 research days (2026-04-01..2026-10-05), $10,000 a trade: both 98 trades, 71% win, +$120,316 | --no-squeeze 92
trades, 71% win, +$94,065 | --squeeze-only 16 trades, 75% win, +$36,707.

A ticker-day not in the vault (or stored there as no_data / no_contract / error) is skipped and written to
<out>/missing_from_vault.xlsx: python ib_data_vault.py --list <out>/missing_from_vault.xlsx adds them.

Bar CSV files (--bars): <TICKER>_<YYYY-MM-DD>_bars.csv with columns time, open, high, low, close, volume[, prior_close]
(time in ET, 04:00-20:00). Without a prior_close column the prior close must come from the list.

Outputs (--out, default ./jay_read_results): trades.csv, summary.txt, monthly.csv, equity.csv (compounding), charts/*.png,
missing_from_vault.xlsx (only when a day is missing)
"""
import argparse, os, sys, time as _time
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jay_read_short as JR
import max_squeeze_short as SQ

ET = "America/New_York"
MIN_SHORT_PRICE = 0.50                # 3.13.1: no short signal under this price (the live short scanner's $0.50 minimum)
VAULT_DB = r"market_data_vault.db"   # FULL PATH of your vault (--vault), e.g. r"C:\...\ib_data_vault\market_data_vault.db".
                                     # A bare name is looked up next to this file, then in the current folder.


# ---------------------------------------------------------------------------------------------------------- data
def read_list(path):
    df = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    tc = next((cols[c] for c in ("ticker", "symbol", "tickers", "stock", "sym") if c in cols), None)
    dc = next((cols[c] for c in ("date", "day", "trade date", "trading day", "trade_date") if c in cols), None)
    if tc is None or dc is None:
        raise SystemExit(f"{path}: need a ticker column (Ticker/Symbol) and a date column (Date/Day); found {list(df.columns)}")
    pcc = cols.get("prior_close") or cols.get("prior close") or cols.get("prev close") or cols.get("previous close")
    out = []
    for _, r in df.iterrows():
        if pd.isna(r[tc]) or pd.isna(r[dc]):
            continue
        out.append((str(r[tc]).strip().upper(), pd.to_datetime(r[dc]).date(),
                    float(r[pcc]) if pcc and not pd.isna(r[pcc]) else None))
    return sorted(set(out), key=lambda x: (x[1], x[0]))


def read_bars(path):
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]
    tcol = next((c for c in ("time", "datetime", "date", "timestamp") if c in raw.columns), None)
    ts = pd.to_datetime(raw[tcol])
    raw["time"] = ts.dt.tz_localize(ET) if ts.dt.tz is None else ts.dt.tz_convert(ET)
    pc = float(raw["prior_close"].dropna().iloc[0]) if "prior_close" in raw.columns and raw["prior_close"].notna().any() else None
    return raw[["time", "open", "high", "low", "close", "volume"]], pc


def clean(df, day):
    """That ET day only, sorted, no duplicates, numbers only, candles with trades only."""
    df = df[df["time"].dt.date == day].copy()
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0).clip(lower=0)
    return df[df.volume > 0].reset_index(drop=True)


def vault_bars():
    """lh_vault_bars.py (next to this file): how the backtesters read the IB data vault."""
    mod = sys.modules.get("lh_vault_bars")
    if mod is None:
        import importlib.util
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lh_vault_bars.py")
        if not os.path.exists(p):
            raise SystemExit("lh_vault_bars.py not found - keep it next to jay_read_short_backtest.py")
        spec = importlib.util.spec_from_file_location("lh_vault_bars", p)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["lh_vault_bars"] = mod
        spec.loader.exec_module(mod)
    return mod


MISSING_PREFIX = "missing from vault: "


def load_day(bars_dir, ticker, day, pc_list=None, vault=None):
    """(df, prior close, "") or (None, None, why). From the vault when one is given, else from the CSV folder."""
    if vault is not None:
        df, pc, _, _, why = vault_bars().load(vault, ticker, day)
        if df is None:
            return None, None, MISSING_PREFIX + why
    else:
        path = os.path.join(bars_dir, f"{ticker}_{day:%Y-%m-%d}_bars.csv")
        if not os.path.exists(path):
            return None, None, "no bar file"
        df, pc = read_bars(path)
    pc = pc_list or pc
    if not pc:
        return None, None, "no prior close"
    df = clean(df, day)
    if df.empty:
        return None, None, "no candles with trades"
    return df, pc, ""


# ---------------------------------------------------------------------------------------------------------- run
def make_short(ticker, pc, cfg, sq_cfg=None, mode="both", simulate_fills=True):
    """mode "both" = the bot's ShortBook (Jay-read + max squeeze, one position per stock), "jr" / "sq" = one alone.
    simulate_fills=False = the live-bot API (tests)."""
    if mode == "jr":
        return JR.JayReadShort(ticker, pc, cfg, simulate_fills=simulate_fills)
    if mode == "sq":
        return SQ.MaxSqueezeShort(ticker, pc, sq_cfg, simulate_fills=simulate_fills)
    return SQ.ShortBook(ticker, pc, jr_cfg=cfg, sq_cfg=sq_cfg, simulate_fills=simulate_fills)


def skip_cheap_signals(s, events, min_px):
    """3.13.1: the live scanner only adds stocks at $0.50+ (SHORT_SCAN_MIN_PRICE): a short signal under min_px is not
    taken (the waiting entry is dropped before the next candle)."""
    for e in events:
        if e.get("type") == "SIGNAL" and min_px and float(e.get("close") or 0) < min_px:
            p = s.part(e["signal"].get("setup")) if hasattr(s, "part") else s
            p.pending = None
            p.awaiting = None


def run_day(df, pc, ticker, cfg, sq_cfg=None, mode="both"):
    s = make_short(ticker, pc, cfg, sq_cfg, mode)
    for r in df.itertuples(index=False):
        skip_cheap_signals(s, s.on_bar(r.time, r.open, r.high, r.low, r.close, r.volume), MIN_SHORT_PRICE)
    return s.finish(), s


def run_all(days, bars_dir, cfg, vault=None, verbose=True, sq_cfg=None, mode="both"):
    trades, missing = [], []
    for n, (tk, d, pc_list) in enumerate(days, 1):
        try:
            df, pc, why = load_day(bars_dir, tk, d, pc_list, vault)
        except Exception as e:                                      # one bad day must not stop the run
            df, pc, why = None, None, f"error: {e}"
        if df is None:
            missing.append((tk, d, why)); continue
        tr, _ = run_day(df, pc, tk, cfg, sq_cfg, mode)
        trades += tr
        if verbose and n % 100 == 0:
            print(f"  {n}/{len(days)} days, {len(trades)} trades")
    return pd.DataFrame(trades), missing


def fmt_usd(v):
    return "-" if v != v else (("+" if v >= 0 else "-") + f"${abs(v):,.0f}")


def stats(T):
    T = T.sort_values(["date", "entry_time"])
    w, l = T[T.pnl > 0], T[T.pnl <= 0]
    eq = T.pnl.cumsum()
    return dict(trades=len(T), days=T.date.nunique(), wins=len(w), losses=len(l), win=len(w) / len(T), pnl=T.pnl.sum(),
                avg_win=w.pnl.mean() if len(w) else 0.0, avg_loss=l.pnl.mean() if len(l) else 0.0,
                pf=w.pnl.sum() / -l.pnl.sum() if len(l) and l.pnl.sum() < 0 else np.inf, worst=T.pnl.min(),
                max_dd=(eq - eq.cummax()).min(), no_best5=T.pnl.sort_values().iloc[:-5].sum() if len(T) > 5 else np.nan,
                median_stop=T.stop_pct.median())


def snowball(T, start=10_000.0, frac=0.20, fee_pct=3.0):
    """Compounding: each short is frac of the realized account at its entry; P&L is booked at its exit."""
    T = T.sort_values(["date", "entry_time"]).reset_index(drop=True)
    ev = []
    for i, r in T.iterrows():
        ev.append((r.date, r.entry_time, 1, i)); ev.append((r.date, r.exit_time or "16:00", 0 if r.exit_time > r.entry_time else 2, i))
    ev.sort()
    eq, size, rows = start, {}, []
    for d, t, kind, i in ev:
        if kind == 1:
            size[i] = eq * frac
        else:
            eq += size.pop(i) * T.ret[i]
            rows.append(dict(date=d, time=t, ticker=T.ticker[i], equity=eq))
    E = pd.DataFrame(rows)
    dd = (E.equity / E.equity.cummax() - 1).min() if len(E) else 0.0
    return eq, dd, E


def report(T, cfg, missing, n_days, sq_cfg=None, mode="both"):
    L = []
    p = L.append
    sq_cfg = sq_cfg or SQ.settings()
    lock = "off" if cfg["LOCK_STOP_PCT"] is None else f"after -{cfg['LOCK_AFTER_PCT']:.0f}% the stop goes to {JR.lock_text(cfg['LOCK_STOP_PCT'])}"
    if mode != "sq":
        p(f"JAY-READ SHORT{' + MAX SQUEEZE SHORT' if mode == 'both' else ''} backtest   Jay-read entries: rollover"
          f"{' + overhead-high level' if cfg['LEVEL_SHORT'] else ''}"
          f"{', re-entry after a new high' if cfg['REENTRY_AFTER_NEW_HIGH'] else ''}")
        p(f"   (${cfg['POSITION_USD']:,.0f} a trade, locate {cfg['LOCATE_FEE_PCT']}%, slippage {cfg['SLIPPAGE_PCT']}% "
          f"a fill, stop = regular-hours high +{cfg['HOD_STOP_PCT']}%, lock {lock}, EOD cover {cfg['EOD_COVER_TIME']})")
    else:
        p("MAX SQUEEZE SHORT backtest (alone)")
    if mode != "jr":
        p(f"   max squeeze: up {sq_cfg['MIN_UP_PCT']:g}%+, squeezed {sq_cfg['SQUEEZE_PCT']:g}%+ over the last swing high "
          f"({sq_cfg['SWING_PCT']:g}% pullbacks), red candle within {sq_cfg['NEAR_TOP_PCT']:g}% of the top, stop = top "
          f"+{sq_cfg['STOP_OVER_TOP_PCT']:g}%, no lock, EOD cover {sq_cfg['EOD_COVER_TIME']}"
          + ("; one short per stock at a time, a stop-out ends the stock for both" if mode == "both" else ""))
    p(f"ticker-days in the list: {n_days}, run: {n_days - len(missing)}, skipped: {len(missing)}")
    if T.empty:
        p("no trades"); return "\n".join(L)
    x = stats(T)
    p(f"trades {x['trades']} on {x['days']} days | {x['wins']} W / {x['losses']} L = {100 * x['win']:.0f}% | P&L {fmt_usd(x['pnl'])} | "
      f"avg win {fmt_usd(x['avg_win'])} / avg loss {fmt_usd(x['avg_loss'])} | PF {x['pf']:.2f}")
    p(f"worst {fmt_usd(x['worst'])} | max drawdown {fmt_usd(x['max_dd'])} | without best 5 {fmt_usd(x['no_best5'])} | "
      f"median stop {100 * x['median_stop']:.0f}% over the entry")
    eq, dd, _ = snowball(T)
    p(f"compounding: $10,000 at 20% of the account a short -> {fmt_usd(eq).lstrip('+')} (max drawdown {100 * dd:.0f}%)")
    for lab, g in (("Apr-Jun", T[T.date < "2026-07-01"]), ("Jul-Oct", T[T.date >= "2026-07-01"])):
        if len(g):
            p(f"  {lab}: {len(g)} trades, {100 * (g.pnl > 0).mean():.0f}% win, {fmt_usd(g.pnl.sum())}")
    p("exit reasons: " + ", ".join(f"{k} {v} ({100 * (T[T.exit_reason == k].pnl > 0).mean():.0f}% win, "
                                   f"{fmt_usd(T[T.exit_reason == k].pnl.sum())})" for k, v in T.exit_reason.value_counts().items()))
    p("by month:")
    for mo, g in T.groupby(T.date.str[:7]):
        p(f"  {mo}: {len(g):3d} trades, {100 * (g.pnl > 0).mean():3.0f}% win, {fmt_usd(g.pnl.sum())}")
    p("by entry:")
    for k, g in T.groupby("setup"):
        p(f"  {k:18s}: {len(g):3d} trades, {100 * (g.pnl > 0).mean():3.0f}% win, {fmt_usd(g.pnl.sum())}")
    p("by setup kind:")
    for k, g in T.groupby("kind"):
        p(f"  {k:18s}: {len(g):3d} trades, {100 * (g.pnl > 0).mean():3.0f}% win, {fmt_usd(g.pnl.sum())}")
    if missing:
        p("skipped ticker-days (first 10): " + ", ".join(f"{a} {b} ({c})" for a, b, c in missing[:10]))
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------------- chart
def chart(df, pc, tr, cfg, path, number=None):
    """House-style chart of one trade: 1-min candles by index, VWAP, the read (regular-hours high, crack low, overhead
    high, drop low, bounce high), entry, stop, lock level, exit. No halt lines."""
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["text.parse_math"] = False
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    BG, PANEL, GRID, TXT, MUTED = "#0e0f11", "#121316", "#25272b", "#d6d9de", "#8b9099"
    UP, DN, VWC, SH, STOPC, MFE, HL, BLUE = "#e6e8eb", "#f23645", "#ff9800", "#e040fb", "#ff6b5b", "#22d3ee", "#ffd23f", "#3b82f6"
    o, h, l, c, v = (df[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    m = (df.time.dt.hour * 60 + df.time.dt.minute).to_numpy()
    vw = np.cumsum((h + l + c) / 3 * v) / np.cumsum(v)
    hm = df.time.dt.strftime("%H:%M").to_numpy()
    ke, ks = int(tr["k_entry"]), int(tr["k_signal"])
    kx = int(tr["k_exit"]) if tr["k_exit"] == tr["k_exit"] else len(df) - 1
    sq = tr.get("setup", "") == "squeeze"
    k_first = min(int(tr["k_rh"]), int(tr["k_ref"]))
    start = 540 if m[k_first] >= 545 else max(240, m[k_first] - 20)
    end = min(960, max(m[min(kx, len(df) - 1)] + 45, m[ke] + 120))
    idx = [k for k in range(len(df)) if start <= m[k] < end]
    X = {k: n for n, k in enumerate(idx)}
    fig = plt.figure(figsize=(16, 9.5), facecolor=BG)
    ax = fig.add_axes([0.04, 0.3, 0.63, 0.58]); av = fig.add_axes([0.04, 0.08, 0.63, 0.2])
    for a in (ax, av):
        a.set_facecolor(PANEL); a.grid(color=GRID, lw=0.5); a.tick_params(colors=MUTED, labelsize=8.5)
        for s_ in a.spines.values():
            s_.set_color(GRID)
    for k in idx:
        col = UP if c[k] >= o[k] else DN
        ax.plot([X[k], X[k]], [l[k], h[k]], color=col, lw=0.7, zorder=2)
        ax.add_patch(Rectangle((X[k] - 0.35, min(o[k], c[k])), 0.7, max(abs(c[k] - o[k]), (h[k] - l[k]) * 0.02 + 1e-9), color=col, zorder=3))
        av.bar(X[k], v[k], color="#8b9099" if c[k] >= o[k] else DN, width=0.8, alpha=0.85)
    xs = [X[k] for k in idx]
    ax.plot(xs, [vw[k] for k in idx], color=VWC, lw=1.2)
    rh_x = [X[k] for k in idx if int(tr["k_rh"]) <= k <= kx]
    if rh_x:
        ax.plot([rh_x[0], rh_x[-1]], [tr["rth_high"]] * 2, color=MUTED, lw=0.8, ls=":")
    marks = [(int(tr["k_rh"]), tr["rth_high"], "regular-hours high", "o", BLUE, 6),
             (int(tr["k_crack"]), tr["crack_low"], f"crack -{100 * tr['crack']:.0f}%", "^", MFE, -14),
             (int(tr["k_ref"]), tr["ref"], "level" if tr.get("setup", "") == "level" else "overhead high", "o", BLUE, 6),
             (int(tr["k_low"]), tr["low"], "drop low", "^", MFE, -14),
             (int(tr["k_bh"]), tr["bounce_high"], "bounce high", "D", HL, 10)]
    if sq:                                   # max squeeze: the swing high it broke (ref) and the squeeze top (bounce high)
        marks = [(int(tr["k_ref"]), tr["ref"], "last swing high (the average short)", "o", BLUE, 6),
                 (int(tr["k_crack"]), tr["crack_low"], "pullback that confirmed it", "^", MFE, -14),
                 (int(tr["k_bh"]), tr["bounce_high"], f"squeeze top +{100 * tr['bounce']:.0f}%", "D", HL, 10)]
        kr = [X[k] for k in idx if int(tr["k_ref"]) <= k <= kx]
        if kr:
            ax.plot([kr[0], kr[-1]], [tr["ref"]] * 2, color=BLUE, lw=0.8, ls=":")
    seen = set()
    for kk, px, lab, mk, cc, dy in marks:
        if kk in X and (kk, round(px, 6)) not in seen:
            seen.add((kk, round(px, 6)))
            ax.plot([X[kk]], [px], marker=mk, ms=10, mfc="none" if mk == "o" else cc, mec=cc, mew=2, zorder=8)
            ax.annotate(lab, (X[kk], px), xytext=(8, dy), textcoords="offset points", color=cc, fontsize=8.5)
    xe, xx = X.get(ke, xs[-1]), X.get(kx, xs[-1])
    ax.plot([xe], [tr["entry"]], marker="v", ms=12, color=SH, mec="black", zorder=10)
    ax.annotate(f"short {tr['entry']:.4g} {tr['entry_time']}", (xe, tr["entry"]), xytext=(10, -16), textcoords="offset points",
                color=SH, fontsize=9, weight="bold")
    ax.plot([xe, xx], [tr["stop"]] * 2, color=STOPC, lw=1, ls="--")
    ax.text(xx, tr["stop"], f" stop {tr['stop']:.4g}", color=STOPC, fontsize=8, va="bottom")
    if not sq and cfg["LOCK_STOP_PCT"] is not None and tr["lock_time"]:
        kl = next((k for k in idx if k >= ke and hm[k] == tr["lock_time"]), None)
        lk = tr["entry"] * (1 - cfg["LOCK_STOP_PCT"] / 100)
        if kl in X:
            ax.plot([X[kl], xx], [lk, lk], color=MFE, lw=1, ls="--")
            ax.text(X[kl], lk, f" lock {lk:.4g}", color=MFE, fontsize=8, va="bottom")
    ax.plot([xx], [tr["exit_price"]], marker="X", ms=10, color=STOPC if tr["pnl"] <= 0 else MFE, mec="black", zorder=9)
    lo = min(l[k] for k in idx); hi = max(max(h[k] for k in idx), tr["stop"])
    ax.set_ylim(lo - (hi - lo) * 0.04, hi + (hi - lo) * 0.06); ax.set_xlim(-2, len(xs) + 2); av.set_xlim(-2, len(xs) + 2)
    ticks, last, slot = [], -99, None
    for k in idx:
        s30 = m[k] // 30
        if s30 != slot and X[k] - last > len(idx) * 0.05:
            ticks.append(X[k]); last = X[k]
        slot = s30
    for a in (ax, av):
        a.set_xticks(ticks); a.set_xticklabels([hm[idx[t]] for t in ticks], color=MUTED, fontsize=8)
    ax.set_xticklabels([]); av.set_yticks([])
    col = "#4ade80" if tr["pnl"] > 0 else DN
    num = f"#{number}  " if number else ""
    lvl = tr.get("setup", "rollover") == "level"
    name = "Max squeeze short" if sq else ("Jay-read overhead-high short" if lvl else "Jay-read rollover short")
    fig.text(0.03, 0.955, f"{num}{tr['ticker']}  {tr['date']}   {name}   {fmt_usd(tr['pnl'])}", color=col, fontsize=17, weight="bold")
    fig.text(0.03, 0.925, f"{tr['exit_reason']} at {tr['exit_time']}.  Magenta = short, dashed red = stop, "
             + ("X = exit, orange = VWAP, dotted = the squeeze top and the swing high it broke." if sq else
                "dashed cyan = lock, X = exit, orange = VWAP, dotted = regular-hours high."), color=MUTED, fontsize=10)
    f = lambda v_: f"{100 * v_:+.0f}%"
    lines = [("THE READ", TXT), (f"stock +{100 * tr['up']:.0f}% (prior close {pc:.4g}), ${tr['dollar_vol'] / 1e6:.0f}M traded", MUTED),
             (f"regular-hours high {tr['rth_high']:.4g} at {tr['rth_high_time']} ({tr['hod_age_min']} min old)", MUTED),
             (f"momentum broken: cracked -{100 * tr['crack']:.0f}% to {tr['crack_low']:.4g}", MUTED),
             (f"{'level (lower high)' if lvl else 'overhead high'} {tr['ref']:.4g} at {tr['ref_time']} -> drop -{100 * tr['drop']:.0f}% to {tr['low']:.4g}", MUTED),
             (f"bounce +{100 * tr['bounce']:.0f}% to {tr['bounce_high']:.4g} at {tr['bounce_high_time']}", MUTED),
             (f"  back {100 * tr['retrace']:.0f}% of the drop; {100 * tr['reclaim']:.0f}% of the whole crack", MUTED),
             (f"  ({tr['kind']})", MUTED),
             (f"signal {tr['signal_time']}: " + ("the bounce hit the level and was rejected" if lvl else "red candle at the top of the bounce"), MUTED),
             (f"  {f(tr['vs_vwap'])} vs VWAP", MUTED), ("", MUTED),
             ("THE TRADE", TXT), (f"short {tr['entry']:.4g} at {tr['entry_time']}", MUTED),
             (f"stop {tr['stop']:.4g} ({f(tr['stop_pct'])}: regular-hours high +{cfg['HOD_STOP_PCT']:.0f}%)", MUTED),
             (f"lock: {('at ' + tr['lock_time']) if tr['lock_time'] else 'not reached'}", MUTED),
             (f"exit {tr['exit_price']:.4g} {tr['exit_reason']} at {tr['exit_time']}", MUTED),
             (f"P&L {fmt_usd(tr['pnl'])} on ${cfg['POSITION_USD']:,.0f} ({f(tr['ret'])} net of {cfg['LOCATE_FEE_PCT']:.0f}% locate)", MUTED),
             (f"best open profit {100 * tr['mfe']:.0f}%, worst {100 * tr['mae']:.0f}% against", MUTED)]
    if sq:
        lines = [("THE READ", TXT), (f"stock +{100 * tr['up']:.0f}% (prior close {pc:.4g}), ${tr['dollar_vol'] / 1e6:.0f}M traded", MUTED),
                 (f"last swing high it broke {tr['ref']:.4g} at {tr['ref_time']}", MUTED),
                 (f"  (the 'average short' level: a high with a {SQ.SWING_PCT:g}% pullback)", MUTED),
                 (f"squeeze top {tr['bounce_high']:.4g} at {tr['bounce_high_time']}: +{100 * tr['bounce']:.0f}% over it", MUTED),
                 (f"signal {tr['signal_time']}: red candle at the top", MUTED), (f"  {f(tr['vs_vwap'])} vs VWAP", MUTED), ("", MUTED),
                 ("THE TRADE", TXT), (f"short {tr['entry']:.4g} at {tr['entry_time']}", MUTED),
                 (f"stop {tr['stop']:.4g} ({f(tr['stop_pct'])}: the top +{SQ.STOP_OVER_TOP_PCT:g}%), no lock", MUTED),
                 (f"exit {tr['exit_price']:.4g} {tr['exit_reason']} at {tr['exit_time']}", MUTED),
                 (f"P&L {fmt_usd(tr['pnl'])} on ${cfg['POSITION_USD']:,.0f} ({f(tr['ret'])} net of {cfg['LOCATE_FEE_PCT']:.0f}% locate)", MUTED),
                 (f"best open profit {100 * tr['mfe']:.0f}%, worst {100 * tr['mae']:.0f}% against", MUTED)]
    y = 0.88
    for s_, cc in lines:
        fig.text(0.69, y, s_, color=cc, fontsize=10, weight="bold" if cc == TXT else "normal", va="top"); y -= 0.029
    fig.savefig(path, dpi=100, facecolor=BG); plt.close(fig)


# ---------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Backtest the Jay-read short on a list of ticker-days.")
    ap.add_argument("--list", required=True, help=".xlsx / .csv with ticker and date columns (optional prior_close)")
    ap.add_argument("--vault", default=None, help="market_data_vault.db (default: VAULT_DB at the top of this file)")
    ap.add_argument("--bars", default=None, help="read <TICKER>_<YYYY-MM-DD>_bars.csv files from this folder INSTEAD of "
                                                 "the vault (one-off files)")
    ap.add_argument("--out", default="jay_read_results")
    ap.add_argument("--from", dest="d0", default=None, help="first date YYYY-MM-DD")
    ap.add_argument("--to", dest="d1", default=None, help="last date YYYY-MM-DD")
    ap.add_argument("--no-lock", action="store_true", help="Jay-read: no lock, hold the original stop to EOD")
    ap.add_argument("--no-squeeze", action="store_true", help="the Jay-read short alone (no max squeeze short)")
    ap.add_argument("--squeeze-only", action="store_true", help="the max squeeze short alone")
    ap.add_argument("--rollover-only", action="store_true", help="entry A only (v1.0: no overhead-high level entry)")
    ap.add_argument("--reentry", action="store_true", help="after a stop, allow a new setup once the stock makes a new high")
    ap.add_argument("--charts", type=int, default=-1, help="annotated PNG for up to N trades (-1 = all, 0 = none)")
    ap.add_argument("--position", type=float, default=JR.POSITION_USD, help="$ per trade")
    a = ap.parse_args()

    days = read_list(a.list)
    if a.d0:
        days = [x for x in days if x[1] >= date.fromisoformat(a.d0)]
    if a.d1:
        days = [x for x in days if x[1] <= date.fromisoformat(a.d1)]
    os.makedirs(a.out, exist_ok=True)
    over = {"LOCK_STOP_PCT": None} if a.no_lock else {}
    if a.rollover_only:
        over["LEVEL_SHORT"] = False
    if a.reentry:
        over["REENTRY_AFTER_NEW_HIGH"] = True
    cfg = JR.settings(POSITION_USD=a.position, **over)
    sq_cfg = SQ.settings(POSITION_USD=a.position)
    mode = "sq" if a.squeeze_only else ("jr" if a.no_squeeze else "both")
    vault = None
    if not a.bars:
        try:
            vault = vault_bars().open_vault(a.vault or VAULT_DB, near=__file__)
        except RuntimeError as exc:
            raise SystemExit(str(exc))
        print(f"bars from the vault: {vault.path}")
    t0 = _time.time()
    missing = []
    try:
        T, missing = run_all(days, a.bars, cfg, vault, sq_cfg=sq_cfg, mode=mode)
        txt = report(T, cfg, missing, len(days), sq_cfg, mode)
        print(txt)
        with open(os.path.join(a.out, "summary.txt"), "w") as f:
            f.write(txt + "\n")
        if not T.empty:
            T = T.sort_values(["date", "entry_time"]).reset_index(drop=True)
            T.insert(0, "no", np.arange(1, len(T) + 1))
            T.to_csv(os.path.join(a.out, "trades.csv"), index=False)
            T.groupby(T.date.str[:7]).agg(trades=("pnl", "size"), win=("pnl", lambda s: (s > 0).mean()), pnl=("pnl", "sum")) \
                .to_csv(os.path.join(a.out, "monthly.csv"))
            snowball(T)[2].to_csv(os.path.join(a.out, "equity.csv"), index=False)
            n = len(T) if a.charts < 0 else min(a.charts, len(T))
            if n:
                cdir = os.path.join(a.out, "charts"); os.makedirs(cdir, exist_ok=True)
                for _, tr in T.head(n).iterrows():
                    df, pc, _ = load_day(a.bars, tr.ticker, date.fromisoformat(tr.date), None, vault)
                    chart(df, pc, tr, cfg, os.path.join(cdir, f"{tr.no:03d}_{tr.date}_{tr.ticker}_{tr.entry_time.replace(':', '')}.png"), tr.no)
                print(f"charts: {n} saved in {cdir}")
    finally:
        miss = vault_bars().Missing()
        for tk, d, why in missing:
            if why.startswith(MISSING_PREFIX):
                miss.add(tk, d, why[len(MISSING_PREFIX):])
        if vault is not None:
            miss.print_summary(miss.write(a.out))
    print(f"done in {_time.time() - t0:.0f} s -> {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
