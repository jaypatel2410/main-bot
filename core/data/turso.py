# -*- coding: utf-8 -*-
"""LH Short Bot 3.14 - the cloud database (Turso / libSQL over HTTPS, no extra package needed).

Everything that used to live in files on this PC and that you want on every PC lives here: settings (favorites,
watchlist, layout, hotkeys, colors ...), backtest runs + trades + your notes, the trade journals, the vault feed queue
and the data vault itself (bars). Credentials come from the .env file (or the environment):

    TURSO_DATABASE_URL=libsql://your-db-name-yourorg.turso.io
    TURSO_AUTH_TOKEN=...

TURSO_DATABASE_URL may also be file:C:\\path\\test.db (a plain SQLite file: tests / a dry run without the network).
Without credentials every function here does nothing (configured() is False) and the callers keep their old local files.
"""
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS kv (ns TEXT NOT NULL, k TEXT NOT NULL, v TEXT, updated TEXT, PRIMARY KEY (ns, k)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS bt_runs (folder TEXT NOT NULL, rid TEXT NOT NULL, job TEXT, progress TEXT, summary TEXT,"
    " PRIMARY KEY (folder, rid)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS bt_trades (folder TEXT NOT NULL, rid TEXT NOT NULL, csv TEXT, PRIMARY KEY (folder, rid)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS bt_notes (folder TEXT NOT NULL, k TEXT NOT NULL, v TEXT, PRIMARY KEY (folder, k)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS journal (file TEXT NOT NULL, rk TEXT NOT NULL, row TEXT, PRIMARY KEY (file, rk)) WITHOUT ROWID",
    # the data vault (same columns as ib_data_vault.py; WITHOUT ROWID = one B-tree, half the row writes)
    "CREATE TABLE IF NOT EXISTS v_days (ticker TEXT NOT NULL, day TEXT NOT NULL, status_1m TEXT, status_10s TEXT, prior_close REAL,"
    " prior_volume REAL, n_1m INTEGER, n_10s INTEGER, first_bar TEXT, last_bar TEXT, day_high REAL, day_volume REAL, source TEXT,"
    " fetched_at TEXT, note TEXT, PRIMARY KEY (ticker, day)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS v_bars_1m (ticker TEXT NOT NULL, day TEXT NOT NULL, t TEXT NOT NULL, open REAL, high REAL, low REAL,"
    " close REAL, volume REAL, PRIMARY KEY (ticker, day, t)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS v_bars_10s (ticker TEXT NOT NULL, day TEXT NOT NULL, t TEXT NOT NULL, open REAL, high REAL, low REAL,"
    " close REAL, volume REAL, PRIMARY KEY (ticker, day, t)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS v_daily (ticker TEXT NOT NULL, day TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,"
    " volume REAL, PRIMARY KEY (ticker, day)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS v_daily_hist (ticker TEXT NOT NULL, day TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL,"
    " volume REAL, PRIMARY KEY (ticker, day)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS v_daily_hist_cover (ticker TEXT PRIMARY KEY, status TEXT, want_start TEXT, want_end TEXT,"
    " first_day TEXT, last_day TEXT, n INTEGER, fetched_at TEXT, note TEXT)",
    # change log: a PC pulls what happened after the last seq it has (ticker-days / ticker histories to re-copy)
    "CREATE TABLE IF NOT EXISTS v_log (seq INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, day TEXT, kind TEXT)",
]


def _read_env_file():
    """TURSO_* from the .env next to the app / main.py (the same file the other credentials use)."""
    out = {}
    here = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, ".env")]
    d = here
    for _ in range(4):
        d = os.path.dirname(d)
        cands.append(os.path.join(d, ".env"))
    cands.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "LHShortBot", ".env"))
    for p in cands:
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s.startswith("#") or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    k, v = k.strip().upper(), v.strip().strip("\"'")
                    if k.startswith("TURSO_") and v and k not in out:
                        out[k] = v
        except OSError:
            continue
    return out


class TursoError(RuntimeError):
    pass


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _val(c):
    t = c.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(c["value"])
    if t == "float":
        return float(c["value"])
    return c.get("value")


class Cloud:
    def __init__(self, url=None, token=None):
        env = _read_env_file()
        self.url = (url or os.environ.get("TURSO_DATABASE_URL") or env.get("TURSO_DATABASE_URL") or "").strip()
        self.token = (token or os.environ.get("TURSO_AUTH_TOKEN") or env.get("TURSO_AUTH_TOKEN") or "").strip()
        self.local = None
        self.lock = threading.RLock()
        self.ready = False
        self.error = ""
        self._pending = {}                      # (ns, k) -> value : background writes, latest wins
        self._pcond = threading.Condition()
        self._writer = None
        self._cache = {}                        # ns -> {k: value}
        if self.url.startswith("file:"):
            self.local = sqlite3.connect(self.url[5:], check_same_thread=False)
        elif self.url.startswith("libsql://"):
            self.url = "https://" + self.url[len("libsql://"):]
        self.url = self.url.rstrip("/")

    # ------------------------------------------------------------------ transport
    def configured(self):
        return bool(self.local is not None or (self.url and self.token))

    def _post(self, reqs):
        body = json.dumps({"requests": reqs + [{"type": "close"}]}).encode("utf-8")
        last = None
        for i in range(4):
            try:
                rq = urllib.request.Request(self.url + "/v2/pipeline", data=body, method="POST",
                                            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
                with urllib.request.urlopen(rq, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                msg = exc.read().decode("utf-8", "replace")[:300]
                if exc.code in (401, 403):
                    raise TursoError(f"Turso refused the token (HTTP {exc.code}) - check TURSO_AUTH_TOKEN") from None
                last = TursoError(f"Turso HTTP {exc.code}: {msg}")
                if exc.code < 500 and exc.code != 429:
                    raise last from None
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last = TursoError(f"Turso not reachable: {exc}")
            time.sleep(0.6 * (i + 1))
        raise last

    def batch(self, stmts, atomic=False):
        """[(sql, args)] -> [rows per statement]; rows = list of tuples. atomic = all or nothing."""
        stmts = [(s, tuple(a or ())) for s, a in stmts]
        if not stmts:
            return []
        if self.local is not None:
            with self.lock:
                out = []
                try:
                    for s, a in stmts:
                        cur = self.local.execute(s, a)
                        out.append(cur.fetchall() if cur.description else [])
                    self.local.commit()
                except Exception:
                    self.local.rollback()
                    raise
                return out
        seq = ([("BEGIN", ())] if atomic else []) + stmts + ([("COMMIT", ())] if atomic else [])
        reqs = [{"type": "execute", "stmt": {"sql": s, "args": [_arg(x) for x in a]}} for s, a in seq]
        res = self._post(reqs)["results"]
        out = []
        for i, r in enumerate(res[:len(seq)]):
            if r.get("type") != "ok":
                msg = (r.get("error") or {}).get("message", "error")
                raise TursoError(f"{msg}  [{seq[i][0][:80]}]")
            rr = r["response"]["result"]
            out.append([tuple(_val(c) for c in row) for row in rr.get("rows", [])])
        if atomic:
            out = out[1:-1]
        return out

    def execute(self, sql, args=()):
        return self.batch([(sql, args)])[0]

    def init(self):
        """Create the tables (idempotent). False = not configured / not reachable (self.error says why)."""
        if not self.configured():
            return False
        try:
            self.batch([(s, ()) for s in SCHEMA])
            self.ready = True
            self.error = ""
        except TursoError as exc:
            self.ready, self.error = False, str(exc)
        return self.ready

    # ------------------------------------------------------------------ key/value (settings, favorites, caches ...)
    def kv_all(self, ns):
        rows = self.execute("SELECT k, v FROM kv WHERE ns=?", (ns,))
        out = {}
        for k, v in rows:
            try:
                out[k] = json.loads(v)
            except (TypeError, ValueError):
                pass
        return out

    def kv_get(self, ns, k, default=None):
        rows = self.execute("SELECT v FROM kv WHERE ns=? AND k=?", (ns, k))
        try:
            return json.loads(rows[0][0]) if rows else default
        except (TypeError, ValueError):
            return default

    def kv_put(self, ns, k, value):
        self.execute("INSERT OR REPLACE INTO kv (ns, k, v, updated) VALUES (?,?,?,datetime('now'))",
                     (ns, k, json.dumps(value, default=str)))

    def kv_del(self, ns, k):
        self.execute("DELETE FROM kv WHERE ns=? AND k=?", (ns, k))

    def kv_put_bg(self, ns, k, value):
        """Write in the background (the UI / the trading loop never waits for the network). The latest value of a key wins."""
        with self._pcond:
            self._pending[(ns, k)] = value
            if self._writer is None or not self._writer.is_alive():
                self._writer = threading.Thread(target=self._write_loop, name="turso-writer", daemon=True)
                self._writer.start()
            self._pcond.notify()

    def _write_loop(self):
        while True:
            with self._pcond:
                while not self._pending:
                    self._pcond.wait()
                batch, self._pending = self._pending, {}
            try:
                self.batch([("INSERT OR REPLACE INTO kv (ns, k, v, updated) VALUES (?,?,?,datetime('now'))",
                             (ns, k, json.dumps(v, default=str))) for (ns, k), v in batch.items()])
            except Exception as exc:
                self.error = str(exc)
                with self._pcond:                         # keep it for the next try (a newer value of the key wins)
                    for key, v in batch.items():
                        self._pending.setdefault(key, v)
                time.sleep(5)

    def flush(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            with self._pcond:
                if not self._pending:
                    return True
            time.sleep(0.1)
        return False


# ---------------------------------------------------------------------- trade journals (the CSV files stay the bot's own
# crash-recovery log; every row is mirrored here, so the Journal shows the trades of every PC)
JOURNAL_SKIP = ("account",)


def _rk(row):
    import hashlib
    return hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:20]


def journal_add(file, row):
    """Mirror one journal row (background; never raises, never blocks the trading loop)."""
    row = {k: ("" if v is None else str(v)) for k, v in dict(row).items() if k not in JOURNAL_SKIP}

    def go():
        c = cloud()
        if c is not None:
            try:
                c.execute("INSERT OR REPLACE INTO journal (file, rk, row) VALUES (?,?,?)", (file, _rk(row), json.dumps(row)))
            except Exception:
                pass
    threading.Thread(target=go, daemon=True, name="turso-journal").start()


def journal_rows(file):
    c = cloud()
    if c is None:
        return None
    try:
        return [json.loads(r) for (r,) in c.execute("SELECT row FROM journal WHERE file=?", (file,))]
    except Exception:
        return None


def journal_backfill(path, file):
    """Upload the rows of a local journal CSV that Turso does not have yet (start-up; carries the old history over)."""
    import csv
    c = cloud()
    if c is None or not os.path.isfile(path):
        return 0
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = [{k: ("" if v is None else str(v)) for k, v in r.items() if k not in JOURNAL_SKIP and k is not None}
                    for r in csv.DictReader(fh)]
        have = {r for (r,) in c.execute("SELECT rk FROM journal WHERE file=?", (file,))}
        new = [(file, _rk(r), json.dumps(r)) for r in rows if _rk(r) not in have]
        for i in range(0, len(new), 100):
            c.batch([("INSERT OR REPLACE INTO journal (file, rk, row) VALUES (?,?,?)", x) for x in new[i:i + 100]], atomic=True)
        return len(new)
    except Exception:
        return 0


_CLOUD = None
_CLOUD_LOCK = threading.Lock()


def cloud():
    """The shared client (None = no credentials: the app keeps using its local files)."""
    global _CLOUD
    with _CLOUD_LOCK:
        if _CLOUD is None:
            _CLOUD = Cloud()
            _CLOUD.tried = 0.0
        c = _CLOUD
        if c.configured() and not c.ready and time.time() - c.tried > 60:      # offline at start-up: try again every minute
            c.tried = time.time()
            c.init()
        return c if (c.configured() and c.ready) else None


def reset_for_tests():
    global _CLOUD
    _CLOUD = None
