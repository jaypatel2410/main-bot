# -*- coding: utf-8 -*-
"""LH Short Bot - app helpers: .env, strategy selection, chart rows, settings, alerts, journal, UI bridge, BotSym.
Part of main.py: main.py runs this file in its OWN namespace (same names, same settings), so the code works exactly
as when it was one file. Do not run it on its own - start main.py."""
# =============================================================================
# APP CODE
# =============================================================================
APP_NAME = "LH Short Bot"
APP_VERSION = "3.13.1"

try:
    from zoneinfo import ZoneInfo
    ET_TZ = ZoneInfo("America/New_York")
except Exception:  # no tz database available - fall back to pytz (ships with pandas)
    import pytz
    ET_TZ = pytz.timezone("America/New_York")


def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _data_dir():
    root = os.environ.get("LOCALAPPDATA")
    path = os.path.join(root, "LHShortBot") if root else os.path.join(os.path.expanduser("~"), ".lh_short_bot")
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = _data_dir()
log = logging.getLogger("lh_app")


# -----------------------------------------------------------------------------
# 3.11: ONE .env FILE FOR EVERY CREDENTIAL. KEY=VALUE lines next to the app (the .exe folder); # = comment. Read at
# start-up and whenever the keys are needed; the Keys dialog writes to it. Values are never logged or shown.
# -----------------------------------------------------------------------------
ENV_FILE_NAME = ".env"
ENV_KEYS = ("TZ_API_KEY_ID", "TZ_API_SECRET", "TZ_ACCOUNT_ID", "TZ_ROUTE", "DISCORD_WEBHOOK_URL", "DISCORD_MENTION",
            "IB_HOST", "IB_PORT", "IB_CLIENT_ID", "VAULT_DB", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY", "SEC_CONTACT_EMAIL")
ENV_SECRET = ("TZ_API_KEY_ID", "TZ_API_SECRET", "TZ_ACCOUNT_ID", "DISCORD_WEBHOOK_URL", "TURSO_AUTH_TOKEN", "ALPACA_SECRET_KEY")
ENV_ALIASES = {"TZ_API_SECRET_KEY": "TZ_API_SECRET", "TRADEZERO_API_KEY_ID": "TZ_API_KEY_ID",
               "TRADEZERO_API_SECRET": "TZ_API_SECRET", "DISCORD_WEBHOOK": "DISCORD_WEBHOOK_URL"}
ENV_TEMPLATE = """# LH Short Bot - every credential in one file (3.11).
# Keep this file next to LHShortBot.exe (or main.py). Never share it, never upload it.
# One KEY=VALUE per line, no quotes needed. An empty value = not set. Lines starting with # are comments.

# TradeZero Developer API keys (paper keys trade the paper account, live keys the live account)
TZ_API_KEY_ID=
TZ_API_SECRET=
# Account ID: empty = the first account these keys can see
TZ_ACCOUNT_ID=
# Route: empty = TradeZero's default (paper: PAPER)
TZ_ROUTE=

# Discord: Server Settings -> Integrations -> Webhooks -> New Webhook -> Copy Webhook URL
DISCORD_WEBHOOK_URL=
# Ping on urgent messages: @everyone, <@your user id> or empty
DISCORD_MENTION=@everyone

# IB Gateway (live 4001, paper 4002; TWS 7496 / 7497)
IB_HOST=127.0.0.1
IB_PORT=4001
IB_CLIENT_ID=101

# Your IB data vault (market_data_vault.db), read only - older days load from it first. Empty = not used
VAULT_DB=

# Turso cloud database (settings, favorites, backtests, notes, journals, vault): Settings > Keys and Discord
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=

# Real-time news (News tab): a free Alpaca account (alpaca.markets -> API keys) and your e-mail for the SEC
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
SEC_CONTACT_EMAIL=

# Live trading is NOT switched on here: it needs ALLOW_LIVE_TRADING = True in main.py.
"""


def env_path():
    """The .env file in use: next to the app, else in the app data folder. A new one goes next to the app (the app data
    folder when the app folder cannot be written)."""
    for p in (os.path.join(_base_dir(), ENV_FILE_NAME), os.path.join(_base_dir(), ENV_FILE_NAME + ".txt"),
              os.path.join(DATA_DIR, ENV_FILE_NAME)):
        if os.path.isfile(p):                        # (.env.txt: Notepad added ".txt" - it works too)
            return p
    p = os.path.join(_base_dir(), ENV_FILE_NAME)
    try:
        probe = os.path.join(_base_dir(), ".lh_write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("x")
        os.remove(probe)
        return p
    except OSError:
        return os.path.join(DATA_DIR, ENV_FILE_NAME)


def _env_parse_line(line):
    s = line.strip()
    if not s or s.startswith("#") or "=" not in s:
        return None, None
    if s.lower().startswith("export "):
        s = s[7:].lstrip()
    k, v = s.split("=", 1)
    k, v = k.strip().upper(), v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    elif " #" in v:                                  # KEY=value  # comment
        v = v.split(" #", 1)[0].rstrip()
    return ENV_ALIASES.get(k, k), v


def env_read(path=None):
    """{KEY: value} from the .env file (missing file = {})."""
    path = path or env_path()
    out = {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                k, v = _env_parse_line(line)
                if k:
                    out[k] = v
    except OSError:
        pass
    return out


def env_get(key, default=""):
    """A setting: the .env file first, then the Windows / shell environment, then `default`."""
    v = env_read().get(key, "")
    if not v:
        v = os.environ.get(key, "") or next((os.environ.get(a, "") for a, k in ENV_ALIASES.items() if k == key
                                             and os.environ.get(a)), "")
    return v if v else default


def env_write(updates, path=None):
    """Set keys in the .env file, keeping every other line and comment (a missing file starts from the template).
    Atomic (temp file + replace). Returns the path."""
    path = path or env_path()
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = ENV_TEMPLATE.splitlines()
    todo = {k: ("" if v is None else str(v).replace("\n", "").replace("\r", "")) for k, v in updates.items()}
    for i, line in enumerate(lines):
        k, _ = _env_parse_line(line)
        if k in todo:
            lines[i] = f"{k}={todo.pop(k)}"
    for k, v in todo.items():
        lines.append(f"{k}={v}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines).rstrip("\n") + "\n")
    os.replace(tmp, path)
    return path


def env_migrate():
    """First start of 3.11 (no .env file yet): create .env and copy in what the Keys dialog saved before
    (tradezero.json, discord.json in the app data folder or next to the app). Once .env exists it is the only place -
    nothing is copied again (a key you delete from .env stays deleted). Returns the names copied (never the values)."""
    path = env_path()
    if os.path.isfile(path):
        return []
    have = {}
    found = {}
    for p in (os.path.join(_base_dir(), "tradezero.json"), os.path.join(DATA_DIR, "tradezero.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            for jk, ek in (("api_key_id", "TZ_API_KEY_ID"), ("api_secret", "TZ_API_SECRET"),
                           ("account_id", "TZ_ACCOUNT_ID"), ("route", "TZ_ROUTE")):
                if str(d.get(jk, "") or "").strip():
                    found[ek] = str(d[jk]).strip()
        except (OSError, ValueError, AttributeError):
            pass
    for p in (os.path.join(_base_dir(), "discord.json"), os.path.join(DATA_DIR, "discord.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            if str(d.get("url", "") or "").strip():
                found["DISCORD_WEBHOOK_URL"] = str(d["url"]).strip()
            if "mention" in d and d["mention"] is not None:
                found["DISCORD_MENTION"] = str(d["mention"]).strip()
        except (OSError, ValueError, AttributeError):
            pass
    add = {k: v for k, v in found.items() if not have.get(k)}
    if not os.path.isfile(path) or add:
        try:
            env_write(add, path)
        except OSError as exc:
            log.warning("could not write %s: %s", path, exc.__class__.__name__)
            return []
    return sorted(add)


def env_apply():
    """IB Gateway address and the vault path from .env (the constants above are the defaults)."""
    global IB_HOST, IB_PORT, IB_CLIENT_ID, VAULT_DB
    IB_HOST = env_get("IB_HOST", IB_HOST) or IB_HOST
    for name in ("IB_PORT", "IB_CLIENT_ID"):
        raw = env_get(name, "")
        if raw:
            try:
                globals()[name] = int(raw)
            except ValueError:
                log.warning(".env: %s is not a number - using %s", name, globals()[name])
    VAULT_DB = env_get("VAULT_DB", VAULT_DB) or ""


def env_status():
    """For the Keys dialog / log: which credentials are set (names only, never values)."""
    d = env_read()
    return {"file": env_path(), "exists": os.path.isfile(env_path()),
            "set": [k for k in ENV_KEYS if d.get(k)], "missing": [k for k in ENV_SECRET[:2] + ("DISCORD_WEBHOOK_URL",)
                                                            if not d.get(k)]}
STRAT = sys.modules.get(__name__)
STRATEGY_SOURCE = "embedded (v16: bounce-zone + vacuum short)"


def _setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    fh = RotatingFileHandler(os.path.join(DATA_DIR, "app.log"), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    for name in ("ib_async", "ib_insync"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.addHandler(fh)


def _select_strategy():
    """Embedded engine by default; optionally the lh_short_backtester.py next to the app."""
    here = sys.modules[__name__]
    if not USE_EXTERNAL_STRATEGY:
        return here, "embedded (v16: bounce-zone + vacuum short)"
    path = os.path.join(_base_dir(), EXTERNAL_STRATEGY_FILE)
    if not os.path.exists(path):
        return here, "embedded (external file not found)"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("lh_external_strategy", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for k, v in (("VACUUM_ENABLED", False), ("VAC_ENTRY_START", "09:30"), ("VAC_LAST_ENTRY_TIME", "15:30"),
                     ("VAC_PULLBACK_PCT", 5.0), ("VAC_EXIT", "EOD")):
            if not hasattr(mod, k):                  # an older (v14) backtester file: bounce-zone only
                setattr(mod, k, v)
        return mod, f"external file: {os.path.basename(path)}"
    except Exception as exc:
        log.exception("external strategy failed to load")
        return here, f"embedded (external file failed: {exc.__class__.__name__})"


def jr_mode():
    """True = the short side is the Jay-read short (SHORT_STRATEGY = "jay_read"); False = the parked v16 short."""
    return str(SHORT_STRATEGY).strip().lower() != "v16"


def jr_ready():
    """Jay-read mode and jay_read_short.py loaded (3.13.0: or Jay-read 2)."""
    return jr_mode() and (JR is not None or JR2 is not None)


def sq_on():
    """3.9.0: the max squeeze short runs next to the Jay-read short."""
    return jr_mode() and bool(SQUEEZE_SHORT) and JR is not None and SQ is not None


def jr2_ready():
    """3.13.0: Jay-read 2 loaded (jay_read_2_short.py) in Jay-read mode."""
    return jr_mode() and JR2 is not None


def jr2_on():
    """3.13.0: Jay-read 2 reads the charts (its trading mode is not Off)."""
    return jr2_ready() and mode("jr2") != "off"


def jrm():
    """3.13.0: the Jay-read module whose rules the screens show: Jay-read 2 when it is on, else Jay-read v1.2."""
    return JR2 if jr2_on() or (JR is None and JR2 is not None) else JR


def jr_label():
    return "Jay-read 2" if jrm() is JR2 and JR2 is not None else "Jay-read"


def jr_source():
    if not jr_mode():
        return None
    if jr2_ready():
        txt = f"Jay-read 2 v{getattr(JR2, '__version__', '?')} ({os.path.basename(getattr(JR2, '__file__', 'jay_read_2_short.py'))})"
        if JR is not None and mode("jr") != "off":
            txt += f" + Jay-read v{getattr(JR, '__version__', '?')}"
        return txt + (" + max squeeze short" if sq_on() else "") + " - v16 bounce-zone + vacuum parked"
    if JR is None:
        return f"Jay-read short NOT LOADED ({JR_IMPORT_ERROR}) - no shorts; v16 parked"
    txt = f"Jay-read short v{getattr(JR, '__version__', '?')} ({os.path.basename(getattr(JR, '__file__', JAY_READ_FILE))})"
    if sq_on():
        txt += f" + max squeeze short ({os.path.basename(getattr(SQ, '__file__', SQUEEZE_FILE))})"
    elif SQUEEZE_SHORT:
        txt += f" - max squeeze short NOT LOADED ({SQ_IMPORT_ERROR})"
    return txt + " - v16 bounce-zone + vacuum parked"


# -----------------------------------------------------------------------------
# 3.10 TRADING MODE per strategy: "trading" = places orders, "alert" = signals to Discord only, "off" = not traded or
# posted. Picked in the app (menu -> Trading mode), saved in settings.json ("modes"), no rebuild needed. The constants
# ALERT_ONLY / SQUEEZE_ALERT_ONLY / LONG_PREMARKET only give the start-up default until a mode is saved.
# -----------------------------------------------------------------------------
MODE_KEYS = ("long", "jr2", "jr", "sq")   # 3.13.0: + jr2 (Jay-read 2)
MODE_VALUES = ("trading", "alert", "off")
MODE_NAMES = {"long": "Premarket long", "jr2": "Jay-read 2 short", "jr": "Jay-read short v1.2", "sq": "Max squeeze short"}
MODE_TEXT = {"trading": "Trading", "alert": "Alert only", "off": "Off"}
MODES = {}                         # the modes picked in the app (saved); a strategy not in it uses its constant


def default_modes():
    jr12 = JR_V12_DEFAULT_MODE if JR_V12_DEFAULT_MODE in MODE_VALUES else ("alert" if ALERT_ONLY else "trading")
    return {"long": "trading" if LONG_PREMARKET else "off", "jr2": "alert" if JR2_ALERT_ONLY else "trading",
            "jr": jr12, "sq": ("alert" if SQUEEZE_ALERT_ONLY else "trading") if SQUEEZE_SHORT else "off"}


def set_modes(saved=None):
    """Load the modes picked in the app (saved = the dict from settings.json; None / {} = the constants' defaults)."""
    MODES.clear()
    saved = dict(saved or {})
    if saved and "jr2" not in saved:                 # 3.13.0: modes saved before Jay-read 2 existed - the old Jay-read
        saved.pop("jr", None)                        # mode is not carried over (v1.2 starts at JR_V12_DEFAULT_MODE)
    for k, v in saved.items():
        if k in MODE_KEYS and v in MODE_VALUES:
            MODES[k] = v
    return {k: mode(k) for k in MODE_KEYS}


def mode(key):
    if key == "long" and not LONG_PREMARKET:
        return "off"
    if key == "jr2" and JR2 is None:
        return "off"
    return MODES.get(key) or default_modes()[key]


def setup_mode(setup):
    """The mode of a short setup ("squeeze" = the max squeeze short, else the Jay-read short)."""
    if str(setup or "").startswith("jr2"):          # 3.13.0: Jay-read 2 (gapper / spiker)
        return mode("jr2")
    return mode("sq" if setup == "squeeze" else "jr")


def modes_text(short=False):
    """'Premarket long: Trading - Jay-read short: Alert only - ...' (Discord, status)."""
    keys = [k for k in MODE_KEYS if (k != "sq" or sq_on() or SQUEEZE_SHORT) and (k != "jr2" or JR2 is not None)]
    if short:
        nm = {"long": "Long", "jr2": "Jay-read 2", "jr": "Jay-read v1.2", "sq": "Squeeze"}
        return "  ·  ".join(f"{nm[k]}: {MODE_TEXT[mode(k)].upper() if mode(k) != 'trading' else 'ON'}" for k in keys)
    return "  ·  ".join(f"{MODE_NAMES[k]}: {MODE_TEXT[mode(k)]}" for k in keys)


def not_trading():
    """The strategies that are NOT placing orders: [(key, mode)]."""
    keys = [k for k in MODE_KEYS if (k != "sq" or sq_on()) and (k != "long" or LONG_PREMARKET)
            and (k != "jr2" or JR2 is not None)]
    return [(k, mode(k)) for k in keys if mode(k) != "trading"]


set_modes()


def strategy_label():
    """3.9.0: the strategies that run (status bar, start-up message)."""
    parts = []
    if LONG_PREMARKET:
        parts.append("Premarket long" if LP is not None else "Premarket long NOT LOADED")
    if not jr_mode():
        parts.append(f"short: {STRATEGY_SOURCE}")
    else:
        if JAY_READ_2:                               # 3.13.0
            parts.append("Jay-read 2" + {"alert": " (alert only)", "off": " (off)"}.get(mode("jr2"), "")
                         if JR2 is not None else "Jay-read 2 NOT LOADED")
        if JR is None:
            parts.append("Jay-read short NOT LOADED")
        elif mode("jr") != "off" or not JAY_READ_2:
            parts.append(f"Jay-read short v{getattr(JR, '__version__', '?')}"
                         + {"alert": " (alert only)", "off": " (off)"}.get(mode("jr"), ""))
        if sq_on():
            parts.append("Max squeeze short" + {"alert": " (alert only)", "off": " (off)"}.get(mode("sq"), ""))
        elif SQUEEZE_SHORT:
            parts.append("Max squeeze short NOT LOADED")
    return " + ".join(parts)


def alert_only_for(setup):
    """3.10: the trading mode of the setup's strategy is "Alert only" (the app's Trading mode menu)."""
    return setup_mode(setup) == "alert"


def off_for(setup):
    """3.10: the setup's strategy is switched Off - its signals are neither traded nor posted."""
    return setup_mode(setup) == "off"


JR_SETUP_NAME = {"rollover": "Jay-read A rollover", "level": "Jay-read B overhead high", "squeeze": "Max squeeze short",
                 "jr2_gap": "JR2 gapper", "jr2_spk": "JR2 spiker"}          # 3.13.0: + Jay-read 2
JR_SETUP_CODE = {"rollover": "JR_A", "level": "JR_B", "squeeze": "SQ", "jr2_gap": "JR2_G", "jr2_spk": "JR2_S"}


def jr_info():
    """The Jay-read rules for the page (signal panel text)."""
    if JR is None:
        return None
    return {"up": JR.MIN_UP_PCT, "dollar": round(JR.MIN_DOLLAR_VOL / 1e6), "age": JR.HOD_MIN_AGE_MIN,
            "crack": JR.MIN_CRACK_PCT, "vwapA": JR.MIN_OVER_VWAP_PCT, "vwapB": JR.LEVEL_MIN_OVER_VWAP_PCT,
            "levelStart": JR.LEVEL_SIGNAL_START, "start": JR.SIGNAL_START, "end": JR.SIGNAL_END, "stop": JR.HOD_STOP_PCT,
            "lockAfter": JR.LOCK_AFTER_PCT, "lockStop": JR.LOCK_STOP_PCT, "eodChart": JR.EOD_COVER_TIME,
            "lockText": JR.lock_text(JR.LOCK_STOP_PCT), "ver": getattr(JR, "__version__", ""),
            "alertOnly": mode("jr") != "trading", "eod": JR_EOD_COVER_TIME,
            "sq": ({"up": SQ.MIN_UP_PCT, "squeeze": SQ.SQUEEZE_PCT, "swing": SQ.SWING_PCT, "near": SQ.NEAR_TOP_PCT,
                    "stop": SQ.STOP_OVER_TOP_PCT, "start": SQ.SIGNAL_START, "end": SQ.SIGNAL_END,
                    "alertOnly": mode("sq") != "trading"} if sq_on() else None),
            "jr2": jr2_info(), "v12": mode("jr") != "off"}


def jr2_info():
    """3.13.0: Jay-read 2's rules for the signal panel (None when it is off / not loaded)."""
    if not jr2_on():
        return None
    g, s = JR2.SETTINGS["GAPPER"], JR2.SETTINGS["SPIKER"]
    return {"ver": getattr(JR2, "__version__", ""), "split": JR2.SETTINGS["GAP_SPLIT_PCT"], "up": g["MIN_UP_PCT"],
            "dollar": round(g["MIN_DOLLAR_VOL"] / 1e6), "age0": g["AGE_MIN"], "age1": g["AGE_MAX"], "crack0": g["CRACK_MIN"],
            "crack1": g["CRACK_MAX"], "r0": round(g["R_MIN"] * 100), "r1": round(g["R_MAX"] * 100), "fresh": g["FRESH"],
            "under": g["UNDER_PCT"], "vwap": g["V_MIN_PCT"], "start": g["SIGNAL_START"], "end": g["SIGNAL_END"],
            "stop": g["STOP_PCT"], "spkFlush": s["FLUSH_VW"], "lockAfter": JR2.LOCK_AFTER_PCT,
            "lockText": JR2.lock_text(JR2.LOCK_STOP_PCT), "eod": JR_EOD_COVER_TIME, "alertOnly": mode("jr2") != "trading"}


def jr2_cfg():
    """3.13.0: Jay-read 2's settings for the live bot (its SETTINGS; the EOD cover from JR_EOD_COVER_TIME)."""
    return JR2.settings(EOD_COVER_TIME=JR_EOD_COVER_TIME)


def jr_cfg():
    """The module's settings for the live bot: the backtested values, the EOD cover from JR_EOD_COVER_TIME."""
    return JR.settings(EOD_COVER_TIME=JR_EOD_COVER_TIME)


def sq_cfg():
    """3.9.0: the max squeeze settings for the live bot: the backtested values, the EOD cover from JR_EOD_COVER_TIME."""
    return SQ.settings(EOD_COVER_TIME=JR_EOD_COVER_TIME)


def make_book(sym, prior, live=True):
    """3.9.0: the short strategies of one symbol for one day - a ShortBook (Jay-read + max squeeze, one position at a
    time; the max squeeze part only when sq_on()), or without max_squeeze_short.py the JayReadShort alone. Both have the
    same API. live=False = the backtest view of the chart (fills from the candles, cover 15:55).
    3.13.0: Jay-read 2 first, then Jay-read v1.2 (only when its mode is not Off), then the max squeeze - all in one
    ShortBook (max_squeeze_short.ShortBook: one short per stock, a stop-out of one ends the stock for all)."""
    if jr2_on():
        parts = [JR2.JayRead2Short(sym, prior, cfg=jr2_cfg() if live else None, simulate_fills=not live)]
        if JR is not None and mode("jr") != "off":
            parts.append(JR.JayReadShort(sym, prior, cfg=jr_cfg() if live else None, simulate_fills=not live))
        if SQ is not None and sq_on() and mode("sq") != "off":
            parts.append(SQ.MaxSqueezeShort(sym, prior, cfg=sq_cfg() if live else None, simulate_fills=not live))
        return JR2.make_book(sym, prior, parts)
    if SQ is not None:
        return SQ.ShortBook(sym, prior, jr_cfg=jr_cfg() if live else None, sq_cfg=sq_cfg() if live else None,
                            simulate_fills=not live, squeeze=sq_on())
    return JR.JayReadShort(sym, prior, cfg=jr_cfg() if live else None, simulate_fills=not live)


def jr_part(book, setup):
    """The strategy object behind a setup (the book's Jay-read or max squeeze part)."""
    return book.part(setup) if hasattr(book, "part") else book


def jr_finished(book):
    """No more short trades today on this stock (stopped out / every strategy at its max trades)."""
    if hasattr(book, "parts"):
        return book.done
    return book.done or len(book.trades) >= book.cfg["MAX_TRADES_PER_DAY"]


def jr_done_note(book, sym):
    """After a close: 'Done for the day on X (...)' or ''."""
    if book is None or not jr_finished(book):
        return ""
    stopped = any(p.done and p._stop_rh is not None for p in getattr(book, "parts", [book]))
    return f"Done for the day on {sym} ({'stopped out' if stopped else 'max trades reached'})."


def jr_part_finished(part):
    """One strategy of the book is done today (stopped out / its max trades)."""
    return part.done or len(part.trades) >= part.cfg["MAX_TRADES_PER_DAY"]


def jr_hm(t):
    try:
        return t.strftime("%H:%M")
    except Exception:
        return str(t)[11:16]


def jr_read_text(s):
    """Jay's read of a signal in one paragraph (Discord, app log, chart note)."""
    if s.get("setup") == "squeeze":                     # 3.9.0: the max squeeze short
        return (f"Stock +{s['up'] * 100:.0f}%, ${s['dollar'] / 1e6:,.0f}M traded. Last swing high it broke (where the "
                f"average short went in) {_fp(s['level'])} at {jr_hm(s['level_time'])}; squeezed "
                f"+{s['squeeze'] * 100:.0f}% over it to {_fp(s['top'])} at {jr_hm(s['top_time'])}. Red candle at the top - "
                f"close {_fp(s['close'])}, VWAP {_fp(s['vwap'])} ({s['vs_vwap'] * 100:+.0f}%). Stop {_fp(s['stop'])} (the "
                f"top +{SQ.STOP_OVER_TOP_PCT:g}%), no lock.")
    if str(s.get("setup") or "").startswith("jr2"):     # 3.13.0: Jay-read 2
        basis = {"hod": "high of day", "rh": "regular-hours high", "bh": "bounce high"}.get(s.get("stop_basis"), "high")
        return (f"{JR_SETUP_NAME.get(s['setup'], 'Jay-read 2')}, {s['kind']}: stock +{s['up'] * 100:.0f}%, "
                f"${s['dollar'] / 1e6:,.0f}M traded. High {_fp(s['rth_high'])} at {jr_hm(s['rth_high_time'])} "
                f"({s['hod_age_min']} min old); flush -{s['crack'] * 100:.0f}% to {_fp(s['crack_low'])} at "
                f"{jr_hm(s['crack_low_time'])}; first bounce to {_fp(s['bounce_high'])} at {jr_hm(s['bounce_high_time'])} "
                f"({s['retrace'] * 100:.0f}% of the flush, no new high). Rejected near the top - close {_fp(s['close'])}, "
                f"VWAP {_fp(s['vwap'])} ({s['vs_vwap'] * 100:+.0f}%). Stop {_fp(s['stop'])} ({basis} "
                f"{_fp(s['hod'] if s.get('stop_basis') == 'hod' else s['rth_high'])} +{s.get('stop_pct', 5):g}%).")
    lvl = s["setup"] == "level"
    return (f"High {_fp(s['rth_high'])} at {jr_hm(s['rth_high_time'])} ({s['hod_age_min']} min old), stock +{s['up'] * 100:.0f}%, "
            f"${s['dollar'] / 1e6:,.0f}M traded. Momentum broke: cracked -{s['crack'] * 100:.0f}% to {_fp(s['crack_low'])} "
            f"at {jr_hm(s['crack_low_time'])}. {'Level (lower high it failed at)' if lvl else 'Overhead high'} "
            f"{_fp(s['ref'])} at {jr_hm(s['ref_time'])} -> drop -{s['drop'] * 100:.0f}% to {_fp(s['low'])}, bounce "
            f"+{s['bounce'] * 100:.0f}% to {_fp(s['bounce_high'])} ({s['retrace'] * 100:.0f}% of the drop, "
            f"{s['reclaim'] * 100:.0f}% of the crack). "
            + ("The bounce hit the level and was rejected" if lvl else "Red candle at the top of the bounce")
            + f" - close {_fp(s['close'])}, VWAP {_fp(s['vwap'])} ({s['vs_vwap'] * 100:+.0f}%). Stop {_fp(s['stop'])} "
              f"(regular-hours high +{JR.HOD_STOP_PCT:g}%).")


def jr_eng_info(frame, has_rth, prior):
    """What the bot shows / needs from the day when the v16 engine is parked: HOD, VWAP, gap, volume (no v16 signals)."""
    n = len(frame)
    out = {"pending": None, "vac": None, "vac_armed": None, "trades": [], "hod": None, "gap": None, "gapOk": False,
           "block": "" if has_rth else "pre-market", "vol": 0.0, "bars": n, "vwap": None, "close": None}
    if not n:
        return out
    tp = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    vv = float(frame["volume"].sum())
    out.update(hod=float(frame["high"].max()), vol=vv, close=float(frame["close"].iloc[-1]),
               vwap=float((tp * frame["volume"]).sum() / vv) if vv > 0 else None)
    if has_rth and prior:
        rth = frame[(frame["time"].dt.hour * 60 + frame["time"].dt.minute >= 570) & (frame["volume"] > 0)]
        if len(rth):
            out["gap"] = (float(rth["open"].iloc[0]) / prior - 1.0) * 100.0
            out["gapOk"] = True                          # no gap rule in the Jay-read short (it needs +150% on the day)
    return out


class K:
    """Session timing taken from the strategy parameters (seconds of the ET day)."""
    rth_s = 9 * 3600 + 30 * 60
    rth_e = 16 * 3600
    eod_s = 15 * 3600 + 55 * 60
    include_pm = True


def _secs(hhmm):
    hh, mm = str(hhmm).split(":")
    return int(hh) * 3600 + int(mm) * 60


def _init_constants():
    K.rth_s = _secs(STRAT.RTH_START)
    K.rth_e = _secs(STRAT.RTH_END)
    K.eod_s = _secs(STRAT.EOD_COVER_TIME)
    K.include_pm = bool(STRAT.VWAP_INCLUDE_PREMARKET)


# -----------------------------------------------------------------------------
# Time / number helpers. Chart time = ET wall-clock seconds, so the chart axis
# reads in New York time on any PC time zone.
# -----------------------------------------------------------------------------
def ctime(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return calendar.timegm(dt.astimezone(ET_TZ).timetuple())


def is_rth(t):
    s = t % 86400
    return K.rth_s <= s < K.rth_e


def day_date(dn):
    return ddate(1970, 1, 1) + timedelta(days=int(dn))


def _f(x, nd=6):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return _f(o)
    if isinstance(o, (datetime, ddate, pd.Timestamp)):
        return str(o)
    return str(o)


def _dumps(obj):
    return json.dumps(obj, separators=(",", ":"), default=_json_default, allow_nan=False)


def _fmt_shares(v):
    v = float(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div:
            return f"{v / div:g}{suf}"
    return f"{v:g}"


def _num(x):
    """Positive finite float, else None (IB uses nan / -1 for 'no value')."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if x != x or math.isinf(x) or x <= 0:
        return None
    return x


def bar_ohlcv(b):
    v = b.volume
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = 0.0
    if not v or v != v or v < 0:
        v = 0.0
    return float(b.open), float(b.high), float(b.low), float(b.close), v


def day_ranges(tc):
    """[(day_number, start, end)] for consecutive bars of the same ET day."""
    out = []
    n = len(tc)
    a = 0
    for i in range(1, n + 1):
        if i == n or tc[i] // 86400 != tc[a] // 86400:
            out.append((tc[a] // 86400, a, i))
            a = i
    return out



def history_rows(st):
    rows = []
    for dn, a, b in day_ranges(st.tc):
        pv = vv = 0.0
        started = K.include_pm
        for i in range(a, b):
            t = st.tc[i]
            o, h, l, c, v = bar_ohlcv(st.bars[i])
            r = is_rth(t)
            if not started and r:
                started = True
            if started:
                pv += (h + l + c) / 3.0 * v
                vv += v
            rows.append([t, _f(o), _f(h), _f(l), _f(c), _f(v, 2), 1 if r else 0, _f(pv / vv) if vv > 0 else None])
    return rows


def bar_row(st, i):
    """Row for bar i with the day's VWAP up to that bar (same formula as the engine)."""
    t = st.tc[i]
    dn = t // 86400
    a = i
    while a > 0 and st.tc[a - 1] // 86400 == dn:
        a -= 1
    pv = vv = 0.0
    started = K.include_pm
    for j in range(a, i + 1):
        o, h, l, c, v = bar_ohlcv(st.bars[j])
        if not started and is_rth(st.tc[j]):
            started = True
        if started:
            pv += (h + l + c) / 3.0 * v
            vv += v
    o, h, l, c, v = bar_ohlcv(st.bars[i])
    return [t, _f(o), _f(h), _f(l), _f(c), _f(v, 2), 1 if is_rth(t) else 0, _f(pv / vv) if vv > 0 else None]


def recalc_today(st):
    """Running sums over the closed candles of the latest day (all but the last bar)."""
    n = len(st.tc)
    if n == 0:
        st.tcum = None
        return
    dn = st.tc[-1] // 86400
    a = n - 1
    while a > 0 and st.tc[a - 1] // 86400 == dn:
        a -= 1
    pv = vv = vol = 0.0
    hod = -math.inf
    started = K.include_pm
    rth_open = None
    for i in range(a, n - 1):
        o, h, l, c, v = bar_ohlcv(st.bars[i])
        if rth_open is None and is_rth(st.tc[i]):
            rth_open = o
        if not started and is_rth(st.tc[i]):
            started = True
        if started:
            pv += (h + l + c) / 3.0 * v
            vv += v
        vol += v
        hod = max(hod, h)
    st.tcum = {"day": dn, "pv": pv, "vv": vv, "started": started, "vol": vol, "hod": hod, "rth_open": rth_open}


def _live_base(st):
    """Closed-candle sums for the live candle's day (adds IB's last bar if the
    live candle is a newer, tick-built one)."""
    t = st.live[0]
    dn = t // 86400
    cm = st.tcum
    if cm is not None and cm["day"] == dn:
        pv, vv, started, vol, hod = cm["pv"], cm["vv"], cm["started"], cm["vol"], cm["hod"]
    else:
        pv = vv = vol = 0.0
        started, hod = K.include_pm, -math.inf
    if st.tc and t > st.tc[-1] and st.tc[-1] // 86400 == dn:
        o, h, l, c, v = bar_ohlcv(st.bars[-1])
        if not started and is_rth(st.tc[-1]):
            started = True
        if started:
            pv += (h + l + c) / 3.0 * v
            vv += v
        vol += v
        hod = max(hod, h)
    return pv, vv, started, vol, hod


def live_row(st):
    t, o, h, l, c, v = st.live
    pv, vv, started, _, _ = _live_base(st)
    r = is_rth(t)
    if not started and r:
        started = True
    if started:
        pv += (h + l + c) / 3.0 * v
        vv += v
    return [t, _f(o), _f(h), _f(l), _f(c), _f(v, 2), 1 if r else 0, _f(pv / vv) if vv > 0 else None]


def make_quote(st):
    t, o, h, l, c, v = st.live
    pv, vv, started, vol, hod = _live_base(st)
    if started or is_rth(t):
        pv += (h + l + c) / 3.0 * v
        vv += v
    hod = max(hod, h)
    vol += v
    prior = prior_for(st, t // 86400)
    up = (c / prior - 1.0) * 100.0 if prior else None
    off = (hod - c) / hod * 100.0 if hod > 0 else None
    cm = st.tcum
    ro = cm.get("rth_open") if cm is not None and cm.get("day") == t // 86400 else None
    if ro is None and is_rth(t):
        ro = o                                   # the live candle is the first regular-hours candle
    gap = (ro / prior - 1.0) * 100.0 if (ro and prior) else None
    return {
        "last": _f(c), "prior": _f(prior), "chg": _f(c - prior) if prior else None, "up": _f(up, 2),
        "hod": _f(hod), "off": _f(off, 2), "vwap": _f(pv / vv) if vv > 0 else None, "vol": _f(vol, 0),
        "volOk": (bool(vol >= STRAT.MIN_DAY_VOLUME) if getattr(STRAT, "MIN_DAY_VOLUME", 0) else None),
        "gap": _f(gap, 2), "gapOk": (bool(gap >= STRAT.MIN_GAP_PCT) if gap is not None else None),
        "inZone": bool(off is not None and STRAT.ZONE_NEAR_PCT <= off <= STRAT.ZONE_FAR_PCT),
        "halted": bool(getattr(st, "halted", False)),
        "bid": _f((getattr(st, "ba", None) or (None, None))[0]), "ask": _f((getattr(st, "ba", None) or (None, None))[1]),
    }


# -----------------------------------------------------------------------------
# Strategy runs (pure functions; the engine itself is untouched)
# -----------------------------------------------------------------------------
def make_frame(st, a, b):
    rows = st.bars[a:b]
    times = pd.to_datetime(np.asarray(st.tc[a:b], dtype="int64"), unit="s").tz_localize(STRAT.ET)
    o, h, l, c, v = zip(*(bar_ohlcv(x) for x in rows))
    return pd.DataFrame({"time": times, "open": o, "high": h, "low": l, "close": c, "volume": v})


def session_live(now_et, dn):
    """True while day dn is today and the strategy's EOD cover time has not passed."""
    if now_et.date() != day_date(dn):
        return False
    return now_et.hour * 3600 + now_et.minute * 60 + now_et.second < K.eod_s


def build_jobs(st, now_et):
    ranges = day_ranges(st.tc)
    if not ranges:
        return []
    latest = ranges[-1][0]
    jobs = []
    for dn, a, b in ranges:
        if dn != latest:
            cached = st.day_cache.get(dn)
            if cached is not None and cached[0] == b - a:
                continue
        jobs.append({"sym": st.sym, "day": dn, "date": day_date(dn), "df": make_frame(st, a, b),
                     "tc": list(st.tc[a:b]), "prior": prior_for(st, dn),
                     "live": dn == latest and session_live(now_et, dn), "latest": dn == latest})
    return jobs


EXIT_COLORS = {"Stop": "#f23645", "EOD": "#9598a1", "VWAP": "#089981"}


def _ts_epoch(ts):
    try:
        return calendar.timegm(ts.timetuple())
    except Exception:
        return None


def summarize(bt, job):
    tc = job["tc"]
    n = len(tc)
    live = job["live"]
    scr = STRAT.SCRATCH_R
    trades, markers = [], []
    for tr in bt.trades:
        ei, xi, pi = tr["entry_idx"], tr["exit_idx"], tr["partial_idx"]
        # the engine force-closes any open trade at the last bar it is given;
        # during the live session that is the forming candle, so the trade is still open
        is_open = live and tr["exit_reason"] == "EOD" and (tc[xi] % 86400) < K.eod_s
        shares = max(1, int(tr["shares"]))
        pshares = max(0, min(shares - 1, int(round(shares * STRAT.PARTIAL_PCT)))) if pi >= 0 else 0
        stop_now = tr["stop_path"][-1][1] if tr["stop_path"] else tr["stop"]
        item = {
            "day": job["day"], "n": tr["n"], "setup": tr["setup"], "note": tr["note"],
            "t": tc[ei], "sigT": _ts_epoch(tr["signal_time"]),
            "entry": _f(tr["entry"]), "stop": _f(tr["stop"]), "stopNow": _f(stop_now), "risk": _f(tr["risk_pct"], 2),
            "t1": _f(tr["t1"]), "t1k": tr["t1_kind"], "t2": _f(tr["t2"]),
            "pT": tc[pi] if pi >= 0 else None, "pPx": _f(tr["partial_px"]) if pi >= 0 else None,
            "xT": None if is_open else tc[xi], "xPx": None if is_open else _f(tr["exit"]),
            "reason": "OPEN" if is_open else tr["exit_reason"], "R": _f(tr.get("R_net", tr["R"]), 3), "open": bool(is_open),
            "pfrac": pshares / shares, "grade": tr.get("grade", ""), "leg": tr.get("leg"),
            "net": _f(tr.get("pnl_pct_net"), 2), "fee": tr.get("fee_pct", 0.0),
            "top": _f(tr.get("top")), "dip": _f(tr.get("dip_pct"), 1), "zv": _f(tr.get("zone_vs_vwap_pct"), 1),
        }
        trades.append(item)
        markers.append({"time": tc[ei], "position": "aboveBar", "color": "#f23645", "shape": "arrowDown",
                        "text": f"S{tr['n']} {tr['setup']}" + (f" {tr['grade']}" if tr.get("grade") else "")})
        if pi >= 0:
            markers.append({"time": tc[pi], "position": "belowBar", "color": "#089981", "shape": "arrowUp",
                            "text": "T1"})
        if not is_open:
            base = tr["exit_reason"].replace(" (gap)", "")
            markers.append({"time": tc[xi], "position": "belowBar", "color": EXIT_COLORS.get(base, "#9598a1"),
                            "shape": "arrowUp", "text": f"{tr['exit_reason']} {tr.get('R_net', tr['R']):+.2f}R"})
    skips, skip_markers = [], []
    for s in bt.skipped:
        i = s["idx"]
        if live and i >= n - 1:
            continue                       # decided on the forming candle - not final yet
        skips.append({"t": tc[i], "setup": s["setup"], "reason": s["reason"], "px": _f(s["price"])})
        skip_markers.append({"time": tc[i], "position": "aboveBar", "color": "rgba(149,152,161,0.85)",
                             "shape": "circle", "text": "", "size": 0.6})
    rs = [t["R"] or 0.0 for t in trades if not t["open"]]
    gap = getattr(bt, "gap_pct", float("nan"))
    stats = {"trades": len(trades), "wins": sum(1 for r in rs if r >= scr),
             "losses": sum(1 for r in rs if r <= -scr), "R": _f(sum(rs), 2), "open": sum(1 for t in trades if t["open"]),
             "gap": _f(gap, 1) if gap == gap else None, "gapOk": bool(getattr(bt, "gap_ok", False))}
    # bounce zone: the short limit resting for the next / forming candle (live only)
    armed = None
    pend = getattr(bt, "pending", None)
    if live and pend is not None and "trigger" in pend and 0 <= pend["idx"] < n:
        armed = {"t": tc[pend["idx"]], "setup": pend["sig"].setup, "trigger": _f(pend["trigger"]),
                 "zoneHi": _f(pend.get("zone_hi")), "stop": _f(pend["sig"].stop), "top": _f(pend.get("top")),
                 "dip": _f(pend.get("dip_pct"), 1), "ext": _f(pend.get("ext"), 1)}
    stats["armed"] = armed
    levels = []
    if job["latest"] and SHOW_DAY_LEVELS:
        if bt.hod and bt.hod > 0 and not math.isinf(bt.hod):
            levels.append({"price": _f(bt.hod), "color": "#9598a1", "style": "dot", "title": "HOD"})
        if bt.pm_high == bt.pm_high and bt.hod and abs(bt.pm_high - bt.hod) / bt.hod > 0.01:
            levels.append({"price": _f(bt.pm_high), "color": "#2962ff", "style": "dash", "title": "PM high"})
        if job["prior"]:
            levels.append({"price": _f(job["prior"]), "color": "#5d606b", "style": "dot", "title": "Prev close"})
    if job["latest"]:
        if armed:
            levels.append({"price": armed["zoneHi"], "color": "#ce93d8", "style": "dot", "title": "Zone 10%"})
            levels.append({"price": armed["trigger"], "color": "#ff9800", "style": "dash", "title": "Short limit 12%"})
            levels.append({"price": armed["stop"], "color": "#f23645", "style": "dot", "title": "Stop if filled"})
        if live and getattr(bt, "vac_armed", False) and getattr(bt, "vac_peak_idx", -1) >= 0:
            levels.append({"price": _f(bt.vac_peak), "color": "#e040fb", "style": "dot", "title": "Vacuum peak"})
            levels.append({"price": _f(bt.vac_peak * (1 - STRAT.VAC_PULLBACK_PCT / 100.0)), "color": "#e040fb",
                           "style": "dash", "title": "Vacuum: short below"})
        for t in trades:
            if t["open"]:
                levels.append({"price": t["entry"], "color": "#d1d4dc", "style": "solid", "title": f"S{t['n']} entry"})
                levels.append({"price": t["stopNow"], "color": "#f23645", "style": "dash", "title": "Stop"})
                levels.append({"price": t["top"], "color": "#9598a1", "style": "dot", "title": "Top"})
                levels.append({"price": t["t1"], "color": "#089981", "style": "dot",
                               "title": "VWAP at entry" if t["setup"] == "VACUUM" else "Dip low (guide)"})
    return {"day": job["day"], "n": n, "live": live, "latest": job["latest"], "trades": trades,
            "markers": markers, "skips": skips, "skip_markers": skip_markers, "levels": levels, "stats": stats}


JR_EXIT_NAME = {"STOP": "Stop", "LOCK": "Lock", "EOD": "EOD", "END": "EOD"}


def summarize_jr(job):
    """The chart overlay in Jay-read mode: the module in backtest mode (fills at the next open, stop / lock / 15:55 from
    the candles) on the day's closed candles - the same view as the backtester. Same output shape as summarize()."""
    tc, df, live = job["tc"], job["df"], job["live"]
    n = len(tc)
    scr = STRAT.SCRATCH_R
    trades, markers, skips, skip_markers, levels = [], [], [], [], []
    stats = {"trades": 0, "wins": 0, "losses": 0, "R": 0.0, "open": 0, "gap": None, "gapOk": False, "armed": None,
             "up": None, "dollar": None, "jr": JR is not None}
    prior = job["prior"]
    if (JR is None and JR2 is None) or not prior or not n:
        return {"day": job["day"], "n": n, "live": live, "latest": job["latest"], "trades": trades, "markers": markers,
                "skips": skips, "skip_markers": skip_markers, "levels": levels, "stats": stats}
    s = make_book(job["sym"], prior, live=False)            # 3.9.0: Jay-read + max squeeze, backtested settings
    use = n - 1 if live else n                              # live: the last candle is still forming
    o, h, l, c, v = (df[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    times = df["time"]
    idx = []                                                # module candle k -> row of the day
    for i in range(use):
        if not v[i] > 0:
            continue
        idx.append(i)
        for e in s.on_bar(times.iloc[i], o[i], h[i], l[i], c[i], v[i]):
            if e["type"] == "SKIP" and not (live and i >= use - 1):
                g = e["signal"]
                skips.append({"t": tc[i], "setup": JR_SETUP_NAME.get(g["setup"], g["setup"]), "reason": e["reason"],
                              "px": _f(g["close"])})
                skip_markers.append({"time": tc[i], "position": "aboveBar", "color": "rgba(149,152,161,0.85)",
                                     "shape": "circle", "text": "", "size": 0.6})
    if not live:
        s.finish()
    for num, tr in enumerate(s.trades, 1):
        g = tr.signal
        ei = idx[tr.k0] if tr.k0 < len(idx) else idx[-1]
        is_open = not tr.closed
        xi = idx[min(tr.k_end, len(idx) - 1)] if tr.closed else None
        risk = tr.stop0 - tr.entry
        ret = tr.ret if tr.closed else None
        R = ret * tr.entry / risk if (ret is not None and risk > 0) else 0.0
        reason = JR_EXIT_NAME.get(tr.reason, tr.reason) if tr.closed else "OPEN"
        code = {"level": "B", "rollover": "A"}.get(g["setup"], "SQ")
        name = ("Max squeeze" if g["setup"] == "squeeze" else JR_SETUP_NAME[g["setup"]]
                if str(g["setup"]).startswith("jr2") else "Jay-read " + code)
        item = {"day": job["day"], "n": num, "setup": name, "note": jr_read_text(g), "t": tc[ei],
                "sigT": tc[idx[g["k"]]] if g["k"] < len(idx) else None, "entry": _f(tr.entry), "stop": _f(tr.stop0),
                "stopNow": _f(tr.stop), "risk": _f(risk / tr.entry * 100.0, 2),
                "t1": _f(g["level"] if g["setup"] == "squeeze" else g["crack_low"]),
                "t1k": "LEVEL" if g["setup"] == "squeeze" else "CRACK",
                "t2": None, "pT": None, "pPx": None, "xT": tc[xi] if xi is not None else None,
                "xPx": _f(tr.legs[-1][1]) if tr.closed else None, "reason": reason, "R": _f(R, 3), "open": is_open,
                "pfrac": 0.0, "grade": "", "leg": None, "net": _f(ret * 100.0, 2) if ret is not None else None,
                "fee": float(JR.LOCATE_FEE_PCT), "top": _f(g["rth_high"]),
                "dip": _f((g["squeeze"] if g["setup"] == "squeeze" else g["crack"]) * 100.0, 1),
                "zv": _f(g["vs_vwap"] * 100.0, 1)}
        trades.append(item)
        markers.append({"time": tc[ei], "position": "aboveBar", "color": "#e040fb", "shape": "arrowDown",
                        "text": f"S{num} {code}"})
        if xi is not None:
            markers.append({"time": tc[xi], "position": "belowBar",
                            "color": {"Stop": "#f23645", "Lock": "#22d3ee"}.get(reason, "#9598a1"), "shape": "arrowUp",
                            "text": f"{reason} {R:+.2f}R"})
    rs = [t["R"] or 0.0 for t in trades if not t["open"]]
    rd = s.reader
    up = rd.hod / rd.pc - 1.0 if rd.pc else None
    gap = None
    if rd.i0 is not None:
        gap = (rd.o[rd.i0] / rd.pc - 1.0) * 100.0
    stats.update(trades=len(trades), wins=sum(1 for r in rs if r >= scr), losses=sum(1 for r in rs if r <= -scr),
                 R=_f(sum(rs), 2), open=sum(1 for t in trades if t["open"]), gap=_f(gap, 1),
                 gapOk=bool(up is not None and up * 100.0 >= jrm().MIN_UP_PCT), up=_f(up * 100.0 if up is not None else None, 1),
                 dollar=_f(rd.dollar, 0))
    if job["latest"]:
        if job["prior"] and SHOW_DAY_LEVELS:
            levels.append({"price": _f(job["prior"]), "color": "#5d606b", "style": "dot", "title": "Prev close"})
        # 3.10: no RTH-high / "stop if short" lines on the chart (the high of day is a small label at its candle);
        # only an open trade's stop is drawn
        if SHOW_DAY_LEVELS and rd.i0 is not None and rd.rh > 0 and not math.isinf(rd.rh):
            levels.append({"price": _f(rd.rh), "color": "#9598a1", "style": "dot", "title": "RTH high"})
            sref = rd.hod if jrm() is JR2 and JR2 is not None else rd.rh      # 3.13.0: Jay-read 2 = high of day +5%
            levels.append({"price": _f(sref * (1 + jrm().HOD_STOP_PCT / 100.0)), "color": "#f23645", "style": "dot",
                           "title": "Stop if short"})
        for t in trades:
            if t["open"]:
                levels.append({"price": t["stopNow"], "color": "#f23645", "style": "dash",
                               "title": "Lock stop" if t["stopNow"] != t["stop"] else "Stop"})
    return {"day": job["day"], "n": n, "live": live, "latest": job["latest"], "trades": trades,
            "markers": markers, "skips": skips, "skip_markers": skip_markers, "levels": levels, "stats": stats}


def run_jobs(jobs):
    if jr_mode():                               # 3.7.0: the Jay-read short (the v16 engine is parked)
        return [summarize_jr(job) for job in jobs]
    out = []
    for job in jobs:
        bt = STRAT.Backtest(job["sym"], job["date"], job["df"], job["prior"])
        if any(is_rth(t) for t in job["tc"]):
            bt.run()
        else:                                   # pre-market only so far: no signals possible yet
            bt.hod = float(job["df"]["high"].max())
        out.append(summarize(bt, job))
    return out


# -----------------------------------------------------------------------------
# Chart library (TradingView lightweight-charts, Apache-2.0) - cached locally
# -----------------------------------------------------------------------------
def load_chart_lib():
    name = f"lightweight-charts-{LWC_VERSION}.js"
    places = [os.path.join(DATA_DIR, name), os.path.join(_base_dir(), name)]
    if getattr(sys, "_MEIPASS", None):
        places.append(os.path.join(sys._MEIPASS, name))
    for p in places:
        try:
            if os.path.exists(p) and os.path.getsize(p) > 50_000:
                with open(p, encoding="utf-8") as fh:
                    return fh.read()
        except OSError:
            pass
    for url in (f"https://cdn.jsdelivr.net/npm/lightweight-charts@{LWC_VERSION}/dist/lightweight-charts.standalone.production.js",
                f"https://unpkg.com/lightweight-charts@{LWC_VERSION}/dist/lightweight-charts.standalone.production.js"):
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read().decode("utf-8")
            if "createChart" in data and len(data) > 50_000:
                with open(places[0], "w", encoding="utf-8") as fh:
                    fh.write(data)
                log.info("chart library downloaded from %s", url)
                return data
        except Exception as exc:
            log.warning("chart library download failed (%s): %s", url, exc)
    return None


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
class Settings:
    KEYS = ("ext", "skipped", "sound", "panel", "orders", "ordall", "olong")
    TIMEFRAMES = ("1", "2", "5", "15", "30", "D")
    SIZES = {"side": (0.15, 0.55), "scanh": (0.12, 0.88), "ordh": (0.10, 0.70), "newsw": (0.15, 0.75),   # right column / bot panel / orders panel
             "wside": (0.12, 0.45)}                                                # 3.11: the watchlist (left) column

    def __init__(self):
        self.path = os.path.join(DATA_DIR, "settings.json")
        self.lock = threading.Lock()
        self.data = {"ext": EXTENDED_HOURS_DEFAULT, "skipped": SHOW_SKIPPED_DEFAULT, "sound": SOUND_ALERTS_DEFAULT,
                     "panel": True, "side": 0.32, "scanh": 0.55, "tf": DEFAULT_TIMEFRAME, "recent": [], "last_symbol": "", "watchlist": [],
                     "orders": True, "ordall": False, "ordh": 0.28}
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.data.update(json.load(fh))
        except (OSError, ValueError):
            pass
        self._cloud_load()

    # 3.14: Turso is the home of the settings (favorites, watchlist, layout, hotkeys, colors, modes ...), one row per key.
    # settings.json stays only as the offline copy: used when the database cannot be reached at start-up.
    LOCAL_ONLY = ("alerts",)                    # price alerts live only while the app runs

    def _cloud(self):
        try:
            import turso
            return turso.cloud()
        except Exception:
            return None

    def _cloud_load(self):
        c = self._cloud()
        if c is None:
            return
        try:
            remote = c.kv_all("settings")
            if remote:
                self.data.update({k: v for k, v in remote.items() if k not in self.LOCAL_ONLY})
            else:                                # first run with the database: upload what this PC has
                for k, v in self.data.items():
                    if k not in self.LOCAL_ONLY:
                        c.kv_put("settings", k, v)
                log.info("settings uploaded to Turso (%d keys)", len(self.data))
            self._cloud_background()
        except Exception as exc:
            log.warning("Turso settings not loaded (%s) - using this PC's copy", exc)

    def _cloud_background(self):
        """Once, off the main thread: carry this PC's journal history into Turso and bring the vault replica up to date."""
        def go():
            try:
                import turso
                c = turso.cloud()
                if c is None:
                    return
                for name in ("bot_trades.csv", "long_bot_trades.csv", "long_stop_slippage.csv"):
                    n = turso.journal_backfill(os.path.join(DATA_DIR, name), name)
                    if n:
                        log.info("journal %s: %d rows uploaded to Turso", name, n)
                import lh_backtest
                import turso_vault
                vp = lh_backtest.settings().get("vault") or turso_vault.default_replica()
                nd, nh = turso_vault.pull(vp, lambda m: log.info("vault sync: %s", m))
                if nd or nh:
                    log.info("vault replica %s: %d ticker-days, %d histories pulled from Turso", vp, nd, nh)
            except Exception as exc:
                log.warning("Turso background sync: %s", exc)
        threading.Thread(target=go, daemon=True, name="turso-sync").start()

    def _push(self, key):
        if key in self.LOCAL_ONLY:
            return
        c = self._cloud()
        if c is not None:
            c.kv_put_bg("settings", key, self.data.get(key))

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    def set(self, key, value):
        with self.lock:
            self.data[key] = value
            self._save()
            self._push(key)

    def add_recent(self, sym):
        with self.lock:
            rec = [s for s in self.data.get("recent", []) if s != sym]
            self.data["recent"] = ([sym] + rec)[:12]
            self._save()
            self._push("recent")

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("could not save settings")



class PriceAlerts:
    """3.11: price alerts (Alt + click on the chart, or the Alerts tab). One-shot: fires once when the price crosses
    it, then it is removed. Checked on the chart symbol's and the watchlist's live prices. Saved in settings.json."""

    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.Lock()
        # 3.12.1: alerts live only while the app runs - none are carried over from an earlier run (or a crash)
        self.items = []
        if settings.get("alerts"):
            settings.set("alerts", [])

    def clear(self):
        """3.12.1: the app is closing - every alert is deleted."""
        with self.lock:
            self.items = []
            self._save()

    def _save(self):
        self.settings.set("alerts", list(self.items))

    def add(self, sym, px, last=None, direction=None):
        px = float(px)
        up = (direction == "up") if direction in ("up", "down") else (True if not last else px >= float(last))
        a = {"id": f"{int(time.time() * 1000) % 10**10:x}{len(self.items)}", "sym": sym, "px": round(px, 4),
             "dir": "up" if up else "down", "t": datetime.now(ET_TZ).strftime("%m-%d %H:%M")}
        with self.lock:
            self.items = [x for x in self.items if not (x["sym"] == sym and abs(x["px"] - a["px"]) < 1e-9)] + [a]
            self.items = self.items[-60:]
            self._save()
        return a

    def remove(self, aid):
        with self.lock:
            n = len(self.items)
            self.items = [x for x in self.items if x.get("id") != aid]
            if len(self.items) != n:
                self._save()
        return len(self.items) != n

    def check(self, sym, px):
        if not self.items or not px:
            return []
        fired = []
        with self.lock:
            keep = []
            for a in self.items:
                if a["sym"] == sym and ((a["dir"] == "up" and px >= a["px"]) or (a["dir"] == "down" and px <= a["px"])):
                    fired.append(a)
                else:
                    keep.append(a)
            if fired:
                self.items = keep
                self._save()
        return fired

    def list(self):
        with self.lock:
            return list(self.items)


def _jfloat(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


def _journal_rows(d, name):
    """3.14: the rows of a journal: this PC's CSV plus the rows Turso has from every other PC (no duplicates)."""
    import csv as _csv
    rows = []
    try:
        with open(os.path.join(d, name), encoding="utf-8", newline="") as fh:
            rows = [r for r in _csv.DictReader(fh)]
    except OSError:
        pass
    try:
        import turso
        far = turso.journal_rows(name)
        if far:
            skip = turso.JOURNAL_SKIP
            seen = {turso._rk({k: ("" if v is None else str(v)) for k, v in r.items() if k not in skip and k is not None})
                    for r in rows}
            rows += [r for r in far if turso._rk(r) not in seen]
    except Exception:
        pass
    return rows


def journal_trades(data_dir=None):
    """3.11: every closed trade from the bot's journals: bot_trades.csv (shorts) + long_bot_trades.csv (premarket long,
    one row per closed trade = its last leg). Never the account column."""
    import csv as _csv
    d = data_dir or DATA_DIR
    out = []
    try:
        if True:
            for r0 in _journal_rows(d, "bot_trades.csv"):
                code = str(r0.get("setup") or "")
                out.append({"d": str(r0.get("date") or ""), "sym": str(r0.get("symbol") or ""), "side": "Short",
                            "strat": "sq" if code == "SQ" else "jr2" if code.startswith("JR2") else "jr" if code.startswith("JR") else "v16",
                            "setup": SETUP_NAME.get(code, code), "qty": int(_jfloat(r0.get("shares"))),
                            "entry": _jfloat(r0.get("entry_avg")), "exit": _jfloat(r0.get("exit_avg")),
                            "tin": str(r0.get("entry_time") or "")[:5], "tout": str(r0.get("exit_time") or "")[:5],
                            "net": round(_jfloat(r0.get("pnl_net")), 2), "R": _jfloat(r0.get("R_net")),
                            "res": str(r0.get("exit_reason") or ""), "loc": _jfloat(r0.get("locate_cost"))})
    except OSError:
        pass
    try:
        if True:
            for r0 in _journal_rows(d, "long_bot_trades.csv"):
                if str(r0.get("trade_pnl") or "").strip() == "":
                    continue                             # a partial leg - the trade's last leg carries its P&L
                res = str(r0.get("result") or "")
                setup = str(r0.get("setup") or "")
                out.append({"d": str(r0.get("date") or ""), "sym": str(r0.get("symbol") or ""), "side": "Long",
                            "strat": "long", "setup": "Momentum" if "MOMENTUM" in setup else "Bull flag" if "FLAG" in setup
                            else (setup or "Premarket long"), "qty": int(_jfloat(r0.get("shares"))),
                            "entry": _jfloat(r0.get("entry")), "exit": _jfloat(r0.get("exit")),
                            "tin": str(r0.get("entry_time") or "")[:5], "tout": str(r0.get("exit_time") or "")[:5],
                            "net": round(_jfloat(r0.get("trade_pnl")), 2), "R": None, "res": res, "loc": 0.0})
    except OSError:
        pass
    out.sort(key=lambda x: (x["d"], x["tin"]))
    return out


def tz_round_trips(fills, file_rows=None):
    """3.13: TradeZero fills (Buy / Sell) -> closed trades per symbol and day, in the Journal's row format.
    A position that opens with a Sell is a short, with a Buy a long; the trade closes when the position is flat again.
    Net = TradeZero's net proceeds (fees in). Strategy / setup / locate / R come from the bot's journal row of the same
    day, symbol and side (entry within 2%); a trade the bot never booked shows as "Manual / other"."""
    by = {}
    for f in fills or []:
        sym = str(f.get("symbol") or "").upper()
        d = str(f.get("tradeDate") or "")[:10]
        side = str(f.get("side") or "")
        qty = abs(_jfloat(f.get("qty")))
        if not sym or not d or qty <= 0 or side not in ("Buy", "Sell"):
            continue
        by.setdefault((d, sym), []).append((str(f.get("execTime") or ""), side, qty, _jfloat(f.get("price")),
                                            _jfloat(f.get("netProceeds"))))
    out = []
    for (d, sym), fl in sorted(by.items()):
        fl.sort(key=lambda x: x[0])
        pos, cur = 0.0, None
        for t, side, qty, px, net in fl:
            sgn = 1 if side == "Buy" else -1
            if cur is None:
                cur = {"d": d, "sym": sym, "side": "Long" if sgn > 0 else "Short", "tin": t[:5], "qty": 0.0, "cost": 0.0,
                       "xq": 0.0, "xcost": 0.0, "net": 0.0, "tout": ""}
            opening = (sgn > 0) == (cur["side"] == "Long")
            if opening:
                cur["qty"] += qty
                cur["cost"] += qty * px
            else:
                cur["xq"] += qty
                cur["xcost"] += qty * px
                cur["tout"] = t[:5]
            cur["net"] += net
            pos += sgn * qty
            if abs(pos) < 1e-6:
                out.append(cur)
                cur, pos = None, 0.0
    rows = []
    fr = list(file_rows or [])
    for c in out:
        entry = c["cost"] / c["qty"] if c["qty"] else 0.0
        exitp = c["xcost"] / c["xq"] if c["xq"] else 0.0
        m = None
        for r0 in fr:
            if r0["d"] == c["d"] and r0["sym"] == c["sym"] and r0["side"] == c["side"] and entry > 0 \
                    and abs(r0["entry"] / entry - 1) <= 0.02:
                m = r0
                break
        if m is not None:
            fr.remove(m)
        loc = m["loc"] if m else 0.0
        rows.append({"d": c["d"], "sym": c["sym"], "side": c["side"], "strat": m["strat"] if m else "manual",
                     "setup": m["setup"] if m else "Manual / other", "qty": int(round(c["qty"])),
                     "entry": round(entry, 4), "exit": round(exitp, 4), "tin": c["tin"], "tout": c["tout"],
                     "net": round(c["net"] - loc, 2), "R": m["R"] if m else None,
                     "res": (m["res"] if m else "TradeZero fill"), "loc": loc, "src": "tz"})
    rows.sort(key=lambda x: (x["d"], x["tin"]))
    return rows


def journal_data(rng="month", month="", today=None, data_dir=None, tz_fills=None):
    """3.11 Journal screen: totals, P&L calendar, equity, per strategy and the trades of today / week / month / all."""
    import csv as _csv
    today = today or datetime.now(ET_TZ).date()
    rng = rng if rng in ("today", "week", "month", "all") else "month"
    start = {"today": today, "week": today - timedelta(days=today.weekday()), "month": today.replace(day=1),
             "all": ddate(2000, 1, 1)}[rng]
    allt = journal_trades(data_dir)
    source = "file"
    if tz_fills:                                         # 3.13: TradeZero is the source when it returns fills
        tz_rows = tz_round_trips(tz_fills, allt)
        if tz_rows:
            lo = min(t["d"] for t in tz_rows)
            allt = tz_rows + [t for t in allt if t["d"] < lo]   # older days TradeZero did not send: from the files
            allt.sort(key=lambda x: (x["d"], x["tin"]))
            source = "tz"
    tr = [t for t in allt if str(start) <= t["d"] <= str(today)]
    nets = [t["net"] for t in tr]
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    eq, cum, peak, mdd = [], 0.0, 0.0, 0.0
    for t in tr:
        cum += t["net"]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
        eq.append(round(cum, 2))
    by_day = {}
    for t in allt:
        by_day.setdefault(t["d"], [0.0, 0])
        by_day[t["d"]][0] += t["net"]
        by_day[t["d"]][1] += 1
    try:
        y, m = (int(x) for x in str(month).split("-")[:2])
        first = ddate(y, m, 1)
    except (TypeError, ValueError):
        first = today.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    cal, d = [], first
    while d < nxt:
        if d.weekday() < 5:
            v = by_day.get(str(d))
            cal.append({"d": d.day, "wd": d.weekday(), "pnl": round(v[0], 2) if v else None, "n": v[1] if v else 0,
                        "today": d == today})
        d += timedelta(days=1)
    strat = []
    for k, nm in (("jr2", "Jay-read 2 short"), ("jr", "Jay-read short v1.2"), ("sq", "Max squeeze short"), ("long", "Premarket long")):
        g = [t for t in tr if t["strat"] == k]
        if k == "sq" and not g and not sq_on():          # 3.14: the max squeeze is not in the bot - no empty row
            continue
        gw = [t for t in g if t["net"] > 0]
        strat.append({"k": k, "name": nm, "n": len(g), "win": round(100.0 * len(gw) / len(g)) if g else None,
                      "net": round(sum(t["net"] for t in g), 2), "avg": round(sum(t["net"] for t in g) / len(g), 2) if g else None,
                      "bt": BT_REF.get(k)})
    slip = []
    try:
        with open(os.path.join(data_dir or DATA_DIR, "long_stop_slippage.csv"), encoding="utf-8", newline="") as fh:
            for r0 in _csv.DictReader(fh):
                if str(start) <= str(r0.get("date") or "") <= str(today):
                    slip.append(_jfloat(r0.get("slip_vs_trigger_pct")))
    except OSError:
        pass
    days_traded = sorted({t["d"] for t in tr})
    dn = [by_day[x][0] for x in days_traded]
    return {"range": rng, "from": str(start), "to": str(today), "n": len(tr), "source": source,
            "shorts": sum(1 for t in tr if t["side"] == "Short"), "longs": sum(1 for t in tr if t["side"] == "Long"),
            "net": round(sum(nets), 2), "win": round(100.0 * len(wins) / len(tr)) if tr else None,
            "avgWin": round(sum(wins) / len(wins), 2) if wins else None,
            "avgLoss": round(sum(losses) / len(losses), 2) if losses else None,
            "payoff": round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 2) if wins and losses and sum(losses) else None,
            "mdd": round(mdd, 2), "loc": round(sum(t["loc"] for t in tr), 2),
            "slip": round(sum(slip) / len(slip), 2) if slip else None, "slipN": len(slip),
            "days": len(days_traded), "best": round(max(dn), 2) if dn else None, "worst": round(min(dn), 2) if dn else None,
            "month": f"{first:%Y-%m}", "monthName": f"{first:%B %Y}", "cal": cal, "eq": eq,
            "strat": strat, "trades": list(reversed(tr))[:400]}


def older_jobs(sym, days, prior_of):
    """Strategy jobs for finished older days (display only - the chart's backtest view, never the bot)."""
    jobs = []
    for dn, cs in days:
        prior = prior_of(dn)
        if not prior or not cs:
            continue
        tc = [x[0] for x in cs]
        times = pd.to_datetime(np.asarray(tc, dtype="int64"), unit="s").tz_localize(STRAT.ET)
        o, h, l, c, v = (list(z) for z in zip(*((x[1], x[2], x[3], x[4], x[5]) for x in cs)))
        df = pd.DataFrame({"time": times, "open": o, "high": h, "low": l, "close": c, "volume": v})
        jobs.append({"sym": sym, "day": dn, "date": day_date(dn), "df": df, "tc": tc, "prior": prior,
                     "live": False, "latest": False})
    return jobs


# -----------------------------------------------------------------------------
# Python -> chart bridge (one thread, batched, coalesced, ~10 pushes/s max)
# -----------------------------------------------------------------------------
class UiBridge:
    def __init__(self):
        self.window = None
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.calls = []
        self.rows = {}
        self.quote_msg = None
        self.closed = False

    def on_loaded(self, *_):
        self.ready.set()

    def call(self, fn, payload=None):
        js = f"App.{fn}({_dumps(payload) if payload is not None else ''})"
        with self.lock:
            self.calls.append(js)

    def call_raw(self, fn, json_text):
        with self.lock:
            self.calls.append(f"App.{fn}({json_text})")

    def upsert(self, gen, row):
        with self.lock:
            self.rows[(gen, row[0])] = (gen, row)

    def quote(self, gen, q):
        q["gen"] = gen
        with self.lock:
            self.quote_msg = q

    def close(self):
        self.closed = True

    def run(self):
        self.ready.wait()
        while not self.closed:
            time.sleep(0.1)
            with self.lock:
                calls, rows, quote = self.calls, self.rows, self.quote_msg
                self.calls, self.rows, self.quote_msg = [], {}, None
            parts = list(calls)
            if rows:
                by_gen = {}
                for gen, row in rows.values():
                    by_gen.setdefault(gen, []).append(row)
                for gen, lst in by_gen.items():
                    lst.sort(key=lambda r: r[0])
                    parts.append(f"App.upsertBars({_dumps({'gen': gen, 'bars': lst})})")
            if quote is not None:
                parts.append(f"App.setQuote({_dumps(quote)})")
            if parts and self.window is not None and not self.closed:
                try:
                    self.window.evaluate_js(";".join(parts) + ";0")
                except Exception as exc:
                    log.warning("UI push failed: %s", exc)


def _beep(kind):
    if sys.platform != "win32":
        return

    def run():
        try:
            import winsound
            if kind == "short":
                winsound.Beep(988, 140)
                winsound.Beep(1319, 240)
            else:
                winsound.Beep(784, 180)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()



JOURNAL_COLS = ["date", "symbol", "setup", "account", "top", "short_limit", "stop", "shares", "entry_avg", "entry_time",
                "exit_avg", "exit_time", "exit_reason", "locate_per_share", "locate_cost", "pnl_gross", "pnl_net", "R_net"]
SETUP_NAME = {"BOUNCE_ZONE": "Bounce-zone", "VACUUM": "Vacuum", "JR_A": "Jay-read A rollover", "JR_B": "Jay-read B overhead high",
              "SQ": "Max squeeze", "JR2_G": "JR2 gapper", "JR2_S": "JR2 spiker"}
ROLE_LABEL = {"entry": "Bot entry", "stop": "Bot stop", "ystop": "Your stop", "cover": "Bot cover", "bot": "Bot",
              "you": "You", "long": "Long bot"}



def _fp(x):
    return "-" if x is None or x != x else (f"{x:.4f}" if x < 1 else f"{x:.2f}")


def _money(x):
    return "-" if x is None else ("-" if x < 0 else "") + f"${abs(x):,.2f}"


def _pm(x):
    """3.10 Discord titles: +$1,234 / -$1,234 / $0."""
    x = float(x or 0.0)
    return "$0" if abs(x) < 0.5 else ("+" if x > 0 else "-") + f"${abs(x):,.0f}"



def bot_engine(sym, frame, day, prior, has_rth, void=()):
    """One run of the untouched v16 engine on today's CLOSED candles. Returns what the bot needs.
    void = entries you cancelled in the orders panel ("B", top candle time) / ("V", "peak time-signal time"): the engine
    treats them as never filled (no simulated position blocking the next setup; that bounce top stays used up). Keys are
    candle times, so a candle reload cannot shift them."""
    n = len(frame)
    out = {"pending": None, "vac": None, "vac_armed": None, "trades": [], "hod": float(frame["high"].max()) if n else None,
           "gap": None, "gapOk": False, "block": "", "vol": float(frame["volume"].sum()) if n else 0.0, "bars": n,
           "vwap": None, "close": float(frame["close"].iloc[-1]) if n else None}
    if n:
        tp = (frame["high"] + frame["low"] + frame["close"]) / 3.0
        vv = frame["volume"].sum()
        out["vwap"] = float((tp * frame["volume"]).sum() / vv) if vv > 0 else None
    if not has_rth:
        out["block"] = "pre-market"
        return out
    bt = STRAT.Backtest(sym, day, frame, prior)
    seen = {"vp": None}
    ts = lambda i: calendar.timegm(frame["time"].iloc[i].timetuple())
    if void:
        void = set(void)
        try_fill, vac_fill = bt._try_fill, bt._vac_fill

        def try_fill_v(t):
            p = bt.pending
            try_fill(t)
            pos = bt.pos
            if pos is not None and p is not None and pos.entry_idx == t and ("B", ts(int(p["top_idx"]))) in void:
                bt.pos, bt.ntr = None, bt.ntr - 1        # you cancelled this one: no position (the top stays used)
                bt.log_skip(t, "cancelled by you - setup skipped", p["trigger"])

        def vac_fill_v(t):
            p = bt.vac_pending
            vac_fill(t)
            pos = bt.pos
            if (pos is not None and p is not None and pos.entry_idx == t
                    and ("V", f"{ts(p['peak_idx'])}-{ts(p['idx'])}") in void):
                bt.pos, bt.vac_ntr = None, bt.vac_ntr - 1
        bt._try_fill, bt._vac_fill = try_fill_v, vac_fill_v
    if hasattr(bt, "_vac_update"):
        vac_update = bt._vac_update

        def spy(t):                                  # the engine clears vac_pending when run() ends: keep the last one
            vac_update(t)
            seen["vp"] = bt.vac_pending
        bt._vac_update = spy
    bt.run()
    p = bt.pending
    if p is not None and "trigger" in p:
        out["pending"] = {"trigger": float(p["trigger"]), "zone_hi": float(p["zone_hi"]), "stop": float(p["sig"].stop),
                          "top": float(p["top"]), "dip": float(p.get("dip_pct", 0.0)), "ext": float(p.get("ext", 0.0)),
                          "top_t": ts(int(p["top_idx"])) if p.get("top_idx", -1) >= 0 else None}
    vp = seen["vp"]
    if vp is not None:                               # vacuum short decided at the last closed candle: short at the next open
        quiet = float(frame["volume"].iloc[vp["idx"] + 1:].sum()) <= 0     # only halted candles since the signal
        out["vac"] = {"key": f"{vp['peak_idx']}-{vp['idx']}", "peak": float(vp["peak"]), "stop": float(vp["sig"].stop),
                      "trigger": float(vp["trigger"]), "ext": float(vp["ext"]), "t": ts(vp["idx"]), "peak_t": ts(vp["peak_idx"]),
                      "fresh": quiet, "vkey": f"{ts(vp['peak_idx'])}-{ts(vp['idx'])}"}
    if getattr(bt, "vac_armed", False) and bt.vac_peak_idx >= 0:
        out["vac_armed"] = {"peak": float(bt.vac_peak), "t": ts(bt.vac_arm_idx), "arm_idx": int(bt.vac_arm_idx),
                            "trigger": float(bt.vac_peak * (1 - STRAT.VAC_PULLBACK_PCT / 100.0))}
    out["vac_skip"] = None
    for sk in getattr(bt, "skipped", []):
        if sk.get("setup") == getattr(STRAT, "VAC_SETUP", "VACUUM") and sk["idx"] == n - 1:
            out["vac_skip"] = {"key": f"{sk['idx']}", "reason": str(sk["reason"]).replace("vacuum signal - ", ""),
                               "price": float(sk["price"]), "t": ts(sk["idx"])}
    for tr in bt.trades:
        out["trades"].append({"setup": tr["setup"], "top": float(tr["top"]), "entry": float(tr["entry"]),
                              "stop": float(tr["stop"]), "t": calendar.timegm(tr["entry_time"].timetuple()),
                              "reason": tr["exit_reason"], "open": tr["exit_reason"] == "EOD" and tr["exit_idx"] == n - 1})
    out["hod"] = float(bt.hod) if bt.hod == bt.hod and not math.isinf(bt.hod) else out["hod"]
    gap = getattr(bt, "gap_pct", float("nan"))
    out["gap"] = gap if gap == gap else None
    out["gapOk"] = bool(bt.gap_ok)
    out["block"] = bt.block_reason or ""
    if len(bt.cumvol):
        out["vol"] = float(bt.cumvol[-1])
    if len(bt.vwap) and bt.vwap[-1] == bt.vwap[-1]:
        out["vwap"] = float(bt.vwap[-1])
    return out


class BotSym:
    def __init__(self, sym):
        self.sym = sym
        self.st = None                  # SymState with the 1-min candles (IB keepUpToDate)
        self.ticker = None
        self.loading = False
        self.next_load = 0.0
        self.load_err = ""
        self.last_bar_wall = 0.0
        self.last_px = None
        self.halted = False
        self.eng = None                 # last engine result
        self.eng_key = None
        self.phase = "idle"             # idle | locating | working | short | covering | manual (you took the short over)
        self.entry = None               # the trade in progress
        self.stop_coid = None
        self.stop_qty = 0
        self.stop_owner = "bot"         # "bot" = the bot's stop, "you" = a stop you placed / changed at TradeZero
        self.stop_missing_since = None
        self.stop_alerted_at = 0.0
        self.last_flow = 0.0            # last "stock flow" picture sent to Discord (monotonic)
        self.cover = None               # {"coid", "reason", "tries"}
        self.busy = False
        self.skip_top = {}              # top -> reason: do not retry this top (locate too expensive, order rejected...)
        self.trades = []                # finished real trades today
        self.next_poll = 0.0
        self.status, self.kind = "Waiting for IB Gateway...", "dim"
        self.data_lost_at = None
        self.gone_since = None
        self.auto_added = False         # 3.7: put on the watchlist by the short scanner
        self.halt = None                # 3.12: the halt now: {"t", "hms", "px", "dir", "src", "resumed", ...}
        self.stop_guard = None          # 3.12: the stop TradeZero rejected / cancelled: put back / covered (see _guard_stop)
        self.vol_seen = None            # 3.12: IB's day volume at the last tick (rising = real trades, never indications)
        self.bid = self.ask = None      # 3.12: the quote (the reopen check)
        self.reset_day()

    def reset_day(self):
        # 3.7 Jay-read short: one JayReadShort per symbol per day, fed every closed candle once
        self.jr = None                  # the module object (live mode: simulate_fills=False)
        self.jr_dn = None               # its day
        self.jr_fp = []                 # the candles fed so far (time, o, h, l, c, v) - an IB revision rebuilds the read
        self.jr_sig = None              # a SIGNAL waiting for the bot step: {"sig", "wall", "t"}
        self.jr_lock = None             # STOP_MOVED: the lock stop to place
        self.jr_eod = False             # COVER_ALL: cover at the EOD time
        self.jr_ctx = None              # the read right now: momentum broke (for the pre-locate and the status line)
        self.jr_plan = None             # what the flow picture shows for a signal
        self.jr_virtual = None          # ALERT_ONLY: the short the bot WOULD hold (followed on the candles like the backtest)
        self.sq_ctx = None              # 3.9.0: the max squeeze read right now: a squeeze is on (pre-locate, status line)
        self.hunt = None                # 3.9.0: the locate search ("pre" before a signal / "entry" after one)
        self.loc_note = ""              # 3.9.0: the last locate offer seen (status line, messages)
        self.pre_req = None             # pre-locate request (stock stretched above VWAP)
        self.pre_done = False
        self.locate_requests = 0
        self.locate_px = 0.0            # $/share of the locate in use
        self.locate_unbilled = 0.0      # $ of locates bought today not yet charged to a trade (the next fill pays it)
        self.locate_cost = 0.0          # $ paid for locates today
        self.etb = None
        self.notes = set()              # one-time notes already sent today
        self.used_vac = set()           # vacuum signals already acted on
        self.void = set()               # entries you cancelled: ("B", top candle) / ("V", vacuum key) - engine skips them
        self.seen_armed = set()         # bounce limits / vacuum traps already reported
        self.last_img = 0.0
        self.eod_alerted = set()
        self.loaded_msg = False
        self.halts = []                 # 3.12: today's halts (up / down, price, halt and resume times)
