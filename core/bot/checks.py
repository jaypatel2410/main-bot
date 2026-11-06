# -*- coding: utf-8 -*-
"""LH Short Bot 3.15 - part of the Bot class (runs in main.py's namespace like the other core/bot parts).

    Morning check   at the start, 04:55 (before the premarket long) and 09:00 (before the shorts): IB Gateway and its data
                    farms, TradeZero (keys, paper / live), buying power vs the next trade, Discord, the vault feed, the PC
                    clock vs IB's server, the trade database, float lookups, the main-loop watchdog, disk space. Posted to
                    Discord ("all passed", or the failed items with a ping). "Run check now" / "Send to Discord" in the
                    Bot center.
    Stop check      every minute, each open short: a working buy-to-cover stop at TradeZero for the whole position. A bot
                    stop missing twice in a row (orders list refreshes every 2 s) is handed to the stop guard, which places
                    it again at the bot's price and pings Discord. A stop you set yourself is never moved - a short one is
                    only reported. During a halt nothing is sent (the halt rules decide at the reopen). The premarket long
                    has no stop at TradeZero (it sells on the price) - listed as bot-managed.
"""


class _BotChecks:
    # ---------------- 3.15: watchdog (Discord only) + keep the PC awake ----------------
    def _watchdog_start(self):
        """A thread of its own (it must not depend on the loop it watches): the main loop's 1-second tick sets _wd_beat;
        no beat for WATCHDOG_STALL_SEC = Discord @everyone (posted straight from this thread), and again when it is back.
        The same thread keeps Windows from sleeping while the bot runs (SetThreadExecutionState)."""
        import threading
        self.wd_awake, self.wd_last = False, ""

        def run():
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                self.wd_awake = True
            except Exception:
                self.wd_awake = False
            stalled = False
            while True:
                time.sleep(5)
                beat = getattr(self, "_wd_beat", None)
                if beat is None:
                    continue
                age = time.monotonic() - beat
                if age >= WATCHDOG_STALL_SEC and not stalled:
                    stalled = True
                    self.wd_last = datetime.now(ET_TZ).strftime("%H:%M:%S")
                    opens = ", ".join(f"{b.sym} short {int(_fnum((b.entry or {}).get('filled'))):,}"
                                      + (f" (stop {_fp((b.entry or {}).get('stop_live'))} at TradeZero)" if (b.entry or {}).get('stop_live') else "")
                                      for b in list(self.syms.values()) if _fnum((b.entry or {}).get("filled")) > 0) or "none"
                    try:
                        self.dc.send_now(f"🚨 The bot's main loop has not run for {int(age)} s",
                                         f"The bot may be frozen or the PC busy / asleep. Open positions: {opens}.", "err",
                                         tag="WATCHDOG", username=DISCORD_NAME_SYSTEM, ping=True)
                    except Exception:
                        pass
                elif age < 10 and stalled:
                    stalled = False
                    try:
                        self.dc.send_now("✅ The bot's main loop is running again", f"Stalled since {self.wd_last} ET.", "ok",
                                         tag="WATCHDOG", username=DISCORD_NAME_SYSTEM)
                    except Exception:
                        pass
        threading.Thread(target=run, name="watchdog", daemon=True).start()

    def _watchdog_info(self):
        beat = getattr(self, "_wd_beat", None)
        return {"age": int(time.monotonic() - beat) if beat else None, "awake": getattr(self, "wd_awake", False),
                "stall": WATCHDOG_STALL_SEC, "last": getattr(self, "wd_last", "")}

    # ---------------- morning check ----------------
    def _checks_tick(self, now, mono, secs, weekday):
        """From the 1-second tick: the scheduled morning checks and the minute stop check."""
        if not hasattr(self, "_mc_done"):
            self._mc_done, self.mcheck, self.stopchk, self._sc_next, self._sc_miss = set(), None, [], 0.0, {}
            self._mc_start = mono + 45                       # the start check: once the connections had time to come up
        day = str(now.date())
        if self._mc_start and mono >= self._mc_start:
            self._mc_start = 0
            self.loop.create_task(self._morning_check("start", send=True))
        for hm in ("04:55", "09:00"):
            at = _secs(hm)
            key = f"{day} {hm}"
            if weekday and at <= secs < at + 600 and key not in self._mc_done:
                self._mc_done.add(key)
                self.loop.create_task(self._morning_check(hm, send=True))
        if mono >= self._sc_next:
            self._sc_next = mono + 60
            self.loop.create_task(self._stop_check())

    async def _morning_check(self, why="now", send=False):
        be, items = self.be, []

        def add(ok, name, text):
            items.append({"ok": "ok" if ok is True else "warn" if ok is None else "bad", "name": name, "text": text})

        ib = getattr(be, "ib", None)
        conn = (getattr(be, "status", {}) or {}).get("conn")
        ib_ok = ib is not None and ib.isConnected()
        add(ib_ok and conn == "connected", "IB Gateway", ("connected" + (" - data farms OK" if conn == "connected" else
             " - data farm warning: " + str((be.status or {}).get("text", ""))[:80])) if ib_ok else "not connected")
        tz_ok = self.tz_ready()
        add(tz_ok and not self.live_blocked(), "TradeZero",
            f"{self.acc_type.lower() or '?'} account - keys OK" if tz_ok else (self.tz_status or {}).get("text", "not connected"))
        bp = _fnum(self.acc_info.get("buyingPower", self.acc_info.get("bp")), 0.0)
        base = self.size_base or _fnum(self.acc_info.get("equity"), 0.0)
        nxt = min(base * ACCOUNT_PCT / 100.0, MAX_POSITION_USD) if base else 0.0
        add((bp >= nxt) if tz_ok and nxt else None, "Buying power",
            f"${bp:,.0f} - next trade ${nxt:,.0f} ({ACCOUNT_PCT:g}% of ${base:,.0f})" if tz_ok else "unknown (TradeZero not connected)")
        add(bool(self.dc.on), "Discord", "webhook OK" if self.dc.on else "no webhook saved")
        try:
            import vault_feed as VF
            st = VF.status(DATA_DIR) or {}
            q = VF.summary(DATA_DIR) or {}
            last = (st.get("days") or [""])[-1] if st.get("days") else ""
            ok = st.get("state") != "error"
            add(ok, "Vault feed", (f"last run {st.get('ended', st.get('started', '?'))[:16]}" + (f" (day {last})" if last else "")
                                   if st else "no run yet") + (f" - {len(q)} day(s) queued" if q else "")
                + ("" if ok else f" - ERROR {str(st.get('error', ''))[:60]}"))
        except Exception as exc:
            add(None, "Vault feed", f"unknown ({exc.__class__.__name__})")
        if ib_ok:
            try:
                srv = await asyncio.wait_for(ib.reqCurrentTimeAsync(), 5)
                off = time.time() - srv.timestamp()
                add(abs(off) < 2, "PC clock", f"{off:+.1f} s vs the IB server")
            except Exception:
                add(None, "PC clock", "IB server time not answered")
        else:
            add(None, "PC clock", "not checked (IB Gateway not connected)")
        tdb = getattr(self, "tdb", None)
        if tdb is not None:
            sync = {"on": "cloud sync on", "off": "cloud sync off (no Turso keys)", "error": "cloud sync ERROR"}.get(tdb.sync_state, tdb.sync_state)
            add(tdb.sync_state != "error", "Trade database", f"saved locally - {sync}" + (f" - {tdb.pending()} waiting" if tdb.pending() else ""))
        else:
            add(False, "Trade database", "not open")
        fl = getattr(be, "floats", None)
        if fl is not None:
            left = fl.lookups_left()
            add(left is None or left > 3, "Float lookups", "no Alpha Vantage key - SEC shares outstanding only" if left is None
                else f"{left} of {fl.DAILY} left today")
        wd = getattr(self, "_wd_beat", None)
        age = time.monotonic() - wd if wd else None
        add(age is not None and age < 10, "Watchdog", f"main loop beat {age:.0f} s ago - PC kept awake" if age is not None else "not running")
        try:
            import shutil
            free = shutil.disk_usage(DATA_DIR).free / 1e9
            add(free >= 5, "Disk space", f"{free:,.0f} GB free")
        except Exception:
            add(None, "Disk space", "unknown")
        bad = [i for i in items if i["ok"] == "bad"]
        self.mcheck = {"at": self.now().strftime("%H:%M:%S"), "why": why, "ok": not bad, "items": items}
        if getattr(self, "tdb", None) is not None:
            try:
                import tradedb
                self.tdb.put("health", {"id": f"mc-{self.now():%Y%m%d-%H%M%S}", "day": str(self.now().date()),
                                        "t": int(time.time()), "kind": "morning", "ok": int(not bad), "data": tradedb.dumps(self.mcheck)})
            except Exception:
                log.exception("health save")
        if send:
            self._mcheck_discord()
        self._push(True)
        return self.mcheck

    def _mcheck_discord(self):
        mc = self.mcheck
        if not mc:
            return
        bad = [i for i in mc["items"] if i["ok"] == "bad"]
        warn = [i for i in mc["items"] if i["ok"] == "warn"]
        lines = [f"{'❌' if i['ok'] == 'bad' else '⚠️' if i['ok'] == 'warn' else '✅'} {i['name']}: {i['text']}" for i in mc["items"]]
        modes = " · ".join(f"{MODE_NAMES[k]} {str(MODES.get(k) or 'trading').replace('alert', 'alert only').title()}"
                           for k in ("long", "jr2", "jr"))
        title = "Morning check · all passed" if not bad else f"Morning check · {len(bad)} failed"
        self._notify(("✅ " if not bad else "🚨 ") + title, "\n".join(lines) + (f"\n\nStrategies: {modes}" if modes else ""),
                     "ok" if not bad and not warn else "warn" if not bad else "err", ping=bool(bad), critical=bool(bad),
                     tag=f"MORNING CHECK  ·  {mc['at']}", who="System")

    # ---------------- 3.15: the 16:05 daily summary + the auto shutdown ----------------
    def _equity_png(self, day, start_eq, rows):
        """The day's equity curve (PNG bytes): start equity + every closed trade at its exit time, dots green / red."""
        try:
            import io
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            pts = sorted(((r["tout"] or r["tin"] or "16:00"), r["net"]) for r in rows)
            xs, ys, eq = [4.0], [start_eq], start_eq
            dots = []
            for hm, net in pts:
                hh, mm = (int(x) for x in (hm + ":00")[:5].split(":"))
                eq += net
                xs.append(hh + mm / 60.0)
                ys.append(eq)
                dots.append((xs[-1], eq, net))
            xs.append(16.0)
            ys.append(eq)
            fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=110)
            fig.patch.set_facecolor("#1e1f22")
            ax.set_facecolor("#1e1f22")
            col = "#10b981" if eq >= start_eq else "#f43f5e"
            ax.step(xs, ys, where="post", color=col, linewidth=2.2)
            ax.fill_between(xs, ys, min(ys) - (max(ys) - min(ys) or 1) * 0.1, step="post", color=col, alpha=0.12)
            for x, y, n in dots:
                ax.plot([x], [y], "o", color="#10b981" if n > 0 else "#f43f5e", markersize=5)
            ax.set_xlim(4, 16)
            ax.set_xticks([4, 7, 10, 13, 16])
            ax.set_xticklabels(["04:00", "07:00", "10:00", "13:00", "16:00"])
            ax.tick_params(colors="#80848e", labelsize=8)
            for sp in ax.spines.values():
                sp.set_visible(False)
            ax.grid(axis="y", color="#2b2d31")
            ax.set_title(f"Equity · {day}", color="#b5bac1", fontsize=10, loc="left")
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _p: f"{v / 1000:.1f}k" if abs(v) >= 1000 else f"{v:.0f}"))
            buf = io.BytesIO()
            fig.tight_layout()
            fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
            plt.close(fig)
            return buf.getvalue()
        except Exception:
            log.exception("equity picture")
            return None

    def _summary_315(self):
        """16:05 Discord: net P&L after locates, win rate, equity and % change, per strategy, locates, best / worst trade,
        the missed signals with their would-have P&L, and the day's equity curve."""
        day = str(self.now().date())
        rows = [t for t in journal_trades() if t["d"] == day]
        try:
            _attach_locates(rows, day, day)
        except Exception:
            pass
        net = sum(r["net"] for r in rows)
        loc = sum(r["loc"] for r in rows)
        wins, losses = sum(1 for r in rows if r["net"] > 0), sum(1 for r in rows if r["net"] <= 0)
        eq = _fnum(self.acc_info.get("equity"), 0.0)
        sod = _fnum(self.acc_info.get("sodEquity"), 0.0) or (eq - (self.day_pnl or net) if eq else 0.0)
        names = {"long": "Premarket long", "jr2": "Jay-read 2", "jr": "Jay-read v1.2", "sq": "Max squeeze", "manual": "Manual"}
        per = {}
        for r in rows:
            p = per.setdefault(r["strat"], [0.0, 0])
            p[0] += r["net"]
            p[1] += 1
        best = max(rows, key=lambda r: r["net"]) if rows else None
        worst = min(rows, key=lambda r: r["net"]) if rows else None
        ms = self.missed.summary(day) if getattr(self, "missed", None) is not None else None
        f = [("Net P&L", _money(net), True),
             ("Win rate", f"{round(100 * wins / len(rows))}% ({wins} / {losses})" if rows else "-", True),
             ("Equity", f"{_money(eq)} ({(eq / sod - 1) * 100:+.1f}%)" if eq and sod else (_money(eq) if eq else "-"), True)]
        f += [(names.get(k, k), f"{_money(v[0])} · {v[1]} trade{'s' if v[1] != 1 else ''}", True) for k, v in per.items()]
        f += [("Locates", _money(-loc) if loc else "$0", True),
              ("Best", f"{best['sym']} {_money(best['net'])}" if best else "-", True),
              ("Worst", f"{worst['sym']} {_money(worst['net'])}" if worst else "-", True),
              ("Missed", f"{ms['n']} signal{'s' if ms['n'] != 1 else ''} ({_money(ms['pnl'])})" if ms else "-", True)]
        opens = self.open_positions()
        if opens:
            f.append(("STILL OPEN", ", ".join(f"{o['sym']} {o['side']} {o['qty']:,}" for o in opens), False))
        png = self._equity_png(day, sod or eq or 0.0, rows)
        title = f"📊 Daily summary · {self.now():%a %b %d}"
        text = "No closed trade today." if not rows else ""
        self._log(f"{title}: net {_money(net)}, {len(rows)} trades", "info")
        try:
            self.dc.send(title, text, "ok" if net >= 0 else "warn", fields=f,
                         image=[("equity.png", png)] if png else None, tag="DAILY SUMMARY", username=DISCORD_NAME_SYSTEM)
        except Exception:
            log.exception("daily summary")
        if getattr(self, "tdb", None) is not None:
            try:
                import tradedb
                self.tdb.put("daily", {"day": day, "data": tradedb.dumps({"net": net, "loc": loc, "wins": wins, "losses": losses,
                                                                         "equity": eq, "sod": sod, "per": per, "missed": ms}),
                                       "updated": self.now().strftime("%H:%M:%S")})
            except Exception:
                log.exception("daily save")

    def _shutdown_offer(self):
        """After the 16:05 summary: nothing open = the window counts down 5:00 and closes the app (Keep running stops it);
        a position or a working order open = no shutdown, Discord @everyone instead."""
        opens = self.open_positions()
        working = [o for o in self.orders_raw.values() if o.get("orderStatus") in OPEN_STATES]
        if opens or working:
            what = ", ".join(f"{o['sym']} {o['side']} {o['qty']:,}" for o in opens)
            what += (("; " if what else "") + f"{len(working)} working order{'s' if len(working) != 1 else ''}") if working else ""
            self._notify("⚠️ Market closed - the bot stays on", f"Not shutting down: {what}. Close them, then the app.", "warn",
                         ping=True, critical=True, tag="AUTO SHUTDOWN SKIPPED", who="System")
            return
        self.be.bridge.call("shutdownPrompt", {"secs": AUTO_SHUTDOWN_SEC, "summary": True, "flat": True})

    # ---------------- stop check (every minute) ----------------
    async def _stop_check(self):
        rows = []
        for bs in list(self.syms.values()):
            ent = bs.entry or {}
            filled = int(_fnum(ent.get("filled"), 0))
            if filled <= 0:
                self._sc_miss.pop(bs.sym, None)
                continue
            bot_px = _f(self._stop_px(bs))
            row = {"sym": bs.sym, "side": "short", "qty": filled, "bot": bot_px, "tz": None, "yours": False, "st": "ok", "text": "OK"}
            if bs.halt is not None:
                row.update(st="warn", text="halted - the halt rules decide at the reopen", tz=_f(ent.get("stop_live")))
            elif bs.stop_guard is not None:
                row.update(st="warn", text=f"no stop - being placed again ({bs.stop_guard.get('why', '')})")
            else:
                user = self._user_stop_in(bs)
                own = self.orders_raw.get(bs.stop_coid) if bs.stop_coid else None
                own_ok = own is not None and own.get("orderStatus") in OPEN_STATES
                o = user if (bs.stop_owner == "you" and user is not None) else own if own_ok else user
                if o is None:
                    n = self._sc_miss.get(bs.sym, 0) + 1
                    self._sc_miss[bs.sym] = n
                    if n >= 2:                               # missing twice in a row: the guard places it again + Discord
                        self._sc_miss.pop(bs.sym, None)
                        self._stop_lost(bs, "the stop check found no working stop at TradeZero", "")
                        self._guard_ping(bs, force=True)
                        row.update(st="warn", text=f"missing - re-placing at {_fp(bot_px)} ({self.now():%H:%M:%S})")
                    else:
                        row.update(st="warn", text="not in TradeZero's order list - checked again in 1 min")
                else:
                    self._sc_miss.pop(bs.sym, None)
                    side, _ = _oside(o)
                    q = int(_fnum(o.get("orderQuantity"), 0)) - int(_fnum(o.get("executed"), 0))
                    yours = o is user and not (own_ok and own is user)
                    row.update(tz=_f(_ostop(o)), yours=yours)
                    if side not in ("Cover", "Buy"):
                        row.update(st="bad", text=f"wrong side ({side}) - check it at TradeZero")
                    elif q < filled:
                        row.update(st="bad", text=f"covers {q:,} of {filled:,} sh" + (" - your stop is kept" if yours else ""))
                        key = (bs.sym, q, filled)
                        if getattr(self, "_sc_warned", None) != key:
                            self._sc_warned = key
                            self._notify(f"⚠️ {bs.sym}: the stop covers {q:,} of {filled:,} sh", "Stop check: the working stop at "
                                         "TradeZero is smaller than the short." + (" It is your stop - not changed by the bot."
                                                                                   if yours else ""), "warn", bs=bs, ping=True)
                    else:
                        row["text"] = "OK" + (" - manual stop kept" if yours else "")
            rows.append(row)
        for lt in (self.longbot.open_longs() if getattr(self, "longbot", None) is not None else []):
            p = lt.day.pos
            rows.append({"sym": lt.sym, "side": "long", "qty": int(p.shares), "bot": _f(p.stop), "tz": None, "yours": False,
                         "st": "ok", "text": "bot-managed (sells on the price - no stop at TradeZero)"})
        self.stopchk = rows
        self.stopchk_at = self.now().strftime("%H:%M:%S")
