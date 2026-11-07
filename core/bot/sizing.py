# -*- coding: utf-8 -*-
"""Kestrel - Bot: the 09:00 sizing base and position size.
Part of the Bot class (core/bot/bot_core.py): main.py runs this file in its own namespace. Code moved here unchanged."""

class _BotSizing:

    def _size_equity(self):
        """3.12: what ACCOUNT_PCT is taken of - the sizing base (equity at SIZE_BASE_TIME, re-set when a trade closes);
        before the base is set: the equity now."""
        if self.size_base and self.size_base > 0:
            return self.size_base
        return _fnum(self.acc_info.get("equity"))

    def _size(self, px):
        eq = self._size_equity()
        bp = _fnum(self.acc_info.get("buyingPower", self.acc_info.get("bp")), 0.0)
        pos_usd = min(eq * ACCOUNT_PCT / 100.0, MAX_POSITION_USD)
        if bp > 0:
            pos_usd = min(pos_usd, bp * 0.95)
        return int(pos_usd // px) if px > 0 else 0

    def _size_base_tick(self, secs):
        """Set the base at SIZE_BASE_TIME (or at the start when the app starts later); re-set it after a close: the
        equity after the close when nothing else is open, else the old base + the closed trades' realized P&L (the open
        trades' P&L never changes the size)."""
        eq = _fnum(self.acc_info.get("equity"))
        if eq <= 0:
            return
        n, usd = self._closed_today()
        today = str(self.now().date())
        if self.size_base is None:
            if secs < _secs(SIZE_BASE_TIME):
                return
            st = self._state_load()
            if st.get("date") == today and _fnum(st.get("base")) > 0:
                self.size_base, self.size_note = _fnum(st["base"]), str(st.get("base_note") or "kept from earlier today")
                self.size_closed = (int(st.get("closed_n") or 0), _fnum(st.get("closed_usd")))
                self._log(f"Size base {_money(self.size_base)} ({self.size_note}) - kept after the restart")
                return
            late = secs >= _secs(SIZE_BASE_TIME) + 120
            self.size_base = eq
            self.size_note = (f"equity at {self.now():%H:%M} (the app started after {SIZE_BASE_TIME})" if late
                              else f"equity at {SIZE_BASE_TIME}")
            self.size_closed = (n, usd)
            self._state_save()
            self._notify(f"Size base {_money(eq)}  ·  each short {_money(min(eq * ACCOUNT_PCT / 100.0, MAX_POSITION_USD))}",
                         f"{self.size_note.capitalize()}. Every new short is {ACCOUNT_PCT:g}% of it - also while other "
                         f"trades are open. It is re-set when a trade closes.", "dim", tag="SIZE BASE", who="System")
            return
        cn, cusd = self.size_closed or (n, usd)
        if n == cn:
            self.rebase_at = None
            return
        mono = time.monotonic()
        if self.rebase_at is None:                       # a trade closed: read the account first (equity after it)
            self.rebase_at = mono
            self.next_acct = 0.0
            return
        if self.acct_mono < self.rebase_at and mono - self.rebase_at < 20:
            return
        old = self.size_base
        opens = self._opens_now()
        if not opens and self.acct_mono >= self.rebase_at:
            self.size_base, how = eq, "equity after the close"
        else:
            self.size_base = max(1.0, old + (usd - cusd))
            how = "base + the closed trade's P&L" + (f" ({', '.join(opens)} still open)" if opens else "")
        self.size_note = f"{how} at {self.now():%H:%M}"
        self.size_closed, self.rebase_at = (n, usd), None
        self._state_save()
        self._log(f"Size base {_money(old)} -> {_money(self.size_base)} ({how})")
        self._notify(f"Size base {_money(old)} → {_money(self.size_base)}  ·  next short "
                     f"{_money(min(self.size_base * ACCOUNT_PCT / 100.0, MAX_POSITION_USD))}",
                     f"A trade closed: {how}.", "dim", tag="SIZE BASE", who="System")

    def _jr_size(self, px, stop):
        """Shares for a short at px: ACCOUNT_PCT of equity (max MAX_POSITION_USD, buying power), then the $ risk cap.
        Returns (shares, note)."""
        qty = self._size(px)
        risk = stop - px
        if MAX_RISK_PER_TRADE_USD and risk > 0:
            cap = int(MAX_RISK_PER_TRADE_USD / risk)
            if cap < qty:
                return cap, f"cut from {qty:,} to {cap:,} sh by the ${MAX_RISK_PER_TRADE_USD:,.0f} risk cap"
        return qty, ""
