# -*- coding: utf-8 -*-
"""LH Short Bot - JsApi: what the app window calls (screens, journal, favorites, alerts, backtest).
Part of main.py: main.py runs this file in its OWN namespace (same names, same settings), so the code works exactly
as when it was one file. Do not run it on its own - start main.py."""
class JsApi:
    def __init__(self, backend, settings):
        self._backend = backend
        self._settings = settings
        # 3.10.1: private names (leading "_"): pywebview exposes every PUBLIC attribute of the js_api object to the page
        # and walked into the window's native WinForms / WebView2 objects (3.9.0 / 3.10.0: "Error while processing
        # window.native..." in the log, the window "not responding" for 5-10 s at start-up)
        self._window = None
        self._exit_ok = {"v": False}                      # 3.9.0: the close question was answered

    def get_init(self):
        self._backend.request_resend()
        return {
            "settings": {k: self._settings.get(k) for k in Settings.KEYS + tuple(Settings.SIZES) + ("tf", "otab", "hotkeys")},
            "recent": self._settings.get("recent", []),
            "status": self._backend.status,
            "info": {"app": f"{APP_NAME} {APP_VERSION}", "strategy": strategy_label(),
                     "ib": f"{IB_HOST}:{IB_PORT}", "history": HISTORY_DURATION, "histMax": HISTORY_MAX_1M_BARS,
                     "minUp": STRAT.MIN_GAP_PCT, "minGap": STRAT.MIN_GAP_PCT, "dip": STRAT.MIN_DIP_PCT,
                     "zoneFar": STRAT.ZONE_FAR_PCT, "zoneNear": STRAT.ZONE_NEAR_PCT, "stopTop": STRAT.STOP_ABOVE_TOP_PCT,
                     "vwapMin": STRAT.MIN_ZONE_ABOVE_VWAP_PCT, "entryStart": STRAT.ENTRY_START,
                     "lastEntry": STRAT.LAST_ENTRY_TIME, "eod": STRAT.EOD_COVER_TIME,
                     "fee": float(getattr(STRAT, "LOCATE_FEE_PCT", 0.0)), "minVol": float(getattr(STRAT, "MIN_DAY_VOLUME", 0)),
                     "bot": {"size": f"{ACCOUNT_PCT:g}% of equity", "loc": MAX_LOCATE_PCT,
                             "maxTrades": MAX_BOT_TRADES_PER_DAY, "live": bool(ALLOW_LIVE_TRADING)},
                     "short": "jay_read" if jr_mode() else "v16", "jr": jr_info(), "btref": BT_REF,
                     "scanUp": SHORT_SCAN_MIN_UP_PCT, "scanOn": bool(SHORT_SCANNER),
                     "vac": {"on": bool(getattr(STRAT, "VACUUM_ENABLED", False)),
                             "stretch": getattr(STRAT, "VAC_STRETCH_PCT", 15.0), "pull": getattr(STRAT, "VAC_PULLBACK_PCT", 5.0),
                             "stop": getattr(STRAT, "VAC_STOP_ABOVE_PEAK_PCT", 3.0),
                             "last": getattr(STRAT, "VAC_LAST_ENTRY_TIME", "15:30")}},
        }

    def load_symbol(self, sym):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        if not sym:
            return {"ok": False}
        self._settings.add_recent(sym)
        self._backend.request_symbol(sym)
        return {"ok": True, "recent": self._settings.get("recent", [])}

    def save_settings(self, data):
        if not isinstance(data, dict):
            return False
        for k in Settings.KEYS:
            if k in data:
                self._settings.set(k, bool(data[k]))
        if str(data.get("tf", "")) in Settings.TIMEFRAMES:
            self._settings.set("tf", str(data["tf"]))
        if str(data.get("otab", "")) in ("pos", "orders", "long", "loc", "alr"):     # 3.10: the orders-panel tab
            self._settings.set("otab", str(data["otab"]))
        for k, (lo, hi) in Settings.SIZES.items():
            if k in data:
                try:
                    self._settings.set(k, round(min(hi, max(lo, float(data[k]))), 4))
                except (TypeError, ValueError):
                    pass
        return True

    def reconnect(self):
        self._backend.request_reconnect()
        return True

    # ---- bot ----
    def _bot(self):
        return self._backend.bot

    def bot_add(self, sym):
        b = self._bot()
        if b is not None:
            b.cmd(b.add, sym)
        return True

    def bot_remove(self, sym):
        b = self._bot()
        if b is not None:
            b.cmd(b.remove, str(sym or "").upper())
        return True

    def bot_auto(self, on):
        b = self._bot()
        if b is not None:
            b.cmd(b.set_auto, bool(on))
        return True

    def set_mode(self, key, value):
        """3.10: menu -> Trading mode -> Trading / Alert only / Off."""
        b = self._bot()
        key, value = str(key or ""), str(value or "")
        if key not in MODE_KEYS or value not in MODE_VALUES:
            return {"ok": False, "error": "unknown mode"}
        if b is None:                                    # no bot yet: just save it
            saved = dict(self._backend.settings.get("modes", {}) or {})
            saved[key] = value
            self._backend.settings.set("modes", saved)
            set_modes(saved)
            return {"ok": True}
        b.cmd(b.set_mode, key, value)
        return {"ok": True}

    def bot_flatten(self):
        b = self._bot()
        if b is not None:
            b.cmd(b.flatten)
        return True

    def bot_cover(self, sym):
        b = self._bot()
        if b is not None:
            b.cmd(b.cover_one, str(sym or "").upper())
        return True

    def bot_set_stop(self, sym, price):
        try:
            price = float(price)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Type a price"}
        b = self._bot()
        if b is None:
            return {"ok": False, "error": "The bot is not running"}
        bs = b.syms.get(str(sym or "").upper())
        if bs is None or bs.phase not in ("short", "manual") or not bs.entry:
            return {"ok": False, "error": "No open short on this symbol"}
        last = bs.last_px or 0.0
        if price <= 0 or (last and price <= last):
            return {"ok": False, "error": f"A buy stop must be above the last price ({last:g})"}
        b.cmd(b.set_stop, bs.sym, price)
        return {"ok": True}

    # ---- 3.9.0: the locate window ----
    def loc_quote(self, sym, qty):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        try:
            qty = int(float(str(qty).replace(",", "")))
        except (TypeError, ValueError):
            qty = 0
        if not sym:
            return {"ok": False, "error": "Type a symbol"}
        if qty < 1:
            return {"ok": False, "error": "Type the number of shares"}
        b = self._bot()
        if b is None or not b.tz_ready():
            return {"ok": False, "error": "TradeZero is not connected"}
        if b.loc_busy:
            return {"ok": False, "error": "A locate request is running - wait for its answer"}
        b.cmd(b.loc_quote, sym, qty)
        return {"ok": True}

    def loc_accept(self, oid):
        b = self._bot()
        if b is None or not b.tz_ready():
            return {"ok": False, "error": "TradeZero is not connected"}
        b.cmd(b.loc_accept, str(oid or ""))
        return {"ok": True}

    def loc_cancel(self):
        b = self._bot()
        if b is not None:
            b.cmd(b.loc_cancel)
        return {"ok": True}

    def loc_refresh(self):
        b = self._bot()
        if b is not None:
            b.cmd(b.loc_refresh)
        return {"ok": True}

    # ---- 3.9.0: closing the app with a position open ----
    def close_state(self):
        b = self._bot()
        try:
            return {"open": b.open_positions() if b is not None else []}
        except Exception:
            return {"open": []}

    def close_choice(self, choice):
        """yes = close every position at market (the page waits, then calls 'exit'); no = keep them, close the app;
        exit = close the app now; cancel = keep the app open."""
        b = self._bot()
        choice = str(choice or "")
        if choice == "yes" and b is not None:
            b.cmd(b.close_for_exit)
            return {"ok": True}
        if choice in ("no", "exit"):
            if choice == "no" and b is not None:
                try:
                    b.closed_with_positions()
                except Exception:
                    log.exception("close message")
            self._exit_ok["v"] = True
            threading.Thread(target=self._destroy, daemon=True).start()
        return {"ok": True}

    def _destroy(self):
        time.sleep(1.0)                                  # the Discord message above gets queued first
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:
            log.exception("window destroy")

    def long_on(self, on):
        """Older page call: ON / OFF = the premarket long's Trading mode Trading / Off (3.10)."""
        b = self._bot()
        lb = b.longbot if b is not None else None
        if lb is None:
            return {"ok": False, "error": "The premarket long is not running - is lh_long_premarket.py next to the app?"}
        return self.set_mode("long", "trading" if on else "off")

    def long_sell(self, sym):
        b = self._bot()
        lb = b.longbot if b is not None else None
        if lb is None:
            return {"ok": False, "error": "The premarket long is not running"}
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        if not lb.holds(sym):
            return {"ok": False, "error": f"No open long on {sym}"}
        b.cmd(lb.sell_now, sym)
        return {"ok": True}

    def order_cancel(self, coid):
        b = self._bot()
        if b is None or not b.tz_ready():
            return {"ok": False, "error": "TradeZero is not connected"}
        coid = str(coid or "")
        if coid not in b.orders_raw:
            return {"ok": False, "error": "That order is not in TradeZero's list any more"}
        b.cmd(b.order_cancel, coid)
        return {"ok": True}

    def order_modify(self, coid, price):
        try:
            price = float(price)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Type a price"}
        b = self._bot()
        if b is None or not b.tz_ready():
            return {"ok": False, "error": "TradeZero is not connected"}
        o = b.orders_raw.get(str(coid or ""))
        if o is None:
            return {"ok": False, "error": "That order is not in TradeZero's list any more"}
        why = b._check_edit(o, _tick_px(price) if price > 0 else price)
        if not why and b._role(o)[0] == "bot":
            why = "the bot no longer manages this order - cancel it instead"
        if why:
            return {"ok": False, "error": why}
        b.cmd(b.order_modify, str(coid), price)
        return {"ok": True, "price": _tick_px(price)}

    def discord_keys(self):
        cfg = discord_load()
        url = cfg.get("url", "")
        return {"has": bool(url), "ok": discord_url_ok(url), "tail": url[-6:] if url else "", "mention": cfg.get("mention", ""),
                "file": env_path()}

    def discord_save(self, url, mention):
        url = str(url or "").strip()
        cur = discord_load()
        if not url:
            url = cur.get("url", "")                    # empty box = keep the saved webhook
        if url and not discord_url_ok(url):
            return {"ok": False, "error": "That is not a Discord webhook URL (https://discord.com/api/webhooks/...)"}
        try:
            path = discord_save(url, str(mention or "").strip())
        except Exception as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
        b = self._bot()
        if b is not None:
            b.reload_discord()
        return {"ok": True, "file": path}

    def discord_test(self, url, mention):
        r = self.discord_save(url, mention)
        if not r.get("ok"):
            return r
        b = self._bot()
        dc = b.dc if b is not None else None
        if dc is None or not dc.on:
            return {"ok": False, "error": "No Discord webhook saved"}
        ok, msg = dc.send_now("Discord is connected",
                              "Trade alerts, locates, stops, connection problems and the closing alerts come here.", "ok",
                              quick=True, tag="TEST MESSAGE", username=DISCORD_NAME_SYSTEM)
        return {"ok": ok, "error": "" if ok else f"Discord said: {msg}"}

    # ---- 3.14: Turso (the cloud database): status line + the credentials in Settings > Keys and Discord ----
    def turso_status(self):
        try:
            import turso
            return {"ok": True, **turso.status()}
        except Exception as exc:
            return {"ok": False, "state": "error", "error": str(exc)}

    def turso_keys(self):
        url = env_get("TURSO_DATABASE_URL", "")
        return {"url": url, "hasToken": bool(env_get("TURSO_AUTH_TOKEN", "")), "file": env_path()}

    def turso_save(self, url, token):
        url = str(url or "").strip()
        token = str(token or "").strip()
        if url and not url.startswith(("libsql://", "https://", "file:")):
            return {"ok": False, "error": "The URL starts with libsql:// (Turso dashboard -> your database)"}
        upd = {"TURSO_DATABASE_URL": url}
        if token:                                        # empty box = keep the saved token
            upd["TURSO_AUTH_TOKEN"] = token
        try:
            path = env_write(upd)
        except Exception as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
        import threading
        import turso
        turso.reset()
        os.environ.pop("TURSO_DATABASE_URL", None)
        os.environ.pop("TURSO_AUTH_TOKEN", None)

        def go():                                        # connect, then upload / merge the settings (off the window thread)
            if turso.cloud() is not None:
                self._settings._cloud_load()
        threading.Thread(target=go, daemon=True, name="turso-connect").start()
        return {"ok": True, "file": path}

    def tz_keys(self):
        cfg = tz_load_keys()
        kid = cfg.get("api_key_id", "")
        return {"id": kid, "hasSecret": bool(cfg.get("api_secret")), "acc": cfg.get("account_id", ""),
                "file": env_path()}

    def tz_save(self, key_id, secret, account_id):
        try:
            path = tz_save_keys(str(key_id or ""), str(secret or ""), str(account_id or ""))
        except Exception as exc:
            return {"ok": False, "error": f"Could not save: {exc}"}
        b = self._bot()
        if b is not None:
            b.cmd(b.reconnect_tz)
        return {"ok": True, "file": path}

    def more_history(self, sym, kind, oldest):
        """3.10: the page scrolled past its oldest candle - older candles for the open chart only."""
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        kind = "D" if str(kind) == "D" else "1m"
        try:
            res = self._backend.fetch_more(sym, kind, float(oldest))
            rows = res.get("rows", []) if isinstance(res, dict) else res
            return {"ok": True, "sym": sym, "kind": kind, "rows": rows, "done": not rows,
                    "src": res.get("src", "") if isinstance(res, dict) else ""}
        except Exception as exc:
            log.warning("older history %s: %r", sym, exc)
            return {"ok": False, "sym": sym, "kind": kind, "error": str(exc) or exc.__class__.__name__}

    # ---- 3.11: price alerts, screens, journal, hotkeys ----
    def alert_add(self, sym, price, last=None, direction=None):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        try:
            price = float(price)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Type a price"}
        if not sym or not price > 0:
            return {"ok": False, "error": "Type a symbol and a price"}
        try:
            last = float(last) if last not in (None, "") else self._backend.last_price(sym)
        except (TypeError, ValueError):
            last = self._backend.last_price(sym)
        a = self._backend.alerts.add(sym, price, last, direction)
        b = self._bot()
        if b is not None:
            b.loop.call_soon_threadsafe(b._push, True)
        return {"ok": True, "alert": a, "watched": bool(self._backend.last_price(sym))}

    # ---- 3.13: Backtest tab (lh_backtest.py; the run itself is a separate process - trading is never slowed) ----
    def _btm(self):
        import importlib
        if _base_dir() not in sys.path:
            sys.path.insert(0, _base_dir())
        return importlib.import_module("lh_backtest")

    def _bt_job(self):
        j = getattr(self, "_btj", None)
        if j and j["proc"] is not None and not j["proc"].is_alive() and j.get("state") == "running":
            j["state"] = "ended"
        return j

    def colors_get(self):
        return {"ok": True, "colors": self._settings.get("colors") or None}

    def colors_set(self, colors=None):
        self._settings.set("colors", colors if isinstance(colors, dict) else None)
        return {"ok": True}

    def vf_status(self):
        """3.12.1: the daily vault feed - queued days and the last run."""
        try:
            import vault_feed as VF
            return {"ok": True, "queue": VF.summary(DATA_DIR), "last": VF.status(DATA_DIR)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def bt_list(self):
        try:
            B = self._btm()
            st = B.settings()
            j = self._bt_job()
            return {"ok": True, "strats": B.strategies(), "vault": st.get("vault", ""), "vinfo": B.vault_info(st.get("vault", "")),
                    "last": st.get("last_cfg") or B.DEFAULT_CFG, "dir": B.BT_DIR,
                    "running": {"k": j["k"], "rid": j["rid"]} if j and j["proc"] is not None and j["proc"].is_alive() else None}
        except Exception as exc:
            log.exception("bt_list")
            return {"ok": False, "error": str(exc)}

    def bt_vault(self, path):
        try:
            B = self._btm()
            path = str(path or "").strip().strip('"')
            info = B.vault_info(path)
            if not info.get("ok"):
                return {"ok": False, "error": info.get("error", "vault not found")}
            B.save_settings(vault=os.path.abspath(path))
            return {"ok": True, "vinfo": info}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def bt_cards(self):
        """3.14: the Backtest page: every strategy as a card (its one run, the new vault days waiting for it)."""
        try:
            B = self._btm()
            st = B.settings()
            j = self._bt_job()
            favs = [f.get("sym") for f in (self._settings.get("favorites", []) or []) if isinstance(f, dict)]
            return {"ok": True, "strats": B.cards(favs), "vault": st.get("vault", ""), "vinfo": B.vault_info(st.get("vault", "")),
                    "last": st.get("last_cfg") or B.DEFAULT_CFG,
                    "running": {"k": j["k"], "rid": j["rid"]} if j and j["proc"] is not None and j["proc"].is_alive() else None}
        except Exception as exc:
            log.exception("bt_cards")
            return {"ok": False, "error": str(exc)}

    def bt_update(self, k):
        """3.14: run only the vault days the strategy's run has not covered yet; the run and its P&L are replaced by the
        updated one. Nothing to do = answers at once."""
        try:
            B = self._btm()
            favs = [f.get("sym") for f in (self._settings.get("favorites", []) or []) if isinstance(f, dict)]
            j = self._bt_job()
            if j and j["proc"] is not None and j["proc"].is_alive():
                return {"ok": False, "error": "A backtest is already running"}
            new, total = B.pending(str(k), favs)
            if new == 0:
                return {"ok": True, "uptodate": True, "n": 0, "total": total}
            r = self.bt_run(k, None, True)
            r["new"] = new
            r["total"] = total
            return r
        except Exception as exc:
            log.exception("bt_update")
            return {"ok": False, "error": str(exc)}

    def bt_run(self, k, cfg=None, update=False):
        try:
            j = self._bt_job()
            if j and j["proc"] is not None and j["proc"].is_alive():
                return {"ok": False, "error": "A backtest is already running - stop it first"}
            B = self._btm()
            favs = [f.get("sym") for f in (self._settings.get("favorites", []) or []) if isinstance(f, dict)]
            path, rid, n = B.new_job(str(k), dict(cfg or {}), favs, bool(update))
            import multiprocessing as mp
            proc = mp.get_context("spawn").Process(target=B.run_job, args=(path,), daemon=True, name="lh-backtest")
            proc.start()
            self._btj = {"proc": proc, "k": str(k), "rid": rid, "path": path, "state": "running", "folder": B.strat(str(k))["folder"]}
            log.info("backtest %s started: %d ticker-days (run %s)", k, n, rid)
            return {"ok": True, "rid": rid, "n": n}
        except Exception as exc:
            log.exception("bt_run")
            return {"ok": False, "error": str(exc)}

    def bt_status(self):
        j = self._bt_job()
        if not j:
            return {"ok": True, "job": None}
        B = self._btm()
        pg = B._jload(os.path.join(os.path.dirname(j["path"]), "progress.json"), {})
        alive = j["proc"] is not None and j["proc"].is_alive()
        if not alive and pg.get("state") == "running":
            pg["state"] = "error"
            pg["error"] = pg.get("error") or "the backtest process ended unexpectedly"
        return {"ok": True, "job": {"k": j["k"], "rid": j["rid"], "alive": alive, **pg}}

    def bt_stop(self):
        j = self._bt_job()
        if not j:
            return {"ok": True}
        try:
            open(os.path.join(os.path.dirname(j["path"]), "STOP"), "w").close()
        except OSError:
            pass
        return {"ok": True}

    def bt_runs(self, k):
        try:
            B = self._btm()
            st = B.strat(str(k))
            return {"ok": True, "runs": B.list_runs(st["folder"]) if st else []}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def bt_delete(self, k, rid):
        """3.13.1: delete one run (its folder) of a strategy."""
        try:
            j = self._bt_job()
            if j and j.get("rid") == rid and j["proc"] is not None and j["proc"].is_alive():
                return {"ok": False, "error": "This run is still going - stop it first"}
            B = self._btm()
            st = B.strat(str(k))
            if st is None:
                return {"ok": False, "error": "Unknown strategy"}
            B.delete_run(st["folder"], str(rid))
            log.info("backtest run %s of %s deleted", rid, k)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def bt_result(self, k, rid):
        try:
            B = self._btm()
            st = B.strat(str(k))
            cn = self._cn()
            try:                                         # 3.14: this strategy's old chart notes become shared chart notes
                n = B.notes_move(st["folder"], cn)
                if n:
                    log.info("%s backtest notes of %s moved to the chart notes", n, k)
            except Exception:
                log.exception("moving the backtest notes")
            r = B.result(st["folder"], str(rid))
            allc = cn.everything()                       # the trade list: which charts have notes (live or backtest)
            for t in r["trades"]:
                ns = allc.get(f"{t['tk']}|{t['day']}") or []
                t["nnote"], t["note1"] = len(ns), (ns[-1]["text"][:120] if ns else "")
            return {"ok": True, **r}
        except Exception as exc:
            log.exception("bt_result")
            return {"ok": False, "error": str(exc)}

    def bt_bars(self, tk, day):
        try:
            B = self._btm()
            return B.bars(B.settings().get("vault", ""), str(tk), str(day))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def bt_notes(self, k, tk, day):
        try:
            B = self._btm()
            return {"ok": True, **B.notes_get(B.strat(str(k))["folder"], str(tk), str(day))}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def bt_note_save(self, k, tk, day, verdict=None, text=None, px=None, hms=None, nid=None, delete=False):
        try:
            B = self._btm()
            n = B.notes_save(B.strat(str(k))["folder"], str(tk), str(day), verdict, text, px, hms, nid, bool(delete))
            return {"ok": True, **n}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- 3.14: chart notes (right click on the live chart or a backtest chart -> Add note; core/data/chart_notes.py) ----
    def _cn(self):
        import chart_notes
        return chart_notes.store(DATA_DIR)

    def notes_get(self, tk):
        """Every note of a ticker (all days) - the live chart shows the loaded days, a backtest chart its day."""
        try:
            return {"ok": True, "notes": self._cn().for_ticker(tk)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "notes": []}

    def note_save(self, tk, day, t=None, px=None, text="", nid=None, src="live"):
        try:
            note = self._cn().save(tk, day, t, px, text, nid, src)
            if not nid and str(src) == "live":           # 3.14: the vault feed fetches this ticker-day, so its chart is in the Notes tab
                import threading
                import vault_feed as VF
                threading.Thread(target=VF.record, args=(DATA_DIR, note["day"], [note["tk"]], "chart note"), daemon=True).start()
            return {"ok": True, "note": note}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("note_save")
            return {"ok": False, "error": f"Could not save the note: {exc}"}

    def note_delete(self, nid):
        try:
            return {"ok": self._cn().delete(nid)}
        except Exception as exc:
            log.exception("note_delete")
            return {"ok": False, "error": str(exc)}

    # ---- 3.14: the Notes tab - every ticker-day with chart notes (live + backtest) or a backtest verdict ----
    def notes_list(self):
        try:
            allv = self._cn().everything()
            B = self._btm()
            names = {s["folder"]: s["name"] for s in B.BUILTIN}
            keys_of = {s["folder"]: s["k"] for s in B.BUILTIN}
            verd = B.verdicts_all()
            keys = set(allv) | set(verd)
            trades = B.trades_for(keys)
            out = []
            for k in keys:
                tk, _, day = k.partition("|")
                notes = allv.get(k, [])
                tr = [{"strat": names.get(t["folder"], t["folder"]), "k": keys_of.get(t["folder"], "x_" + t["folder"]), "side": t.get("side", ""), "setup": t.get("setup", ""),
                       "entry": t["entry"], "entry_hms": t.get("entry_hms", ""), "exit": t["exit"], "exit_hms": t.get("exit_hms", ""),
                       "stop": t["stop"], "result": t.get("result", ""), "pnl": t["pnl"]} for t in trades.get(k, [])]
                out.append({"tk": tk, "day": day, "notes": notes,
                            "verdicts": [{"strat": names.get(f, f), "v": v} for f, v in verd.get(k, [])],
                            "trades": tr, "src": sorted({n.get("src", "live") for n in notes}),
                            "last": max([n.get("updated") or n.get("created") or "" for n in notes] or [day])})
            out.sort(key=lambda x: (x["day"], x["last"]), reverse=True)
            return {"ok": True, "items": out}
        except Exception as exc:
            log.exception("notes_list")
            return {"ok": False, "error": str(exc), "items": []}

    def notes_bars(self, tk, day):
        """1-minute candles of a ticker-day for the Notes tab: the vault, else the candles this PC saved from IB."""
        tk = re.sub(r"[^A-Z0-9. ]", "", str(tk or "").upper()).strip()
        day = str(day or "")[:10]
        try:
            B = self._btm()
            r = B.bars(B.settings().get("vault", ""), tk, day)
            if r.get("ok"):
                return r
        except Exception:
            pass
        cache = getattr(self._backend, "cache", None)
        try:
            y, m, d = (int(x) for x in day.split("-"))
            got = cache.day(tk, (ddate(y, m, d) - ddate(1970, 1, 1)).days) if cache is not None else None
        except Exception:
            got = None
        if got and got[0]:
            out, cv, cpv = [], 0.0, 0.0
            for t, o, h, l, c, v in got[0]:
                if not (4 * 3600 <= t % 86400 < 20 * 3600):
                    continue
                cv += v or 0
                cpv += (v or 0) * (h + l + c) / 3.0
                out.append({"time": int(t), "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": cpv / cv if cv else c})
            return {"ok": bool(out), "bars": out, "daily": [], "pc": got[1]}
        today = str(self._backend.now_et().date()) == day
        return {"ok": False, "error": "today's candles are on the live chart (the vault gets them tomorrow)" if today
                else "no candles saved for this day (not in the vault)"}

    # ---- 3.14: the IB tab - the IB account's positions (read only) ----
    def ib_portfolio(self):
        try:
            return {"ok": True, **self._backend.ib_portfolio()}
        except Exception as exc:
            return {"ok": False, "error": str(exc) or exc.__class__.__name__, "rows": []}

    # ---- 3.12.1: favorites (permanent list of tickers, e.g. multi-day runners) ----
    def fav_list(self):
        return {"ok": True, "favs": list(self._settings.get("favorites", []) or [])}

    def fav_set(self, sym, on=True):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        if not sym:
            return {"ok": False, "error": "No symbol"}
        favs = [f for f in (self._settings.get("favorites", []) or []) if isinstance(f, dict) and f.get("sym") != sym]
        if on:
            favs.insert(0, {"sym": sym, "t": self._backend.now_et().strftime("%Y-%m-%d")})
        favs = favs[:300]
        self._settings.set("favorites", favs)
        return {"ok": True, "favs": favs}

    def alert_remove(self, aid):
        ok = self._backend.alerts.remove(str(aid or ""))
        b = self._bot()
        if b is not None:
            b.loop.call_soon_threadsafe(b._push, True)
        return {"ok": ok}

    def scan_screen(self, on, cfg=None):
        self._backend.scan_screen(bool(on), cfg if isinstance(cfg, dict) else {})
        return {"ok": True}

    def ui_screen(self, name):
        self._backend.ui_screen = str(name or "chart")[:12]
        return {"ok": True}

    def _tz_fills(self, rng="month", month=""):
        """3.13: TradeZero's fills for the Journal (live accounts; paper returns none -> the bot's files are used).
        A separate client so the trading connection is never shared; cached 60 s (TradeZero allows 1 request / s)."""
        try:
            bot = self._backend.bot
            tz = getattr(bot, "tz", None)
            if tz is None or not getattr(bot, "acc", ""):
                return None
            today = self._backend.now_et().date()
            days = {"today": 1, "week": 7, "month": 31}.get(str(rng), 365)
            try:
                y, m = (int(x) for x in str(month).split("-")[:2])
                first = ddate(y, m, 1)
                days = max(days, (today - first).days + 1)
            except (TypeError, ValueError):
                pass
            days = min(365, days)
            start = today - timedelta(days=days - 1)
            key = (bot.acc, str(start))
            c = getattr(self, "_tzh_cache", None)
            if c and c[0] == key and time.monotonic() - c[1] < 60:
                return c[2]
            cli = getattr(self, "_tzh_cli", None)
            if cli is None or getattr(cli, "key_id", None) != getattr(tz, "key_id", None):
                cli = type(tz)(tz.key_id, tz.secret, base=getattr(tz, "base", None))
                self._tzh_cli = cli
            fills = cli.history(bot.acc, str(start), days=days + 1)
            self._tzh_cache = (key, time.monotonic(), fills)
            return fills
        except Exception:
            log.warning("journal: TradeZero history not available - using the bot's journal files", exc_info=True)
            return None

    def journal(self, rng="month", month=""):
        try:
            return {"ok": True, **journal_data(str(rng or "month"), str(month or ""), today=self._backend.now_et().date(),
                                               tz_fills=self._tz_fills(rng, month))}
        except Exception as exc:
            log.exception("journal")
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}

    def journal_csv(self, rng="month"):
        """Save the journal's trades of the range as a CSV (no account column) - asks where."""
        try:
            d = journal_data(str(rng or "month"), today=self._backend.now_et().date(), tz_fills=self._tz_fills(rng))
            name = f"lh_journal_{d['from']}_to_{d['to']}.csv"
            path = None
            try:
                import webview
                if self._window is not None:
                    kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or getattr(webview, "SAVE_DIALOG", 30)
                    res = self._window.create_file_dialog(kind, save_filename=name)
                    path = res[0] if isinstance(res, (list, tuple)) and res else res
                    if not path:
                        return {"ok": False, "error": "cancelled"}
            except Exception:
                path = None
            if not path:
                path = os.path.join(os.path.expanduser("~"), "Documents", name)
                if not os.path.isdir(os.path.dirname(path)):
                    path = os.path.join(DATA_DIR, name)
            import csv as _csv
            cols = ["d", "sym", "side", "setup", "qty", "tin", "entry", "tout", "exit", "res", "net", "loc"]
            head = ["date", "symbol", "side", "setup", "shares", "entry_time", "entry", "exit_time", "exit", "result",
                    "pnl_net", "locate_cost"]
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh)
                w.writerow(head)
                for t in reversed(d["trades"]):
                    w.writerow([t.get(c, "") for c in cols])
            return {"ok": True, "file": path, "n": len(d["trades"])}
        except Exception as exc:
            log.exception("journal csv")
            return {"ok": False, "error": str(exc) or exc.__class__.__name__}

    def save_hotkeys(self, data):
        if not isinstance(data, dict):
            return {"ok": False}
        mp = data.get("map") if isinstance(data.get("map"), dict) else {}
        clean = {str(k)[:20]: str(v)[:24] for k, v in mp.items() if re.match(r"^[a-z_]{2,20}$", str(k))}
        self._settings.set("hotkeys", {"on": bool(data.get("on")), "map": clean})
        return {"ok": True}

    def get_daily(self, sym):
        sym = re.sub(r"[^A-Z0-9. ]", "", str(sym or "").upper()).strip()
        try:
            return {"ok": True, "sym": sym, "rows": self._backend.fetch_daily(sym)}
        except Exception as exc:
            log.warning("daily %s: %r", sym, exc)
            return {"ok": False, "sym": sym, "error": str(exc) or exc.__class__.__name__}
