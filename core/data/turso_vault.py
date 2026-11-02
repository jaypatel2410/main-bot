#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The data vault in Turso (3.14).

Turso is the home of the vault: ib_data_vault.py pushes every ticker-day it fetches (push_day / push_hist, called by the
Vault class), and every PC keeps a local READ replica (market_data_vault.db) that is filled from Turso (pull). The
backtests and the chart read the replica exactly as before - it is only a cache you can delete and pull again.

    python turso_vault.py upload --db C:\\...\\ib_data_vault\\market_data_vault.db   one time: copy the vault into Turso (resumable)
    python turso_vault.py pull   [--db <replica>]     bring this PC's replica up to date (first run = everything)
    python turso_vault.py status [--db <replica>]     rows in Turso vs the local file
(without --db: %LOCALAPPDATA%\\LHShortBot\\vault\\market_data_vault.db)

Credentials: TURSO_DATABASE_URL / TURSO_AUTH_TOKEN in the bot's .env (or the environment).
The ARCHIVE vault (market_data_vault_ARCHIVE.db, older days) is NOT uploaded: it would add ~4,800 extra days to every
"all vault days" backtest.
"""
import argparse
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import turso  # noqa: E402


def default_replica():
    """This PC's replica: the vault path of the Backtest tab, else <app data>\\vault\\market_data_vault.db."""
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "LHShortBot", "vault", "market_data_vault.db")


DEFAULT_DB = default_replica()
LOCAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS days (ticker TEXT NOT NULL, day TEXT NOT NULL, status_1m TEXT, status_10s TEXT, prior_close REAL,
    prior_volume REAL, n_1m INTEGER DEFAULT 0, n_10s INTEGER DEFAULT 0, first_bar TEXT, last_bar TEXT, day_high REAL,
    day_volume REAL, source TEXT, fetched_at TEXT, note TEXT, PRIMARY KEY (ticker, day));
CREATE TABLE IF NOT EXISTS bars_1m (ticker TEXT NOT NULL, day TEXT NOT NULL, t TEXT NOT NULL, open REAL, high REAL, low REAL,
    close REAL, volume REAL, PRIMARY KEY (ticker, day, t));
CREATE TABLE IF NOT EXISTS bars_10s (ticker TEXT NOT NULL, day TEXT NOT NULL, t TEXT NOT NULL, open REAL, high REAL, low REAL,
    close REAL, volume REAL, PRIMARY KEY (ticker, day, t));
CREATE TABLE IF NOT EXISTS daily (ticker TEXT NOT NULL, day TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
    volume REAL, PRIMARY KEY (ticker, day));
CREATE TABLE IF NOT EXISTS daily_hist (ticker TEXT NOT NULL, day TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,
    volume REAL, PRIMARY KEY (ticker, day));
CREATE TABLE IF NOT EXISTS daily_hist_cover (ticker TEXT PRIMARY KEY, status TEXT, want_start TEXT, want_end TEXT,
    first_day TEXT, last_day TEXT, n INTEGER, fetched_at TEXT, note TEXT);
"""
BAR_COLS = "ticker, day, t, open, high, low, close, volume"
DAY_COLS = ("ticker", "day", "status_1m", "status_10s", "prior_close", "prior_volume", "n_1m", "n_10s", "first_bar", "last_bar",
            "day_high", "day_volume", "source", "fetched_at", "note")
OHLC = "ticker, day, open, high, low, close, volume"
COVER_COLS = ("ticker", "status", "want_start", "want_end", "first_day", "last_day", "n", "fetched_at", "note")
CHUNK = 250                       # rows per INSERT statement


def _cloud():
    return turso.cloud()


def _multi(table, cols, rows):
    """[(sql, args)] : INSERT OR REPLACE of rows in chunks."""
    out = []
    ph = "(" + ",".join("?" * len(cols)) + ")"
    for i in range(0, len(rows), CHUNK):
        part = rows[i:i + CHUNK]
        out.append((f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES " + ",".join([ph] * len(part)),
                    [x for r in part for x in r]))
    return out


# ----------------------------------------------------------------------------- push (local sqlite -> Turso)
def push_day(db, ticker, day, log=True):
    """One ticker-day: the days row, its 1-minute and 10-second bars, the ticker's daily rows. Atomic. False = no Turso."""
    c = _cloud()
    if c is None:
        return False
    day = str(day)
    st = [("DELETE FROM v_bars_1m WHERE ticker=? AND day=?", (ticker, day)),
          ("DELETE FROM v_bars_10s WHERE ticker=? AND day=?", (ticker, day))]
    r = db.execute(f"SELECT {','.join(DAY_COLS)} FROM days WHERE ticker=? AND day=?", (ticker, day)).fetchone()
    if r:
        st += _multi("v_days", DAY_COLS, [r])
    for src, dst in (("bars_1m", "v_bars_1m"), ("bars_10s", "v_bars_10s")):
        rows = db.execute(f"SELECT {BAR_COLS} FROM {src} WHERE ticker=? AND day=? ORDER BY t", (ticker, day)).fetchall()
        st += _multi(dst, BAR_COLS.split(", "), rows)
    rows = db.execute(f"SELECT {OHLC} FROM daily WHERE ticker=?", (ticker,)).fetchall()
    st += _multi("v_daily", OHLC.split(", "), rows)
    if log:
        st.append(("INSERT INTO v_log (ticker, day, kind) VALUES (?,?,'day')", (ticker, day)))
    c.batch(st, atomic=True)
    return True


def push_hist(db, ticker, log=True):
    c = _cloud()
    if c is None:
        return False
    st = [("DELETE FROM v_daily_hist WHERE ticker=?", (ticker,))]
    st += _multi("v_daily_hist", OHLC.split(", "), db.execute(f"SELECT {OHLC} FROM daily_hist WHERE ticker=?", (ticker,)).fetchall())
    cv = db.execute(f"SELECT {','.join(COVER_COLS)} FROM daily_hist_cover WHERE ticker=?", (ticker,)).fetchone()
    if cv:
        st += _multi("v_daily_hist_cover", COVER_COLS, [cv])
    if log:
        st.append(("INSERT INTO v_log (ticker, day, kind) VALUES (?,'','hist')", (ticker,)))
    c.batch(st, atomic=True)
    return True


def upload_all(db_path=DEFAULT_DB, say=print):
    """Copy the whole local vault into Turso. Resumable: ticker-days / histories already there are skipped."""
    c = _cloud()
    if c is None:
        raise SystemExit("Turso is not configured (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN in .env)")
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    have = {(t, d) for t, d in c.execute("SELECT ticker, day FROM v_days")}
    days = db.execute("SELECT ticker, day FROM days ORDER BY day, ticker").fetchall()
    todo = [x for x in days if x not in have]
    say(f"vault days: {len(days):,} local, {len(have):,} already in Turso, {len(todo):,} to upload")
    t0 = time.time()
    for i, (tk, dy) in enumerate(todo, 1):
        for attempt in range(5):
            try:
                push_day(db, tk, dy)
                break
            except turso.TursoError as exc:
                say(f"  {tk} {dy}: {exc} (retry {attempt + 1})")
                time.sleep(3 * (attempt + 1))
        else:
            raise SystemExit(f"stopped at {tk} {dy} - run upload again to continue")
        if i % 100 == 0 or i == len(todo):
            say(f"  {i:,}/{len(todo):,} ticker-days  ({(time.time() - t0) / 60:.1f} min)")
    have_h = {t for (t,) in c.execute("SELECT ticker FROM v_daily_hist_cover")}
    tks = [t for (t,) in db.execute("SELECT ticker FROM daily_hist_cover")]
    todo_h = [t for t in tks if t not in have_h]
    say(f"daily histories: {len(tks):,} local, {len(todo_h):,} to upload")
    for i, tk in enumerate(todo_h, 1):
        push_hist(db, tk)
        if i % 100 == 0 or i == len(todo_h):
            say(f"  {i:,}/{len(todo_h):,} histories")
    top = (c.execute("SELECT MAX(seq) FROM v_log")[0][0]) or 0
    db.close()
    rw = _open_replica(db_path)                    # this file already has everything: later pulls start after what was uploaded
    rw.execute("INSERT OR REPLACE INTO _sync (k, v) VALUES ('seq', ?)", (top,))
    rw.commit()
    rw.close()
    say("upload done")


# ----------------------------------------------------------------------------- pull (Turso -> local replica)
def _open_replica(db_path):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    db = sqlite3.connect(db_path, timeout=30)
    db.executescript(LOCAL_SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS _sync (k TEXT PRIMARY KEY, v INTEGER)")
    db.commit()
    return db


def pull(db_path=DEFAULT_DB, say=None, batch_days=15):
    """Bring the local replica up to date from Turso (first run: everything). Returns (days_pulled, hist_pulled)."""
    c = _cloud()
    if c is None:
        return 0, 0
    say = say or (lambda m: None)
    db = _open_replica(db_path)
    last = (db.execute("SELECT v FROM _sync WHERE k='seq'").fetchone() or (0,))[0]
    log = c.execute("SELECT MAX(seq), ticker, day, kind FROM v_log WHERE seq>? GROUP BY ticker, day, kind ORDER BY 1", (last,))
    if not log:
        return 0, 0
    top = max(r[0] for r in log)
    nd = nh = 0
    days = [(t, d) for _s, t, d, k in log if k == "day"]
    hists = [t for _s, t, _d, k in log if k == "hist"]
    say(f"vault: {len(days):,} ticker-days and {len(hists):,} histories to pull")
    for i in range(0, len(days), batch_days):
        part = days[i:i + batch_days]
        st = []
        for tk, dy in part:
            st += [(f"SELECT {','.join(DAY_COLS)} FROM v_days WHERE ticker=? AND day=?", (tk, dy)),
                   (f"SELECT {BAR_COLS} FROM v_bars_1m WHERE ticker=? AND day=? ORDER BY t", (tk, dy)),
                   (f"SELECT {BAR_COLS} FROM v_bars_10s WHERE ticker=? AND day=? ORDER BY t", (tk, dy)),
                   (f"SELECT {OHLC} FROM v_daily WHERE ticker=?", (tk,))]
        res = c.batch(st)
        for j, (tk, dy) in enumerate(part):
            drow, b1, b10, dl = res[j * 4:j * 4 + 4]
            db.execute("DELETE FROM bars_1m WHERE ticker=? AND day=?", (tk, dy))
            db.execute("DELETE FROM bars_10s WHERE ticker=? AND day=?", (tk, dy))
            db.execute("DELETE FROM days WHERE ticker=? AND day=?", (tk, dy))
            if drow:
                db.executemany(f"INSERT INTO days ({','.join(DAY_COLS)}) VALUES ({','.join('?' * len(DAY_COLS))})", drow)
            db.executemany("INSERT OR REPLACE INTO bars_1m VALUES (?,?,?,?,?,?,?,?)", b1)
            db.executemany("INSERT OR REPLACE INTO bars_10s VALUES (?,?,?,?,?,?,?,?)", b10)
            db.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?)", dl)
            nd += 1
        db.commit()
        if (i // batch_days) % 20 == 0:
            say(f"vault: {min(i + batch_days, len(days)):,}/{len(days):,} ticker-days")
    for tk in hists:
        h, cv = c.batch([(f"SELECT {OHLC} FROM v_daily_hist WHERE ticker=?", (tk,)),
                         (f"SELECT {','.join(COVER_COLS)} FROM v_daily_hist_cover WHERE ticker=?", (tk,))])
        db.execute("DELETE FROM daily_hist WHERE ticker=?", (tk,))
        db.executemany("INSERT OR REPLACE INTO daily_hist VALUES (?,?,?,?,?,?,?)", h)
        db.executemany(f"INSERT OR REPLACE INTO daily_hist_cover VALUES ({','.join('?' * len(COVER_COLS))})", cv)
        nh += 1
    db.execute("INSERT OR REPLACE INTO _sync (k, v) VALUES ('seq', ?)", (top,))
    db.commit()
    db.close()
    return nd, nh


def status(db_path=DEFAULT_DB):
    c = _cloud()
    loc = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) if os.path.isfile(db_path) else None
    for cloud_t, local_t in (("v_days", "days"), ("v_bars_1m", "bars_1m"), ("v_bars_10s", "bars_10s"), ("v_daily", "daily"),
                             ("v_daily_hist", "daily_hist"), ("v_daily_hist_cover", "daily_hist_cover")):
        n = c.execute(f"SELECT COUNT(*) FROM {cloud_t}")[0][0] if c else "-"
        m = loc.execute(f"SELECT COUNT(*) FROM {local_t}").fetchone()[0] if loc else "-"
        print(f"{local_t:<18} turso {n:>10}   local {m:>10}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("upload", "pull", "status"))
    ap.add_argument("--db", default=DEFAULT_DB)
    a = ap.parse_args()
    if a.cmd == "upload":
        upload_all(a.db)
    elif a.cmd == "pull":
        print("pulled (ticker-days, histories):", pull(a.db, print))
    else:
        status(a.db)
