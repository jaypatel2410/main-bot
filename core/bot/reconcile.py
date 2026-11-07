# -*- coding: utf-8 -*-
"""Kestrel - Bot: TradeZero connection, reconciliation, restart rebuild, journal, state file.
Part of the Bot class (core/bot/bot_core.py): main.py runs this file in its own namespace. Code moved here unchanged."""

class _BotReconcile:

    # ---------------- 3.12: what a restart keeps (bot_state.json next to the journal) ----------------
    def _state_file(self):
        return os.path.join(os.path.dirname(self.journal) or DATA_DIR, "bot_state.json")

    def _state_save(self):
        """Today's sizing base and every open short (setup, stop, entry time, locate) - a restart takes them back."""
        try:
            today = str(self.now().date())
            st = self._state_load()
            if st.get("date") != today:
                st = {"date": today, "open": {}}
            st["base"], st["base_note"] = self.size_base, self.size_note
            if self.size_closed is not None:
                st["closed_n"], st["closed_usd"] = self.size_closed
            op = st.setdefault("open", {})
            for b in self.syms.values():
                ent = b.entry or {}
                if int(ent.get("filled") or 0) > 0 and b.phase in ("working", "short", "manual", "covering"):
                    op[b.sym] = {k: ent.get(k) for k in self.STATE_KEYS if isinstance(ent.get(k), (int, float, str, bool))}
                elif b.sym in op and not b.entry:
                    op[b.sym]["closed"] = True
            path = self._state_file()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(st, fh, default=str)
            os.replace(tmp, path)
        except Exception:
            log.exception("bot state")

    def open_positions(self):
        """3.9.0: what the bot holds now - asked when you close the app."""
        out = []
        for bs in self.syms.values():
            ent = bs.entry or {}
            if bs.phase in ("short", "manual", "covering") and int(ent.get("filled") or 0) > 0:
                stop = ent.get("stop_live") or ent.get("stop")
                out.append({"sym": bs.sym, "side": "short", "qty": int(ent["filled"]), "avg": _f(ent.get("avg")),
                            "stop": _f(stop) if bs.stop_coid else None, "phase": bs.phase})
            elif bs.phase == "working" and ent:
                out.append({"sym": bs.sym, "side": "short order working", "qty": int(ent.get("filled") or 0),
                            "avg": _f(ent.get("avg")) if ent.get("filled") else None, "stop": None, "phase": bs.phase})
        if self.longbot is not None:
            try:
                for t in self.longbot.open_longs():
                    p = t.day.pos
                    out.append({"sym": t.sym, "side": "long", "qty": int(p.shares), "avg": _f(p.entry), "stop": _f(p.stop),
                                "phase": "long"})
            except Exception:
                log.exception("open longs")
        return out

    def closed_with_positions(self):
        """3.9.0: you close the app and answered No - stops stay at TradeZero, positions stay open."""
        opens = self.open_positions()
        if opens:
            f = []
            for o in opens[:20]:
                if o["side"] == "short" and o.get("stop"):
                    v, c = f"{o['qty']:,} @ {_fp(o['avg'])}\nstop {_fp(o['stop'])} stays at TradeZero", None
                elif o["side"] == "long":
                    v = f"{o['qty']:,} @ {_fp(o['avg'])}\nNO stop at TradeZero (the app watched it)"
                else:
                    v = f"{o['qty']:,}" + (f" @ {_fp(o['avg'])}" if o.get("avg") else "") + "\nNO stop at TradeZero"
                f.append((f"{o['sym']} {o['side']}", v, True))
            f.append(("Note", "Stop orders expire at 16:00 - manage them in TradeZero until the app runs again", False))
            self._notify("Open positions are not managed until the app runs again", "", "err", fields=f, ping=True,
                         tag="APP CLOSED  ·  YOU CHOSE: KEEP POSITIONS", who="System")

    async def reconnect_tz(self):
        if self.tz is not None:
            getattr(self.tz, "close", lambda: None)()
        self.tz = None
        self.tz_status = {"conn": "off", "text": "TradeZero: reconnecting..."}
        self.next_tz_try = 0.0
        self._push(force=True)

    # ---------------- TradeZero connection ----------------
    async def _tz_connect(self):
        cfg = tz_load_keys()
        if not cfg.get("api_key_id") or not cfg.get("api_secret"):
            self.tz = None
            self.tz_status = {"conn": "off", "text": "TradeZero keys not set - click Keys"}
            return
        client = TZClient(cfg["api_key_id"], cfg["api_secret"])
        try:
            accs = await self._tz(client.accounts)
        except TZError as exc:
            client.close()
            self.tz = None
            why = "keys rejected (check Key ID / Secret)" if exc.status in (401, 403, 404) else str(exc)
            if self.tz_status.get("conn") != "error":
                self._notify("TradeZero connection failed - the bot cannot trade",
                             (why + ". Open Keys in the app and paste the TradeZero keys again.") if "keys" in why else why,
                             "err", tag="TRADEZERO LOGIN FAILED" if "keys" in why else "TRADEZERO NOT CONNECTED",
                             who="System", ping=True)
            self.tz_status = {"conn": "error", "text": f"TradeZero: {why}"}
            return
        want = cfg.get("account_id", "")
        acc = next((a for a in accs if str(a.get("account")) == want), None) if want else (accs[0] if accs else None)
        if acc is None:
            self.tz = None
            self.tz_status = {"conn": "error", "text": "TradeZero: the account set in Keys was not found for these keys"}
            return
        first = not self.acc
        if self.tz is not None and self.tz is not client:
            getattr(self.tz, "close", lambda: None)()
        self.tz, self.acc = client, str(acc.get("account"))
        self.acc_type = str(acc.get("accountType", ""))
        self.acc_info = acc
        self.route = (cfg.get("route") or "").strip() or None
        self.tz_status = {"conn": "connected", "text": f"TradeZero {self.acc_type}"}   # 3.10: never the account id
        self._log(f"Connected to TradeZero - {self.acc_type} account, equity ${_fnum(acc.get('equity')):,.0f}")
        if first and self.is_paper() and AUTO_TRADE_ON_START_PAPER and not self.auto:
            self.auto = True
            self._log("Paper account: auto-trade switched ON (AUTO_TRADE_ON_START_PAPER)", "warn")
        if self.live_blocked():
            self._notify("Live account - the bot will not place orders", "ALLOW_LIVE_TRADING = False. Signals still post "
                         "here as alerts.", "warn", tag="LIVE ACCOUNT LOCKED", who="System")
        if not first:
            self._notify("TradeZero connected again", "Every order and position is checked again.", "ok",
                         tag="TRADEZERO BACK", who="System")
        self.net_alerted = False
        await self._reconcile()

    async def _refresh_account(self):
        try:
            info = await self._tz(self.tz.account, self.acc)
            if isinstance(info, dict) and info:
                info.setdefault("buyingPower", info.get("bp"))
                self.acc_info.update(info)
                self.acct_mono = time.monotonic()        # 3.12: the sizing base waits for this after a close
            pnl = await self._tz(self.tz.pnl, self.acc)
            if isinstance(pnl, dict) and "dayPnl" in pnl:
                self.day_pnl = _fnum(pnl.get("dayPnl"))
            if self.tz_status.get("conn") != "connected":
                self.tz_status = {"conn": "connected", "text": f"TradeZero {self.acc_type}"}   # 3.10: never the account id
        except TZError as exc:
            if self._net_quiet(exc):
                self._log(f"account refresh: no answer from TradeZero ({exc.text})", "warn")
                return
            first = self.tz_status.get("conn") != "error"
            self.tz_status = {"conn": "error", "text": f"TradeZero: {exc}"}
            if first:
                self._notify("No answer from TradeZero", str(exc) + ". Retrying. Stops already at TradeZero keep working. "
                             "No new orders until it answers.", "err", tag="TRADEZERO NOT ANSWERING", who="System",
                             ping=True)

    @staticmethod
    def _osym(o):
        return str(o.get("symbol") or o.get("tradedSymbol") or "")

    async def _reconcile(self):
        """On (re)connect: take over shorts in watchlist symbols (with your stop if there is one), cancel stale entries."""
        try:
            pos = await self._tz(self.tz.positions, self.acc)
            orders = await self._tz(self.tz.orders, self.acc)
        except TZError as exc:
            self._log(f"could not read positions / orders: {exc}", "warn")
            return
        open_orders = [o for o in orders if o.get("orderStatus") in OPEN_STATES]
        for o in open_orders:
            coid = str(o.get("clientOrderId", ""))
            sym = self._osym(o)
            if coid.startswith("LHBS") and sym in self.syms and self.syms[sym].phase == "idle":
                try:
                    await self._tz(self.tz.cancel, self.acc, coid)
                    self._log(f"{sym}: cancelled an old entry order {coid}")
                except TZError:
                    pass
        for p in pos:
            sym, side, sh = str(p.get("symbol", "")), str(p.get("side", "")), abs(int(_fnum(p.get("shares"))))
            if side != "Short" or sh <= 0 or str(p.get("securityType", "Stock")) != "Stock":
                continue
            bs = self.syms.get(sym)
            if bs is None:
                self._notify(f"Open short {sym} ({sh} sh) is not on the watchlist", "The bot leaves it alone.", "warn")
                continue
            if bs.phase != "idle":
                continue
            self._adopt_short(bs, sh, _fnum(p.get("priceAvg")), open_orders)
        self.pos_snapshot = {str(p.get("symbol")): (str(p.get("side")), abs(int(_fnum(p.get("shares"))))) for p in pos
                             if abs(_fnum(p.get("shares"))) > 0}
        self.pos_mono = time.monotonic()
        if self.rebuilt_day != self.now().date():        # 3.12: today's trades from TradeZero (once a day)
            self.rebuilt_day = self.now().date()
            try:
                self._rebuild_today(orders, pos)
            except Exception:
                log.exception("rebuild today")

    def _journal_today(self):
        """Today's rows of the trade journal (dicts)."""
        try:
            if not os.path.exists(self.journal):
                return []
            rows = pd.read_csv(self.journal, dtype=str).fillna("")
        except Exception:
            return []
        today = str(self.now().date())
        return rows[rows["date"] == today].to_dict("records")

    def _rebuild_today(self, orders, pos):
        """3.12: after a start: today's bot shorts from TradeZero's order list, not only the journal. A short of the bot
        that closed while the app was off (or was never booked - you covered it at TradeZero) is written to the journal
        with its real prices; every symbol's trades today come back (the summary, the journal screen, the "done for the
        day" rule); the trade count too. One System message says what TradeZero shows."""
        today = str(self.now().date())
        st = self._state_load()
        st_open = (st.get("open") or {}) if st.get("date") == today else {}
        by_sym = {}
        for o in orders:
            ex = int(_fnum(o.get("executed")))
            c = str(o.get("clientOrderId") or "")
            if ex <= 0 or c.startswith("LLB"):
                continue
            side, _ = _oside(o)
            if side not in ("Short", "Cover"):
                continue
            by_sym.setdefault(self._osym(o), []).append((self._o_epoch(o), side, ex, _fnum(o.get("priceAvg")), c, _otype(o)))
        jr_rows = self._journal_today()
        added, n_entries, lines = [], 0, []
        for sym, fl in sorted(by_sym.items()):
            if not any(c.startswith("LHBS") for _, _, _, _, c, _ in fl):
                continue                                 # never a short of the bot today: yours, left alone
            fl.sort(key=lambda x: x[0])
            trades, cur = [], None
            for t, side, ex, px, c, typ in fl:
                if side == "Short":
                    if cur is None:
                        cur = {"tin": t, "sh": 0, "cost": 0.0, "out": 0, "ocost": 0.0, "bot": False, "last": None}
                    cur["sh"] += ex
                    cur["cost"] += ex * px
                    cur["bot"] = cur["bot"] or c.startswith("LHBS")
                elif cur is not None:
                    take = min(ex, cur["sh"] - cur["out"])
                    cur["out"] += take
                    cur["ocost"] += take * px
                    cur["last"], cur["tout"] = (c, typ), t
                    if cur["out"] >= cur["sh"]:
                        trades.append(cur)
                        cur = None
            n_entries += sum(1 for x in trades if x["bot"]) + (1 if cur is not None and cur["bot"] else 0)
            closed = [x for x in trades if x["bot"]]
            have = [rw for rw in jr_rows if rw.get("symbol") == sym]
            for x in closed[len(have):]:                 # the journal misses these
                c, typ = x["last"]
                reason = ("Stop" if c.startswith("LHBP") else "Cover" if c.startswith("LHBC")
                          else "Your stop" if typ in ("Stop", "StopLimit") else "Covered by you")
                rec = st_open.get(sym) or {}
                qty, avg, ex_px = int(x["sh"]), x["cost"] / x["sh"], x["ocost"] / max(1, x["out"])
                fee = _fnum(rec.get("locate_usd"))
                stop0 = _fnum(rec.get("stop"))
                risk = (stop0 - avg) * qty if stop0 > avg else 0.0
                gross = (avg - ex_px) * qty
                row = {"date": today, "symbol": sym, "setup": rec.get("setup") or "?", "account": self.acc,
                       "top": rec.get("top"), "short_limit": rec.get("limit"), "stop": round(stop0, 4) if stop0 else "",
                       "shares": qty, "entry_avg": round(avg, 4),
                       "entry_time": datetime.fromtimestamp(x["tin"], ET_TZ).strftime("%H:%M:%S") if x["tin"] else "",
                       "exit_avg": round(ex_px, 4),
                       "exit_time": datetime.fromtimestamp(x["tout"], ET_TZ).strftime("%H:%M:%S") if x.get("tout") else "",
                       "exit_reason": reason, "locate_per_share": round(fee / qty, 4) if qty else 0.0,
                       "locate_cost": round(fee, 2), "pnl_gross": round(gross, 2), "pnl_net": round(gross - fee, 2),
                       "R_net": round((gross - fee) / risk, 3) if risk > 0 else 0.0}
                self._journal(row)
                added.append(row)
                lines.append(f"{sym} {qty:,} sh {_fp(avg)} → {_fp(ex_px)} {reason.lower()} {_pm(gross - fee)} (added to the journal)")
        # every watchlist symbol's closed trades today, from the (now complete) journal
        for rw in self._journal_today():
            bs = self.syms.get(rw.get("symbol"))
            if bs is None or getattr(bs, "_rebuilt", False):
                continue
            def ep(hms):
                try:
                    h_, m_, s_ = (int(v) for v in str(hms).split(":"))
                    return calendar.timegm(self.now().date().timetuple()) + h_ * 3600 + m_ * 60 + s_
                except (TypeError, ValueError):
                    return 0
            bs.trades.append({"R": _fnum(rw.get("R_net")), "net": _fnum(rw.get("pnl_net")), "reason": rw.get("exit_reason", ""),
                              "setup": rw.get("setup", ""), "qty": int(_fnum(rw.get("shares"))), "tin": ep(rw.get("entry_time")),
                              "tout": ep(rw.get("exit_time")), "entry": _fnum(rw.get("entry_avg")),
                              "exit": _fnum(rw.get("exit_avg")), "rebuilt": True})
        for bs in self.syms.values():
            bs._rebuilt = True
            if bs.jr is not None:
                self._jr_restore(bs)                     # stop-outs today -> done for the day
        self.trades_today = max(self.trades_today, n_entries)
        opens = [f"{s} {sh:,} sh short" for s, (sd, sh) in self.pos_snapshot.items() if sd == "Short" and sh > 0]
        n_closed = sum(len(b.trades) for b in self.syms.values())
        if added or n_closed or opens:
            self._notify("Today rebuilt from TradeZero",
                         "\n".join(lines) or "The journal already had every closed bot short.", "warn" if added else "dim",
                         who="System", tag="START CHECK  ·  TRADEZERO",
                         fields=[("Bot shorts today", str(n_entries), True), ("Closed (journal)", str(n_closed), True),
                                 ("Open at TradeZero", ", ".join(opens) or "none", False)])
        self._log(f"Rebuilt today from TradeZero: {n_entries} bot short(s), {len(added)} added to the journal")

    def _adopt_short(self, bs, sh, avg, open_orders, why=""):
        """Take over a short at TradeZero the bot does not hold: with the stop order already there (yours or the
        bot's), else the bot's stop (Jay-read: regular-hours high +3%; v16: top +3%) once the candles are loaded.
        3.8.0: an entry of the bot whose answer was an error (orphan) gives its own plan and Jay-read signal."""
        sym = bs.sym
        rec = next((r for r in self.orphans.values() if r["sym"] == sym and r["role"] == "entry" and r["ctx"].get("ent")),
                   None)
        stop_o = next((o for o in open_orders if self._osym(o) == sym and _fnum(o.get("priceStop")) > 0
                       and o.get("orderStatus") in OPEN_STATES), None)
        if rec is not None:
            bs.entry = dict(rec["ctx"]["ent"], filled=sh, qty=max(sh, int(rec["ctx"]["ent"].get("qty", sh))), avg=avg,
                            t=self._wall(), adopted=True, coid=None)
            for k, r in list(self.orphans.items()):
                if r is rec:
                    self.orphans.pop(k, None)
            sg = bs.entry.get("jr_sig")
            if bs.entry.get("jr") and sg is not None and bs.jr is not None and bs.jr.pos is None:
                try:
                    if bs.jr.awaiting is None:
                        bs.jr.awaiting = sg
                    info = bs.jr.entry_filled(avg, self.now())
                    bs.entry["jr_lock_trigger"], bs.entry["jr_lock_stop"] = info.get("lock_trigger"), info.get("lock_stop")
                except Exception:
                    log.exception("jay-read adopt %s", sym)
            bs.entry["stop"] = max(bs.entry.get("stop") or 0.0, avg * (1 + MIN_STOP_ABOVE_FILL_PCT / 100.0))
            self.trades_today += 1
        else:
            bs.entry = {"coid": None, "setup": "?", "top": None, "trigger": None, "zone_hi": None,
                        "stop": None, "qty": sh, "filled": sh, "avg": avg, "t": self._wall(),
                        "adopted": True, "locate_px": 0.0}
            st = self._state_load()                      # 3.12: the bot's own short from before the restart
            rec = ((st.get("open") or {}).get(sym) or {}) if st.get("date") == str(self.now().date()) else {}
            if rec and not rec.get("closed"):
                for k in ("setup", "top", "stop", "limit", "t", "locate_usd", "locate_px", "jr_locked", "user_stop"):
                    if rec.get(k) not in (None, ""):
                        bs.entry[k] = rec[k]
                if not rec.get("jr"):
                    bs.entry.pop("jr", None)
                why = why or ""
        if stop_o:
            bs.stop_coid = str(stop_o.get("clientOrderId"))
            bs.stop_qty = int(_fnum(stop_o.get("leavesQuantity"), sh)) or sh
            bs.stop_owner = "bot" if bs.stop_coid.startswith("LHB") else "you"
            bs.entry["stop"] = _fnum(stop_o.get("priceStop"))
            bs.entry["stop_live"] = bs.entry["stop"]
        else:
            bs.stop_coid, bs.stop_qty, bs.stop_owner = None, 0, "bot"
        bs.stop_missing_since = None
        bs.phase = "short"
        bs.next_poll = 0.0
        plan = (f"stop {_fp(bs.entry['stop'])} ({'yours' if bs.stop_owner == 'you' else 'at TradeZero'})" if stop_o else
                (f"the bot's stop {_fp(px_round(bs.entry['stop'], True))} goes in now" if bs.entry.get("stop") else
                 "no stop found - the bot places its stop (high +3%) as soon as the candles are loaded"))
        self._notify(f"\U0001F6A8 {sym}: open short taken over ({sh:,} sh @ {_fp(avg)})",
                     (why + " " if why else "") + plan + ".", "err" if why else "warn", bs=bs, chart=True, ping=bool(why),
                     critical=True)

    async def _find_unknown_shorts(self, shorts, pos):
        """3.8.0: a short at TradeZero in a watchlist symbol that the bot sent an entry for today but does not hold (the
        entry's answer was an error and it filled) - taken over with a stop once 2 checks UNKNOWN_SHORT_CONFIRM_SEC
        apart agree. Not right after the bot's own trade closed (TradeZero's list can lag)."""
        mono = time.monotonic()
        avg = {str(p.get("symbol")): _fnum(p.get("priceAvg")) for p in pos if str(p.get("side")) == "Short"}
        seen = set()
        for sym, sh in shorts.items():
            bs = self.syms.get(sym)
            if bs is None or bs.busy or bs.phase != "idle" or bs.entry is not None:
                continue
            if mono - getattr(bs, "done_mono", -1e9) < 15:
                continue
            # the bot's: an entry whose answer was an error (orphan), or an entry order of the bot TradeZero never
            # confirmed to it - never a short you opened yourself
            ours = any(r["sym"] == sym and r["role"] == "entry" for r in self.orphans.values()) or any(
                self._osym(o) == sym and str(c).startswith("LHB") and str(o.get("side")) == "Sell"
                and str(o.get("openClose") or "Open") == "Open" and c not in self.known_entries
                and not any(str(c).startswith(k) for k in self.known_entries)
                and (int(_fnum(o.get("executed"))) > 0 or o.get("orderStatus") in OPEN_STATES)
                for c, o in self.orders_raw.items())
            if not ours:
                continue
            seen.add(sym)
            first = self.unknown_short.get(sym)
            if first is None or first[1] != sh:
                self.unknown_short[sym] = (mono, sh)
                continue
            if mono - first[0] < UNKNOWN_SHORT_CONFIRM_SEC or not await self._grab(bs, 2.0):
                continue
            try:
                if bs.phase == "idle" and bs.entry is None:
                    try:
                        orders = await self._tz(self.tz.orders, self.acc)
                    except TZError:
                        orders = []
                    open_orders = [o for o in orders if o.get("orderStatus") in OPEN_STATES]
                    self._adopt_short(bs, sh, avg.get(sym, 0.0) or bs.last_px or 0.0, open_orders,
                                      why="TradeZero shows a short of the bot that it did not know (an order answered "
                                          "with an error filled anyway).")
                    self.unknown_short.pop(sym, None)
            finally:
                bs.busy = False
        for sym in list(self.unknown_short):
            if sym not in seen:
                self.unknown_short.pop(sym, None)

    def _o_epoch(self, o):
        """An order's time as ET wall-clock epoch seconds (0 = unknown)."""
        for key in ("lastUpdated", "startTime"):
            utc, naive = _tz_time(o.get(key))
            if utc is None and naive is not None and self.tz_naive == "UTC":
                utc = naive
            if utc is not None:
                d = datetime.fromtimestamp(utc, ET_TZ)
                return calendar.timegm(d.replace(tzinfo=None).timetuple())
            if naive is not None:
                return naive
        return 0

    def _journal(self, row):
        try:
            new = not os.path.exists(self.journal)
            with open(self.journal, "a", encoding="utf-8", newline="") as fh:
                if new:
                    fh.write(",".join(JOURNAL_COLS) + "\n")
                fh.write(",".join("" if row.get(c) is None else str(row.get(c)) for c in JOURNAL_COLS) + "\n")
        except OSError:
            log.warning("could not write the trade journal")
        try:                                               # 3.14: mirrored to Turso (every PC's Journal shows it)
            import turso
            turso.journal_add("bot_trades.csv", {c: row.get(c) for c in JOURNAL_COLS})
        except Exception:
            pass

    async def _check_positions(self):
        """Shares covered at TradeZero by you: follow partial covers, stop managing a short that is gone."""
        try:
            pos = await self._tz(self.tz.positions, self.acc)
        except TZError:
            return
        shorts = {str(p.get("symbol")): abs(int(_fnum(p.get("shares")))) for p in pos
                  if str(p.get("side")) == "Short" and abs(_fnum(p.get("shares"))) > 0}
        self.pos_snapshot = {str(p.get("symbol")): (str(p.get("side")), abs(int(_fnum(p.get("shares"))))) for p in pos
                             if abs(_fnum(p.get("shares"))) > 0}
        self.pos_mono = time.monotonic()
        try:
            await self._find_unknown_shorts(shorts, pos)          # 3.8.0
        except Exception:
            log.exception("unknown shorts")
        for bs in self.syms.values():
            if (bs.phase in ("short", "manual", "covering") and bs.entry and bs.entry.get("filled", 0) > 0
                    and (not bs.busy or bs.phase == "covering")):
                have = shorts.get(bs.sym, 0)
                if bs.phase == "covering":               # 3.12: never stuck on "Covering..." - TradeZero decides
                    if have > 0:
                        bs.gone_since = None
                    elif bs.gone_since is None:
                        bs.gone_since = time.monotonic()
                    elif time.monotonic() - bs.gone_since > 8 and await self._grab(bs, 3.0):
                        try:
                            bs.gone_since = None
                            if bs.phase == "covering" and bs.entry:
                                px, who = await self._tz_exit_px(bs)
                                cv = bs.cover or {}
                                if cv.get("coid"):
                                    try:
                                        await self._tz(self.tz.cancel, self.acc, cv["coid"])
                                    except TZError:
                                        pass
                                await self._finish(bs, px, cv.get("reason", "Cover") if who == "bot" else "Covered by you")
                        finally:
                            bs.busy = False
                    continue
                if bs.phase == "manual" and have > bs.entry["filled"]:
                    self._log(f"{bs.sym}: your short is {have:,} shares now (was {bs.entry['filled']:,})", "warn")
                    bs.entry["filled"] = have
                if have >= bs.entry["filled"]:
                    bs.gone_since = None
                elif have > 0:
                    bs.gone_since = None
                    old = bs.entry["filled"]
                    bs.busy = True
                    try:
                        part = {"R": 0.0, "net": (bs.entry["avg"] - (bs.last_px or bs.entry["avg"])) * (old - have),
                                "reason": "Partial (you)", "setup": bs.entry.get("setup", ""), "qty": old - have,
                                "entry": bs.entry["avg"], "exit": bs.last_px}
                        bs.trades.append(part)
                        bs.entry["filled"] = have
                        self._notify(f"{bs.sym}: you covered {old - have:,} shares - {have:,} still short",
                                     "You manage this short." if bs.phase == "manual" else
                                     "Stop quantity adjusted." if bs.stop_owner == "bot" else "Your stop is left as you set it.",
                                     "warn", bs=bs, chart=True)
                        if bs.phase == "short" and bs.stop_owner == "bot" and bs.stop_coid:
                            await self._ensure_stop(bs, have)
                    finally:
                        bs.busy = False
                elif bs.gone_since is None:
                    bs.gone_since = time.monotonic()
                elif time.monotonic() - bs.gone_since > 8:
                    bs.gone_since = None
                    px, who = await self._tz_exit_px(bs)     # 3.12: your real fill price, not the last price
                    if bs.entry and bs.phase in ("short", "manual"):
                        await self._finish(bs, px, "Covered by you" if who != "bot" else "Cover")
            else:
                bs.gone_since = None

    # ---------------- orders panel (below the chart) ----------------
    def _role(self, o):
        """Who owns this order: entry / stop / cover of a bot trade, 'ystop' = your stop the bot follows,
        'bot' = an older bot order, 'you' = an order you placed."""
        coid = str(o.get("clientOrderId") or "")
        if coid.startswith("LLB"):                       # v3.5: an order of the premarket long module
            return "long", None
        bs = self.syms.get(self._osym(o))
        if bs is not None and coid:
            if bs.phase == "working" and bs.entry and coid == bs.entry.get("coid"):
                return "entry", bs
            if bs.stop_coid and coid == bs.stop_coid and bs.phase in ("short", "working"):
                return ("stop" if bs.stop_owner == "bot" else "ystop"), bs
            if bs.phase == "covering" and bs.cover and coid == bs.cover.get("coid"):
                return "cover", bs
        return ("bot" if coid.startswith("LHB") else "you"), bs

    def _ui_positions(self):
        """3.10 page data: open positions (Positions tab, Unrealized in the top bar), today's real fills (the chart's
        triangles: short = red down at the fill price, cover / buy = green up, long sell = red down) and today's closed
        trades. Times: ET wall clock as epoch seconds (the chart's time axis)."""
        pos, fills, closed = [], [], []
        for b in self.syms.values():
            ent = b.entry or {}
            last = b.last_px
            if b.phase in ("short", "manual", "covering") and ent.get("filled"):
                q, a = int(ent["filled"]), _fnum(ent.get("avg"))
                stop = ent.get("stop_live") or (px_round(ent["stop"], True) if ent.get("stop") else None)
                pos.append({"sym": b.sym, "side": "Short", "qty": q, "avg": _f(a), "last": _f(last),
                            "unreal": _f((a - last) * q, 2) if last else None, "stop": _f(stop) if b.phase != "manual" else None,
                            "t": datetime.fromtimestamp(int(ent.get("t") or 0), timezone.utc).strftime("%H:%M"),
                            "setup": SETUP_NAME.get(ent.get("setup"), ent.get("setup", "")), "kind": "short"})
            if ent.get("filled") and ent.get("t"):
                fills.append({"sym": b.sym, "t": int(ent["t"]) // 60 * 60, "px": _f(ent.get("avg")), "dir": "down"})
            for t in b.trades:
                if t.get("tin"):
                    fills.append({"sym": b.sym, "t": int(t["tin"]) // 60 * 60, "px": _f(t.get("entry")), "dir": "down"})
                if t.get("tout") and t.get("exit") is not None:
                    fills.append({"sym": b.sym, "t": int(t["tout"]) // 60 * 60, "px": _f(t.get("exit")), "dir": "up"})
                closed.append({"sym": b.sym, "side": "Short", "qty": int(t.get("qty") or 0), "avg": _f(t.get("entry")),
                               "exit": _f(t.get("exit")), "pnl": _f(t.get("net"), 2),
                               "t": datetime.fromtimestamp(int(t.get("tin") or 0), timezone.utc).strftime("%H:%M")
                               if t.get("tin") else "",
                               "setup": SETUP_NAME.get(t.get("setup"), t.get("setup", "")), "res": str(t.get("reason", ""))})
        lb = self.longbot
        if lb is not None and LP is not None:
            try:
                ct = lambda ts: calendar.timegm(LP.et_dt(ts).timetuple()) // 60 * 60
                for tr in lb.open_longs():
                    p = tr.day.pos
                    last = tr.last if LP._pos(tr.last) else None
                    pos.append({"sym": tr.sym, "side": "Long", "qty": int(p.shares), "avg": _f(p.entry), "last": _f(last),
                                "unreal": _f((last - p.entry) * p.shares, 2) if last else None,
                                "stop": _f(p.trailing if p.partial and p.trailing > 0 else p.stop),
                                "t": LP.et_hms(p.t)[:5], "setup": "Premarket long", "kind": "long"})
                for d in lb.days.values():
                    for g in d.legs:
                        fills.append({"sym": g["sym"], "t": ct(g["entry_t"]), "px": _f(g["entry"]), "dir": "up"})
                        fills.append({"sym": g["sym"], "t": ct(g["exit_t"]), "px": _f(g["exit"]), "dir": "down"})
                    if d.pos is not None:
                        fills.append({"sym": d.sym, "t": ct(d.pos.t),
                                      "px": _f(d.pos.entry), "dir": "up"})
                for r in getattr(lb, "closed_rows", []) or []:
                    closed.append({"sym": r["sym"], "side": "Long", "qty": r["sh"], "avg": r["entry"], "exit": r["exit"],
                                   "pnl": r["pnl"], "t": r["t"], "setup": "Premarket long", "res": r["res"]})
            except Exception:
                log.exception("ui positions (long)")
        seen, uniq = set(), []
        for f in fills:
            k = (f["sym"], f["t"], f["px"], f["dir"])
            if f["sym"] and f["px"] is not None and k not in seen:
                seen.add(k)
                uniq.append(f)
        return pos, uniq, closed
