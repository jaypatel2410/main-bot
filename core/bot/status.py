# -*- coding: utf-8 -*-
"""Kestrel - Bot: logging, Discord messages, end-of-day summary, heartbeat, goodbye.
Part of the Bot class (core/bot/bot_core.py): main.py runs this file in its own namespace. Code moved here unchanged."""

class _BotStatus:

    def _log(self, text, kind="info"):
        stamp = self.now().strftime("%H:%M:%S")
        self.logs.append({"t": stamp, "k": kind, "x": text})
        (log.warning if kind in ("warn", "err") else log.info)("BOT %s", text)

    def _clean(self, text):
        """Text without the TradeZero account id (error texts carry it in the URL)."""
        text = str(text or "")
        acc = str(getattr(self, "acc", "") or "")
        return text.replace(acc, "(account)") if len(acc) >= 4 else text

    def _notify(self, title, text="", kind="info", bs=None, fields=None, chart=False, ping=False, critical=False,
                marks=None, levels=None, log_it=True, stage=None, tag=None, who=None):
        """App log + Discord. chart=True (or a stage) attaches the 1-minute candle chart (and the "stock flow" picture
        when DISCORD_FLOW_IMAGES) - throttled per symbol unless critical. stage = "closed" draws the finished trade from
        marks. 3.10: tag = the small line above the title (None = picked from the title); who = "Shorts" / "System"
        (None = Shorts for a symbol message, else System)."""
        title, text = self._clean(title), self._clean(text)    # 3.8.0: no account id in Discord / the log
        fields = [(n, self._clean(v), inl) for n, v, inl in (fields or [])] or None
        if who is None:
            m0 = re.match(r"^[^A-Za-z0-9]*([A-Z][A-Z0-9.]{0,7})\b", str(title))
            who = "Shorts" if (bs is not None or (m0 and m0.group(1) in self.syms)) else "System"
        uname = {"Shorts": DISCORD_NAME_SHORTS, "Longs": DISCORD_NAME_LONGS}.get(who, DISCORD_NAME_SYSTEM)
        if log_it:
            self._log(f"{title}" + (f" - {text}" if text and len(text) < 160 else ""),
                      {"ok": "info", "dim": "info", "short": "trade", "cover": "trade"}.get(kind, kind))
        if not self.dc.on:
            return
        flow = None
        if (chart or stage) and DISCORD_FLOW_IMAGES and bs is not None and bs.st is not None:
            mono = time.monotonic()
            if critical or mono - bs.last_flow >= DISCORD_IMAGE_MIN_GAP_SEC:
                allr = chart_rows_today(bs.st)
                if len(allr) >= 3:
                    bs.last_flow = mono
                    try:
                        flow = (allr, self._flow_plan(bs, stage, title, marks, text))
                    except Exception:
                        log.exception("flow plan")
        rows, prior, hod = None, None, None
        if chart and DISCORD_CHART_IMAGES and bs is not None and bs.st is not None:
            mono = time.monotonic()
            if critical or mono - bs.last_img >= DISCORD_IMAGE_MIN_GAP_SEC:
                bs.last_img = mono
                allr = chart_rows_today(bs.st)
                if allr:
                    # the last DISCORD_CHART_MINUTES, stretched back to show the entry / marked candles of the trade
                    t0 = allr[-1][0] - DISCORD_CHART_MINUTES * 60
                    ts = [m["t"] for m in (marks or []) if m.get("t")]
                    if bs.entry and bs.entry.get("t"):
                        ts.append(bs.entry["t"])
                    if ts:
                        t0 = min(t0, min(ts) - 20 * 60)
                    rows = [r for r in allr if r[0] >= t0] or allr
                    hod = (bs.eng or {}).get("hod") or max(r[2] for r in allr)
                prior = prior_for(bs.st, bs.st.tc[-1] // 86400) if bs.st.tc else None
                levels = levels if levels is not None else self._levels(bs)
        sym = bs.sym if bs is not None else ""

        def job():
            imgs = []
            if flow is not None:
                try:
                    imgs.append(("flow.png", render_flow_png(sym, *flow)))
                except Exception:
                    log.exception("flow image")
            if rows:
                try:
                    imgs.append(("chart.png", render_chart_png(sym, rows, title, levels, marks, prior, hod)))
                except Exception:
                    log.exception("chart image")
            self.dc.send(title, text, kind, fields, [(n, b) for n, b in imgs if b] or None, ping, username=uname, tag=tag)
        self.msg_pool.submit(job)

    def reload_discord(self):
        cfg = discord_load()
        self.dc.configure(cfg["url"], cfg["mention"])

    def _jr_status_text(self, bs):
        rd = bs.jr.reader if bs.jr is not None else None
        if bs.hunt is not None:
            return self._hunt_text(bs), "work"
        if rd is None or not len(rd.o):
            return "Jay-read: waiting for candles", "dim"
        if jr_finished(bs.jr):
            stopped = any(p.done and p._stop_rh is not None for p in getattr(bs.jr, "parts", [bs.jr]))
            return f"Shorts: done for the day ({'stopped out' if stopped else 'max trades'})", "done"
        txt, kind = self._jr_read_text(bs, rd)
        return txt, kind

    async def _eod(self):
        self._notify(f"{EOD_COVER_TIME} - covering every bot short", "", "warn")
        for bs in list(self.syms.values()):
            if bs.phase in ("working", "short", "locating", "manual"):
                await self._flatten_one(bs, "EOD")

    def _eod_alert(self, title, only_open=False):
        """No automatic cover: urgent message with every open short, its numbers and its chart."""
        opens = [b for b in self.syms.values() if b.phase in ("short", "covering", "manual") and b.entry
                 and self._tz_short(b)]
        if not opens:
            if not only_open:
                self._notify("No open bot shorts", "", "dim", tag=f"CLOSE CHECK  ·  {EOD_ALERT_TIME}", who="Shorts")
            return
        secs = self._wall() % 86400
        auto = [b for b in opens if (b.entry or {}).get("jr") and JR_EOD_COVER_TIME and b.phase in ("short", "covering")
                and secs < _secs(JR_EOD_COVER_TIME)]
        for bs in auto:                                  # 3.7: Jay-read shorts the bot covers itself at JR_EOD_COVER_TIME
            ent = bs.entry
            last = bs.last_px or ent["avg"]
            self._notify(f"{bs.sym} - the bot covers at {JR_EOD_COVER_TIME}",
                         f"Short {ent['filled']:,} @ {_fp(ent['avg'])}  ·  last {_fp(last)}  ·  "
                         f"{_money((ent['avg'] - last) * ent['filled'] - _fnum(ent.get('locate_usd')))} now (net of the locate).",
                         "warn", bs=bs, chart=True, critical=True, tag=f"CLOSING  ·  {JR_EOD_COVER_TIME}")
        opens = [b for b in opens if b not in auto]
        if not opens:
            return
        self.be.bridge.call("alert", {"kind": "short", "t": self._wall() // 60 * 60, "title": "CLOSE YOUR SHORTS",
                                      "text": ", ".join(f"{b.sym} {b.entry['filled']} sh" for b in opens) + " - stops expire at 16:00"})
        for bs in opens:
            ent = bs.entry
            last = bs.last_px or ent["avg"]
            qty = ent["filled"]
            stop = ent.get("stop_live") or ent.get("stop") or 0
            unreal = (ent["avg"] - last) * qty - _fnum(ent.get("locate_usd"))
            risk = (_fnum(ent.get("stop")) - ent["avg"]) * qty
            r = unreal / risk if risk > 0 else 0.0
            mins = (self._wall() - ent.get("t", self._wall())) // 60
            f = [("Setup", SETUP_NAME.get(ent.get("setup"), ent.get("setup", "?")), True), ("Shares", f"{qty:,}", True),
                 ("Entry", _fp(ent["avg"]), True), ("Last", _fp(last), True),
                 ("Stop", "NONE - you manage this short" if bs.phase == "manual" else
                  f"{_fp(stop)} ({'yours' if bs.stop_owner == 'you' else 'bot'})", True),
                 ("Unrealized (net of locate)", f"{_money(unreal)} = {r:+.2f}R", True), ("In trade", f"{mins} min", True)]
            self._notify(f"{bs.sym} - short still open: close it", "The bot does NOT cover at the close. Close it at "
                         "TradeZero (day stop orders expire at 16:00).", "err", bs=bs, fields=f,
                         chart=True, critical=True, ping=True, tag=str(title).upper())

    def _summary(self):
        trades = [(b.sym, t) for b in self.syms.values() for t in b.trades]
        loc = sum(b.locate_cost for b in self.syms.values())
        lines = [f"`{s:<6}` {SETUP_NAME.get(t['setup'], t['setup'] or '?'):<11} {t['qty']:>6,} sh  {t['reason']:<14} "
                 f"{_money(t['net']):>11}  {t['R']:+.2f}R" for s, t in trades]
        net = sum(t["net"] for _, t in trades)
        opens = [b for b in self.syms.values() if b.phase in ("short", "covering", "manual") and b.entry]
        for b in opens:
            ent = b.entry
            last = b.last_px or ent["avg"]
            unreal = (ent["avg"] - last) * ent["filled"] - _fnum(ent.get("locate_usd"))
            lines.append(f"`{b.sym:<6}` {SETUP_NAME.get(ent.get('setup'), '?'):<11} {ent['filled']:>6,} sh  STILL OPEN     "
                         f"{_money(unreal):>11}  entry {_fp(ent['avg'])} last {_fp(last)}")
        f = [("Closed trades", str(len(trades)), True), ("Net P&L (closed)", _money(net), True),
             ("Total R", f"{sum(t['R'] for _, t in trades):+.2f}R", True), ("Locates paid", _money(loc), True),
             ("Day P&L (TradeZero)", _money(self.day_pnl), True),
             ("Still open", ", ".join(f"{b.sym} {b.entry['filled']:,} sh" for b in opens) or "none", True)]
        if self.jr_alert_trades:                         # 3.7 ALERT_ONLY: what the Jay-read short would have done
            at = self.jr_alert_trades
            lines += ["", f"**Alert-only trades (no orders): {len(at)}, would be about {_money(sum(x['net'] for x in at))} "
                          f"after a {JR.LOCATE_FEE_PCT:g}% locate**"]
            lines += [f"`{x['sym']:<6}` {x['name']:<26} {x['qty']:>6,} sh  {x['reason']:<5} {_money(x['net']):>11}  {x['R']:+.2f}R"
                      for x in at]
        # 3.10: DAY CLOSED - shorts + longs, the trades, what was not traded, equity
        lb = self.longbot
        lrows = list(getattr(lb, "closed_rows", []) or []) if lb is not None else []
        lnet = sum(r["pnl"] for r in lrows)
        for r in lrows:
            lines.append(f"`{r['sym']:<6}` {'Long':<11} {r['sh']:>6,} sh  {str(r['res'])[:14]:<14} {_money(r['pnl']):>11}  "
                         f"{r['r']:+.2f}R")
        n_all = len(trades) + len(lrows)
        won = sum(1 for _, t in trades if t["net"] > 0) + sum(1 for r in lrows if r["pnl"] > 0)
        f = [("Shorts", f"{len(trades)} trade{'s' if len(trades) != 1 else ''}  ·  "
                        f"{sum(1 for _, t in trades if t['net'] > 0)} won\n{_money(net)}", True),
             ("Longs", f"{len(lrows)} trade{'s' if len(lrows) != 1 else ''}  ·  {sum(1 for r in lrows if r['pnl'] > 0)} won"
                       f"\n{_money(lnet)}", True),
             ("Locates paid", _money(loc), True),
             ("Day P&L (TradeZero)", _money(self.day_pnl), True),
             ("Equity", _money(_fnum(self.acc_info.get("equity"))) if self.acc else "-", True),
             ("Still open", ", ".join(f"{b.sym} {b.entry['filled']:,} sh" for b in opens) or "none", True)]
        self._notify(f"Day {_pm(self.day_pnl if self.day_pnl is not None else net + lnet)}  ·  {n_all} "
                     f"trade{'s' if n_all != 1 else ''}  ·  {won} won",
                     "\n".join(lines) or "No trades today.", "warn" if opens else "ok", fields=f, ping=bool(opens),
                     tag="DAY CLOSED" + (f"  ·  {self.acc_type.upper()}" if self.acc_type else "")
                     + ("  ·  SHORTS STILL OPEN" if opens else ""), who="System")

    def _heartbeat(self):
        """STATUS every DISCORD_HEARTBEAT_MIN - only what is open, what is watched and the connections (2026-11-06: no
        strategy modes / what is off - a mode change has its own message)."""
        hm = f"{self.now():%H:%M}"
        opens = self._open_lines(brief=True)
        title = f"{len(opens)} open" if opens else "Nothing open"
        kind = "dim"
        ib = self.be.ib
        conns = (f"IB Gateway {'OK' if ib is not None and ib.isConnected() else 'DOWN'}  ·  "
                 f"{('TradeZero ' + self.acc_type + ' OK') if self.tz_ready() else self.tz_status.get('text', 'TradeZero -')}"
                 f"  ·  Discord OK")
        watch = "\n".join(f"{b.sym:<6} {_fp(b.last_px):>8}  {b.status}"[:150] for b in self.syms.values()) or "nothing"
        f = [("Open", "\n".join(opens) if opens else "nothing", False),
             ("Watching", f"```{watch[:950]}```", False),
             ("Connections", conns, False)]
        self._notify(title, "", kind, fields=f, tag=f"STATUS {hm}  ·  EVERY {DISCORD_HEARTBEAT_MIN} MIN", who="System")

    def goodbye(self):
        """App closing (any thread): last Discord message, sent right away."""
        try:
            opens = [b for b in self.syms.values() if b.phase in ("short", "covering", "working", "manual") and b.entry]
            txt = ("Open shorts are NOT managed while the app is closed (their stop orders stay at TradeZero): " +
                   ", ".join(f"{b.sym} {b.entry.get('filled', 0)} sh" for b in opens)) if opens else "No open bot shorts."
            lt = self.longbot.goodbye_text() if self.longbot is not None else ""
            if lt:
                txt += "\n" + lt
                opens = opens or [lt]
            if self.dc.on:
                try:                                       # 3.12.1: every stop sends today's vault feed list
                    import vault_feed as VF
                    day = self.now().date()
                    self.dc.send_now(f"Vault feed list - {day}", VF.discord_text(DATA_DIR, day), "dim", quick=True,
                                     tag="VAULT FEED  ·  BOT STOPPED", username=DISCORD_NAME_SYSTEM)
                except Exception:
                    log.exception("vault feed list")
                self.dc.send_now("App closed - positions still open" if opens else "App closed - nothing open",
                                 txt if opens else "", "err" if opens else "dim", quick=True, tag="BOT STOPPED",
                                 username=DISCORD_NAME_SYSTEM)
        except Exception:
            log.exception("goodbye")

    # ---------------- status for the page ----------------
    def _status(self, bs):
        e = bs.eng or {}
        ent = bs.entry
        if bs.phase == "locating":
            bs.status, bs.kind = (self._hunt_text(bs) if bs.hunt is not None else "Getting the locate..."), "work"
        elif bs.phase == "working":
            f = f" - {ent['filled']}/{ent['qty']} filled" if ent["filled"] else ""
            bs.status, bs.kind = f"{SETUP_NAME.get(ent['setup'], '')} short {_fp(ent['limit'])} x{ent['qty']} working{f}", "work"
        elif bs.phase == "short":
            r = ""
            stop = ent.get("stop_live") or ent.get("stop")
            if bs.last_px and ent.get("stop") and ent["stop"] > ent["avg"] > 0:
                rr = ((ent["avg"] - bs.last_px) * ent["filled"] - _fnum(ent.get("locate_usd"))) / ((ent["stop"] - ent["avg"]) * ent["filled"])
                r = f" - {rr:+.2f}R"
            own = " (yours)" if bs.stop_owner == "you" else ""
            ns = " - NO STOP" if not bs.stop_coid else ""
            if bs.stop_guard is not None:                # 3.12
                ns = " - STOP NOT AT TRADEZERO: " + ("goes in at the reopen" if bs.halt is not None else
                                                      f"placing it again ({bs.stop_guard['tries']} tries)")
            hl = self._halt_text(bs)
            bs.status, bs.kind = f"{hl}SHORT {ent['filled']} @ {_fp(ent['avg'])} - stop {_fp(stop)}{own}{r}{ns}", "short"
        elif bs.phase == "covering":
            cv = bs.cover or {}
            left = int(cv.get("qty") or 0) - int(cv.get("got") or 0)
            bs.status = self._halt_text(bs) + (f"Covering {left:,} sh - waits for the reopen" if bs.halt is not None else
                                               f"Covering {left:,} sh (try {cv.get('tries', 0)})"
                                               + (f" - {cv['text']}" if cv.get("text") else ""))
            bs.kind = "work"
        elif bs.phase == "manual":
            r = ""
            if bs.last_px and ent.get("avg"):
                r = f" - {(ent['avg'] - bs.last_px) * ent['filled'] - _fnum(ent.get('locate_usd')):+,.0f}$"
            bs.status, bs.kind = f"YOUR SHORT {ent['filled']} @ {_fp(ent['avg'])} - no bot stop, you manage it{r}", "short"
        elif bs.load_err:
            bs.status, bs.kind = bs.load_err, "err"
        elif bs.st is None:
            bs.status, bs.kind = "Loading candles..." if self.be.ib is not None and self.be.ib.isConnected() else "Waiting for IB Gateway...", "dim"
        elif not e:
            bs.status, bs.kind = "Starting...", "dim"
        else:                                            # the Jay-read read
            done = f"{len(bs.trades)} trade{'s' if len(bs.trades) != 1 else ''} {sum(t['R'] for t in bs.trades):+.2f}R - " if bs.trades else ""
            if not jr_ready():
                bs.status, bs.kind = done + "Jay-read short not loaded - no shorts", "err"
            elif bs.jr_virtual is not None:
                vt = bs.jr_virtual
                bs.status = done + (f"ALERT trade: would be short {vt['qty']:,} @ {_fp(vt['entry'])}, stop {_fp(vt['stop'])}"
                                    + (" (lock)" if vt["locked"] else ""))
                bs.kind = "short"
            else:
                txt, kind = self._jr_status_text(bs)
                live = bs.jr_ctx and mode("jr") == "trading"
                why = (self.can_open() if live and bs.hunt is None else "") or ""
                alert = bs.jr_ctx and mode("jr") == "alert"
                off = bs.jr_ctx and mode("jr") == "off"
                bs.status = (done + txt + (" (alert only)" if alert else " (strategy off)" if off else "")
                             + (f" - {why}" if why else ""))
                bs.kind = kind
