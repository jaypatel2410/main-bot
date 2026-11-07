# -*- coding: utf-8 -*-
"""Kestrel 3.14 - chart notes: your notes pinned to a candle and a price on a ticker's chart.

One note belongs to a ticker and a day, not to a screen: the live chart and every backtest chart of that ticker-day
show the same notes (right click on either chart -> Add note). Each note:

    id       unique, never reused
    tk, day  "WETO", "2026-11-02"
    t        the candle it is pinned to: ET wall clock as a UTC epoch (the time both charts use), None = not pinned
    px       the price it is pinned to (None = not pinned)
    text     what you wrote (up to 4000 characters)
    created  "2026-11-02 10:42:07" (ET) - the notes of a ticker-day are numbered 1, 2, 3 ... in this order
    updated  the last edit
    src      where it was written: "live", "backtest" or "backtest-old" (moved over from the per-strategy notes)

Saved twice, so a note is never lost:
    Turso       table chart_notes - every PC sees every note
    this PC     chart_notes.json in the app data folder - written first, at once. A note saved while Turso is not
                reachable waits in it ("pending") and is sent by a background thread when Turso answers again.
Without Turso credentials the notes simply stay in chart_notes.json.
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    _ET = None

TABLE = ("CREATE TABLE IF NOT EXISTS chart_notes (tk TEXT NOT NULL, day TEXT NOT NULL, id TEXT NOT NULL, t INTEGER, px REAL,"
         " text TEXT, created TEXT, updated TEXT, src TEXT, PRIMARY KEY (tk, day, id)) WITHOUT ROWID")
COLS = ("tk", "day", "id", "t", "px", "text", "created", "updated", "src")
MAX_TEXT = 4000
RETRY_SEC = 30                                      # a failed upload is tried again this often
_TK = re.compile(r"[A-Z0-9][A-Z0-9.\- ]{0,11}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _now():
    return (datetime.now(_ET) if _ET else datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def _clean_tk(tk):
    s = str(tk or "").upper().strip()
    if not _TK.fullmatch(s):
        raise ValueError(f"not a ticker: {tk!r}")
    return s


def _clean_day(day):
    s = str(day or "").strip()
    if not _DAY.fullmatch(s):
        raise ValueError(f"not a day: {day!r}")
    return s


def _num(v, kind):
    if v is None or v == "":
        return None
    try:
        x = kind(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None                     # NaN -> None


def _cloud():
    """The Turso client of turso.py (None = not configured / not reachable)."""
    try:
        import turso
        return turso.cloud()
    except Exception:
        return None


class Store:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "chart_notes.json")
        self.lock = threading.RLock()
        self.notes = {}                              # id -> note
        self.pending = {}                            # id -> {"op": "put"|"del", "tk", "day", "v"}: not in Turso yet
        self._v = 0
        self._table = False                          # chart_notes created in this Turso database (this run)
        self._wake = threading.Event()
        self._sender = None
        self._load()
        if self.pending:
            self._kick()

    # ------------------------------------------------------------------ this PC's copy
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return
        self.notes = {k: v for k, v in (d.get("notes") or {}).items() if isinstance(v, dict)}
        self.pending = {k: v for k, v in (d.get("pending") or {}).items() if isinstance(v, dict)}
        self._v = max([int(p.get("v") or 0) for p in self.pending.values()] + [0])

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"notes": self.notes, "pending": self.pending}, fh, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _mark(self, nid, op, n):
        self._v += 1
        self.pending[nid] = {"op": op, "tk": n["tk"], "day": n["day"], "v": self._v}

    # ------------------------------------------------------------------ Turso
    def _db(self):
        c = _cloud()
        if c is not None and not self._table:
            try:
                c.execute(TABLE)
                self._table = True
            except Exception:
                return None
        return c

    def _refresh(self, rows, tk=None):
        """Turso's notes replace this PC's copy (a note deleted on another PC goes here too) - except the notes changed
        here that Turso does not have yet."""
        with self.lock:
            for nid, n in list(self.notes.items()):
                if (tk is None or n.get("tk") == tk) and nid not in self.pending:
                    del self.notes[nid]
            for r in rows:
                n = dict(zip(COLS, r))
                if n["id"] not in self.pending:
                    self.notes[n["id"]] = n
            self._save()

    def _kick(self):
        """Wake the sender (one thread for the life of the app: it sleeps until a note changes, and retries every
        RETRY_SEC while Turso does not answer)."""
        with self.lock:
            if self._sender is None or not self._sender.is_alive():
                self._sender = threading.Thread(target=self._send_loop, name="chart-notes", daemon=True)
                self._sender.start()
        self._wake.set()

    def _send_loop(self):
        while True:
            self._wake.wait(RETRY_SEC)
            self._wake.clear()
            try:
                self.send()
            except Exception:                            # never let the sender die - the notes stay pending
                pass

    def send(self):
        """Send the pending changes to Turso. True = nothing left to send (or no Turso: they stay on this PC)."""
        with self.lock:
            todo = {k: dict(v) for k, v in self.pending.items()}
            notes = {k: dict(self.notes[k]) for k, v in todo.items() if v["op"] == "put" and k in self.notes}
        if not todo:
            return True
        c = self._db()
        if c is None:
            return False
        stmts = []
        for nid, p in todo.items():
            if p["op"] == "put" and nid in notes:
                n = notes[nid]
                stmts.append((f"INSERT OR REPLACE INTO chart_notes ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                              tuple(n.get(k) for k in COLS)))
            else:
                stmts.append(("DELETE FROM chart_notes WHERE tk=? AND day=? AND id=?", (p["tk"], p["day"], nid)))
        try:
            c.batch(stmts, atomic=True)
        except Exception:
            return False
        with self.lock:                                  # a note changed again while it was being sent stays pending
            for nid, p in todo.items():
                if self.pending.get(nid, {}).get("v") == p["v"]:
                    del self.pending[nid]
            self._save()
            return not self.pending

    # ------------------------------------------------------------------ what the window calls
    def for_ticker(self, tk):
        """Every note of a ticker (all days), oldest first. Turso's copy when it answers, else this PC's."""
        tk = _clean_tk(tk)
        c = self._db()
        if c is not None:
            try:
                self._refresh(c.execute(f"SELECT {', '.join(COLS)} FROM chart_notes WHERE tk=?", (tk,)), tk)
            except Exception:
                pass
        with self.lock:
            out = [dict(n) for n in self.notes.values() if n.get("tk") == tk]
        return sorted(out, key=lambda n: (n.get("created") or "", n["id"]))

    def everything(self):
        """{"TK|day": [notes]} of every ticker-day (the backtest's trade list shows which charts have notes)."""
        c = self._db()
        if c is not None:
            try:
                self._refresh(c.execute(f"SELECT {', '.join(COLS)} FROM chart_notes"))
            except Exception:
                pass
        out = {}
        with self.lock:
            for n in self.notes.values():
                out.setdefault(f"{n['tk']}|{n['day']}", []).append(dict(n))
        for v in out.values():
            v.sort(key=lambda n: (n.get("created") or "", n["id"]))
        return out

    def save(self, tk, day, t=None, px=None, text="", nid=None, src="live"):
        """A new note (nid None) or a changed text (nid given; a t and px given move its pin too). Saved here at once;
        Turso in the background."""
        tk, day = _clean_tk(tk), _clean_day(day)
        text = str(text or "").strip()[:MAX_TEXT]
        if not text:
            raise ValueError("the note is empty")
        now = _now()
        with self.lock:
            n = self.notes.get(nid) if nid else None
            if nid and n is None:
                raise ValueError("that note was deleted")
            if n is None:
                nid = f"{int(time.time() * 1000):x}{secrets.token_hex(2)}"
                n = {"tk": tk, "day": day, "id": nid, "t": _num(t, int), "px": _num(px, float), "text": text,
                     "created": now, "updated": now, "src": str(src or "live")[:20]}
                self.notes[nid] = n
            else:
                n["text"], n["updated"] = text, now
                if _num(t, int) is not None and _num(px, float) is not None:      # 3.14: pinned / moved from the Notes tab
                    n["t"], n["px"] = _num(t, int), _num(px, float)
            self._mark(nid, "put", n)
            self._save()
            out = dict(n)
        self._kick()
        return out

    def delete(self, nid):
        with self.lock:
            n = self.notes.pop(str(nid or ""), None)
            if n is None:
                return False
            self._mark(n["id"], "del", n)
            self._save()
        self._kick()
        return True

    def import_old(self, tk, day, old_notes):
        """The backtest's per-strategy notes of one ticker-day ({id, text, px, hms, saved}) become chart notes. Safe to run
        again: a note already moved is skipped. Returns how many were added."""
        import calendar
        tk, day = _clean_tk(tk), _clean_day(day)
        y = int(day[:4])
        added = 0
        with self.lock:
            for i, o in enumerate(old_notes or []):
                text = str(o.get("text") or "").strip()[:MAX_TEXT]
                if not text:
                    continue
                # the same old note always gets the same id, so a second run skips it
                nid = "bt" + hashlib.sha1(f"{tk}|{day}|{o.get('id')}|{text}".encode("utf-8")).hexdigest()[:16]
                if nid in self.notes or self.pending.get(nid, {}).get("op") == "del":
                    continue
                hms = str(o.get("hms") or "")
                t = None
                if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", hms):
                    hh, mm, ss = (int(x) for x in (hms + ":00")[:8].split(":"))
                    t = calendar.timegm((y, int(day[5:7]), int(day[8:10]), hh, mm, ss, 0, 0, 0))
                saved = str(o.get("saved") or "")               # "11-02 14:05" (no year, no seconds): the chart day's year;
                sec = f"{min(i, 59):02d}"                        # the list position as seconds keeps their order (= numbers)
                created = f"{y}-{saved}:{sec}" if re.fullmatch(r"\d{2}-\d{2} \d{2}:\d{2}", saved) else f"{day} 00:00:{sec}"
                n = {"tk": tk, "day": day, "id": nid, "t": t, "px": _num(o.get("px"), float), "text": text,
                     "created": created, "updated": created, "src": "backtest-old"}
                self.notes[nid] = n
                self._mark(nid, "put", n)
                added += 1
            if added:
                self._save()
        if added:
            self._kick()
        return added


_STORE = None
_STORE_LOCK = threading.Lock()


def store(data_dir):
    """The one store of this app (data_dir = the app data folder)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None or os.path.dirname(_STORE.path) != data_dir:
            _STORE = Store(data_dir)
        return _STORE
