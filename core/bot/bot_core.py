# -*- coding: utf-8 -*-
"""LH Short Bot - the auto-trading Bot: start, the 1-second loop, watchlist, strategy reads, vault feed (the rest of the class is in the other core/bot/*.py files).
Part of main.py: main.py runs this file in its OWN namespace (same names, same settings), so the code works exactly
as when it was one file. Do not run it on its own - start main.py."""


class Bot(_BotStatus, _BotOrders, _BotStopsHalts, _BotSizing, _BotReconcile):  # 3.12.1: the class is split over core/bot/*.py (code unchanged)
    def __init__(self, backend):
        self.be = backend
        self.loop = backend.loop
        self.settings = backend.settings
        wl = [s for s in (self.settings.get("watchlist", []) or []) if isinstance(s, str) and s][:MAX_WATCHLIST]
        self.syms = {s: BotSym(s) for s in wl}
        self.auto = bool(AUTO_TRADE_ON_START)
        self.tz = None
        self.acc = ""
        self.acc_type = ""
        self.acc_info = {}
        self.route = None
        self.tz_status = {"conn": "off", "text": "TradeZero: not connected"}
        self.next_tz_try = 0.0
        self.next_acct = 0.0
        self.next_pos_check = 0.0
        self.tz_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="tz")
        self.tz_fast = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tz-fast")   # 3.12: halt-reopen orders only
        # (its own warm TradeZero connection - kept fresh during a halt - so a reopen order never waits for a handshake)
        self.size_base = None           # 3.12: the sizing base ($): equity at SIZE_BASE_TIME, re-set when a trade closes
        self.size_note = ""
        self.size_closed = None         # (closed trades, realized $) when the base was last set
        self.rebase_at = None           # a trade closed: the base is re-set after the next account refresh
        self.acct_mono = 0.0            # when the account was last read
        self.state_path = os.path.join(DATA_DIR, "bot_state.json")   # 3.12: open trades + the base (a restart keeps them)
        self.pos_mono = 0.0             # when TradeZero's positions were last read
        self.halt_lat = deque(maxlen=20)  # 3.12: reopen seen -> order answered (ms)
        self.msg_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="notify")   # one thread = messages stay in order
        self.dc = Discord()
        self.logs = deque(maxlen=300)
        self.last_push = ""
        self.day = None
        self.trades_today = 0
        self.sig_today = {"jr2": 0, "jr": 0, "sq": 0}   # 3.11: short signals today (bot center)
        self.lat_ms = deque(maxlen=50)        # 3.11: signal -> order sent at TradeZero, ms (bot center)
        self._cinfo = (0.0, None)             # 3.11: bar cache info, refreshed at most every 30 s
        self.day_pnl = None
        self.flags = set()              # once-a-day events done (eod alert, sell-back, summary...)
        self.located = set()
        self.flattening = False
        self.seq = 0
        self.journal = os.path.join(DATA_DIR, "bot_trades.csv")
        self.rebuilt_day = None         # 3.12: today's trades rebuilt from TradeZero (once a day, after the first connect)
        self.started_at = time.monotonic()
        self.hello_sent = False
        self.next_heartbeat = time.monotonic() + DISCORD_HEARTBEAT_MIN * 60 if DISCORD_HEARTBEAT_MIN else float("inf")
        self.ib_down_since = None
        self.ib_down_alerted = False    # 3.10: the "IB STILL DOWN 5 MIN" message was sent
        self.ib_link_down = None        # 3.10: IB Gateway up but no link to IBKR (error 1100) since
        self.err_sent = {}
        self.net_alerted = False        # Discord was told TradeZero stopped answering (a "back" message follows)
        # orders panel (below the chart)
        self.orders_raw = {}            # clientOrderId -> today's order from TradeZero
        self.order_seen = {}            # clientOrderId -> first time seen (ET seconds) when TradeZero sends no time
        self.order_ops = {}             # clientOrderId -> "cancel" / "modify" while it runs
        self.orphans = {}               # orders sent while the network dropped: settled when they show up
        self.unknown_short = {}         # 3.8.0: symbol -> (first seen, shares) of a short the bot does not hold yet
        self.known_entries = set()      # 3.8.0: entry order ids TradeZero confirmed (the bot tracks those itself)
        self.next_orders = 0.0
        self.orders_busy = False
        self.orders_err = ""
        self.orders_at = None
        self.last_orders_push = ""
        self.tz_naive = None            # TradeZero times without a time zone: "ET" or "UTC" (learned from a fresh order)
        self.longbot = None             # v3.5: the premarket long module (lh_long_premarket.py), started in run()
        self.pos_snapshot = {}          # symbol -> (side, shares) from TradeZero's last position list
        self.jr_alert_trades = []       # 3.7 ALERT_ONLY: today's would-be Jay-read trades (daily summary)
        # 3.9.0: the locate window (orders panel -> Locates) and today's locates (locates_today.json)
        self.loc_rows = []              # today's locates: yours from the window and the bot's
        self.loc_q = None               # the window's request: symbol, shares, state, offers
        self.loc_inv = []               # TradeZero's locate inventory (located shares by symbol)
        self.loc_inv_at = None
        self.loc_busy = False
        # 3.7: auto short-scanner (Jay-read mode)
        self.scanning = False
        self.next_scan = 0.0
        self.scan_seen = set()          # symbols the scanner already handled today (added / full / removed by you)
        self.scan_n = self.scan_fail = self.scan_added = 0
        auto = self.settings.get("auto_syms", {}) or {}
        for s_ in self.syms.values():
            s_.auto_added = s_.sym in auto

    # ---------------- helpers ----------------
    def now(self):
        return self.be.now_et()

    def _wall(self, now=None):
        return calendar.timegm((now or self.now()).timetuple())

    def _coid(self, sym, tag):
        self.seq = (self.seq + 1) % 1000
        return f"LHB{tag}{re.sub(r'[^A-Z0-9]', '', sym)[:6]}{self.now():%H%M%S}{self.seq:03d}"

    def _ui_msg(self, kind, text):
        """Short message on the chart (toast) + the bot log."""
        self._log(text, {"err": "err", "warn": "warn"}.get(kind, "info"))
        self.be.bridge.call("orderMsg", {"kind": kind, "text": text})

    def _net_quiet(self, exc):
        """A network blip (no HTTP answer, already retried) is only logged. Discord hears about it once
        TZ_NET_ALERT_AFTER calls in a row got no answer - and again when TradeZero answers."""
        if getattr(exc, "status", 1) != 0 or self.tz is None:
            return False
        if getattr(self.tz, "net_fail", 0) >= TZ_NET_ALERT_AFTER:
            first = not self.net_alerted
            self.net_alerted = True
            return not first                             # one Discord message per outage
        return True

    def _qid(self, sym, tag="Q"):
        self.seq = (self.seq + 1) % 1000
        return f"LH{tag}-{re.sub(r'[^A-Z0-9]', '', sym)[:6]}-{self.now():%m%d%H%M%S}-{self.seq:03d}"

    def tz_ready(self):
        return self.tz is not None and self.tz_status.get("conn") == "connected" and bool(self.acc)

    def is_paper(self):
        return self.acc_type.lower() == "paper"

    def can_open(self):
        """Why new shorts are not allowed right now ('' = allowed)."""
        if not self.auto:
            return "auto-trade is off"
        if not self.tz_ready():
            return "TradeZero not connected"
        if self.live_blocked():
            return "LIVE account - set ALLOW_LIVE_TRADING = True to trade it"
        if self.flattening:
            return "flattening"
        if self.trades_today >= MAX_BOT_TRADES_PER_DAY:
            return f"daily limit of {MAX_BOT_TRADES_PER_DAY} trades reached"
        sod = _fnum(self.acc_info.get("sodEquity"))
        if (MAX_DAILY_LOSS_PCT and self.day_pnl is not None and sod > 0
                and self.day_pnl <= -MAX_DAILY_LOSS_PCT / 100.0 * sod):
            return f"daily loss limit ({MAX_DAILY_LOSS_PCT:g}% of start-of-day equity) hit"
        return ""

    # ---------------- 3.12: the sizing base ----------------
    def _closed_today(self):
        """(closed trades today, their realized $): the shorts + the premarket long."""
        n, usd = 0, 0.0
        for b in self.syms.values():
            for t in b.trades:
                n += 1
                usd += _fnum(t.get("net"))
        lb = self.longbot
        for row in ((getattr(lb, "closed_rows", None) or []) if lb is not None else []):
            n += 1
            usd += _fnum(row.get("pnl"))
        return n, usd

    def _opens_now(self):
        """Symbols with an open position now (bot shorts and the premarket long)."""
        out = [b.sym for b in self.syms.values() if b.entry and int(b.entry.get("filled") or 0) > 0
               and b.phase in ("working", "short", "manual", "covering")]
        lb = self.longbot
        if lb is not None:
            try:
                out += [t.sym for t in lb.open_longs()]
            except Exception:
                pass
        return out

    def _state_load(self):
        try:
            with open(self._state_file(), encoding="utf-8") as fh:
                st = json.load(fh)
            return st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            return {}

    STATE_KEYS = ("setup", "top", "stop", "stop_live", "limit", "t", "locate_usd", "locate_px", "jr", "avg", "filled",
                  "user_stop", "jr_locked")

    # ---------------- notifications (app log + Discord, with a chart image) ----------------
    def _levels(self, bs):
        e, ent, lv = bs.eng or {}, bs.entry, []
        if ent and ent.get("filled"):
            lv.append({"price": ent.get("avg"), "color": "#d1d4dc", "style": "solid", "title": "entry"})
        if ent and ent.get("stop"):
            lv.append({"price": ent.get("stop_live") or px_round(ent["stop"], True), "color": "#f23645", "style": "dash",
                       "title": "stop" + (" (yours)" if bs.stop_owner == "you" else "")})
        if ent and not ent.get("filled") and ent.get("limit"):
            lv.append({"price": ent["limit"], "color": "#ff9800", "style": "dash", "title": "short limit"})
        p = e.get("pending")
        if p and not ent:
            lv += [{"price": px_round(p["trigger"], False), "color": "#ff9800", "style": "dash", "title": "short limit 12%"},
                   {"price": p["zone_hi"], "color": "#ce93d8", "style": "dot", "title": "zone 10%"},
                   {"price": px_round(p["stop"], True), "color": "#f23645", "style": "dot", "title": "stop if filled"}]
        va = e.get("vac_armed")
        if va and not ent:
            lv += [{"price": va["peak"], "color": "#e040fb", "style": "dot", "title": "vacuum peak"},
                   {"price": va["trigger"], "color": "#e040fb", "style": "dash", "title": "5% pullback"}]
        if e.get("hod"):
            lv.append({"price": e["hod"], "color": "#9598a1", "style": "dot", "title": "HOD"})
        return lv

    def _flow_plan(self, bs, stage, title, marks=None, text=""):
        """What the "stock flow" picture shows right now: the setup the engine sees or the trade in progress."""
        e, ent = bs.eng or {}, bs.entry
        clean = re.sub(r"^[^A-Za-z0-9]+", "", str(title or "")).replace(f"{bs.sym}: ", "").replace(bs.sym, "").strip(" :-")
        st = bs.st
        prior = prior_for(st, st.tc[-1] // 86400) if st and st.tc else None
        last = bs.last_px
        bits = []
        if prior and last:
            bits.append(f"{last / prior * 100 - 100:+.0f}% vs prior close")
        if e.get("gap") is not None:
            bits.append(f"gap {e['gap']:+.0f}% at the open")
        if e.get("vwap") and last:
            bits.append(f"{last / e['vwap'] * 100 - 100:+.0f}% vs VWAP")
        if st and st.tc:
            bits.append(datetime.fromtimestamp(st.tc[-1], timezone.utc).strftime("%H:%M ET"))
        plan = {"title": clean or "watching", "sub": "  ·  ".join(bits), "entry": None, "stop": None, "ref": None,
                "supports": [], "watch": [], "marks": [], "path": False, "entry_tag": ""}
        if stage == "closed":                            # the finished trade: entry and exit only
            for m in marks or []:
                short = m.get("text") == "SHORT"
                plan["marks"].append({"t": m.get("t"), "price": m.get("price"), "text": m.get("text", ""),
                                      "kind": "short" if short else "cover"})
                if short:
                    plan["entry"] = (m.get("price"), "Short")
                else:
                    plan["exit"] = (m.get("price"), f"Covered ({str(m.get('text', '')).lower()})")
            first = str(text or "").split(". The strategy")[0].strip()
            if first:
                plan["sub"] = first + ("." if not first.endswith(".") else "")
            return plan
        p, v, va = e.get("pending"), e.get("vac"), e.get("vac_armed")
        if stage == "skipped":                           # the order is gone: show what the engine sees next
            ent, v = None, None
        jp = bs.jr_plan if stage == "jrsignal" else None
        if jp:                                           # 3.7: a Jay-read signal - the short the read wants now
            sj = jp["s"]
            plan.update(entry=(jp["px"], "Short here"), stop=(px_round(sj["stop"], True), "Stop if filled"), ref=jp["px"],
                        path=True, entry_tag="Jay-read short")
            plan["watch"] += [(sj["ref"], "Level" if sj["setup"] == "level" else "Overhead high"), (sj["rth_high"], "RTH high")]
            plan["supports"].append((sj["crack_low"], "crack low"))
        elif ent and ent.get("filled"):                  # in the short
            stop = ent.get("stop_live") or px_round(ent["stop"], True)
            plan.update(entry=(ent["avg"], "Entry"), stop=(stop, "Your stop" if bs.stop_owner == "you" else "Stop"),
                        ref=min(ent["avg"], last or ent["avg"]), path="down")
            plan["marks"].append({"t": ent.get("t", 0) // 60 * 60, "price": ent["avg"],
                                  "text": f"SHORT {ent['filled']:,}", "kind": "short"})
            if bs.phase == "manual":
                plan["stop"] = None
        elif ent:                                        # short order working (or locating for it)
            lim = ent.get("limit") or ent.get("trigger")
            plan.update(entry=(lim, "Short limit"), stop=(px_round(ent["stop"], True), "Stop if filled"), ref=lim,
                        path=True, entry_tag="Short here")
        elif v and stage in ("signal", "locate", None):  # vacuum signal: short at the next open
            plan.update(entry=(last or v["trigger"], "Short now"), stop=(px_round(v["stop"], True), "Stop if filled"),
                        ref=last or v["trigger"], path=True, entry_tag="Vacuum short")
            plan["watch"].append((v["peak"], "Vacuum peak"))
        elif p:                                          # bounce-zone limit resting 12% under the top
            plan.update(entry=(px_round(p["trigger"], False), "Short limit 12%"),
                        stop=(px_round(p["stop"], True), "Stop if filled"), ref=p["trigger"], path=True,
                        entry_tag="Short the bounce")
            plan["watch"] += [(p["top"], "Top"), (p["zone_hi"], "Zone top 10%")]
            if p.get("dip"):
                plan["supports"].append((p["top"] * (1 - p["dip"] / 100.0), "dip low"))
        elif va:                                         # vacuum trap armed: short on a close under the trigger
            stop = va["peak"] * (1 + getattr(STRAT, "VAC_STOP_ABOVE_PEAK_PCT", 3.0) / 100.0)
            plan.update(entry=(va["trigger"], "Short below"), stop=(px_round(stop, True), "Stop if filled"),
                        ref=va["trigger"], path=True, entry_tag="Vacuum short")
            plan["watch"].append((va["peak"], "Vacuum peak"))
        elif jr_mode():                                  # 3.7: Jay-read - the regular-hours high and the crack low
            if bs.jr is not None and bs.jr.reader.rh > 0 and not math.isinf(bs.jr.reader.rh):
                plan["watch"].append((bs.jr.reader.rh, "RTH high"))
            if bs.jr_ctx:
                plan["supports"].append((bs.jr_ctx["low"], "crack low"))
        else:                                            # nothing set up yet: where the bot starts to act
            vw = e.get("vwap")
            if not vw and st and st.tc:
                vw = next((r[6] for r in reversed(chart_rows_today(st)) if r[6]), None)
            if vw:
                plan["watch"].append((vw * (1 + PRELOCATE_VWAP_PCT / 100.0), f"VWAP +{PRELOCATE_VWAP_PCT:g}%"
                                      + ("" if (bs.pre_req or bs.pre_done) else " = locate")))
        if bs.phase == "locating":
            plan["title"] = clean or "locating shares"
        for m in marks or []:                            # marks the message adds (skipped signal ...)
            if m.get("text") and m.get("text") != "SHORT":
                plan["marks"].append({"t": m.get("t"), "price": m.get("price"), "text": m["text"], "kind": "other"})
        if st and st.tc:                                 # the pre-market high is a support once the price is above it
            pm = [r[2] for r in chart_rows_today(st) if (r[0] % 86400) < 570 * 60]
            if pm:
                plan["supports"].append((max(pm), "pre-market high"))
        return plan

    def _hello(self):
        """3.10: BOT STARTED - what trades, what only alerts, sizes, connections (no account id)."""
        self.hello_sent = True
        ib = self.be.ib
        ibs = "connected" if ib is not None and ib.isConnected() else "not connected yet"
        acct = self.acc_type or ("not connected" if not self.acc else "")
        tzs = f"TradeZero {acct} connected" if self.tz_ready() else self.tz_status.get("text", "TradeZero: -")
        win = {"long": (f"{LP.SCAN_START}-{LP.FLATTEN_AT[:5]}" if LP is not None else ""),
               "jr": (f"{JR.SIGNAL_START}-{JR.SIGNAL_END}" if JR is not None else ""),
               "jr2": (f"{JR2.SIGNAL_START}-{JR2.SIGNAL_END}" if JR2 is not None else ""),
               "sq": (f"{SQ.SIGNAL_START}-{SQ.SIGNAL_END}" if sq_on() else "")}
        fields = []
        for k in MODE_KEYS:
            if (k == "sq" and not sq_on()) or (k == "jr2" and JR2 is None):
                continue
            if k == "long" and (not LONG_PREMARKET or self.longbot is None):
                fields.append((MODE_NAMES[k], "NOT RUNNING" + (f"\n{LP_IMPORT_ERROR}" if LP_IMPORT_ERROR else ""), True))
                continue
            m = mode(k)
            fields.append((MODE_NAMES[k], {"trading": "TRADING", "alert": "ALERT ONLY", "off": "OFF"}[m] + "\n"
                           + ({"trading": win[k], "alert": "no orders", "off": "not watched"}[m] or "-"), True))
        if jr_mode() and JR is None:
            fields.append(("Jay-read short", f"NOT LOADED: {JR_IMPORT_ERROR} - put {JAY_READ_FILE} next to the app", False))
        long_sz = (f"Long {LP.ACCOUNT_PCT:g}% (max ${LP.MAX_POSITION_USD / 1000:,.0f}k)\n" if LP is not None else "")
        fields += [("Size", long_sz + f"Short {ACCOUNT_PCT:g}% (max ${MAX_POSITION_USD / 1000:,.0f}k)", True),
                   ("Locates", f"bot max {MAX_LOCATE_PCT:g}% of price", True),
                   ("Watchlist", (", ".join(self.syms) or "empty")
                    + (f"\n+ scanner {SHORT_SCAN_START}" if jr_mode() and SHORT_SCANNER else ""), True),
                   ("Close", (f"shorts covered at {JR_EOD_COVER_TIME}" if JR_EOD_COVER_TIME
                              else f"no automatic cover - alert at {EOD_ALERT_TIME}"), True),
                   ("Connections", f"IB Gateway {ibs}  ·  {tzs}  ·  Discord OK", False)]
        nt = not_trading()
        if not nt:
            title = "Every strategy is trading"
            desc = f"Auto-trade is {'ON' if self.auto else 'OFF'}."
        else:
            title = "Not trading now: " + ", ".join(f"{MODE_NAMES[k]} ({MODE_TEXT[m].lower()})" for k, m in nt)
            tr = [MODE_NAMES[k].lower() for k in MODE_KEYS if mode(k) == "trading" and (k != "sq" or sq_on())]
            desc = (f"Auto-trade is {'ON' if self.auto else 'OFF'}."
                    + (f" The {' and the '.join(tr)} place{'s' if len(tr) == 1 else ''} orders." if tr else "")
                    + "\nTurn one on in the app: menu → Trading mode → Trading.")
        if not self.auto:
            desc += "\nAuto-trade is OFF - no strategy places orders until you switch it on (menu → Auto-trade)."
        kind = "warn" if nt or not self.auto else "info"
        self._notify(title, desc, kind, fields=fields, who="System",
                     tag=f"BOT STARTED  ·  {APP_VERSION}" + (f"  ·  {self.acc_type.upper()}" if self.acc_type else ""))

    # ---------------- commands from the page (any thread) ----------------
    def cmd(self, fn, *a):
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(fn(*a)))

    async def add(self, sym, auto=False):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        if not sym or sym in self.syms:
            return
        if len(self.syms) >= MAX_WATCHLIST:
            self._log(f"watchlist is full ({MAX_WATCHLIST} symbols) - remove one first", "warn")
            return
        self.syms[sym] = BotSym(sym)
        self.syms[sym].auto_added = bool(auto)
        self.settings.set("watchlist", list(self.syms))
        a = dict(self.settings.get("auto_syms", {}) or {})
        if auto:
            a[sym] = str(self.now().date())
        else:
            a.pop(sym, None)
        self.settings.set("auto_syms", a)
        self._notify(f"{sym}", (f"Scanner: up {SHORT_SCAN_MIN_UP_PCT:g}%+ from the prior close at {self.now():%H:%M}. "
                                if auto else "Added in the app. ") + "Reading its chart from 04:00.", "dim",
                     tag="ADDED TO WATCHLIST", who="Shorts")
        self._push(force=True)

    async def remove(self, sym):
        bs = self.syms.get(sym)
        if bs is None:
            return
        if bs.phase != "idle":
            self._log(f"{sym} has an order or a position ({bs.phase}) - close it before removing it", "warn")
            return
        self._unsub(bs)
        del self.syms[sym]
        self.scan_seen.add(sym)                          # 3.7: the scanner does not put it back today
        self.settings.set("watchlist", list(self.syms))
        a = dict(self.settings.get("auto_syms", {}) or {})
        if a.pop(sym, None) is not None:
            self.settings.set("auto_syms", a)
        self._notify(f"{sym}", "", "dim", tag="REMOVED FROM WATCHLIST", who="Shorts")
        self._push(force=True)

    async def set_auto(self, on):
        on = bool(on)
        if on and self.live_blocked():
            self._log("This is a LIVE account. Set ALLOW_LIVE_TRADING = True in the app settings to let the bot trade it.", "err")
            self.auto = False
        elif on and not self.tz_ready():
            self._log("Connect TradeZero first (keys) - auto-trade stays off", "warn")
            self.auto = False
        elif on != self.auto:
            self.auto = on
            nt = not_trading()
            self._notify("Auto-trade ON - the bot places orders" if on else "Auto-trade OFF - no new orders",
                         (("Not trading: " + ", ".join(f"{MODE_NAMES[k]} ({MODE_TEXT[m].lower()})" for k, m in nt) + ".")
                          if on and nt else "") if on else
                         "Working entry orders are cancelled. Open shorts keep their stop.",
                         "info" if on else "warn", tag="AUTO-TRADE", who="System")
        self._push(force=True)

    def long_mode(self):
        """3.10: the premarket long's trading mode (the long module reads it at start-up)."""
        return mode("long")

    async def set_mode(self, key, value):
        """3.10: menu -> Trading mode. Saved at once (settings.json) - no rebuild, no restart."""
        if key not in MODE_KEYS or value not in MODE_VALUES:
            return
        old = mode(key)
        if key == "long" and not LONG_PREMARKET:
            self._log("The premarket long is not started (LONG_PREMARKET = False)", "warn")
            self._push(force=True)
            return
        if old == value:
            self._push(force=True)
            return
        saved = dict(self.settings.get("modes", {}) or {})
        saved[key] = value
        self.settings.set("modes", saved)
        set_modes(saved)
        if key == "long" and self.longbot is not None:
            self.longbot.set_mode(value)
        if key in ("jr2", "jr", "sq"):                   # 3.13.0: the short book holds the strategies that are not Off -
            for bs in self.syms.values():                # rebuilt from today's candles on the next candle (idle stocks;
                b = bs.jr                                # a stock with an order / position keeps its book until flat)
                if b is not None and bs.phase == "idle" and b.pos is None and b.awaiting is None and bs.jr_sig is None:
                    bs.jr = None
        nt = not_trading()
        after = {"trading": f"The next {MODE_NAMES[key]} signal places a real order.",
                 "alert": "Its signals go to Discord as alerts - no orders.",
                 "off": "Its signals are not traded and not posted."}[value]
        tail = (" Every strategy now trades." if not nt else
                " Not trading: " + ", ".join(f"{MODE_NAMES[k]} ({MODE_TEXT[m].lower()})" for k, m in nt) + ".")
        if value == "trading" and not self.auto:
            tail += " Auto-trade is OFF - turn it on in the menu to place orders."
        self._notify(f"{MODE_NAMES[key]}: {MODE_TEXT[old]} → {MODE_TEXT[value]}", "Changed in the app. " + after + tail,
                     "info", tag="MODE CHANGED", who="System")
        self._push(force=True)

    async def close_for_exit(self):
        """3.9.0: you close the app and answered Yes - auto-trade off, every bot order and stop cancelled, every position
        closed at market (shorts bought back, longs sold). The app closes once nothing is open."""
        self.auto = False
        opens = self.open_positions()
        self._notify("Closing every position at market",
                     ("\n".join(f"{o['sym']} {o['side']} {o['qty']:,}" + (f" - stop {_fp(o['stop'])} cancelled" if o.get('stop')
                                                                          and o['side'] == 'short' else "")
                                for o in opens) or "Nothing open.") + "\nAuto-trade OFF - the app closes once nothing is open.",
                     "warn", tag="APP CLOSING  ·  YOU CHOSE: CLOSE EVERYTHING", who="System")
        for bs in list(self.syms.values()):
            bs.hunt = None
            if bs.phase in ("working", "short", "manual"):
                await self._flatten_one(bs, "App closed - you chose to close")
        if self.longbot is not None:
            await self.longbot.flatten_all("App closed")
        self._push(force=True)

    # ---------------- IB data per symbol ----------------
    def _unsub(self, bs):
        st = bs.st
        bs.st = None
        ib = self.be.ib
        if st is None:
            return
        try:
            if st.bars is not None and st.h_bars is not None:
                st.bars.updateEvent -= st.h_bars
            if bs.ticker is not None and st.h_tick is not None:
                bs.ticker.updateEvent -= st.h_tick
        except Exception:
            pass
        if ib is not None and ib.isConnected():
            try:
                ib.cancelHistoricalData(st.bars)
            except Exception:
                pass
            try:
                ib.cancelMktData(st.contract)
            except Exception:
                pass
        bs.ticker = None

    async def _load(self, bs):
        ib = self.be.ib
        if ib is None or not ib.isConnected() or bs.loading:
            return
        bs.loading = True
        bs.status, bs.kind = "Loading candles...", "dim"
        try:
            self._unsub(bs)
            details = await asyncio.wait_for(ib.reqContractDetailsAsync(Stock(bs.sym.replace(".", " "), "SMART", "USD")), 20)
            if not details:
                bs.load_err = "symbol not found at IBKR"
                bs.next_load = time.monotonic() + 300
                self._notify(f"❌ {bs.sym}: symbol not found at IBKR", "Check the ticker.", "err")
                return
            cd = pick_details(details)
            contract = cd.contract
            contract.exchange = "SMART"
            daily = await asyncio.wait_for(ib.reqHistoricalDataAsync(
                contract, endDateTime="", durationStr="15 D", barSizeSetting="1 day",
                whatToShow="TRADES", useRTH=True, formatDate=1), 30)
            bars = await asyncio.wait_for(ib.reqHistoricalDataAsync(
                contract, endDateTime="", durationStr="2 D", barSizeSetting="1 min",
                whatToShow="TRADES", useRTH=False, formatDate=2, keepUpToDate=True), 120)
            if not bars:
                bs.load_err = "no 1-minute data from IB"
                bs.next_load = time.monotonic() + 60
                return
            st = SymState(0, bs.sym, contract, cd.longName or "", contract.primaryExchange or "")
            st.bars = bars
            st.tc = [ctime(b.date) for b in bars]
            st.prior = prior_closes(daily, st.tc, bars)
            st.loaded_day = self._wall() // 86400

            def on_bars(blist, has_new, bs=bs, st=st):
                try:
                    bs.last_bar_wall = time.monotonic()
                    if has_new or len(st.tc) != len(blist):
                        st.tc = [ctime(x.date) for x in blist]
                    elif st.tc:
                        st.tc[-1] = ctime(blist[-1].date)
                except Exception:
                    log.exception("bot bars %s", bs.sym)

            def on_tick(tk, bs=bs):
                try:
                    self._on_quote(bs, tk)                # 3.12: prices + the halt / reopen (see _on_quote)
                except Exception:
                    log.exception("bot tick %s", bs.sym)

            st.h_bars, st.h_tick = on_bars, on_tick
            bars.updateEvent += on_bars
            try:
                bs.ticker = ib.reqMktData(contract, "", False, False)
                bs.ticker.updateEvent += on_tick
            except Exception:
                log.exception("bot reqMktData %s", bs.sym)
            bs.st = st
            bs.load_err = ""
            bs.data_lost_at = None
            bs.last_bar_wall = time.monotonic()
            bs.eng_key = None
            if bs.last_px is None:
                bs.last_px = float(bars[-1].close)
            self._log(f"{bs.sym}: candles loaded ({len(bars)} bars)")
            if not bs.loaded_msg:
                bs.loaded_msg = True
                rows = chart_rows_today(st)
                dn = st.tc[-1] // 86400
                pc = prior_for(st, dn)
                hod = max((r[2] for r in rows), default=None)
                vol = sum(r[5] for r in rows)
                last = bs.last_px
                f = [("Last", _fp(last), True), ("Prior close", _fp(pc), True),
                     ("Change", f"{(last / pc - 1) * 100:+.0f}%" if pc and last else "-", True),
                     ("HOD", _fp(hod), True), ("VWAP", _fp(rows[-1][6]) if rows and rows[-1][6] else "-", True),
                     ("Volume today", _fmt_shares(vol) if vol else "0", True)]
                self._notify(f"\U0001F4C8 {bs.sym}: analysis running", f"{cd.longName or ''} {contract.primaryExchange or ''}".strip(),
                             "info", bs=bs, fields=f, chart=True, critical=True)
        except Exception as exc:
            bs.load_err = f"load failed ({exc.__class__.__name__})"
            bs.next_load = time.monotonic() + 30
            log.exception("bot load %s", bs.sym)
        finally:
            bs.loading = False

    def _open_lines(self, brief=False):
        """3.10: every open position with what protects it (Discord connection messages). brief = the status line:
        shares, average, last, stop, unrealized."""
        out = []
        for b in self.syms.values():
            ent = b.entry or {}
            if b.phase in ("short", "manual", "covering") and ent.get("filled"):
                stop = ent.get("stop_live") or (px_round(ent["stop"], True) if ent.get("stop") else None)
                if brief:
                    last, q, a = b.last_px, ent["filled"], _fnum(ent.get("avg"))
                    out.append(f"{b.sym} short {q:,} @ {_fp(a)}  ·  last {_fp(last)}  ·  stop "
                               + (_fp(stop) if stop and b.phase != "manual" else "NONE")
                               + (f"  ·  {_pm((a - last) * q)}" if last else ""))
                    continue
                out.append(f"{b.sym} short {ent['filled']:,} @ {_fp(ent.get('avg'))} - "
                           + (f"its stop {_fp(stop)} at TradeZero still protects it" if stop and b.phase != "manual"
                              else "NO stop order at TradeZero"))
        lb = self.longbot
        if lb is not None:
            try:
                for t in lb.open_longs():
                    p = t.day.pos
                    out.append(f"{t.sym} long {int(p.shares):,} @ {_fp(p.entry)}  ·  stop {_fp(p.stop)}" if brief else
                               f"{t.sym} long {int(p.shares):,} @ {_fp(p.entry)} - stop {_fp(p.stop)} is watched by "
                               f"the app (no stop order at TradeZero)")
            except Exception:
                log.exception("open longs")
        return out

    def on_ib_link(self, up):
        """3.10: IB Gateway lost / got back its link to IBKR's servers (error 1100 / 1101-1102)."""
        mono = time.monotonic()
        if not up and self.ib_link_down is None:
            self.ib_link_down = mono
            self._notify("IB Gateway is up but lost IBKR - no live data", "Usually back within a minute. New entries "
                         "paused until data flows again.", "warn", tag="IBKR SERVERS NOT REACHABLE", who="System")
        elif up and self.ib_link_down is not None:
            mins = (mono - self.ib_link_down) / 60.0
            self.ib_link_down = None
            self._notify(f"IBKR servers reachable again after {mins:.0f} min" if mins >= 1 else
                         "IBKR servers reachable again", "Live data flows again.", "ok", tag="IBKR BACK", who="System")

    def on_ib_disconnected(self):
        mono = time.monotonic()
        if self.ib_down_since is None:
            self.ib_down_since = mono
            self.ib_down_alerted = False
            opens = self._open_lines()
            self._notify("No live data - the bot cannot see prices",
                         f"The app lost IB Gateway at {self.now():%H:%M:%S}. Reconnecting every 20 s.", "err",
                         tag="IB GATEWAY DISCONNECTED", who="System", ping=True,
                         fields=[("Open now", "\n".join(opens) if opens else "nothing open", False),
                                 ("Paused", "new entries, locate search, lock moves; resting entry orders are cancelled "
                                            "after 20 s", False)])
        for bs in self.syms.values():
            bs.st, bs.ticker = None, None
            if bs.data_lost_at is None:
                bs.data_lost_at = mono

    # ---------------- engine ----------------
    async def _run_engine(self, bs, cur_min):
        st = bs.st
        if st is None or not st.tc:
            return
        dn = cur_min // 86400
        tc = st.tc
        a = len(tc)
        while a > 0 and tc[a - 1] // 86400 == dn:
            a -= 1
        b = len(tc)
        while b > a and tc[b - 1] >= cur_min:            # the forming candle is not used (decided at the close)
            b -= 1
        if b <= a:
            bs.eng = {"pending": None, "vac": None, "vac_armed": None, "trades": [], "hod": None, "gap": None,
                      "gapOk": False, "block": "no candles today yet", "vol": 0.0, "bars": 0, "vwap": None, "close": None}
            return
        frame = make_frame(st, a, b)
        has_rth = any(is_rth(t) for t in tc[a:b])
        prior = prior_for(st, dn)
        if jr_mode():                                    # 3.7.0: the Jay-read short (the v16 engine is parked)
            bs.eng = jr_eng_info(frame, has_rth, prior)
            if jr_ready() and prior:
                try:
                    self._jr_feed(bs, frame, dn, prior)
                except Exception:
                    log.exception("jay-read feed %s", bs.sym)
            return
        try:
            bs.eng = await self.loop.run_in_executor(self.be.pool, bot_engine, bs.sym, frame, day_date(dn), prior, has_rth,
                                                     frozenset(bs.void))
        except Exception:
            log.exception("bot engine %s", bs.sym)
            return
        self._setup_events(bs)

    def _setup_events(self, bs):
        """Report a newly armed bounce limit / vacuum trap once, with the chart."""
        e = bs.eng or {}
        p = e.get("pending")
        if p and ("B", round(p["trigger"], 6)) not in bs.seen_armed and bs.phase == "idle":
            bs.seen_armed.add(("B", round(p["trigger"], 6)))
            why = self.can_open()
            self._notify(f"\U0001F3AF {bs.sym}: BOUNCE-ZONE armed",
                         f"Top {_fp(p['top'])} dipped {p['dip']:.0f}%. Short limit {_fp(px_round(p['trigger'], False))} "
                         f"(12% under the top), stop if filled {_fp(px_round(p['stop'], True))}. Zone {p['ext']:.0f}% above VWAP."
                         + (f"\nNo order: {why}" if why else ""), "trade", bs=bs, chart=True, critical=True)
        va = e.get("vac_armed")
        if va and not self._vac_open():
            va = None                                    # after VAC_LAST_ENTRY_TIME the trap can no longer trade
        sk = e.get("vac_skip")
        if sk and ("S", sk["key"]) not in bs.seen_armed and not sk["reason"].startswith("outside"):
            bs.seen_armed.add(("S", sk["key"]))
            if any(w in sk["reason"] for w in ("climax", "staircase", "stop-out")):
                self._notify(f"\u23ED {bs.sym}: vacuum signal skipped", sk["reason"][:300], "dim", bs=bs, chart=True,
                             marks=[{"t": sk["t"], "price": sk["price"], "text": "SKIP", "color": "#9598a1"}])
        if va and ("V", va["arm_idx"]) not in bs.seen_armed and bs.phase == "idle":
            bs.seen_armed.add(("V", va["arm_idx"]))
            vw = e.get("vwap")
            self._notify(f"\U0001F9F2 {bs.sym}: VACUUM trap armed",
                         f"High {(va['peak'] / vw - 1) * 100:.0f}% above VWAP on dying volume. Short signal when a candle closes "
                         f"under {_fp(va['trigger'])} ({STRAT.VAC_PULLBACK_PCT:g}% under the peak {_fp(va['peak'])})."
                         if vw else "", "trade", bs=bs, chart=True, critical=True)

    def _vac_open(self):
        """Vacuum shorts can still fill now (before VAC_LAST_ENTRY_TIME)."""
        return getattr(STRAT, "VACUUM_ENABLED", False) and \
            self._wall() % 86400 <= _secs(getattr(STRAT, "VAC_LAST_ENTRY_TIME", "15:30"))

    def _drop_old_auto(self):
        """New day: symbols the scanner added on an earlier day leave the watchlist (unless an order / short is open)."""
        if not SHORT_SCAN_DROP_NEXT_DAY:
            return
        today = str(self.now().date())
        a = dict(self.settings.get("auto_syms", {}) or {})
        gone = []
        for sym, d in list(a.items()):
            bs = self.syms.get(sym)
            if d >= today:
                continue
            if bs is not None and bs.phase != "idle":
                continue
            if bs is not None:
                self._unsub(bs)
                del self.syms[sym]
                gone.append(sym)
            a.pop(sym, None)
        if gone:
            self.settings.set("watchlist", list(self.syms))
            self._log(f"short scanner: removed yesterday's symbols {', '.join(gone)}")
        self.settings.set("auto_syms", a)

    # ---------------- 3.7.0 / 3.9.0: the Jay-read + max squeeze shorts (jay_read_short.py / max_squeeze_short.py) ---------
    def _jr_feed(self, bs, frame, dn, prior):
        """Feed today's closed candles (with trades) to the symbol's short book (Jay-read + max squeeze) once each. A new
        book (warmup with every candle since 04:00) when the symbol is added / the day starts. If IB revised a candle
        already fed, the chart reads are rebuilt from the candles (the trade state is kept); only new candles produce
        events."""
        rows = [(r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                for r in frame.itertuples(index=False, name=None) if r[5] and r[5] > 0]
        fp = [(r[0].value, r[1], r[2], r[3], r[4], r[5]) for r in rows]
        if bs.jr is None or bs.jr_dn != dn:
            bs.jr = make_book(bs.sym, prior, live=True)
            bs.jr_dn = dn
            bs.jr.warmup(rows)
            bs.jr_fp = fp
            self._jr_restore(bs)
            names = " + ".join(("Jay-read 2" if type(p).__name__ == "JayRead2Short" else "max squeeze"
                                if p.cfg.get("CODE") == "SQ" else "Jay-read v1.2") for p in getattr(bs.jr, "parts", [bs.jr]))
            self._log(f"{bs.sym}: {names} read started ({len(rows)} candles "
                      f"since 04:00, prior close {_fp(prior)})")
            self._jr_context(bs)
            return
        n0 = len(bs.jr_fp)
        if fp[:n0] != bs.jr_fp:                          # IB changed / dropped a candle we already read
            keep = min(n0, len(fp))
            if hasattr(bs.jr, "rebuild"):
                bs.jr.rebuild(rows[:keep])
            else:
                bs.jr.reader = JR.JayReader(prior, bs.jr.cfg)
                for t, o, h, l, c, v in rows[:keep]:
                    bs.jr.reader.add_bar(t, t.hour * 60 + t.minute, o, h, l, c, v)
            self._log(f"{bs.sym}: IB revised a candle already read - the chart read is rebuilt", "warn")
            n0 = keep
        new = rows[n0:]
        bs.jr_fp = fp
        for i, (t, o, h, l, c, v) in enumerate(new):
            if bs.jr_virtual is not None:               # ALERT_ONLY: the would-be short meets this candle first
                self._jr_virtual_bar(bs, t, o, h, l, c)
            for e in bs.jr.on_bar(t, o, h, l, c, v):
                self._jr_event(bs, e, last=i == len(new) - 1)
        self._jr_context(bs)

    def _jr_event(self, bs, e, last=True):
        typ = e["type"]
        if typ == "SIGNAL":
            s = e["signal"]
            name = JR_SETUP_NAME.get(s.get("setup"), "short")
            if not last:                                 # a candle that arrived late (data gap): too old to trade
                bs.jr.entry_cancelled()
                self._log(f"{bs.sym}: {name} signal at {jr_hm(e['time'])} came in late (data catch-up) - skipped", "warn")
                return
            pre_search = bs.phase == "locating" and (bs.hunt or {}).get("mode") == "pre"
            if (bs.phase != "idle" and not pre_search) or bs.jr_sig is not None:
                bs.jr.entry_cancelled()
                self._log(f"{bs.sym}: {name} signal at {jr_hm(e['time'])} while the bot is busy here ({bs.phase}) - skipped")
                return
            bs.jr_sig = {"sig": s, "wall": self._wall(), "t": e["time"], "mono": time.monotonic()}
            k = "sq" if s.get("setup") == "squeeze" else "jr2" if str(s.get("setup")).startswith("jr2") else "jr"
            self.sig_today[k] = self.sig_today.get(k, 0) + 1
        elif typ == "STOP_MOVED":
            if bs.jr_virtual is not None:               # ALERT_ONLY: the would-be stop moves (no order)
                vt = bs.jr_virtual
                vt["stop"], vt["locked"] = float(e["stop"]), True
                self._notify(f"\U0001F47B {bs.sym}: alert trade - the lock would move the stop to {_fp(vt['stop'])}",
                             f"Faded {JR.LOCK_AFTER_PCT:g}% from the would-be entry {_fp(vt['entry'])}: stop to "
                             f"{JR.lock_text(JR.LOCK_STOP_PCT)}. ALERT ONLY - no order.", "info", bs=bs)
            else:
                bs.jr_lock = float(e["stop"])
        elif typ == "COVER_ALL":
            if bs.jr_virtual is None:
                bs.jr_eod = True
        elif typ == "SKIP":
            s = e.get("signal") or {}
            self._log(f"{bs.sym}: {JR_SETUP_NAME.get(s.get('setup'), 'short')} signal at {jr_hm(e['time'])} not taken - "
                      f"{e.get('reason', '')}")

    def _jr_virtual_bar(self, bs, t, o, h, l, c):
        """ALERT_ONLY: the would-be short against one new closed candle - the backtest's rules: from 15:55 covered at the
        candle's open; a candle opening at/over the stop = covered at its open, a high reaching it = at the stop."""
        vt, jr = bs.jr_virtual, bs.jr
        if vt is None or jr is None or jr.pos is None:
            bs.jr_virtual = None
            return
        m = t.hour * 60 + t.minute
        eod = JR._min(JR.EOD_COVER_TIME) if JR.EOD_COVER_TIME else 955
        if m >= eod:
            px, why = o, "EOD"
        elif o >= vt["stop"]:
            px, why = o, "STOP"
        elif h >= vt["stop"]:
            px, why = vt["stop"], "STOP"
        else:
            return
        out = jr.cover_filled(1.0, px, why, t)
        reason = out[-1]["reason"] if out else why
        bs.jr_virtual = None
        qty = vt["qty"]
        gross = (vt["entry"] - px) * qty
        fee = vt["entry"] * qty * JR.LOCATE_FEE_PCT / 100.0
        risk = (jr.trades[-1].stop0 - vt["entry"]) * qty if jr.trades else 0.0
        net = gross - fee
        self.jr_alert_trades.append({"sym": bs.sym, "name": vt["name"], "qty": qty, "entry": vt["entry"], "exit": px,
                                     "reason": reason, "net": net, "R": net / risk if risk > 0 else 0.0})
        note = jr_done_note(jr, bs.sym)
        self._notify(f"{bs.sym} would be {_pm(net)}  ·  {net / risk if risk > 0 else 0:+.1f}R",
                     f"Short {_fp(vt['entry'])} → {_fp(px)} at {jr_hm(t)} ({reason.lower()}). About {_money(net)} after a "
                     f"{JR.LOCATE_FEE_PCT:g}% locate. No order was placed (alert only)." + (f" {note}" if note else ""),
                     "dim", bs=bs, chart=True, critical=True, tag="ALERT TRADE CLOSED",
                     stage="closed", levels=[],
                     marks=[{"t": vt["t"] // 60 * 60, "price": vt["entry"], "text": "SHORT", "color": "#e040fb"},
                            {"t": calendar.timegm(t.timetuple()) // 60 * 60, "price": px, "text": reason,
                             "color": "#26a69a", "up": True}])

    def _jr_context(self, bs):
        """Where the reads are right now (status line, pre-locate): bs.jr_ctx = the Jay-read 'momentum broke' numbers,
        bs.sq_ctx = 3.9.0 the max squeeze numbers once a squeeze is on (up MIN_UP_PCT+, SQUEEZE_PCT+ over the level)."""
        bs.jr_ctx = bs.sq_ctx = None
        book = bs.jr
        rd = book.reader if book is not None else None
        if rd is None or not len(rd.o):
            return
        try:
            ctx = rd._context(len(rd.o) - 1)
        except Exception:
            ctx = None
        if ctx is not None:
            RH, k_rh, LO, k_lo = ctx
            bs.jr_ctx = {"rh": RH, "low": LO, "crack": 1 - LO / RH, "age": rd.m[-1] - rd.m[k_rh]}
        sq = getattr(book, "sq", None)
        if sq is not None and len(sq.reader.o) and sq.reader.pc:
            try:
                st = sq.reader.state()
            except Exception:
                st = None
            if st is not None:
                lvl, _, top, _ = st
                up = sq.reader.hod / sq.reader.pc - 1.0
                if up * 100.0 >= sq.cfg["MIN_UP_PCT"] and top >= lvl * (1 + sq.cfg["SQUEEZE_PCT"] / 100.0):
                    bs.sq_ctx = {"level": lvl, "top": top, "sq": top / lvl - 1.0, "up": up,
                                 "stop": top * (1 + sq.cfg["STOP_OVER_TOP_PCT"] / 100.0)}

    def _jr_restore(self, bs):
        """App restarted mid-day: today's short trades of this symbol from the journal. A stop-out = done for the day (both
        shorts: a stop-out ends the stock); a strategy at its max trades = that one is done (the book starts fresh, the
        journal remembers)."""
        try:
            if not os.path.exists(self.journal):
                return
            rows = pd.read_csv(self.journal, dtype=str).fillna("")
        except Exception:
            return
        today = str(self.now().date())
        mine = rows[(rows["date"] == today) & (rows["symbol"] == bs.sym)
                    & rows["setup"].isin(["JR_A", "JR_B", "SQ", "JR2_G", "JR2_S"])]
        if not len(mine):
            return
        book = bs.jr
        msgs = []
        parts = []
        if getattr(book, "jr2", None) is not None:       # 3.13.0: Jay-read 2
            parts.append((("JR2_G", "JR2_S"), book.jr2, "Jay-read 2"))
        if getattr(book, "jr2", None) is None or getattr(book, "jr1", None) is not None:
            parts.append((("JR_A", "JR_B"), jr_part(book, "rollover"), "Jay-read"))
        if getattr(book, "sq", None) is not None:
            parts.append((("SQ",), book.sq, "max squeeze"))
        for codes, part, label in parts:
            m = mine[mine["setup"].isin(codes)]
            if not len(m):
                continue
            stopped = bool(m["exit_reason"].isin(["Stop", "Your stop", "Stop rejected"]).any())
            if stopped or len(m) >= part.cfg["MAX_TRADES_PER_DAY"]:
                part.done = True
                if stopped:
                    part._stop_rh = float("inf")         # stopped out today (no re-entry)
            msgs.append(f"{len(m)} {label} trade(s){' incl. a stop-out' if stopped else ''}")
        if hasattr(book, "_sync_done"):
            book._sync_done()
        if msgs:
            self._log(f"{bs.sym}: journal - {', '.join(msgs)} today"
                      + (": done for the day" if jr_finished(book) else ""))

    def _jr_read_text(self, bs, rd):
        """The Jay-read part of the status line."""
        M, lb = jrm(), jr_label()                         # 3.13.0: Jay-read 2's rules when it is on
        jp = bs.jr.jr2 if getattr(bs.jr, "jr2", None) is not None else jr_part(bs.jr, "rollover")
        if jp.done:
            return f"{lb}: done for the day (stopped out)", "done"
        if len(jp.trades) >= M.MAX_TRADES_PER_DAY:
            return f"{lb}: done for the day ({M.MAX_TRADES_PER_DAY} trades)", "done"
        up = rd.hod / rd.pc * 100.0 - 100.0 if rd.pc else 0.0
        d = f"+{up:.0f}%, ${rd.dollar / 1e6:,.0f}M"
        if rd.i0 is None:
            return f"{lb}: pre-market {d}", "dim"
        if up < M.MIN_UP_PCT:
            return f"{lb}: up only {up:+.0f}% (needs +{M.MIN_UP_PCT:g}%)", "dim"
        if rd.dollar < M.MIN_DOLLAR_VOL:
            return f"{lb}: {d} traded (needs ${M.MIN_DOLLAR_VOL / 1e6:g}M)", "watch"
        if M.MAX_HALT_JUMPS is not None and rd.halt_jumps >= M.MAX_HALT_JUMPS:
            return f"{lb}: halt game ({rd.halt_jumps} halts) - no read", "dim"
        if bs.jr_ctx:
            c = bs.jr_ctx
            return (f"{lb} {d}: momentum broke - cracked -{c['crack'] * 100:.0f}% from {_fp(c['rh'])}; "
                    f"" + ("waiting for the first bounce to fail near the top" if M is JR2 and JR2 is not None else "waiting for a bounce to roll over / hit a level") + ""), "armed"
        age = rd.m[-1] - rd.m[rd.k_rh] if rd.k_rh >= 0 else 0
        if age < M.HOD_MIN_AGE_MIN:
            return f"{lb} {d}: front side - high {_fp(rd.rh)} only {age} min old", "watch"
        off = (1 - rd.c[len(rd.c) - 1] / rd.rh) * 100.0 if rd.rh > 0 else 0.0
        if M is JR2 and JR2 is not None and off >= M.MIN_CRACK_PCT:    # 3.13.0: cracked, but a rule is not met yet
            why = ("the flush low has not reached VWAP (spiker)" if getattr(rd, "kind", "") == "spiker"
                   else f"the flush is outside {JR2.SETTINGS['GAPPER']['CRACK_MIN']:g}-{JR2.SETTINGS['GAPPER']['CRACK_MAX']:g}%")
            return f"{lb} {d}: {off:.0f}% under the high {_fp(rd.rh)} - {why}", "watch"
        return f"{lb} {d}: {off:.0f}% under the high {_fp(rd.rh)} (needs a {M.MIN_CRACK_PCT:g}% crack)", "watch"

    def _jr_levels(self, s, px=None):
        if s.get("setup") == "squeeze":                  # 3.9.0: the max squeeze short
            lv = [{"price": px_round(s["stop"], True), "color": "#f23645", "style": "dash", "title": "stop"},
                  {"price": s["top"], "color": "#ffd23f", "style": "dot", "title": "squeeze top"},
                  {"price": s["level"], "color": "#3b82f6", "style": "dot", "title": "swing high it broke"},
                  {"price": s["vwap"], "color": "#ff9800", "style": "dot", "title": "VWAP"}]
        elif str(s.get("setup")).startswith("jr2"):     # 3.13.0: Jay-read 2
            lv = [{"price": px_round(s["stop"], True), "color": "#f23645", "style": "dash", "title": "stop"},
                  {"price": s["rth_high"], "color": "#9598a1", "style": "dot", "title": "RTH high"},
                  {"price": s["bounce_high"], "color": "#3b82f6", "style": "dot", "title": "bounce high"},
                  {"price": s["crack_low"], "color": "#22d3ee", "style": "dot", "title": "flush low"},
                  {"price": s["vwap"], "color": "#ff9800", "style": "dot", "title": "VWAP"}]
        else:
            lv = [{"price": px_round(s["stop"], True), "color": "#f23645", "style": "dash", "title": "stop"},
                  {"price": s["rth_high"], "color": "#9598a1", "style": "dot", "title": "RTH high"},
                  {"price": s["ref"], "color": "#3b82f6", "style": "dot",
                   "title": "level" if s["setup"] == "level" else "overhead high"},
                  {"price": s["crack_low"], "color": "#22d3ee", "style": "dot", "title": "crack low"},
                  {"price": s["vwap"], "color": "#ff9800", "style": "dot", "title": "VWAP"}]
        if px:
            lv.insert(0, {"price": px, "color": "#e040fb", "style": "solid", "title": "short here"})
        return lv

    async def _jr_maybe_enter(self, bs):
        """A short SIGNAL (Jay-read or max squeeze): post it with the read, then (unless alert-only / a guard says no)
        locate and short now - or, with no locate within MAX_LOCATE_PCT yet, keep searching (3.9.0) and short once
        located."""
        sg = bs.jr_sig
        if sg is None or bs.jr is None:
            return
        bs.jr_sig = None
        if bs.hunt is not None and bs.hunt.get("mode") == "pre":
            bs.hunt = None                               # the signal takes over the locate search
        jr, s = bs.jr, sg["sig"]
        sq = s.get("setup") == "squeeze"
        cfg = jr_part(jr, s["setup"]).cfg
        alert = alert_only_for(s["setup"])
        name = JR_SETUP_NAME.get(s["setup"], s["setup"])
        if off_for(s["setup"]):                          # 3.10: strategy switched Off in the app - no order, no post
            jr.entry_cancelled()
            self._log(f"{bs.sym}: {name} signal at {jr_hm(sg['t'])} ignored - the strategy is Off (Trading mode)", "info")
            return
        now = self.now()
        wall = self._wall(now)
        last = bs.last_px or s["close"]
        why = ""
        if not alert:
            why = (self.can_open() or ("halted" if bs.halted else "")
                   or ("an earlier order is not settled yet (network)" if self._orphan_entry(bs.sym) else "")
                   or ("the premarket long still holds it" if self.long_holds(bs.sym) else ""))
        else:                                            # alert only: what would still block the real short
            why = ("halted" if bs.halted else "") or ("the premarket long still holds it" if self.long_holds(bs.sym) else "")
        if not why:
            ok, w = jr.entry_allowed(last, now)
            why = "" if ok else w
        if not why and wall - sg["wall"] > JR_SIGNAL_MAX_AGE_SEC:
            why = f"signal {wall - sg['wall']}s old"
        qty, cap_note = self._jr_size(last, s["stop"])
        if not why and qty < 1:
            why = "position size too small"
        risk = s["stop"] - last
        lk = cfg.get("LOCK_STOP_PCT")
        lock_trig = last * (1 - cfg["LOCK_AFTER_PCT"] / 100.0)
        lock_stop = last * (1 - lk / 100.0) if lk is not None else None
        plan = (f"stop {_fp(px_round(s['stop'], True))} ({risk / last * 100:.0f}% over {_fp(last)}, risk "
                f"{_money(risk * max(qty, 0))}{'; ' + cap_note if cap_note else ''})"
                + (f". Lock: once it trades {_fp(lock_trig)} (-{cfg['LOCK_AFTER_PCT']:g}%) the stop moves to {_fp(lock_stop)} "
                   f"({JR.lock_text(lk)})" if lock_stop else ". No lock - the stop stays")
                + (f". Followed to {JR.EOD_COVER_TIME} like the backtest" if alert
                   else f". Cover {JR_EOD_COVER_TIME} by the bot" if JR_EOD_COVER_TIME else ". No automatic cover at the close"))
        if alert and not why:
            action = f"ALERT ONLY - no order. Would short {qty:,} sh @ ~{_fp(last)} now; {plan}."
        elif alert:
            action = f"ALERT ONLY - and no short now anyway: {why}."
        elif why:
            action = f"No order: {why}."
        else:
            action = f"Shorting now: {qty:,} sh, marketable limit {JR_ENTRY_SLIP_PCT:g}% under {_fp(last)}; {plan}."
        bs.jr_plan = {"px": last, "stop": s["stop"], "s": s}
        stop_r = px_round(s["stop"], True)
        lock_f = ([("Lock", f"at {_fp(lock_trig)} (-{cfg['LOCK_AFTER_PCT']:g}%) the stop goes to {_fp(lock_stop)} "
                            f"({JR.lock_text(lk)})", False)] if lock_stop else [("Lock", "none - the stop stays", False)])
        mk = [{"t": calendar.timegm(sg["t"].timetuple()) // 60 * 60, "price": s["close"], "text": "SIGNAL",
               "color": "#e040fb"}]
        if alert or why:                                 # 3.10: SIGNAL · NOT TRADED - and why, in one line
            mk_= "sq" if sq else "jr2" if str(s["setup"]).startswith("jr2") else "jr"      # 3.13.0
            how = ("Why: the " + MODE_NAMES[mk_] + " is set to Alert only - no order.\n"
                   "Turn it on in the app: menu → Trading mode → " + MODE_NAMES[mk_]
                   + " → Trading." if alert and not why else f"Why: {why}.")
            if alert and why:
                how = f"Alert only - and no short now anyway: {why}."
            if alert and not self.auto:
                how += " (Auto-trade is OFF too.)"
            self._notify(f"{bs.sym} - {name}  ·  " + ("ALERT ONLY" if alert else "not traded"),
                         how + "\n" + jr_read_text(s), "warn", bs=bs, chart=True, critical=True, stage="jrsignal",
                         tag="SIGNAL  ·  NOT TRADED", levels=self._jr_levels(s, last), marks=mk,
                         fields=[("Would short", f"{max(qty, 0):,} @ {_fp(last)}", True), ("Stop", _fp(stop_r), True),
                                 ("Followed as", "alert trade" if alert and not why else "-", True)])
        else:
            self._notify(f"{bs.sym} - shorting {qty:,} at ~{_fp(last)}", jr_read_text(s), "trade", bs=bs, chart=True,
                         critical=True, stage="jrsignal", tag=("SHORT SIGNAL  ·  " + name).upper(),
                         levels=self._jr_levels(s, last), marks=mk,
                         fields=[("Short", f"{qty:,} sh\nlimit {_fp(px_round(last * (1 - JR_ENTRY_SLIP_PCT / 100.0), up=False))}",
                                  True),
                                 ("Stop", f"{_fp(stop_r)}\n({'top' if sq else 'high of day' if s.get('stop_basis') == 'hod' else 'high'} +"
                                          f"{(SQ.STOP_OVER_TOP_PCT if sq else s.get('stop_pct', cfg.get('HOD_STOP_PCT', 3))):g}%)", True),
                                 ("Risk", f"{_money(risk * max(qty, 0))}\n({risk / last * 100:.0f}% over entry)"
                                  + (f"\n{cap_note}" if cap_note else ""), True)] + lock_f)
        bs.jr_plan = None
        if alert and not why:                            # the would-be short: followed on the candles, no order
            jr.entry_filled(last, now)
            bs.jr_virtual = {"entry": last, "stop": s["stop"], "qty": max(qty, 0), "name": name, "t": wall, "locked": False}
            return
        if alert or why:
            jr.entry_cancelled()
            return
        bs.phase = "locating"
        self._status(bs)
        try:
            st, qty2, loc_px = await self._locate_once(bs, qty, last, "entry")
        except TZError as exc:
            st, qty2, loc_px = "retry", 0, 0.0
            self._notify(f"❌ {bs.sym}: locate error", str(exc), "err")
        finally:
            if bs.phase == "locating":
                bs.phase = "idle"
        if st == "ok":
            await self._jr_short_now(bs, sg, qty2, loc_px)
            return
        if st == "stop":
            jr.entry_cancelled()
            self._notify(f"{bs.sym}: {name} skipped - no locate", f"Signal at {jr_hm(sg['t'])}. {bs.loc_note}", "warn",
                         bs=bs)
            return
        mono = time.monotonic()                          # 3.9.0: no locate within the cap yet - keep searching
        floor = s["close"] * (1 - LOCATE_GIVE_UP_DROP_PCT / 100.0)
        bs.hunt = {"mode": "entry", "sg": sg, "t0": mono, "cycle0": mono, "next": mono + LOCATE_RETRY_SEC, "tries": 1,
                   "paused": 0, "floor": floor}
        self._notify(f"\U0001F50D {bs.sym}: no locate within {MAX_LOCATE_PCT:g}% yet - still searching ({name})",
                     f"Asking TradeZero again every {LOCATE_RETRY_SEC:g} s, a {LOCATE_PAUSE_SEC / 60:g}-min break after every "
                     f"{LOCATE_HUNT_SEC / 60:g} min of searching. Shorts as soon as shares are located (never more than "
                     f"{MAX_LOCATE_PCT:g}% of the price a share), unless the price falls to {_fp(floor)} "
                     f"({LOCATE_GIVE_UP_DROP_PCT:g}% under the signal close {_fp(s['close'])}), reaches the stop "
                     f"{_fp(px_round(s['stop'], True))} or the entry window ends.", "warn", bs=bs)

    def _jr_settle(self, bs):
        """Keep the module in step with the bot: a SIGNAL with no order (and no locate search) behind it is cancelled, a
        position the bot no longer holds is closed (normally _finish reports it with the price)."""
        jr = bs.jr
        if jr is None or bs.phase != "idle":
            return
        if jr.awaiting is not None and bs.jr_sig is None and (bs.hunt or {}).get("mode") != "entry":
            jr.entry_cancelled()
        if jr.pos is not None and bs.entry is None and bs.jr_virtual is None:
            self._log(f"{bs.sym}: short position closed outside the normal exit - marked closed", "warn")
            try:
                jr.cover_filled(1.0, bs.last_px or jr.pos.entry, "MANUAL", self.now())
            except Exception:
                log.exception("jay-read settle %s", bs.sym)

    # ---------------- 3.9.0: the locate search ----------------
    def _hunt_text(self, bs):
        h = bs.hunt
        mono = time.monotonic()
        wait = max(0, int(h["next"] - mono))
        what = (f"after the {JR_SETUP_NAME.get(h['sg']['sig']['setup'], 'short')} signal (gives up at {_fp(h['floor'])})"
                if h["mode"] == "entry" else "before a signal")
        return (f"Locate search {what}: {h['tries']} request(s), " + (f"break {wait}s" if h["cycle0"] > mono else
                                                                       f"next in {wait}s")
                + (f" - last offer {bs.loc_note}" if bs.loc_note else ""))

    def _hunt_end_reason(self, bs, h):
        if bs.phase not in ("idle", "locating"):
            return "an order / position is open"
        why = self.can_open()
        if why:
            return why
        if bs.jr is None:
            return "no chart read"
        if h["mode"] == "entry":
            s = h["sg"]["sig"]
            if bs.jr.awaiting is None:
                return "the signal was cancelled"
            last = bs.last_px
            if last is not None and last <= h["floor"]:
                return (f"the price {_fp(last)} fell {LOCATE_GIVE_UP_DROP_PCT:g}%+ under the signal close {_fp(s['close'])} "
                        "- the move is gone")
            ok, w = bs.jr.entry_allowed(last or s["close"], self.now())
            return "" if ok else w
        if jr_finished(bs.jr):
            return "done for the day on this stock"
        if self._wall() % 86400 >= _secs(JR.SIGNAL_END):
            return f"after {JR.SIGNAL_END} - no new signals"
        return ""

    def _hunt_end(self, bs, h, why):
        bs.hunt = None
        if h["mode"] == "entry":
            s = h["sg"]["sig"]
            if bs.jr is not None and bs.jr.awaiting is not None and bs.entry is None:
                bs.jr.entry_cancelled()
            self._notify(f"{bs.sym}: {JR_SETUP_NAME.get(s['setup'], 'short')} skipped - no locate found",
                         f"Searched {h['tries']} time(s) since the signal at {jr_hm(h['sg']['t'])} and stopped: {why}.",
                         "warn", bs=bs)
        else:
            self._log(f"{bs.sym}: locate search before a signal stopped - {why} ({h['tries']} request(s))")

    async def _jr_hunt(self, bs):
        """One step of the locate search (the idle step calls it every second): start the pre-signal search when the
        read asks for it, stop when its reason is gone, one request when due, a LOCATE_PAUSE_SEC break after every
        LOCATE_HUNT_SEC of searching."""
        if bs.hunt is None:
            if not bs.pre_req:
                return
            req, bs.pre_req = bs.pre_req, None
            if time.monotonic() - req["mono"] > 30:
                return
            bs.pre_done = True                           # one pre-signal search a day per stock
            await self._jr_pre_start(bs, req)
            return
        h = bs.hunt
        why = self._hunt_end_reason(bs, h)
        if why:
            self._hunt_end(bs, h, why)
            return
        mono = time.monotonic()
        if mono < h["next"]:
            return
        if bs.halted or self.long_holds(bs.sym):
            h["next"] = mono + 5
            return
        if mono - h["cycle0"] >= LOCATE_HUNT_SEC:        # searched LOCATE_HUNT_SEC: a break
            h["next"] = h["cycle0"] = mono + LOCATE_PAUSE_SEC
            h["paused"] += 1
            txt = (f"{h['tries']} request(s) so far, nothing within {MAX_LOCATE_PCT:g}% of the price"
                   + (f" (last offer {bs.loc_note})" if bs.loc_note else "") + f" - {LOCATE_PAUSE_SEC / 60:g}-min break, "
                   "then searching again")
            if h["paused"] == 1:
                self._notify(f"\U0001F50D {bs.sym}: still no locate", txt, "dim", bs=bs)
            else:
                self._log(f"{bs.sym}: locate search - {txt}")
            return
        h["next"] = mono + LOCATE_RETRY_SEC
        h["tries"] += 1
        if h["mode"] == "entry":
            s = h["sg"]["sig"]
            px = bs.last_px or s["close"]
            qty, _ = self._jr_size(px, s["stop"])
        else:
            px = bs.last_px or h["ref"]
            qty = self._size(px)
        if qty < 1:
            return
        bs.phase = "locating"
        try:
            st, n, lp = await self._locate_once(bs, qty, px, h["mode"], quiet=True)
        except TZError as exc:
            st, n, lp = "retry", 0, 0.0
            self._log(f"{bs.sym}: locate request failed ({exc}) - searching on", "warn")
        finally:
            if bs.phase == "locating":
                bs.phase = "idle"
        if bs.hunt is not h:
            return
        if st == "ok":
            bs.hunt = None
            if h["mode"] == "entry":
                await self._jr_short_now(bs, h["sg"], n, lp, searched=True)
        elif st == "su_only":
            bs.hunt = None
        elif st == "stop":
            self._hunt_end(bs, h, bs.loc_note or "no more locate requests today")

    async def _jr_pre_start(self, bs, req):
        """The read says a short may come (Jay-read: momentum broke / max squeeze: a squeeze is on): locate now so the
        shares are ready; no offer within the cap = the search goes on (LOCATE_RETRY_SEC)."""
        if self.can_open():
            return
        ref = req["ref"]
        qty = self._size(ref)
        what = "max squeeze forming" if req.get("sq") and not req.get("jr") else "momentum broke - Jay-read setup forming"
        if not (self.is_paper() and not LOCATE_ON_PAPER) and not bs.etb:
            have = await self._inventory(bs)              # yours (the locate window / ZeroPro / web) or the bot's
            if self._enough_located(have, qty):
                self._notify(f"⚡ {bs.sym}: {what}", f"{have:,} shares are already located in the account (size {qty:,}) - "
                             f"they are used, no new locate.", "trade", bs=bs, chart=True)
                return
        if req.get("jr"):
            c = req["jr"]
            detail = f"High {_fp(c['rh'])} ({c['age']} min old), cracked -{c['crack'] * 100:.0f}% to {_fp(c['low'])}."
        else:
            c = req["sq"]
            detail = (f"Up +{c['up'] * 100:.0f}%, squeezed +{c['sq'] * 100:.0f}% over the swing high {_fp(c['level'])} to "
                      f"{_fp(c['top'])} - a red candle up there is the max squeeze short (stop {_fp(c['stop'])}).")
        self._notify(f"⚡ {bs.sym}: {what}", detail + f" Getting the locate now so the shares are ready before a signal "
                     f"(reference price {_fp(ref)}).", "trade", bs=bs, chart=True, critical=True)
        mono = time.monotonic()
        h = {"mode": "pre", "ref": ref, "t0": mono, "cycle0": mono, "next": mono + LOCATE_RETRY_SEC, "tries": 1, "paused": 0}
        bs.hunt = h
        bs.phase = "locating"
        self._status(bs)
        try:
            st, _, _ = await self._locate_once(bs, qty, ref, "pre")
        except TZError as exc:
            st = "retry"
            self._notify(f"❌ {bs.sym}: locate error", str(exc), "err")
        finally:
            if bs.phase == "locating":
                bs.phase = "idle"
        if bs.hunt is h and st != "retry":
            bs.hunt = None

    # ---------------- main loop ----------------
    async def run(self):
        self._log(f"Bot ready - watchlist: {', '.join(self.syms) or '(empty - add tickers)'}")
        if LONG_PREMARKET and LP is not None:
            try:
                self.longbot = LP.LongModule(self, TZError, DATA_DIR)
                self.loop.create_task(self.longbot.run())
                self._log(f"Premarket long module ready ({LP.SCAN_START}-{LP.FLATTEN_AT[:5]} ET, "
                          f"{'ON' if self.longbot.enabled else 'OFF'})")
            except Exception as exc:
                log.exception("premarket long module")
                self._log(f"premarket long module failed to start: {exc}", "err")
        elif LONG_PREMARKET:
            self._log(f"premarket long module not loaded ({LP_IMPORT_ERROR}) - put lh_long_premarket.py next to the app",
                      "err")
        while not self.be.closing:
            await asyncio.sleep(1.0)
            try:
                await self._tick()
            except Exception:
                log.exception("bot tick")

    # ---------------- 3.14: the IB portfolio to Discord (IB_REPORT_TIMES, ET, weekdays) ----------------
    def _ib_report_tick(self, now, secs, weekday):
        """Once per report time and day, within 30 minutes after it (a later start does not send an old report)."""
        if not weekday:
            return
        for hm in IB_REPORT_TIMES or ():
            try:
                h, m = (int(x) for x in str(hm).split(":"))
            except ValueError:
                continue
            at = h * 3600 + m * 60
            key = f"{now.date()} {hm}"
            if at <= secs < at + 1800 and key not in getattr(self, "_ibr_sent", set()):
                self._ibr_sent = getattr(self, "_ibr_sent", set()) | {key}
                self.loop.create_task(self._ib_report(hm))

    async def _ib_report(self, hm):
        try:
            r = await self.be._portfolio()
        except Exception as exc:
            self._log(f"IB portfolio report {hm}: not sent - {exc}", "warn")
            return
        cm = lambda v: "-" if v is None else f"{'-' if v < 0 else ''}C${abs(v):,.0f}"          # noqa: E731
        sg = lambda v: "-" if v is None else ("+" if v > 0 else "") + cm(v)                   # noqa: E731
        pc = lambda v: "" if v is None else f" ({v:+.1f}%)"                                     # noqa: E731
        rows = r.get("rows") or []
        lines = [f"{x['sym']}  {x['qty']:,.0f} sh  ·  {cm(x['value']) if x['cad'] else x['cur'] + ' ' + format(x['value'] or 0, ',.0f')}"
                 f"  ·  today {sg(x['day'])}{pc(x['day_pct'])}  ·  unrealized {sg(x['upnl'])}{pc(x['pct'])}" for x in rows]
        f = [("Market value", cm(r.get("value")), True), ("Today", sg(r.get("day")), True),
             ("Unrealized", sg(r.get("upnl")), True),
             ("USD/CAD", f"{r['usdcad']:.4f}" if r.get("usdcad") else "no rate", True)]
        note = []
        if r.get("missing"):
            note.append(f"{r['missing']} position(s) without a price from IB")
        if r.get("no_rate"):
            note.append(f"{r['no_rate']} position(s) not converted to CAD")
        self._notify(f"IB portfolio {cm(r.get('value'))}  ·  today {sg(r.get('day'))}",
                     chr(10).join(lines + ([""] + note if note else [])) or "No open positions.",
                     "ok" if (r.get("day") or 0) >= 0 else "warn", fields=f, tag=f"IB PORTFOLIO  ·  {hm} ET", who="System")

    # ---------------- 3.12.1: daily vault feed (core/vault_feed.py) ----------------
    def _vault_feed_tick(self, now, mono, secs, weekday):
        """Once a minute (04:00-20:00 ET, weekdays): note today's monitored symbols in the feed's own queue.
        A minute after start and then every 10 min: if earlier days are queued and no feed is running, fetch them
        into the data vault in a separate process (own IB client id, read-only)."""
        try:
            import vault_feed as VF
            if weekday and 4 * 3600 <= secs < 20 * 3600 and mono - getattr(self, "_vf_rec", 0.0) >= 60:
                self._vf_rec = mono
                threading.Thread(target=VF.record, args=(DATA_DIR, str(now.date()), list(self.syms), "watchlist / monitored"),
                                 daemon=True, name="vf-record").start()          # 3.14: the queue is in Turso - never wait for it here
            if weekday and secs >= 20 * 3600 and getattr(self, "_vf_eod", None) != str(now.date()):
                self._vf_eod = str(now.date())             # 20:00 ET: the day's list, once
                self._notify(f"Vault feed list - {now.date()}", VF.discord_text(DATA_DIR, now.date()), "dim",
                             tag="VAULT FEED  ·  END OF DAY", who="System")
            if mono < getattr(self, "_vf_next", 0.0):
                return
            if not hasattr(self, "_vf_next"):
                self._vf_next = mono + 60.0                    # first check a minute after the start
                return
            self._vf_next = mono + 600.0
            p = getattr(self, "_vf_proc", None)
            if p is not None and p.is_alive():
                return
            vs = getattr(self, "_vf_state", "idle")           # 3.14: ask Turso off the trading loop; decide on the next tick
            if vs == "idle":
                self._vf_next = mono + 2.0

                def _ask(day=now.date()):
                    try:
                        self._vf_days = VF.pending_days(DATA_DIR, day)
                    except Exception:
                        self._vf_days = []
                    self._vf_state = "ready"
                self._vf_state = "asking"
                threading.Thread(target=_ask, daemon=True, name="vf-pending").start()
                return
            if vs == "asking":
                self._vf_next = mono + 2.0
                return
            self._vf_state = "idle"
            days = list(getattr(self, "_vf_days", []) or [])
            self._vf_next = mono + 600.0
            if not days:
                return
            import lh_backtest
            vault = lh_backtest.settings().get("vault", "")
            if not vault and lh_backtest._cloud() is not None:       # 3.14: the vault is in Turso: this PC's replica
                import turso_vault
                vault = turso_vault.default_replica()
            if not vault:
                if not getattr(self, "_vf_warned", False):
                    self._vf_warned = True
                    self._log("vault feed: set the vault path in the Backtest tab - the queued days wait until then", "warn")
                return
            import multiprocessing as mp
            self._vf_proc = mp.get_context("spawn").Process(target=VF.run_feed, args=(DATA_DIR, vault, IB_HOST, IB_PORT, days),
                                                            daemon=True, name="lh-vault-feed")
            self._vf_proc.start()
            self._log(f"vault feed: fetching {len(days)} earlier day(s) into the data vault ({', '.join(days)}) - "
                      f"separate process, read-only IB client {VF.FEED_CLIENT_ID}")
        except Exception:
            log.exception("vault feed")

    async def _tick(self):
        now = self.now()
        mono = time.monotonic()
        wall = self._wall(now)
        secs = wall % 86400
        cur_min = wall // 60 * 60
        weekday = now.weekday() < 5
        self._vault_feed_tick(now, mono, secs, weekday)          # 3.12.1: the daily vault feed (never blocks)
        self._ib_report_tick(now, secs, weekday)                 # 3.14: the IB portfolio to Discord (10:00, 12:00)
        if self.day != now.date():
            self.day = now.date()
            self.trades_today = 0
            self.sig_today = {"jr2": 0, "jr": 0, "sq": 0}
            self.flags = set()
            self.located = set()
            self.size_base, self.size_note, self.size_closed, self.rebase_at = None, "", None, None
            self.order_seen = {k: v for k, v in self.order_seen.items() if k in self.orders_raw}
            for bs in self.syms.values():
                bs.skip_top, bs.trades, bs.eng = {}, [], None
                bs.reset_day()
            self.scan_seen = set()
            self.jr_alert_trades = []
            self.loc_q, self.loc_inv = None, []
            self._loc_load()                             # 3.9.0: today's locates (a restart keeps them)
            self._loc_push()
            self._drop_old_auto()
        # TradeZero
        if not self.tz_ready():
            if mono >= self.next_tz_try:
                self.next_tz_try = mono + 20
                await self._tz_connect()
        elif mono >= self.next_acct:
            self.next_acct = mono + 30
            await self._refresh_account()
        if self.tz_ready() and weekday:
            try:
                self._size_base_tick(secs)               # 3.12: equity at SIZE_BASE_TIME, re-set after a close
            except Exception:
                log.exception("size base")
        if not self.hello_sent and (self.tz_status.get("conn") != "off" or mono - self.started_at > 25 or
                                    self.tz_status.get("text", "").startswith("TradeZero keys")):
            self._hello()
        # IB candles
        ib = self.be.ib
        ib_ok = ib is not None and ib.isConnected()
        if (ib_ok and self.ib_down_since is not None
                and (not self.syms or any(b.st is not None for b in self.syms.values()))):
            mins = (mono - self.ib_down_since) / 60.0
            self.ib_down_since = None
            n = sum(1 for b in self.syms.values() if b.st is not None)
            self._notify(f"Live data again after {mins:.0f} min" if mins >= 1 else "Live data again",
                         (f"Candles reloaded for {n} symbol{'s' if n != 1 else ''}. " if n else "")
                         + "Signals that formed during the gap are not traded.", "ok", tag="IB GATEWAY BACK", who="System")
        elif (not ib_ok and self.ib_down_since is not None and not self.ib_down_alerted
              and mono - self.ib_down_since >= 300):
            self.ib_down_alerted = True
            self._notify("No prices for 5 minutes", "Check IB Gateway on the PC (logged out? daily restart?) and the "
                         "internet. The bot keeps trying.", "err", tag="IB STILL DOWN  ·  5 MIN", who="System", ping=True)
        active = weekday and 4 * 3600 <= secs < 20 * 3600
        for bs in list(self.syms.values()):
            if not ib_ok:
                if bs.phase == "idle":
                    bs.status, bs.kind = "Waiting for IB Gateway...", "dim"
                continue
            if bs.st is None:
                if not bs.loading and mono >= bs.next_load:
                    self.loop.create_task(self._load(bs))
                continue
            if active and secs >= 4 * 3600 + 30 and bs.st.loaded_day != wall // 86400:
                self._log(f"{bs.sym}: new trading day - reloading candles")
                self.loop.create_task(self._load(bs))
                continue
            if K.rth_s <= secs < K.rth_e and mono - bs.last_bar_wall > 240 and not bs.loading:
                self._notify(f"{bs.sym} - no new candle for 4 min, re-subscribing", f"Halted, or IB stopped sending it. "
                             f"The bot reloads {bs.sym} now.", "warn", tag=f"NO CANDLES  ·  {bs.sym}", who="System")
                self.loop.create_task(self._load(bs))
                continue
            sec_in = secs % 60
            key = (cur_min, 0 if sec_in < 10 else 1)
            if sec_in >= 2 and key != bs.eng_key:
                bs.eng_key = key
                await self._run_engine(bs, cur_min)
            self._check_prelocate(bs, secs)
        # 3.7: auto short-scanner (Jay-read mode)
        if (jr_mode() and SHORT_SCANNER and weekday and ib_ok and mono >= self.next_scan
                and _secs(SHORT_SCAN_START) <= secs < _secs(SHORT_SCAN_END)):
            self.next_scan = mono + SHORT_SCAN_INTERVAL_SEC
            self.loop.create_task(self._short_scan())
        # trading
        for bs in list(self.syms.values()):
            if not bs.busy:
                self.loop.create_task(self._step(bs))
        if self.tz_ready() and mono >= self.next_pos_check:
            self.next_pos_check = mono + POS_CHECK_SEC
            self.loop.create_task(self._check_positions())
        # orders panel: TradeZero's order list every ORDERS_POLL_SEC (slower while the panel is closed)
        if self.tz_ready() and mono >= self.next_orders:
            self.next_orders = mono + (ORDERS_POLL_SEC if self.settings.get("orders", True) else 10.0)
            self.loop.create_task(self._poll_orders())
        elif not self.tz_ready():
            self._push_orders()
        if self.net_alerted and self.tz_ready() and getattr(self.tz, "net_fail", 0) == 0:
            self.net_alerted = False
            self._notify("TradeZero answers again", "Every order and position is checked again - nothing missed.", "ok",
                         tag="TRADEZERO BACK", who="System")
        # the close
        if (weekday and jr_mode() and JR_EOD_COVER_TIME and "jr_eod" not in self.flags
                and _secs(JR_EOD_COVER_TIME) + 15 <= secs < K.rth_e):
            self.flags.add("jr_eod")                     # 3.7: backstop if the EOD candle event did not come (data gap)
            for bs in self.syms.values():
                if bs.phase == "short" and (bs.entry or {}).get("jr"):
                    bs.jr_eod = True
        if weekday:
            if EOD_AUTO_COVER and secs >= K.eod_s and "eod" not in self.flags and secs < K.rth_e + 3600:
                self.flags.add("eod")
                self.loop.create_task(self._eod())
            if not EOD_AUTO_COVER and secs >= _secs(EOD_ALERT_TIME) and "alert1" not in self.flags and secs < K.rth_e:
                self.flags.add("alert1")
                self._eod_alert(f"CLOSE YOUR SHORTS  ·  {EOD_ALERT_TIME}")
            if not EOD_AUTO_COVER and secs >= K.rth_e - 60 and "alert2" not in self.flags and secs < K.rth_e:
                self.flags.add("alert2")
                self._eod_alert("STOPS EXPIRE AT 16:00", only_open=True)
            if secs >= K.rth_e + 30 and "expired" not in self.flags and secs < K.rth_e + 3600:
                self.flags.add("expired")
                left = [b for b in self.syms.values() if b.phase in ("short", "manual", "covering") and b.entry
                        and self._tz_short(b)]
                if left:
                    self._notify("Day stop orders are gone - shorts still open", "Still short: " +
                                 ", ".join(f"{b.sym} {b.entry['filled']:,} sh" for b in left) +
                                 ". Cover in TradeZero or place an extended-hours order.", "err", ping=True,
                                 tag="STOPS EXPIRED  ·  16:00", who="Shorts")
            if (secs >= K.rth_e + 300 and "sellback" not in self.flags and self.tz_ready()):
                self.flags.add("sellback")
                self.loop.create_task(self._sell_back_locates())
            if secs >= K.rth_e + 330 and "summary" not in self.flags and secs < K.rth_e + 4 * 3600:
                self.flags.add("summary")
                self._summary()
        if DISCORD_HEARTBEAT_MIN and mono >= self.next_heartbeat:
            self.next_heartbeat = mono + DISCORD_HEARTBEAT_MIN * 60
            if active and self.syms:
                self._heartbeat()
        self._tbt_tick()
        self._push()

    def _tbt_tick(self):
        """3.12.2: tick-by-tick for the TICK_BY_TICK_MAX stocks closest to an order (core/data/tickfeed.py)."""
        try:
            import tickfeed
            if getattr(self, "tbt", None) is None:
                self.tbt = tickfeed.TickSlots(TICK_BY_TICK_MAX, self._log)
            self.tbt.sync(self.be.ib, tickfeed.wanted_for(self) if TICK_BY_TICK_MAX > 0 else [])
        except Exception:
            log.exception("tick-by-tick")

    async def _step(self, bs):
        if bs.busy:
            return
        if bs.halt is not None and bs.phase in ("short", "covering") and bs.entry:
            return                                       # 3.12: halted - _halt_watch owns it (the lock stays free so
        bs.busy = True                                   # the reopen order never waits for a step)
        try:
            if bs.phase == "idle":
                await self._maybe_enter(bs)
                if jr_mode():                            # 3.9.0: the locate search (before / after a signal)
                    if bs.phase == "idle":
                        await self._jr_hunt(bs)
                elif bs.pre_req:
                    req, bs.pre_req = bs.pre_req, None
                    if bs.phase == "idle" and time.monotonic() - req["mono"] <= 30:     # still fresh: locate now
                        bs.pre_done = True                                             # once a day
                        await self._prelocate(bs, req)
            elif bs.phase == "working":
                await self._manage_entry(bs)
            elif bs.phase == "short":
                await self._manage_short(bs)
            elif bs.phase == "covering":
                await self._manage_cover(bs)
        except TZError as exc:
            mono = time.monotonic()
            if bs.phase == "locating":                   # the entry order did not go out: free the symbol again
                bs.phase = "idle"
            if self._net_quiet(exc):
                self._log(f"{bs.sym}: no answer from TradeZero ({exc.text}) - retrying", "warn")
            elif mono - self.err_sent.get(bs.sym, 0) > 60:
                self.err_sent[bs.sym] = mono
                if exc.status == 0 and self.tz:          # 3.10: the outage message (once; "TRADEZERO BACK" follows)
                    self._notify(f"No answer from TradeZero ({getattr(self.tz, 'net_fail', 0)} tries)",
                                 "Retrying - check your internet connection. Stops already at TradeZero keep working. "
                                 "No new orders until it answers.", "err", tag="TRADEZERO NOT ANSWERING", who="System",
                                 ping=True)
                else:
                    self._notify(f"{bs.sym} - TradeZero answered with an error", str(exc), "err", tag="ORDER ERROR",
                                 bs=bs)
            else:
                self._log(f"{bs.sym}: TradeZero error {exc}", "err")
            bs.next_poll = time.monotonic() + 3
        except Exception:
            log.exception("bot step %s", bs.sym)
        finally:
            if bs.jr is not None:
                self._jr_settle(bs)
            bs.busy = False
            self._status(bs)

    async def _inventory(self, bs):
        """Located shares of this symbol available in the account now - located by you (the locate window, ZeroPro,
        the web) or by the bot."""
        inv = await self._tz(self.tz.locate_inventory, self.acc)
        return sum(int(_fnum(r.get("available"))) for r in inv if str(r.get("symbol")) == bs.sym)

    # ---------------- 3.9.0: the locate window (orders panel -> Locates) ----------------
    def _loc_path(self):
        return os.path.join(DATA_DIR, "locates_today.json")

    def _loc_load(self):
        """Today's locates (yours from the window and the bot's) from locates_today.json - kept through the day, so a
        restart knows what was located and paid. Another day's file is ignored."""
        self.loc_rows = []
        try:
            with open(self._loc_path(), encoding="utf-8") as f:
                d = json.load(f)
            if str(d.get("date")) == str(self.now().date()):
                self.loc_rows = [r for r in d.get("rows", []) if isinstance(r, dict) and r.get("sym")]
        except FileNotFoundError:
            pass
        except Exception as exc:
            self._log(f"locates_today.json not read ({exc.__class__.__name__}) - starting the day's locate list empty", "warn")
        for r in self.loc_rows:
            if r.get("by") == "bot":
                self.located.add(r["sym"])               # the bot's own: sold back after the close
            bs = self.syms.get(r["sym"])
            if bs is not None:
                bs.locate_px = _fnum(r.get("px"))
                bs.locate_cost += _fnum(r.get("total"))

    def _loc_save(self):
        try:
            tmp = self._loc_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"date": str(self.now().date()), "rows": self.loc_rows}, f, indent=1)
            os.replace(tmp, self._loc_path())
        except Exception as exc:
            self._log(f"locates_today.json not saved ({exc})", "warn")

    def _loc_record(self, sym, qty, px, kind, by):
        self.loc_rows.append({"t": self.now().strftime("%H:%M:%S"), "sym": sym, "qty": int(qty), "px": round(float(px), 6),
                              "total": round(float(px) * int(qty), 2), "type": kind, "by": by})
        self._loc_save()
        self._loc_push()

    def _loc_last(self, sym):
        bs = self.syms.get(sym)
        if bs is not None and bs.last_px:
            return float(bs.last_px)
        st = getattr(self.be, "state", None)
        if st is not None and getattr(st, "sym", None) == sym and getattr(st, "live", None):
            return float(st.live[4])
        return None

    def _loc_push(self):
        q = dict(self.loc_q) if self.loc_q else None
        if q:
            now = self._wall()
            q["offers"] = [dict(o, left=max(0, o["exp"] - now)) for o in q.get("offers", [])]
        payload = {"q": q, "inv": self.loc_inv, "rows": self.loc_rows, "cap": MAX_LOCATE_PCT, "tz": self.tz_ready(),
                   "paper": self.tz_ready() and self.is_paper() and not LOCATE_ON_PAPER, "invAt": self.loc_inv_at,
                   "spent": round(sum(_fnum(r.get("total")) for r in self.loc_rows), 2)}
        self.be.bridge.call_raw("setLocate", _dumps(payload))

    async def loc_refresh(self):
        """The account's located shares now (TradeZero's locate inventory)."""
        if not self.tz_ready():
            self._loc_push()
            return
        try:
            inv = await self._tz(self.tz.locate_inventory, self.acc)
        except TZError as exc:
            self.loc_q = dict(self.loc_q or {}, msg=f"Inventory not read: {exc}", err=True)
            self._loc_push()
            return
        agg = {}
        for r in inv:
            sym = str(r.get("symbol") or "")
            if not sym:
                continue
            a = agg.setdefault(sym, {"sym": sym, "avail": 0, "types": set()})
            a["avail"] += int(_fnum(r.get("available")))
            lt = LOCATE_TYPES.get(int(_fnum(r.get("locateType"))))
            if lt:
                a["types"].add({"PreBorrow": "Pre-borrow", "SingleUse": "Single-use"}.get(lt, lt))
        self.loc_inv = [{"sym": a["sym"], "avail": a["avail"], "type": ", ".join(sorted(a["types"])) or "-"}
                        for a in sorted(agg.values(), key=lambda a: a["sym"])]
        self.loc_inv_at = self.now().strftime("%H:%M:%S")
        self._loc_push()

    async def loc_quote(self, sym, qty):
        """Your locate request from the window: TradeZero's offers (re-usable / pre-borrow and single-use) with $ a share,
        the total and % of the price. No cap - you decide (the bot's own locates stay under MAX_LOCATE_PCT)."""
        if self.loc_busy:
            return
        self.loc_busy = True
        try:
            if self.loc_q and self.loc_q.get("state") == "offers":
                await self.loc_cancel(push=False)
            last = self._loc_last(sym)
            self.loc_q = {"sym": sym, "qty": int(qty), "qid": None, "state": "asking", "offers": [], "last": last,
                          "msg": "Asking TradeZero...", "err": False}
            self._loc_push()
            if not self.tz_ready():
                self.loc_q.update(state="error", msg="TradeZero is not connected", err=True)
                return
            if self.is_paper() and not LOCATE_ON_PAPER:
                self.loc_q.update(state="error", err=True, msg="Paper account: TradeZero's paper environment has no locate "
                                                             "inventory - shorts go in without one (LOCATE_ON_PAPER = False).")
                return
            qid = self._qid(sym, "M")
            self.loc_q["qid"] = qid
            try:
                await self._tz(self.tz.locate_quote, self.acc, sym, int(qty), qid)
            except TZError as exc:
                self.loc_q.update(state="error", msg=f"Request refused: {exc}", err=True)
                return
            offers, rows, deadline, first_seen = [], [], time.monotonic() + LOCATE_WAIT_SEC, None
            while time.monotonic() < deadline:
                await asyncio.sleep(1.0)
                try:
                    hist = await self._tz(self.tz.locate_history, self.acc)
                except TZError:
                    continue
                rows = [h for h in hist if str(h.get("quoteReqID", "")) in (qid, qid + ".SU")]
                offers = [h for h in rows if int(_fnum(h.get("locateStatus"))) == 65 and _fnum(h.get("locatePrice")) > 0]
                if offers:
                    if first_seen is None:
                        first_seen = time.monotonic()
                    if len(offers) >= 2 or time.monotonic() - first_seen >= 2.0:
                        break
                elif rows and all(int(_fnum(h.get("locateStatus"))) in (52, 56, 67) for h in rows):
                    break
            last = self._loc_last(sym) or last
            exp = self._wall() + 30
            out = []
            for h in sorted(offers, key=lambda h: (str(h.get("quoteReqID", "")).endswith(".SU"), _fnum(h.get("locatePrice")))):
                su = str(h.get("quoteReqID", "")).endswith(".SU")
                lp = _fnum(h.get("locatePrice"))
                out.append({"id": str(h.get("quoteReqID")), "kind": "Single-use" if su else "Pre-borrow / re-usable",
                            "su": su, "px": lp, "total": round(lp * int(qty), 2), "pct": _f(lp / last * 100.0, 2) if last else None,
                            "exp": exp})
            if out:
                self.loc_q.update(state="offers", offers=out, last=last, err=False,
                                  msg=f"{len(out)} offer(s) for {int(qty):,} {sym} - an offer is good for about 30 s")
            else:
                why = next((str(h.get("text") or "") for h in rows if h.get("text")), "") or "no offer from TradeZero"
                self.loc_q.update(state="none", msg=f"No shares: {why}", err=True)
            self._log(f"{sym}: locate window - {self.loc_q['msg']}")
        finally:
            self.loc_busy = False
            self._loc_push()

    async def loc_accept(self, oid):
        """Buy one offer of the window's request. The shares are kept for the day; the bot uses them first (and the
        symbol goes on the watchlist so the bot can short it)."""
        q = self.loc_q or {}
        o = next((x for x in q.get("offers", []) if x["id"] == oid), None)
        if o is None or q.get("state") != "offers":
            self._ui_msg("warn", "That offer is gone - ask again")
            return
        if self._wall() > o["exp"] + 5:
            q.update(state="none", msg="The offer expired (30 s) - ask again", err=True)
            self._loc_push()
            return
        sym, qty = q["sym"], int(q["qty"])
        q.update(state="buying", msg=f"Buying {qty:,} {sym} ({o['kind']}) ...", err=False)
        self._loc_push()
        try:
            before = sum(int(_fnum(r.get("available"))) for r in await self._tz(self.tz.locate_inventory, self.acc)
                         if str(r.get("symbol")) == sym)
            await self._tz(self.tz.locate_accept, self.acc, oid)
        except TZError as exc:
            q.update(state="error", msg=f"Not bought: {exc}", err=True)
            self._loc_push()
            return
        after, deadline = before, time.monotonic() + 12
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            try:
                after = sum(int(_fnum(r.get("available"))) for r in await self._tz(self.tz.locate_inventory, self.acc)
                            if str(r.get("symbol")) == sym)
            except TZError:
                continue
            if after > before:
                break
        if after <= before:
            q.update(state="error", msg="Accepted, but the shares did not show up yet - check TradeZero's locate window",
                     err=True)
            self._loc_push()
            return
        total = o["px"] * qty
        self._loc_record(sym, qty, o["px"], o["kind"].split(" /")[0], "you")
        if sym not in self.syms:
            await self.add(sym)
        bs = self.syms.get(sym)
        if bs is not None:
            bs.locate_px = o["px"]
            bs.locate_cost += total
            bs.locate_unbilled += total                 # charged to the next short of this symbol
        q.update(state="done", msg=f"Located {qty:,} {sym} - {after:,} shares ready. The bot uses them first.", err=False)
        self._notify(f"\U0001F4E6 {sym}: you located {qty:,} shares in the app",
                     f"{o['kind']}: ${o['px']:.4f}/share = {_money(total)}"
                     + (f" ({o['pct']:.2f}% of {_fp(q.get('last'))})" if o.get("pct") is not None else "")
                     + f". {after:,} shares located in the account now - the bot uses them first today."
                     + ("" if bs is not None else f" (The watchlist is full - add {sym} to let the bot short it.)"),
                     "ok", bs=bs)
        await self.loc_refresh()

    # ---------------- entries ----------------
    def long_holds(self, sym):
        """v3.5: the premarket long still has shares (or an order step) in sym - no short on it until it is sold."""
        return self.longbot is not None and self.longbot.holds(sym)

    async def _maybe_enter(self, bs):
        if jr_mode():                                   # 3.7.0: the Jay-read short (v16 parked)
            await self._jr_maybe_enter(bs)
            return
        e = bs.eng
        if not e or bs.st is None or self.can_open() or bs.halted or self._orphan_entry(bs.sym):
            return
        if self.long_holds(bs.sym):
            return                                      # the premarket long is still in this stock
        v = e.get("vac")
        if v and v["key"] not in bs.used_vac:
            bs.used_vac.add(v["key"])
            await self._enter_vacuum(bs, v)
            return
        p = e.get("pending")
        if not p or p["top"] in bs.skip_top:
            return
        last = bs.last_px
        if last is None or last >= p["zone_hi"]:
            return                                      # already past the zone: the engine wants a new dip first
        wall = self._wall()
        if wall % 86400 > _secs(STRAT.LAST_ENTRY_TIME) + 59:
            return
        limit_px = px_round(p["trigger"], up=False)
        qty = self._size(limit_px)
        if qty < 1:
            bs.skip_top[p["top"]] = "position size too small"
            return
        bs.phase = "locating"
        self._status(bs)
        try:
            ok, qty, loc_px = await self._get_locate(bs, qty, limit_px, "entry")
        except TZError as exc:
            ok, loc_px = False, 0.0
            self._notify(f"❌ {bs.sym}: locate error", str(exc), "err")
        if not ok:
            bs.skip_top[p["top"]] = "no locate"
            bs.phase = "idle"
            return
        p2 = (bs.eng or {}).get("pending")
        if not p2 or abs(p2["top"] - p["top"]) > 1e-9 * p["top"] or self.can_open() or (bs.last_px or 0) >= p["zone_hi"]:
            bs.phase = "idle"
            self._log(f"{bs.sym}: setup changed while locating - no order")
            return
        coid = self._coid(bs.sym, "S")
        ent = {"coid": coid, "setup": "BOUNCE_ZONE", "top": p["top"], "trigger": p["trigger"], "top_t": p.get("top_t"),
               "zone_hi": p["zone_hi"], "stop": p["stop"], "qty": qty, "filled": 0, "avg": 0.0, "t": wall,
               "cancel_sent": False, "locate_px": loc_px, "limit": limit_px, "dip": p["dip"], "ext": p["ext"]}
        r = await self._place(bs.sym, "entry", "Sell", "Open", "Limit", qty, "Day", limit=limit_px, coid=coid, ctx={"ent": ent})
        if r.get("orderStatus") == "Rejected":
            bs.phase = "idle"
            bs.skip_top[p["top"]] = f"rejected: {r.get('text')}"
            self._notify(f"❌ {bs.sym}: short limit rejected", str(r.get("text")), "err")
            return
        ent["coid"] = r.get("clientOrderId") or coid
        bs.entry = ent
        bs.phase = "working"
        bs.next_poll = time.monotonic() + 0.5
        self._notify(f"\U0001F7E7 {bs.sym}: BOUNCE short limit placed",
                     f"Sell short {qty:,} @ {_fp(limit_px)} (resting). Stop if filled {_fp(px_round(p['stop'], True))}.",
                     "trade", bs=bs, chart=True, critical=True)

    async def _enter_vacuum(self, bs, v):
        wall = self._wall()
        last = bs.last_px
        if last is None or (wall - v["t"] > 150 and not v.get("fresh")):
            return                                      # stale signal (data gap)
        if last >= v["stop"]:
            self._notify(f"{bs.sym}: vacuum signal skipped", f"price {_fp(last)} already at the stop {_fp(v['stop'])}", "warn")
            return
        limit_px = px_round(last * (1 - VAC_ENTRY_SLIP_PCT / 100.0), up=False)
        qty = self._size(limit_px)
        if qty < 1:
            return
        self._notify(f"\U0001F9F2 {bs.sym}: VACUUM short signal",
                     f"Peak {_fp(v['peak'])} ({v['ext']:.0f}% over VWAP) on dying volume, candle closed {STRAT.VAC_PULLBACK_PCT:g}% "
                     f"under it. Shorting now, stop {_fp(px_round(v['stop'], True))}.", "trade", bs=bs, chart=True, critical=True,
                     levels=[{"price": v["peak"], "color": "#e040fb", "style": "dot", "title": "peak"},
                             {"price": px_round(v["stop"], True), "color": "#f23645", "style": "dash", "title": "stop"}],
                     marks=[{"t": v["t"], "price": last, "text": "SIGNAL", "color": "#e040fb"}])
        bs.phase = "locating"
        self._status(bs)
        try:
            ok, qty, loc_px = await self._get_locate(bs, qty, limit_px, "entry")
        except TZError as exc:
            ok, loc_px = False, 0.0
            self._notify(f"❌ {bs.sym}: locate error", str(exc), "err")
        if not ok or self.can_open():
            bs.phase = "idle"
            return
        last = bs.last_px or last
        if last >= v["stop"] or (self._wall() - v["t"] > 150 and not v.get("fresh")):
            bs.phase = "idle"
            self._notify(f"{bs.sym}: vacuum entry dropped", "the price moved too far while locating", "warn")
            return
        limit_px = px_round(last * (1 - VAC_ENTRY_SLIP_PCT / 100.0), up=False)
        coid = self._coid(bs.sym, "S")
        ent = {"coid": coid, "setup": "VACUUM", "top": v["peak"], "trigger": v["trigger"],
               "zone_hi": None, "stop": v["stop"], "qty": qty, "filled": 0, "avg": 0.0, "t": self._wall(),
               "cancel_sent": False, "locate_px": loc_px, "limit": limit_px, "dip": 0.0, "ext": v["ext"],
               "deadline": time.monotonic() + VAC_ENTRY_TIMEOUT_SEC, "vac_key": v["key"], "vac_t": v.get("vkey")}
        r = await self._place(bs.sym, "entry", "Sell", "Open", "Limit", qty, "Day", limit=limit_px, coid=coid, ctx={"ent": ent})
        if r.get("orderStatus") == "Rejected":
            bs.phase = "idle"
            self._notify(f"❌ {bs.sym}: vacuum short rejected", str(r.get("text")), "err")
            return
        ent["coid"] = r.get("clientOrderId") or coid
        bs.entry = ent
        bs.phase = "working"
        bs.next_poll = time.monotonic() + 0.4
        self._notify(f"\U0001F7E7 {bs.sym}: VACUUM short order placed",
                     f"Sell short {qty:,} @ {_fp(limit_px)} (marketable limit, {VAC_ENTRY_SLIP_PCT:g}% under the last price). "
                     f"Stop if filled {_fp(px_round(v['stop'], True))}.", "trade", bs=bs, chart=True, critical=True)

    def _skip_setup(self, bs, ent):
        """You cancelled the bot's entry: that trade is ignored - the bot and the engine look for the next setup."""
        if ent.get("setup") == "VACUUM":
            if ent.get("vac_key"):
                bs.used_vac.add(ent["vac_key"])
            if ent.get("vac_t"):
                bs.void.add(("V", ent["vac_t"]))
        else:
            if ent.get("top") is not None:
                bs.skip_top[ent["top"]] = "cancelled by you"
            if ent.get("top_t") is not None:
                bs.void.add(("B", int(ent["top_t"])))
        bs.eng_key = None                                # run the engine again right away

    # ---------------- 3.12: halts, the stop that must be at TradeZero, your own stop ----------------
    def _in_position(self, bs):
        ent = bs.entry or {}
        return int(ent.get("filled") or 0) > 0 and bs.phase in ("short", "covering", "manual")

    def _on_quote(self, bs, tk):
        """Every IB tick of a watchlist stock (event-loop thread). Trading: the last price (+ price alerts) and the quote.
        Halted (IB tick 49, or TradeZero said so): every price is IGNORED - indications can be anything ($100 on a $2
        stock). The reopen = IB's halt flag clears (or the day volume rises: a real trade); the first real price then
        decides at once (see _halt_decide) - no waiting for the next second."""
        px = _num(getattr(tk, "last", None))
        vol = _num(getattr(tk, "volume", None))
        bid, ask = _num(getattr(tk, "bid", None)), _num(getattr(tk, "ask", None))
        flag = _num(getattr(tk, "halted", None)) is not None
        traded = vol is not None and bs.vol_seen is not None and vol > bs.vol_seen
        if vol is not None and (bs.vol_seen is None or vol > bs.vol_seen):
            bs.vol_seen = vol
        h = bs.halt
        if h is None:
            if px:
                bs.last_px = px
                ca = getattr(self.be, "check_alerts", None)          # 3.11: price alerts on the watchlist
                if ca is not None and getattr(getattr(self.be, "alerts", None), "items", None):
                    ca(bs.sym, px)
            if bid:
                bs.bid = bid
            if ask:
                bs.ask = ask
            if flag:
                self._halt_start(bs, "IB")
            elif bs.halted:
                bs.halted = False
            return
        mono = time.monotonic()
        if h.get("resumed") is None:
            age = mono - h["mono"]
            if h["src"] == "IB":
                back = (not flag) or (traded and age >= 30)
            else:                                        # TradeZero said "halted" (IB showed no halt): a real trade
                back = (traded and age >= 2) or (not flag and age >= 30 and traded)
            if not back:
                return                                   # still halted: prices are indications - ignored
            now = self.now()
            h["resumed"], h["resumed_hms"], h["res_mono"] = self._wall(now), now.strftime("%H:%M:%S"), mono
            bs.halted = False
            self._log(f"{bs.sym}: trading resumed {h['resumed_hms']} (halted {h['hms']}, {h['src']})", "warn")
        ref = h.get("px") or bs.last_px or 0.0

        def sane(p):
            return bool(p) and (not ref or ref / HALT_SANE_X <= p <= ref * HALT_SANE_X)

        cand = None
        if traded and sane(px):
            cand = (px, "first trade")
        elif sane(bid) and sane(ask) and ask >= bid and (ask - bid) <= 0.25 * ask:
            cand = (ask, "ask")                          # what buying back costs right now
        elif mono - h["res_mono"] > 10 and sane(px):
            cand = (px, "last price")
        if cand is None:
            return
        if traded and px:
            bs.last_px = px
        if bid:
            bs.bid = bid
        if ask:
            bs.ask = ask
        self._halt_decide(bs, h, cand[0], cand[1])

    def _warm_fast(self):
        """Keep the reopen thread's TradeZero connection fresh (one cheap read every 5 s while a held stock is halted)."""
        if self.tz is None or getattr(self, "_warming", False):
            return
        self._warming = True

        def run():
            try:
                self.tz.account(self.acc)
            except Exception:
                pass
            finally:
                self._warming = False
        try:
            self.loop.run_in_executor(self.tz_fast, run)
        except RuntimeError:
            self._warming = False

    async def _finish(self, bs, exit_px, reason):
        bs.done_mono = time.monotonic()                  # 3.8.0: TradeZero's position list may lag this close
        ent = bs.entry or {}
        jr_note = ""
        if ent.get("jr") and bs.jr is not None and bs.jr.pos is not None:     # 3.7: tell the Jay-read module
            mod = {"Stop": "STOP", "Your stop": "STOP", "Stop rejected": "STOP", "Lock": "STOP", "EOD": "EOD"}.get(reason, "MANUAL")
            try:
                out = bs.jr.cover_filled(1.0, exit_px, mod, self.now())
                why = out[-1]["reason"] if out else mod
                jr_note = jr_done_note(bs.jr, bs.sym)
                if not jr_note and why == "LOCK":
                    jr_note = "Jay-read: lock exit - it can set up again today."
            except Exception:
                log.exception("jay-read cover_filled %s", bs.sym)
        qty = int(ent.get("filled", 0))
        avg = _fnum(ent.get("avg"))
        stop0 = _fnum(ent.get("stop"))
        risk = (stop0 - avg) * qty if stop0 > avg else 0.0
        gross = (avg - exit_px) * qty
        fee = _fnum(ent.get("locate_usd"))
        net = gross - fee
        r = net / risk if risk > 0 else 0.0
        wall = self._wall()
        row = {"date": str(self.now().date()), "symbol": bs.sym, "setup": ent.get("setup", ""), "account": self.acc,
               "top": ent.get("top"), "short_limit": ent.get("limit"), "stop": round(stop0, 4), "shares": qty,
               "entry_avg": round(avg, 4),
               "entry_time": datetime.fromtimestamp(ent.get("t", wall), timezone.utc).strftime("%H:%M:%S"),
               "exit_avg": round(exit_px, 4), "exit_time": self.now().strftime("%H:%M:%S"), "exit_reason": reason,
               "locate_per_share": round(fee / qty, 4) if qty else 0.0, "locate_cost": round(fee, 2),
               "pnl_gross": round(gross, 2), "pnl_net": round(net, 2), "R_net": round(r, 3)}
        self._journal(row)
        bs.trades.append({"R": r, "net": net, "reason": reason, "setup": ent.get("setup", ""), "qty": qty,
                          "tin": int(ent.get("t", wall)), "tout": int(wall),
                          "entry": avg, "exit": exit_px})
        win = net > 0
        held = max(0, wall - int(ent.get("t", wall))) // 60
        held_t = f"{held // 60} h {held % 60} min" if held >= 60 else f"{held} min"
        t_in = datetime.fromtimestamp(ent.get("t", wall), timezone.utc).strftime("%H:%M")
        rs = {"Stop": "STOP", "Your stop": "YOUR STOP", "Stop rejected": "STOP", "Lock": "LOCK", "EOD": "EOD"}.get(reason)
        tagx = "WIN" if win else (rs or str(reason).upper()[:24])
        self._notify(f"{bs.sym}  {_pm(net)}  ·  {r:+.1f}R",
                     (f"{jr_note}" if jr_note else
                      (f"The strategy keeps running on {bs.sym}." if reason != "Flatten" else "")),
                     "cover" if win else "err", bs=bs, chart=True, critical=True, stage="closed",
                     tag=f"CLOSED  ·  {tagx}",
                     fields=[("Entry", f"{_fp(avg)}\n{t_in}", True), ("Exit", f"{_fp(exit_px)}\n{self.now():%H:%M} "
                                                                         f"{str(reason).lower()}", True),
                             ("Held", held_t, True),
                             ("Net", f"{_money(gross)} gross - {_money(fee)} locate", True),
                             ("Size", f"{qty:,} sh", True),
                             ("Today shorts", f"{sum(len(b.trades) for b in self.syms.values())} trade(s)  ·  "
                                              f"{_money(sum(t['net'] for b in self.syms.values() for t in b.trades))}", True)],
                     marks=[{"t": ent.get("t", wall) // 60 * 60, "price": avg, "text": "SHORT", "color": "#f23645"},
                            {"t": wall // 60 * 60, "price": exit_px, "text": reason.upper(), "color": "#26a69a", "up": True}],
                     levels=[])
        self.be.bridge.call("alert", {"kind": "cover", "t": wall // 60 * 60, "title": f"COVERED  {bs.sym}",
                                      "text": f"{reason}  ·  {qty} sh @ {exit_px:.4g}  ·  net ${net:,.2f} ({r:+.2f}R)"})
        if self.settings.get("sound"):
            _beep("cover")
        if bs.stop_coid and not reason.endswith("top") and reason not in ("Stop", "Your stop"):
            try:
                await self._tz(self.tz.cancel, self.acc, bs.stop_coid)
            except TZError:
                pass
        if bs.phase == "working" and ent.get("coid") and not ent.get("cancel_sent"):
            try:
                await self._tz(self.tz.cancel, self.acc, ent["coid"])
            except TZError:
                pass
        bs.entry, bs.stop_coid, bs.stop_qty, bs.cover, bs.phase = None, None, 0, None, "idle"
        bs.stop_owner, bs.stop_missing_since, bs.stop_guard = "bot", None, None
        self._state_save()                               # 3.12: the open trade is gone from bot_state.json

    async def _settle_orphans(self, orders):
        """Orders sent while the network dropped (the answer was lost): once one shows up at TradeZero the bot
        tracks it if that order is still what it needs, otherwise it cancels it (and alerts you about any shares it
        filled, which the bot then does not manage)."""
        if not self.orphans:
            return
        mono = time.monotonic()
        for coid, rec in list(self.orphans.items()):
            o = next((x for x in orders if str(x.get("clientOrderId", "")).startswith(coid)), None)
            if o is None:
                rec["miss"] = rec.get("miss", 0) + 1
                if not rec.get("gone") and (rec["miss"] >= 10 or mono - rec["mono"] > 180):
                    rec["gone"] = True                   # not in TradeZero's list: it never arrived (still watched
                    self._log(f"{rec['sym']}: order {coid} never reached TradeZero")      # for 30 min, just in case)
                elif rec.get("gone") and mono - rec["mono"] > 1800:
                    self.orphans.pop(coid, None)
                continue
            self.orphans.pop(coid, None)
            real, st, ctx = str(o.get("clientOrderId")), str(o.get("orderStatus") or ""), rec["ctx"]
            live, ex = st not in DONE_STATES, int(_fnum(o.get("executed")))
            bs = self.syms.get(rec["sym"])
            if bs is None or rec["role"] == "you":
                self._notify(f"⚠ {rec['sym']}: your changed order {real} did reach TradeZero ({st})",
                             "It was sent during a network drop - check it in the orders panel.", "warn")
                continue
            if not await self._grab(bs, 4.0):
                self.orphans[coid] = rec                 # next poll
                continue
            try:
                role = "late" if rec.get("gone") else rec["role"]      # showed up after it was given up: never adopted
                if role == "entry" and bs.phase == "idle" and (live or ex > 0) and ctx.get("ent"):
                    bs.entry, bs.phase, bs.next_poll = dict(ctx["ent"], coid=real), "working", 0.0
                    sg = ctx["ent"].get("jr_sig")
                    if sg is not None and bs.jr is not None and bs.jr.awaiting is None and bs.jr.pos is None:
                        bs.jr.awaiting = sg                  # 3.8.0: the module tracks the late fill (stop, lock)
                    self._notify(f"⚠ {bs.sym}: the short order sent during a network drop reached TradeZero",
                                 "The bot tracks it now (fills, stop, cancel rules).", "warn", bs=bs)
                elif role == "stop" and bs.phase == "short" and bs.entry and not bs.stop_coid and live:
                    q = int(_fnum(o.get("leavesQuantity"), ctx.get("qty", 0))) or int(ctx.get("qty", 0))
                    bs.stop_coid, bs.stop_qty, bs.stop_owner, bs.stop_missing_since = real, q, "bot", None
                    bs.entry["stop_live"] = _ostop(o) or ctx.get("stop")
                    self._log(f"{bs.sym}: the stop sent during a network drop reached TradeZero - using it", "warn")
                elif role == "cover" and bs.phase == "short" and live and ctx.get("cover"):
                    bs.cover, bs.phase, bs.next_poll = dict(ctx["cover"], coid=real), "covering", 0.0
                    self._log(f"{bs.sym}: the cover sent during a network drop reached TradeZero - tracking it", "warn")
                else:
                    if live:
                        await self._tz(self.tz.cancel, self.acc, real)
                        o2 = await self._wait_done(real, 4.0) or o
                        ex = max(ex, int(_fnum(o2.get("executed"))))
                    if ex > 0 and rec["role"] == "entry":
                        self._notify(f"\U0001F6A8 {bs.sym}: {ex:,} shares filled on an order sent during a network drop",
                                     f"Order {real} was a duplicate and is cancelled, but {ex:,} shares of it filled. The bot "
                                     "does NOT manage them - check the position at TradeZero and put a stop on them.",
                                     "err", bs=bs, chart=True, ping=True)
                    elif live:
                        self._notify(f"⚠ {bs.sym}: cancelled a duplicate order",
                                     f"{real} was sent during a network drop and is not needed any more.", "warn")
                    else:
                        self._log(f"{bs.sym}: order {real} sent during a network drop ended {st} - nothing to do")
            except TZError as exc:
                self._notify(f"\U0001F6A8 {bs.sym}: could not settle order {real}", f"{exc} - check it in the orders panel.",
                             "err", ping=True)
            finally:
                bs.busy = False

    def _check_edit(self, o, price):
        """'' if the new price is sane for this order, else why not."""
        typ, (side, _) = _otype(o), _oside(o)
        if typ not in ("Limit", "Stop", "StopLimit"):
            return f"a {typ} order has no price to change"
        if not (price > 0):
            return "type a price above 0"
        bs = self.syms.get(self._osym(o))
        last = (bs.last_px if bs is not None else None) or 0.0
        if last:
            if abs(price / last - 1.0) > 0.6:
                return f"{_fp(price)} is more than 60% away from the last price {_fp(last)} - check the number"
            if typ in ("Stop", "StopLimit") and side in ("Cover", "Buy") and price <= last:
                return f"a buy stop must be above the last price ({_fp(last)})"
            if typ in ("Stop", "StopLimit") and side in ("Short", "Sell") and price >= last:
                return f"a sell stop must be below the last price ({_fp(last)})"
        return ""

    async def _modify_plain(self, o, price):
        """Your own order (or an old bot order): cancel it, then the same order for the shares left at the new price."""
        coid, sym = str(o.get("clientOrderId")), self._osym(o)
        typ = _otype(o)
        side = str(o.get("side") or "")
        oc = str(o.get("openClose") or "") or ("Close" if side.lower().startswith("buy") else "Open")
        tif = str(o.get("timeInForce") or "Day")
        lim0, stp0 = _olimit(o), _ostop(o)
        await self._tz(self.tz.cancel, self.acc, coid)
        o2 = await self._wait_done(coid) or {}
        st = o2.get("orderStatus")
        if st not in DONE_STATES:
            self._ui_msg("err", f"{sym}: TradeZero did not confirm the cancel - price not changed")
            return
        qty = int(_fnum(o2.get("orderQuantity"), _fnum(o.get("orderQuantity"))))
        left = qty - int(_fnum(o2.get("executed")))
        if st == "Filled" or left <= 0:
            self._ui_msg("info", f"{sym}: the order filled before the price change")
            return
        limit = stop = None
        if typ == "Limit":
            limit = price
        elif typ == "Stop":
            stop = price
        else:
            stop = price
            limit = _tick_px(price + (lim0 - stp0)) if lim0 > 0 and stp0 > 0 else price
        self.seq = (self.seq + 1) % 1000
        new = f"LHU{re.sub(r'[^A-Z0-9]', '', sym)[:6]}{self.now():%H%M%S}{self.seq:03d}"
        label = f"{_oside(o)[0]} {typ} {left:,} @ {_fp(price)}"
        try:
            r = await self._place(sym, "you", side, oc, typ, left, tif, limit=limit, stop=stop, coid=new)
            bad = f"rejected: {r.get('text')}" if r.get("orderStatus") == "Rejected" else ""
        except TZError as exc:
            bad = ("no answer from TradeZero - it may still arrive, check the orders panel"
                   if exc.status == 0 or exc.status >= 500 else str(exc))
        if bad:
            self._notify(f"\U0001F6A8 {sym}: order change failed - the old order is cancelled",
                         f"New {label}: {bad}. Place it again at TradeZero if it is not in the orders panel.", "err", ping=True)
            self._ui_msg("err", f"{sym}: new order not placed ({bad[:80]}) - the old one is cancelled")
            return
        self._log(f"{sym}: your order changed - {label} (was {_fp(stp0 or lim0)})", "warn")
        self._ui_msg("info", f"{sym}: {label}")

    def _alerts_list(self):
        al = getattr(self.be, "alerts", None)
        return al.list() if al is not None else []

    def _health(self):
        """3.11 bot center: connections and speed (no account id, no keys)."""
        be = self.be
        cache = getattr(be, "cache", None)
        t0, ci = self._cinfo
        if cache is not None and (ci is None or time.monotonic() - t0 > 30):
            try:
                ci = cache.info()
            except Exception:
                ci = None
            self._cinfo = (time.monotonic(), ci)
        lat = list(self.lat_ms)
        st = getattr(be, "status", {}) or {}
        return {"ib": st.get("conn"), "ibText": st.get("text", ""), "ibMs": getattr(be, "ib_ping_ms", None),
                "tzMs": getattr(self.tz, "last_ms", None) if self.tz is not None else None,
                "lat": lat, "latMed": sorted(lat)[len(lat) // 2] if lat else None,
                "cache": ci, "loadMs": getattr(be, "load_ms", None), "loadSrc": getattr(be, "load_src", ""),
                "watch": len(self.syms), "max": MAX_WATCHLIST,
                "haltMs": list(self.halt_lat)}

    def _push(self, force=False):
        rows = []
        for bs in self.syms.values():
            if (bs.phase == "idle" and not bs.busy) or bs.halt is not None:
                self._status(bs)
            e = bs.eng or {}
            ent = bs.entry or {}
            rows.append({"sym": bs.sym, "last": _f(bs.last_px), "gap": _f(e.get("gap"), 1), "gapOk": bool(e.get("gapOk")),
                         "status": bs.status, "kind": bs.kind, "halted": bs.halted, "phase": bs.phase,
                         "hdir": (bs.halt or {}).get("dir", ""), "hpx": _f((bs.halt or {}).get("px")),
                         "ht": (bs.halt or {}).get("hms", ""),
                         "stop": _f(ent.get("stop_live") or ent.get("stop")) if bs.phase == "short" else None})
        info = self.acc_info
        pos, fills, closed = self._ui_positions()
        unreal = sum(p["unreal"] for p in pos if p.get("unreal") is not None)
        payload = {"tz": self.tz_status, "acct": {"id": bool(self.acc), "type": self.acc_type, "equity": _f(info.get("equity"), 2),
                                                  "bp": _f(info.get("buyingPower", info.get("bp")), 2), "dayPnl": _f(self.day_pnl, 2),
                                                  "unreal": _f(unreal, 2) if pos else 0.0},
                   "modes": {k: mode(k) for k in MODE_KEYS},
                   "modeOn": {"long": bool(LONG_PREMARKET and self.longbot is not None), "jr2": jr2_ready(),
                              "jr": jr_mode() and JR is not None, "sq": sq_on()},
                   "pos": pos, "fills": fills, "closed": closed,
                   "auto": self.auto, "liveBlocked": self.live_blocked(), "reason": self.can_open() if self.auto else "",
                   "rows": rows, "trades": self.trades_today, "maxTrades": MAX_BOT_TRADES_PER_DAY,
                   "size": (f"{ACCOUNT_PCT:g}% of the base {_money(self.size_base)} = "
                            f"{_money(min(self.size_base * ACCOUNT_PCT / 100.0, MAX_POSITION_USD))} a short ({self.size_note})"
                            if self.size_base else f"{ACCOUNT_PCT:g}% of equity (max ${MAX_POSITION_USD:,.0f})"),
                   "sizeBase": _f(self.size_base, 2), "locCap": MAX_LOCATE_PCT,
                   "dc": self.dc.status(), "log": list(self.logs)[-80:],
                   "sig": dict(self.sig_today), "alerts": self._alerts_list(), "health": self._health()}
        js = _dumps(payload)
        if js != self.last_push or force:
            self.last_push = js
            self.be.bridge.call_raw("setBot", js)


# -----------------------------------------------------------------------------
# JS API (called from the page)
# -----------------------------------------------------------------------------
