#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IB - the market data of LH Short Bot 3.12: the IB Gateway connection (connect / reconnect, 1-minute candles,
live quotes, the halt flag, the scanner), the chart data sent to the page, the candle cache (bar_cache.db) and the read
only IB data vault, and the per-symbol candle state used by the bot.
Part of LH Short Bot - keep it next to main.py. Names written app.X live in main.py (the settings at its top).
"""
import sys
import logging
import asyncio
import calendar
import math
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timedelta
from datetime import timezone

app = sys.modules["lh_host"]                     # main.py (it binds itself before importing this file)
log = logging.getLogger("lh_app")


# -----------------------------------------------------------------------------
# Per-symbol state
# -----------------------------------------------------------------------------
class SymState:
    def __init__(self, gen, sym, contract, name, exchange):
        self.gen, self.sym, self.contract, self.name, self.exchange = gen, sym, contract, name, exchange
        self.bars = None                 # IB BarDataList (keepUpToDate)
        self.tc = []                     # chart time per bar
        self.ticker = None
        self.h_bars = self.h_tick = None
        self.subscribed = False
        self.prior = {}                  # day number -> prior close
        self.day_cache = {}              # finished days: day -> (bar count, result)
        self.live = None                 # forming candle [t, o, h, l, c, v]
        self.tcum = None                 # running VWAP / HOD / volume of the closed candles today
        self.precision = 2
        self.last_bar_wall = time.monotonic()
        self.last_tick_wall = 0.0
        self.last_resub = time.monotonic()
        self.last_finalize = 0.0
        self.last_engine = 0.0
        self.engine_busy = False
        self.engine_again = False
        self.dirty = True
        self.has_open = False
        self.halted = False
        self.ba = (None, None)          # 3.14: (bid, ask) from IB's quote - pushed on every change, also in a halt
        self.sig_json = ""
        self.alerted = set()
        self.closed_alerted = set()
        self.initial_done = False
        self.loaded_day = None
        self.reload_day = None
def bid_ask(ticker):
    """3.14: (bid, ask) of an IB ticker; None where IB has no price (nan, or -1 / 0 = no quote)."""
    out = []
    for k in ("bid", "ask"):
        try:
            v = float(getattr(ticker, k, None))
        except (TypeError, ValueError):
            v = None
        out.append(v if v is not None and v > 0 and not math.isnan(v) else None)
    return tuple(out)


def pick_details(details):
    primaries = ("NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "ISLAND", "NYSE ARCA", "NYSEAMERICAN")
    stk = [d for d in details if getattr(d.contract, "secType", "STK") == "STK"] or list(details)
    for d in stk:
        if (d.contract.primaryExchange or "").upper() in primaries:
            return d
    return stk[0]
def prior_closes(daily, tc, bars):
    """Prior close per day: IB daily bars (same as the backtester), else the
    previous day's last regular-hours 1-min close."""
    closes = []
    for d in daily or []:
        dd = d.date
        if isinstance(dd, datetime):
            dd = dd.date()
        elif isinstance(dd, str):
            try:
                dd = datetime.strptime(dd[:8], "%Y%m%d").date()
            except ValueError:
                continue
        closes.append((dd, float(d.close)))
    closes.sort()
    out = {}
    last_rth_close = None
    for dn, a, b in app.day_ranges(tc):
        dd = app.day_date(dn)
        pc = None
        for cd, cl in closes:
            if cd < dd:
                pc = cl
        out[dn] = pc if pc is not None else last_rth_close
        for i in range(b - 1, a - 1, -1):
            if app.is_rth(tc[i]):
                last_rth_close = float(bars[i].close)
                break
    return out
def prior_for(st, dn):
    if st.prior.get(dn) is not None:
        return st.prior[dn]
    last = None
    for d, a, b in app.day_ranges(st.tc):
        if d >= dn:
            break
        for i in range(b - 1, a - 1, -1):
            if app.is_rth(st.tc[i]):
                last = float(st.bars[i].close)
                break
    st.prior[dn] = last
    return last
# -----------------------------------------------------------------------------
# 3.11: BAR CACHE - finished days' 1-minute candles on disk (bar_cache.db in the app data folder) + your IB data vault
# (VAULT_DB, read only). A finished day never changes, so it is fetched from IB once. Chart time = ET wall clock epoch.
# -----------------------------------------------------------------------------
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS days (sym TEXT NOT NULL, day INTEGER NOT NULL, n INTEGER, prior REAL, src TEXT, saved TEXT,
    PRIMARY KEY (sym, day));
CREATE TABLE IF NOT EXISTS bars (sym TEXT NOT NULL, day INTEGER NOT NULL, t INTEGER NOT NULL, o REAL, h REAL, l REAL,
    c REAL, v REAL, PRIMARY KEY (sym, day, t));
"""
CACHE_MAX_DAYS = 4000               # symbol-days kept (about 160 MB); the oldest saved are dropped at start-up
SESSION_START_SEC = 4 * 3600        # 04:00 ET - a day whose first candle is later than 04:05 may be cut (not cached)
def _wd(dn):
    return app.day_date(dn).weekday() < 5
class BarCache:
    def __init__(self, path=None, vault=None):
        self.path = path or os.path.join(app.DATA_DIR, "bar_cache.db")
        self.lock = threading.Lock()
        self.db = None
        self.vault = None
        self.vault_path = ""
        self.stats = {"cache": 0, "vault": 0, "ib": 0, "saved": 0}
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
            self.db.executescript(CACHE_SCHEMA)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.commit()
            self._prune()
        except Exception as exc:
            log.warning("bar cache not available (%s): %s", self.path, exc)
            self.db = None
        vp = (vault if vault is not None else app.VAULT_DB) or ""
        if not vp:                                       # 3.14: the vault is in Turso - read this PC's replica of it
            try:
                import turso
                import turso_vault
                if turso.cloud() is not None and os.path.isfile(turso_vault.default_replica()):
                    vp = turso_vault.default_replica()
            except Exception:
                pass
        if vp:
            try:
                p = os.path.abspath(os.path.expanduser(vp))
                if not os.path.isfile(p):
                    raise FileNotFoundError(p)
                self.vault = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False, timeout=5)
                self.vault.execute("SELECT 1 FROM days LIMIT 1")
                self.vault_path = p
                log.info("IB data vault (read only): %s", p)
            except Exception as exc:
                log.warning("vault not used (%s): %s", vp, exc.__class__.__name__)
                self.vault = None

    def _prune(self):
        n = self.db.execute("SELECT COUNT(*) FROM days").fetchone()[0]
        if n <= CACHE_MAX_DAYS:
            return
        old = self.db.execute("SELECT sym, day FROM days ORDER BY saved LIMIT ?", (n - CACHE_MAX_DAYS,)).fetchall()
        self.db.executemany("DELETE FROM bars WHERE sym=? AND day=?", old)
        self.db.executemany("DELETE FROM days WHERE sym=? AND day=?", old)
        self.db.commit()

    def _vault_day(self, sym, dn):
        if self.vault is None:
            return None
        ds = str(app.day_date(dn))
        row = self.vault.execute("SELECT status_1m, prior_close FROM days WHERE ticker=? AND day=?", (sym, ds)).fetchone()
        if not row or row[0] not in ("ok", "no_data"):
            return None
        if row[0] == "no_data":
            return [], row[1]
        out = []
        for t, o, h, l, c, v in self.vault.execute("SELECT t, open, high, low, close, volume FROM bars_1m WHERE ticker=? "
                                                   "AND day=? ORDER BY t", (sym, ds)):
            try:
                out.append((calendar.timegm(datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").timetuple()),
                            float(o), float(h), float(l), float(c), float(v or 0)))
            except (TypeError, ValueError):
                continue
        return (out, row[1]) if out else None

    def day(self, sym, dn):
        """(candles [(t, o, h, l, c, v)], prior close or None) of a finished day; [] = no trades that day (holiday);
        None = not on disk (ask IB)."""
        with self.lock:
            try:
                if self.db is not None:
                    r = self.db.execute("SELECT n, prior FROM days WHERE sym=? AND day=?", (sym, int(dn))).fetchone()
                    if r is not None:
                        bars = self.db.execute("SELECT t, o, h, l, c, v FROM bars WHERE sym=? AND day=? ORDER BY t",
                                               (sym, int(dn))).fetchall() if r[0] else []
                        self.stats["cache"] += 1
                        return bars, r[1]
                vd = self._vault_day(sym, dn)
            except Exception as exc:
                log.warning("bar cache read %s: %s", sym, exc)
                return None
            if vd is not None:
                self.stats["vault"] += 1
            return vd

    def put(self, sym, dn, bars, prior=None, src="IB"):
        with self.lock:
            if self.db is None:
                return
            try:
                self.db.execute("DELETE FROM bars WHERE sym=? AND day=?", (sym, int(dn)))
                self.db.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)",
                                    [(sym, int(dn), int(b[0]), b[1], b[2], b[3], b[4], b[5]) for b in bars])
                self.db.execute("INSERT OR REPLACE INTO days VALUES (?,?,?,?,?,?)",
                                (sym, int(dn), len(bars), prior, src, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                self.db.commit()
                self.stats["saved"] += 1
            except Exception as exc:
                log.warning("bar cache write %s: %s", sym, exc)

    def set_prior(self, sym, dn, prior):
        with self.lock:
            if self.db is None or prior is None:
                return
            try:
                self.db.execute("UPDATE days SET prior=? WHERE sym=? AND day=? AND prior IS NULL", (prior, sym, int(dn)))
                self.db.commit()
            except Exception:
                pass

    def walk(self, sym, before_dn, want, max_weekdays=12):
        """The `want` trading days before day `before_dn` that are on disk, newest first: [(dn, candles, prior)]. Stops
        at the first day that is not on disk (so the list is always contiguous); holidays are passed over."""
        got, d, seen = [], int(before_dn) - 1, 0
        while len(got) < want and seen < max_weekdays:
            if _wd(d):
                seen += 1
                r = self.day(sym, d)
                if r is None:
                    break
                if r[0]:
                    got.append((d, list(r[0]), r[1]))
            d -= 1
        return got

    def info(self):
        with self.lock:
            n = 0
            try:
                if self.db is not None:
                    n = self.db.execute("SELECT COUNT(*) FROM days").fetchone()[0]
            except Exception:
                pass
        try:
            mb = os.path.getsize(self.path) / 1e6
        except OSError:
            mb = 0.0
        s = self.stats
        served = s["cache"] + s["vault"] + s["ib"]
        return {"days": n, "mb": round(mb, 1), "vaultOn": bool(self.vault), "hit": round(100.0 * (s["cache"] + s["vault"]) /
                served, 0) if served else None, **s}
def candle_tuples(bars):
    """IB bars -> {day: [(t, o, h, l, c, v)]} (chart time)."""
    out = {}
    for b in bars or []:
        t = app.ctime(b.date)
        o, h, l, c, v = app.bar_ohlcv(b)
        out.setdefault(t // 86400, []).append((t, o, h, l, c, v))
    return out
def rows_from_tuples(days):
    """[(dn, candles)] oldest first -> the page's 1-minute rows (VWAP per day, the chart's formula)."""
    rows = []
    for dn, cs in days:
        pv = vv = 0.0
        started = app.K.include_pm
        for t, o, h, l, c, v in cs:
            r = app.is_rth(t)
            if not started and r:
                started = True
            if started:
                pv += (h + l + c) / 3.0 * v
                vv += v
            rows.append([t, app._f(o), app._f(h), app._f(l), app._f(c), app._f(v, 2), 1 if r else 0, app._f(pv / vv) if vv > 0 else None])
    return rows
def chart_to_utc(t):
    """Chart time (ET wall clock as epoch) -> the real instant (aware UTC)."""
    naive = datetime.fromtimestamp(int(t), timezone.utc).replace(tzinfo=None)
    try:
        aware = naive.replace(tzinfo=app.ET_TZ) if not hasattr(app.ET_TZ, "localize") else app.ET_TZ.localize(naive)
    except Exception:
        aware = naive.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc)
def ib_bar(t, o, h, l, c, v):
    """A cached candle as an IB bar object (it goes into IB's keep-up-to-date candle list)."""
    d = chart_to_utc(t)
    if app._IBBar is not None:
        return app._IBBar(date=d, open=o, high=h, low=l, close=c, volume=v, average=0.0, barCount=0)
    from types import SimpleNamespace
    return SimpleNamespace(date=d, open=o, high=h, low=l, close=c, volume=v, average=0.0, barCount=0)
# -----------------------------------------------------------------------------
# IB backend (own thread + asyncio loop)
# -----------------------------------------------------------------------------
class Backend:
    def __init__(self, bridge, settings):
        self.bridge, self.settings = bridge, settings
        app.set_modes(settings.get("modes"))                 # 3.10: the saved trading mode of every strategy
        self.loop = asyncio.new_event_loop()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine")
        self.ib = None
        self.state = None
        self.gen = 0
        self.pending_sym = None
        self.loading = 0
        self.closing = False
        self.connecting = False
        self.cid_offset = 0
        self.cid_conflict = False
        self.clock_offset = timedelta(0)
        self.last_error = ""
        self.status = {"conn": "connecting", "text": "Starting..."}
        self.bot = None                  # the auto-trader (watchlist + TradeZero)
        self.daily_cache = {}            # symbol -> (date fetched, rows)
        self.cache = BarCache() if app.BAR_CACHE else None   # 3.11: finished days on disk (+ the vault, read only)
        self._mlock = None                # 3.11: one older-history IB request at a time (page + prefetch)
        self.no_older = {}                # symbol -> chart time before which IB has nothing
        self.prefetch_busy = False
        self.more_next = 0.0
        self.ib_ping_ms = None            # 3.11: IB Gateway round trip (heartbeat), for the bot center
        self.load_ms = None               # last chart open: ms, and where the candles came from
        self.load_src = ""
        self.alerts = app.PriceAlerts(settings)   # 3.11: price alerts
        self.ui_screen = "chart"           # 3.11: the screen the page shows (chart / scan / journal / bot / keys)
        self.scan_on = False               # 3.11: the Scanner screen is open -> scan + live quotes
        self.scan_task = None
        self.scan_force = False
        self.scan_cfg = {"up": 30.0, "px": 0.5}
        self.scan_tk = {}                  # symbol -> (contract, ticker)
        self.scan_order, self.scan_at, self.scan_err = [], "", ""
        self.thread = threading.Thread(target=self._thread_main, name="ib-loop", daemon=True)

    # ---- thread entry points ----
    def start(self):
        self.thread.start()

    def _thread_main(self):
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._main())
        try:
            self.loop.run_forever()
        except Exception:
            log.exception("event loop stopped")

    def request_symbol(self, sym):
        asyncio.run_coroutine_threadsafe(self._load(sym), self.loop)

    def request_reconnect(self):
        self.loop.call_soon_threadsafe(self._force_reconnect)

    def fetch_daily(self, sym):
        """Blocking helper for the page: daily candles (regular hours) for sym."""
        return asyncio.run_coroutine_threadsafe(self._daily(sym), self.loop).result(timeout=75)

    async def _daily(self, sym):
        if self.ib is None or not self.ib.isConnected():
            raise RuntimeError("not connected to IB Gateway")
        today = self.now_et().date()
        cached = self.daily_cache.get(sym)
        if cached is not None and cached[0] == today:
            return cached[1]
        st = self.state
        contract = st.contract if st is not None and st.sym == sym and st.contract is not None else None
        if contract is None:
            details = await asyncio.wait_for(self.ib.reqContractDetailsAsync(app.Stock(sym.replace(".", " "), "SMART", "USD")), 20)
            if not details:
                raise RuntimeError("symbol not found")
            contract = pick_details(details).contract
            contract.exchange = "SMART"
        self.last_error = ""
        bars = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr=app.DAILY_HISTORY, barSizeSetting="1 day",
            whatToShow="TRADES", useRTH=True, formatDate=1), 60)
        rows = []
        for b in bars or []:
            d = b.date.date() if isinstance(b.date, datetime) else b.date
            if isinstance(d, str):
                d = datetime.strptime(d[:8], "%Y%m%d").date()
            o, h, l, c, v = app.bar_ohlcv(b)
            rows.append([calendar.timegm(d.timetuple()), app._f(o), app._f(h), app._f(l), app._f(c), app._f(v, 0), 1, None])
        if not rows:
            raise RuntimeError(self.last_error or "IB returned no daily candles")
        if len(self.daily_cache) > 20:
            self.daily_cache.clear()
        self.daily_cache[sym] = (today, rows)
        return rows

    def fetch_more(self, sym, kind, oldest):
        """3.10, blocking helper for the page: older candles of the OPEN chart only (scroll left / zoom out).
        kind "1m" = 1-minute rows (VWAP per day like the chart) before `oldest` (chart time); "D" = daily rows.
        3.11: {"rows": [...], "src": "cache" | "IB"} - finished days come from disk when it has them."""
        return asyncio.run_coroutine_threadsafe(self._more(sym, kind, int(oldest)), self.loop).result(timeout=90)

    def _more_lock(self):
        if self._mlock is None:
            self._mlock = asyncio.Lock()
        return self._mlock

    async def _ib_older(self, st, oldest, daily=False):
        """One IB request for the candles before `oldest` (chart time) - spaced HISTORY_MORE_MIN_GAP_SEC apart."""
        if self.ib is None or not self.ib.isConnected():
            raise RuntimeError("not connected to IB Gateway")
        wait = self.more_next - time.monotonic()
        if wait > 0:                                     # IB pacing: one older-history request at a time, spaced
            await asyncio.sleep(wait)
        self.more_next = time.monotonic() + app.HISTORY_MORE_MIN_GAP_SEC
        bars = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
            st.contract, endDateTime=chart_to_utc(oldest), durationStr=app.HISTORY_MORE_DAILY if daily else app.HISTORY_MORE_1M,
            barSizeSetting="1 day" if daily else "1 min", whatToShow="TRADES", useRTH=daily,
            formatDate=1 if daily else 2), 80)
        if self.cache is not None and not daily:
            self.cache.stats["ib"] += 1
        return bars or []

    def _today_dn(self):
        return calendar.timegm(self.now_et().timetuple()) // 86400

    def _store_days(self, sym, days, end_dn=None, prior=None):
        """Finished days -> the bar cache. The earliest day of a request is kept only if it starts by 04:05 (complete);
        weekdays inside the request without a candle are kept as empty (holidays). Today only after 20:05."""
        if self.cache is None or not days:
            return
        net = self.now_et()
        today = calendar.timegm(net.timetuple()) // 86400
        closed = net.hour * 3600 + net.minute * 60 >= 20 * 3600 + 300
        dns = sorted(days)
        for i, dn in enumerate(dns):
            if dn > today or (dn == today and not closed):
                continue
            cs = days[dn]
            if i == 0 and cs and cs[0][0] % 86400 > SESSION_START_SEC + 300:
                continue                                 # may be cut at the start of the request
            self.cache.put(sym, dn, cs, (prior or {}).get(dn))
        last = min(end_dn if end_dn is not None else dns[-1] + 1, today)
        for dn in range(dns[0] + 1, last):
            if dn not in days and _wd(dn) and self.cache.day(sym, dn) is None:
                self.cache.put(sym, dn, [], None, "IB-empty")

    async def _more(self, sym, kind, oldest):
        """3.11: older candles of the open chart - from disk (bar cache / vault) when it has them, else IB; the next
        older days are then fetched in the background; the strategies' trades on these days follow (display only)."""
        st = self.state
        if st is None or st.sym != sym or st.contract is None:
            raise RuntimeError("that chart is not open any more")
        if kind == "D":
            bars = await self._ib_older(st, oldest, daily=True)
            rows = []
            for b in bars:
                d = b.date.date() if isinstance(b.date, datetime) else b.date
                if isinstance(d, str):
                    d = datetime.strptime(d[:8], "%Y%m%d").date()
                t = calendar.timegm(d.timetuple())
                if t < oldest:
                    o, h, l, c, v = app.bar_ohlcv(b)
                    rows.append([t, app._f(o), app._f(h), app._f(l), app._f(c), app._f(v, 0), 1, None])
            return {"rows": rows, "src": "IB"}
        dn0 = int(oldest) // 86400
        src = "cache"
        async with self._more_lock():
            got = self.cache.walk(sym, dn0, 5) if self.cache is not None else []
            if not got:
                if self.state is not st:
                    raise RuntimeError("that chart is not open any more")
                bars = [b for b in await self._ib_older(st, oldest) if app.ctime(b.date) < oldest]
                days = candle_tuples(bars)
                self._store_days(sym, days, end_dn=dn0)
                got = [(dn, days[dn], None) for dn in sorted(days, reverse=True)]
                src = "IB"
                if not got:
                    self.no_older[sym] = int(oldest)
        got.sort(key=lambda x: x[0])
        rows = rows_from_tuples([(dn, cs) for dn, cs, _ in got])
        if got:
            if app.OLDER_DAY_SIGNALS and app.jr_mode():
                self.loop.create_task(self._older_signals(st, got))
            self._prefetch_soon(st, got[0][0] * 86400 + SESSION_START_SEC)
        return {"rows": rows, "src": src}

    def _prefetch_soon(self, st, before_t, delay=0.3):
        """3.11: fetch the next older days of the open chart into the cache before the page asks for them."""
        if not app.HISTORY_PREFETCH or self.cache is None or self.prefetch_busy or st.sym in self.no_older:
            return
        self.loop.create_task(self._prefetch(st, int(before_t), delay))

    async def _prefetch(self, st, before_t, delay):
        if self.prefetch_busy:
            return
        self.prefetch_busy = True
        try:
            await asyncio.sleep(delay)
            if self.state is not st or self.ib is None or not self.ib.isConnected():
                return
            if len(self.cache.walk(st.sym, before_t // 86400, 5)) >= 5:
                return                                   # already on disk
            async with self._more_lock():
                if self.state is not st or len(self.cache.walk(st.sym, before_t // 86400, 5)) >= 5:
                    return
                bars = [b for b in await self._ib_older(st, before_t) if app.ctime(b.date) < before_t]
                if not bars:
                    self.no_older[st.sym] = before_t
                    return
                self._store_days(st.sym, candle_tuples(bars), end_dn=before_t // 86400)
                log.info("prefetched older candles %s (%d)", st.sym, len(bars))
        except Exception as exc:
            log.info("prefetch %s: %r", st.sym, exc)
        finally:
            self.prefetch_busy = False

    async def _older_signals(self, st, got):
        """3.11: the strategies (Jay-read + max squeeze, the chart's backtest view) on older days -> triangles on the
        chart and cards in the Signals panel. Display only: this never reaches the bot or TradeZero."""
        try:
            daily = None
            need = [dn for dn, cs, pc in got if not pc]
            if need:
                try:
                    daily = await self._daily(st.sym)
                except Exception as exc:
                    log.info("older signals %s: no daily candles (%r)", st.sym, exc)
            closes = sorted((r[0] // 86400, r[4]) for r in (daily or []) if r[4])
            known = {dn: pc for dn, cs, pc in got if pc}

            def prior_of(dn):
                if known.get(dn):
                    return known[dn]
                pc = None
                for d, c in closes:
                    if d < dn:
                        pc = c
                    else:
                        break
                if pc is None:                           # the day before, from its own candles
                    prev = [x for x in got if x[0] < dn]
                    if prev:
                        rth = [c for t, o, h, l, c, v in prev[-1][1] if app.is_rth(t)]
                        pc = rth[-1] if rth else None
                if pc is not None and self.cache is not None:
                    self.cache.set_prior(st.sym, dn, pc)
                return pc
            jobs = app.older_jobs(st.sym, [(dn, cs) for dn, cs, _ in got], prior_of)
            if not jobs:
                return
            results = await self.loop.run_in_executor(self.pool, app.run_jobs, jobs)
            if self.state is not st:
                return
            trades = [t for res in results for t in res["trades"]]
            self.bridge.call("olderSignals", {"sym": st.sym, "gen": st.gen, "days": [j["day"] for j in jobs],
                                              "trades": trades})
        except Exception:
            log.exception("older-day signals %s", st.sym)

    def request_resend(self):
        self.loop.call_soon_threadsafe(self._resend)

    def _resend(self):
        if self.bot is not None:
            self.bot.last_push = ""             # the bot panel is re-sent on its next tick
            if self.bot.longbot is not None:
                self.bot.longbot.last_push = ""  # ... and the premarket long tab
        st = self.state
        if st is None or st.bars is None:
            if self.pending_sym:
                self.bridge.call("setLoading", {"sym": self.pending_sym, "quiet": False,
                                                "waiting": self.ib is None or not self.ib.isConnected()})
            return
        self.bridge.call("setHistory", {"gen": st.gen, "sym": st.sym, "name": st.name, "exch": st.exchange,
                                        "precision": st.precision, "keepView": False, "bars": app.history_rows(st)})
        if st.sig_json:
            self.bridge.call_raw("setSignals", st.sig_json)
        if st.live is not None:
            self.bridge.quote(st.gen, app.make_quote(st))

    def stop(self):
        if self.closing:
            return
        if self.bot is not None:                    # "bot stopped" message to Discord (open shorts listed)
            th = threading.Thread(target=self.bot.goodbye, daemon=True)
            th.start()
            th.join(5)
        self.closing = True
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop).result(timeout=4)
        except Exception:
            pass

    # ---- helpers ----
    def now_et(self):
        return (datetime.now(timezone.utc) + self.clock_offset).astimezone(app.ET_TZ)

    def _set_status(self, conn, text):
        self.status = {"conn": conn, "text": text}
        self.bridge.call("setStatus", self.status)

    def _toast(self, kind, text):
        self.bridge.call("toast", {"kind": kind, "text": text})

    # ---- connection ----
    async def _main(self):
        if app.IB is None:
            self._set_status("disconnected", "IB API library missing - run: pip install ib_async")
            return
        self.ib = app.IB()
        self.ib.errorEvent += self._on_error
        self.ib.disconnectedEvent += self._on_disconnected
        start_sym = (app.DEFAULT_SYMBOL or self.settings.get("last_symbol") or "").strip().upper()
        if start_sym:
            self.pending_sym = start_sym
            self.bridge.call("setLoading", {"sym": start_sym, "quiet": False, "waiting": True})
        self.loop.create_task(self._watchdog())
        self.loop.create_task(self._alert_watch())
        if self.bot is None:
            self.bot = app.Bot(self)
            self.loop.create_task(self.bot.run())
        await self._ensure_connected()

    async def _ensure_connected(self):
        if self.connecting or self.closing or self.ib is None:
            return
        self.connecting = True
        delay = 2
        try:
            while not self.closing and not self.ib.isConnected():
                cid = app.IB_CLIENT_ID + self.cid_offset
                self._set_status("connecting", f"Connecting to IB Gateway {app.IB_HOST}:{app.IB_PORT} (client id {cid})...")
                self.cid_conflict = False
                try:
                    await self.ib.connectAsync(app.IB_HOST, app.IB_PORT, clientId=cid, timeout=10, readonly=True)
                except Exception as exc:
                    try:
                        self.ib.disconnect()
                    except Exception:
                        pass
                    if self.cid_conflict:
                        self.cid_offset = (self.cid_offset + 1) % 20
                        delay = 1
                    why = "API port closed / Gateway not running" if isinstance(exc, (ConnectionRefusedError, OSError)) \
                        else exc.__class__.__name__
                    self._set_status("disconnected", f"IB Gateway not reachable at {app.IB_HOST}:{app.IB_PORT} ({why}) - "
                                                     f"retrying in {delay}s")
                    log.warning("connect failed: %r", exc)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30)
            if self.ib.isConnected() and not self.closing:
                self.ib.reqMarketDataType(app.MARKET_DATA_TYPE)
                cid = app.IB_CLIENT_ID + self.cid_offset
                self._set_status("connected", f"Connected to IB Gateway {app.IB_HOST}:{app.IB_PORT} - client id {cid}")
                log.info("connected (client id %s)", cid)
                sym = self.pending_sym or (self.state.sym if self.state else None)
                if sym:
                    quiet = self.state is not None and self.state.sym == sym
                    self.loop.create_task(self._load(sym, quiet=quiet))
        finally:
            self.connecting = False

    def _on_disconnected(self):
        if self.closing:
            return
        log.warning("disconnected from IB Gateway")
        if self.state is not None:
            self.state.subscribed = False
        if self.bot is not None:
            self.bot.on_ib_disconnected()
        self._set_status("disconnected", "Disconnected from IB Gateway - reconnecting...")
        self.loop.create_task(self._reconnect_soon())

    async def _reconnect_soon(self):
        await asyncio.sleep(1.5)
        await self._ensure_connected()

    def _force_reconnect(self):
        if self.ib is None:
            return
        if self.ib.isConnected():
            self._toast("info", "Reconnecting to IB Gateway...")
            self.ib.disconnect()            # disconnectedEvent -> reconnect + reload
        else:
            self.loop.create_task(self._ensure_connected())

    def _on_error(self, *args):
        try:
            req_id, code, msg = args[0], int(args[1]), str(args[2])
        except Exception:
            return
        if code in (2104, 2106, 2158, 2119, 2108):
            if self.status.get("conn") == "warning":
                self._set_status("connected", f"Data farm OK - {msg}")
            return
        if code == 162 and "api scanner subscription cancelled" in msg.lower():
            return
        log.info("IB %s (req %s): %s", code, req_id, msg)
        if code == 326:
            self.cid_conflict = True
        elif code == 1100:
            self._set_status("warning", "IB Gateway lost its link to IBKR servers - waiting for it to come back...")
            if self.bot is not None:
                self.bot.on_ib_link(False)               # 3.10: Discord "IBKR SERVERS NOT REACHABLE"
        elif code in (1101, 1102):
            self._set_status("connected", "Link to IBKR servers restored")
            if self.bot is not None:
                self.bot.on_ib_link(True)
            if self.state is not None:
                self.loop.create_task(self._load(self.state.sym, quiet=True))
        elif code in (2103, 2105, 2157):
            self._set_status("warning", f"IB data farm issue: {msg}")
        elif code in (354, 10089, 10090, 10167, 10168, 10197):
            self._toast("warn", f"Market data: {msg}")
        elif code == 10182 and self.state is not None:
            self.loop.create_task(self._load(self.state.sym, quiet=True))
        elif code in (162, 200, 321, 322):
            if "cancel" not in msg.lower():
                self.last_error = msg

    async def _watchdog(self):
        last_hb = 0.0
        while not self.closing:
            await asyncio.sleep(5)
            try:
                ib = self.ib
                if ib is None:
                    continue
                if not ib.isConnected():
                    if not self.connecting:
                        self.loop.create_task(self._ensure_connected())
                    continue
                mono = time.monotonic()
                if mono - last_hb >= app.HEARTBEAT_SEC:
                    last_hb = mono
                    try:
                        t_ping = time.monotonic()
                        server = await asyncio.wait_for(ib.reqCurrentTimeAsync(), 10)
                        self.ib_ping_ms = int((time.monotonic() - t_ping) * 1000)
                        if server.tzinfo is None:
                            server = server.replace(tzinfo=timezone.utc)
                        off = server - datetime.now(timezone.utc)
                        if abs(off.total_seconds()) < 120:
                            self.clock_offset = off
                    except Exception:
                        log.warning("heartbeat failed - reconnecting")
                        self._set_status("connecting", "IB Gateway not responding - reconnecting...")
                        try:
                            ib.disconnect()
                        except Exception:
                            pass
                        continue
                st = self.state
                if st is None:
                    if self.pending_sym and not self.loading:
                        self.loop.create_task(self._load(self.pending_sym))
                    continue
                net = self.now_et()
                secs = net.hour * 3600 + net.minute * 60 + net.second
                dn = calendar.timegm(net.timetuple()) // 86400
                active = net.weekday() < 5 and 4 * 3600 <= secs < 20 * 3600
                if active and secs >= 4 * 3600 + 60 and st.reload_day != dn:
                    st.reload_day = dn
                    if st.loaded_day != dn:
                        log.info("new trading day - reloading %s", st.sym)
                        self.loop.create_task(self._load(st.sym, quiet=True))
                        continue
                if active and st.subscribed:
                    stale = mono - st.last_bar_wall
                    trading = mono - st.last_tick_wall < 30
                    if (stale > app.STALE_STREAM_SEC and trading) or (stale > 300 and mono - st.last_resub > 600):
                        log.warning("stream stalled (%.0fs) - re-subscribing %s", stale, st.sym)
                        st.last_resub = mono
                        self._toast("warn", "Candle stream stalled - re-subscribing")
                        self.loop.create_task(self._load(st.sym, quiet=True))
                        continue
                if st.has_open and st.dirty and mono - st.last_engine >= app.ENGINE_INTERVAL_SEC:
                    self.loop.create_task(self._run_engine(st))
            except Exception:
                log.exception("watchdog")

    async def _alert_watch(self):
        """3.12.1: price alerts on any symbol. A symbol that is neither the open chart nor on the watchlist gets its
        own live quote while it has an alert (cancelled when the alert fires or is removed); checked every second."""
        self.alert_tk = {}
        conn_seen = None
        while not self.closing:
            await asyncio.sleep(1.0)
            try:
                ib = self.ib
                ok = ib is not None and ib.isConnected()
                if not ok or conn_seen is not ib:          # disconnected / reconnected: subscriptions are gone
                    self.alert_tk = {}
                    conn_seen = ib if ok else None
                    if not ok:
                        continue
                want = {a["sym"] for a in self.alerts.list()}
                own = {s for s in want if self._own_ticker(s) is not None}
                for sym in [s for s in self.alert_tk if s not in want or s in own]:
                    c, tk = self.alert_tk.pop(sym)
                    if c is not None:
                        try:
                            ib.cancelMktData(c)
                        except Exception:
                            pass
                for sym in sorted(want - own - set(self.alert_tk))[:20]:
                    try:
                        cs = await asyncio.wait_for(ib.qualifyContractsAsync(app.Stock(sym.replace(".", " "), "SMART", "USD")), 10)
                        if cs:
                            self.alert_tk[sym] = (cs[0], ib.reqMktData(cs[0], "", False, False))
                        else:
                            self.alert_tk[sym] = (None, None)
                    except Exception as exc:
                        log.warning("price alert quote %s: %r", sym, exc)
                        self.alert_tk[sym] = (None, None)
                for sym, (c, tk) in list(self.alert_tk.items()):
                    if tk is None:
                        continue
                    px = app._num(getattr(tk, "last", None))
                    if px and px > 0:
                        self.check_alerts(sym, px)
            except Exception:
                log.exception("alert watch")

    async def _shutdown(self):
        self.closing = True
        try:
            self.alerts.clear()                          # 3.12.1: price alerts end with the app
        except Exception:
            log.exception("clear alerts")
        try:                                             # 3.14: the last settings changes reach Turso before the app ends
            import turso
            c = turso.cloud()
            if c is not None:
                await asyncio.get_running_loop().run_in_executor(None, c.flush, 10)
        except Exception:
            log.exception("Turso flush")
        try:
            if self.state is not None:
                self._unsubscribe(self.state)
            if self.bot is not None:
                for bs in list(self.bot.syms.values()):
                    self.bot._unsub(bs)
                if getattr(self.bot, "tbt", None) is not None:
                    self.bot.tbt.close()             # 3.12.2: tick-by-tick slots
            if self.ib is not None and self.ib.isConnected():
                self.ib.disconnect()
        except Exception:
            pass
        self.loop.call_later(0.2, self.loop.stop)

    # ---- symbol loading / streaming ----
    def _unsubscribe(self, st):
        st.subscribed = False
        try:
            if st.bars is not None and st.h_bars is not None:
                st.bars.updateEvent -= st.h_bars
        except Exception:
            pass
        try:
            if st.ticker is not None and st.h_tick is not None:
                st.ticker.updateEvent -= st.h_tick
        except Exception:
            pass
        if self.ib is not None and self.ib.isConnected():
            try:
                if st.bars is not None:
                    self.ib.cancelHistoricalData(st.bars)
            except Exception:
                pass
            try:
                if st.ticker is not None:
                    self.ib.cancelMktData(st.contract)
            except Exception:
                pass

    def _expected_last_day(self):
        """The day IB's "1 D" request will return: today from 04:00 on a weekday, else the last weekday before."""
        net = self.now_et()
        dn = calendar.timegm(net.timetuple()) // 86400
        if net.weekday() < 5 and net.hour >= 4:
            return dn
        dn -= 1
        while not _wd(dn):
            dn -= 1
        return dn

    def _fast_days(self, sym, last_dn):
        """The 4 trading days before `last_dn` from the cache (oldest first), or None if one of them is missing."""
        if self.cache is None:
            return None
        got = self.cache.walk(sym, last_dn, 4)
        if len(got) < 4:
            return None
        return sorted(got, key=lambda x: x[0])

    async def _load(self, sym, quiet=False):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        if not sym:
            return
        self.gen += 1
        gen = self.gen
        old = self.state
        carry = None
        if old is not None:
            if old.sym == sym:
                carry = (old.alerted, old.closed_alerted)
            self._unsubscribe(old)
        self.state = None
        self.pending_sym = sym
        self.settings.set("last_symbol", sym)
        if self.ib is None or not self.ib.isConnected():
            self.bridge.call("setLoading", {"sym": sym, "quiet": False, "waiting": True})
            return
        self.bridge.call("setLoading", {"sym": sym, "quiet": quiet})
        self.loading += 1
        try:
            await self._load_inner(sym, gen, quiet, carry)
        except Exception as exc:
            log.exception("load %s", sym)
            if gen == self.gen:
                self.bridge.call("setError", {"sym": sym, "text": f"Could not load {sym}: {exc}"})
        finally:
            self.loading -= 1

    async def _load_inner(self, sym, gen, quiet, carry):
        self.last_error = ""
        ib_sym = sym.replace(".", " ")
        try:
            details = await asyncio.wait_for(self.ib.reqContractDetailsAsync(app.Stock(ib_sym, "SMART", "USD")), 20)
        except Exception as exc:
            log.warning("contract details %s: %r", sym, exc)
            details = []
        if gen != self.gen:
            return
        if not details:
            self.pending_sym = None
            self.bridge.call("setError", {"sym": sym, "text": f"{sym}: symbol not found at IBKR (US stocks)."})
            return
        cd = pick_details(details)
        contract = cd.contract
        contract.exchange = "SMART"
        st = SymState(gen, sym, contract, cd.longName or "", contract.primaryExchange or "")
        try:
            daily = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
                contract, endDateTime="", durationStr="15 D", barSizeSetting="1 day",
                whatToShow="TRADES", useRTH=True, formatDate=1), 30)
        except Exception as exc:
            log.warning("daily bars %s: %r", sym, exc)
            daily = []
        if gen != self.gen:
            return
        bars = None
        t_open = time.monotonic()
        # 3.11 fast open: the cache has the 4 trading days before today -> IB sends only today (one small request)
        fast = self._fast_days(sym, self._expected_last_day()) if (app.FAST_OPEN and self.cache is not None
                                                                    and app.HISTORY_DURATION == "5 D") else None
        try:
            bars = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
                contract, endDateTime="", durationStr="1 D" if fast else app.HISTORY_DURATION, barSizeSetting="1 min",
                whatToShow="TRADES", useRTH=False, formatDate=2, keepUpToDate=True), 120)
        except Exception as exc:
            log.warning("1-min bars %s: %r", sym, exc)
        if gen != self.gen:
            if bars:
                try:
                    self.ib.cancelHistoricalData(bars)
                except Exception:
                    pass
            return
        if fast and bars:
            last_dn = app.ctime(bars[0].date) // 86400
            prev = self._fast_days(sym, last_dn)
            if prev is None:                             # the cache does not have the week before this day after all
                try:
                    self.ib.cancelHistoricalData(bars)
                except Exception:
                    pass
                fast = None
                try:
                    bars = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
                        contract, endDateTime="", durationStr=app.HISTORY_DURATION, barSizeSetting="1 min",
                        whatToShow="TRADES", useRTH=False, formatDate=2, keepUpToDate=True), 120)
                except Exception as exc:
                    log.warning("1-min bars %s: %r", sym, exc)
                    bars = None
                if gen != self.gen:
                    if bars:
                        try:
                            self.ib.cancelHistoricalData(bars)
                        except Exception:
                            pass
                    return
            else:
                bars[0:0] = [ib_bar(*x) for dn, cs, pc in prev for x in cs]
                fast = prev
        if not bars:
            self.pending_sym = None
            extra = f" ({self.last_error})" if self.last_error else ""
            self.bridge.call("setError", {"sym": sym, "text": f"No 1-minute data from IB for {sym}{extra}."})
            return

        st.bars = bars
        st.tc = [app.ctime(b.date) for b in bars]
        st.prior = prior_closes(daily, st.tc, bars)
        o, h, l, c, v = app.bar_ohlcv(bars[-1])
        st.live = [st.tc[-1], o, h, l, c, v]
        st.precision = 4 if c < 1.0 else 2
        st.loaded_day = st.tc[-1] // 86400
        st.reload_day = calendar.timegm(self.now_et().timetuple()) // 86400
        if carry is not None:
            st.alerted, st.closed_alerted = carry
            st.initial_done = True
        app.recalc_today(st)
        self.state = st
        self.pending_sym = None
        self.load_ms = int((time.monotonic() - t_open) * 1000)
        self.load_src = "cache + IB today" if fast else "IB"
        if not fast:                                     # 3.11: the finished days of this load -> the cache
            try:
                self._store_days(sym, candle_tuples(bars), prior=st.prior)
            except Exception:
                log.exception("bar cache %s", sym)
        self._prefetch_soon(st, st.tc[0], delay=3.0)     # the week before, in the background

        self.bridge.call("setHistory", {
            "gen": gen, "sym": sym, "name": st.name, "exch": st.exchange, "precision": st.precision,
            "keepView": bool(quiet), "bars": app.history_rows(st)})
        self._attach(st)
        self.bridge.quote(gen, app.make_quote(st))
        log.info("loaded %s: %d bars (%s) in %d ms from %s", sym, len(bars), st.exchange, self.load_ms, self.load_src)
        await self._run_engine(st)

    def _attach(self, st):
        def on_bars(bars, has_new):
            try:
                self._on_bars(st, bars, has_new)
            except Exception:
                log.exception("bar update")

        def on_tick(ticker):
            try:
                self._on_tick(st, ticker)
            except Exception:
                log.exception("tick update")

        st.h_bars, st.h_tick = on_bars, on_tick
        st.bars.updateEvent += on_bars
        try:
            st.ticker = self.ib.reqMktData(st.contract, "", False, False)
            st.ticker.updateEvent += on_tick
        except Exception:
            log.exception("reqMktData")
        st.subscribed = True
        st.last_bar_wall = st.last_resub = time.monotonic()

    def _push_live(self, st):
        self.bridge.upsert(st.gen, app.live_row(st))
        self.bridge.quote(st.gen, app.make_quote(st))
        if self.alerts.items and st.live is not None:
            self.check_alerts(st.sym, st.live[4])

    # ---- 3.11: price alerts ----
    def last_price(self, sym):
        st = self.state
        if st is not None and st.sym == sym and st.live is not None:
            return st.live[4]
        bs = self.bot.syms.get(sym) if self.bot is not None else None
        return bs.last_px if bs is not None else None

    def check_alerts(self, sym, px):
        try:
            for a in self.alerts.check(sym, float(px)):
                self._alert_fired(a, float(px))
        except Exception:
            log.exception("price alert %s", sym)

    def _alert_fired(self, a, px):
        word = "above" if a["dir"] == "up" else "below"
        txt = f"{a['sym']} traded {app._fp(px)} - your alert at {app._fp(a['px'])} ({word})"
        log.info("PRICE ALERT %s", txt)
        self.bridge.call("alert", {"kind": "cover", "t": calendar.timegm(self.now_et().timetuple()) // 60 * 60,
                                   "title": f"PRICE ALERT  {a['sym']}", "text": txt})
        if self.settings.get("sound"):
            app._beep("short")
        if self.bot is not None:
            try:
                self.bot._notify(f"{a['sym']} - price alert {app._fp(a['px'])}", f"{txt}. Set in the app (Alt + click on the "
                                 f"chart or the Alerts tab); it fires once.", "warn", tag="PRICE ALERT", who="System")
                self.bot._push(force=True)
            except Exception:
                log.exception("price alert message")

    # ---- 3.11: the Scanner screen (runs only while it is open) ----
    def scan_screen(self, on, cfg=None):
        self.loop.call_soon_threadsafe(self._scan_set, bool(on), dict(cfg or {}))

    def _scan_set(self, on, cfg):
        try:
            if cfg.get("up") is not None:
                self.scan_cfg["up"] = min(1000.0, max(5.0, float(cfg["up"])))
            if cfg.get("px") is not None:
                self.scan_cfg["px"] = min(100.0, max(0.1, float(cfg["px"])))
        except (TypeError, ValueError):
            pass
        self.scan_on = on
        if on:
            self.scan_force = True
            if self.scan_task is None or self.scan_task.done():
                self.scan_task = self.loop.create_task(self._scan_loop())

    def _own_ticker(self, sym):
        st = self.state
        if st is not None and st.sym == sym and st.ticker is not None:
            return st.ticker
        bs = self.bot.syms.get(sym) if self.bot is not None else None
        return getattr(bs, "ticker", None) if bs is not None else None

    def _scan_cancel(self, sym):
        c, tk = self.scan_tk.pop(sym, (None, None))
        mine = (self.state is not None and self.state.sym == sym) or (self.bot is not None and sym in self.bot.syms)
        if c is not None and not mine and self.ib is not None and self.ib.isConnected():
            try:
                self.ib.cancelMktData(c)
            except Exception:
                pass

    def _vol_mult(self):
        """IB's live volume tick may be in lots of 100 (US stocks): compared once with the chart's own candles."""
        st = self.state
        try:
            tv = app._num(getattr(st.ticker, "volume", None)) if st is not None and st.ticker is not None else None
            cm = st.tcum if st is not None else None
            if tv and cm and cm.get("vol"):
                r = (cm["vol"] + (st.live[5] if st.live else 0)) / tv
                self.vol_mult = 100.0 if 30 <= r <= 300 else 1.0
        except Exception:
            pass
        return getattr(self, "vol_mult", 1.0)

    async def _scan_loop(self):
        next_scan = 0.0
        try:
            while self.scan_on and not self.closing:
                ib = self.ib
                if ib is None or not ib.isConnected() or app.ScannerSubscription is None:
                    self.scan_err = "IB Gateway not connected" if app.ScannerSubscription is not None else "IB API missing"
                    self._scan_push()
                    await asyncio.sleep(2)
                    continue
                mono = time.monotonic()
                if mono >= next_scan or self.scan_force:
                    self.scan_force = False
                    next_scan = mono + app.SCAN_SCREEN_EVERY_SEC
                    try:
                        sub = app.ScannerSubscription(instrument="STK", locationCode="STK.US.MAJOR", scanCode="TOP_PERC_GAIN",
                                                  numberOfRows=app.SCAN_SCREEN_ROWS, abovePrice=self.scan_cfg["px"])
                        flt = [app.TagValue("changePercAbove", f"{self.scan_cfg['up']:g}")]
                        data = list(await asyncio.wait_for(ib.reqScannerDataAsync(sub, [], flt), 20) or [])
                        # 3.12.1: after 16:00 IB's regular-hours list misses stocks that run only after the close
                        # (INO 10-30): add IB's after-hours gainers, merged into the same list (duplicates dropped)
                        net = self.now_et()
                        if net.hour * 3600 + net.minute * 60 >= 16 * 3600:
                            try:
                                sub_ah = app.ScannerSubscription(instrument="STK", locationCode="STK.US.MAJOR",
                                                                 scanCode="TOP_AFTER_HOURS_PERC_GAIN",
                                                                 numberOfRows=app.SCAN_SCREEN_ROWS, abovePrice=self.scan_cfg["px"])
                                ah = await asyncio.wait_for(ib.reqScannerDataAsync(sub_ah, [], []), 20)
                                data = list(ah or []) + data
                            except Exception as exc:
                                log.warning("scanner screen: after-hours scan failed: %r", exc)
                        order = []
                        for d in data or []:
                            c = d.contractDetails.contract
                            sym = str(getattr(c, "symbol", "") or "").upper().strip().replace(" ", ".")
                            if not re.match(r"^[A-Z][A-Z0-9.]{0,7}$", sym) or sym in order:
                                continue
                            order.append(sym)
                            if sym not in self.scan_tk:
                                own = self._own_ticker(sym)      # already streamed by the chart / the bot: share it
                                if own is not None:
                                    self.scan_tk[sym] = (None, own)
                                else:
                                    c.exchange = "SMART"
                                    self.scan_tk[sym] = (c, ib.reqMktData(c, "165", False, False))
                        for sym in [s for s in self.scan_tk if s not in order]:
                            self._scan_cancel(sym)
                        self.scan_order = order
                        self.scan_at = self.now_et().strftime("%H:%M:%S")
                        self.scan_err = ""
                    except Exception as exc:
                        self.scan_err = f"scan failed ({exc.__class__.__name__}) - check the IBKR scanner permissions"
                        log.warning("scanner screen: %r", exc)
                self._scan_push()
                await asyncio.sleep(1.5)
        finally:
            for sym in list(self.scan_tk):
                self._scan_cancel(sym)
            self.scan_order = []

    def _scan_push(self):
        mult = self._vol_mult()
        net = self.now_et()
        pre = net.hour * 3600 + net.minute * 60 < app.K.rth_s
        rows = []
        bot = self.bot
        for i, sym in enumerate(self.scan_order, 1):
            c, tk = self.scan_tk.get(sym, (None, None))
            if tk is None:
                continue
            g = lambda name: app._num(getattr(tk, name, None))
            last = g("last") or g("close")
            pc = g("close")
            hi = g("high")
            vol = (g("volume") or 0.0) * mult
            avg = (app._num(getattr(tk, "avVolume", None)) or 0.0) * mult
            chg = (last / pc - 1) * 100.0 if last and pc else None
            up_hi = (max(hi or 0, last or 0) / pc - 1) * 100.0 if pc and (hi or last) else chg
            dol = vol * last if last else 0.0
            frm = (hi - last) / hi * 100.0 if hi and last and hi >= last else None
            bs = bot.syms.get(sym) if bot is not None else None
            chips = []
            if app.jr_ready():
                need = []
                if up_hi is None or up_hi < app.jrm().MIN_UP_PCT:
                    need.append(f"up {app.jrm().MIN_UP_PCT:g}% (now {up_hi or 0:.0f}%)")
                if dol < app.jrm().MIN_DOLLAR_VOL:
                    need.append(f"${app.jrm().MIN_DOLLAR_VOL / 1e6:g}M traded (now ${dol / 1e6:.1f}M)")
                chips.append({"k": "jr", "ok": not need, "t": app.jr_label() + ": " + ("up / $ ok - waits for the crack and a "
                              "bounce" if not need else "needs " + ", ".join(need))})
            if app.sq_on():
                ok = up_hi is not None and up_hi >= app.SQ.MIN_UP_PCT
                chips.append({"k": "sq", "ok": ok, "t": "Squeeze: " + (f"up {app.SQ.MIN_UP_PCT:g}% ok - waits for a swing high "
                              f"and a {app.SQ.SQUEEZE_PCT:g}% squeeze over it" if ok else f"needs up {app.SQ.MIN_UP_PCT:g}%")})
            if app.LP is not None and pre:
                g = getattr(app.LP, "MIN_GAP_PCT", 0.3) * 100
                ok = chg is not None and chg >= g
                chips.append({"k": "long", "ok": ok, "t": "Premarket long: " + (f"up {g:g}% - in its own scan" if ok
                                                                               else f"needs up {g:g}%")})
            rows.append({"n": i, "sym": sym, "last": app._f(last), "pc": app._f(pc), "chg": app._f(chg, 1), "hi": app._f(hi),
                         "vol": app._f(vol, 0), "dol": app._f(dol, 0), "rvol": app._f(vol / avg, 1) if avg else None,
                         "from": app._f(frm, 1), "halt": app._num(getattr(tk, "halted", None)) is not None,
                         "watch": bs is not None, "status": bs.status if bs is not None else "", "chips": chips})
        self.bridge.call("setScan", {"rows": rows, "at": self.scan_at, "err": self.scan_err, "cfg": self.scan_cfg,
                                     "n": len(rows), "on": self.scan_on})

    def _on_bars(self, st, bars, has_new):
        if st is not self.state or not st.subscribed:
            return
        st.last_bar_wall = time.monotonic()
        b = bars[-1]
        t = app.ctime(b.date)
        o, h, l, c, v = app.bar_ohlcv(b)
        n = len(bars)
        if has_new:
            if len(st.tc) == n - 1:
                st.tc.append(t)
            else:
                st.tc = [app.ctime(x.date) for x in bars]
            app.recalc_today(st)
            if n >= 2:
                self.bridge.upsert(st.gen, app.bar_row(st, n - 2))   # closed candle, IB values
            self.loop.create_task(self._after_new_bar(st))
        elif st.tc:
            st.tc[-1] = t
        lv = st.live
        if lv is not None and lv[0] == t:
            lv[1] = o
            lv[2] = max(lv[2], h)
            lv[3] = min(lv[3], l)
            if time.monotonic() - st.last_tick_wall > 3:
                lv[4] = c
            lv[5] = v
        elif lv is None or lv[0] < t:
            st.live = [t, o, h, l, c, v]
        else:
            self.bridge.upsert(st.gen, app.bar_row(st, n - 1))   # IB is behind the tick-built candle
            st.dirty = True
            return
        st.dirty = True
        self._push_live(st)

    def _on_tick(self, st, ticker):
        if st is not self.state or not st.subscribed or st.live is None:
            return
        halted = app._num(getattr(ticker, "halted", None)) is not None      # IB tick 49: 1 = halted, 2 = volatility halt
        if halted != st.halted:
            st.halted = halted
            log.info("%s %s", st.sym, "HALTED" if halted else "trading resumed")
            self._toast("warn" if halted else "info", f"{st.sym} {'HALTED' if halted else 'resumed trading'}")
            self.bridge.quote(st.gen, app.make_quote(st))
        ba = bid_ask(ticker)                      # 3.14: bid / ask - a halt has no trades, but IB still quotes where it
        ba_new = ba != st.ba                      # will open, so every quote change goes to the window
        if ba_new:
            st.ba = ba
        px = None
        traded = False
        for tk in (getattr(ticker, "ticks", None) or ()):
            tt = getattr(tk, "tickType", None)
            if tt in (4, 68):                     # LAST / DELAYED_LAST
                px = tk.price
                traded = True
            elif tt in (5, 71, 48, 77):           # sizes / RT volume = a trade printed
                traded = True
        if not traded:
            if ba_new:
                self.bridge.quote(st.gen, app.make_quote(st))
            return
        if px is None:
            px = ticker.last
        try:
            px = float(px)
        except (TypeError, ValueError):
            return
        if not (px > 0) or math.isnan(px):
            if ba_new:
                self.bridge.quote(st.gen, app.make_quote(st))
            return
        net = self.now_et()
        secs = net.hour * 3600 + net.minute * 60 + net.second
        if secs < 4 * 3600 or secs >= 20 * 3600:
            if ba_new:
                self.bridge.quote(st.gen, app.make_quote(st))
            return
        t = calendar.timegm(net.timetuple()) // 60 * 60
        st.last_tick_wall = time.monotonic()
        lv = st.live
        if t == lv[0]:
            if px == lv[4] and lv[3] <= px <= lv[2]:
                if ba_new:
                    self.bridge.quote(st.gen, app.make_quote(st))
                return
            lv[2] = max(lv[2], px)
            lv[3] = min(lv[3], px)
            lv[4] = px
        elif t > lv[0]:
            st.live = [t, px, px, px, px, 0.0]    # new minute before IB's candle arrives
        else:
            if ba_new:
                self.bridge.quote(st.gen, app.make_quote(st))
            return
        self._push_live(st)                       # (the quote it sends carries the bid / ask too)

    async def _after_new_bar(self, st):
        await asyncio.sleep(app.FINALIZE_DELAY_SEC)
        if st is not self.state or not st.subscribed:
            return
        await self._finalize(st)
        if st is self.state:
            await self._run_engine(st)

    async def _finalize(self, st):
        """Re-sync the just-closed candles with IB's final historical bars, so the
        live chart and the strategy see exactly what the backtest sees."""
        if time.monotonic() - st.last_finalize < app.FINALIZE_MIN_GAP_SEC or self.ib is None or not self.ib.isConnected():
            return
        st.last_finalize = time.monotonic()
        try:
            recent = await asyncio.wait_for(self.ib.reqHistoricalDataAsync(
                st.contract, endDateTime="", durationStr="300 S", barSizeSetting="1 min",
                whatToShow="TRADES", useRTH=False, formatDate=2, keepUpToDate=False), 15)
        except Exception as exc:
            log.info("finalize skipped: %r", exc)
            return
        if st is not self.state or not recent or st.bars is None:
            return
        n = len(st.bars)
        index = {st.tc[i]: i for i in range(max(0, n - 12), n - 1)}   # never touch the forming candle
        changed = False
        for rb in recent:
            i = index.get(app.ctime(rb.date))
            if i is None:
                continue
            if app.bar_ohlcv(rb) != app.bar_ohlcv(st.bars[i]):
                st.bars[i] = rb
                changed = True
                self.bridge.upsert(st.gen, app.bar_row(st, i))
        if changed:
            app.recalc_today(st)
            st.dirty = True

    async def _run_engine(self, st):
        if st is not self.state or st.bars is None:
            return
        if st.engine_busy:
            st.engine_again = True
            return
        st.engine_busy = True
        try:
            while True:
                st.engine_again = False
                st.dirty = False
                jobs = app.build_jobs(st, self.now_et())
                if not jobs:
                    break
                results = await self.loop.run_in_executor(self.pool, app.run_jobs, jobs)
                if st is not self.state:
                    return
                self._publish(st, results)
                if not st.engine_again:
                    break
        except Exception:
            log.exception("strategy run")
        finally:
            st.engine_busy = False
            st.last_engine = time.monotonic()

    def _publish(self, st, results):
        latest = None
        for r in results:
            if r["latest"]:
                latest = r
            if not r["live"]:
                st.day_cache[r["day"]] = (r["n"], r)
        if latest is None:
            return
        days = sorted(set(st.day_cache) | {latest["day"]})
        per_day = [latest if d == latest["day"] else st.day_cache[d][1] for d in days]
        markers = [m for r in per_day for m in r["markers"]]
        trades = [t for r in reversed(per_day) for t in reversed(r["trades"])]
        week = {"trades": sum(r["stats"]["trades"] for r in per_day),
                "wins": sum(r["stats"]["wins"] for r in per_day),
                "losses": sum(r["stats"]["losses"] for r in per_day),
                "R": app._f(sum(r["stats"]["R"] or 0 for r in per_day), 2)}
        # re-run the engine every few seconds while a trade is open or a short limit is armed
        st.has_open = any(t["open"] for t in latest["trades"]) or bool(latest["stats"].get("armed"))
        payload = {"gen": st.gen, "day": latest["day"], "live": latest["live"], "markers": markers,
                   "skipMarkers": latest["skip_markers"], "trades": trades, "skips": latest["skips"][-80:],
                   "levels": latest["levels"], "today": latest["stats"], "week": week, "scratch": app.STRAT.SCRATCH_R}
        js = app._dumps(payload)
        if js != st.sig_json:
            st.sig_json = js
            self.bridge.call_raw("setSignals", js)
        self._alerts(st, latest)

    def _alerts(self, st, latest):
        live = latest["live"]
        prec = st.precision

        def fp(x):
            return "-" if x is None else f"{x:.{prec}f}"
        cur = {(latest["day"], tr["t"], tr["setup"]) for tr in latest["trades"]}
        if live and st.initial_done:
            for key in sorted(getattr(st, "shown_open", set()) - cur):
                if key[0] == latest["day"]:
                    st.closed_alerted.add(key)
                    self.bridge.call("alert", {
                        "kind": "cover", "t": key[1], "title": f"SIGNAL CANCELLED  {st.sym}",
                        "text": f"{key[2]}  \u00b7  the stock halted right after the entry - treat it as not filled"})
                    log.info("CANCELLED %s %s (halt right after the entry)", st.sym, key[2])
        st.shown_open = {(latest["day"], tr["t"], tr["setup"]) for tr in latest["trades"] if tr["open"]} if live else set()
        armed = latest["stats"].get("armed")
        if armed and live and st.initial_done:
            akey = (latest["day"], armed["trigger"], "ARMED")       # same top = same limit = one toast
            if akey not in st.alerted:
                st.alerted.add(akey)
                self._toast("warn", f"{st.sym}: bounce zone armed - short limit {fp(armed['trigger'])} "
                                    f"({app.STRAT.ZONE_FAR_PCT:g}% under the top {fp(armed['top'])}, dip {armed['dip'] or 0:.0f}%), "
                                    f"stop {fp(armed['stop'])}")
                log.info("ARMED %s %s limit %s stop %s", st.sym, armed["setup"], armed["trigger"], armed["stop"])
        for tr in latest["trades"]:
            key = (latest["day"], tr["t"], tr["setup"])
            if not st.initial_done or not live:
                st.alerted.add(key)
                if not tr["open"]:
                    st.closed_alerted.add(key)
                continue
            if key not in st.alerted:
                st.alerted.add(key)
                self.bridge.call("alert", {
                    "kind": "short", "t": tr["t"], "title": f"SHORT SIGNAL  {st.sym}",
                    "text": f"S{tr['n']} {tr['setup']}  \u00b7  entry {fp(tr['entry'])}  \u00b7  stop {fp(tr['stop'])} "
                            f"({(tr['risk'] or 0):.1f}%)  \u00b7  top {fp(tr['top'])}  \u00b7  dip {(tr['dip'] or 0):.0f}%  \u00b7  "
                            f"hold to {app.STRAT.EOD_COVER_TIME}"})
                if self.settings.get("sound"):
                    app._beep("short")
                log.info("SIGNAL %s %s entry %s stop %s", st.sym, tr["setup"], tr["entry"], tr["stop"])
            if not tr["open"] and key not in st.closed_alerted:
                st.closed_alerted.add(key)
                self.bridge.call("alert", {
                    "kind": "cover", "t": tr["xT"], "title": f"COVER  {st.sym}",
                    "text": f"S{tr['n']} {tr['setup']}  \u00b7  {tr['reason']} {(tr['R'] or 0):+.2f}R  \u00b7  exit {fp(tr['xPx'])}"})
                if self.settings.get("sound"):
                    app._beep("cover")
        st.initial_done = True
