# -*- coding: utf-8 -*-
"""LH Short Bot - Bot: the stop guard, user stops, halts and the reopen logic.
Part of the Bot class (core/bot/bot_core.py): main.py runs this file in its own namespace. Code moved here unchanged."""

class _BotStopsHalts:

    def live_blocked(self):
        return self.acc_type.lower() == "live" and not ALLOW_LIVE_TRADING

    async def set_stop(self, sym, price):
        bs = self.syms.get(sym)
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if bs is None or bs.phase not in ("short", "manual") or not bs.entry or price <= 0:
            return
        if not await self._grab(bs):
            self._ui_msg("warn", f"{sym}: the bot is working on this short right now - try the stop again in a second")
            return
        try:
            if bs.phase == "manual":                     # a stop from the app hands the short back to the bot
                bs.phase, bs.stop_owner, bs.stop_coid, bs.stop_qty = "short", "bot", None, 0
                self._log(f"{sym}: stop set from the app - the bot manages the short again", "warn")
            bs.entry["user_stop"] = True                 # 3.9.0: your stop - the bot (the lock too) never moves it again
            await self._replace_stop(bs, price, "you (app)")
        except TZError as exc:
            self._notify(f"{sym} - stop change failed", str(exc), "err", bs=bs, tag="STOP NOT CHANGED")
        finally:
            bs.busy = False

    async def _jr_apply_lock(self, bs, lk):
        """STOP_MOVED (the Jay-read lock): the stop goes to the lock level (v1.2: the entry +5%). Already traded over it
        = cover now (the backtest covers at the next open). A stop you changed - at TradeZero or with the app's stop box
        - is kept: the bot never moves it again."""
        ent = bs.entry
        cur = ent.get("stop_live") or ent.get("stop")
        new = px_round(lk, up=True)
        ent["jr_locked"] = True
        lock = JR.lock_text(JR.LOCK_STOP_PCT)
        if bs.stop_owner == "you" or ent.get("user_stop"):     # your stop: never touched by the bot
            self._notify(f"{bs.sym}: Jay-read lock level reached - your stop {_fp(cur)} is kept",
                         f"The strategy would move the stop to {_fp(new)} ({lock}) now. You changed the stop, so the "
                         f"bot leaves it.", "warn", bs=bs, chart=True)
            return
        if cur and new >= cur:
            self._log(f"{bs.sym}: Jay-read lock level {_fp(new)} is not under the stop {_fp(cur)} - stop kept")
            return
        if bs.last_px is not None and bs.last_px >= new:
            self._notify(f"{bs.sym}: Jay-read lock - price {_fp(bs.last_px)} is already over the lock stop {_fp(new)}",
                         f"Faded {JR.LOCK_AFTER_PCT:g}% then bounced: covering at market now.", "warn", bs=bs, chart=True)
            await self._start_cover(bs, "Lock")
            return
        await self._replace_stop(bs, new, f"the Jay-read lock: faded {JR.LOCK_AFTER_PCT:g}% - stop to {lock} "
                                          f"{_fp(ent.get('avg'))}")

    # ---------------- protection: the stop ----------------
    async def _ensure_stop(self, bs, qty):
        ent = bs.entry
        if qty <= 0 or ent.get("stop") is None:
            return
        if bs.stop_coid and bs.stop_qty == qty:
            return
        if bs.stop_guard is not None:                       # 3.12: the guard places it (retries, pings, reopen)
            return
        stop_px = px_round(ent.get("stop_live") or ent["stop"], up=True)
        if bs.stop_coid:                                    # more shares filled: replace the stop (cancel + new)
            if not await self._cancel_wait(bs, bs.stop_coid):
                return
        if bs.halt is not None:                             # 3.12: TradeZero takes no order during a halt - the stop
            ent["stop_live"] = stop_px                      # goes in the instant trading resumes (pinged until then)
            self._stop_lost(bs, "the stock is halted", "")
            return
        coid = self._coid(bs.sym, "P")
        r = await self._place(bs.sym, "stop", "Buy", "Close", "Stop", qty, "Day", stop=stop_px, coid=coid,
                              ctx={"stop": stop_px, "qty": qty})
        coid = r.get("clientOrderId") or coid
        if r.get("orderStatus") == "Rejected":              # 3.12: never a panic cover - see _guard_stop
            ent["stop_live"] = stop_px
            self._stop_lost(bs, "TradeZero rejected the stop", str(r.get("text") or ""))
            await self._guard_stop(bs)
            return
        bs.stop_coid, bs.stop_qty, bs.stop_owner = coid, qty, "bot"
        bs.stop_missing_since, bs.stop_guard = None, None
        ent["stop_live"] = stop_px
        self._state_save()
        self._notify(f"{bs.sym} - stop {_fp(stop_px)} placed for {qty:,} sh", "Buy-to-cover stop order at TradeZero.", "dim",
                     bs=bs, stage="stop", tag="STOP PLACED")

    async def _replace_stop(self, bs, price, who):
        ent = bs.entry
        old = ent.get("stop_live") or ent.get("stop")
        if bs.stop_coid and not await self._cancel_wait(bs, bs.stop_coid):
            return
        ent["stop_live"] = px_round(price, up=True)
        bs.stop_coid, bs.stop_qty = None, 0
        if bs.halt is not None:                             # 3.12: halted - the new stop goes in at the reopen
            self._stop_lost(bs, "the stock is halted", "")
            return
        coid = self._coid(bs.sym, "P")
        r = await self._place(bs.sym, "stop", "Buy", "Close", "Stop", ent["filled"], "Day", stop=ent["stop_live"], coid=coid,
                              ctx={"stop": ent["stop_live"], "qty": ent["filled"]})
        if r.get("orderStatus") == "Rejected":              # 3.12: guarded (placed again / covered over it), pinged
            self._stop_lost(bs, "TradeZero rejected the new stop", str(r.get("text") or ""))
            await self._guard_stop(bs)
            return
        bs.stop_coid, bs.stop_qty, bs.stop_owner = r.get("clientOrderId") or coid, ent["filled"], "bot"
        bs.stop_guard = None
        self._state_save()
        if str(who).startswith("the Jay-read lock"):     # 3.10: STOP MOVED · LOCK with the new worst case
            q, a = ent["filled"], _fnum(ent.get("avg"))
            self._notify(f"{bs.sym} - stop {_fp(old)} → {_fp(ent['stop_live'])}",
                         f"Faded {JR.LOCK_AFTER_PCT:g}% from {_fp(a)}. Worst case now {_money((a - ent['stop_live']) * q)} "
                         f"instead of {_money((a - _fnum(old)) * q)}.", "lock", bs=bs, chart=True, critical=True,
                         tag="STOP MOVED  ·  LOCK")
        else:
            self._notify(f"{bs.sym} - stop {_fp(old)} → {_fp(ent['stop_live'])}", f"Changed by {who}. The bot will not move "
                         f"it again - the lock included.", "info", bs=bs, chart=True, critical=True,
                         tag="STOP CHANGED BY YOU")

    async def _find_user_stop(self, bs):
        orders = await self._tz(self.tz.orders, self.acc)
        mine = [o for o in orders if self._osym(o) == bs.sym and o.get("orderStatus") in OPEN_STATES
                and _fnum(o.get("priceStop")) > 0 and str(o.get("side", "Buy")) == "Buy"]
        mine.sort(key=lambda o: str(o.get("lastUpdated") or o.get("startTime") or ""))
        return mine[-1] if mine else None

    async def _stop_missing(self, bs):
        """Our stop is gone (cancelled at TradeZero): follow your new stop, or warn and put one back."""
        ent = bs.entry
        mono = time.monotonic()
        if bs.halt is not None:                          # 3.12: in a halt it was TradeZero, not you: the guard
            self._stop_lost(bs, "the stop is gone during the halt", "")
            await self._guard_stop(bs)
            return
        user = await self._find_user_stop(bs)
        if user is not None:
            old = ent.get("stop_live") or ent["stop"]
            bs.stop_coid = str(user.get("clientOrderId"))
            bs.stop_qty = int(_fnum(user.get("leavesQuantity"), ent["filled"])) or ent["filled"]
            bs.stop_owner = "bot" if bs.stop_coid.startswith("LHB") else "you"
            ent["stop_live"] = _fnum(user.get("priceStop"))
            bs.stop_missing_since = None
            self._notify(f"✏ {bs.sym}: following your stop {_fp(ent['stop_live'])}", f"(was {_fp(old)})", "warn",
                         bs=bs, chart=True)
            return
        if bs.stop_missing_since is None:
            bs.stop_missing_since = mono
            bs.stop_alerted_at = mono
            self._notify(f"\U0001F6A8 {bs.sym}: the stop was cancelled - position has NO stop",
                         (f"Put back at {_fp(ent.get('stop_live') or ent['stop'])} in {STOP_GRACE_SEC}s unless you place your own."
                          if REPLACE_REMOVED_STOP else "Place a stop at TradeZero."), "err", bs=bs, chart=True, ping=True)
            return
        if REPLACE_REMOVED_STOP and mono - bs.stop_missing_since >= STOP_GRACE_SEC:
            bs.stop_missing_since = None
            bs.stop_owner = "bot"
            last, sp = bs.last_px, px_round(ent.get("stop_live") or ent["stop"], up=True)
            if last and last >= sp:                      # 3.12: already over the stop - it would be rejected: cover
                await self._start_cover(bs, "Stop")
                return
            await self._ensure_stop(bs, ent["filled"])
        elif not REPLACE_REMOVED_STOP and mono - bs.stop_alerted_at > 300:
            bs.stop_alerted_at = mono
            self._notify(f"\U0001F6A8 {bs.sym}: still NO stop on the short", "", "err", ping=True)

    def _stop_px(self, bs):
        ent = bs.entry or {}
        s = ent.get("stop_live") or ent.get("stop")
        return px_round(s, up=True) if s else None

    def _halt_dir(self, bs, px):
        """'UP' / 'DOWN' from the move of the last 5 minutes (LULD: up halts come at the top of a spike), with the %."""
        st = bs.st
        try:
            n = len(st.bars) if st is not None and st.bars is not None else 0
            if not px or n < 2:
                return "", None
            look = [st.bars[i] for i in range(max(0, n - 6), n)]
            ref = float(look[0].open)
            hi = max(float(b.high) for b in look)
            lo = min(float(b.low) for b in look)
            chg = (px / ref - 1.0) * 100.0 if ref > 0 else None
            if px >= hi * 0.97 and (chg is None or chg >= 0):
                return "UP", chg
            if px <= lo * 1.03 and (chg is None or chg <= 0):
                return "DOWN", chg
            return ("UP" if (chg or 0) >= 0 else "DOWN"), chg
        except Exception:
            return "", None

    def _halt_start(self, bs, src, px=None):
        """A halt began (IB tick 49, or TradeZero answered 'halted'): record the time, price and direction; tell Discord
        (an @everyone ping when the bot holds the stock); the watcher keeps a warm TradeZero line and checks the reopen
        every HALT_CHECK_SEC from the halt time + HALT_REOPEN_WAIT_SEC."""
        if bs.halt is not None:
            return
        now = self.now()
        px = px or bs.last_px
        d, chg = self._halt_dir(bs, px)
        prev = bs.halts[-1] if bs.halts else None
        again = (src != "IB" and prev is not None and prev["src"] != "IB" and prev.get("resumed")
                 and self._wall(now) - prev["resumed"] < 120)          # TradeZero still says halted (30 s re-check)
        if again:
            h = dict(prev, mono=time.monotonic(), resumed=None, decided=False, quiet=True)
            bs.halts[-1] = h
        else:
            h = {"t": self._wall(now), "hms": now.strftime("%H:%M:%S"), "px": px, "dir": d, "chg": chg, "src": src,
                 "mono": time.monotonic(), "resumed": None, "n": len(bs.halts) + 1}
            bs.halts.append(h)
        bs.halt, bs.halted = h, True
        try:
            self.loop.create_task(self._halt_watch(bs, h))
        except RuntimeError:
            pass
        if again:
            self._log(f"{bs.sym}: TradeZero still says halted - checking again in 30 s", "warn")
            return
        reopen = datetime.fromtimestamp(h["t"] + HALT_REOPEN_WAIT_SEC, timezone.utc).strftime("%H:%M:%S")
        inpos = self._in_position(bs)
        f = [("Halted at", f"{h['hms']} ET", True), ("Price", _fp(px), True),
             ("Direction", (d or "?") + (f"  ({chg:+.0f}% in 5 min)" if chg is not None else ""), True),
             ("Reopen check", f"from {reopen} ET, every {HALT_CHECK_SEC:g} s", True)]
        if h["n"] > 1:
            f.append(("Halts today", str(h["n"]), True))
        if inpos:
            ent = bs.entry
            sp = self._stop_px(bs)
            f.append(("Your short", f"{int(ent['filled']):,} @ {_fp(ent.get('avg'))}", True))
            f.append(("Stop", (f"{_fp(sp)} at TradeZero" if bs.stop_coid else f"{_fp(sp)} - NOT at TradeZero: goes in at the "
                               f"reopen") if sp else "none", True))
            f.append(("At the reopen", f"opens over {_fp(sp)} → covered at market at once; under it → the stop stays at "
                                       f"TradeZero (put back if TradeZero dropped it). Prices during the halt are ignored."
                      if sp else "you manage this short", False))
        src_t = "" if src == "IB" else " (TradeZero says it is halted)"
        self._notify(f"⏸ {bs.sym} HALTED {d or ''} at {_fp(px)}".replace("  ", " "), f"Halt #{h['n']} today{src_t}.",
                     "err" if inpos else "warn", bs=bs, fields=f, ping=inpos, critical=inpos,
                     tag=f"HALT {d}  ·  {h['hms']}" if d else f"HALT  ·  {h['hms']}")

    async def _halt_watch(self, bs, h):
        """While halted: the stop order's status every STOP_POLL_SEC (TradeZero may drop it - that is not you), the fast
        TradeZero line kept warm, the "STOP NOT PLACED" ping every minute, and from the halt time + 5 min the reopen
        check every HALT_CHECK_SEC on IB's ticker (every IB tick checks it too)."""
        last_poll = last_warm = 0.0
        while bs.halt is h and not self.be.closing:
            try:
                mono = time.monotonic()
                if self._in_position(bs) and self.tz_ready():
                    if bs.stop_coid and mono - last_poll >= STOP_POLL_SEC:
                        last_poll = mono
                        await self._halt_poll_stop(bs)
                    if mono - last_warm >= 5.0:
                        last_warm = mono
                        self._warm_fast()
                    if bs.stop_guard is not None and bs.phase == "short":
                        self._guard_ping(bs)
                    if bs.phase == "covering" and bs.cover is not None:
                        self._cover_ping(bs)
                if bs.halt is not h:
                    break
                age = self._wall() - h["t"]
                if age >= HALT_REOPEN_WAIT_SEC - 1 and bs.ticker is not None:
                    self._on_quote(bs, bs.ticker)       # the per-second reopen check (in case an IB event was missed)
                if (bs.halt is h and h["src"] != "IB" and h.get("resumed") is None and mono - h["mono"] >= 30
                        and bs.last_px):                 # only TradeZero said "halted" and IB shows nothing: try again
                    now = self.now()                     # every 30 s (a rejection starts a new TradeZero halt)
                    h["resumed"], h["resumed_hms"], h["res_mono"] = self._wall(now), now.strftime("%H:%M:%S"), mono
                    self._halt_decide(bs, h, bs.last_px, "TradeZero check - no halt at IB")
            except Exception:
                log.exception("halt watch %s", bs.sym)
            await asyncio.sleep(HALT_CHECK_SEC)

    async def _halt_poll_stop(self, bs):
        """During a halt: is the stop still at TradeZero? (no lock: the reopen must never wait for this call)"""
        coid = bs.stop_coid
        try:
            o = await self._tz(self.tz.order, self.acc, coid)
        except TZError:
            return
        if not o or bs.stop_coid != coid:
            return
        st = str(o.get("orderStatus") or "")
        if st in ("Rejected", "Canceled", "DoneForDay", "Expired"):
            self._stop_lost(bs, f"TradeZero {'rejected' if st == 'Rejected' else 'cancelled'} the stop during the halt",
                            str(o.get("text") or ""))
            self._guard_ping(bs, force=True)

    def _halt_decide(self, bs, h, px, src):
        """The first real price after the reopen: the halt is over. A held short is acted on at once (_halt_act - orders
        first, messages after); otherwise just the RESUMED message."""
        if h.get("decided"):
            return
        h.update(decided=True, open_px=px, open_src=src, dec_mono=time.monotonic())
        bs.halt, bs.halted = None, False
        if bs.phase in ("short", "covering") and self._in_position(bs):
            self.loop.create_task(self._halt_act(bs, h, px, src))
        else:
            self._halt_msg(bs, h, "manual: you manage this short" if bs.phase == "manual" else "", "")

    async def _halt_act(self, bs, h, px, src):
        """The reopen of a halted short. Opens over the stop -> covered at market NOW (if the stop is still at TradeZero
        it triggers by itself - checked for 2 s, then cancelled and covered). Opens under it -> the stop must be at
        TradeZero: placed now if TradeZero dropped it. Nothing else runs first (no chart, no Discord)."""
        if not await self._grab(bs, 1.5, step=0.005):
            self._log(f"{bs.sym}: reopen - the symbol was busy, acting anyway", "warn")
            bs.busy = True
        did, err = "", ""
        try:
            ent = bs.entry
            sp = self._stop_px(bs)
            if not ent or int(ent.get("filled") or 0) <= 0:
                did = "nothing open"
            elif bs.phase == "covering":
                did = await self._cover_now(bs, urgent=True)
            elif sp and px >= sp:
                if bs.stop_coid:
                    did = await self._stop_or_cover(bs)
                else:
                    await self._start_cover(bs, "Stop", urgent=True)
                    did = f"covering at market (opened {_fp(px)}, over the stop {_fp(sp)})"
            elif sp and not bs.stop_coid:
                did = await self._place_guard_stop(bs, urgent=True)
            elif sp:
                did = f"stop {_fp(sp)} stays at TradeZero"
            else:
                did = "no stop level - you manage it"
        except TZError as exc:
            err = self._clean(str(exc))
            if bs.phase == "short" and not bs.stop_coid and bs.stop_guard is None:
                self._stop_lost(bs, "the reopen order failed", err)
        except Exception as exc:
            log.exception("halt act %s", bs.sym)
            err = f"{exc.__class__.__name__}: {exc}"
        finally:
            bs.busy = False
        ms = int((time.monotonic() - h.get("res_mono", h["dec_mono"])) * 1000)
        self.halt_lat.append(ms)
        self._halt_msg(bs, h, did, err, ms)
        self._state_save()

    async def _stop_or_cover(self, bs):
        """Reopened over the stop while the stop is at TradeZero: it triggers on the open by itself. Checked for 2 s; if it
        has not filled, it is cancelled (a fill meanwhile is seen) and the short covered at market."""
        coid = bs.stop_coid
        for _ in range(8):
            await asyncio.sleep(0.25)
            try:
                o = await self.loop.run_in_executor(self.tz_fast, lambda: self.tz.order(self.acc, coid)) or {}
            except TZError:
                continue
            if o.get("orderStatus") == "Filled" or int(_fnum(o.get("executed"))) >= int(bs.entry["filled"]):
                await self._finish(bs, _fnum(o.get("priceAvg"), self._stop_px(bs)), "Stop")
                return "the stop filled on the reopen"
            if o.get("orderStatus") in DONE_STATES:
                break
        await self._start_cover(bs, "Stop", urgent=True)
        return "stop did not trigger in 2 s - covering at market"

    def _halt_msg(self, bs, h, did, err, ms=None):
        if bs.halt is not None and bs.halt.get("quiet"):
            return                                       # TradeZero still halted it: no RESUMED message yet
        dur = int((h.get("resumed") or self._wall()) - h["t"])
        op = h.get("open_px")
        chg = (op / h["px"] - 1.0) * 100.0 if op and h.get("px") else None
        f = [("Halted", f"{h['hms']} ET  ·  {h.get('dir') or '?'}  ·  {_fp(h.get('px'))}", True),
             ("Resumed", f"{h.get('resumed_hms', '?')} ET  ·  {_fp(op)} ({h.get('open_src', '')})", True),
             ("Halted for", f"{dur // 60} min {dur % 60:02d} s", True)]
        if chg is not None:
            f.append(("Reopen vs halt", f"{chg:+.1f}%", True))
        if did or err:
            f.append(("Action", (did or "") + (f" - ERROR {err}" if err else ""), False))
        if ms is not None:
            f.append(("Speed", f"{ms} ms from the reopen to TradeZero's answer", True))
        bad = bool(err) or "covering" in did or "rejected" in did
        self._notify(f"▶ {bs.sym} RESUMED {h.get('resumed_hms', '')} at {_fp(op)}", "", "err" if bad else "info", bs=bs,
                     fields=f, chart=True, critical=True, ping=bool(err),
                     tag=f"HALT OVER  ·  {dur // 60}:{dur % 60:02d}")

    def _stop_lost(self, bs, why, text):
        """The bot's stop is not at TradeZero and you did not remove it (rejected / dropped in a halt). The short is
        guarded until a stop is back: pinged every STOP_PING_SEC, placed again every STOP_RETRY_SEC while trading,
        covered at market if the price trades over it; in a halt: at the reopen (see _halt_act)."""
        ent = bs.entry or {}
        sp = self._stop_px(bs)
        bs.stop_coid, bs.stop_qty, bs.stop_missing_since = None, 0, None
        if "halt" in str(text).lower() and bs.halt is None:
            self._halt_start(bs, "TradeZero")
        g = bs.stop_guard
        if g is None:
            bs.stop_guard = {"px": sp, "since": time.monotonic(), "ping": 0.0, "next": 0.0, "why": why,
                             "text": self._clean(text), "tries": 0}
        else:
            g.update(why=why, text=self._clean(text) or g.get("text", ""))
            if sp:
                g["px"] = sp
        self._log(f"{bs.sym}: NO STOP at TradeZero - {why}" + (f" ({self._clean(text)})" if text else ""), "err")
        if not ent:
            bs.stop_guard = None

    def _guard_ping(self, bs, force=False):
        g, ent = bs.stop_guard, bs.entry
        if g is None or not ent:
            return
        mono = time.monotonic()
        if not force and mono - g["ping"] < STOP_PING_SEC:
            return
        g["ping"] = mono
        mins = int((mono - g["since"]) // 60)
        h = bs.halt
        if h is not None:
            plan = (f"Halted {h.get('dir') or ''} at {_fp(h.get('px'))} since {h['hms']} ET. The stop {_fp(g['px'])} goes in "
                    f"the instant it reopens - or the short is covered at market if it opens over {_fp(g['px'])}.")
        else:
            plan = (f"Placing it again every {STOP_RETRY_SEC:g} s; covered at market if the price trades over "
                    f"{_fp(g['px'])}. Your own stop at TradeZero is taken over.")
        self._notify(f"\U0001F6A8 {bs.sym}: STOP NOT PLACED - {int(ent['filled']):,} sh short, no stop at TradeZero",
                     f"{g['why']}" + (f": {g['text']}" if g.get("text") else "") + f".\n{plan}", "err", bs=bs, ping=True,
                     critical=True, tag=f"STOP NOT PLACED  ·  {mins} MIN" if mins else "STOP NOT PLACED",
                     fields=[("Short", f"{int(ent['filled']):,} @ {_fp(ent.get('avg'))}", True),
                             ("Stop", _fp(g["px"]), True), ("Last", "halted" if h is not None else _fp(bs.last_px), True)])

    async def _guard_stop(self, bs):
        """A stop that must be at TradeZero is not (see _stop_lost): your own stop takes over; trading over the stop =
        covered at market; else the stop is placed again (every STOP_RETRY_SEC); halted = nothing is sent (the reopen
        decides). Discord is pinged every minute until the stop is there."""
        g, ent = bs.stop_guard, bs.entry
        if g is None or not ent:
            bs.stop_guard = None
            return
        mono = time.monotonic()
        user = self._user_stop_in(bs)
        if user is not None:
            bs.stop_guard = None
            self._follow_user_stop(bs, user, "the bot's stop was not at TradeZero")
            return
        halted = bs.halt is not None
        last = bs.last_px
        if not halted and g.get("px") and last and last >= g["px"]:
            bs.stop_guard = None
            await self._start_cover(bs, "Stop rejected" if "reject" in str(g.get("why")) else "Stop")
            return
        self._guard_ping(bs)
        if halted or mono < g["next"]:
            return
        g["next"] = mono + STOP_RETRY_SEC
        await self._place_guard_stop(bs)

    async def _place_guard_stop(self, bs, urgent=False):
        """Place the guarded stop (urgent = the reopen). Returns what happened."""
        g, ent = bs.stop_guard, bs.entry
        sp = (g or {}).get("px") or self._stop_px(bs)
        qty = int(ent["filled"])
        coid = self._coid(bs.sym, "P")
        r = await self._place(bs.sym, "stop", "Buy", "Close", "Stop", qty, "Day", stop=sp, coid=coid,
                              ctx={"stop": sp, "qty": qty}, urgent=urgent)
        if r.get("orderStatus") == "Rejected":
            text = self._clean(str(r.get("text") or ""))
            if bs.stop_guard is None:
                self._stop_lost(bs, "TradeZero rejected the stop", text)
            g = bs.stop_guard
            g["tries"] += 1
            g["text"] = text
            if "halt" in text.lower():
                if bs.halt is None:
                    self._halt_start(bs, "TradeZero")
                return f"stop {_fp(sp)} rejected (TradeZero: halted) - sent again at the reopen"
            if bs.last_px and bs.last_px >= sp:
                bs.stop_guard = None
                await self._start_cover(bs, "Stop rejected", urgent=urgent)
                return f"stop rejected and the price {_fp(bs.last_px)} is over it - covering at market"
            return f"stop {_fp(sp)} rejected ({text}) - placed again every {STOP_RETRY_SEC:g} s"
        tries = (g or {}).get("tries", 0) + 1
        since = (g or {}).get("since")
        bs.stop_coid, bs.stop_qty, bs.stop_owner = r.get("clientOrderId") or coid, qty, "bot"
        ent["stop_live"] = sp
        bs.stop_guard, bs.stop_missing_since = None, None
        self._state_save()
        if not urgent:
            mins = f" after {int((time.monotonic() - since) // 60)} min" if since else ""
            self._notify(f"✅ {bs.sym}: stop {_fp(sp)} is at TradeZero again{mins}", f"Placed on try {tries}.", "ok", bs=bs,
                         tag="STOP PLACED")
        return f"stop {_fp(sp)} placed for {qty:,} sh"

    def _user_stop_in(self, bs):
        """Your own open buy-to-cover stop for this stock in TradeZero's order list (the orders panel reads it every
        ORDERS_POLL_SEC) - the latest one, or None."""
        mine = []
        for c, o in self.orders_raw.items():
            if self._osym(o) != bs.sym or str(c).startswith("LHB") or str(c).startswith("LLB"):
                continue
            if o.get("orderStatus") not in OPEN_STATES or _ostop(o) <= 0:
                continue
            side, _ = _oside(o)
            if side not in ("Cover", "Buy") or str(o.get("openClose") or "Close") == "Open":
                continue
            mine.append(o)
        mine.sort(key=lambda o: str(o.get("lastUpdated") or o.get("startTime") or ""))
        return mine[-1] if mine else None

    def _follow_user_stop(self, bs, o, why):
        ent = bs.entry
        old = ent.get("stop_live") or ent.get("stop")
        bs.stop_coid = str(o.get("clientOrderId"))
        bs.stop_qty = int(_fnum(o.get("leavesQuantity"), ent["filled"])) or int(ent["filled"])
        bs.stop_owner = "you"
        ent["stop_live"], ent["user_stop"] = _ostop(o), True
        bs.stop_missing_since = None
        self._state_save()
        self._notify(f"✏ {bs.sym}: following YOUR stop {_fp(ent['stop_live'])} at TradeZero",
                     f"{why}. Your stop protects the short now (was {_fp(old)}); the bot never moves it.", "warn", bs=bs,
                     tag="YOUR STOP")

    async def _user_stop_too(self, bs):
        """You placed your own stop at TradeZero while the bot's stop is there: two stops could buy back twice the
        shares (= a long). The bot cancels its own and follows yours (when yours covers the whole short)."""
        if bs.stop_owner != "bot" or not bs.stop_coid or not bs.entry:
            return
        o = self._user_stop_in(bs)
        if o is None or str(o.get("clientOrderId")) == bs.stop_coid:
            return
        q = int(_fnum(o.get("leavesQuantity"), _fnum(o.get("orderQuantity"))))
        if q < int(bs.entry["filled"]):
            key = ("ustop_part", str(o.get("clientOrderId")))
            if key not in bs.notes:
                bs.notes.add(key)
                self._notify(f"⚠ {bs.sym}: your stop covers {q:,} of {int(bs.entry['filled']):,} shares",
                             "The bot's stop for all shares stays too - together they could buy back more than you are "
                             "short. Cancel one of them.", "warn", bs=bs, ping=True)
            return
        if not await self._cancel_wait(bs, bs.stop_coid):
            return                                       # the bot's stop filled meanwhile: the trade is closed
        self._follow_user_stop(bs, o, "You placed your own stop - the bot cancelled its stop (never two stops)")

    def _o_clock(self, o, key, coid):
        utc, naive = _tz_time(o.get(key))
        if utc is None and naive is not None:            # no time zone in TradeZero's time: learn ET or UTC once
            seen = self.order_seen.get(coid)
            if self.tz_naive is None and seen is not None and abs(naive - seen) < 900:
                self.tz_naive = "ET"
            elif self.tz_naive is None and seen is not None:
                et = datetime.fromtimestamp(naive, ET_TZ).replace(tzinfo=None)
                if abs(calendar.timegm(et.timetuple()) - seen) < 900:
                    self.tz_naive = "UTC"
            if self.tz_naive == "ET":
                return datetime.fromtimestamp(naive, timezone.utc).strftime("%H:%M:%S")
            if self.tz_naive == "UTC":
                utc = naive
        if utc is not None:
            return datetime.fromtimestamp(utc, ET_TZ).strftime("%H:%M:%S")
        seen = self.order_seen.get(coid)
        return datetime.fromtimestamp(seen, timezone.utc).strftime("%H:%M:%S") if seen else ""

    async def _panel_stop(self, bs, price):
        if bs.stop_owner != "bot":
            bs.stop_owner = "bot"                        # your stop becomes the bot's stop at your price
        try:
            await self._replace_stop(bs, price, "you (orders panel)")
        finally:
            ent = bs.entry or {}
            if bs.phase not in ("short", "working"):
                self._ui_msg("warn", f"{bs.sym}: the stop filled before the change - the short is closed")
            elif bs.stop_coid and abs(_fnum(ent.get("stop_live")) - px_round(price, up=True)) < 1e-9:
                self._ui_msg("info", f"{bs.sym}: stop moved to {_fp(ent['stop_live'])}")
            else:
                self._ui_msg("err", f"{bs.sym}: the stop was NOT moved - the short has no stop right now (see Discord)")

    async def _user_cancel_stop(self, bs):
        """You cancel the bot's stop (or your stop the bot follows): you take the short over - no stop, the bot stops
        managing it and only tracks it until it is covered; then it looks for the next setup on this symbol."""
        ent = bs.entry
        if bs.phase == "working":                        # the stop of a partial fill: the rest of the entry goes first
            if not ent.get("cancel_sent"):
                await self._tz(self.tz.cancel, self.acc, ent["coid"])
                ent["cancel_sent"] = True
            ent["why"] = "you took over the trade"
            o = await self._wait_done(ent["coid"], 6.0)
            if not o or o.get("orderStatus") not in DONE_STATES:
                self._ui_msg("err", f"{bs.sym}: TradeZero did not confirm the cancel of the rest of the entry - "
                                    "the stop is NOT cancelled, try again")
                return
            n, avg = self._entry_totals(ent, o)
            if n > ent["filled"]:
                ent["filled"], ent["avg"] = n, avg       # late fills: counted, no new stop (you take it over)
            ent["user_cancel"] = True
        coid = bs.stop_coid
        if coid and not await self._cancel_wait(bs, coid):
            self._ui_msg("warn", f"{bs.sym}: the stop filled before the cancel - the short is closed")
            return
        bs.stop_coid, bs.stop_qty, bs.stop_missing_since = None, 0, None
        if not bs.entry or bs.entry.get("filled", 0) <= 0:
            bs.entry, bs.phase = None, "idle"
            return
        bs.phase = "manual"
        self._notify(f"✋ {bs.sym}: you took over the short - {ent['filled']:,} sh @ {_fp(ent['avg'])}",
                     "You cancelled the stop: this short has NO stop now and the bot no longer manages it. It is tracked "
                     f"until you cover it (Cover button or TradeZero); then the bot looks for the next setup on {bs.sym}. "
                     "Set a stop with the Stop button to hand it back to the bot.", "err", bs=bs, chart=True)
        self._ui_msg("warn", f"{bs.sym}: stop cancelled - you manage this short now (it has no stop)")

    def _halt_text(self, bs):
        h = bs.halt
        if h is None:
            return ""
        due = datetime.fromtimestamp(h["t"] + HALT_REOPEN_WAIT_SEC, timezone.utc).strftime("%H:%M:%S")
        return f"HALTED {h.get('dir') or ''} {_fp(h.get('px'))} since {h['hms']} (reopen check from {due}) - ".replace("  ", " ")
