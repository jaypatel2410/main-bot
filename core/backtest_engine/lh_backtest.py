#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LH Short Bot 3.13 - the Backtest tab's engine (research only: it never connects to IB Gateway or TradeZero).

Runs a strategy over ticker-days of the IB data vault (market_data_vault.db) in a SEPARATE PROCESS, so the live bot is
never slowed, with the same strategy code the bot trades with:

    Jay-read short     jay_read_short.py      (through lh_combined_backtester.py, shorts on, long off)
    Max squeeze short  max_squeeze_short.py   (same run - one position per stock, as live - filtered to its trades)
    Premarket long     lh_long_premarket.py   (lh_combined_backtester.py long engine, shorts off)
    your own           backtest/<folder>/strategy.py   (see backtest/README.md: NAME + run_day(...))

Files (next to main.py):
    backtest/<folder>/runs/<YYYYmmdd-HHMMSS>/job.json, progress.json, trades.csv, summary.json
    backtest/<folder>/notes.json       your verdict + notes per ticker-day (kept across runs)
    backtest/settings.json             the vault path and the last run settings
"""
import calendar
import hashlib
import csv
import importlib.util
import json
import math
import os
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    import pytz
    ET = pytz.timezone("America/New_York")


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):                               # 3.12.1: this file lives in core/backtest_engine/ - find the app folder
        if os.path.isfile(os.path.join(d, "main.py")) or os.path.isdir(os.path.join(d, "backtest")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))


BASE = base_dir()
BT_DIR = os.path.join(BASE, "backtest")

SUBDIRS = ("jay_read_short", "jay_read_2", "max_squeeze_short", "premarket_long", "_shared")
for _sub in SUBDIRS:                                  # the strategy files live in backtest/<strategy>/
    _sp = os.path.join(BT_DIR, _sub)
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.insert(0, _sp)

BUILTIN = [
    # 3.13.0: Jay-read 2 - the live short (jay_read_2_short.py); and with the momentum long = the live bot
    {"k": "jr2", "folder": "jay_read_2", "name": "Jay-read 2 short", "file": "backtest/jay_read_2/jay_read_2_short.py",
     "side": "Short", "engine": "combined_short", "match": "jr2"},
    {"k": "jr2long", "folder": "combined_jr2_long", "name": "Momentum long + Jay-read 2 (live bot)",
     "file": "backtest/_shared/lh_combined_backtester.py", "side": "Both", "engine": "combined_all", "match": "jr2long"},
    {"k": "jr", "folder": "jay_read_short", "name": "Jay-read short v1.2", "file": "backtest/jay_read_short/jay_read_short.py", "side": "Short",
     "engine": "combined_short", "match": "jr"},
    {"k": "sq", "folder": "max_squeeze_short", "name": "Max squeeze short", "file": "backtest/max_squeeze_short/max_squeeze_short.py", "side": "Short",
     "engine": "combined_short", "match": "sq"},
    {"k": "long", "folder": "premarket_long", "name": "Premarket long", "file": "backtest/premarket_long/lh_long_premarket.py", "side": "Long",
     "engine": "combined_long", "match": "long"},
    # 3.12.2: the combined runs - the strategies together on each ticker-day, one position per stock (as live)
    {"k": "jrsq", "folder": "combined_jr_sq", "name": "Jay-read + Max squeeze (shorts)", "file": "backtest/_shared/lh_combined_backtester.py",
     "side": "Short", "engine": "combined_short", "match": "jrsq"},
    {"k": "jrlong", "folder": "combined_jr_long", "name": "Momentum long + Jay-read v1.2",
     "file": "backtest/_shared/lh_combined_backtester.py", "side": "Both", "engine": "combined_all", "match": "jrlong"},
    {"k": "all", "folder": "combined_all", "name": "Momentum long + Jay-read + Max squeeze", "file": "backtest/_shared/lh_combined_backtester.py",
     "side": "Both", "engine": "combined_all", "match": "all"},
]
DEFAULT_CFG = {"from": "", "to": "", "days": "all", "list": "", "locate": 3.0, "slip": 0.1,
               "comp_pct": 20.0, "comp_max": 50000.0, "comp_max_long": 10000.0, "start_bal": 10000.0, "procs": 0}


# ----------------------------------------------------------------------------- small helpers
def _jload(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, default=str)
    os.replace(tmp, path)


def _load_file(name, path):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def _mod(name):
    """A strategy / backtester module: the .py file next to main.py (or the .exe), else the copy built into the .exe."""
    for d in [os.path.join(BT_DIR, x) for x in SUBDIRS] + [BASE]:
        f = os.path.join(d, name + ".py")
        if os.path.isfile(f):
            return _load_file(name, f)
    import importlib
    return importlib.import_module(name)


def _stub_plotly():
    """lh_combined_backtester.py imports plotly for its HTML charts; the tab never draws those, so a missing plotly
    (e.g. in the .exe) is replaced by an empty stand-in."""
    try:
        import plotly.graph_objects  # noqa: F401
    except Exception:
        import types
        pl = types.ModuleType("plotly")
        go = types.ModuleType("plotly.graph_objects")
        sp = types.ModuleType("plotly.subplots")
        sp.make_subplots = lambda *a, **k: None
        pl.graph_objects, pl.subplots = go, sp
        sys.modules.update({"plotly": pl, "plotly.graph_objects": go, "plotly.subplots": sp})


def settings():
    s = _jload(os.path.join(BT_DIR, "settings.json"), {})
    c = _cloud()
    if c is not None:                                  # 3.14: the last run settings follow you; the vault path is per PC
        try:
            lc = c.kv_get("bt", "last_cfg", None)
            if lc:
                s["last_cfg"] = lc
        except Exception:
            pass
    if not s.get("vault"):
        for cand in (os.path.join(BASE, "..", "ib_data_vault", "market_data_vault.db"),
                     os.path.join(BASE, "ib_data_vault", "market_data_vault.db"),
                     os.path.join(BASE, "market_data_vault.db")):
            if os.path.isfile(cand):
                s["vault"] = os.path.abspath(cand)
                break
    if not s.get("vault") and c is not None:            # 3.14: the vault lives in Turso; this PC reads its replica
        try:
            import turso_vault
            s["vault"] = turso_vault.default_replica()
        except Exception:
            pass
    return s


def save_settings(**kw):
    s = settings()
    s.update({k: v for k, v in kw.items() if v is not None})
    c = _cloud()
    if c is not None and kw.get("last_cfg") is not None:
        try:
            c.kv_put("bt", "last_cfg", kw["last_cfg"])
        except Exception:
            pass
    _jsave(os.path.join(BT_DIR, "settings.json"), s)
    return s


def strategies():
    """The built-in strategies + every backtest/<folder>/strategy.py (NAME, optional SIDE, run_day)."""
    out = [dict(s) for s in BUILTIN]
    try:
        for d in sorted(os.listdir(BT_DIR)):
            f = os.path.join(BT_DIR, d, "strategy.py")
            if d.startswith(("_", ".")) or not os.path.isfile(f) or any(s["folder"] == d for s in out):
                continue
            name, side = d.replace("_", " ").title(), "Short"
            try:
                src = open(f, encoding="utf-8").read()
                for line in src.splitlines():
                    if line.startswith("NAME") and "=" in line:
                        name = line.split("=", 1)[1].strip().strip("\"'")
                    if line.startswith("SIDE") and "=" in line:
                        side = line.split("=", 1)[1].strip().strip("\"'")
            except OSError:
                pass
            out.append({"k": "x_" + d, "folder": d, "name": name, "file": f"backtest/{d}/strategy.py", "side": side,
                        "engine": "custom", "match": "all"})
    except OSError:
        pass
    last = None
    c = _cloud()
    if c is not None:                                   # 3.14: one query for every strategy's newest run
        try:
            last = {}
            for f, rid, j, p, sm in c.execute("SELECT folder, rid, job, progress, summary FROM bt_runs WHERE rid IN "
                                               "(SELECT MAX(rid) FROM bt_runs GROUP BY folder)"):
                last.setdefault(f, []).append((rid, j, p, sm))
        except Exception:
            last = None
    for s in out:
        s["last"] = None
        runs = list_runs(s["folder"], None if last is None else last.get(s["folder"], []))
        if runs:
            s["last"] = runs[0]
    return out


def strat(k):
    for s in strategies():
        if s["k"] == k:
            return s
    return None


def _cloud():
    """3.14: the Turso client (None = no credentials: runs stay in backtest/<folder>/runs as before)."""
    try:
        try:
            import turso
        except ImportError:
            sys.path.insert(0, os.path.join(BASE, "core", "data"))
            import turso
        return turso.cloud()
    except Exception:
        return None


def _run_row(rid, job, pg, sm):
    return {"id": rid, "cfg": (job or {}).get("cfg", {}), "state": (pg or {}).get("state", "?"), "done": (pg or {}).get("done", 0),
            "total": (pg or {}).get("total", 0), "error": (pg or {}).get("error", ""),
            "updated": (sm or {}).get("updated", ""), "days_total": (sm or {}).get("days_total"), "missing": (sm or {}).get("missing", 0),
            "tot": (sm or {}).get("tot"), "oos": (sm or {}).get("halves", [{}, {}])[-1] if sm else None,
            "note": (job or {}).get("note", "")}


def _up_run(folder, rid):
    """3.14: a finished run -> Turso (job without the day list, progress, summary, trades.csv); then the local folder goes."""
    c = _cloud()
    d = os.path.join(BT_DIR, folder, "runs", rid)
    sm = _jload(os.path.join(d, "summary.json"), None)
    if c is None or not sm:
        return False
    job = _jload(os.path.join(d, "job.json"), {})
    job.pop("days", None)
    pg = _jload(os.path.join(d, "progress.json"), {})
    try:
        with open(os.path.join(d, "trades.csv"), encoding="utf-8", newline="") as fh:
            tr = fh.read()
    except OSError:
        tr = ""
    c.batch([("INSERT OR REPLACE INTO bt_runs (folder, rid, job, progress, summary) VALUES (?,?,?,?,?)",
              (folder, rid, json.dumps(job, default=str), json.dumps(pg, default=str), json.dumps(sm, default=str))),
             ("INSERT OR REPLACE INTO bt_trades (folder, rid, csv) VALUES (?,?,?)", (folder, rid, tr))], atomic=True)
    with open(os.path.join(d, ".uploaded"), "w") as fh:        # the local folder is scratch now; list_runs removes it a little later
        fh.write("1")                                          # (the window still reads the final progress.json from it)
    return True


def list_runs(folder, cloud_rows=None):
    """cloud_rows: the folder's Turso rows [(rid, job, progress, summary)] when the caller already fetched them."""
    root = os.path.join(BT_DIR, folder, "runs")
    c = _cloud()
    out = []
    try:
        for rid in sorted(os.listdir(root), reverse=True)[:50]:
            rdir = os.path.join(root, rid)
            if not os.path.isdir(rdir):
                continue
            if rid.endswith(".deleted") or not os.listdir(rdir):       # leftover / empty folder from a delete: clean it up, no blank row
                _rmtree_hard(rdir)
                continue
            up = os.path.join(rdir, ".uploaded")
            if os.path.isfile(up):                                            # already in Turso: show the cloud row, drop the scratch
                if time.time() - os.path.getmtime(up) > 120:
                    _rmtree_hard(rdir)
                continue
            sm = _jload(os.path.join(root, rid, "summary.json"), None)
            pg = _jload(os.path.join(root, rid, "progress.json"), {})
            stale = not pg and time.time() - os.path.getmtime(rdir) > 300      # a run that never reported (left over)
            if not sm and (pg.get("state") == "error" or stale):              # 3.12.2: failed runs are not kept
                import shutil
                shutil.rmtree(rdir, ignore_errors=True)
                continue
            if sm and c is not None:                                          # finished (or an old local run): move it to Turso
                try:
                    if _up_run(folder, rid):
                        continue
                except Exception:
                    pass
            job = _jload(os.path.join(root, rid, "job.json"), {})
            out.append(_run_row(rid, job, pg, sm))
    except OSError:
        pass
    if c is not None:
        try:
            have = {r["id"] for r in out}
            rows = cloud_rows if cloud_rows is not None else c.execute(
                "SELECT rid, job, progress, summary FROM bt_runs WHERE folder=? ORDER BY rid DESC LIMIT 50", (folder,))
            for rid, j, p, s in rows:
                if rid not in have:
                    out.append(_run_row(rid, json.loads(j or "{}"), json.loads(p or "{}"), json.loads(s or "null")))
            out.sort(key=lambda r: r["id"], reverse=True)
            out = out[:50]
        except Exception:
            pass
    return out


# ----------------------------------------------------------------------------- vault reading (main process, light)
def _db(vault):
    if not vault or not os.path.isfile(vault):
        raise RuntimeError("Vault not found - set the path of market_data_vault.db in the Backtest tab")
    c = sqlite3.connect(f"file:{vault}?mode=ro", uri=True, timeout=10)
    return c


def vault_info(vault):
    try:
        c = _db(vault)
        n, lo, hi = c.execute("select count(*), min(day), max(day) from days where status_1m='ok'").fetchone()
        c.close()
        return {"ok": True, "days": n or 0, "from": lo or "", "to": hi or ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def day_list(vault, cfg, favorites=()):
    """[(ticker, day)] for the run: every vault day in the range, the favorites' vault days, or a list file."""
    lo, hi = cfg.get("from") or "0000-00-00", cfg.get("to") or "9999-99-99"
    c = _db(vault)
    try:
        rows = c.execute("select ticker, day from days where status_1m='ok' and day between ? and ? order by day, ticker",
                         (lo, hi)).fetchall()
    finally:
        c.close()
    mode = cfg.get("days") or "all"
    if mode == "fav":
        fav = {str(f).upper() for f in favorites}
        rows = [r for r in rows if r[0] in fav]
    elif mode == "list":
        want = set()
        path = str(cfg.get("list") or "")
        if not os.path.isfile(path):
            raise RuntimeError(f"List file not found: {path}")
        import pandas as pd
        df = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
        cols = {c.lower(): c for c in df.columns}
        tk = cols.get("ticker") or cols.get("symbol")
        dc = cols.get("date") or cols.get("day")
        if not tk or not dc:
            raise RuntimeError("The list needs a Ticker (or Symbol) and a Date column")
        for r in df.itertuples(index=False):
            t = str(getattr(r, tk)).upper().strip()
            d = str(pd.Timestamp(getattr(r, dc)).date())
            want.add((t, d))
        rows = [r for r in rows if (r[0], r[1]) in want]
    return [(r[0], r[1]) for r in rows]


def _fake_epoch(day, hms):
    """ET wall clock as a UTC epoch (the chart shows ET times that way)."""
    y, m, d = (int(x) for x in day.split("-"))
    hh, mm, ss = (int(x) for x in (hms + ":00:00").split(":")[:3])
    return calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0))


def bars(vault, ticker, day):
    """1-minute bars (04:00-20:00 ET) + VWAP and the last 20 daily bars, for the trade chart."""
    c = _db(vault)
    try:
        rows = c.execute("select t, open, high, low, close, volume from bars_1m where ticker=? and day=? order by t",
                         (ticker, day)).fetchall()
        try:
            daily = c.execute("select day, open, high, low, close, volume from daily_hist where ticker=? and day<=? "
                              "order by day desc limit 21", (ticker, day)).fetchall()[::-1]
        except sqlite3.Error:
            daily = []
        pc = c.execute("select prior_close from days where ticker=? and day=?", (ticker, day)).fetchone()
    finally:
        c.close()
    out, cv, cpv = [], 0.0, 0.0
    for t, o, h, l, cl, v in rows:
        hms = str(t)[11:19]
        if not ("04:00:00" <= hms < "20:00:00"):
            continue
        v = float(v or 0)
        cv += v
        cpv += v * (h + l + cl) / 3.0
        out.append({"time": _fake_epoch(day, hms), "open": o, "high": h, "low": l, "close": cl, "volume": v,
                    "vwap": cpv / cv if cv else cl})
    dl = [{"time": _fake_epoch(d, "00:00"), "open": o, "high": h, "low": l, "close": cl} for d, o, h, l, cl, _v in daily]
    return {"ok": bool(out), "bars": out, "daily": dl, "pc": (pc or [None])[0]}


# ----------------------------------------------------------------------------- notes
def _notes_path(folder):
    return os.path.join(BT_DIR, folder, "notes.json")


def _notes_migrate(c, folder):
    """3.14: an old backtest/<folder>/notes.json goes into Turso once (the file is renamed .migrated)."""
    p = _notes_path(folder)
    old = _jload(p, None) if os.path.isfile(p) else None
    if not old:
        return
    c.batch([("INSERT OR REPLACE INTO bt_notes (folder, k, v) VALUES (?,?,?)", (folder, k, json.dumps(v)))
             for k, v in old.items()] or [], atomic=True)
    try:
        os.replace(p, p + ".migrated")
    except OSError:
        pass


def notes_get(folder, tk, day):
    c = _cloud()
    if c is not None:
        _notes_migrate(c, folder)
        rows = c.execute("SELECT v FROM bt_notes WHERE folder=? AND k=?", (folder, f"{tk}|{day}"))
        return json.loads(rows[0][0]) if rows else {"verdict": "", "notes": []}
    return _jload(_notes_path(folder), {}).get(f"{tk}|{day}", {"verdict": "", "notes": []})


def notes_all(folder):
    c = _cloud()
    if c is not None:
        _notes_migrate(c, folder)
        return {k: json.loads(v) for k, v in c.execute("SELECT k, v FROM bt_notes WHERE folder=?", (folder,))}
    return _jload(_notes_path(folder), {})


def notes_save(folder, tk, day, verdict=None, text=None, px=None, hms=None, nid=None, delete=False):
    c = _cloud()
    key = f"{tk}|{day}"
    if c is not None:
        _notes_migrate(c, folder)
        rows = c.execute("SELECT v FROM bt_notes WHERE folder=? AND k=?", (folder, key))
        n = json.loads(rows[0][0]) if rows else None
    else:
        n = _jload(_notes_path(folder), {}).get(key)
    n = n or {"verdict": "", "notes": []}
    if verdict is not None:
        n["verdict"] = str(verdict)[:40]
    if delete and nid:
        n["notes"] = [x for x in n["notes"] if x.get("id") != nid]
    elif text:
        now = datetime.now(ET).strftime("%m-%d %H:%M")
        if nid:
            for x in n["notes"]:
                if x.get("id") == nid:
                    x.update({"text": str(text)[:4000], "saved": now})
        else:
            n["notes"].append({"id": f"{int(time.time() * 1000):x}", "text": str(text)[:4000], "px": px, "hms": hms or "",
                               "saved": now})
    _notes_put(folder, key, n, c)
    return n


def _notes_put(folder, key, n, c=None):
    """Write one ticker-day's verdict + notes (an empty one is removed)."""
    empty = not n.get("verdict") and not n.get("notes")
    if c is not None:
        if empty:
            c.execute("DELETE FROM bt_notes WHERE folder=? AND k=?", (folder, key))
        else:
            c.execute("INSERT OR REPLACE INTO bt_notes (folder, k, v) VALUES (?,?,?)", (folder, key, json.dumps(n)))
        return
    allv = _jload(_notes_path(folder), {})
    if empty:
        allv.pop(key, None)
    else:
        allv[key] = n
    _jsave(_notes_path(folder), allv)


def verdicts_all():
    """3.14 Notes tab: {"TK|day": [(strategy folder, verdict)]} of every strategy (one query with Turso)."""
    out = {}
    c = _cloud()
    if c is not None:
        try:
            for folder, k, v in c.execute("SELECT folder, k, v FROM bt_notes"):
                vd = (json.loads(v or "{}") or {}).get("verdict") or ""
                if vd:
                    out.setdefault(k, []).append((folder, vd))
            return out
        except Exception:
            pass
    for s in BUILTIN:
        for k, n in _jload(_notes_path(s["folder"]), {}).items():
            if (n or {}).get("verdict"):
                out.setdefault(k, []).append((s["folder"], n["verdict"]))
    return out


def trades_for(keys):
    """3.14 Notes tab: {"TK|day": [trade rows + "folder"]} - the backtest trades of these ticker-days (every strategy's run)."""
    import io
    keys = set(keys)
    out = {}
    texts = []
    c = _cloud()
    if c is not None:
        try:
            texts += [(f, t) for f, t in c.execute("SELECT folder, csv FROM bt_trades")]
        except Exception:
            pass
    try:
        for f in os.listdir(BT_DIR):
            root = os.path.join(BT_DIR, f, "runs")
            for rid in (os.listdir(root) if os.path.isdir(root) else []):
                p = os.path.join(root, rid, "trades.csv")
                if os.path.isfile(p) and not os.path.isfile(os.path.join(root, rid, ".uploaded")):
                    with open(p, encoding="utf-8", newline="") as fh:
                        texts.append((f, fh.read()))
    except OSError:
        pass
    seen = set()
    for folder, text in texts:
        for r in csv.DictReader(io.StringIO(text or "")):
            k = f"{r.get('tk')}|{r.get('day')}"
            sig = (folder, k, r.get("entry_hms"), r.get("setup"))
            if k in keys and sig not in seen:
                seen.add(sig)
                r["folder"] = folder
                for kk in ("entry", "stop", "exit", "pnl"):
                    try:
                        r[kk] = float(r[kk])
                    except (TypeError, ValueError):
                        r[kk] = None
                out.setdefault(k, []).append(r)
    return out


def notes_move(folder, store):
    """3.14: this strategy's chart notes move to the shared chart notes (core/data/chart_notes.py: the live chart and
    every backtest chart of the ticker-day show them). The verdicts stay here, per strategy. A note is removed from here
    only after the chart notes have it (on this PC at once; Turso in the background). Returns how many notes moved."""
    c = _cloud()
    moved = 0
    for key, n in notes_all(folder).items():
        if not n.get("notes"):
            continue
        tk, _, day = key.partition("|")
        try:
            moved += store.import_old(tk, day, n["notes"])
        except ValueError:                               # not a ticker-day key: left where it is
            continue
        _notes_put(folder, key, {"verdict": n.get("verdict", ""), "notes": []}, c)
    return moved


# ----------------------------------------------------------------------------- the run (worker process)
_CB = None
_CUSTOM = None
_JOB = None


def _init(job):
    """Pool worker start: load the engines once and set the run's costs."""
    global _CB, _CUSTOM, _JOB
    _JOB = job
    sys.path.insert(0, BASE)
    st = job["strat"]
    if st["engine"] == "custom":
        _CUSTOM = _load_file("bt_custom_" + st["folder"], os.path.join(BT_DIR, st["folder"], "strategy.py"))
        return
    _stub_plotly()
    _CB = _mod("lh_combined_backtester")
    _mod("lh_vault_bars")
    if getattr(_CB, "_JR", None) is None:            # in the .exe the strategy files are inside the program
        try:
            _CB._JR = _mod("jay_read_short")
            _CB._SQ = _mod("max_squeeze_short")
        except Exception:
            pass
    _CB.VAULT_DB = job["vault"]
    _CB.LOCATE_FEE_PCT = float(job["cfg"]["locate"])
    _CB.SLIPPAGE_PCT = float(job["cfg"]["slip"])
    _CB.SHORT_STRATEGY = "jay_read_2" if st["match"] in ("jr2", "jr2long") else "jay_read"   # 3.13.0
    if st["match"] in ("jr2", "jr2long") and getattr(_CB, "_JR2", None) is None:
        try:
            _CB._JR2 = _mod("jay_read_2_short")
        except Exception:
            pass
    _CB.SQUEEZE_ENABLED = st["match"] not in ("jr", "jrlong", "jr2", "jr2long")       # 3.12.2: Jay-read alone, as the live bot trades it now
    if st["engine"] == "combined_long":
        _CB.LONG_ENABLED, _CB.SHORT_ENABLED = True, False
    elif st["engine"] == "combined_all":
        _CB.LONG_ENABLED, _CB.SHORT_ENABLED = True, True
    else:
        _CB.LONG_ENABLED, _CB.SHORT_ENABLED = False, True


def _hms(ts):
    return datetime.fromtimestamp(int(ts), ET).strftime("%H:%M:%S") if ts else ""


def _one(td):
    tk, day = td
    st = _JOB["strat"]
    try:
        if st["engine"] == "custom":
            vault = _mod("lh_vault_bars").open_vault(_JOB["vault"], near=BASE)
            df1, pc, _df10 = vault.load_day(tk, day)
            if df1 is None or df1.empty:
                return tk, day, "missing", []
            raw = _CUSTOM.run_day(tk, day, df1, pc, dict(_JOB["cfg"])) or []
            out = []
            for t in raw:
                out.append({"tk": tk, "day": day, "side": t.get("side", st["side"]), "setup": t.get("setup", st["name"]),
                            "entry_hms": t.get("entry_hms", ""), "entry": float(t["entry"]), "stop": float(t.get("stop") or 0),
                            "exit_hms": t.get("exit_hms", ""), "exit": float(t["exit"]), "result": t.get("result", ""),
                            "ret_pct": float(t["ret_pct"]), "R": t.get("R"), "note": t.get("note", "")})
            return tk, day, "ok", out
        r = _CB.run_day(tk, datetime.strptime(day, "%Y-%m-%d").date(), vault=_CB.open_vault(_JOB["vault"]))
        out = []
        for t in r.trades:
            setup = str(t.get("setup") or "")
            m = st["match"]
            if m == "jr" and not setup.startswith("Jay-read"):
                continue
            if m == "sq" and setup != "Max squeeze short":
                continue
            if m == "jr2" and not setup.startswith("JR2"):
                continue
            if m == "jr2long" and setup == "Max squeeze short":
                continue
            if m == "jrlong" and setup == "Max squeeze short":
                continue
            if m == "jrsq" and not (setup.startswith("Jay-read") or setup == "Max squeeze short"):
                continue
            legs = t.get("legs") or [{}]
            xs = sum(lg.get("frac", 0) for lg in legs) or 1.0
            exit_px = sum(lg.get("px", 0) * lg.get("frac", 0) for lg in legs) / xs
            out.append({"tk": tk, "day": day, "side": "Short" if t["side"] != _CB.LONG_SIDE else "Long", "setup": setup,
                        "entry_hms": _hms(t["entry_ts"]), "entry": float(t["entry"]), "stop": float(t.get("stop") or 0),
                        "exit_hms": _hms(legs[-1].get("ts")), "exit": float(exit_px), "result": str(t.get("result") or ""),
                        "ret_pct": float(t["ret_pct"]), "R": float(t.get("R") or 0), "note": str(t.get("note") or "")[:300]})
        return tk, day, "ok", out
    except Exception as exc:
        name = exc.__class__.__name__
        return tk, day, ("missing" if name == "MissingFromVault" else "error:" + str(exc)[:120]), []


def _secs(hms):
    try:
        h, m, x = (str(hms or "0:0:0") + ":0:0").split(":")[:3]
        return int(h) * 3600 + int(m) * 60 + int(float(x))
    except ValueError:
        return 0


def size_trades(trades, cfg):
    """3.12.2: every trade's $ P&L the way the live bot sizes it - a compounding account that starts at start_bal; each
    trade = comp_pct% (20) of the balance at its entry, capped at comp_max ($50k) for shorts and comp_max_long ($10k) for
    longs, and never more than the cash not already in open trades (overlapping trades share the account). P&L is
    booked into the balance when the trade exits."""
    pct = float(cfg.get("comp_pct") or 20) / 100.0
    cap_s, cap_l = float(cfg.get("comp_max") or 50000), float(cfg.get("comp_max_long") or 10000)
    eq = float(cfg.get("start_bal") or 10000)
    tr = sorted(trades, key=lambda t: (t["day"], _secs(t["entry_hms"])))
    open_ = []                                      # (exit key, size, trade)
    curve = []

    def close_until(key):
        nonlocal eq
        for o in sorted([o for o in open_ if o[0] <= key], key=lambda o: o[0]):
            open_.remove(o)
            eq += o[2]["pnl"]
            curve.append(round(eq))

    for t in tr:
        ent = (t["day"], _secs(t["entry_hms"]))
        close_until(ent)
        used = sum(o[1] for o in open_)
        cap = cap_l if t.get("side") == "Long" else cap_s
        size = max(0.0, min(eq * pct, cap, eq - used))
        t["size"] = round(size, 2)
        t["pnl"] = round(size * t["ret_pct"] / 100.0, 2)
        xs = _secs(t["exit_hms"]) if t.get("exit_hms") else 86399
        open_.append(((t["day"], max(xs, ent[1])), size, t))
    close_until(("9999-99-99", 0))
    return tr, round(eq), curve


def stats(trades, cfg):
    tr, end_bal, curve = size_trades(trades, cfg)

    def block(g):
        p = [t["pnl"] for t in g]
        if not p:
            return {"n": 0, "win": None, "pnl": 0, "pf": None, "no5": 0, "dd": 0, "avg": None}
        w, l = sum(x for x in p if x > 0), -sum(x for x in p if x < 0)
        cum = peak = dd = 0.0
        for x in p:
            cum += x
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        return {"n": len(p), "win": round(100.0 * sum(1 for x in p if x > 0) / len(p), 1), "pnl": round(sum(p)),
                "pf": round(w / l, 2) if l else None, "no5": round(sum(p) - sum(sorted(p)[-5:])), "dd": round(dd),
                "avg": round(sum(p) / len(p))}

    tot = block(tr)
    peak, mdd = float(cfg.get("start_bal") or 10000), 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak if peak else 0)
    tot["comp_end"], tot["comp_dd_pct"] = end_bal, round(100 * mdd, 1)
    days = sorted({t["day"] for t in tr})
    cut = days[len(days) // 2] if days else ""
    lo_cfg = cfg.get("from") or (days[0] if days else "")
    hi_cfg = cfg.get("to") or (days[-1] if days else "")
    try:
        a, b = datetime.strptime(lo_cfg, "%Y-%m-%d"), datetime.strptime(hi_cfg, "%Y-%m-%d")
        cut = (a + (b - a) / 2).strftime("%Y-%m-%d")
    except ValueError:
        pass
    h1 = block([t for t in tr if t["day"] < cut])
    h2 = block([t for t in tr if t["day"] >= cut])
    h1["name"], h2["name"] = f"In-sample (to {cut})", f"Out-of-sample (from {cut})"

    def by(keyf, order=None):
        groups = {}
        for t in tr:
            groups.setdefault(keyf(t), []).append(t)
        keys = order or sorted(groups)
        return [dict(block(groups[k]), name=k) for k in keys if k in groups]

    def band(px):
        return "<$1" if px < 1 else "$1-2" if px < 2 else "$2-5" if px < 5 else "$5-10" if px < 10 else "$10+"

    cum, eqline = 0.0, []
    for t in tr:
        cum += t["pnl"]
        eqline.append(round(cum))
    return {"tot": tot, "halves": [h1, h2], "cut": cut,
            "by": {"setup": by(lambda t: t["setup"]), "hour": by(lambda t: (t["entry_hms"] or "??")[:2] + ":00"),
                   "month": by(lambda t: t["day"][:7]),
                   "price": by(lambda t: band(t["entry"]), ["<$1", "$1-2", "$2-5", "$5-10", "$10+"]),
                   "result": by(lambda t: t["result"] or "-")},
            "eq": eqline, "eqc": curve}


# ----------------------------------------------------------------------------- 3.12.2: saved results per ticker-day
# A strategy's trades on a past ticker-day never change while its code and costs stay the same, so each run saves them in
# backtest/<strategy>/cache.json and the next run only backtests the days that are not in it yet (the new vault days).
# The fingerprint covers the strategy's code files, the shared engine files, the costs and the vault: change any of them
# and the whole cache is thrown away, so the run is a full one again. Missing / error days are never saved.
# Delete cache.json to force a full run.
_ENGINE_FILES = ("_shared/lh_combined_backtester.py", "_shared/lh_vault_bars.py", "jay_read_short/jay_read_short.py",
                 "jay_read_2/jay_read_2_short.py",
                 "max_squeeze_short/max_squeeze_short.py", "premarket_long/lh_long_premarket.py")
_CACHE_SKIP = ("from", "to", "days", "list", "procs", "usd", "comp_pct", "comp_max", "start_bal")   # selection / sizing only


def _fingerprint(job):
    st, cfg = job["strat"], job["cfg"]
    h = hashlib.sha256()
    files = [f"{st['folder']}/strategy.py"] if st["engine"] == "custom" else list(_ENGINE_FILES)
    if st["engine"] == "custom":
        files += ["_shared/lh_vault_bars.py"]
    for rel in files:
        f = os.path.join(BT_DIR, *rel.split("/"))
        h.update(rel.encode())
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"-")
    h.update(json.dumps({k: v for k, v in sorted(cfg.items()) if k not in _CACHE_SKIP}, sort_keys=True).encode())
    h.update(json.dumps([st["engine"], st["match"], os.path.basename(job["vault"] or ""), "jr-alone-1"]).encode())
    return h.hexdigest()[:24]


def _cache_path(folder):
    return os.path.join(BT_DIR, folder, "cache.json")


def _cache_load(job):
    fp = _fingerprint(job)
    folder = job["strat"]["folder"]
    cl = _cloud()
    if cl is not None:                                  # 3.14: the saved days are shared between your PCs
        c = cl.kv_get("btcache", folder, None)
        if c is None and os.path.isfile(_cache_path(folder)):
            c = _jload(_cache_path(folder), None)
    else:
        c = _jload(_cache_path(folder), None)
    if not isinstance(c, dict) or c.get("fp") != fp:
        return {"fp": fp, "days": {}}
    c.setdefault("days", {})
    return c



def run_job(job_path):
    """The worker process: every ticker-day of the job, results written to the run folder."""
    job = _jload(job_path, None)
    out_dir = os.path.dirname(job_path)
    prog = os.path.join(out_dir, "progress.json")
    t0 = time.time()
    try:
        days = [tuple(x) for x in job["days"]]
        total = len(days)
        _jsave(prog, {"state": "running", "done": 0, "total": total, "trades": 0, "t0": t0})
        trades, miss, errs, done = [], 0, [], 0
        cache = _cache_load(job)
        cdays = cache["days"]
        todo = []
        for tk, day in days:                               # saved days: their trades come from the cache
            hit = cdays.get(f"{tk}|{day}")
            if hit is None:
                todo.append((tk, day))
            else:
                trades.extend(hit)
                done += 1
        cached = done
        _jsave(prog, {"state": "running", "done": done, "total": total, "trades": len(trades), "t0": t0, "cached": cached})
        days = todo
        procs = int(job["cfg"].get("procs") or 0) or max(1, min(6, (os.cpu_count() or 2) - 2))
        stop_flag = os.path.join(out_dir, "STOP")
        if procs <= 1 or len(days) < 20:
            _init(job)
            it = map(_one, days)
            pool = None
        else:
            import multiprocessing as mp
            try:                                         # 3.12.2: the app starts this process as a daemon (so it ends with
                mp.current_process()._config["daemon"] = False   # the app); a daemon may not start the worker pool
            except Exception:
                pass
            pool = mp.get_context("spawn").Pool(procs, initializer=_init, initargs=(job,))
            it = pool.imap_unordered(_one, days, chunksize=8)
        last = 0.0
        for tk, day, st, tr in it:
            done += 1
            if st == "missing":
                miss += 1
            elif st.startswith("error"):
                errs.append(f"{tk} {day}: {st[6:]}")
            trades.extend(tr)
            if st == "ok":
                cdays[f"{tk}|{day}"] = tr
            if time.time() - last > 1.0 or done == total:
                last = time.time()
                _jsave(prog, {"state": "running", "done": done, "total": total, "trades": len(trades), "t0": t0,
                              "missing": miss, "errors": len(errs)})
            if os.path.exists(stop_flag):
                break
        if pool is not None:
            pool.terminate()
        stopped = os.path.exists(stop_flag)
        try:
            cl = _cloud()
            if cl is not None:
                cl.kv_put("btcache", job["strat"]["folder"], cache)
                try:
                    os.remove(_cache_path(job["strat"]["folder"]))   # the old local copy is in Turso now
                except OSError:
                    pass
            else:
                _jsave(_cache_path(job["strat"]["folder"]), cache)
        except Exception:
            pass
        sm = stats(trades, job["cfg"])
        sm.update({"days_run": done, "days_total": total, "missing": miss, "errors": errs[:50],
                   "secs": round(time.time() - t0, 1), "stopped": stopped,
                   "cached": cached, "new_days": done - cached, "updated": datetime.now(ET).strftime("%Y-%m-%d %H:%M")})
        cols = ["tk", "day", "side", "setup", "entry_hms", "entry", "stop", "exit_hms", "exit", "result", "ret_pct", "size", "pnl",
                "R", "note"]
        with open(os.path.join(out_dir, "trades.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for t in sorted(trades, key=lambda t: (t["day"], t["entry_hms"])):
                w.writerow(t)
        _jsave(os.path.join(out_dir, "summary.json"), sm)
        _jsave(prog, {"state": "stopped" if stopped else "done", "done": done, "total": total, "trades": len(trades),
                      "t0": t0, "secs": round(time.time() - t0, 1), "missing": miss, "errors": len(errs)})
        try:                                               # 3.14: the finished run goes to Turso (list_runs retries if this fails)
            _up_run(job["strat"]["folder"], os.path.basename(out_dir))
        except Exception:
            pass
    except Exception as exc:
        _jsave(prog, {"state": "error", "error": f"{exc.__class__.__name__}: {exc}", "trace": traceback.format_exc()[-2000:],
                      "t0": t0})


def main_run(folder):
    """3.14: a strategy has ONE run. Its row (list_runs format) or None."""
    runs = list_runs(folder)
    return runs[0] if runs else None


def pending(k, favorites=()):
    """(ticker-days of the vault the run has not covered yet, all ticker-days of its settings) - exact: asks the saved
    per-day results. A changed strategy file makes every day new (the saved results no longer fit)."""
    st = strat(k)
    old = main_run(st["folder"]) if st else None
    if not old or old["state"] == "running":
        return 0, 0
    c = dict(DEFAULT_CFG)
    c.update(old["cfg"] or {})
    vault = settings().get("vault") or ""
    days = day_list(vault, c, favorites)
    cache = _cache_load({"strat": st, "cfg": c, "vault": vault})
    have = cache["days"]
    return sum(1 for tk, d in days if f"{tk}|{d}" not in have), len(days)


def cards(favorites=()):
    """3.14: the Backtest page - every strategy with its one run and how many new vault days wait for it."""
    out = strategies()
    try:
        vault = settings().get("vault") or ""
    except Exception:
        vault = ""
    for s in out:
        s["new_days"] = None
        r = s.get("last")
        if r and r.get("state") in ("done", "stopped") and r.get("days_total") is not None and vault:
            try:
                c = dict(DEFAULT_CFG)
                c.update(r["cfg"] or {})
                s["new_days"] = max(0, len(day_list(vault, c, favorites)) - int(r["days_total"]))
            except Exception:
                pass
    return out


def new_job(k, cfg, favorites=(), update=False):
    """Write the job (run folder + job.json). Returns (job_path, run_id, n_days). Runs nothing.
    3.14: a strategy has one run. update=False creates it (refused if it exists); update=True runs the SAME run again with
    its saved settings: the saved per-day results are reused, only the new vault days are run, and the run is replaced."""
    st = strat(k)
    if st is None:
        raise RuntimeError("Unknown strategy")
    s = settings()
    vault = s.get("vault") or ""
    old = main_run(st["folder"])
    if update:
        if not old or old["state"] not in ("done", "stopped"):
            raise RuntimeError("This strategy has no finished run to update - run it once first")
        cfg = old["cfg"]
        rid = old["id"]
    else:
        if old:
            raise RuntimeError("This strategy already has its run - it updates itself (or delete the run to start over)")
        rid = datetime.now(ET).strftime("%Y%m%d-%H%M%S")
    c = dict(DEFAULT_CFG)
    c.update({kk: v for kk, v in (cfg or {}).items() if kk in DEFAULT_CFG})
    for kk in ("locate", "slip", "comp_pct", "comp_max", "comp_max_long", "start_bal"):
        c[kk] = float(c[kk])
    days = day_list(vault, c, favorites)
    if not days:
        raise RuntimeError("No vault days match these settings")
    out = os.path.join(BT_DIR, st["folder"], "runs", rid)
    if os.path.isdir(out):                              # an update starts clean (the old result stays in Turso until the new one replaces it)
        _rmtree_hard(out)
    os.makedirs(out, exist_ok=True)
    job = {"strat": st, "cfg": c, "vault": vault, "days": days, "created": rid, "note": "", "update": bool(update)}
    path = os.path.join(out, "job.json")
    _jsave(path, job)
    if not update:
        save_settings(last_cfg=c)
    return path, rid, len(days)


def _trade_keys(text):
    import io
    return {f"{r.get('tk')}|{r.get('day')}" for r in csv.DictReader(io.StringIO(text or ""))}


def _orphan_note_keys(c, folder, rid, root):
    """Notes that belong only to the run being deleted: the ticker-days of its trades that no other run of the strategy
    has (a note shown in another run stays - notes are per strategy and ticker-day)."""
    def local(r):
        try:
            with open(os.path.join(root, r, "trades.csv"), encoding="utf-8", newline="") as fh:
                return fh.read()
        except OSError:
            return ""
    mine = _trade_keys(local(rid))
    others = set()
    if c is not None:
        row = c.execute("SELECT csv FROM bt_trades WHERE folder=? AND rid=?", (folder, rid))
        mine |= _trade_keys(row[0][0] if row else "")
        for (t,) in c.execute("SELECT csv FROM bt_trades WHERE folder=? AND rid<>?", (folder, rid)):
            others |= _trade_keys(t)
    try:
        for r in os.listdir(root):
            if r != rid:
                others |= _trade_keys(local(r))
    except OSError:
        pass
    have = set(notes_all(folder))
    return sorted((mine - others) & have)


def delete_run(folder, rid):
    """3.13.1: remove one run folder (backtest/<strategy>/runs/<id>). Only a name like 20261031-175743 inside that
    strategy's runs folder; a run that is still going is not removed."""
    import re
    import shutil
    if not re.fullmatch(r"\d{8}-\d{6}", str(rid or "")) or not re.fullmatch(r"[A-Za-z0-9_]+", str(folder or "")):
        raise RuntimeError("not a run")
    root = os.path.realpath(os.path.join(BT_DIR, folder, "runs"))
    d = os.path.realpath(os.path.join(root, rid))
    if os.path.dirname(d) != root:
        raise RuntimeError("run not found")
    here = os.path.isdir(d)
    if here and (_jload(os.path.join(d, "progress.json"), {}) or {}).get("state") == "running" and \
            time.time() - os.path.getmtime(os.path.join(d, "progress.json")) < 120:
        raise RuntimeError("this run is still going - stop it first")
    c = _cloud()
    gone = False
    orphans = _orphan_note_keys(c, folder, rid, root)
    if c is not None:                                    # 3.14: the run, its trades, its row and its notes leave the database too
        c.batch([("DELETE FROM bt_trades WHERE folder=? AND rid=?", (folder, rid)),
                 ("DELETE FROM bt_runs WHERE folder=? AND rid=?", (folder, rid))] +
                [("DELETE FROM bt_notes WHERE folder=? AND k=?", (folder, k)) for k in orphans], atomic=True)
        gone = True
    elif orphans:
        allv = _jload(_notes_path(folder), {})
        for k in orphans:
            allv.pop(k, None)
        _jsave(_notes_path(folder), allv)
    if here:
        _rmtree_hard(d)
        if os.path.exists(d):
            raise RuntimeError("could not remove the run folder (a file is open or OneDrive is syncing it) - try again")
        gone = True
    if not gone:
        raise RuntimeError("run not found")
    return True


def _rmtree_hard(d):
    """Remove a folder even when a file is read-only or briefly locked (Windows / OneDrive): retry, then rename away."""
    import shutil
    import stat

    def _onerr(fn, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        except OSError:
            pass
    for _ in range(5):
        shutil.rmtree(d, onerror=_onerr)
        if not os.path.exists(d):
            return
        time.sleep(0.3)
    try:                                           # still there: move it out of the runs list, delete what we can later
        os.rename(d, d + ".deleted")
        shutil.rmtree(d + ".deleted", ignore_errors=True)
    except OSError:
        pass


def result(folder, rid, limit=5000):
    import io
    d = os.path.join(BT_DIR, folder, "runs", rid)
    sm = _jload(os.path.join(d, "summary.json"), None)
    job_cfg = _jload(os.path.join(d, "job.json"), {}).get("cfg", {})
    prog = _jload(os.path.join(d, "progress.json"), {})
    text = None
    try:
        with open(os.path.join(d, "trades.csv"), encoding="utf-8", newline="") as fh:
            text = fh.read()
    except OSError:
        pass
    c = _cloud()
    if c is not None and (text is None or sm is None):               # 3.14: the run lives in Turso
        rows = c.execute("SELECT r.job, r.progress, r.summary, t.csv FROM bt_runs r LEFT JOIN bt_trades t "
                         "ON t.folder=r.folder AND t.rid=r.rid WHERE r.folder=? AND r.rid=?", (folder, rid))
        if rows:
            j, p, s, tcsv = rows[0]
            sm = json.loads(s or "null")
            job_cfg = json.loads(j or "{}").get("cfg", {})
            prog = json.loads(p or "{}")
            text = tcsv or ""
    trades = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text or ""))):
        if i >= limit:
            break
        for kk in ("entry", "stop", "exit", "ret_pct", "pnl"):
            try:
                r[kk] = float(r[kk])
            except (TypeError, ValueError):
                r[kk] = None
        trades.append(r)
    nts = notes_all(folder)
    for t in trades:
        n = nts.get(f"{t['tk']}|{t['day']}")
        t["verdict"] = (n or {}).get("verdict", "")
        t["nnote"] = len((n or {}).get("notes", []))
        t["note1"] = ((n or {}).get("notes") or [{}])[-1].get("text", "")[:120] if n and n.get("notes") else ""
    return {"summary": sm, "trades": trades, "job": job_cfg, "progress": prog}


if __name__ == "__main__":                              # python lh_backtest.py <job.json>  (manual / debugging)
    import multiprocessing as _mp
    _mp.freeze_support()
    if len(sys.argv) > 1:
        run_job(sys.argv[1])
