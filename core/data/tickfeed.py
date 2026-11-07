# -*- coding: utf-8 -*-
"""Kestrel - tick-by-tick prices for the few stocks that matter right now (3.12.2, 2026-10-31).

IB streams every single trade ("AllLast" tick-by-tick) for only a handful of stocks at a time, so the bot gives its
TICK_BY_TICK_MAX slots (5) to the stocks closest to an order, and re-decides every second:

    0  a position or an order in flight          (short: locating / working / short / covering / manual;
                                                   long: holding, or a buy / sell being worked)
    1  a short setup is live                      (Jay-read / squeeze read on, a signal waiting, a locate search)
    2  the premarket-long watchlist               (it only lists stocks already up 30%+ inside the fresh window;
                                                   it drops them itself when the window ends or the move fails)
    3  shorts you added yourself                  (scanner auto-adds get a slot only once a setup is live)
    4  the chart you have open, while Time & Sales is on (3.15) - only when a slot is left over

A stock that stops qualifying gives its slot back within a second. Nothing about the strategies changes: IB puts each
trade into the SAME ticker object the bot already reads (ticker.last), so the existing price handlers simply hear every
trade instead of IB's ~250 ms summary. The premarket long, which acts on every price, also gets each print of a burst
one by one (see patch_long). The normal quote stream (bid / ask / volume / halts) stays as it is. If IB refuses a slot
(its own limit), the stock just keeps the normal stream and the slot is retried a minute later.
"""
import time

TICK_TYPE = "AllLast"
SHORT_ACTIVE = ("locating", "working", "short", "covering", "manual")


class TickSlots:
    def __init__(self, max_n=5, log=None):
        self.max_n = int(max_n)
        self.log = log or (lambda *a, **k: None)
        self.subs = {}            # key -> (contract, ticker)
        self.ib = None
        self.refused = {}         # key -> monotonic time to retry
        self._err_hooked = None

    # IB's "too many tick-by-tick requests" / "not allowed" errors -> give the slot back, retry later
    def _on_error(self, req_id, code, msg, contract=None):
        if code not in (10189, 10190, 10191, 354, 10167, 10168, 322):
            return
        for key, (c, tk) in list(self.subs.items()):
            rid = self._req_id(tk)
            if rid == req_id or (contract is not None and c is contract):
                self._cancel(key)
                self.refused[key] = time.monotonic() + 60
                self.log(f"{key[1]}: IB refused tick-by-tick ({code}) - normal quotes, retry in 1 min", "warn")

    def _req_id(self, tk):
        try:
            return self.ib.wrapper.ticker2ReqId[TICK_TYPE].get(tk)
        except Exception:
            return None

    def _cancel(self, key):
        c, _tk = self.subs.pop(key, (None, None))
        if c is not None and self.ib is not None and self.ib.isConnected():
            try:
                self.ib.cancelTickByTickData(c, TICK_TYPE)
            except Exception:
                pass

    def sync(self, ib, wanted):
        """wanted = [(priority, key, contract)]; key = (side, symbol). Keeps the best TICK_BY_TICK_MAX subscribed."""
        if ib is None or not ib.isConnected():
            self.subs.clear()                        # IB dropped them with the connection
            self.ib = None
            return
        if ib is not self.ib:                       # new connection: old subscriptions are gone
            self.subs.clear()
            self.ib = ib
        if self._err_hooked is not ib:
            try:
                ib.errorEvent += self._on_error
                self._err_hooked = ib
            except Exception:
                pass
        now = time.monotonic()
        best, seen = [], set()
        for prio, key, contract in sorted(wanted, key=lambda w: w[0]):
            if key in seen or contract is None or self.refused.get(key, 0) > now:
                continue
            seen.add(key)
            best.append((key, contract))
            if len(best) >= self.max_n:
                break
        want = dict(best)
        for key in list(self.subs):
            if key not in want or self.subs[key][0] is not want[key]:   # gone, or re-subscribed with a new contract
                self._cancel(key)
        added = []
        for key, contract in want.items():
            if key in self.subs:
                continue
            try:
                tk = ib.reqTickByTickData(contract, TICK_TYPE, 0, False)
                self.subs[key] = (contract, tk)
                added.append(key[1])
            except Exception as exc:
                self.refused[key] = now + 60
                self.log(f"{key[1]}: tick-by-tick not started ({exc}) - normal quotes", "warn")
        if added:
            self.log("tick-by-tick on: " + ", ".join(f"{k[1]} ({'long' if k[0] == 'L' else 'short'})"
                                                     for k in self.subs))

    def close(self):
        for key in list(self.subs):
            self._cancel(key)

    def names(self):
        return [k[1] for k in self.subs]


def patch_long(trader_cls):
    """The premarket long acts on every price (entry trigger, stop, target, trail): give it each print of a burst in
    order, not only the last one. Same on_price, same rules - only more of the prices it would have seen."""
    if getattr(trader_cls, "_tbt_patched", False):
        return
    orig = trader_cls._on_tick

    def _on_tick(self, tk):
        try:
            prints = [float(t.price) for t in (getattr(tk, "tickByTicks", None) or ())
                      if getattr(t, "price", 0) and float(t.price) > 0]
        except Exception:
            prints = []
        if len(prints) > 1 and not self.halted and not self.seeding:
            for p in prints[:-1]:                    # the last print goes through the normal handler below
                self.last = p
                try:
                    self.on_price(p)
                except Exception:
                    pass
        orig(self, tk)

    trader_cls._on_tick = _on_tick
    trader_cls._tbt_patched = True


def wanted_for(bot):
    """The bot's candidates for a slot (see the priorities above)."""
    out = []
    for bs in list(getattr(bot, "syms", {}).values()):
        st = bs.st
        if st is None or getattr(st, "contract", None) is None or bs.ticker is None:
            continue
        if bs.phase in SHORT_ACTIVE:
            p = 0
        elif bs.jr_sig or bs.hunt or bs.jr_ctx or bs.pre_req:
            p = 1
        elif not bs.auto_added:
            p = 3
        else:
            continue
        out.append((p, ("S", bs.sym), st.contract))
    lb = getattr(bot, "longbot", None)
    if lb is not None and getattr(lb, "enabled", True):
        for tr in list(getattr(lb, "traders", {}).values()):
            if not getattr(tr, "active", False) or tr.ticker is None or tr.contract is None:
                continue
            patch_long(type(tr))
            held = tr.day.pos is not None or tr.busy()
            out.append((0 if held else 2, ("L", tr.sym), tr.contract))
    # 3.15: the chart you have open while Time & Sales is on - last in line (every watchlist stock above comes first)
    be = getattr(bot, "be", None)
    tp, st = getattr(be, "tape", None), getattr(be, "state", None)
    if (tp is not None and tp.on and st is not None and getattr(st, "subscribed", False)
            and getattr(st, "contract", None) is not None and st.sym not in {k[1] for _p, k, _c in out}):
        out.append((4, ("S", st.sym), st.contract))
    return out
