# -*- coding: utf-8 -*-
"""Kestrel - the daily vault feed (3.12.1, 2026-10-31).

The bot keeps its OWN list of the ticker-days it looked at (a separate memory: vault_queue.json in the app data folder;
it never touches the watchlist, favorites or anything else):

    shorts  every symbol the bot monitored that day - the watchlist you keep, the ones you add, the scanner's
            auto-adds - recorded with the date (1-minute bars + the prior close + 2 years of daily history)
    longs   ONLY the premarket-long tickers that actually traded (from long_bot_trades.csv) - also their 10-second bars

The next time the bot runs on a later day it fetches those days from IB into the data vault (market_data_vault.db,
through ib_data_vault.py from the vault folder - the same code as "python ib_data_vault.py --list ..."), in a separate
process with its own IB client id (read-only: it only requests historical bars). Days the vault already has are skipped.
When a day is done it is removed from the queue - so the loop goes on every day and no day is missed.
"""
import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from datetime import date, datetime

FEED_CLIENT_ID = 82                    # its own IB client id (the bot uses IB_CLIENT_ID; research scripts use 81)
_LOCK = threading.Lock()


def queue_path(data_dir):
    return os.path.join(data_dir, "vault_queue.json")


def _cloud():
    try:
        import turso
        return turso.cloud()
    except Exception:
        return None


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            q = json.load(fh)
        return q if isinstance(q, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, q):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(q, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


# 3.14: the queue (day -> {ticker: why}) lives in Turso (kv 'vault_queue', one row per day), so every PC feeds the same
# list. vault_queue.json is only read once, to carry an old queue into the database.
def _qload(data_dir):
    c = _cloud()
    if c is None:
        return _load(queue_path(data_dir))
    try:
        q = c.kv_all("vault_queue")
        old = queue_path(data_dir)
        if os.path.isfile(old):
            for day, syms in _load(old).items():
                q.setdefault(day, {}).update({s: v for s, v in syms.items() if s not in q.get(day, {})})
            _qsave(data_dir, q)
            os.replace(old, old + ".migrated")
        return q
    except Exception:
        return _load(queue_path(data_dir))


def _qsave(data_dir, q):
    c = _cloud()
    if c is None:
        _save(queue_path(data_dir), q)
        return
    try:
        cur = c.kv_all("vault_queue")
        for day, syms in q.items():
            if cur.get(day) != syms:
                c.kv_put("vault_queue", day, syms)
        for day in cur:
            if day not in q:
                c.kv_del("vault_queue", day)
    except Exception:
        _save(queue_path(data_dir), q)


def record(data_dir, day, syms, why="monitored"):
    """Add ticker-days to the queue (idempotent). day = 'YYYY-MM-DD'."""
    syms = [s for s in syms if s]
    if not syms:
        return
    c = _cloud()
    if c is not None:                                    # 3.14: only today's row is read and written
        with _LOCK:
            try:
                d = c.kv_get("vault_queue", str(day), {}) or {}
                new = {s: {"why": why, "t": datetime.now().strftime("%H:%M")} for s in syms if s not in d}
                if new:
                    d.update(new)
                    c.kv_put("vault_queue", str(day), d)
                return
            except Exception:
                pass                                     # Turso not reachable: fall back to the local file below
    with _LOCK:
        q = _load(queue_path(data_dir))
        d = q.setdefault(str(day), {})
        changed = False
        for s in syms:
            if s not in d:
                d[s] = {"why": why, "t": datetime.now().strftime("%H:%M")}
                changed = True
        if changed:
            _qsave(data_dir, q)


def pending_days(data_dir, today):
    return sorted(d for d in _qload(data_dir) if d < str(today))


def summary(data_dir):
    q = _qload(data_dir)
    return {d: len(v) for d, v in sorted(q.items())}


def _long_traded(data_dir, day):
    """Premarket-long tickers that traded that day (long_bot_trades.csv)."""
    import csv
    out = set()
    try:
        with open(os.path.join(data_dir, "long_bot_trades.csv"), encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("date") or "") == day and r.get("symbol"):
                    out.add(str(r["symbol"]).upper())
    except OSError:
        pass
    try:                                                  # 3.14: + the longs another PC traded (Turso journal)
        import turso
        for r in turso.journal_rows("long_bot_trades.csv") or []:
            if str(r.get("date") or "") == day and r.get("symbol"):
                out.add(str(r["symbol"]).upper())
    except Exception:
        pass
    return out


def run_feed(data_dir, vault_path, host, port, days, client_id=FEED_CLIENT_ID):
    """The worker process: fetch the queued days into the vault, then drop them from the queue."""
    status_path = os.path.join(data_dir, "vault_feed_status.json")
    st = {"state": "running", "started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "days": days, "log": []}

    def note(msg):
        st["log"].append(f"{datetime.now():%H:%M:%S} {msg}")
        st["log"] = st["log"][-200:]
        _save(status_path, st)

    try:
        cl = _cloud()
        if cl is not None:                              # 3.14: bring this PC's replica up to date first (skips days already fetched)
            import turso_vault as TV
            note(f"vault replica: {TV.pull(vault_path or TV.default_replica(), note)}")
            vault_path = vault_path or TV.default_replica()
        if not vault_path or not os.path.isfile(vault_path):
            raise RuntimeError(f"vault not found: {vault_path!r} - set it in the Backtest tab")
        vdir = os.path.dirname(os.path.abspath(vault_path))
        f = os.path.join(vdir, "ib_data_vault.py")
        if not os.path.isfile(f):                       # the replica folder has no copy: use the one in the vault folder
            for cand in (os.path.join(os.path.dirname(__file__), "..", "..", "backtest", "_shared", "ib_data_vault.py"),
                         os.path.join(os.path.dirname(__file__), "..", "..", "..", "ib_data_vault", "ib_data_vault.py"),
                         os.path.join(os.path.dirname(__file__), "..", "..", "ib_data_vault.py")):
                if os.path.isfile(cand):
                    f = os.path.abspath(cand)
                    break
        if not os.path.isfile(f):
            raise RuntimeError(f"ib_data_vault.py not found (looked next to the vault: {vdir})")
        spec = importlib.util.spec_from_file_location("ib_data_vault", f)
        V = importlib.util.module_from_spec(spec)
        sys.modules["ib_data_vault"] = V
        spec.loader.exec_module(V)
        vault = V.Vault(vault_path)
        factory = lambda: V.IBFetcher(host=host, port=int(port), client_id=int(client_id))  # noqa: E731
        q = _qload(data_dir)
        for day in days:
            syms = sorted((q.get(day) or {}).keys())
            longs = sorted(_long_traded(data_dir, day))
            dd = datetime.strptime(day, "%Y-%m-%d").date()
            note(f"{day}: {len(syms)} short / watchlist tickers, {len(longs)} traded longs")
            if syms:
                r = V.fetch_list(vault, [(s, dd) for s in syms if s not in longs], factory, need_10s=False)
                note(f"{day}: 1-minute {r}")
            if longs:
                r = V.fetch_list(vault, [(s, dd) for s in longs], factory, need_10s=True)
                note(f"{day}: longs with 10-second bars {r}")
            allj = [(s, dd) for s in sorted(set(syms) | set(longs))]
            if allj and hasattr(V, "fetch_daily_history"):
                try:
                    r = V.fetch_daily_history(vault, allj, factory, years=2)
                    note(f"{day}: daily history {r}")
                except Exception as exc:
                    note(f"{day}: daily history failed: {exc!r}")
            with _LOCK:                                 # the day is done: drop it from the queue (only this list)
                if cl is not None:
                    cl.kv_del("vault_queue", day)
                else:
                    q2 = _load(queue_path(data_dir))
                    q2.pop(day, None)
                    _save(queue_path(data_dir), q2)
            note(f"{day}: done - removed from the queue")
        st["state"] = "done"
    except Exception as exc:
        st["state"] = "error"
        st["error"] = f"{exc.__class__.__name__}: {exc}"
        st["trace"] = traceback.format_exc()[-1500:]
    st["ended"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save(status_path, st)


def day_lists(data_dir, day):
    """(short / watchlist tickers queued for `day`, premarket longs that traded `day`)."""
    q = _qload(data_dir)
    return sorted((q.get(str(day)) or {}).keys()), sorted(_long_traded(data_dir, str(day)))


def discord_text(data_dir, day):
    """The list for Discord: what the vault feed will fetch tomorrow for `day`."""
    shorts, longs = day_lists(data_dir, day)
    lines = [f"Shorts / watchlist ({len(shorts)}) - 1-minute bars:", ", ".join(shorts) if shorts else "none",
             "", f"Premarket longs that traded ({len(longs)}) - 1-minute + 10-second bars:", ", ".join(longs) if longs else "none",
             "", "Fetched into the data vault the next day the bot runs."]
    return "\n".join(lines)


def status(data_dir):
    return _load(os.path.join(data_dir, "vault_feed_status.json"))
