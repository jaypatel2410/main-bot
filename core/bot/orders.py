# -*- coding: utf-8 -*-
"""Kestrel - Bot: entries, covers, locates, order tracking and the orders panel.
Part of the Bot class (core/bot/bot_core.py): main.py runs this file in its own namespace. Code moved here unchanged."""

class _BotOrders:

    async def _tz(self, fn, *a, **k):
        return await self.loop.run_in_executor(self.tz_pool, lambda: fn(*a, **k))

    async def _place(self, sym, role, side, oc, typ, qty, tif="Day", limit=None, stop=None, coid=None, ctx=None,
                     urgent=False):
        """Every order goes out through here. When the network drops after the order may have reached TradeZero, the
        order is looked up by its id (TradeZero's recovery recipe) - it is never blindly sent twice. If it cannot be
        settled now it is remembered and settled when it shows up in the order list (see _settle_orphans).
        3.12 urgent (a halt reopen): its own thread and warm connection, no pacing wait."""
        try:
            if urgent:
                fn = getattr(self.tz, "place_urgent", None) or self.tz.place
                r = await self.loop.run_in_executor(self.tz_fast, lambda: fn(
                    self.acc, sym, side, oc, typ, qty, tif, limit=limit, stop=stop, coid=coid, route=self.route)) or {}
            else:
                r = await self._tz(self.tz.place, self.acc, sym, side, oc, typ, qty, tif, limit=limit, stop=stop,
                                   coid=coid, route=self.route) or {}
            if role == "entry":
                self.known_entries.add(str(r.get("clientOrderId") or coid))
            return r
        except TZError as exc:
            # 3.8.0: ANY error answer (16 Oct: a long buy answered HTTP 404 filled anyway) or no answer: the order may
            # be at TradeZero - look it up by its id first. Only "never left this PC" is final.
            if not coid or not getattr(exc, "sent", True):
                raise
            for i in range(3):
                await asyncio.sleep(0.6 + 0.6 * i)
                try:
                    o = await self._tz(self.tz.order, self.acc, coid)
                except TZError:
                    continue
                if o:
                    self._log(f"{sym}: order {coid} is at TradeZero although the answer was '{self._clean(str(exc))}' "
                              f"- tracking it", "warn")
                    if role == "entry":
                        self.known_entries.add(str(o.get("clientOrderId") or coid))
                    return o
            self.orphans[coid] = {"sym": sym, "role": role, "mono": time.monotonic(), "ctx": dict(ctx or {}), "miss": 0}
            raise

    def _orphan_entry(self, sym):
        """An entry sent during a network drop is not settled yet: no new entry on this symbol until it is
        (otherwise the same setup could be shorted twice)."""
        return any(r["sym"] == sym and r["role"] == "entry" and not r.get("gone") for r in self.orphans.values())

    async def _wait_done(self, coid, secs=6.0):
        """After a cancel: poll the order until TradeZero reports it finished. Returns the last order seen (or None)."""
        o = None
        for _ in range(max(1, int(secs / 0.4))):
            await asyncio.sleep(0.4)
            try:
                o = await self._tz(self.tz.order, self.acc, coid) or o
            except TZError:
                pass
            if (o or {}).get("orderStatus") in DONE_STATES:
                break
        return o

    async def _grab(self, bs, wait=8.0, step=0.2):
        """Take the symbol's lock (no bot step runs on it meanwhile). False if it stays busy."""
        for _ in range(max(1, int(wait / step))):
            if not bs.busy:
                bs.busy = True
                return True
            await asyncio.sleep(step)
        return False

    async def flatten(self):
        self.auto = False
        self.flattening = True
        self._notify("Closing everything at market", "You clicked Flatten all: bot orders cancelled, every bot short "
                     "covered and every long sold at market. Auto-trade OFF.", "warn", tag="FLATTEN ALL", who="System")
        try:
            for bs in list(self.syms.values()):
                await self._flatten_one(bs, "Flatten")
            if self.longbot is not None:                 # v3.5: the premarket longs too
                await self.longbot.flatten_all("Flatten all")
        finally:
            self.flattening = False
        self._push(force=True)

    async def cover_one(self, sym):
        bs = self.syms.get(sym)
        if bs is not None and bs.phase in ("short", "working", "manual"):
            self._notify(f"{sym} - covering at market (you clicked Cover)", "", "warn", bs=bs, tag="COVER")
            await self._flatten_one(bs, "Cover (app)")

    # ---------------- 3.7.0: auto short-scanner ----------------
    async def _short_scan(self):
        """IBKR top % gainers up SHORT_SCAN_MIN_UP_PCT%+ (price SHORT_SCAN_MIN_PRICE+) -> the short watchlist."""
        ib = self.be.ib
        if self.scanning or ib is None or not ib.isConnected():
            return
        self.scanning = True
        try:
            # 3.15: the shared gainers scan. With the Scanner screen open its live quotes check the up % (no extra IB
            # request); otherwise a list asked with exactly SHORT_SCAN_MIN_UP_PCT (shared / cached when it can be)
            quotes = bool(getattr(self.be, "scan_on", False))
            cons, eup = await self.be.gainers("short", SHORT_SCAN_MIN_UP_PCT, SHORT_SCAN_MIN_PRICE, 50,
                                              SHORT_SCAN_INTERVAL_SEC, exact=not quotes)
            self.scan_n += 1
            self.scan_fail = 0
            for c in cons or []:
                sym = str(getattr(c, "symbol", "") or "").upper().strip().replace(" ", ".")
                if not re.match(r"^[A-Z][A-Z0-9.]{0,7}$", sym) or sym in self.syms or sym in self.scan_seen:
                    continue
                tk = self.be.scan_tk.get(sym, (None, None))[1] if quotes else None
                if eup < SHORT_SCAN_MIN_UP_PCT - 1e-9:   # list asked with a lower up %: the live quote must show it
                    lq = _num(getattr(tk, "last", None)) if tk is not None else None
                    pq = _num(getattr(tk, "close", None)) if tk is not None else None
                    if not lq or not pq or (lq / pq - 1) * 100.0 < SHORT_SCAN_MIN_UP_PCT:
                        continue                         # not up enough / no quote yet (not marked seen: checked again)
                if tk is not None:                       # 3.15: under 1M shares today / worth over $1B: not added now
                    last = _num(getattr(tk, "last", None)) or _num(getattr(tk, "close", None))      # (not marked seen: the
                    vol = (_num(getattr(tk, "volume", None)) or 0.0) * self.be._vol_mult()            # next scan checks again)
                    fl = self.be.floats.peek(sym) if getattr(self.be, "floats", None) is not None else None
                    if not scan_keep(vol, fl["v"] * last if fl and fl.get("v") and last else None):
                        continue
                self.scan_seen.add(sym)
                if len(self.syms) >= MAX_WATCHLIST:
                    self._notify(f"\U0001F50E short scanner: {sym} is up {SHORT_SCAN_MIN_UP_PCT:g}%+ - watchlist full",
                                 f"{MAX_WATCHLIST} symbols already. Remove one to let the scanner add new runners.", "warn")
                    continue
                self.scan_added += 1
                await self.add(sym, auto=True)
        except Exception as exc:
            self.scan_fail += 1
            log.warning("short scan failed: %r", exc)
            if self.scan_fail == 6:
                self._notify("\u26A0 Short scanner failing", f"6 scans in a row failed ({exc.__class__.__name__}: {exc}). "
                             "Check the IBKR scanner permissions - or add the tickers yourself.", "warn")
        finally:
            self.scanning = False

    async def _jr_short_now(self, bs, sg, qty_loc, loc_px, searched=False):
        """Shares located: check again and send the marketable-limit short (searched = after a locate search: the signal
        age does not count, the search had its own limits)."""
        jr, s = bs.jr, sg["sig"]
        name = JR_SETUP_NAME.get(s["setup"], s["setup"])
        now = self.now()
        wall = self._wall(now)
        last = bs.last_px or s["close"]
        ok, w = jr.entry_allowed(last, now)
        why = (self.can_open() or ("halted" if bs.halted else "") or ("" if ok else w)
               or ("the premarket long still holds it" if self.long_holds(bs.sym) else "")
               or ("" if searched or wall - sg["wall"] <= JR_SIGNAL_MAX_AGE_SEC
                   else f"signal {wall - sg['wall']}s old after the locate"))
        qty3, cap_note = self._jr_size(last, s["stop"])
        qty = min(qty_loc, qty3)
        if not why and qty < 1:
            why = "position size too small"
        if why:
            bs.phase = "idle"
            jr.entry_cancelled()
            self._notify(f"{bs.sym}: {name} entry dropped", f"{why} (price {_fp(last)})", "warn", bs=bs)
            return
        limit_px = px_round(last * (1 - JR_ENTRY_SLIP_PCT / 100.0), up=False)
        coid = self._coid(bs.sym, "S")
        ent = {"coid": coid, "setup": JR_SETUP_CODE.get(s["setup"], "JR_A"), "top": s["rth_high"], "trigger": s["close"],
               "zone_hi": None, "stop": s["stop"], "qty": qty, "filled": 0, "avg": 0.0, "t": wall, "cancel_sent": False,
               "locate_px": loc_px, "limit": limit_px, "dip": s["crack"] * 100.0, "ext": s["vs_vwap"] * 100.0,
               "deadline": time.monotonic() + JR_ENTRY_TIMEOUT_SEC, "jr": True, "jr_sig": s}
        r = await self._place(bs.sym, "entry", "Sell", "Open", "Limit", qty, "Day", limit=limit_px, coid=coid, ctx={"ent": ent})
        if sg.get("mono"):
            self.lat_ms.append(int((time.monotonic() - sg["mono"]) * 1000))
        if r.get("orderStatus") == "Rejected":
            bs.phase = "idle"
            jr.entry_cancelled()
            self._notify(f"❌ {bs.sym}: {name} short rejected", str(r.get("text")), "err")
            return
        ent["coid"] = r.get("clientOrderId") or coid
        bs.entry = ent
        bs.phase = "working"
        bs.next_poll = time.monotonic() + 0.4
        self._notify(f"\U0001F7E7 {bs.sym}: short order placed ({name})",
                     f"Sell short {qty:,} @ {_fp(limit_px)} (marketable limit, {JR_ENTRY_SLIP_PCT:g}% under the last price "
                     f"{_fp(last)}). Stop if filled {_fp(px_round(s['stop'], True))}." + (f" {cap_note}." if cap_note else "")
                     + (" Located after a search." if searched else ""), "trade", bs=bs, chart=True, critical=True)

    def _check_prelocate(self, bs, secs):
        """The read says momentum broke (Jay-read): ask for the locate now (once), so the shares are ready for a signal."""
        if (not JR_PRELOCATE or not jr_ready() or bs.pre_done or bs.pre_req or bs.hunt is not None
                or bs.phase != "idle" or not bs.last_px or self.can_open() or bs.jr is None or jr_finished(bs.jr)):
            return
        if not (bool(bs.jr_ctx) and mode("jr") == "trading" and not jr_part_finished(jr_part(bs.jr, "rollover"))):
            return                                       # never for an alert-only strategy
        if not (K.rth_s <= secs < _secs(JR.SIGNAL_END)):
            return
        e = bs.eng or {}
        vw = e.get("vwap")
        bs.pre_req = {"jr": dict(bs.jr_ctx), "vwap": vw, "ext": (bs.last_px / vw - 1.0) * 100.0 if vw else 0.0,
                      "ref": bs.last_px, "mono": time.monotonic()}

    # ---------------- locates ----------------
    @staticmethod
    def _enough_located(avail, qty):
        """3.8.0: the shares already located are used without buying more (LOCATE_USE_EXISTING_MIN_PCT)."""
        if avail <= 0:
            return False
        return avail >= qty or (avail >= 100 and avail >= qty * LOCATE_USE_EXISTING_MIN_PCT / 100.0)

    async def _get_locate(self, bs, qty, px, mode):
        """(ok, shares, $/share) - one attempt (the v16 path)."""
        st, n, lp = await self._locate_once(bs, qty, px, mode)
        return st == "ok", n, lp

    async def _locate_once(self, bs, qty, px, mode, quiet=False):
        """ONE locate attempt -> (status, shares, $/share).
        status "ok"      shares ready: located now, already located in the account, easy to borrow, or a paper account
               "retry"   no offer within MAX_LOCATE_PCT / no shares: ask again later (the locate search)
               "su_only" before a signal: only single-use shares fit the cap - bought when a signal comes
               "stop"    no more locate requests today (MAX_LOCATE_REQUESTS_PER_SYMBOL)
        mode 'pre' = before a signal (re-usable shares only), 'entry' = at / after a signal (single-use ok). The bot never
        pays more than MAX_LOCATE_PCT of px a share. quiet = a repeat of the search: requests and prices go to the bot log;
        Discord hears about a locate that is bought. One locate per symbol a day, re-used for every trade."""
        bs.loc_note = ""
        if self.is_paper() and not LOCATE_ON_PAPER:
            if "paper" not in bs.notes:
                bs.notes.add("paper")
                self._notify(f"{bs.sym}: paper account - no locate needed",
                             "TradeZero's paper environment has no locate inventory; shorts go in without one.", "dim")
            return "ok", qty, 0.0
        if bs.etb is None:
            try:
                bs.etb = bool(await self._tz(self.tz.is_etb, self.acc, bs.sym))
            except TZError as exc:
                self._log(f"{bs.sym}: easy-to-borrow check failed ({exc})", "warn")
        if bs.etb:
            if "etb" not in bs.notes:
                bs.notes.add("etb")
                self._notify(f"{bs.sym}: easy to borrow - no locate needed", "", "dim")
            return "ok", qty, 0.0
        avail = await self._inventory(bs)
        if self._enough_located(avail, qty):           # 3.8.0: shares already located are used - no new locate
            if mode == "entry":
                self._notify(f"\U0001F4E6 {bs.sym}: using {min(qty, avail):,} shares already located - no new locate",
                             (f"Size {qty:,}; the account has {avail:,} located shares of {bs.sym}"
                              + (" (the short is cut to them)" if avail < qty else "") + "."), "dim", bs=bs)
            return "ok", min(qty, avail), bs.locate_px
        if bs.locate_requests >= MAX_LOCATE_REQUESTS_PER_SYMBOL:
            if avail > 0 and mode == "entry":
                return "ok", avail, bs.locate_px
            bs.loc_note = f"{MAX_LOCATE_REQUESTS_PER_SYMBOL} locate requests used today"
            if "maxreq" not in bs.notes:
                bs.notes.add("maxreq")
                self._notify(f"{bs.sym}: no more locate requests today", f"{MAX_LOCATE_REQUESTS_PER_SYMBOL} requests used.",
                             "warn")
            return "stop", 0, 0.0
        need = int(math.ceil((qty - avail) / 100.0)) * 100
        cap = MAX_LOCATE_PCT / 100.0 * px
        if avail > 0:
            self._log(f"{bs.sym}: {avail:,} shares already located - locating only the missing {need:,}")
        qid = self._qid(bs.sym)
        bs.locate_requests += 1
        await self._tz(self.tz.locate_quote, self.acc, bs.sym, need, qid)
        if quiet:
            self._log(f"{bs.sym}: locate request #{bs.locate_requests} - {need:,} sh, max ${cap:.4f}/share "
                      f"({MAX_LOCATE_PCT:g}% of {_fp(px)})")
        else:
            self._notify(f"\U0001F4E8 {bs.sym}: locate requested - {need:,} shares",
                         (f"{avail:,} shares already located in the account - only the missing ones are located. " if avail
                          else "") + f"Price basis {_fp(px)} ({'last price' if mode == 'pre' else 'entry price'}). "
                         f"Max locate {MAX_LOCATE_PCT:g}% = ${cap:.4f}/share = up to {_money(cap * need)} total. "
                         f"Waiting for TradeZero's offer...", "info", bs=bs, stage="locate", critical=True)
        offers, rows, deadline, first_seen = [], [], time.monotonic() + LOCATE_WAIT_SEC, None
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            hist = await self._tz(self.tz.locate_history, self.acc)
            rows = [h for h in hist if str(h.get("quoteReqID", "")) in (qid, qid + ".SU")]
            offers = [h for h in rows if int(_fnum(h.get("locateStatus"))) == 65 and _fnum(h.get("locatePrice")) > 0]
            if offers:
                if first_seen is None:
                    first_seen = time.monotonic()
                if len(offers) >= 2 or time.monotonic() - first_seen >= 2.0:
                    break
            elif rows and all(int(_fnum(h.get("locateStatus"))) in (52, 56, 67) for h in rows):
                break
        lines, choices, notes = [], [], []
        for h in offers:
            su = str(h.get("quoteReqID", "")).endswith(".SU")
            lp = _fnum(h.get("locatePrice"))
            ok = lp <= cap
            kind = "Single-use" if su else "Re-usable (locate / pre-borrow)"
            lines.append(f"**{kind}**: ${lp:.4f}/share = {_money(lp * need)} for {need:,} sh = {lp / px * 100:.2f}% of {_fp(px)} "
                         f"{'✅ within' if ok else '❌ above'} the {MAX_LOCATE_PCT:g}% cap")
            notes.append((lp, f"${lp:.4f} = {lp / px * 100:.1f}% ({'single-use' if su else 're-usable'})"))
            if ok and (not su or mode == "entry" or PRELOCATE_ACCEPT_SINGLE_USE):
                choices.append((su, lp, h))
        if not offers:
            why = next((str(h.get("text") or "") for h in rows if h.get("text")), "") or "no offer"
            lines.append(f"No offer ({why}).")
            bs.loc_note = f"none ({why})"
        else:
            bs.loc_note = min(notes)[1]
        if mode == "pre":
            choices.sort(key=lambda c: (c[0], c[1]))      # re-usable first (kept all day), then the cheapest
        else:
            choices.sort(key=lambda c: c[1])
        su_only = False
        if choices:
            su, lp, h = choices[0]
            decision = f"Buying the {'single-use' if su else 're-usable'} locate: {need:,} sh x ${lp:.4f} = {_money(lp * need)}."
        elif any(str(h.get("quoteReqID", "")).endswith(".SU") and _fnum(h.get("locatePrice")) <= cap for h in offers):
            su_only = True
            decision = ("Only single-use shares fit the cap - not bought now (they are used up by the first short). "
                        "They are bought when a setup actually fires.")
        else:
            decision = "Not buying - nothing within the cap." + (
                f" The bot keeps searching: a request every {LOCATE_RETRY_SEC:g} s, a {LOCATE_PAUSE_SEC / 60:g}-min break "
                f"after every {LOCATE_HUNT_SEC / 60:g} min.")
        if quiet and not choices:
            self._log(f"{bs.sym}: locate request #{bs.locate_requests}: {bs.loc_note or 'no offer'} - not bought "
                      f"(max {MAX_LOCATE_PCT:g}% of {_fp(px)})")
        else:
            self._notify(f"\U0001F4B2 {bs.sym}: locate prices", "\n".join(lines) + "\n\n" + decision,
                         "trade" if choices else "warn", bs=bs, chart=True, critical=True)
        if not choices:
            try:
                await self._tz(self.tz.locate_cancel, self.acc, qid)
            except TZError:
                pass
            if avail > 0 and mode == "entry":
                return "ok", avail, bs.locate_px
            return ("su_only" if su_only and mode == "pre" else "retry"), 0, 0.0
        su, lp, h = choices[0]
        await self._tz(self.tz.locate_accept, self.acc, str(h.get("quoteReqID")))
        self.located.add(bs.sym)
        deadline = time.monotonic() + 12
        avail2 = avail
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            avail2 = await self._inventory(bs)
            if avail2 >= avail + min(need, qty):
                break
        if avail2 <= avail:
            self._notify(f"❌ {bs.sym}: locate accepted but the shares did not show up", "Check TradeZero's locate window.", "err")
            return ("ok", avail, bs.locate_px) if (avail > 0 and mode == "entry") else ("retry", 0, 0.0)
        bs.locate_px = lp
        bs.locate_cost += lp * need
        bs.locate_unbilled += lp * need
        self._loc_record(bs.sym, need, lp, "Single-use" if su else "Pre-borrow", "bot")
        self._notify(f"✅ {bs.sym}: locate done - {avail2:,} shares ready",
                     f"Paid {_money(lp * need)} (${lp:.4f}/share, {'single-use' if su else 're-usable all day'}). "
                     f"Locates today on {bs.sym}: {_money(bs.locate_cost)}.", "ok", bs=bs, stage="locate", critical=True)
        return "ok", min(qty, avail2), lp

    async def loc_cancel(self, push=True):
        q = self.loc_q or {}
        if q.get("qid") and q.get("state") in ("offers", "asking"):
            try:
                await self._tz(self.tz.locate_cancel, self.acc, q["qid"])
            except TZError:
                pass
        self.loc_q = None
        if push:
            self._loc_push()

    def short_busy(self, sym):
        """v3.5, for the premarket long: '' = sym is free to buy; otherwise why not (a short of the short bot, or a short
        position in the account - a long buy would cover it)."""
        bs = self.syms.get(sym)
        if bs is not None and bs.phase != "idle":
            return f"the short bot has a {bs.phase} trade on {sym}"
        side, sh = self.pos_snapshot.get(sym, ("", 0))
        if side == "Short" and sh:
            return f"{sym} is short {sh:,} sh in the account"
        return ""

    def _keep_entry(self, bs, wall):
        ent, e = bs.entry, bs.eng or {}
        if not self.auto:
            return False, "auto-trade off"
        if self.flattening:
            return False, "flatten"
        if ent.get("user_px"):                           # you set this price in the orders panel: kept until it fills,
            last = self._entry_last_time(ent)
            if wall % 86400 > _secs(last) + 59:          # you cancel it, or the setup's entry window ends
                return False, f"{last} passed"
            return True, ""
        if ent.get("jr"):                                # Jay-read: a marketable limit right after the signal
            if bs.halted:
                return False, "halted - the entry is pulled (the signal is not repeated)"
            if time.monotonic() > ent.get("deadline", 0):
                return False, f"not filled within {JR_ENTRY_TIMEOUT_SEC}s"
            return True, ""
        if bs.halted:
            return False, "halted - the order is pulled"
        return False, "not a bot entry order"

    @staticmethod
    def _entry_last_time(ent):
        """The last entry time of the setup this entry order belongs to."""
        return JR.LAST_ENTRY_TIME if JR is not None else "15:30"

    @staticmethod
    def _entry_totals(ent, o):
        """(shares filled, average price) of the whole entry: orders before a price change + the working order."""
        ex = int(_fnum(o.get("executed")))
        prev, cost = int(ent.get("filled_prev", 0)), _fnum(ent.get("cost_prev"))
        n = prev + ex
        if n <= 0:
            return 0, 0.0
        return n, (cost + ex * _fnum(o.get("priceAvg"), ent["limit"])) / n

    async def _entry_fill(self, bs, o, stop=True):
        """New entry shares filled: report it (the first fill makes it a trade) and place / resize the stop."""
        ent = bs.entry
        filled, avg = self._entry_totals(ent, o)
        if filled <= ent["filled"]:
            return False
        first = ent["filled"] == 0
        ent["filled"], ent["avg"] = filled, avg
        ent["t"] = self._wall()
        if first:
            self.trades_today += 1
            ent["locate_usd"], bs.locate_unbilled = bs.locate_unbilled, 0.0     # the locate is charged once, to this trade
            if ent.get("jr") and bs.jr is not None:     # 3.7: the Jay-read module now holds the position (lock, EOD)
                if bs.jr.awaiting is not None:
                    info = bs.jr.entry_filled(avg, self.now())
                    ent["jr_lock_trigger"], ent["jr_lock_stop"] = info.get("lock_trigger"), info.get("lock_stop")
                else:
                    self._log(f"{bs.sym}: Jay-read fill without a waiting signal - the module does not track this short",
                              "warn")
            # a fill above the planned stop (fast spike) still gets a stop above the fill
            ent["stop"] = max(ent["stop"], ent["avg"] * (1 + MIN_STOP_ABOVE_FILL_PCT / 100.0))
            self.be.bridge.call("alert", {"kind": "short", "t": ent["t"] // 60 * 60, "title": f"SHORT FILLED  {bs.sym}",
                                          "text": f"{SETUP_NAME.get(ent['setup'], ent['setup'])}  ·  {filled} sh @ "
                                                  f"{ent['avg']:.4g}  ·  stop {px_round(ent['stop'], True)}"})
            if self.settings.get("sound"):
                _beep("short")
        risk = ent["stop"] - ent["avg"]
        loc = (f"Locate {_money(ent['locate_usd'])} charged to this trade." if ent.get("locate_usd")
               else "Using shares located earlier today (already paid)." if ent["locate_px"] else "No locate fee.")
        if ent.get("jr") and ent.get("jr_lock_stop"):
            loc += (f" Lock: once it trades {_fp(ent['jr_lock_trigger'])} the stop moves to {_fp(ent['jr_lock_stop'])}."
                    + (f" The bot covers at {JR_EOD_COVER_TIME}." if JR_EOD_COVER_TIME else " No automatic cover at the close."))
        part = f" ({filled:,} of {ent['qty']:,})" if filled < ent["qty"] else ""
        self._notify(f"{bs.sym} - short {filled:,} @ {_fp(ent['avg'])}{part}  ·  stop "
                     f"{_fp(px_round(ent['stop'], True))} {'going in' if stop else 'level'}",
                     f"{SETUP_NAME.get(ent['setup'], ent['setup'])} short. {loc}", "short", bs=bs, chart=True, critical=True,
                     tag="SHORT FILLED",
                     fields=[("Position", f"{_money(ent['avg'] * filled)}\n{ACCOUNT_PCT:g}% of equity", True),
                             ("Risk", f"{_money(risk * filled)}\n({risk / ent['avg'] * 100:.1f}% to the stop)", True),
                             ("Locate", (f"{_money(ent['locate_usd'])}\ncharged to this trade" if ent.get("locate_usd")
                                         else "located earlier\n(already paid)" if ent["locate_px"] else "none"), True)],
                     marks=[{"t": ent["t"] // 60 * 60, "price": ent["avg"], "text": "SHORT", "color": "#f23645"}],
                     levels=[{"price": ent["avg"], "color": "#d1d4dc", "style": "solid", "title": "entry"},
                             {"price": px_round(ent["stop"], True), "color": "#f23645", "style": "dash", "title": "stop"}])
        if stop:
            await self._ensure_stop(bs, filled)
        if first:
            self._state_save()                           # 3.12: a restart takes the trade back with its setup / stop
        return True

    async def _manage_entry(self, bs, force=False):
        mono = time.monotonic()
        if mono < bs.next_poll and not force:
            return
        bs.next_poll = mono + ORDER_POLL_SEC
        ent = bs.entry
        o = await self._tz(self.tz.order, self.acc, ent["coid"])
        if not o:
            return
        status = o.get("orderStatus", "")
        await self._entry_fill(bs, o)
        if bs.phase != "working":
            return
        if ent["filled"] > 0 and bs.stop_owner == "bot" and (not bs.stop_coid or bs.stop_qty != ent["filled"]):
            await self._ensure_stop(bs, ent["filled"])  # a stop that could not go out earlier (network) - try again
            if bs.phase != "working":
                return
        if status in DONE_STATES:
            # cancelled by you: in the orders panel, or at TradeZero (cancelled without the bot asking)
            by_you = bool(ent.get("user_cancel")) or (status == "Canceled" and not ent.get("cancel_sent") and not ent.get("why"))
            if status == "Rejected":
                self._notify(f"❌ {bs.sym}: short order rejected", str(o.get("text")), "err")
            if ent["filled"] > 0:
                if by_you:
                    self._notify(f"✋ {bs.sym}: you cancelled the rest of the entry",
                                 f"{ent['filled']:,} of {ent['qty']:,} shares filled - they stay short with the bot's stop.",
                                 "warn", bs=bs)
                elif status != "Filled":
                    self._log(f"{bs.sym}: entry closed ({status}) with {ent['filled']} of {ent['qty']} filled")
                bs.phase = "short"
                await self._ensure_stop(bs, ent["filled"])
            else:
                if by_you:
                    self._skip_setup(bs, ent)
                    self._notify(f"✋ {bs.sym}: you cancelled the {SETUP_NAME.get(ent['setup'], ent['setup'])} short - trade skipped",
                                 f"The bot ignores this setup and keeps watching {bs.sym} for the next one.", "warn",
                                 bs=bs, chart=True, critical=True, stage="skipped")
                elif status != "Rejected":
                    self._notify(f"{bs.sym}: short order {status.lower()} - nothing filled", ent.get("why", ""), "dim",
                                 bs=bs, stage="skipped")
                bs.entry, bs.phase = None, "idle"
            return
        keep, why = self._keep_entry(bs, self._wall())
        if not keep and not ent["cancel_sent"]:
            ent["why"] = why
            self._log(f"{bs.sym}: cancelling the short order ({why})")
            await self._tz(self.tz.cancel, self.acc, ent["coid"])
            ent["cancel_sent"] = True                    # set after TradeZero took it (a network error tries again)
            bs.next_poll = time.monotonic() + 0.7

    async def _cancel_wait(self, bs, coid):
        """Cancel an order and wait for it; False if it filled meanwhile (the position is then closed)."""
        await self._tz(self.tz.cancel, self.acc, coid)
        for _ in range(12):
            await asyncio.sleep(0.4)
            o = await self._tz(self.tz.order, self.acc, coid) or {}
            if o.get("orderStatus") in DONE_STATES:
                if o.get("orderStatus") == "Filled" and bs.entry and int(_fnum(o.get("executed"))) >= bs.entry["filled"]:
                    await self._finish(bs, _fnum(o.get("priceAvg")), "Stop")
                    return False
                break
        if bs.stop_coid == coid:
            bs.stop_coid = None
        return True

    async def _manage_short(self, bs):
        ent0 = bs.entry or {}
        halted = bs.halt is not None                     # 3.12: during a halt nothing is sent (it waits for the reopen)
        if ent0.get("jr") and not halted:                # 3.7: Jay-read events (EOD cover, lock) go first
            if bs.jr_eod:
                bs.jr_eod = False
                if JR_EOD_COVER_TIME:
                    await self._start_cover(bs, "EOD")
                    return
            if bs.jr_lock is not None:
                lk, bs.jr_lock = bs.jr_lock, None
                await self._jr_apply_lock(bs, lk)
                return
        mono = time.monotonic()
        if mono < bs.next_poll:
            return
        bs.next_poll = mono + STOP_POLL_SEC
        ent = bs.entry
        if ent.get("stop") is None:                          # taken over without a stop: top of the day +3%
            e = bs.eng or {}
            if jr_ready() and bs.jr is not None and bs.jr.reader.rh > 0 and not math.isinf(bs.jr.reader.rh):
                ent["top"] = bs.jr.reader.rh                     # Jay-read: the regular-hours high +3%
                ent["stop"] = ent["top"] * (1 + JR.HOD_STOP_PCT / 100.0)
                if getattr(bs.jr, "jr2", None) is not None and bs.jr.reader.hod > 0:   # 3.13.0: Jay-read 2 = HOD +5%
                    ent["stop"] = bs.jr.reader.hod * (1 + JR2.HOD_STOP_PCT / 100.0)
            else:                                            # no read: the high of day +3%
                if not e.get("hod"):
                    return
                ent["stop"] = e["hod"] * 1.03
                ent["top"] = e["hod"]
        if bs.stop_guard is not None:                        # 3.12: TradeZero rejected / cancelled the stop
            await self._guard_stop(bs)
            return
        if not bs.stop_coid:
            if bs.stop_missing_since is None and bs.stop_owner == "bot" and not ent.get("stop_live"):
                await self._ensure_stop(bs, ent["filled"])          # first stop of this trade
                return
            await self._stop_missing(bs)
            return
        o = await self._tz(self.tz.order, self.acc, bs.stop_coid)
        if not o:
            return
        status = o.get("orderStatus", "")
        if status == "Filled" or (status in DONE_STATES and int(_fnum(o.get("executed"))) >= ent["filled"]):
            await self._finish(bs, _fnum(o.get("priceAvg"), ent.get("stop_live") or ent["stop"]),
                               ("Lock" if ent.get("jr_locked") else "Stop") if bs.stop_owner == "bot" else "Your stop")
        elif status == "Rejected":                                    # 3.12: never a panic cover (AZTR)
            self._stop_lost(bs, "TradeZero rejected the stop", str(o.get("text") or ""))
            await self._guard_stop(bs)
        elif status in ("Canceled", "DoneForDay", "Expired"):
            text = str(o.get("text") or "")
            if halted or "halt" in text.lower():                     # TradeZero dropped it in the halt - not you
                self._stop_lost(bs, "TradeZero cancelled the stop during the halt", text)
                await self._guard_stop(bs)
            else:
                bs.stop_coid, bs.stop_qty = None, 0
                await self._stop_missing(bs)
        else:
            sp = _fnum(o.get("priceStop"))
            live = ent.get("stop_live") or ent["stop"]
            if sp > 0 and abs(sp - live) > 1e-6:                     # you changed the stop price at TradeZero
                ent["stop_live"] = sp
                ent["user_stop"] = True
                self._state_save()
                self._notify(f"✏ {bs.sym}: stop changed by you {_fp(live)} → {_fp(sp)}",
                             "The bot now follows your stop.", "warn", bs=bs, chart=True, critical=True)
            await self._user_stop_too(bs)                            # 3.12: your own stop next to the bot's

    def _cover_ping(self, bs, force=False):
        cv = bs.cover
        if cv is None:
            return
        mono = time.monotonic()
        if not force and mono - cv.get("ping", 0.0) < STOP_PING_SEC:
            return
        cv["ping"] = mono
        left = int(cv["qty"]) - int(cv.get("got", 0))
        h = bs.halt
        if h is not None:
            self._notify(f"\U0001F6A8 {bs.sym}: halted - the cover of {left:,} sh goes at the reopen",
                         f"Halted {h.get('dir') or ''} at {_fp(h.get('px'))} since {h['hms']} ET. Covered at market the "
                         f"instant it reopens ({cv['reason']}).", "err", bs=bs, ping=True, tag="COVER WAITS FOR THE REOPEN")
        else:
            self._notify(f"\U0001F6A8 {bs.sym}: COVER NOT FILLED - {left:,} sh still short",
                         f"{cv.get('text') or 'not filled'}. The bot keeps sending it every {COVER_RETRY_SEC:g} s and stops "
                         f"as soon as TradeZero shows the short closed (also when you cover it there).", "err", bs=bs,
                         ping=True, tag="COVER FAILED  ·  STILL TRYING")

    async def _tz_exit_px(self, bs):
        """(price, 'you' / 'bot') of the shares bought back at TradeZero since this short's entry: every filled
        buy-to-cover order of the stock - the real exit of a short closed outside the bot."""
        try:
            orders = await self._tz(self.tz.orders, self.acc)
        except TZError:
            orders = list(self.orders_raw.values())
        ent = bs.entry or {}
        t_in = int(ent.get("t") or 0)
        n, cost, last = 0, 0.0, (0, "")
        for o in orders:
            if self._osym(o) != bs.sym or _oside(o)[0] != "Cover":
                continue
            ex = int(_fnum(o.get("executed")))
            if ex <= 0:
                continue
            t = self._o_epoch(o)
            if t and t_in and t < t_in - 60:
                continue
            n += ex
            cost += ex * _fnum(o.get("priceAvg"))
            c = str(o.get("clientOrderId") or "")
            if t >= last[0]:
                last = (t, "bot" if c.startswith("LHB") else "you")
        if n and cost > 0:
            return cost / n, last[1]
        return (bs.last_px or _fnum(ent.get("avg"))), ""


    # ---------------- exits ----------------
    async def _start_cover(self, bs, reason, urgent=False):
        ent = bs.entry
        qty = int(ent["filled"]) if ent else 0
        if qty <= 0:
            bs.phase, bs.entry = "idle", None
            return
        if bs.stop_coid:
            if not await self._cancel_wait(bs, bs.stop_coid):
                return
        bs.stop_guard = None
        bs.cover = {"coid": None, "reason": reason, "tries": 0, "qty": qty, "got": 0, "cost": 0.0, "ping": 0.0,
                    "failed": 0.0, "text": ""}
        bs.phase = "covering"
        if bs.halt is not None and not urgent:           # 3.12: TradeZero takes no order in a halt: at the reopen
            self._cover_ping(bs, force=True)
            return
        await self._cover_now(bs, urgent=urgent)
        self._notify(f"{bs.sym}: covering {qty:,} at market", reason, "warn", bs=bs, chart=True, critical=True)

    async def _cover_now(self, bs, urgent=False):
        """Send the cover for the shares still short: market in regular hours (the first try / the reopen), else a limit
        5% over the last price (outside regular hours, and the retries)."""
        cv, ent = bs.cover, bs.entry
        left = int(cv["qty"]) - int(cv.get("got", 0))
        if left <= 0:
            return "nothing left"
        coid = self._coid(bs.sym, "C")
        secs = self._wall() % 86400
        rth = K.rth_s <= secs < K.rth_e
        ctx = {"cover": {"reason": cv["reason"], "tries": cv["tries"] + 1, "qty": cv["qty"]}}
        if rth and (cv["tries"] == 0 or urgent):
            r = await self._place(bs.sym, "cover", "Buy", "Close", "Market", left, "Day", coid=coid, ctx=ctx, urgent=urgent)
            how = "market"
        else:
            lim = px_round((bs.last_px or ent["avg"]) * 1.05, up=True)
            r = await self._place(bs.sym, "cover", "Buy", "Close", "Limit", left, "Day" if rth else "Day_Plus", limit=lim,
                                  coid=coid, ctx=ctx, urgent=urgent)
            how = f"limit {_fp(lim)}"
        cv.update(coid=r.get("clientOrderId") or coid, tries=cv["tries"] + 1)
        bs.next_poll = time.monotonic() + (0.3 if urgent else 0.7)
        if r.get("orderStatus") == "Rejected":
            cv["text"] = self._clean(str(r.get("text") or ""))
        return f"cover {left:,} sh at {how} sent"

    async def _manage_cover(self, bs):
        """3.12: a cover that fails is never a dead end - halted: it waits for the reopen (sent the instant it reopens);
        else sent again every COVER_RETRY_SEC (pinged each minute) until TradeZero shows the short closed - also when you
        closed it there (_check_positions)."""
        mono = time.monotonic()
        if mono < bs.next_poll:
            return
        bs.next_poll = mono + ORDER_POLL_SEC
        cv = bs.cover
        if cv.get("coid"):
            o = await self._tz(self.tz.order, self.acc, cv["coid"])
            if not o:
                return
            status = o.get("orderStatus", "")
            ex = int(_fnum(o.get("executed")))
            if status == "Filled" or (status in DONE_STATES and int(cv.get("got", 0)) + ex >= int(cv["qty"])):
                n = int(cv.get("got", 0)) + ex
                px = (_fnum(cv.get("cost")) + ex * _fnum(o.get("priceAvg"), bs.last_px or 0.0)) / n if n else bs.last_px
                await self._finish(bs, px or 0.0, cv["reason"])
                return
            if status not in DONE_STATES:
                return                                   # working
            cv["got"] = int(cv.get("got", 0)) + ex
            cv["cost"] = _fnum(cv.get("cost")) + ex * _fnum(o.get("priceAvg"))
            cv["coid"], cv["failed"] = None, mono
            cv["text"] = self._clean(str(o.get("text") or status))
            self._log(f"{bs.sym}: cover {status.lower()} ({cv['text']})", "warn")
            if "halt" in cv["text"].lower() and bs.halt is None:
                self._halt_start(bs, "TradeZero")
        if bs.halt is not None:                          # the reopen sends it (_halt_act); pinged every minute
            self._cover_ping(bs)
            return
        if cv["tries"] >= 4:
            if mono - cv.get("failed", 0.0) < COVER_RETRY_SEC:
                return
            self._cover_ping(bs)
        await self._cover_now(bs)

    async def _flatten_one(self, bs, reason):
        if not await self._grab(bs, 20.0):                   # wait for a running step / order change of this symbol
            self._log(f"{bs.sym}: still busy after 20 s - {reason} goes ahead anyway", "warn")
            bs.busy = True
        try:
            if bs.phase == "working" and bs.entry:
                await self._tz(self.tz.cancel, self.acc, bs.entry["coid"])
                await asyncio.sleep(1.0)
                o = await self._tz(self.tz.order, self.acc, bs.entry["coid"]) or {}
                n, avg = self._entry_totals(bs.entry, o)
                if n > bs.entry["filled"]:
                    bs.entry["filled"], bs.entry["avg"] = n, avg
                if bs.entry["filled"] > 0:
                    bs.phase = "short"
                else:
                    bs.entry, bs.phase = None, "idle"
            if bs.phase in ("short", "manual"):
                await self._start_cover(bs, reason)
        except TZError as exc:
            self._notify(f"❌ {bs.sym}: {reason} error", str(exc), "err")
        finally:
            bs.busy = False

    def _tz_short(self, b):
        """3.12: TradeZero's last position list (when fresh) still shows this short (else it was closed there)."""
        if not self.pos_mono or time.monotonic() - self.pos_mono > 20:
            return True
        side, sh = self.pos_snapshot.get(b.sym, ("", 0))
        return side == "Short" and sh > 0

    async def _sell_back_locates(self):
        if not self.located:
            return
        try:
            inv = await self._tz(self.tz.locate_inventory, self.acc)
        except TZError as exc:
            self._log(f"locate sell-back skipped: {exc}", "warn")
            return
        for r in inv:
            sym = str(r.get("symbol"))
            if sym not in self.located or (sym in self.syms and self.syms[sym].phase != "idle"):
                continue
            q = int(_fnum(r.get("available"))) // 100 * 100
            lt = LOCATE_TYPES.get(int(_fnum(r.get("locateType"))))
            if q <= 0 or lt is None:
                continue
            try:
                await self._tz(self.tz.locate_sell, self.acc, sym, q, lt, self._qid(sym, "S"))
                self._notify(f"{sym}: sold back {q:,} unused located shares for credit", lt, "dim")
            except TZError as exc:
                self._log(f"{sym}: locate sell-back failed ({exc})", "warn")

    def _order_row(self, o):
        coid = str(o.get("clientOrderId") or "")
        role, bs = self._role(o)
        st = str(o.get("orderStatus") or "")
        typ = _otype(o)
        qty, ex = int(_fnum(o.get("orderQuantity"))), int(_fnum(o.get("executed")))
        lim, stp = _olimit(o), _ostop(o)
        side, scls = _oside(o)
        live = st not in DONE_STATES and st != "Replaced"
        px = stp if typ in ("Stop", "StopLimit") else lim if typ == "Limit" else None
        by = ROLE_LABEL.get(role, role)
        if role == "bot":                                # a finished / older bot order: entry, stop or cover by its id
            by = {"S": "Bot entry", "P": "Bot stop", "C": "Bot cover"}.get(coid[3:4], "Bot")
        elif role == "long":
            by = {"B": "Long buy", "S": "Long sell", "F": "Long flatten"}.get(coid[3:4], "Long bot")
        if bs is not None and bs.phase == "manual" and role == "you":
            by = "You (your short)"
        return {"c": coid, "s": self._osym(o), "sd": side, "sc": scls, "ty": "Stop Lmt" if typ == "StopLimit" else typ,
                "tif": str(o.get("timeInForce") or ""), "q": qty, "f": ex, "px": _f(px) if px else None,
                "px2": _f(lim) if typ == "StopLimit" and lim else None,
                "ek": ("stop" if typ in ("Stop", "StopLimit") else "limit" if typ == "Limit" else "")
                if live and role not in ("bot", "long") else "",
                "avg": _f(_fnum(o.get("priceAvg"))) if ex else None,
                "t": self._o_clock(o, "startTime", coid), "tu": self._o_clock(o, "lastUpdated", coid) or self._o_clock(o, "startTime", coid),
                "by": by, "r": role, "st": st, "live": live, "op": self.order_ops.get(coid, ""),
                "tx": str(o.get("text") or "")[:160]}

    def _push_orders(self, force=False):
        rows = [self._order_row(o) for o in self.orders_raw.values()]
        pend = sorted([r for r in rows if r["live"]], key=lambda r: r["t"], reverse=True)
        fill = sorted([r for r in rows if not r["live"] and r["f"] > 0], key=lambda r: r["tu"], reverse=True)
        done = sorted([r for r in rows if not r["live"] and r["f"] <= 0], key=lambda r: r["tu"], reverse=True)
        at = datetime.fromtimestamp(self.orders_at, timezone.utc).strftime("%H:%M:%S") if self.orders_at else ""
        payload = {"conn": self.tz_ready(), "err": self.orders_err, "at": at, "acc": self.acc_type if self.acc else "",
                   "pend": pend[:150], "fill": fill[:150], "done": done[:150]}
        js = _dumps(payload)
        if js != self.last_orders_push or force:
            self.last_orders_push = js
            self.be.bridge.call_raw("setOrders", js)

    async def _poll_orders(self):
        if self.orders_busy or not self.tz_ready():
            return
        self.orders_busy = True
        try:
            try:
                orders = await self._tz(self.tz.orders, self.acc)
            except TZError as exc:
                self.orders_err = "no answer from TradeZero - retrying" if exc.status == 0 else str(exc)[:140]
                self._push_orders()
                return
            self.orders_err = ""
            now = self._wall()
            raw = {}
            for o in orders:
                coid = str(o.get("clientOrderId") or "")
                if coid:
                    raw[coid] = o
                    self.order_seen.setdefault(coid, now)
            self.orders_raw, self.orders_at = raw, now
        finally:
            self.orders_busy = False
        await self._settle_orphans(orders)
        self._push_orders()

    async def order_cancel(self, coid):
        await self._order_cmd(coid, "cancel", None)

    async def order_modify(self, coid, price):
        await self._order_cmd(coid, "modify", price)

    async def _order_cmd(self, coid, op, price):
        o = self.orders_raw.get(coid)
        if o is None or not self.tz_ready():
            self._ui_msg("err", "That order is not in TradeZero's list any more")
            return
        if coid in self.order_ops:
            return
        sym = self._osym(o)
        self.order_ops[coid] = op
        self._push_orders(force=True)
        try:
            # the panel row can be 2 s old: read the order again before touching it
            fresh = await self._tz(self.tz.order, self.acc, coid)
            if not fresh or fresh.get("orderStatus") in DONE_STATES or fresh.get("orderStatus") == "Replaced":
                st = (fresh or {}).get("orderStatus") or "gone"
                self._ui_msg("warn", f"{sym}: that order is already {st.lower()} - nothing changed")
                return
            o = fresh
            self.orders_raw[coid] = o
            if op == "modify":
                price = _tick_px(float(price))
                why = self._check_edit(o, price)
                if why:
                    self._ui_msg("err", f"{sym}: {why}")
                    return
            role, bs = self._role(o)
            if op == "modify" and role == "bot":
                self._ui_msg("err", f"{sym}: the bot no longer manages this order - cancel it instead")
                return
            if op == "modify" and role == "long":
                self._ui_msg("err", f"{sym}: the premarket long bot prices this order itself - cancel it instead")
                return
            if role in ("entry", "stop", "ystop", "cover"):
                if not await self._grab(bs):
                    self._ui_msg("warn", f"{sym}: the bot is working on this order right now - try again in a second")
                    return
                try:
                    role2, _ = self._role(o)             # the trade may have moved on while we waited
                    if role2 != role:
                        self._ui_msg("warn", f"{sym}: the order changed meanwhile - nothing done, check the panel")
                        return
                    if op == "cancel":
                        fn = {"entry": self._user_cancel_entry, "stop": self._user_cancel_stop,
                              "ystop": self._user_cancel_stop, "cover": self._user_cancel_cover}[role]
                        await fn(bs)
                    elif role == "entry":
                        await self._modify_entry(bs, price)
                    elif role in ("stop", "ystop"):
                        await self._panel_stop(bs, price)
                    else:
                        await self._modify_cover(bs, price)
                finally:
                    bs.busy = False
                    self._status(bs)
            elif op == "cancel":
                await self._cancel_plain(o)
            else:
                await self._modify_plain(o, price)
        except TZError as exc:
            self._ui_msg("err", f"{sym}: {'cancel' if op == 'cancel' else 'price change'} failed - {exc}")
        except Exception:
            log.exception("order %s %s", op, coid)
            self._ui_msg("err", f"{sym}: {op} failed (details in the log file)")
        finally:
            self.order_ops.pop(coid, None)
            self.next_orders = 0.0
            self._push_orders(force=True)
            self._push(force=True)

    async def _cancel_plain(self, o):
        coid, sym = str(o.get("clientOrderId")), self._osym(o)
        await self._tz(self.tz.cancel, self.acc, coid)
        o2 = await self._wait_done(coid, 4.0) or {}
        st = o2.get("orderStatus")
        if st == "Filled":
            self._ui_msg("warn", f"{sym}: the order filled before the cancel arrived")
        else:
            self._ui_msg("info", f"{sym}: order cancelled" if st in DONE_STATES else f"{sym}: cancel sent")

    async def _user_cancel_entry(self, bs):
        """You cancel the bot's short order: nothing filled = the trade is skipped (bot + engine look for the next setup);
        a partial fill stays short with the bot's stop."""
        ent = bs.entry
        if not ent.get("cancel_sent"):
            await self._tz(self.tz.cancel, self.acc, ent["coid"])
            ent["cancel_sent"] = True
        ent["user_cancel"], ent["why"] = True, "cancelled by you"
        for _ in range(12):
            await asyncio.sleep(0.4)
            await self._manage_entry(bs, force=True)
            if bs.phase != "working":
                break
        if bs.phase == "idle":
            self._ui_msg("info", f"{bs.sym}: entry cancelled - the bot skips this setup and watches for the next one")
        elif bs.phase == "short":
            self._ui_msg("info", f"{bs.sym}: rest of the entry cancelled - {bs.entry['filled']:,} sh short with the bot's stop")
        else:
            self._ui_msg("info", f"{bs.sym}: cancel sent - waiting for TradeZero")

    async def _user_cancel_cover(self, bs):
        """You cancel the bot's cover order: the short stays open, without a stop, and you manage it."""
        cv, ent = bs.cover, bs.entry
        await self._tz(self.tz.cancel, self.acc, cv["coid"])
        o = await self._wait_done(cv["coid"], 4.0) or {}
        done = int(_fnum(o.get("executed")))
        if o.get("orderStatus") == "Filled" or done >= cv["qty"]:
            await self._finish(bs, _fnum(o.get("priceAvg"), bs.last_px or 0.0), cv["reason"])
            self._ui_msg("warn", f"{bs.sym}: the cover filled before the cancel - the short is closed")
            return
        if done > 0:
            ent["filled"] = max(0, ent["filled"] - done)
        bs.cover, bs.phase = None, "manual"
        self._notify(f"✋ {bs.sym}: cover cancelled - {ent['filled']:,} sh still short with NO stop",
                     "You manage this short now (Cover button or TradeZero). The Stop button hands it back to the bot.",
                     "err", bs=bs, chart=True, ping=True)
        self._ui_msg("warn", f"{bs.sym}: cover cancelled - the short is open with no stop")

    async def _modify_entry(self, bs, price):
        """New price for the bot's short order (TradeZero cannot modify: cancel, then a new order for the shares left).
        Your price is kept until it fills, you cancel it, or the setup's entry window ends. If the change cannot be
        completed the setup is skipped - the bot never falls back to its own price."""
        ent = bs.entry
        old_coid, old_px = ent["coid"], ent["limit"]
        await self._tz(self.tz.cancel, self.acc, old_coid)
        ent["cancel_sent"], ent["why"] = True, "price change"
        o = await self._wait_done(old_coid) or {}
        st = o.get("orderStatus")
        if st not in DONE_STATES:
            ent["user_cancel"], ent["why"] = True, "price change not completed"
            self._ui_msg("err", f"{bs.sym}: TradeZero did not confirm the cancel in time - no new order sent; the old "
                                "order is being cancelled and this setup is skipped")
            return
        await self._entry_fill(bs, o)
        if bs.phase != "working" or bs.entry is not ent:
            self._ui_msg("warn", f"{bs.sym}: the trade moved on during the change ({bs.phase}) - no new order sent")
            return
        ex = int(_fnum(o.get("executed")))
        if ex:                                           # roll this order's fills into the trade
            ent["cost_prev"] = _fnum(ent.get("cost_prev")) + ex * _fnum(o.get("priceAvg"), old_px)
            ent["filled_prev"] = int(ent.get("filled_prev", 0)) + ex
        left = ent["qty"] - ent["filled"]
        if st == "Filled" or left <= 0:
            bs.phase = "short"
            await self._ensure_stop(bs, ent["filled"])
            self._ui_msg("info", f"{bs.sym}: the short filled before the price change")
            return
        coid = self._coid(bs.sym, "S")
        failed = ""
        try:
            r = await self._place(bs.sym, "entry", "Sell", "Open", "Limit", left, "Day", limit=price, coid=coid,
                                  ctx={"ent": dict(ent, coid=coid, limit=price, user_px=True, cancel_sent=False, why="",
                                                   user_cancel=False)})
            if r.get("orderStatus") == "Rejected":
                failed = f"rejected: {r.get('text')}"
        except TZError as exc:
            failed = ("no answer from TradeZero - if the order arrives anyway the bot tracks it" if exc.status == 0 or exc.status >= 500
                      else str(exc))
        if failed:
            if ent["filled"] > 0:
                bs.phase = "short"
                await self._ensure_stop(bs, ent["filled"])
            else:
                self._skip_setup(bs, ent)
                bs.entry, bs.phase = None, "idle"
            self._notify(f"❌ {bs.sym}: new short price {_fp(price)} not placed", f"{failed}. The old order is cancelled"
                         + (f"; {ent['filled']:,} filled shares stay short with the bot's stop." if ent["filled"] > 0
                            else " and this setup is skipped."), "err", bs=bs)
            self._ui_msg("err", f"{bs.sym}: new price not placed ({failed[:80]})")
            return
        ent.update(coid=r.get("clientOrderId") or coid, limit=price, user_px=True, cancel_sent=False, why="", user_cancel=False)
        bs.next_poll = time.monotonic() + 0.5
        last = self._entry_last_time(ent)
        self._notify(f"✏ {bs.sym}: short limit moved {_fp(old_px)} → {_fp(price)} by you",
                     f"{left:,} shares. Kept until it fills, you cancel it, or {last}.", "warn", bs=bs, chart=True)
        self._ui_msg("info", f"{bs.sym}: short limit now {_fp(price)} ({left:,} sh)")

    async def _modify_cover(self, bs, price):
        cv = bs.cover
        await self._tz(self.tz.cancel, self.acc, cv["coid"])
        o = await self._wait_done(cv["coid"]) or {}
        st, done = o.get("orderStatus"), int(_fnum(o.get("executed")))
        if st == "Filled" or done >= cv["qty"]:
            await self._finish(bs, _fnum(o.get("priceAvg"), bs.last_px or 0.0), cv["reason"])
            self._ui_msg("info", f"{bs.sym}: the cover filled before the price change")
            return
        if st not in DONE_STATES:
            self._ui_msg("err", f"{bs.sym}: TradeZero did not confirm the cancel - cover price not changed")
            return
        left = cv["qty"] - done
        secs = self._wall() % 86400
        tif = "Day" if K.rth_s <= secs < K.rth_e else "Day_Plus"
        coid = self._coid(bs.sym, "C")
        try:
            r = await self._place(bs.sym, "cover", "Buy", "Close", "Limit", left, tif, limit=price, coid=coid,
                                  ctx={"cover": dict(cv, qty=left)})
        except TZError as exc:
            bs.cover, bs.phase = None, "manual"
            self._notify(f"\U0001F6A8 {bs.sym}: new cover order failed - {left:,} sh still short with NO stop",
                         f"{exc}. You manage this short now (Cover button or TradeZero).", "err", bs=bs, ping=True)
            self._ui_msg("err", f"{bs.sym}: new cover failed - the short is open with no stop")
            return
        cv.update(coid=r.get("clientOrderId") or coid, qty=left, user=True)
        bs.next_poll = time.monotonic() + 0.5
        self._ui_msg("info", f"{bs.sym}: cover limit now {_fp(price)} ({left:,} sh)")
