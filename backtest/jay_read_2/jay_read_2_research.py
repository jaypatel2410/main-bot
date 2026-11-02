"""Jay-read 2 (research only, never places orders, reads the IB vault read-only).

GAPPERS = open 30%+ over the prior close -> GAP2 settings.  SPIKERS = open under +30% -> SPK2 settings.
Usage: python jay_read_2_research.py <market_data_vault.db>

Research engine: short the FIRST failed bounce near the top (Jay's 2026-11-01 review).

Closed 1-min candles (04:00-16:00, volume > 0). Short at the next candle's open. Exits = Jay-read's: stop (a candle that
opens over it fills at the open, a high touching it fills at the stop), lock (-25% -> stop to entry +5%), 15:55 cover.
3% locate + 0.1% slippage per fill, $10k a trade.
"""
import sqlite3
import numpy as np, pandas as pd

import sys
VAULT = sys.argv[1] if len(sys.argv) > 1 else "market_data_vault.db"
SLIP, LOCATE = 0.001, 0.03

BASE = dict(
    MIN_UP=150.0,          # high of day (incl. premarket) vs prior close, %
    MIN_DOLLAR=20e6,       # $ traded before the signal
    GAP_MIN=None, GAP_MAX=None,   # open vs prior close, % (None = any)
    AGE_MIN=3, AGE_MAX=180,       # minutes since the regular-hours high
    CRACK_MIN=18.0, CRACK_MAX=60.0,  # flush: lowest low since the high vs the high, %
    FLUSH_VW=None,         # the flush low came within this % over VWAP (None = no condition)
    R_MIN=0.45, R_MAX=1.0,  # the bounce takes back this share of the flush (1.0 = back to the high)
    DT=1.0,                # bounce high at most this % over the regular-hours high (double top allowed)
    FRESH=4,               # the trigger candle comes within this many candles of the bounce high
    UNDER=6.0,             # trigger close within this % under the bounce high
    WICK=0.5,              # trigger = red candle, or upper wick >= this share of the range
    V_MIN=8.0,             # trigger close at least this % over VWAP
    SIG0=575, SIG1=840,    # signal window (09:35 - 14:00)
    MAX_TRADES=2, DONE_AFTER_STOP=True,
    STOP="rh", STOP_PCT=3.0,   # "rh" = regular-hours high +%, "hod" = high incl. premarket +%, "bh" = bounce high +%
    MAX_STOP=None,         # skip when the stop is more than this % over the entry
    LOCK_AFTER=25.0, LOCK_STOP=-5.0, EOD=955,
    MAX_HALT_JUMPS=8,
    ONE_PER_HIGH=False,    # True = one signal per regular-hours high (the first failed bounce only)
)


def load_days(min_up=30.0):
    db = sqlite3.connect(f"file:{VAULT}?mode=ro", uri=True)
    d = pd.read_sql("select ticker, day, prior_close from days where status_1m='ok' and prior_close>0", db)
    hi = pd.read_sql("select ticker, day, max(high) hi from bars_1m group by ticker, day", db)
    d = d.merge(hi, on=["ticker", "day"])
    d = d[d.hi >= d.prior_close * (1 + min_up / 100)].sort_values(["day", "ticker"]).reset_index(drop=True)
    out = []
    for r in d.itertuples():
        b = pd.read_sql("select t,open,high,low,close,volume from bars_1m where ticker=? and day=? and volume>0 order by t",
                        db, params=(r.ticker, r.day))
        ts = pd.to_datetime(b.t)
        mm = (ts.dt.hour * 60 + ts.dt.minute).values
        keep = (mm >= 240) & (mm < 960)
        b, mm = b[keep], mm[keep]
        if len(b) < 30 or not (mm >= 570).any():
            continue
        o, h, l, c, v = (b[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
        tp = (h + l + c) / 3
        vw = np.cumsum(tp * v) / np.cumsum(v)
        dol = np.cumsum(tp * v)
        i0 = int(np.argmax(mm >= 570))
        out.append(dict(tk=r.ticker, d=r.day, pc=float(r.prior_close), m=mm, o=o, h=h, l=l, c=c, vw=vw, dol=dol, i0=i0,
                        gap=(o[i0] / r.prior_close - 1) * 100))
    return out


def run_day(D, P):
    m, o, h, l, c, vw, dol, i0, pc = D["m"], D["o"], D["h"], D["l"], D["c"], D["vw"], D["dol"], D["i0"], D["pc"]
    if P["GAP_MIN"] is not None and D["gap"] < P["GAP_MIN"]:
        return []
    if P["GAP_MAX"] is not None and D["gap"] >= P["GAP_MAX"]:
        return []
    n = len(m)
    hod = np.maximum.accumulate(h)
    trades, pos, pend, used, done, nt = [], None, None, set(), False, 0
    rh, krh, halts = -1.0, -1, 0
    for k in range(n):
        # 1 entry at this open
        if pend is not None:
            sig, pend = pend, None
            e = o[k] * (1 - SLIP)
            if e < sig["stop"] and m[k] < P["EOD"]:
                if P["MAX_STOP"] is None or sig["stop"] / e - 1 <= P["MAX_STOP"] / 100:
                    pos = dict(sig, e=e, stop=sig["stop"], stop0=sig["stop"], k0=k, locked=False, t_in=int(m[k]))
                    trades.append(pos); nt += 1
        # 2 manage
        if pos is not None:
            x, why = None, None
            if m[k] >= P["EOD"]:
                x, why = o[k], "EOD"
            elif k > pos["k0"] and o[k] >= pos["stop"]:
                x, why = o[k], "LOCK" if pos["locked"] else "STOP"
            elif h[k] >= pos["stop"]:
                x, why = pos["stop"], "LOCK" if pos["locked"] else "STOP"
            elif not pos["locked"] and l[k] <= pos["e"] * (1 - P["LOCK_AFTER"] / 100):
                pos["locked"] = True
                pos["stop"] = min(pos["stop"], pos["e"] * (1 - P["LOCK_STOP"] / 100))
            if x is not None:
                pos.update(x=x, why=why, ret=(pos["e"] - x * (1 + SLIP)) / pos["e"] - LOCATE, t_out=int(m[k]))
                if why == "STOP" and P["DONE_AFTER_STOP"]:
                    done = True
                pos = None
        # 3 read at the close
        if k >= i0:
            if k > i0 and m[k] - m[k - 1] >= 5 and abs(o[k] / c[k - 1] - 1) >= 0.05:
                halts += 1
            if h[k] > rh:
                rh, krh = h[k], k
        if pos is not None or pend is not None or done or nt >= P["MAX_TRADES"] or k < i0 + 2:
            continue
        if not (P["SIG0"] <= m[k] <= P["SIG1"]):
            continue
        if hod[k] / pc - 1 < P["MIN_UP"] / 100 or dol[k] < P["MIN_DOLLAR"] or halts >= P["MAX_HALT_JUMPS"]:
            continue
        age = m[k] - m[krh]
        if age < P["AGE_MIN"] or age > P["AGE_MAX"] or krh >= k - 1:
            continue
        klo = krh + int(np.argmin(l[krh:k + 1]))
        L = l[klo]
        crack = 1 - L / rh
        if crack < P["CRACK_MIN"] / 100 or crack > P["CRACK_MAX"] / 100 or klo >= k:
            continue
        if P["FLUSH_VW"] is not None and L > vw[klo] * (1 + P["FLUSH_VW"] / 100):
            continue
        kbh = klo + 1 + int(np.argmax(h[klo + 1:k + 1]))
        BH = h[kbh]
        r = (BH - L) / (rh - L)
        if r < P["R_MIN"] or r > P["R_MAX"] or BH > rh * (1 + P["DT"] / 100):
            continue
        if k - kbh > P["FRESH"] or (krh, klo) in used or (P["ONE_PER_HIGH"] and any(u[0] == krh for u in used)):
            continue
        rng = h[k] - l[k]
        if not (c[k] < o[k] or (rng > 0 and h[k] - c[k] >= P["WICK"] * rng)):
            continue
        if c[k] < BH * (1 - P["UNDER"] / 100) or c[k] < vw[k] * (1 + P["V_MIN"] / 100):
            continue
        if P["STOP"] == "rh":
            stop = rh * (1 + P["STOP_PCT"] / 100)
        elif P["STOP"] == "hod":
            stop = hod[k] * (1 + P["STOP_PCT"] / 100)
        else:
            stop = BH * (1 + P["STOP_PCT"] / 100)
        used.add((krh, klo))
        pend = dict(tk=D["tk"], d=D["d"], gap=D["gap"], stop=stop, rh=rh, bh=BH, low=L, crack=crack * 100, retr=r,
                    vs_vw=(c[k] / vw[k] - 1) * 100, age=int(age), t_sig=int(m[k]), up=(hod[k] / pc - 1) * 100)
    if pos is not None:
        pos.update(x=c[-1], why="EOD", ret=(pos["e"] - c[-1] * (1 + SLIP)) / pos["e"] - LOCATE, t_out=int(m[-1]))
    return trades


def run(days, **over):
    P = dict(BASE, **over)
    out = []
    for D in days:
        out += run_day(D, P)
    return pd.DataFrame(out)


def stats(t):
    if t is None or not len(t):
        return dict(n=0, win=0, pnl=0, pf=0, wo5=0, stop=0, comp=10000, dd=0)
    t = t.sort_values(["d", "t_in"])
    r = t.ret.values * 10000
    pf = r[r > 0].sum() / -r[r < 0].sum() if (r < 0).any() else 99
    eq, peak, dd = 10000.0, 10000.0, 0.0
    for x in t.ret.values:
        eq += min(eq * 0.2, 50000) * x
        peak = max(peak, eq); dd = min(dd, eq / peak - 1)
    return dict(n=len(t), win=round(100 * (r > 0).mean(), 1), pnl=round(r.sum()), pf=round(pf, 2),
                wo5=round(r.sum() - np.sort(r)[-5:].sum()), stop=round(100 * float(np.median(t.stop0 / t.e - 1)), 1),
                comp=round(eq), dd=round(100 * dd, 1))


GAP2 = {'MIN_UP': 200, 'CRACK_MIN': 25, 'FLUSH_VW': None, 'R_MIN': 0.4, 'R_MAX': 0.85, 'DT': 1, 'FRESH': 6, 'V_MIN': 5, 'AGE_MIN': 10, 'AGE_MAX': 180, 'SIG1': 900, 'STOP': 'hod', 'STOP_PCT': 5, 'ONE_PER_HIGH': True, 'MIN_DOLLAR': 20000000.0}
SPK2 = {'MIN_UP': 200, 'CRACK_MIN': 25, 'FLUSH_VW': 0, 'R_MIN': 0.4, 'R_MAX': 0.85, 'DT': 1, 'FRESH': 6, 'V_MIN': 5, 'AGE_MIN': 10, 'AGE_MAX': 180, 'SIG1': 900, 'STOP': 'hod', 'STOP_PCT': 5, 'ONE_PER_HIGH': True, 'MIN_DOLLAR': 20000000.0}


if __name__ == "__main__":
    days = load_days()
    for nm, P, q in (("GAPPERS", GAP2, lambda D: D["gap"] >= 30), ("SPIKERS", SPK2, lambda D: D["gap"] < 30)):
        t = run([D for D in days if q(D)], **P)
        t.to_csv(f"jay_read_2_{nm.lower()}_trades.csv", index=False)
        print(nm, "all", stats(t), "\n   Jul-Oct", stats(t[t.d >= "2026-07"]))
