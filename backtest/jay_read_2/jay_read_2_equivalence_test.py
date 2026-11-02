"""Jay-read 2: the live class (jay_read_2_short.py) vs the research engine (jay_read_2_research.py), trade by trade.

Reads the IB vault READ-ONLY. Places no orders. Usage (from this folder, bot closed or open - it only reads):
    python jay_read_2_equivalence_test.py "C:\\...\\ib_data_vault\\market_data_vault.db"

If the vault was split, the main vault keeps 2026-04-01 on; the 2026 days moved out for being before April
(vault_move_before.py, noted "before 2026-04-01" in the main vault) are read from market_data_vault_ARCHIVE.db, so the
test covers the research's 1,183 ticker-days. The archive's under-$70M days are NOT used (the research did not use them).

Pass = every research trade has the same ticker, day, entry minute, entry price, exit minute, exit price and reason in
the live class, and the live class has no extra trades.
"""
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "jay_read_short"), os.path.join(HERE, "..", "max_squeeze_short")]

import jay_read_2_research as R            # noqa: E402
import jay_read_2_short as J2              # noqa: E402

DAY_FROM = "2026-01-01"
BOOK = True                                         # live API driven through max_squeeze_short.ShortBook (as the bot)


def vault_files(main):
    out = [main]
    arc = os.path.join(os.path.dirname(os.path.abspath(main)), "market_data_vault_ARCHIVE.db")
    if os.path.exists(arc):
        out.append(arc)
    return out


def load(main):
    """The research's ticker-days: status 'ok' in the main vault (2026), plus the days moved to the archive for being
    before April. Bars 04:00-16:00 with volume (as the research loads)."""
    days = []
    db = sqlite3.connect(f"file:{main}?mode=ro", uri=True)
    d = pd.read_sql("select ticker, day, prior_close from days where status_1m='ok' and prior_close>0 and day>=?", db,
                    params=(DAY_FROM,))
    moved = pd.read_sql("select ticker, day from days where status_1m='archived' and day>=? and note like '%before 2026-04-01%'",
                        db, params=(DAY_FROM,))
    sources = [(db, d)]
    arc = vault_files(main)[1:]
    if arc and len(moved):
        adb = sqlite3.connect(f"file:{arc[0]}?mode=ro", uri=True)
        ad = pd.read_sql("select ticker, day, prior_close from days where status_1m='ok' and prior_close>0 and day>=?", adb,
                         params=(DAY_FROM,))
        ad = ad.merge(moved, on=["ticker", "day"])
        sources.append((adb, ad))
    for con, dd in sources:
        for r in dd.sort_values(["day", "ticker"]).itertuples():
            b = pd.read_sql("select t,open,high,low,close,volume from bars_1m where ticker=? and day=? and volume>0 order by t",
                            con, params=(r.ticker, r.day))
            if not len(b):
                continue
            b["ts"] = pd.to_datetime(b.t)
            days.append((r.ticker, r.day, float(r.prior_close), b))
    print(f"{len(d):,} days from the main vault + {len(sources[1][1]) if len(sources) > 1 else 0:,} moved days from the archive")
    return days


def research_day(tk, day, pc, b):
    mm = (b.ts.dt.hour * 60 + b.ts.dt.minute).values
    keep = (mm >= 240) & (mm < 960)
    bb, mm = b[keep], mm[keep]
    if bb.high.max() < pc * 1.3 or len(bb) < 30 or not (mm >= 570).any():
        return []
    o, h, l, c, v = (bb[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
    tp = (h + l + c) / 3
    i0 = int(np.argmax(mm >= 570))
    D = dict(tk=tk, d=day, pc=pc, m=mm, o=o, h=h, l=l, c=c, vw=np.cumsum(tp * v) / np.cumsum(v), dol=np.cumsum(tp * v),
             i0=i0, gap=(o[i0] / pc - 1) * 100)
    P = dict(R.BASE, **(R.GAP2 if D["gap"] >= 30 else R.SPK2))
    out = []
    for t in R.run_day(D, P):
        out.append(dict(tk=tk, d=day, kind="gapper" if D["gap"] >= 30 else "spiker", t_in=int(t["t_in"]),
                        e=round(float(t["e"]), 6), t_out=int(t["t_out"]), x=round(float(t["x"]), 6), why=t["why"],
                        ret=float(t["ret"])))
    return out


def live_day(tk, day, pc, b):
    s = J2.JayRead2Short(tk, pc)                     # backtest mode: the same rules, fills at the next open
    for r in b.itertuples():
        s.on_bar(r.ts.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume)
    s.finish()
    out = []
    for t in s.trades:
        out.append(dict(tk=tk, d=day, kind="gapper" if t.signal["setup"] == J2.SETUP_GAP else "spiker",
                        t_in=t.t0.hour * 60 + t.t0.minute, e=round(float(t.entry), 6),
                        t_out=t.t_end.hour * 60 + t.t_end.minute, x=round(float(t.legs[-1][1]), 6), why=t.reason,
                        ret=float(t.ret)))
    return out


def live_mode_day(tk, day, pc, b):
    """The live API driven like the bot: SIGNAL -> short at the next candle's open (entry_allowed / entry_filled); the
    stop sits at the broker (a candle opening over it fills at the open, a high reaching it fills at the stop); STOP_MOVED
    moves it; COVER_ALL covers at the next candle's open. Same fills as the research, through the live code path."""
    s = J2.JayRead2Short(tk, pc, simulate_fills=False)
    if BOOK:                                        # through the bot's ShortBook (one short per stock) - same trades
        s = J2.make_book(tk, pc, [s])
    slip = s.cfg["SLIPPAGE_PCT"] / 100
    want_entry = want_cover = False
    stop = None
    for r in b.itertuples():
        t = r.ts.to_pydatetime()
        m = t.hour * 60 + t.minute
        if not (240 <= m < 960):
            continue
        if want_entry:
            want_entry = False
            ok, _ = s.entry_allowed(r.open * (1 - slip), t)
            if ok:
                stop = s.entry_filled(r.open * (1 - slip), t)["stop"]
            else:
                s.entry_cancelled()
        if s.pos is not None:
            k0 = s.pos.k0
            if want_cover:
                want_cover = False
                s.cover_filled(1.0, r.open, "EOD", t)
            elif k0 < len(s.reader.o) and r.open >= stop:
                s.cover_filled(1.0, r.open, "STOP", t)
            elif r.high >= stop:
                s.cover_filled(1.0, stop, "STOP", t)
        for e in s.on_bar(t, r.open, r.high, r.low, r.close, r.volume):
            if e["type"] == "SIGNAL":
                want_entry = True
            elif e["type"] == "STOP_MOVED":
                stop = e["stop"]
            elif e["type"] == "COVER_ALL":
                want_cover = True
    s.finish()
    out = []
    for t in s.trades:
        out.append(dict(tk=tk, d=day, kind="gapper" if t.signal["setup"] == J2.SETUP_GAP else "spiker",
                        t_in=t.t0.hour * 60 + t.t0.minute, e=round(float(t.entry), 6),
                        t_out=t.t_end.hour * 60 + t.t_end.minute, x=round(float(t.legs[-1][1]), 6), why=t.reason,
                        ret=float(t.ret)))
    return out


def compare(name, res, liv):
    key = lambda x: (x["tk"], x["d"], x["t_in"])           # noqa: E731
    R_, L_ = {key(x): x for x in res}, {key(x): x for x in liv}
    same, diff = 0, []
    for k in sorted(set(R_) | set(L_)):
        a, b = R_.get(k), L_.get(k)
        if a and b and all(a[f] == b[f] for f in ("kind", "e", "t_out", "x", "why")):
            same += 1
        else:
            diff.append((k, a, b))
    print(f"{name}: identical trades {same} of {len(res)} research / {len(liv)} {name}")
    for k, a, b in diff[:20]:
        print("DIFF", k, "\n   research:", a, "\n   " + name + ":", b)
    return diff


def stats(rows):
    if not rows:
        return "0 trades"
    r = np.array([x["ret"] for x in rows]) * 10000
    pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else float("inf")
    return f"{len(r)} trades, {100 * (r > 0).mean():.0f}% win, PF {pf:.2f}, ${r.sum():,.0f} at $10k"


def main():
    vault = sys.argv[1] if len(sys.argv) > 1 else "market_data_vault.db"
    days = load(vault)
    print(f"{len(days):,} ticker-days in the test (the research used 1,183)")
    res, liv, lvm = [], [], []
    for tk, day, pc, b in days:
        res += research_day(tk, day, pc, b)
        liv += live_day(tk, day, pc, b)
        lvm += live_mode_day(tk, day, pc, b)
    for kind in ("gapper", "spiker"):
        print(f"{kind:7s} research : {stats([x for x in res if x['kind'] == kind])}")
        print(f"{kind:7s} class    : {stats([x for x in liv if x['kind'] == kind])}")
        print(f"{kind:7s} live API : {stats([x for x in lvm if x['kind'] == kind])}")
    diff = compare("class (backtest mode)", res, liv) + compare("live API via ShortBook", res, lvm)
    print("PASS" if not diff else f"FAIL - {len(diff)} differences")
    return 0 if not diff else 1


if __name__ == "__main__":
    sys.exit(main())
