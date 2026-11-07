#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Discord - the messages of Kestrel 3.12: the webhook sender (a background queue, in order, rate limits
respected, so trading never waits on Discord), the message look (colour, tag line, Shorts / Longs / System names, never
the account id) and the 1-minute chart pictures attached to setups, orders and closed trades.
(Named kestrel_discord.py, not discord.py, so it can never clash with the Python package called "discord".)
Part of Kestrel - keep it next to main.py. Names written app.X live in main.py (the settings at its top).
"""
import sys
import logging
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timezone
import queue as _queue
import uuid as _uuid

app = sys.modules["lh_host"]                     # main.py (it binds itself before importing this file)
log = logging.getLogger("lh_app")


# -----------------------------------------------------------------------------
# DISCORD NOTIFICATIONS (webhook) + CHART IMAGES
# A Discord webhook posts into one channel of your server: Server Settings -> Integrations -> Webhooks ->
# New Webhook -> pick the channel -> Copy Webhook URL, then paste it in the app (Keys).
# Messages go out from a background queue (in order, rate limits respected) so trading never waits on Discord.
# -----------------------------------------------------------------------------
import queue as _queue
import uuid as _uuid
# 3.10 colours (the left bar of every message): red = short / problem, green = done well, yellow = note / not traded,
# blue = info, grey = routine, light blue = stop moved by the lock, magenta = short signal
COLORS = {"info": 0x5865F2, "ok": 0x23A55A, "warn": 0xF0B232, "err": 0xF23645, "trade": 0xE040FB, "short": 0xF23645,
          "cover": 0x23A55A, "dim": 0x80848E, "lock": 0x00A8FC, "mag": 0xE040FB,
          "buy": 0x23A55A, "win": 0x23A55A, "loss": 0xF23645, "partial": 0x5865F2, "spike": 0x80848E}   # premarket long
_EMOJI_RE = re.compile(r"^[^A-Za-z0-9$+\-(\[]+")
def dc_style(title, kind, tag=None):
    """3.10 Discord look: (tag, title). The tag is the small coloured line above the title (SHORT FILLED, CLOSED · WIN,
    IB GATEWAY DISCONNECTED ...); no emoji in front of the title; "AIOK: text" -> "AIOK - text"."""
    t = _EMOJI_RE.sub("", str(title or "")).strip()
    t = re.sub(r"^([A-Z][A-Z0-9.]{0,7}): ", r"\1 - ", t)
    if tag:
        return str(tag).upper(), t
    lo = t.lower()
    rules = (("still searching", "SIGNAL  ·  WAITING FOR A LOCATE"), ("still no locate", "LOCATE SEARCH"),
             ("skipped - no locate", "SIGNAL  ·  SKIPPED"), ("entry dropped", "SIGNAL  ·  SKIPPED"),
             ("locate done", "LOCATED"), ("setup forming", "SETUP FORMING"), ("forming", "SETUP FORMING"),
             ("locate prices", "LOCATE OFFERS"), ("locate requested", "LOCATE REQUESTED"),
             ("you located", "YOU LOCATED"), ("already located", "LOCATED"), ("no locate needed", "LOCATE"),
             ("short order placed", "SHORT ORDER SENT"), ("short limit placed", "SHORT ORDER SENT"),
             ("nothing filled", "NOT FILLED"), ("skipped", "SIGNAL  ·  SKIPPED"), ("analysis running", "WATCHING"),
             ("symbol not found", "SYMBOL NOT FOUND"), ("sold back", "LOCATES SOLD BACK"),
             ("could not sell", "SELL FAILED"), ("not filled after", "SELL FAILED"),
             ("sold at tradezero", "SOLD OUTSIDE THE BOT"), ("long at tradezero", "LONG TAKEN OVER"),
             ("entry not filled", "NOT FILLED"), ("short filled", "SHORT FILLED"), ("taken over", "SHORT TAKEN OVER"), ("still no stop", "NO STOP"),
             ("no stop", "NO STOP"), ("stop rejected", "NO STOP"), ("stop removed", "STOP REMOVED"),
             ("cover failed", "COVER FAILED"), ("cover cancelled", "COVER CANCELLED"), ("rejected", "ORDER REJECTED"),
             ("stop changed", "STOP CHANGED BY YOU"), ("following your stop", "STOP CHANGED BY YOU"),
             ("stop moved", "STOP MOVED"), ("lock", "LOCK"), ("stop placed", "STOP PLACED"), ("closed", "CLOSED"),
             ("covering", "COVERING"), ("you covered", "YOU COVERED"), ("network drop", "NETWORK"),
             ("duplicate", "NETWORK"), ("locate", "LOCATE"), ("halted", "HALTED"), ("resumed trading", "HALT OVER"),
             ("watchlist", "WATCHLIST"), ("scanner", "SCANNER"), ("tradezero", "TRADEZERO"), ("ib gateway", "IB GATEWAY"),
             ("market data", "IB GATEWAY"), ("signal", "SIGNAL"), ("cancelled", "CANCELLED BY YOU"), ("flatten", "FLATTEN ALL"),
             ("summary", "SUMMARY"), ("auto-trade", "AUTO-TRADE"), ("order", "ORDER"))
    for key, tg in rules:
        if key in lo:
            return tg, t
    return {"err": "PROBLEM", "warn": "NOTE", "ok": "OK", "trade": "SETUP", "short": "SHORT", "cover": "CLOSED",
            "buy": "BOUGHT", "win": "CLOSED  ·  WIN", "loss": "CLOSED  ·  STOP", "partial": "HALF SOLD",
            "spike": "LONG WATCH"}.get(kind, "INFO"), t
def discord_load():
    """3.11: the webhook and the ping come from the .env file (the only place once it exists); discord.json only
    without a .env file (the start-up copies it in)."""
    cfg = {"url": app.DISCORD_WEBHOOK_URL, "mention": app.DISCORD_MENTION}
    have_env = os.path.isfile(app.env_path())
    for path in (() if have_env else (os.path.join(app._base_dir(), "discord.json"), os.path.join(app.DATA_DIR, "discord.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            for k in cfg:
                if k in data and data[k] is not None:
                    cfg[k] = str(data[k]).strip()
        except (OSError, ValueError):
            pass
    env = app.env_read() if have_env else {}
    if env.get("DISCORD_WEBHOOK_URL"):
        cfg["url"] = env["DISCORD_WEBHOOK_URL"].strip()
    if "DISCORD_MENTION" in env:
        cfg["mention"] = env["DISCORD_MENTION"].strip()
    return cfg
def discord_save(url, mention):
    """3.11: written to the .env file."""
    return app.env_write({"DISCORD_WEBHOOK_URL": (url or "").strip(), "DISCORD_MENTION": (mention or "").strip()})
def discord_url_ok(url):
    return bool(re.match(r"^https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+", url or ""))
class Discord:
    """Posts embeds (and a chart image) to a Discord webhook from its own thread."""

    def __init__(self):
        cfg = discord_load()
        self.url, self.mention = cfg["url"], cfg["mention"]
        self.q = _queue.Queue(maxsize=400)
        self.sent = 0
        self.failed = 0
        self.last_error = ""
        self.last_ok = None
        self.alive = True
        self.thread = threading.Thread(target=self._run, name="discord", daemon=True)
        self.thread.start()

    def configure(self, url, mention):
        self.url, self.mention = (url or "").strip(), (mention or "").strip()

    @property
    def on(self):
        return discord_url_ok(self.url)

    def status(self):
        if not self.url:
            return {"conn": "off", "text": "Discord: not set"}
        if not self.on:
            return {"conn": "error", "text": "Discord: webhook URL looks wrong"}
        if self.last_ok is False:
            return {"conn": "error", "text": f"Discord: {self.last_error}"}
        return {"conn": "connected" if self.last_ok else "off", "text": f"Discord: {self.sent} sent" + (f", {self.failed} failed" if self.failed else "")}

    def send(self, title, text="", kind="info", fields=None, image=None, ping=False, username=None, tag=None):
        """image = PNG bytes, or a list of (file name, PNG bytes) shown in that order (or None). ping = add the mention
        (3.10: only when you have to act). username = Shorts / Longs / System (None = System). tag = the small line
        above the title (None = picked from the title)."""
        if not self.on:
            return False
        if isinstance(image, (bytes, bytearray)):
            image = [("chart.png", bytes(image))]
        image = [(n, b) for n, b in (image or []) if b][:4] or None
        tag, title = dc_style(title, kind, tag)
        item = {"title": str(title)[:250], "text": str(text or "")[:3900], "kind": kind, "fields": fields or [],
                "image": image, "ping": bool(ping), "ts": datetime.now(timezone.utc).isoformat(), "username": username,
                "tag": tag}
        try:
            self.q.put_nowait(item)
        except _queue.Full:
            try:
                self.q.get_nowait()                       # drop the oldest, keep the newest
                self.q.put_nowait(item)
            except Exception:
                pass
        return True

    def send_now(self, title, text="", kind="info", fields=None, quick=False, tag=None, username=None, ping=False):
        """Blocking send (Test button, app closing): returns (ok, message). quick = one short try."""
        if not self.on:
            return False, "the webhook URL is not a Discord webhook URL"
        tag, title = dc_style(title, kind, tag)
        ok = self._post({"title": title, "text": text, "kind": kind, "fields": fields or [], "image": None, "ping": bool(ping),
                         "ts": datetime.now(timezone.utc).isoformat(), "tag": tag, "username": username}, quick=quick)
        return ok, ("sent" if ok else self.last_error)

    def _payload(self, item):
        emb = {"title": item["title"], "description": item["text"], "color": COLORS.get(item["kind"], COLORS["info"]),
               "timestamp": item["ts"]}                   # 3.10: no "Kestrel" footer
        if item.get("tag"):
            emb["author"] = {"name": str(item["tag"])[:250]}
        if item["fields"]:
            emb["fields"] = [{"name": str(n)[:250], "value": str(v)[:1000] or "-", "inline": bool(inl)}
                             for n, v, inl in item["fields"][:25]]
        embeds = [emb]
        for k, (name, _) in enumerate(item["image"] or []):
            if k == 0:
                emb["image"] = {"url": f"attachment://{name}"}
            else:                                         # every further picture in its own embed under the first
                embeds.append({"color": emb["color"], "image": {"url": f"attachment://{name}"}})
        p = {"username": item.get("username") or app.DISCORD_NAME_SYSTEM, "embeds": embeds, "allowed_mentions": {"parse": ["everyone", "users", "roles"]}}
        if item["ping"] and self.mention:
            p["content"] = self.mention
        return p

    def _post(self, item, quick=False):
        payload = json.dumps(self._payload(item)).encode("utf-8")
        if item["image"]:
            bnd = "lhb" + _uuid.uuid4().hex
            body = (f"--{bnd}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                    f"Content-Type: application/json\r\n\r\n").encode() + payload
            for k, (name, data) in enumerate(item["image"]):
                body += (f"\r\n--{bnd}\r\nContent-Disposition: form-data; name=\"files[{k}]\"; filename=\"{name}\"\r\n"
                         f"Content-Type: image/png\r\n\r\n").encode() + data
            body += f"\r\n--{bnd}--\r\n".encode()
            ctype = f"multipart/form-data; boundary={bnd}"
        else:
            body, ctype = payload, "application/json"
        for attempt in range(1 if quick else 5):
            req = urllib.request.Request(self.url + ("&" if "?" in self.url else "?") + "wait=true", data=body, method="POST")
            req.add_header("Content-Type", ctype)
            req.add_header("User-Agent", f"DiscordBot (https://github.com/kestrel-bot, {app.APP_VERSION})")
            try:
                with urllib.request.urlopen(req, timeout=8 if quick else 15) as resp:
                    resp.read()
                self.sent += 1
                self.last_ok, self.last_error = True, ""
                return True
            except urllib.error.HTTPError as exc:
                raw = ""
                try:
                    raw = exc.read().decode("utf-8", "replace")
                except Exception:
                    pass
                if exc.code == 429:                       # rate limited: wait what Discord says
                    try:
                        wait = float(json.loads(raw).get("retry_after", 1.0))
                    except (ValueError, AttributeError):
                        wait = 1.0
                    time.sleep(min(max(wait, 0.2), 30.0))
                    continue
                if exc.code >= 500 and attempt < 3:
                    time.sleep(1.0 + attempt)
                    continue
                self.last_error = f"HTTP {exc.code} {raw[:120]}"
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.last_error = f"no connection ({getattr(exc, 'reason', exc)})"
                if attempt < 3:
                    time.sleep(2.0 + attempt)
                    continue
                break
        self.failed += 1
        self.last_ok = False
        log.warning("Discord send failed: %s", self.last_error)
        return False

    def _run(self):
        while self.alive:
            try:
                item = self.q.get(timeout=1.0)
            except _queue.Empty:
                continue
            try:
                self._post(item)
            except Exception:
                log.exception("discord")
            time.sleep(0.35)                              # stay well under Discord's 5 posts / 2 s per webhook
def chart_rows_today(st, minutes=None):
    """Today's 1-min rows [t, o, h, l, c, v, vwap] (premarket included, VWAP like the engine)."""
    if st is None or not st.tc:
        return []
    dn = st.tc[-1] // 86400
    a = len(st.tc)
    while a > 0 and st.tc[a - 1] // 86400 == dn:
        a -= 1
    rows, pv, vv = [], 0.0, 0.0
    started = app.K.include_pm
    for i in range(a, len(st.tc)):
        o, h, l, c, v = app.bar_ohlcv(st.bars[i])
        if not started and app.is_rth(st.tc[i]):
            started = True
        if started:
            pv += (h + l + c) / 3.0 * v
            vv += v
        rows.append([st.tc[i], o, h, l, c, v, pv / vv if vv > 0 else None])
    if minutes:
        rows = rows[-int(minutes):]
    return rows
def render_chart_png(sym, rows, title="", levels=None, marks=None, prior=None, hod=None):
    """1-minute candles, VWAP, VWAP +20%, HOD and the trade levels -> PNG bytes (None if matplotlib is missing)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Rectangle
    except Exception:
        return None
    if not rows:
        return None
    # emoji are not in the chart font: keep letters, digits, punctuation and arrows
    title = "".join(ch for ch in str(title or "") if ord(ch) < 0x2000 or 0x2190 <= ord(ch) <= 0x21FF).strip().replace("$", r"\$")
    BG, FG, GRID = "#0e0f11", "#d6d9de", "#25272b"
    fig = Figure(figsize=(12, 6.6), dpi=100, facecolor=BG)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.05, 0.27, 0.86, 0.63])
    av = fig.add_axes([0.05, 0.08, 0.86, 0.17], sharex=ax)
    n = len(rows)
    X = list(range(n))
    hi = max(r[2] for r in rows)
    lo = min(r[3] for r in rows)
    for k, r in enumerate(rows):
        o, h, l, c, v = r[1:6]
        col = app.CANDLE_UP_COLOR if c >= o else app.CANDLE_DOWN_COLOR
        ax.vlines(k, l, h, color=col, lw=0.8)
        ax.add_patch(Rectangle((k - 0.35, min(o, c)), 0.7, max(abs(c - o), (hi - lo) * 0.0015), color=col))
        av.bar(k, v, color=col, width=0.8, alpha=0.45 if c >= o else 0.75)
    vw = [r[6] for r in rows]
    ax.plot(X, [x if x is not None else float("nan") for x in vw], color=app.VWAP_COLOR, lw=1.4, label="VWAP")
    rng = hi - lo or hi * 0.01
    ymin, ymax = lo - rng * 0.05, hi + rng * 0.12
    for L in levels or []:
        p = L.get("price")
        if p is None or p != p:
            continue
        ymin, ymax = min(ymin, p - rng * 0.03), max(ymax, p + rng * 0.05)
        ax.axhline(p, color=L.get("color", "#9598a1"), lw=1.1, ls={"solid": "-", "dot": ":", "dash": "--"}.get(L.get("style"), "--"))
        ax.text(n + 0.5, p, f" {L.get('title', '')} {p:.4g}", color=L.get("color", "#9598a1"), fontsize=8.5, va="center",
                ha="left", bbox=dict(fc=BG, ec="none", pad=0.5))
    for M in marks or []:
        t = M.get("t")
        k = next((i for i, r in enumerate(rows) if r[0] >= t), n - 1) if t is not None else n - 1
        up = M.get("up", False)
        ax.annotate(M.get("text", ""), xy=(k, M["price"]), xytext=(k, M["price"] + (-1 if up else 1) * rng * 0.14),
                    color=M.get("color", "#f23645"), fontsize=9, ha="center", weight="bold",
                    arrowprops=dict(arrowstyle="-|>", color=M.get("color", "#f23645"), lw=1.8),
                    bbox=dict(fc=BG, ec="none", pad=0.2))
    ax.set_ylim(ymin, ymax)
    ax.set_xlim(-1, n + 6)
    step = max(1, n // 8)
    ticks = list(range(0, n, step))
    av.set_xticks(ticks)
    av.set_xticklabels([datetime.fromtimestamp(rows[k][0], timezone.utc).strftime("%H:%M") for k in ticks])
    for a in (ax, av):
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=8)
        for sp in a.spines.values():
            sp.set_color(GRID)
        a.yaxis.tick_right()
    for lab in ax.get_xticklabels():
        lab.set_visible(False)
    av.set_yticks([])
    last = rows[-1]
    vwl = last[6]
    up = f"  {last[4] / prior * 100 - 100:+.0f}% vs prior close" if prior else ""
    ext = f"  {last[4] / vwl * 100 - 100:+.0f}% vs VWAP" if vwl else ""
    when = datetime.fromtimestamp(last[0], timezone.utc).strftime("%H:%M")
    fig.text(0.05, 0.955, f"{sym}  {last[4]:.4g}{up}{ext}   HOD {hod or hi:.4g}   {when} ET (1-min)", color="white", fontsize=13,
             weight="bold", va="top")
    if title:
        fig.text(0.05, 0.92, title, color="#a9adb4", fontsize=10, va="top")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    return buf.getvalue()
# -----------------------------------------------------------------------------
# THE "STOCK FLOW" PICTURE (v3.4): a clean line chart that reads like a hand-drawn plan - the price line, VWAP, the
# high of day, the lower highs, where the price is now, and what the bot is doing: the short level, the stop, the next
# supports (T1 / T2, guides only - the bot places no target orders) and the expected path. Sent with every symbol
# message (ticker added, setup forming, armed, signal, locate, order, fill, stop, cover, close, alerts).
# -----------------------------------------------------------------------------
FLOW_BG, FLOW_FG, FLOW_DIM = "#151515", "#d4d4d4", "#9a9a9a"
FLOW_PRICE, FLOW_VWAP, FLOW_STOP, FLOW_TGT = "#c8c8c8", "#f0a030", "#e4572e", "#2ea37a"
FLOW_SHORT, FLOW_SETUP = "#ff7043", "#b48cf0"
def _flow_pivots(ts, hs, ls, pct):
    """Confirmed swing highs / lows of at least pct % (zigzag on the 1-minute highs and lows): [(t, price, 'H' | 'L')].
    A swing counts once the price has moved pct % away from it (the swing in progress is not included)."""
    th = pct / 100.0
    piv, mode = [], 0
    hi, hi_t, lo, lo_t = hs[0], ts[0], ls[0], ts[0]
    for t, h, l in zip(ts, hs, ls):
        if mode == 1:
            if h > hi:
                hi, hi_t = h, t
            elif l <= hi * (1 - th):
                piv.append((hi_t, hi, "H"))
                mode, lo, lo_t = -1, l, t
        elif mode == -1:
            if l < lo:
                lo, lo_t = l, t
            elif h >= lo * (1 + th):
                piv.append((lo_t, lo, "L"))
                mode, hi, hi_t = 1, h, t
        else:
            if h > hi:
                hi, hi_t = h, t
            if l < lo:
                lo, lo_t = l, t
            if hi >= lo * (1 + th) and hi_t > lo_t:
                piv.append((lo_t, lo, "L"))
                mode = 1
            elif lo <= hi * (1 - th) and lo_t > hi_t:
                piv.append((hi_t, hi, "H"))
                mode = -1
    return piv
def _spread_labels(items, span, gap):
    """items [(y, ...)] sorted by y: push label positions apart by at least gap (in price units)."""
    out = []
    for it in sorted(items, key=lambda x: x[0]):
        y = it[0]
        if out and y - out[-1][1] < gap:
            y = out[-1][1] + gap
        out.append((it, y))
    return out
def _fpx(p):
    return f"{p:.2f}" if p >= 1 else f"{p:.4f}"
def render_flow_png(sym, rows, plan):
    """The "stock flow" picture (see _render_flow), drawn with DejaVu Sans, which ships with matplotlib, so it looks the
    same on every PC."""
    try:
        import matplotlib
    except Exception:
        return None
    with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        return _render_flow(sym, rows, plan)
def _render_flow(sym, rows, plan):
    """rows = today's 1-minute rows [t, o, h, l, c, v, vwap] (t = ET wall clock as epoch seconds).
    plan = {"title", "sub", "entry": (price, label) | None, "stop": (price, label) | None, "ref": price for T1/T2,
            "supports": [(price, label)], "watch": [(price, label)], "marks": [{"t", "price", "text", "kind"}],
            "path": True (up to the short level, then down) | "down" (from now down to T1 / T2) | False, "entry_tag"}.
    Returns PNG bytes, or None without matplotlib / data."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except Exception:
        return None
    rows = [r for r in rows if r[4] and r[4] > 0]
    if len(rows) < 3:
        return None
    clean = lambda s: "".join(ch for ch in str(s or "") if ord(ch) < 0x2000 or 0x2190 <= ord(ch) <= 0x21FF).strip() \
        .replace("$", r"\$")                          # a $ pair would switch matplotlib to math text
    mins_all = [(r[0] % 86400) / 60.0 for r in rows]
    cs_all = [r[4] for r in rows]
    hod_all = max(range(len(rows)), key=lambda i: rows[i][2])
    # window: the run and some of the base before it, at least 90 minutes before now
    base = min(cs_all[:hod_all + 1])
    m_move = next((m for m, c in zip(mins_all, cs_all) if c >= base * 1.2), mins_all[hod_all])
    now_m = mins_all[-1]
    start_m = max(mins_all[0], min(m_move - 45, now_m - 90, 540))
    rows = [r for r, m in zip(rows, mins_all) if m >= start_m]
    mins = [(r[0] % 86400) / 60.0 for r in rows]
    hs, ls, cs = [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows]

    def X(m):                                         # time -> x: extended hours squeezed to a third
        w = 0.33
        if m < 570:
            return (m - start_m) * w
        pre = max(0.0, 570 - start_m) * w
        if m < 960:
            return pre + (m - 570)
        return pre + 390 + (m - 960) * w
    xs_all = [X(m) for m in mins]
    hod_i = max(range(len(rows)), key=lambda i: hs[i])
    hod, hod_x = hs[hod_i], xs_all[hod_i]
    rng0 = max(hod - min(ls), hod * 0.02)
    span = (xs_all[-1] - xs_all[0]) or 1.0
    bucket = span / 90.0
    pts = {}
    for x, c in zip(xs_all, cs):
        pts[int(x // bucket)] = (x, c)
    line = sorted(pts.values())
    piv = [(X(t), p, k) for t, p, k in _flow_pivots(mins, hs, ls, max(3.0, min(12.0, rng0 / hod * 100 / 8)))]
    keep = {int(x // bucket) for x, _, _ in piv} | {int(hod_x // bucket)}
    line = sorted(set([q for q in line if int(q[0] // bucket) not in keep] + [(x, y) for x, y, _ in piv] + [(hod_x, hod)]))
    if line[-1][0] < xs_all[-1]:
        line.append((xs_all[-1], cs[-1]))
    vw = [(x, r[6]) for x, r in zip(xs_all, rows) if r[6]]
    now_x, now_px = xs_all[-1], cs[-1]
    vw_now = vw[-1][1] if vw else None

    entry, stop = plan.get("entry"), plan.get("stop")
    x_end = now_x + max(35.0, span * 0.30)
    near = now_x - span * 0.03
    levels = []                                       # (price, label, color, style, from_x)
    for p, lab in plan.get("watch") or []:
        if p and p > 0 and abs(p / hod - 1) > 0.005:
            levels.append((p, lab, FLOW_SETUP, ":", near if str(lab).startswith("VWAP") else hod_x))
    if entry and entry[0]:
        levels.append((entry[0], entry[1], FLOW_SHORT, "--", near))
    if stop and stop[0]:
        levels.append((stop[0], stop[1], FLOW_STOP, "--", near))
    ex = plan.get("exit")
    if ex and ex[0]:                                  # a finished trade: where it was covered
        win = entry and entry[0] and ex[0] < entry[0]
        levels.append((ex[0], ex[1], FLOW_TGT if win else FLOW_STOP, "--", near))
    # T1 / T2 = the next supports under the short (VWAP, dip low, swing lows after the high, pre-market high)
    ref, tg, vw_tag = plan.get("ref"), [], ""
    if ref:
        cand = [(p, lab) for p, lab in (plan.get("supports") or []) if p and p > 0]
        if vw_now:
            cand.append((vw_now, "VWAP"))
        cand += [(y, "swing low") for x, y, k in piv if k == "L" and x > hod_x]
        cand = sorted({round(p, 6): (p, lab) for p, lab in cand}.values(), reverse=True)
        for p, lab in cand:
            if p < (tg[-1][0] if tg else ref) * 0.97:
                tg.append((p, lab))
            if len(tg) == 2:
                break
        for k, (p, lab) in enumerate(tg):
            if lab == "VWAP":
                vw_tag = f"T{k + 1} = "
            else:
                levels.append((p, f"T{k + 1} {lab}", FLOW_TGT, "--", near))

    fig = Figure(figsize=(12.1, 6.4), dpi=100, facecolor=FLOW_BG)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([0.03, 0.06, 0.74, 0.76])

    def text_px(txt, size, weight="normal"):        # width of a label in pixels, measured with the real font
        try:
            t = fig.text(0, 0, txt, fontsize=size, weight=weight)
            wpx = t.get_window_extent(canvas.get_renderer()).width
            t.remove()
            return wpx + 6
        except Exception:
            return len(txt) * 10.0 + 6
    ax.set_facecolor(FLOW_BG)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    ys = [y for _, y in line] + [p for p, *_ in levels] + ([vw_now] if vw_now else [])
    ymin, ymax = min(ys), max(ys + [hod])
    yr = (ymax - ymin) or ymax * 0.05
    ax.set_xlim(xs_all[0] - span * 0.01, x_end)
    ax.set_ylim(ymin - yr * 0.08, ymax + yr * 0.13)

    if mins[0] < 570 <= mins[-1]:                     # the open
        ox = X(570)
        ax.axvline(ox, color="#5a5a5a", ls=(0, (2, 4)), lw=1)
        ax.text(ox, ymin - yr * 0.065, " Open", color=FLOW_DIM, fontsize=10.5, ha="left", va="bottom")
        pre = [y for x, y in line if x < ox]
        if pre and ox - xs_all[0] > span * 0.12:
            ax.text((xs_all[0] + ox) / 2, min(pre) - yr * 0.03, "Pre-market", color=FLOW_DIM, fontsize=10.5,
                    ha="center", va="top")
    elif mins[-1] < 570:                              # all of it before the open
        ax.text((xs_all[0] + now_x) / 2, ymin - yr * 0.065, "Pre-market", color=FLOW_DIM, fontsize=10.5, ha="center",
                va="bottom")
    elif mins[0] >= 960:
        ax.text((xs_all[0] + now_x) / 2, ymin - yr * 0.065, "After hours", color=FLOW_DIM, fontsize=10.5, ha="center",
                va="bottom")
    ax.plot([x for x, _ in line], [y for _, y in line], color=FLOW_PRICE, lw=2.0, solid_joinstyle="round", zorder=3)
    if vw:
        ax.plot([x for x, _ in vw], [y for _, y in vw], color=FLOW_VWAP, lw=2.0, zorder=2)
        ax.plot([now_x, x_end], [vw_now, vw_now], color=FLOW_VWAP, lw=2.0, zorder=2)
    box = dict(fc=FLOW_BG, ec="none", alpha=0.85, pad=1.5)
    late = hod_x > now_x - span * 0.12                 # the high is close to now: label it to the left
    ax.text(hod_x + (-span * 0.01 if late else 0), hod + yr * 0.035, f"HOD {_fpx(hod)}", color=FLOW_FG, fontsize=12,
            ha="right" if late else "center", va="bottom", bbox=box, zorder=8)
    highs = [(x, y) for x, y, k in piv if k == "H" and x > hod_x + bucket and y < hod]
    lower = []                                        # the latest run of highs, each one under the one before
    for x, y in reversed(highs):
        if lower and y <= lower[0][1]:
            break
        lower.insert(0, (x, y))
    lower = lower[-3:] if len(lower) >= 2 else []
    for x, y in lower:
        ax.plot([x], [y], marker="o", ms=13, mfc="none", mec="#a0a0a0", mew=1.8, zorder=4)
    if lower:
        lx, ly = lower[0]
        ax.text(lx + span * 0.02, ly + yr * 0.05, "Lower highs", color=FLOW_FG, fontsize=11.5, ha="left", va="bottom",
                bbox=box, zorder=8)
    mark_boxes = []                                   # (x, y, w, h) of the mark texts, kept clear of the "Now" label
    for M in plan.get("marks") or []:
        t, p = M.get("t"), M.get("price")
        if t is None or not p or (t % 86400) / 60.0 < start_m:
            continue
        x = X((t % 86400) / 60.0)
        short = M.get("kind") == "short"
        col = FLOW_SHORT if short else (FLOW_TGT if M.get("kind") == "cover" else FLOW_DIM)
        ax.plot([x], [p], marker="v" if short else "^", ms=13, color=col, zorder=6)
        mark_boxes.append((x, p, 0, 0))
        if M.get("text") and not ex:
            mark_boxes.append((x, p + (1 if short else -1) * yr * 0.05, text_px(clean(M["text"]), 10.5, "bold"), (1 if short else -1)))
            ax.text(x, p + (1 if short else -1) * yr * 0.05, clean(M["text"]), color=col, fontsize=10.5, weight="bold",
                    ha="center", va="bottom" if short else "top", bbox=box, zorder=8)
    ax.plot([now_x], [now_px], marker="o", ms=10, color="#bdbdbd", zorder=7)
    xr = (x_end - xs_all[0] + span * 0.01) / (0.74 * 1210)            # data units per pixel
    yp = (yr * 1.21) / (0.76 * 640)
    lab_h = 22 * yp

    # the expected path (drawn below), and the "Short ..." tag over its arrow
    t1 = tg[0][0] if tg else None
    t2 = tg[1][0] if len(tg) > 1 else (t1 * 0.97 if t1 else None)
    mode, px_, py_, tag = plan.get("path"), [], [], None
    if mode is True and entry and entry[0]:
        e_px = entry[0]
        px_ = [now_x, now_x + (x_end - now_x) * 0.30]
        py_ = [now_px, e_px]
        if t1:
            px_ += [now_x + (x_end - now_x) * 0.70, now_x + (x_end - now_x) * 0.80, x_end - (x_end - now_x) * 0.02]
            py_ += [t1 * 0.995, t1 + (e_px - t1) * 0.25, t2]
        else:
            px_.append(x_end)
            py_.append(e_px - yr * 0.25)
        tag = clean(plan.get("entry_tag") or "Short")
    elif mode == "down" and t1:
        px_ = [now_x, now_x + (x_end - now_x) * 0.55, now_x + (x_end - now_x) * 0.68, x_end - (x_end - now_x) * 0.02]
        py_ = [now_px, t1 * 0.995, t1 + (now_px - t1) * 0.3, t2]

    mark_at_now = any(tw and abs(x - now_x) < span * 0.03 for x, y, tw, up in mark_boxes)
    if not ex and not mark_at_now:                    # (a SHORT mark on the last candle already says where it is)
        # the "Now" label goes where it covers the least of the price line, the path, the circles and the other labels
        now_txt = f"Now ~{_fpx(now_px)}"
        w = text_px(now_txt, 11.5) * xr
        dx, dy = span * 0.015, yr * 0.045
        dense = []
        for (x1, y1), (x2, y2) in zip(line, line[1:]):
            dense += [(x1 + (x2 - x1) * f, y1 + (y2 - y1) * f) for f in (0, 0.25, 0.5, 0.75)]
        for (x1, y1), (x2, y2) in zip(list(zip(px_, py_)), list(zip(px_, py_))[1:]):
            dense += [(x1 + (x2 - x1) * f, y1 + (y2 - y1) * f) for f in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)] * 3
        for (x1, y1), (x2, y2) in zip(vw + [(x_end, vw_now)] if vw else [], vw[1:] + [(x_end, vw_now)] if vw else []):
            dense += [(x1 + (x2 - x1) * f / 8.0, y1 + (y2 - y1) * f / 8.0) for f in range(8)]   # the VWAP line
        for p_, _, _, _, x0_ in levels:                     # the level lines
            x0_ = max(x0_, xs_all[0])
            dense += [(x0_ + (x_end - x0_) * f / 40.0, p_) for f in range(41)]
        mx, my = 3 * xr, 3 * yp                              # keep a few pixels clear around the label
        hod_w = text_px(f"HOD {_fpx(hod)}", 12) * xr
        boxes = [(hod_x - span * 0.01 - hod_w if late else hod_x - hod_w / 2, hod + yr * 0.035, hod_w, lab_h)]
        if lower:
            boxes.append((lower[0][0] + span * 0.02, lower[0][1] + yr * 0.05, text_px("Lower highs", 11.5) * xr, lab_h))
        boxes += [(x - 8 * xr, y - 8 * yp, 16 * xr, 16 * yp) for x, y in lower]        # the circles
        for x, y, tw, up in mark_boxes:                                               # the marks and their texts
            if not tw:
                boxes.append((x - 8 * xr, y - 8 * yp, 16 * xr, 16 * yp))
            else:
                boxes.append((x - tw * xr / 2, y if up > 0 else y - lab_h, tw * xr, lab_h))
        if tag:
            boxes.append((px_[1] + span * 0.012, py_[1] + yr * 0.11 - lab_h / 2, text_px(tag, 12) * xr, lab_h))
            boxes.append((px_[1] - 6 * xr, py_[1], 12 * xr, yr * 0.13))                    # the arrow
        best = None
        for sx, sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:      # below-left, above-left, below-right, above-right
            x0 = now_x + sx * dx - (w if sx < 0 else 0)
            y0 = now_px + sy * dy - (lab_h if sy < 0 else 0)
            hit = sum(1 for x, y in dense if x0 - mx <= x <= x0 + w + mx and y0 - my <= y <= y0 + lab_h + my)
            hit += sum(20 for bx, by, bw, bh in boxes
                       if x0 - 2 * mx < bx + bw and bx < x0 + w + 2 * mx and y0 - my < by + bh and by < y0 + lab_h + my)
            if best is None or hit < best[0]:
                best = (hit, sx, sy)
        _, sx, sy = best
        ax.text(now_x + sx * dx, now_px + sy * dy, now_txt, color=FLOW_FG, fontsize=11.5, ha="right" if sx < 0 else "left",
                va="top" if sy < 0 else "bottom", bbox=box, zorder=8)

    # the plan: dashed levels from now to the right, labels outside the chart, the expected path
    for p, lab, col, style, x0 in levels:
        ax.plot([max(x0, xs_all[0]), x_end], [p, p], color=col, ls=style, lw=1.6, zorder=2)
    lab_items = [(p, f"{lab} {_fpx(p)}", col) for p, lab, col, _, _ in levels]
    if vw_now:
        lab_items.append((vw_now, f"{vw_tag}VWAP {_fpx(vw_now)}", FLOW_TGT if vw_tag else FLOW_FG))
    for (p, txt, col), y in _spread_labels(lab_items, yr, yr * 0.055):
        ax.text(x_end + span * 0.012, y, txt, color=col, fontsize=12, va="center", ha="left", clip_on=False)
    if px_:
        ax.plot(px_, py_, color=FLOW_SHORT, ls=(0, (3, 3)), lw=2.2, zorder=5)
    if tag:
        e_px = py_[1]
        ax.annotate("", xy=(px_[1], e_px + yr * 0.012), xytext=(px_[1], e_px + yr * 0.13),
                    arrowprops=dict(arrowstyle="-|>", color=FLOW_SHORT, lw=2.2), zorder=6)
        ax.text(px_[1] + span * 0.012, e_px + yr * 0.11, tag, color=FLOW_FG, fontsize=12, ha="left", va="center", bbox=box,
                zorder=8)

    fig.text(0.03, 0.95, clean(f"{sym}   {plan.get('title', '')}"), color="white", fontsize=15, weight="bold", va="top")
    if plan.get("sub"):
        fig.text(0.03, 0.895, clean(plan["sub"]), color=FLOW_DIM, fontsize=10.5, va="top")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=FLOW_BG)
    return buf.getvalue()
