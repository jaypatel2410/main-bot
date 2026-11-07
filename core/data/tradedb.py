# -*- coding: utf-8 -*-
"""Kestrel 3.15 - the trade database: missed signals, health checks, stop checks, daily summaries, locates, events.

The working store is a SQLite file on this PC (trade_db.sqlite in the app data folder) - it works with no keys and the
bot never waits for the network. When TURSO_DATABASE_URL / TURSO_AUTH_TOKEN are in .env, a background thread copies
every new or changed row to Turso (tables tdb_<name>), so every PC sees the same history.
"""
import json
import os
import sqlite3
import threading
import time

TABLES = {
    "missed": ("id TEXT PRIMARY KEY, day TEXT, t INTEGER, sym TEXT, strat TEXT, setup TEXT, side TEXT, px REAL, stop REAL, "
               "qty INTEGER, reason TEXT, cat TEXT, state TEXT, exit_px REAL, exit_t INTEGER, exit_why TEXT, move REAL, "
               "pnl REAL, locate REAL, updated TEXT"),
    "health": "id TEXT PRIMARY KEY, day TEXT, t INTEGER, kind TEXT, ok INTEGER, data TEXT",
    "daily": "day TEXT PRIMARY KEY, data TEXT, updated TEXT",
    "locates": "id TEXT PRIMARY KEY, day TEXT, t INTEGER, sym TEXT, qty INTEGER, px REAL, cost REAL, kind TEXT, by TEXT",
    "events": "id TEXT PRIMARY KEY, day TEXT, t INTEGER, kind TEXT, sym TEXT, text TEXT",
}
KEYS = {"daily": "day"}                              # primary key column (default "id")


class TradeDB:
    def __init__(self, data_dir, log=None):
        self.path = os.path.join(data_dir, "trade_db.sqlite")
        self.log = log
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        for name, cols in TABLES.items():
            self.db.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
        self.db.execute("CREATE TABLE IF NOT EXISTS _outbox (tbl TEXT, k TEXT, PRIMARY KEY (tbl, k))")
        self.db.commit()
        self.cols = {n: [c.split()[0] for c in TABLES[n].split(", ")] for n in TABLES}
        self.wake = threading.Event()
        self.sync_state = "off"
        threading.Thread(target=self._sync_loop, name="tradedb-sync", daemon=True).start()

    # ------------------------------------------------------------------ local (the bot only ever waits on this)
    def put(self, table, row):
        cols = [c for c in self.cols[table] if c in row]
        key = KEYS.get(table, "id")
        with self.lock:
            self.db.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [row[c] for c in cols])
            self.db.execute("INSERT OR IGNORE INTO _outbox (tbl, k) VALUES (?, ?)", (table, str(row[key])))
            self.db.commit()
        self.wake.set()

    def delete(self, table, key):
        k = KEYS.get(table, "id")
        with self.lock:
            self.db.execute(f"DELETE FROM {table} WHERE {k}=?", (key,))
            self.db.execute("INSERT OR IGNORE INTO _outbox (tbl, k) VALUES (?, ?)", (table, str(key)))
            self.db.commit()
        self.wake.set()

    def rows(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]

    def pending(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM _outbox").fetchone()[0]

    # ------------------------------------------------------------------ Turso copy (background)
    def _cloud(self):
        try:
            import turso
            return turso.cloud()
        except Exception:
            return None

    def _sync_loop(self):
        made = False
        while True:
            self.wake.wait(30)
            self.wake.clear()
            c = self._cloud()
            if c is None:
                self.sync_state = "off"
                continue
            try:
                if not made:
                    c.batch([(f"CREATE TABLE IF NOT EXISTS tdb_{n} ({cols})", ()) for n, cols in TABLES.items()])
                    made = True
                with self.lock:
                    todo = self.db.execute("SELECT tbl, k FROM _outbox LIMIT 200").fetchall()
                stmts = []
                for tbl, k in todo:
                    key = KEYS.get(tbl, "id")
                    with self.lock:
                        r = self.db.execute(f"SELECT {', '.join(self.cols[tbl])} FROM {tbl} WHERE {key}=?", (k,)).fetchone()
                    if r is None:
                        stmts.append((f"DELETE FROM tdb_{tbl} WHERE {key}=?", (k,)))
                    else:
                        stmts.append((f"INSERT OR REPLACE INTO tdb_{tbl} ({', '.join(self.cols[tbl])}) VALUES "
                                      f"({', '.join('?' * len(r))})", tuple(r)))
                if stmts:
                    c.batch(stmts, atomic=True)
                    with self.lock:
                        self.db.executemany("DELETE FROM _outbox WHERE tbl=? AND k=?", todo)
                        self.db.commit()
                self.sync_state = "on"
                if len(todo) == 200:
                    self.wake.set()                          # more waiting
            except Exception as exc:
                self.sync_state = "error"
                if self.log is not None:
                    self.log.warning("trade database sync: %r", exc)
                time.sleep(10)


_DB = None
_DB_LOCK = threading.Lock()


def get(data_dir, log=None):
    global _DB
    with _DB_LOCK:
        if _DB is None:
            _DB = TradeDB(data_dir, log)
        return _DB


def dumps(obj):
    return json.dumps(obj, default=str)
