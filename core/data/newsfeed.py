# -*- coding: utf-8 -*-
"""LH Short Bot 3.14 - real-time news of the stock on the chart (the News pane under the chart), two free sources:

    Alpaca news stream   Benzinga headlines of that ticker, pushed over a WebSocket the moment they are published.
                         Opening another chart moves the subscription to it at once. Free Alpaca account:
                         ALPACA_API_KEY / ALPACA_SECRET_KEY in .env (Settings > Keys and Discord).
    SEC EDGAR filings    that company's filing list (data.sec.gov submissions), read every SEC_POLL_SEC seconds - one
                         small request for one company. The SEC needs a contact e-mail in every request:
                         SEC_CONTACT_EMAIL in .env.

Only the chart's stock - never the whole market. When a chart opens, the news since the start of the previous weekday
(04:00 ET) is loaded from both sources, then new items stream in.

Every item: {"id", "src" ("Benzinga" / "SEC"), "t" (epoch), "et" (ET "HH:MM:SS"), "day", "tk" [tickers], "head",
"url", "form", "tags"}. tags: "OFFERING" (offering / dilution words, an offering form, 8-K item 3.02), "OFFER?"
(an offering ending, not a new one), "R/S", "HALT", "FDA", "EARNINGS", "DELIST", "8-K". Nothing here trades.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                                   # pragma: no cover
    _ET = None

ALPACA_WS = "wss://stream.data.alpaca.markets/v1beta1/news"
ALPACA_REST = "https://data.alpaca.markets/v1beta1/news"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{:010d}.json"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_DOC = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}"
SEC_POLL_SEC = 3.0                                  # one company: 1 request every 3 s (the SEC allows 10 a second)
OFFER_FORMS = re.compile(r"^(424B\d|S-1(/A)?|S-3(/A)?|F-1(/A)?|F-3(/A)?|S-3ASR|F-3ASR)$")
ITEMS_8K = {"1.01": "material agreement", "1.03": "bankruptcy", "2.02": "results", "2.03": "new debt", "3.01": "delisting notice",
            "3.02": "unregistered sale of shares", "3.03": "rights of holders changed", "5.02": "officer / director change",
            "5.03": "charter amendment", "5.07": "shareholder vote", "7.01": "Reg FD", "8.01": "other events", "9.01": "exhibits"}
TAGS = [
    ("OFFERING", re.compile(r"\b(public offering|registered direct|direct offering|private placement|at[- ]the[- ]market|"
                            r"\bATM\b|offering of|prices? (an? )?(upsized |underwritten )?\$?[\d.,]+ ?(million|m\b|billion)|"
                            r"pricing of|priced|warrants?|shelf registration|equity line|dilut|convertible (notes?|preferred)|"
                            r"Item 3\.02|unregistered sale)", re.I)),
    ("R/S", re.compile(r"reverse (stock )?split", re.I)),
    ("HALT", re.compile(r"\bhalt(ed|s)?\b", re.I)),
    ("FDA", re.compile(r"\bFDA\b|clinical (trial|hold)|phase [123i]", re.I)),
    ("EARNINGS", re.compile(r"\b(earnings|EPS|quarterly results|Q[1-4] (results|revenue))\b", re.I)),
    ("DELIST", re.compile(r"delist|Item 3\.01|minimum bid", re.I)),
]
NOT_OFFER = re.compile(r"\b(terminat|withdraw|cancel|completes? (its |the )?previously announced|closing of)\w*", re.I)


def _et(ts):
    d = datetime.fromtimestamp(ts, _ET) if _ET else datetime.fromtimestamp(ts)
    return d.strftime("%H:%M:%S"), d.strftime("%Y-%m-%d")


def window_start(now=None):
    """04:00 ET of the previous weekday: a Monday morning still shows Friday's news."""
    now = now or (datetime.now(_ET) if _ET else datetime.now())
    d = now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    start = datetime(d.year, d.month, d.day, 4, 0, tzinfo=now.tzinfo)
    return start.timestamp()


def tag(text, form=""):
    tags = [name for name, rx in TAGS if rx.search(text or "")]
    if form and OFFER_FORMS.match(form) and "OFFERING" not in tags:
        tags.insert(0, "OFFERING")
    if form.startswith("8-K"):
        tags.append("8-K")
    if "OFFERING" in tags and NOT_OFFER.search(text or "") and not (form and OFFER_FORMS.match(form)):
        tags[tags.index("OFFERING")] = "OFFER?"       # "terminates / completes the offering": not a new one
    return tags


class NewsFeed:
    def __init__(self, env_get, on_item=None, on_status=None, log=None, on_reset=None):
        self.env_get = env_get                        # reads .env (the keys can change while the app runs)
        self.on_item = on_item or (lambda it: None)
        self.on_status = on_status or (lambda st: None)
        self.on_reset = on_reset or (lambda sym: None)
        self.log = log
        self.sym = ""                                 # the chart's stock
        self.gen = 0                                  # +1 per symbol change: answers for an older symbol are dropped
        self.items = []
        self.seen = set()
        self.lock = threading.Lock()
        self.status = {"alpaca": "off", "sec": "off", "sym": ""}
        self.stop = threading.Event()
        self.wake = {"alpaca": threading.Event(), "sec": threading.Event()}
        self.ciks = {}                                # ticker -> CIK (SEC)
        self.ciks_at = 0.0

    # ------------------------------------------------------------------ shared
    def start(self):
        for name, fn in (("alpaca", self._alpaca_loop), ("sec", self._sec_loop)):
            threading.Thread(target=fn, name="news-" + name, daemon=True).start()
        return self

    def set_symbol(self, sym):
        """The chart moved to another stock: the list starts again with that stock's news."""
        sym = str(sym or "").upper().strip()
        with self.lock:
            if sym == self.sym:
                return
            self.sym = sym
            self.gen += 1
            self.items, self.seen = [], set()
        self.status["sym"] = sym
        try:
            self.on_reset(sym)
        except Exception:
            pass
        self.restart()

    def restart(self):
        """New keys or a new symbol: both sources act at once."""
        for e in self.wake.values():
            e.set()

    def _set(self, src, text):
        if self.status.get(src) != text:
            self.status[src] = text
            try:
                self.on_status(dict(self.status))
            except Exception:
                pass

    def _warn(self, msg):
        if self.log is not None:
            self.log.warning(msg)

    def _add(self, it, gen):
        with self.lock:
            if gen != self.gen or it["id"] in self.seen or self.sym not in it["tk"]:
                return False
            self.seen.add(it["id"])
            self.items.append(it)
            self.items.sort(key=lambda x: -x["t"])
            del self.items[300:]
        try:
            self.on_item(it)
        except Exception:
            pass
        return True

    def list(self):
        with self.lock:
            return {"sym": self.sym, "items": list(self.items)}

    def _sleep(self, src, secs):
        self.wake[src].wait(secs)
        woke = self.wake[src].is_set()
        self.wake[src].clear()
        return woke

    # ------------------------------------------------------------------ Alpaca (Benzinga): the chart's ticker only
    def _alpaca_keys(self):
        return (self.env_get("ALPACA_API_KEY", "") or "").strip(), (self.env_get("ALPACA_SECRET_KEY", "") or "").strip()

    def alpaca_item(self, n):
        try:
            ts = datetime.fromisoformat(str(n.get("created_at")).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            ts = time.time()
        head = str(n.get("headline") or "").strip()
        hms, day = _et(ts)
        return {"id": f"bz{n.get('id')}", "src": "Benzinga", "t": ts, "et": hms, "day": day,
                "tk": [str(s).upper() for s in (n.get("symbols") or [])][:8], "head": head,
                "url": str(n.get("url") or ""), "form": "", "tags": tag(head + " " + str(n.get("summary") or ""))}

    def _alpaca_backlog(self, key, sec, sym, gen):
        start = datetime.fromtimestamp(window_start(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        q = urllib.parse.urlencode({"symbols": sym, "start": start, "limit": 50, "sort": "desc"})
        rq = urllib.request.Request(f"{ALPACA_REST}?{q}", headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        with urllib.request.urlopen(rq, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        for n in data.get("news") or []:
            self._add(self.alpaca_item(n), gen)

    def _alpaca_loop(self):
        delay = 2
        while not self.stop.is_set():
            key, sec = self._alpaca_keys()
            if not key or not sec:
                self._set("alpaca", "off - add the Alpaca keys in Settings > Keys and Discord")
                self._sleep("alpaca", 30)
                continue
            if not self.sym:
                self._set("alpaca", "waiting for a chart")
                self._sleep("alpaca", 30)
                continue
            try:
                from websockets.sync.client import connect
            except ImportError:
                self._set("alpaca", "off - the websockets package is missing (pip install websockets)")
                self._sleep("alpaca", 300)
                continue
            try:
                self._set("alpaca", "connecting")
                with connect(ALPACA_WS, open_timeout=10, close_timeout=2, max_size=4 * 1024 * 1024) as ws:
                    ws.send(json.dumps({"action": "auth", "key": key, "secret": sec}))
                    have, have_gen, keys = "", -1, (key, sec)
                    while not self.stop.is_set():
                        if self._alpaca_keys() != keys:              # new keys saved: connect again
                            break
                        sym, gen = self.sym, self.gen
                        if gen != have_gen and self.status.get("alpaca") == "live":
                            if have:
                                ws.send(json.dumps({"action": "unsubscribe", "news": [have]}))
                            if sym:
                                ws.send(json.dumps({"action": "subscribe", "news": [sym]}))
                                try:
                                    self._alpaca_backlog(key, sec, sym, gen)
                                except Exception as exc:
                                    self._warn(f"Alpaca news {sym}: {exc!r}")
                            have, have_gen = sym, gen
                        self.wake["alpaca"].clear()
                        try:
                            raw = ws.recv(timeout=0.5)               # short: a new chart is followed within half a second
                        except TimeoutError:
                            continue
                        for m in json.loads(raw) if raw else []:
                            t = m.get("T")
                            if t == "n":
                                self._add(self.alpaca_item(m), self.gen)
                            elif t == "success" and m.get("msg") == "authenticated":
                                self._set("alpaca", "live")
                                delay = 2
                            elif t == "error":
                                code, msg = m.get("code"), m.get("msg", "")
                                raise RuntimeError(f"Alpaca {code}: {msg}" + (" - is another program using these keys?"
                                                                             if code == 406 else ""))
            except Exception as exc:
                self._set("alpaca", f"reconnecting ({str(exc)[:80]})")
                self._warn(f"Alpaca news: {exc!r}")
                self._sleep("alpaca", delay)
                delay = min(60, delay * 2)

    # ------------------------------------------------------------------ SEC EDGAR: the chart's company only
    def _ua(self):
        mail = (self.env_get("SEC_CONTACT_EMAIL", "") or "").strip()
        return f"LH Short Bot {mail}" if "@" in mail else ""

    def _get(self, url, ua, timeout=10):
        rq = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            return r.read()

    def _load_ciks(self, ua):
        if self.ciks and time.time() - self.ciks_at < 12 * 3600:
            return
        data = json.loads(self._get(SEC_TICKERS, ua, 20).decode("utf-8"))
        self.ciks = {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}
        self.ciks_at = time.time()

    def parse_submissions(self, data, sym, cik, since):
        """data.sec.gov submissions JSON -> items for filings accepted after `since` (epoch)."""
        rec = (data.get("filings") or {}).get("recent") or {}
        forms = rec.get("form") or []
        out = []
        for i, form in enumerate(forms):
            acc_t = str((rec.get("acceptanceDateTime") or [""] * len(forms))[i] or "")
            try:
                ts = datetime.fromisoformat(acc_t.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if ts < since:
                break                                    # newest first: the rest is older
            acc = str(rec["accessionNumber"][i])
            doc = str((rec.get("primaryDocument") or [""] * len(forms))[i] or "")
            desc = str((rec.get("primaryDocDescription") or [""] * len(forms))[i] or "")
            items = str((rec.get("items") or [""] * len(forms))[i] or "")
            names = [f"{x} {ITEMS_8K[x]}" for x in items.split(",") if x.strip() in ITEMS_8K]
            head = f"{form} filed" + (f" - {', '.join(names)}" if names else (f" - {desc}" if desc and desc.upper() != form else ""))
            hms, day = _et(ts)
            out.append({"id": "sec" + acc, "src": "SEC", "t": ts, "et": hms, "day": day, "tk": [sym], "head": head,
                        "url": SEC_DOC.format(cik, acc.replace("-", ""), doc) if doc else "", "form": form,
                        "tags": tag(head + " " + " ".join(f"Item {x}" for x in items.split(",")), form)})
        return out

    def _sec_loop(self):
        while not self.stop.is_set():
            ua = self._ua()
            if not ua:
                self._set("sec", "off - add your contact e-mail for the SEC in Settings > Keys and Discord")
                self._sleep("sec", 30)
                continue
            sym, gen = self.sym, self.gen
            if not sym:
                self._set("sec", "waiting for a chart")
                self._sleep("sec", 30)
                continue
            try:
                self._load_ciks(ua)
                cik = self.ciks.get(sym) or self.ciks.get(sym.replace(".", "-"))
                if cik is None:
                    self._set("sec", f"{sym} has no SEC filings (not a US filer)")
                    self._sleep("sec", 60)
                    continue
                data = json.loads(self._get(SEC_SUBMISSIONS.format(cik), ua).decode("utf-8"))
                for it in reversed(self.parse_submissions(data, sym, cik, window_start())):
                    self._add(it, gen)
                self._set("sec", "live")
                self._sleep("sec", SEC_POLL_SEC)
            except urllib.error.HTTPError as exc:
                self._set("sec", f"SEC answered {exc.code}" + (" - check the contact e-mail" if exc.code == 403 else ""))
                self._sleep("sec", 60 if exc.code in (403, 429) else 15)
            except Exception as exc:
                self._set("sec", f"retrying ({str(exc)[:60]})")
                self._sleep("sec", 15)
