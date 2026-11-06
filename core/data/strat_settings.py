# -*- coding: utf-8 -*-
"""LH Short Bot 3.15 - Settings > Strategies: your changes to a strategy's settings, kept apart from its .py file.

The defaults stay in the strategy files (backtest/<strategy>/*.py). Saved changes go to strategy_settings.json next to the
bot (and to Turso when it is set up, so every PC trades the same values). On save - and at every start - they are put
into the loaded strategy module and into every live stock's engine (its cfg), so new signals use them at once; an open
position keeps its stop. The Backtest tab applies the same values in its worker and they are part of its cache key, so a
backtest always matches the live settings.

FIELDS: strategy -> tabs -> groups -> fields. A field: (key, label, unit, kind, lo, hi[, scale]). key is a path into the
strategy's settings ("GAPPER.MIN_UP_PCT" = SETTINGS["GAPPER"]["MIN_UP_PCT"] of Jay-read 2; a plain name = the module
constant). kind: "num" / "int" / "bool" / "time" / "opt:<a>|<b>" / "num?" (number or none). scale: shown = value / scale
(e.g. $M for 20e6).
"""
import json
import os
import sys
import threading

_LOCK = threading.Lock()

_JR2_SET = [
    ("Stock", [("MIN_UP_PCT", "Min run from prior close", "%", "num", 0, 5000),
               ("MIN_DOLLAR_VOL", "Min $ traded", "$M", "num", 0, 5000, 1e6),
               ("AGE_MIN", "High age from", "min", "int", 0, 390), ("AGE_MAX", "High age to", "min", "int", 1, 390)]),
    ("Flush and bounce", [("CRACK_MIN", "Flush under the high from", "%", "num", 0, 100),
                          ("CRACK_MAX", "Flush under the high to", "%", "num", 0, 100),
                          ("R_MIN", "Bounce takes back from", "share", "num", 0, 1),
                          ("R_MAX", "Bounce takes back to", "share", "num", 0, 1.5),
                          ("DT_PCT", "New-high allowance", "%", "num", 0, 50),
                          ("FLUSH_VW", "Flush low within % over VWAP", "%", "num?", 0, 100)]),
    ("Trigger", [("FRESH", "Within candles of the bounce high", "", "int", 1, 60),
                 ("UNDER_PCT", "Close within % of the bounce high", "%", "num", 0, 50),
                 ("V_MIN_PCT", "Close over VWAP", "%", "num", -50, 200),
                 ("WICK", "Upper wick (share of range)", "", "num", 0, 1)]),
    ("Stop", [("STOP", "Stop at", "", "opt:hod|rh|bh", 0, 0),
              ("STOP_PCT", "Stop over that high", "%", "num", 0, 100),
              ("MAX_STOP_PCT", "Max stop distance", "%", "num?", 0, 500)]),
    ("Time", [("SIGNAL_START", "Signals from", "", "time", 0, 0), ("SIGNAL_END", "Signals to", "", "time", 0, 0)]),
]

FIELDS = {
    "jr2": {"name": "Jay-read 2 short", "module": "jay_read_2_short", "tabs": [
        ("Gapper", "Gapper = opens 30%+ over the prior close",
         [(g, [(f"GAPPER.{k}",) + f[1:] for (k, *_), f in ((x, x) for x in fs)]) for g, fs in _JR2_SET]),
        ("Spiker", "Spiker = opens under +30% (the flush must reach VWAP)",
         [(g, [(f"SPIKER.{k}",) + f[1:] for (k, *_), f in ((x, x) for x in fs)]) for g, fs in _JR2_SET]),
        ("Trade rules", "Same for gappers and spikers", [
            ("Day type", [("GAP_SPLIT_PCT", "Gapper when the open is over the prior close by", "%", "num", 0, 1000)]),
            ("Stop and lock", [("LOCK_AFTER_PCT", "Lock after a fade of", "%", "num", 0, 100),
                               ("LOCK_STOP_PCT", "Lock stop (under the entry; -5 = entry +5%)", "%", "num?", -100, 100)]),
            ("Time", [("LAST_ENTRY_TIME", "Last entry", "", "time", 0, 0), ("EOD_COVER_TIME", "Cover", "", "time", 0, 0)]),
            ("Limits", [("MAX_TRADES_PER_DAY", "Max trades per stock per day", "", "int", 1, 20),
                        ("ONE_PER_HIGH", "One short per high", "", "bool", 0, 0),
                        ("STOP_FOR_DAY_AFTER_STOP", "Done for the stock after a stop", "", "bool", 0, 0),
                        ("MAX_HALT_JUMPS", "Skip after halt jumps", "", "int", 0, 100)]),
        ]),
    ]},
    "jr": {"name": "Jay-read short v1.2", "module": "jay_read_short", "tabs": [
        ("Settings", "", [
            ("Stock", [("MIN_DOLLAR_VOL", "Min $ traded", "$M", "num", 0, 5000, 1e6),
                       ("HOD_MIN_AGE_MIN", "High at least this old", "min", "int", 0, 390),
                       ("MIN_CRACK_PCT", "Crack under the high", "%", "num", 0, 100),
                       ("CRACK_NEAR_VWAP_PCT", "Crack low within % of VWAP", "%", "num", 0, 100)]),
            ("Bounce and trigger", [("MIN_DROP_PCT", "Drop from the overhead high", "%", "num", 0, 100),
                                    ("MIN_BOUNCE_PCT", "Bounce from the drop low", "%", "num", 0, 200),
                                    ("RETRACE_MIN", "Bounce takes back at least", "share", "num", 0, 1),
                                    ("MAX_RECLAIM", "Close takes back at most", "share", "num", 0, 1),
                                    ("FRESH_TOP_MIN", "Red candle within min of the bounce high", "min", "int", 1, 60),
                                    ("MAX_UNDER_BOUNCE_HIGH_PCT", "Close within % of the bounce high", "%", "num", 0, 50),
                                    ("MIN_OVER_VWAP_PCT", "Close over VWAP", "%", "num", -50, 200),
                                    ("LEVEL_SHORT", "Level shorts", "", "bool", 0, 0)]),
            ("Stop and lock", [("HOD_STOP_PCT", "Stop over the high", "%", "num", 0, 100),
                               ("LOCK_AFTER_PCT", "Lock after a fade of", "%", "num", 0, 100),
                               ("LOCK_STOP_PCT", "Lock stop (under the entry; -5 = entry +5%)", "%", "num?", -100, 100)]),
            ("Time", [("SIGNAL_START", "Signals from", "", "time", 0, 0), ("SIGNAL_END", "Signals to", "", "time", 0, 0),
                      ("LAST_ENTRY_TIME", "Last entry", "", "time", 0, 0), ("EOD_COVER_TIME", "Cover", "", "time", 0, 0)]),
            ("Limits", [("MAX_TRADES_PER_DAY", "Max trades per stock per day", "", "int", 1, 20),
                        ("STOP_FOR_DAY_AFTER_STOP", "Done for the stock after a stop", "", "bool", 0, 0),
                        ("MAX_HALT_JUMPS", "Skip after halt jumps", "", "int", 0, 100)]),
        ]),
    ]},
    "long": {"name": "Premarket long", "module": "lh_long_premarket", "tabs": [
        ("Settings", "", [
            ("Stock", [("MIN_GAP_PCT", "Watch from prior close +", "share", "num", 0, 10),
                       ("MIN_ENTRY_PRICE", "Min price", "$", "num", 0, 1000), ("MAX_ENTRY_PRICE", "Max price", "$", "num", 0, 1000),
                       ("MAX_EXT_FROM_OPEN", "No entry over the 05:00 open by", "share", "num", 0, 100)]),
            ("Momentum trigger", [("MOM_SURGE_PCT", "1-min candle open to close", "share", "num", 0, 1),
                                  ("MOM_RVOL", "RVOL at least", "x", "num", 0, 100),
                                  ("MOM_MIN_VOLUME", "Shares in that minute", "sh", "int", 0, 10_000_000),
                                  ("MOM_STRONG_CLOSE", "Close in the top of its range", "share", "num", 0, 1),
                                  ("FRESH_ENTRY_SEC", "Entries within s of discovery", "s", "int", 0, 14400),
                                  ("MAX_CHASE_PCT", "Skip when the ask is over the trigger by", "%", "num", 0, 100)]),
            ("Stop and exits", [("MIN_RISK_PCT", "Min stop distance", "share", "num", 0, 1),
                                ("MAX_RISK_PCT", "Max stop distance", "share", "num", 0, 1),
                                ("TARGET_MULT", "Half at R x", "R", "num", 0, 20),
                                ("TARGET_MULT_STRONG", "Half at R x (strong RVOL)", "R", "num", 0, 20),
                                ("MAX_HOLD_MIN_WITHOUT_PROFIT", "Time stop without profit", "min", "int", 1, 240),
                                ("STOP_EARLY_PCT", "Hard stop sells this % over the stop", "%", "num", 0, 20)]),
            ("Limits", [("MAX_TRADES_PER_SYMBOL", "Max trades per stock", "", "int", 1, 20),
                        ("MAX_CONSECUTIVE_LOSSES", "Done after stop-outs in a row", "", "int", 1, 20),
                        ("MAX_OPEN_POSITIONS", "Max open longs", "", "int", 1, 20),
                        ("MAX_POSITION_USD", "Max $ per long", "$", "num", 0, 1_000_000)]),
        ]),
    ]},
}


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if os.path.isfile(os.path.join(d, "main.py")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))


PATH = os.path.join(base_dir(), "strategy_settings.json")


def _cloud():
    try:
        import turso
        return turso.cloud()
    except Exception:
        return None


def load():
    """{strategy: {key: value}} - this PC's file, Turso's copy wins when it is set up."""
    data = {}
    try:
        with open(PATH, encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, ValueError):
        pass
    c = _cloud()
    if c is not None:
        try:
            remote = c.kv_get("strategy_settings", "all", None)
            if remote:
                data = remote
            elif data:
                c.kv_put("strategy_settings", "all", data)
        except Exception:
            pass
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save(data):
    with _LOCK:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, PATH)
    c = _cloud()
    if c is not None:
        try:
            c.kv_put_bg("strategy_settings", "all", data)
        except Exception:
            pass


def fields(k):
    out = []
    for _tab, _note, groups in FIELDS[k]["tabs"]:
        for _g, fs in groups:
            out.extend(fs)
    return {f[0]: f for f in out}


def module(k):
    return sys.modules.get(FIELDS[k]["module"])


def default(k, key):
    """The value in the strategy file (the module as imported, before any override)."""
    m = module(k)
    if m is None:
        return None
    base = getattr(m, "_LH_DEFAULTS", None)
    if base is None:
        base = m._LH_DEFAULTS = {}
    if key not in base:
        base[key] = _get_raw(m, key)
    return base[key]


def _get_raw(m, key):
    if "." in key:
        a, b = key.split(".", 1)
        return (getattr(m, "SETTINGS", {}).get(a) or {}).get(b)
    if hasattr(m, "SETTINGS") and key in m.SETTINGS:
        return m.SETTINGS[key]
    return getattr(m, key, None)


def check(k, key, v):
    """(ok, value or error) for one field."""
    f = fields(k).get(key)
    if f is None:
        return False, "unknown setting"
    kind, lo, hi = f[3], f[4], f[5]
    if kind == "bool":
        return True, bool(v)
    if kind == "time":
        s = str(v or "").strip()
        try:
            hh, mm = (int(x) for x in s.split(":")[:2])
            if 0 <= hh < 24 and 0 <= mm < 60:
                return True, f"{hh:02d}:{mm:02d}"
        except ValueError:
            pass
        return False, "HH:MM"
    if kind.startswith("opt:"):
        opts = kind[4:].split("|")
        return (True, v) if v in opts else (False, "one of " + ", ".join(opts))
    if kind == "num?" and (v is None or v == ""):
        return True, None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False, "a number"
    if not lo <= x <= hi:
        return False, f"{lo:g} to {hi:g}"
    return True, int(round(x)) if kind == "int" else x


def apply(k, values, books=()):
    """Put the values (overrides; missing keys = the file's default) into the loaded module and the live engines."""
    m = module(k)
    if m is None:
        return 0
    n = 0
    for key in fields(k):
        default(k, key)                                      # remember the file's value before the first change
    for key in fields(k):
        v = values.get(key, default(k, key))
        if "." in key:
            a, b = key.split(".", 1)
            m.SETTINGS[a][b] = v
        elif hasattr(m, "SETTINGS") and key in m.SETTINGS:
            m.SETTINGS[key] = v
            if hasattr(m, key):
                setattr(m, key, v)
        else:
            setattr(m, key, v)
        n += 1
    if k == "jr2":                                           # its flat names (the GAPPER set) for the bot's screens
        g = m.SETTINGS["GAPPER"]
        m.MIN_UP_PCT, m.MIN_DOLLAR_VOL, m.HOD_MIN_AGE_MIN = g["MIN_UP_PCT"], g["MIN_DOLLAR_VOL"], g["AGE_MIN"]
        m.MIN_CRACK_PCT, m.SIGNAL_START, m.SIGNAL_END, m.HOD_STOP_PCT = g["CRACK_MIN"], g["SIGNAL_START"], g["SIGNAL_END"], g["STOP_PCT"]
    if k == "long" and hasattr(m, "hms_secs"):
        pass                                                 # (no time fields for the long here: its windows stay in the file)
    fresh = m.settings() if hasattr(m, "settings") else None
    for book in books:                                       # the live engines: new signals use the new values at once
        for part in (getattr(book, "parts", None) or [book]):
            if type(part).__module__ == m.__name__ and isinstance(getattr(part, "cfg", None), dict) and fresh:
                for kk, vv in fresh.items():
                    part.cfg[kk] = dict(vv) if isinstance(vv, dict) else vv
    return n


def apply_all(books=()):
    data = load()
    for k in FIELDS:
        if module(k) is not None:
            apply(k, data.get(k, {}), books)
    return data


def fingerprint(k):
    """The saved overrides of a strategy, as text (part of the Backtest tab's cache key)."""
    return json.dumps(load().get(k, {}), sort_keys=True)


def view(k):
    """The page: tabs, groups, fields with value / default / changed."""
    data = load().get(k, {})
    tabs = []
    for tab, note, groups in FIELDS[k]["tabs"]:
        gs = []
        for g, fs in groups:
            items = []
            for f in fs:
                key, label, unit, kind, lo, hi = f[:6]
                scale = f[6] if len(f) > 6 else 1
                d = default(k, key)
                v = data.get(key, d)
                items.append({"key": key, "label": label, "unit": unit, "kind": kind, "lo": lo, "hi": hi, "scale": scale,
                              "value": v, "default": d, "changed": key in data and data[key] != d})
            gs.append({"name": g, "fields": items})
        tabs.append({"name": tab, "note": note, "groups": gs})
    return {"k": k, "name": FIELDS[k]["name"], "loaded": module(k) is not None, "tabs": tabs}
