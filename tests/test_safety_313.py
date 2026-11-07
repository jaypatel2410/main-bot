"""Kestrel 3.13.0 - safety checks (no IB, no TradeZero, no orders). Run from the bot folder:  python tests/test_safety_313.py

1  live trading stays locked: ALLOW_LIVE_TRADING is False in core/settings.py, a LIVE account is blocked, and neither the
   .env file nor an environment variable can switch it on
2  the strategy modules hold no order / broker code (they only read candles and return events)
3  start-up defaults: Jay-read 2 trading, Jay-read v1.2 off, max squeeze off; modes saved before 3.13 do not switch v1.2 on
4  one short per stock: Jay-read 2 + Jay-read v1.2 in the same ShortBook - a second signal while the first is in a trade is
   skipped
5  .env.example holds no credentials
"""
import os
import re
import runpy
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
ok_n = fail_n = 0


def check(name, cond, info=""):
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print(f"  ok    {name}")
    else:
        fail_n += 1
        print(f"  FAIL  {name} {info}")


os.environ["ALLOW_LIVE_TRADING"] = "True"                    # must have no effect
ns = runpy.run_path(os.path.join(ROOT, "main.py"), run_name="lh_safety_test")

print("1 live trading lock")
check("ALLOW_LIVE_TRADING is False", ns["ALLOW_LIVE_TRADING"] is False)
src = open(os.path.join(ROOT, "core", "settings.py"), encoding="utf-8").read()
check("set in core/settings.py as a constant", re.search(r"^ALLOW_LIVE_TRADING = False", src, re.M) is not None)
helper_lines = [l for l in open(os.path.join(ROOT, "core", "data", "helpers.py"), encoding="utf-8")
                if "ALLOW_LIVE_TRADING" in l and not l.strip().startswith("#")]
check("the .env reader never sets ALLOW_LIVE_TRADING", not any(re.search(r"ALLOW_LIVE_TRADING\s*=", l) for l in helper_lines))
check("an ALLOW_LIVE_TRADING=True environment variable has no effect", ns["ALLOW_LIVE_TRADING"] is False)


class _Acct:
    acc_type = "live"


blocked = ns["_BotStopsHalts"].live_blocked(_Acct())
check("a LIVE account is blocked", blocked is True)
_Acct.acc_type = "paper"
check("a paper account is not blocked", ns["_BotStopsHalts"].live_blocked(_Acct()) is False)

print("2 strategy modules place no orders")
for f in ("backtest/jay_read_2/jay_read_2_short.py", "backtest/jay_read_short/jay_read_short.py"):
    code = open(os.path.join(ROOT, f), encoding="utf-8").read()
    bad = [w for w in ("Tradezero", "TZClient", "requests", "urllib", "place_order", "_place(", "ib_async", "ib_insync")
           if w in code]
    check(f"{f} has no broker / network code", not bad, bad)

print("3 start-up defaults")
ns["set_modes"]({})
check("Jay-read 2 = trading", ns["mode"]("jr2") == "trading")
check("Jay-read v1.2 = off", ns["mode"]("jr") == "off")
check("max squeeze and v16 not in the live bot (3.15)", "sq" not in ns["MODE_KEYS"] and "SQ" not in ns
      and "jr_mode" not in ns and "bot_engine" not in ns)
m = ns["set_modes"]({"jr": "trading", "long": "trading"})
check("modes saved before 3.13 keep v1.2 off", m["jr"] == "off" and m["jr2"] == "trading")
ns["set_modes"]({})
check("JR_EOD_COVER_TIME = 15:55", ns["JR_EOD_COVER_TIME"] == "15:55")

print("4 one short per stock (ShortBook)")
from datetime import datetime, timedelta                       # noqa: E402
ns["set_modes"]({"jr2": "trading", "jr": "trading"})
book = ns["make_book"]("TEST", 1.0, live=True)
check("book holds Jay-read 2 first, then v1.2", [type(p).__name__ for p in book.parts] == ["JayRead2Short", "JayReadShort"])
jr2 = book.jr2
jr2.awaiting = {"setup": "jr2_gap", "stop": 10.0, "rth_high": 9.0}
jr2.entry_filled(5.0, datetime(2026, 11, 2, 10, 0))
book.jr1.awaiting = None
t0 = datetime(2026, 11, 2, 10, 1)
ev = []
book.jr1.on_bar = lambda *a, **k: [dict(type="SIGNAL", time=t0, close=6.0, stop=9.0, signal={"setup": "rollover"})]
ev = book.on_bar(t0, 5, 5.1, 4.9, 5, 1000)
check("a v1.2 signal while Jay-read 2 holds the stock is skipped",
      any(e["type"] == "SKIP" for e in ev) and not any(e["type"] == "SIGNAL" for e in ev), ev)
ns["set_modes"]({})

print("5 .env.example")
ex = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
vals = {k: v.strip() for k, v in re.findall(r"^([A-Z_]+)=(.*)$", ex, re.M)}
check("no key / secret / account / webhook values",
      all(not vals.get(k) for k in ("TZ_API_KEY_ID", "TZ_API_SECRET", "TZ_ACCOUNT_ID", "DISCORD_WEBHOOK_URL")))
check("no Discord webhook URL anywhere", "discord.com/api/webhooks/" not in ex)

print(f"\n{ok_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
